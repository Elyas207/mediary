"""Rescan Library: reconcile the database with what is actually on disk.

People move, rename and delete files outside the app. Rescan makes Mediary
recover from that instead of showing broken entries forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config.settings import Settings
from app.media.ffmpeg import get_ffmpeg, probe_media
from app.models.category import BUILTIN_CATEGORIES, KIND_OTHER
from app.models.media import kind_from_container
from app.services.library_service import LibraryService
from app.services.organization_service import OrganizationService
from app.utils.logging import get_logger

log = get_logger("rescan")

#: File types Mediary will index when it finds them loose in the library.
MEDIA_EXTENSIONS = frozenset(
    {
        "mp4", "mkv", "webm", "mov", "avi", "m4v", "flv", "wmv", "mpg", "mpeg", "ts",
        "mp3", "m4a", "wav", "flac", "aac", "ogg", "opus", "aiff", "wma",
    }
)

#: Never walk into these - they are Mediary's own or the OS's bookkeeping.
SKIP_DIRS = frozenset({".mediary", ".git", "__pycache__", ".Trash", "$RECYCLE.BIN", "System Volume Information"})

#: Cap the probe work so a rescan of a huge library stays responsive.
MAX_PROBES = 400


@dataclass
class RescanResult:
    """What a rescan changed."""

    scanned: int = 0
    imported: int = 0
    missing: int = 0
    recovered: int = 0
    relocated: int = 0
    resized: int = 0

    def summary(self) -> str:
        bits = []
        if self.imported:
            bits.append(f"{self.imported} new file{'s' if self.imported != 1 else ''} indexed")
        if self.relocated:
            bits.append(f"{self.relocated} relocated")
        if self.recovered:
            bits.append(f"{self.recovered} recovered")
        if self.missing:
            bits.append(f"{self.missing} now missing")
        if self.resized:
            bits.append(f"{self.resized} size{'s' if self.resized != 1 else ''} updated")
        if not bits:
            return f"Everything is up to date ({self.scanned} files checked)."
        return " · ".join(bits)


class RescanService:
    """Walks the library root and reconciles it with the index."""

    def __init__(
        self,
        settings: Settings,
        library: LibraryService,
        organizer: OrganizationService | None = None,
    ) -> None:
        self._settings = settings
        self._library = library
        self._organizer = organizer or OrganizationService(settings)

    def run(self, *, import_new: bool = True, progress=None) -> RescanResult:
        result = RescanResult()
        root = self._settings.root_path

        # 1. Flag entries whose file vanished, un-flag ones that came back.
        verification = self._library.verify_files()
        result.missing = verification["missing"]
        result.recovered = verification["recovered"]
        result.resized = verification["resized"]

        if not root.is_dir():
            log.warning("Library root %s does not exist; skipping the disk walk", root)
            return result

        # 2. Try to re-point anything still missing at a same-named file.
        result.relocated = self._library.relocate_missing([root])
        if result.relocated:
            result.missing = max(0, result.missing - result.relocated)

        # 3. Index media that appeared in the library folder from elsewhere.
        known = self._known_paths()
        probes_left = MAX_PROBES
        ffprobe = get_ffmpeg(self._settings.ffmpeg_path).ffprobe_path

        for path in self._walk(root):
            result.scanned += 1
            if progress is not None and result.scanned % 50 == 0:
                progress(result.scanned)
            if not import_new:
                continue
            resolved = str(path)
            if resolved in known or resolved.lower() in known:
                continue

            category, kind = self._classify(path, root)
            probe = None
            if ffprobe and probes_left > 0:
                probe = probe_media(path, ffprobe)
                probes_left -= 1
            media_id = self._library.import_file(
                path, category=category, media_kind=kind, probe=probe
            )
            if media_id is not None:
                result.imported += 1
                known.add(resolved)

        log.info("Rescan complete: %s", result.summary())
        return result

    # ------------------------------------------------------------------

    def _known_paths(self) -> set:
        rows = self._library.db.query("SELECT file_path FROM media")
        paths = set()
        for row in rows:
            paths.add(row[0])
            paths.add(str(row[0]).lower())
        return paths

    def _walk(self, root: Path):
        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                entries = list(directory.iterdir())
            except (OSError, PermissionError):
                continue
            for entry in entries:
                try:
                    if entry.is_dir():
                        if entry.name in SKIP_DIRS or entry.name.startswith("."):
                            continue
                        stack.append(entry)
                    elif entry.is_file():
                        if entry.suffix.lstrip(".").lower() in MEDIA_EXTENSIONS:
                            yield entry
                except OSError:
                    continue

    def _classify(self, path: Path, root: Path) -> tuple:
        """Infer a category from where the file sits under the library root."""
        try:
            relative = path.relative_to(root)
        except ValueError:
            return "Other", kind_from_container(path.suffix)

        folder = "/".join(relative.parts[:-1])
        for category in BUILTIN_CATEGORIES:
            if folder == category.folder or folder.startswith(category.folder + "/"):
                return category.name, category.kind

        kind = kind_from_container(path.suffix)
        if kind == KIND_OTHER:
            return "Other", kind
        # A loose file in an unrecognised folder still gets a sensible home.
        return ("Video" if kind == "video" else "Music"), kind
