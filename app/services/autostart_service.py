"""Registering Mediary to launch when the user signs in.

Each platform has its own mechanism and none of them is a file format we should
guess at, so all three are implemented explicitly:

* Windows - a value under ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
* macOS   - a LaunchAgent plist in ``~/Library/LaunchAgents``
* Linux   - an XDG autostart ``.desktop`` file in ``~/.config/autostart``

Everything is written under the user's own account. Mediary never touches
machine-wide registry keys, ``/Library/LaunchAgents`` or ``/etc/xdg/autostart``,
so enabling this never needs elevation.
"""

from __future__ import annotations

import plistlib
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.paths import APP_NAME, is_linux, is_macos, is_windows

log = get_logger("autostart")

#: Passed by the autostart entry so a login launch starts in the background
#: while a manual launch still opens the window.
HIDDEN_FLAG = "--hidden"

WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_VALUE_NAME = APP_NAME
MACOS_BUNDLE_ID = "app.mediary.Mediary"
LINUX_DESKTOP_NAME = "mediary.desktop"


@dataclass
class AutostartState:
    """What the OS currently has registered."""

    enabled: bool = False
    hidden: bool = False
    command: str = ""
    location: str = ""


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launch_argv(hidden: bool) -> list:
    """The argv the OS should run at login.

    A frozen build launches its own executable. From a source checkout we invoke
    ``main.py`` by absolute path rather than ``-m app.main``, because the login
    session's working directory is not the project root.
    """
    arguments: list = []

    if _is_frozen():
        arguments.append(str(Path(sys.executable).resolve()))
    else:
        interpreter = Path(sys.executable)
        if is_windows():
            # pythonw.exe runs without allocating a console, so nothing flashes
            # on screen at sign-in.
            windowless = interpreter.with_name("pythonw.exe")
            if windowless.is_file():
                interpreter = windowless
        entry = Path(__file__).resolve().parents[1] / "main.py"
        arguments.extend([str(interpreter), str(entry)])

    if hidden:
        arguments.append(HIDDEN_FLAG)
    return arguments


def _quote(arguments: list) -> str:
    if is_windows():
        return " ".join(f'"{part}"' if " " in part else part for part in arguments)
    return " ".join(shlex.quote(part) for part in arguments)


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def _windows_state() -> AutostartState:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, WINDOWS_VALUE_NAME)
    except FileNotFoundError:
        return AutostartState(location=f"HKCU\\{WINDOWS_RUN_KEY}")
    except OSError as exc:
        log.debug("Could not read the Run key: %s", exc)
        return AutostartState(location=f"HKCU\\{WINDOWS_RUN_KEY}")

    command = str(value)
    return AutostartState(
        enabled=True,
        hidden=HIDDEN_FLAG in command,
        command=command,
        location=f"HKCU\\{WINDOWS_RUN_KEY}",
    )


def _windows_set(enabled: bool, hidden: bool) -> tuple:
    import winreg

    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(
                    key, WINDOWS_VALUE_NAME, 0, winreg.REG_SZ, _quote(launch_argv(hidden))
                )
            else:
                try:
                    winreg.DeleteValue(key, WINDOWS_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True, ""
    except OSError as exc:
        log.error("Could not update the Run key: %s", exc)
        return False, str(exc)


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MACOS_BUNDLE_ID}.plist"


def _macos_state() -> AutostartState:
    path = _macos_plist_path()
    state = AutostartState(location=str(path))
    if not path.is_file():
        return state
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        log.debug("Could not read the LaunchAgent: %s", exc)
        return state

    arguments = payload.get("ProgramArguments") or []
    state.enabled = bool(payload.get("RunAtLoad")) and bool(arguments)
    state.hidden = HIDDEN_FLAG in arguments
    state.command = " ".join(str(a) for a in arguments)
    return state


def _macos_set(enabled: bool, hidden: bool) -> tuple:
    path = _macos_plist_path()
    if not enabled:
        try:
            path.unlink(missing_ok=True)
            return True, ""
        except OSError as exc:
            return False, str(exc)

    payload = {
        "Label": MACOS_BUNDLE_ID,
        "ProgramArguments": launch_argv(hidden),
        "RunAtLoad": True,
        # Mediary is a normal app, not a daemon: if the user quits it, leave it
        # quit rather than relaunching behind their back.
        "KeepAlive": False,
        "ProcessType": "Interactive",
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            plistlib.dump(payload, handle)
        return True, ""
    except OSError as exc:
        log.error("Could not write the LaunchAgent: %s", exc)
        return False, str(exc)


# ---------------------------------------------------------------------------
# Linux (XDG autostart)
# ---------------------------------------------------------------------------


def _linux_desktop_path() -> Path:
    import os

    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "autostart" / LINUX_DESKTOP_NAME


def _linux_state() -> AutostartState:
    path = _linux_desktop_path()
    state = AutostartState(location=str(path))
    if not path.is_file():
        return state
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.debug("Could not read the autostart entry: %s", exc)
        return state

    command = ""
    disabled = False
    for line in text.splitlines():
        if line.startswith("Exec="):
            command = line.partition("=")[2].strip()
        elif line.replace(" ", "").lower() == "hidden=true":
            # The XDG spec uses Hidden=true to mean "this entry is disabled",
            # which is unrelated to Mediary's own --hidden flag.
            disabled = True

    state.enabled = bool(command) and not disabled
    state.hidden = HIDDEN_FLAG in command
    state.command = command
    return state


def _linux_set(enabled: bool, hidden: bool) -> tuple:
    path = _linux_desktop_path()
    if not enabled:
        try:
            path.unlink(missing_ok=True)
            return True, ""
        except OSError as exc:
            return False, str(exc)

    entry = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={APP_NAME}",
            "Comment=Download, organise and search a personal media library",
            f"Exec={_quote(launch_argv(hidden))}",
            "Icon=mediary",
            "Terminal=false",
            "Categories=AudioVideo;Audio;Video;Utility;",
            "X-GNOME-Autostart-enabled=true",
            "",
        ]
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry, encoding="utf-8")
        path.chmod(0o755)
        return True, ""
    except OSError as exc:
        log.error("Could not write the autostart entry: %s", exc)
        return False, str(exc)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


class AutostartService:
    """Reads and writes the platform's sign-in autostart entry."""

    @staticmethod
    def is_supported() -> bool:
        return is_windows() or is_macos() or is_linux()

    @staticmethod
    def state() -> AutostartState:
        """What is registered with the OS right now."""
        try:
            if is_windows():
                return _windows_state()
            if is_macos():
                return _macos_state()
            if is_linux():
                return _linux_state()
        except Exception:  # noqa: BLE001 - never let this break Settings
            log.exception("Could not read the autostart state")
        return AutostartState()

    @classmethod
    def is_enabled(cls) -> bool:
        return cls.state().enabled

    @staticmethod
    def set_enabled(enabled: bool, *, hidden: bool = False) -> tuple:
        """Register or remove the entry. Returns ``(ok, error_message)``."""
        try:
            if is_windows():
                ok, error = _windows_set(enabled, hidden)
            elif is_macos():
                ok, error = _macos_set(enabled, hidden)
            elif is_linux():
                ok, error = _linux_set(enabled, hidden)
            else:
                return False, "Launching at sign-in is not supported on this platform."
        except Exception as exc:  # noqa: BLE001
            log.exception("Could not update the autostart entry")
            return False, str(exc)

        if ok:
            log.info(
                "Autostart %s%s", "enabled" if enabled else "disabled",
                " (hidden)" if enabled and hidden else "",
            )
        return ok, error

    @classmethod
    def sync(cls, enabled: bool, hidden: bool) -> tuple:
        """Make the OS entry match the settings, rewriting it if the flag changed.

        The registered command embeds whether to start hidden, so toggling that
        option has to rewrite the entry, not just leave it alone.
        """
        current = cls.state()
        if current.enabled == enabled and (not enabled or current.hidden == hidden):
            return True, ""
        return cls.set_enabled(enabled, hidden=hidden)

    @staticmethod
    def describe_location() -> str:
        """Where the entry lives, for the Settings screen."""
        if is_windows():
            return f"HKCU\\{WINDOWS_RUN_KEY}"
        if is_macos():
            return str(_macos_plist_path())
        if is_linux():
            return str(_linux_desktop_path())
        return ""
