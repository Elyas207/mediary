"""Turning a freshly downloaded file into an organised library asset.

Responsibilities: work out the destination folder for a category, build a clean
filename from metadata, move the file there without ever overwriting anything,
and keep a local thumbnail alongside it.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from app.config.settings import Settings
from app.models.category import (
    BUILTIN_CATEGORIES,
    Category,
    resolve_category,
)
from app.models.download import DownloadOptions
from app.utils.filenames import render_template, sanitize_component, unique_path
from app.utils.logging import get_logger
from app.utils.paths import thumbnails_dir

log = get_logger("organize")


class OrganizationError(Exception):
    """A file could not be placed in the library."""


class OrganizationService:
    """Computes library paths and moves files into them."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def root(self) -> Path:
        return Path(self._settings.library_root).expanduser()

    # ------------------------------------------------------------------
    # Folder layout
    # ------------------------------------------------------------------

    def category_dir(self, category_name: str) -> Path:
        """Absolute folder for a category, e.g. ``<root>/Audio/Sound Effects``."""
        category = self._resolve(category_name)
        target = self.root
        for part in category.relative_parts():
            target = target / sanitize_component(part, fallback="Media")
        return target

    def _resolve(self, category_name: str) -> Category:
        custom = {
            name: {"kind": "other"} for name in (self._settings.custom_categories or [])
        }
        return resolve_category(category_name, custom)

    def ensure_library_tree(self) -> list:
        """Create the default folder structure. Returns the folders created."""
        created: list = []
        root = self.root
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OrganizationError(f"Could not create the library folder: {exc}") from exc

        for category in BUILTIN_CATEGORIES:
            folder = self.category_dir(category.name)
            if not folder.exists():
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    created.append(folder)
                except OSError as exc:
                    log.warning("Could not create %s: %s", folder, exc)
        return created

    def ensure_writable(self) -> tuple:
        """Check the library root can actually be written to."""
        root = self.root
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".mediary-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True, ""
        except OSError as exc:
            return False, str(exc.strerror or exc)

    # ------------------------------------------------------------------
    # Naming
    # ------------------------------------------------------------------

    def build_filename(
        self,
        *,
        title: str,
        extension: str,
        creator: str = "",
        platform: str = "",
        category: str = "",
        quality: str = "",
        media_id: str = "",
        upload_date: str = "",
        template: str | None = None,
    ) -> str:
        """Render the configured filename template into a safe filename."""
        values = {
            "title": title or "Untitled",
            "creator": creator,
            "platform": platform,
            "category": category,
            "quality": quality,
            "ext": (extension or "").lstrip("."),
            "date": _format_date_token(upload_date),
            "id": media_id,
        }
        stem = render_template(template or self._settings.filename_template, values)
        suffix = (extension or "").strip().lower()
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        return f"{stem}{suffix}"

    def destination_for(
        self,
        *,
        title: str,
        extension: str,
        category: str,
        creator: str = "",
        platform: str = "",
        quality: str = "",
        media_id: str = "",
        upload_date: str = "",
    ) -> Path:
        """Full, collision-free destination path for a new asset."""
        folder = self.category_dir(category)
        filename = self.build_filename(
            title=title,
            extension=extension,
            creator=creator,
            platform=platform,
            category=category,
            quality=quality,
            media_id=media_id,
            upload_date=upload_date,
        )
        return unique_path(folder / filename)

    def preview_destination(self, options: DownloadOptions, title: str) -> Path:
        """Where a download *would* land - used by the Download screen preview."""
        return self.category_dir(options.category) / self.build_filename(
            title=title,
            extension=options.target_extension,
            category=options.category,
            quality=options.quality_label(),
        )

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------

    def place(self, source: Path, destination: Path, *, replace: bool = False) -> Path:
        """Move ``source`` to ``destination``, returning the final path.

        Falls back to copy+delete when the two are on different volumes, which
        is common when the library lives on an external drive.
        """
        source = Path(source)
        destination = Path(destination)
        if not source.is_file():
            raise OrganizationError(f"The downloaded file is missing: {source.name}")

        if source.resolve() == self._safe_resolve(destination):
            return source

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OrganizationError(f"Could not create {destination.parent}: {exc}") from exc

        if destination.exists():
            if replace:
                try:
                    destination.unlink()
                except OSError as exc:
                    raise OrganizationError(
                        f"Could not replace the existing file: {exc}"
                    ) from exc
            else:
                destination = unique_path(destination)

        try:
            shutil.move(str(source), str(destination))
        except OSError as exc:
            raise OrganizationError(f"Could not move the file into the library: {exc}") from exc

        log.info("Organised %s -> %s", source.name, destination)
        return destination

    @staticmethod
    def _safe_resolve(path: Path) -> Path:
        try:
            return path.resolve()
        except OSError:
            return path

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------

    def store_thumbnail(self, source: Path, key: str) -> str:
        """Copy a downloaded thumbnail into the app cache. Returns its path."""
        source = Path(source)
        if not source.is_file():
            return ""
        try:
            target_dir = thumbnails_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            suffix = source.suffix.lower() or ".jpg"
            target = target_dir / f"{sanitize_component(key, fallback='thumb')}{suffix}"
            shutil.copy2(source, target)
            return str(target)
        except OSError as exc:
            log.debug("Could not cache thumbnail %s: %s", source, exc)
            return ""

    @staticmethod
    def find_sidecar_thumbnail(media_path: Path) -> Path | None:
        """Locate the image yt-dlp wrote next to the media file."""
        media_path = Path(media_path)
        directory = media_path.parent
        stem = media_path.stem
        for suffix in (".jpg", ".jpeg", ".png", ".webp"):
            candidate = directory / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate
        # yt-dlp sometimes keeps the pre-conversion extension in the stem.
        for candidate in directory.glob(f"{glob_escape(stem)}.*"):
            if candidate.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                return candidate
        return None

    @staticmethod
    def cleanup_sidecars(media_path: Path, *, keep: Path | None = None) -> None:
        """Remove leftover thumbnails and part files next to a finished download."""
        media_path = Path(media_path)
        directory = media_path.parent
        stem = media_path.stem
        keep_resolved = str(keep) if keep else ""
        for candidate in directory.glob(f"{glob_escape(stem)}.*"):
            if candidate == media_path or str(candidate) == keep_resolved:
                continue
            if candidate.suffix.lower() in (
                ".jpg", ".jpeg", ".png", ".webp", ".part", ".ytdl", ".temp",
            ):
                try:
                    candidate.unlink()
                except OSError:
                    pass


def glob_escape(text: str) -> str:
    """Escape glob metacharacters so titles with ``[`` or ``*`` still match."""
    return "".join("[" + c + "]" if c in "*?[]" else c for c in text)


def _format_date_token(upload_date: str) -> str:
    """``"20250104"`` -> ``"2025-01-04"``; empty stays empty."""
    text = (upload_date or "").strip()
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            return text
    return text
