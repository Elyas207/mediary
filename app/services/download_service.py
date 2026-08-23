"""Glue between the download engine, the organiser and the library.

When a worker finishes, this service decides where the file belongs, moves it
there, records it in SQLite and reports the outcome. It is the only place that
knows the whole post-download story.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.config.settings import Settings
from app.downloader.manager import DownloadManager, DownloadResult
from app.models.category import KIND_AUDIO, KIND_VIDEO
from app.models.download import DownloadOptions, DownloadStatus, DownloadTask, MediaInfo
from app.models.media import MediaItem, kind_from_container
from app.services.library_service import DuplicateMatch, LibraryService
from app.services.organization_service import OrganizationError, OrganizationService
from app.utils.logging import get_logger

log = get_logger("download_service")


class DownloadService(QObject):
    """Owns the post-download pipeline: organise -> index -> notify."""

    #: Emitted once an item is fully in the library.
    item_added = Signal(object)          # MediaItem
    #: Emitted whenever the library content changed in any way.
    library_changed = Signal()
    #: Emitted with a short user-facing sentence for the status bar / toast.
    notice = Signal(str, str)            # level, message

    def __init__(
        self,
        settings: Settings,
        manager: DownloadManager,
        library: LibraryService,
        organizer: OrganizationService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._manager = manager
        self._library = library
        self._organizer = organizer
        self._replace_paths: dict = {}

        manager.task_completed.connect(self._on_task_completed)
        manager.task_failed.connect(self._on_task_failed)

    # ------------------------------------------------------------------
    # Queueing
    # ------------------------------------------------------------------

    def queue(
        self,
        url: str,
        options: DownloadOptions,
        info: MediaInfo | None = None,
        *,
        replace_path: str = "",
        start: bool = True,
    ) -> DownloadTask:
        """Add a download. ``start=False`` registers it without running it."""
        task = self._manager.enqueue(url, options, info, start=start)
        if replace_path:
            self._replace_paths[task.id] = replace_path
        return task

    def check_duplicate(self, url: str, info: MediaInfo | None) -> DuplicateMatch | None:
        """Look for an existing library entry matching an incoming download."""
        return self._library.find_duplicate(
            source_url=url,
            platform=info.platform if info else "",
            platform_id=info.platform_id if info else "",
        )

    # ------------------------------------------------------------------
    # Completion pipeline
    # ------------------------------------------------------------------

    @Slot(object, object)
    def _on_task_completed(self, task: DownloadTask, result: DownloadResult) -> None:
        try:
            item = self._finalise(task, result)
        except OrganizationError as exc:
            log.error("Could not organise %s: %s", task.url, exc)
            self._manager.mark_failed(task, str(exc), "")
            self._record_history(task, DownloadStatus.FAILED.value, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - the queue must keep running
            log.exception("Unexpected failure finalising %s", task.url)
            self._manager.mark_failed(
                task, "The file downloaded but could not be added to your library.", str(exc)
            )
            self._record_history(task, DownloadStatus.FAILED.value, str(exc))
            return

        self._manager.mark_complete(task, str(item.file_path if item else ""), item.id if item else None)
        self._record_history(task, DownloadStatus.COMPLETE.value, "", item.id if item else None)
        if item is not None:
            self.item_added.emit(item)
            self.library_changed.emit()

    def _finalise(self, task: DownloadTask, result: DownloadResult) -> MediaItem | None:
        settings = self._settings
        info = result.info or task.info or MediaInfo(url=task.url)
        options = task.options
        source = Path(result.file_path)
        extension = source.suffix.lstrip(".").lower()

        # -- 1. Decide the destination ---------------------------------
        replace_path = self._replace_paths.pop(task.id, "")
        if settings.auto_organize:
            destination = self._organizer.destination_for(
                title=info.title or source.stem,
                extension=extension,
                category=options.category,
                creator=info.creator,
                platform=info.platform,
                quality=options.quality_label(),
                media_id=info.platform_id,
                upload_date=info.upload_date,
            )
        else:
            folder = Path(settings.library_root).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            filename = self._organizer.build_filename(
                title=info.title or source.stem,
                extension=extension,
                creator=info.creator,
                platform=info.platform,
                category=options.category,
                quality=options.quality_label(),
                media_id=info.platform_id,
                upload_date=info.upload_date,
            )
            from app.utils.filenames import unique_path

            destination = unique_path(folder / filename)

        if replace_path:
            destination = Path(replace_path)

        # -- 2. Move it -------------------------------------------------
        final_path = self._organizer.place(source, destination, replace=bool(replace_path))

        # -- 3. Thumbnail ----------------------------------------------
        thumbnail_path = ""
        if result.thumbnail is not None:
            source_thumb = Path(result.thumbnail)
            if _is_in_cache(source_thumb):
                # Already fetched into the thumbnail cache - no need to copy it
                # to a second name and then delete the first.
                thumbnail_path = str(source_thumb)
            else:
                key = f"{info.platform or 'media'}-{info.platform_id or task.id[:12]}"
                thumbnail_path = self._organizer.store_thumbnail(source_thumb, key)
                try:
                    source_thumb.unlink(missing_ok=True)
                except OSError:
                    pass
        self._organizer.cleanup_sidecars(source)

        if not settings.auto_add_to_library:
            self.notice.emit("info", f"Saved to {final_path.parent}")
            return None

        # -- 4. Index it ------------------------------------------------
        probe = result.probe or {}
        media_kind = options.media_kind if options.media_kind in (KIND_AUDIO, KIND_VIDEO) else None
        if media_kind is None:
            media_kind = kind_from_container(extension)

        try:
            size = final_path.stat().st_size
        except OSError:
            size = 0

        item = MediaItem(
            filename=final_path.name,
            file_path=str(final_path),
            file_size=size,
            source_url=info.url or task.url,
            platform=info.platform,
            platform_id=info.platform_id,
            title=info.title or final_path.stem,
            creator=info.creator,
            upload_date=info.upload_date,
            downloaded_at=datetime.now().isoformat(timespec="seconds"),
            media_kind=media_kind,
            category=options.category,
            duration=probe.get("duration") or info.duration or 0.0,
            container=extension,
            width=probe.get("width", 0),
            height=probe.get("height", 0),
            fps=probe.get("fps", 0.0),
            video_codec=probe.get("video_codec", ""),
            audio_codec=probe.get("audio_codec", ""),
            audio_bitrate=probe.get("audio_bitrate", 0),
            sample_rate=probe.get("sample_rate", 0),
            thumbnail_path=thumbnail_path,
        )

        if replace_path:
            existing = self._library.get_by_path(str(final_path))
            if existing is not None:
                item.id = existing.id
                item.favorite = existing.favorite
                item.notes = existing.notes
                item.license_type = existing.license_type
                item.license_url = existing.license_url
                item.attribution_required = existing.attribution_required
                item.license_notes = existing.license_notes
                self._library.update(item)
                self._library.set_tags(item.id, existing.tags)
                item.tags = existing.tags
                return item

        self._library.add(item)
        return item

    @Slot(object)
    def _on_task_failed(self, task: DownloadTask) -> None:
        self._replace_paths.pop(task.id, None)
        self._record_history(task, DownloadStatus.FAILED.value, task.error)

    def _record_history(
        self,
        task: DownloadTask,
        status: str,
        error: str = "",
        media_id: int | None = None,
    ) -> None:
        try:
            self._library.record_download(
                task_id=task.id,
                url=task.url,
                title=task.display_title,
                platform=task.platform,
                category=task.options.category,
                format_label=task.options.quality_label(),
                status=status,
                error=error,
                media_id=media_id,
                started_at=task.created_at,
            )
        except Exception:  # noqa: BLE001 - history is best-effort
            log.debug("Could not write download history for %s", task.id)


def _is_in_cache(path: Path) -> bool:
    """True when a thumbnail already lives in Mediary's thumbnail cache."""
    from app.utils.paths import thumbnails_dir

    try:
        return path.resolve().parent == thumbnails_dir().resolve()
    except OSError:
        return False
