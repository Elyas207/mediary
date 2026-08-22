"""User configuration, persisted as JSON next to the Mediary database.

Settings are a typed dataclass rather than a free-form dict: a typo in a key
raises immediately, and defaults survive upgrades that add new fields to an
existing installation.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from app.utils.logging import get_logger
from app.utils.paths import default_library_root, settings_path

log = get_logger("config")

SETTINGS_VERSION = 1

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_SYSTEM = "system"
THEMES = (THEME_SYSTEM, THEME_DARK, THEME_LIGHT)

VIEW_GRID = "grid"
VIEW_LIST = "list"


@dataclass
class Settings:
    """Every user-tunable value in Mediary."""

    version: int = SETTINGS_VERSION
    first_run_complete: bool = False

    # --- Downloads -------------------------------------------------------
    library_root: str = ""
    default_category: str = "Video"
    default_media_kind: str = "video"          # "video" | "audio"
    default_video_format: str = "mp4"          # mp4 | mkv | webm
    default_video_quality: str = "best"        # best | 2160p ... 360p
    default_audio_format: str = "mp3"          # mp3 | m4a | wav | flac
    default_audio_bitrate: str = "320"         # 128 | 192 | 256 | 320
    auto_organize: bool = True
    auto_add_to_library: bool = True
    embed_thumbnails: bool = True
    embed_metadata: bool = True
    write_thumbnail_files: bool = True
    filename_template: str = "{title}"
    duplicate_action: str = "ask"              # ask | skip | download | replace

    # --- Performance -----------------------------------------------------
    concurrent_downloads: int = 2
    max_speed_kbps: int = 0                    # 0 == unlimited
    retry_count: int = 3
    socket_timeout: int = 30

    # --- Appearance ------------------------------------------------------
    theme: str = THEME_SYSTEM
    library_view: str = VIEW_GRID
    grid_thumbnail_size: int = 200
    show_queue_panel: bool = True

    # --- Startup and background ------------------------------------------
    launch_at_startup: bool = False    # register with the OS sign-in mechanism
    start_hidden: bool = False         # go straight to the tray, no window
    close_to_tray: bool = False        # closing the window keeps Mediary running
    tray_notifications: bool = True    # desktop notification when a download ends

    # --- Tooling ---------------------------------------------------------
    ffmpeg_path: str = ""                      # empty == auto-detect
    ytdlp_auto_check_updates: bool = False

    # --- Window state ----------------------------------------------------
    window_geometry: str = ""
    window_state: str = ""
    last_view: str = "download"

    # --- Custom taxonomy -------------------------------------------------
    custom_categories: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.library_root:
            self.library_root = str(default_library_root())

    @property
    def root_path(self) -> Path:
        return Path(self.library_root).expanduser()

    @property
    def wants_tray(self) -> bool:
        """True when a setting is on that can leave Mediary with no window.

        The tray icon is derived from these rather than being a fourth toggle:
        hiding the window without somewhere to click back is never correct.
        """
        return bool(self.start_hidden or self.close_to_tray)

    def clamp(self) -> None:
        """Coerce out-of-range values that a hand-edited file might contain."""
        self.concurrent_downloads = max(1, min(8, _as_int(self.concurrent_downloads, 2)))
        self.retry_count = max(0, min(10, _as_int(self.retry_count, 3)))
        self.socket_timeout = max(5, min(300, _as_int(self.socket_timeout, 30)))
        self.max_speed_kbps = max(0, _as_int(self.max_speed_kbps, 0))
        self.grid_thumbnail_size = max(140, min(340, _as_int(self.grid_thumbnail_size, 200)))
        if self.theme not in THEMES:
            self.theme = THEME_SYSTEM
        if self.library_view not in (VIEW_GRID, VIEW_LIST):
            self.library_view = VIEW_GRID
        if self.default_media_kind not in ("video", "audio"):
            self.default_media_kind = "video"
        if self.duplicate_action not in ("ask", "skip", "download", "replace"):
            self.duplicate_action = "ask"
        if not str(self.filename_template).strip():
            self.filename_template = "{title}"
        if not isinstance(self.custom_categories, list):
            self.custom_categories = []


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


class SettingsStore:
    """Loads, validates and atomically persists :class:`Settings`."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else settings_path()
        self._settings = Settings()
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def settings(self) -> Settings:
        if not self._loaded:
            self.load()
        return self._settings

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self.settings, key, default)

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        if not hasattr(self.settings, key):
            raise KeyError("Unknown setting: " + repr(key))
        setattr(self._settings, key, value)
        self._settings.clamp()
        if save:
            self.save()

    def update(self, values: dict, *, save: bool = True) -> None:
        settings = self.settings
        for key, value in values.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
            else:
                log.warning("Ignoring unknown setting %r", key)
        settings.clamp()
        if save:
            self.save()

    # -- Persistence ------------------------------------------------------

    def load(self) -> Settings:
        self._loaded = True
        raw: dict = {}
        if self._path.is_file():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("settings file is not a JSON object")
            except (OSError, ValueError) as exc:
                log.error("Could not read settings (%s); falling back to defaults", exc)
                self._backup_corrupt_file()
                raw = {}

        known = {f.name for f in fields(Settings)}
        payload = {k: v for k, v in raw.items() if k in known}
        try:
            self._settings = Settings(**payload)
        except TypeError as exc:
            log.error("Settings had incompatible types (%s); using defaults", exc)
            self._settings = Settings()
        self._settings = _migrate(self._settings)
        self._settings.clamp()
        return self._settings

    def save(self) -> bool:
        """Write settings atomically so a crash can never truncate the file."""
        settings = self.settings
        settings.version = SETTINGS_VERSION
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(asdict(settings), indent=2, ensure_ascii=False)
            handle, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=".settings-", suffix=".tmp"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp_name, self._path)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
            return True
        except OSError as exc:
            log.error("Could not save settings: %s", exc)
            return False

    def _backup_corrupt_file(self) -> None:
        try:
            backup = self._path.with_suffix(self._path.suffix + ".corrupt")
            self._path.replace(backup)
            log.info("Corrupt settings moved to %s", backup)
        except OSError:
            pass


def _migrate(settings: Settings) -> Settings:
    """Upgrade an older settings payload. No-op for version 1."""
    if settings.version < SETTINGS_VERSION:
        log.info("Migrating settings from v%s to v%s", settings.version, SETTINGS_VERSION)
        settings.version = SETTINGS_VERSION
    return settings


_store: SettingsStore | None = None


def get_settings_store() -> SettingsStore:
    """Process-wide settings store."""
    global _store
    if _store is None:
        _store = SettingsStore()
    return _store


def reset_settings_store() -> None:
    """Drop the cached store (used by tests)."""
    global _store
    _store = None
