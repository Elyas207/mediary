"""The download engine: a Qt-signalling queue over a bounded worker pool.

Design notes
------------
* Every yt-dlp call happens on a ``QThreadPool`` worker, never on the GUI thread.
* Concurrency is bounded by a ConcurrencyLimiter rather than the pool size, so
  the limit can change at runtime without restarting the pool.
* Workers own no Qt widgets and touch no database rows; they emit signals and
  the services on the GUI side do the persisting.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from app.config.settings import Settings
from app.downloader import ytdlp_adapter as adapter
from app.downloader.ytdlp_adapter import (
    DownloadCancelled,
    ExtractionError,
    RuntimeConfig,
)
from app.media.ffmpeg import get_ffmpeg, probe_media
from app.models.download import (
    DownloadOptions,
    DownloadStatus,
    DownloadTask,
    MediaInfo,
    Progress,
)
from app.utils.logging import get_logger
from app.utils.paths import cache_dir

log = get_logger("downloader")


class DownloadResult:
    """What a worker produces on success."""

    def __init__(
        self,
        task_id: str,
        file_path: Path,
        info: MediaInfo,
        probe: dict,
        thumbnail: Path | None,
    ) -> None:
        self.task_id = task_id
        self.file_path = file_path
        self.info = info
        self.probe = probe
        self.thumbnail = thumbnail


class WorkerSignals(QObject):
    """Signals emitted from a worker thread; delivered on the GUI thread."""

    progress = Signal(str, object)          # task_id, Progress
    stage = Signal(str, object, str)        # task_id, DownloadStatus, note
    finished = Signal(str, object)          # task_id, DownloadResult
    failed = Signal(str, str, str, str)     # task_id, category, message, detail
    cancelled = Signal(str)                 # task_id


class AnalysisSignals(QObject):
    analyzed = Signal(str, object)          # request_id, MediaInfo
    failed = Signal(str, str, str, str)     # request_id, category, message, detail


class ConcurrencyLimiter:
    """Caps how many downloads run at once, adjustable while work is in flight.

    A plain semaphore cannot have its count *lowered* without parking a thread
    on ``acquire()`` for every permit removed, which leaks a thread each time
    the user turns the setting down. A condition variable over an explicit
    counter reads the current limit on every wake-up instead, so a change takes
    effect immediately and costs nothing.
    """

    def __init__(self, limit: int) -> None:
        self._condition = threading.Condition()
        self._limit = max(1, int(limit))
        self._running = 0

    @property
    def limit(self) -> int:
        with self._condition:
            return self._limit

    def set_limit(self, value: int) -> None:
        with self._condition:
            self._limit = max(1, min(8, int(value)))
            self._condition.notify_all()

    def acquire(self, token: _CancelToken | None = None) -> bool:
        """Wait for a free slot. Returns False if the task was cancelled first."""
        with self._condition:
            while self._running >= self._limit:
                if token is not None and token.cancelled:
                    return False
                # A short timeout keeps cancellation responsive even when no
                # other worker finishes.
                self._condition.wait(0.25)
            if token is not None and token.cancelled:
                return False
            self._running += 1
            return True

    def release(self) -> None:
        with self._condition:
            self._running = max(0, self._running - 1)
            self._condition.notify()

    @property
    def running(self) -> int:
        with self._condition:
            return self._running


class _CancelToken:
    """Thread-safe cancel/pause flag shared with a running worker."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._paused = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()


class AnalysisWorker(QRunnable):
    """Fetches metadata for one URL without downloading anything."""

    def __init__(self, request_id: str, url: str, config: RuntimeConfig) -> None:
        super().__init__()
        self.request_id = request_id
        self.url = url
        self.config = config
        self.signals = AnalysisSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:  # pragma: no cover - exercised through the UI
        try:
            info = analyze_url(self.url, self.config)
        except ExtractionError as exc:
            self.signals.failed.emit(self.request_id, exc.category, exc.message, exc.detail)
        except Exception as exc:  # noqa: BLE001 - worker must never escape
            category, message, detail = adapter.translate_error(str(exc))
            log.exception("Unexpected analysis failure for %s", self.url)
            self.signals.failed.emit(self.request_id, category, message, detail)
        else:
            self.signals.analyzed.emit(self.request_id, info)


def analyze_url(url: str, config: RuntimeConfig | None = None) -> MediaInfo:
    """Probe a URL with yt-dlp and return normalised metadata.

    Raises :class:`ExtractionError` with a human-readable message on failure.
    """
    import yt_dlp

    options = adapter.analysis_options(config)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            payload = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        category, message, detail = adapter.translate_error(str(exc))
        raise ExtractionError(message, detail, category=category) from exc
    except Exception as exc:  # noqa: BLE001
        category, message, detail = adapter.translate_error(str(exc))
        raise ExtractionError(message, detail, category=category) from exc

    if not payload:
        raise ExtractionError(
            "Mediary could not find downloadable media at that URL.",
            "yt-dlp returned no information.",
            category="unsupported",
        )
    return adapter.info_from_dict(payload, url)


class DownloadWorker(QRunnable):
    """Downloads one task into a staging folder and reports progress."""

    def __init__(
        self,
        task: DownloadTask,
        staging_dir: Path,
        config: RuntimeConfig,
        token: _CancelToken,
        *,
        has_ffmpeg: bool,
        slots: ConcurrencyLimiter,
    ) -> None:
        super().__init__()
        self.task = task
        self.staging_dir = Path(staging_dir)
        self.config = config
        self.token = token
        self.has_ffmpeg = has_ffmpeg
        self.slots = slots
        self.signals = WorkerSignals()
        self.setAutoDelete(True)
        self._last_emit = 0.0
        self._finished_path: Path | None = None

    # -- yt-dlp hooks -----------------------------------------------------

    def _check_cancel(self) -> None:
        while self.token.paused and not self.token.cancelled:
            time.sleep(0.2)
        if self.token.cancelled:
            raise DownloadCancelled()

    def _on_progress(self, payload: dict) -> None:
        self._check_cancel()
        status = payload.get("status")
        if status == "downloading":
            now = time.monotonic()
            # Throttle to ~8 updates/second; the UI cannot use more and the
            # signal queue would otherwise dominate the event loop.
            if now - self._last_emit < 0.12:
                return
            self._last_emit = now
            progress = Progress(
                downloaded_bytes=int(payload.get("downloaded_bytes") or 0),
                total_bytes=int(
                    payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
                ),
                speed=float(payload.get("speed") or 0.0),
                eta=int(payload.get("eta") or 0),
                fragment_index=int(payload.get("fragment_index") or 0),
                fragment_count=int(payload.get("fragment_count") or 0),
            )
            self.signals.progress.emit(self.task.id, progress)
        elif status == "finished":
            filename = payload.get("filename")
            if filename:
                self._finished_path = Path(filename)
            self.signals.stage.emit(
                self.task.id, DownloadStatus.PROCESSING, "Processing media"
            )

    def _on_postprocessor(self, payload: dict) -> None:
        self._check_cancel()
        if payload.get("status") != "started":
            info = payload.get("info_dict") or {}
            path = info.get("filepath") or info.get("_filename")
            if path:
                self._finished_path = Path(path)
            return
        name = str(payload.get("postprocessor") or "")
        notes = {
            "FFmpegExtractAudio": "Extracting audio",
            "FFmpegVideoRemuxer": "Remuxing video",
            "FFmpegVideoConvertor": "Converting video",
            "FFmpegMerger": "Merging streams",
            "FFmpegMetadata": "Writing metadata",
            "EmbedThumbnail": "Embedding artwork",
            "MoveFiles": "Finalising",
        }
        note = notes.get(name, "Processing media")
        self.signals.stage.emit(self.task.id, DownloadStatus.PROCESSING, note)

    # -- Execution --------------------------------------------------------

    @Slot()
    def run(self) -> None:  # pragma: no cover - exercised through the UI
        acquired = False
        try:
            # Wait here rather than in the pool so the queue order is honoured
            # and the concurrency limit can be changed while items are waiting.
            if not self.slots.acquire(self.token):
                self.signals.cancelled.emit(self.task.id)
                return
            acquired = True

            if self.token.cancelled:
                self.signals.cancelled.emit(self.task.id)
                return

            self._execute()
        except DownloadCancelled:
            self._cleanup_partial()
            self.signals.cancelled.emit(self.task.id)
        except ExtractionError as exc:
            self.signals.failed.emit(self.task.id, exc.category, exc.message, exc.detail)
        except Exception as exc:  # noqa: BLE001
            category, message, detail = adapter.translate_error(str(exc))
            log.exception("Download failed for %s", self.task.url)
            self.signals.failed.emit(self.task.id, category, message, detail)
        finally:
            if acquired:
                self.slots.release()

    def _execute(self) -> None:
        import yt_dlp

        task = self.task
        info = task.info

        if info is None:
            self.signals.stage.emit(task.id, DownloadStatus.ANALYZING, "Reading metadata")
            info = analyze_url(task.url, self.config)
            task.info = info
            self._check_cancel()

        self.signals.stage.emit(task.id, DownloadStatus.DOWNLOADING, "")

        self.staging_dir.mkdir(parents=True, exist_ok=True)
        options = adapter.download_options(
            task.options,
            self.staging_dir,
            config=self.config,
            has_ffmpeg=self.has_ffmpeg,
            progress_hook=self._on_progress,
            postprocessor_hook=self._on_postprocessor,
            outtmpl_stem=f"mediary-{task.id[:12]}",
        )

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                payload = ydl.extract_info(task.url, download=True)
        except DownloadCancelled:
            raise
        except yt_dlp.utils.DownloadError as exc:
            if self.token.cancelled:
                raise DownloadCancelled() from exc
            category, message, detail = adapter.translate_error(str(exc))
            raise ExtractionError(message, detail, category=category) from exc

        self._check_cancel()

        if payload and payload.get("_type") == "playlist" and payload.get("entries"):
            entries = [e for e in payload["entries"] if e]
            payload = entries[0] if entries else payload

        final_path = self._resolve_output(payload)
        if final_path is None or not final_path.is_file():
            raise ExtractionError(
                "The download finished but Mediary could not find the resulting file.",
                f"Searched in {self.staging_dir}",
                category="missing_output",
            )

        # Refresh the info with what was actually downloaded (titles and
        # uploaders are sometimes only resolved at download time), keeping the
        # artwork we may already have cached during analysis.
        if payload:
            cached_thumbnail = info.thumbnail_path if info else ""
            info = adapter.info_from_dict(payload, task.url)
            info.thumbnail_path = cached_thumbnail or info.thumbnail_path
            task.info = info

        self.signals.stage.emit(task.id, DownloadStatus.ORGANIZING, "Organising")
        probe = probe_media(final_path, get_ffmpeg().ffprobe_path) if self.has_ffmpeg else {}

        thumbnail = _find_thumbnail(self.staging_dir, final_path)
        if thumbnail is None:
            # Not every extractor writes a sidecar image. Fetching it here (on
            # the worker thread) means the library still gets artwork.
            thumbnail = self._fetch_remote_thumbnail(info)

        self.signals.finished.emit(
            task.id, DownloadResult(task.id, final_path, info, probe, thumbnail)
        )

    def _resolve_output(self, payload: dict | None) -> Path | None:
        """Work out which file yt-dlp actually produced."""
        candidates: list = []
        if payload:
            for key in ("filepath", "_filename"):
                value = payload.get(key)
                if value:
                    candidates.append(Path(value))
            for entry in payload.get("requested_downloads") or []:
                value = (entry or {}).get("filepath")
                if value:
                    candidates.append(Path(value))
        if self._finished_path is not None:
            candidates.append(self._finished_path)

        for candidate in candidates:
            if candidate.is_file():
                return candidate

        # Post-processing changes the extension, so fall back to the newest
        # media file in staging that carries our task stem.
        stem = f"mediary-{self.task.id[:12]}"
        media_files = [
            path
            for path in self.staging_dir.glob(f"{stem}*")
            if path.is_file()
            and path.suffix.lower()
            not in (".jpg", ".jpeg", ".png", ".webp", ".part", ".ytdl", ".temp", ".json")
        ]
        if media_files:
            return max(media_files, key=lambda p: p.stat().st_mtime)
        return None

    def _fetch_remote_thumbnail(self, info: MediaInfo | None) -> Path | None:
        """Last-resort artwork: pull the extractor's thumbnail URL directly."""
        if info is None:
            return None
        if info.thumbnail_path and Path(info.thumbnail_path).is_file():
            return Path(info.thumbnail_path)
        if not info.thumbnail_url:
            return None
        from app.services.thumbnail_service import fetch_thumbnail_sync

        path = fetch_thumbnail_sync(
            info.thumbnail_url, info.platform_id or self.task.id[:12]
        )
        return Path(path) if path else None

    def _cleanup_partial(self) -> None:
        stem = f"mediary-{self.task.id[:12]}"
        try:
            for path in self.staging_dir.glob(f"{stem}*"):
                try:
                    path.unlink()
                except OSError:
                    pass
        except OSError:
            pass


def _find_thumbnail(staging_dir: Path, media_path: Path) -> Path | None:
    for candidate in staging_dir.glob(f"{media_path.stem}.*"):
        if candidate.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return candidate
    return None


class DownloadManager(QObject):
    """Owns the queue, the worker pool and the concurrency limit."""

    task_added = Signal(object)                    # DownloadTask
    task_updated = Signal(object)                  # DownloadTask
    task_removed = Signal(str)                     # task_id
    task_completed = Signal(object, object)        # DownloadTask, DownloadResult
    task_failed = Signal(object)                   # DownloadTask
    queue_changed = Signal()

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._tasks: dict = {}
        self._order: list = []
        self._tokens: dict = {}
        self._pool = QThreadPool(self)
        # Headroom above the concurrency limit so a paused worker (which holds
        # a thread while it waits) cannot starve the queue.
        self._pool.setMaxThreadCount(16)
        self._slots = ConcurrencyLimiter(settings.concurrent_downloads)
        self._staging = cache_dir() / "downloads"
        self._lock = threading.RLock()

    # -- Queue introspection ---------------------------------------------

    @property
    def tasks(self) -> list:
        with self._lock:
            return [self._tasks[tid] for tid in self._order if tid in self._tasks]

    def task(self, task_id: str) -> DownloadTask | None:
        return self._tasks.get(task_id)

    def counts(self) -> dict:
        counts = {"active": 0, "pending": 0, "complete": 0, "failed": 0, "total": 0}
        for task in self.tasks:
            counts["total"] += 1
            if task.status.is_active:
                counts["active"] += 1
            elif task.status.is_pending:
                counts["pending"] += 1
            elif task.status == DownloadStatus.COMPLETE:
                counts["complete"] += 1
            elif task.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                counts["failed"] += 1
        return counts

    @property
    def has_work(self) -> bool:
        return any(t.status.is_active or t.status.is_pending for t in self.tasks)

    # -- Configuration ----------------------------------------------------

    def set_concurrency(self, value: int) -> None:
        """Change the limit while the queue is running.

        Raising it lets waiting workers start immediately; lowering it does not
        interrupt anything already running, it just stops new work starting
        until the count falls back under the new limit.
        """
        self._slots.set_limit(value)

    @property
    def concurrency(self) -> int:
        return self._slots.limit

    def _runtime_config(self) -> RuntimeConfig:
        ffmpeg = get_ffmpeg(self._settings.ffmpeg_path)
        return RuntimeConfig(
            ffmpeg_location=ffmpeg.directory if ffmpeg.available else "",
            max_speed_kbps=int(self._settings.max_speed_kbps or 0),
            retries=int(self._settings.retry_count or 0),
            socket_timeout=int(self._settings.socket_timeout or 30),
            write_thumbnail=bool(
                self._settings.write_thumbnail_files or self._settings.embed_thumbnails
            ),
        )

    # -- Analysis ---------------------------------------------------------

    def analyze(self, request_id: str, url: str, on_done, on_error) -> None:
        """Run a metadata probe off the GUI thread."""
        worker = AnalysisWorker(request_id, url, self._runtime_config())
        worker.signals.analyzed.connect(on_done)
        worker.signals.failed.connect(on_error)
        self._pool.start(worker)

    # -- Queue mutation ---------------------------------------------------

    def enqueue(
        self,
        url: str,
        options: DownloadOptions,
        info: MediaInfo | None = None,
        *,
        start: bool = True,
    ) -> DownloadTask:
        task = DownloadTask(url=url, options=options, info=info)
        with self._lock:
            self._tasks[task.id] = task
            self._order.append(task.id)
        self.task_added.emit(task)
        self.queue_changed.emit()
        if start:
            self._start(task)
        return task

    def _start(self, task: DownloadTask) -> None:
        token = _CancelToken()
        self._tokens[task.id] = token
        ffmpeg = get_ffmpeg(self._settings.ffmpeg_path)
        worker = DownloadWorker(
            task,
            self._staging,
            self._runtime_config(),
            token,
            has_ffmpeg=ffmpeg.available,
            slots=self._slots,
        )
        worker.signals.progress.connect(self._on_progress)
        worker.signals.stage.connect(self._on_stage)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.cancelled.connect(self._on_cancelled)
        task.status = DownloadStatus.QUEUED
        task.attempts += 1
        self.task_updated.emit(task)
        self._pool.start(worker)

    def pause(self, task_id: str) -> bool:
        token = self._tokens.get(task_id)
        task = self._tasks.get(task_id)
        if token is None or task is None or task.status.is_terminal:
            return False
        token.pause()
        task.status = DownloadStatus.PAUSED
        task.stage_note = "Paused"
        self.task_updated.emit(task)
        self.queue_changed.emit()
        return True

    def resume(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        token = self._tokens.get(task_id)
        if token is not None and task.status == DownloadStatus.PAUSED:
            token.resume()
            task.status = DownloadStatus.DOWNLOADING
            task.stage_note = ""
            self.task_updated.emit(task)
            self.queue_changed.emit()
            return True
        if task.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
            return self.retry(task_id)
        return False

    def cancel(self, task_id: str) -> bool:
        token = self._tokens.get(task_id)
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if token is not None:
            token.resume()   # unblock a paused worker so it can observe cancel
            token.cancel()
        if task.status.is_pending:
            # Nothing running yet - mark it immediately.
            task.status = DownloadStatus.CANCELLED
            task.stage_note = ""
            self.task_updated.emit(task)
            self.queue_changed.emit()
        return True

    def retry(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status.is_active:
            return False
        task.reset_for_retry()
        self.task_updated.emit(task)
        self._start(task)
        self.queue_changed.emit()
        return True

    def remove(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if not task.status.is_terminal:
            self.cancel(task_id)
        with self._lock:
            self._tasks.pop(task_id, None)
            self._tokens.pop(task_id, None)
            if task_id in self._order:
                self._order.remove(task_id)
        self.task_removed.emit(task_id)
        self.queue_changed.emit()
        return True

    def move(self, task_id: str, offset: int) -> bool:
        """Reorder a *pending* task within the queue."""
        with self._lock:
            if task_id not in self._order:
                return False
            index = self._order.index(task_id)
            target = max(0, min(len(self._order) - 1, index + offset))
            if target == index:
                return False
            self._order.pop(index)
            self._order.insert(target, task_id)
        self.queue_changed.emit()
        return True

    def clear_finished(self) -> int:
        removed = [t.id for t in self.tasks if t.status.is_terminal]
        for task_id in removed:
            self.remove(task_id)
        return len(removed)

    def cancel_all(self) -> None:
        for task in self.tasks:
            if not task.status.is_terminal:
                self.cancel(task.id)

    def shutdown(self, timeout_ms: int = 4000) -> None:
        self.cancel_all()
        self._pool.waitForDone(timeout_ms)

    # -- Worker callbacks (GUI thread) ------------------------------------

    @Slot(str, object)
    def _on_progress(self, task_id: str, progress: Progress) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.status == DownloadStatus.PAUSED:
            return
        task.progress = progress
        if task.status != DownloadStatus.DOWNLOADING:
            task.status = DownloadStatus.DOWNLOADING
        self.task_updated.emit(task)

    @Slot(str, object, str)
    def _on_stage(self, task_id: str, status: DownloadStatus, note: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.status.is_terminal:
            return
        if task.status == DownloadStatus.PAUSED and status == DownloadStatus.DOWNLOADING:
            return
        task.status = status
        task.stage_note = note
        self.task_updated.emit(task)
        self.queue_changed.emit()

    @Slot(str, object)
    def _on_finished(self, task_id: str, result: DownloadResult) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        self.task_completed.emit(task, result)

    @Slot(str, str, str, str)
    def _on_failed(self, task_id: str, category: str, message: str, detail: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.status = DownloadStatus.FAILED
        task.error = message
        task.error_detail = detail
        task.stage_note = category
        task.finished_at = _now()
        self.task_updated.emit(task)
        self.task_failed.emit(task)
        self.queue_changed.emit()

    @Slot(str)
    def _on_cancelled(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.status = DownloadStatus.CANCELLED
        task.stage_note = ""
        task.finished_at = _now()
        self.task_updated.emit(task)
        self.queue_changed.emit()

    def mark_complete(self, task: DownloadTask, output_path: str, media_id: int | None) -> None:
        """Called by the download service once the file is in the library."""
        task.status = DownloadStatus.COMPLETE
        task.output_path = output_path
        task.media_id = media_id
        task.stage_note = ""
        task.finished_at = _now()
        task.progress.downloaded_bytes = task.progress.total_bytes or task.progress.downloaded_bytes
        self.task_updated.emit(task)
        self.queue_changed.emit()

    def mark_failed(self, task: DownloadTask, message: str, detail: str = "") -> None:
        task.status = DownloadStatus.FAILED
        task.error = message
        task.error_detail = detail
        task.finished_at = _now()
        self.task_updated.emit(task)
        self.task_failed.emit(task)
        self.queue_changed.emit()


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
