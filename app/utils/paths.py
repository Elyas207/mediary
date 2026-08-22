"""Platform-aware application directories for Mediary.

Every path Mediary touches is resolved through this module so that no
platform-specific location is ever hardcoded elsewhere in the codebase.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

APP_NAME = "Mediary"
APP_SLUG = "mediary"

#: Environment variable that relocates *all* Mediary state. Used by the test
#: suite and by portable installations.
ENV_HOME = "MEDIARY_HOME"


def _home() -> Path:
    return Path.home()


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def _xdg(var: str, default: Path) -> Path:
    raw = os.environ.get(var)
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            return candidate
    return default


@lru_cache(maxsize=1)
def _override_root() -> Path | None:
    raw = os.environ.get(ENV_HOME)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def config_dir() -> Path:
    """Directory holding ``settings.json`` and other user configuration."""
    override = _override_root()
    if override is not None:
        return override / "config"
    if is_windows():
        base = Path(os.environ.get("APPDATA") or _home() / "AppData" / "Roaming")
        return base / APP_NAME
    if is_macos():
        return _home() / "Library" / "Application Support" / APP_NAME
    return _xdg("XDG_CONFIG_HOME", _home() / ".config") / APP_SLUG


def data_dir() -> Path:
    """Directory holding the SQLite database and other durable state."""
    override = _override_root()
    if override is not None:
        return override / "data"
    if is_windows():
        base = Path(os.environ.get("LOCALAPPDATA") or _home() / "AppData" / "Local")
        return base / APP_NAME
    if is_macos():
        return _home() / "Library" / "Application Support" / APP_NAME
    return _xdg("XDG_DATA_HOME", _home() / ".local" / "share") / APP_SLUG


def cache_dir() -> Path:
    """Directory for regenerable artefacts (thumbnails, extractor caches)."""
    override = _override_root()
    if override is not None:
        return override / "cache"
    if is_windows():
        base = Path(os.environ.get("LOCALAPPDATA") or _home() / "AppData" / "Local")
        return base / APP_NAME / "Cache"
    if is_macos():
        return _home() / "Library" / "Caches" / APP_NAME
    return _xdg("XDG_CACHE_HOME", _home() / ".cache") / APP_SLUG


def logs_dir() -> Path:
    """Directory for rotating application logs."""
    override = _override_root()
    if override is not None:
        return override / "logs"
    if is_macos():
        return _home() / "Library" / "Logs" / APP_NAME
    return data_dir() / "logs"


def thumbnails_dir() -> Path:
    return cache_dir() / "thumbnails"


def database_path() -> Path:
    return data_dir() / "library.db"


def settings_path() -> Path:
    return config_dir() / "settings.json"


def default_library_root() -> Path:
    """The suggested media root, e.g. ``~/Videos/Mediary`` or ``~/Mediary``."""
    override = _override_root()
    if override is not None:
        return override / "library"
    if is_windows():
        candidates = [_home() / "Videos", _home() / "Documents"]
    elif is_macos():
        candidates = [_home() / "Movies", _home() / "Documents"]
    else:
        candidates = [
            _xdg("XDG_VIDEOS_DIR", _home() / "Videos"),
            _home() / "Documents",
        ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate / APP_NAME
    return _home() / APP_NAME


def ensure_app_dirs() -> None:
    """Create every directory Mediary needs for its own state."""
    for directory in (config_dir(), data_dir(), cache_dir(), logs_dir(), thumbnails_dir()):
        directory.mkdir(parents=True, exist_ok=True)


def bundled_binary(name: str) -> Path | None:
    """Return a binary shipped alongside a frozen build, if present.

    PyInstaller unpacks bundled data into ``sys._MEIPASS``; a portable install
    may instead place binaries in a ``bin/`` folder next to the executable.
    """
    exe_name = f"{name}.exe" if is_windows() else name
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
        roots.append(Path(meipass) / "bin")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        roots.extend([exe_dir, exe_dir / "bin"])
    roots.append(Path(__file__).resolve().parents[2] / "bin")
    for root in roots:
        candidate = root / exe_name
        if candidate.is_file():
            return candidate
    return None


def reset_path_cache() -> None:
    """Forget a cached ``MEDIARY_HOME`` override (used by tests)."""
    _override_root.cache_clear()
