"""Background thumbnail fetching.

Preview images are fetched off the GUI thread and cached on disk, so analysing
a batch of ten URLs never stalls the interface. Nothing here uploads anything -
it is a plain HTTP GET of the artwork the extractor already pointed at.
"""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from app.utils.logging import get_logger
from app.utils.paths import thumbnails_dir

log = get_logger("thumbnails")

_TIMEOUT = 12
_MAX_BYTES = 8 * 1024 * 1024
_USER_AGENT = "Mediary/1.0"

_pool: QThreadPool | None = None


def _thread_pool() -> QThreadPool:
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(4)
    return _pool


def cache_path_for(url: str, key: str = "") -> Path:
    """Deterministic on-disk location for a remote thumbnail."""
    digest = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:16]
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".jpg"
    stem = f"{key}-{digest}" if key else digest
    safe_stem = "".join(c for c in stem if c.isalnum() or c in "-_")[:60] or digest
    return thumbnails_dir() / f"{safe_stem}{suffix}"


class _Signals(QObject):
    done = Signal(str)


def fetch_thumbnail_sync(url: str, key: str = "") -> str:
    """Download a thumbnail on the *calling* thread; returns "" on any failure.

    Only ever call this from a worker thread - it performs blocking network I/O.
    """
    if not url:
        return ""
    target = cache_path_for(url, key)
    if target.is_file() and target.stat().st_size > 0:
        return str(target)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if content_type and not content_type.startswith("image/"):
                raise ValueError(f"unexpected content type {content_type!r}")
            payload = response.read(_MAX_BYTES + 1)
        if len(payload) > _MAX_BYTES:
            raise ValueError("thumbnail exceeds the size limit")
        if not payload:
            raise ValueError("empty response")

        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".part")
        temp.write_bytes(payload)
        temp.replace(target)
        return str(target)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        log.debug("Thumbnail fetch failed for %s: %s", url, exc)
    except Exception as exc:  # noqa: BLE001 - never take a worker down
        log.debug("Unexpected thumbnail failure: %s", exc)
    return ""


class _FetchWorker(QRunnable):
    def __init__(self, url: str, target: Path) -> None:
        super().__init__()
        self.url = url
        self.target = target
        self.signals = _Signals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.done.emit(fetch_thumbnail_sync(self.url))


def fetch_thumbnail(url: str, key: str, callback, owner: QObject | None = None) -> None:
    """Fetch ``url`` into the cache and hand the local path to ``callback``.

    Calls back immediately with the cached path when the image is already on
    disk. ``callback`` always runs on the GUI thread.
    """
    if not url:
        callback("")
        return

    target = cache_path_for(url, key)
    if target.is_file() and target.stat().st_size > 0:
        callback(str(target))
        return

    worker = _FetchWorker(url, target)
    if owner is not None:
        # Keep the signal object alive for as long as the requester exists.
        worker.signals.setParent(owner)
    worker.signals.done.connect(callback)
    _thread_pool().start(worker)


def shutdown(timeout_ms: int = 2000) -> None:
    if _pool is not None:
        _pool.waitForDone(timeout_ms)
