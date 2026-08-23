"""Reading the desktop's own theme preferences.

Qt already tells us light-or-dark through ``QStyleHints.colorScheme()``. What it
does not surface portably is the *accent colour* the user picked in their OS
settings, so that is read per platform here.

Everything degrades to Mediary's own palette: a machine that exposes none of
this looks exactly as it did before.
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.utils.logging import get_logger

log = get_logger("theme.system")

#: Accents outside this lightness band are unusable as a UI accent: too dark and
#: white text on it fails, too light and it vanishes against a light surface.
MIN_LIGHTNESS = 0.28
MAX_LIGHTNESS = 0.78


def system_color_scheme() -> str:
    """``"dark"``, ``"light"`` or ``"unknown"`` from Qt's own hint."""
    try:
        from PySide6.QtCore import Qt

        scheme = QApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
    except (AttributeError, TypeError, RuntimeError):
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Accent colour, per platform
# ---------------------------------------------------------------------------


def _windows_accent() -> QColor | None:
    """Windows stores the personalisation accent in the registry as AABBGGRR."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
    except (ImportError, OSError, FileNotFoundError):
        return None

    raw = int(value) & 0xFFFFFFFF
    # DWM stores it byte-reversed relative to the usual ARGB order.
    blue = (raw >> 16) & 0xFF
    green = (raw >> 8) & 0xFF
    red = raw & 0xFF
    return QColor(red, green, blue)


def _macos_accent() -> QColor | None:
    """macOS exposes an accent *index* rather than a colour."""
    # -1/absent means "multicolour", which is the graphite-blue default.
    palette = {
        -1: QColor("#007AFF"),   # multicolour / default blue
        0: QColor("#FF3B30"),    # red
        1: QColor("#FF9500"),    # orange
        2: QColor("#FFCC00"),    # yellow
        3: QColor("#28CD41"),    # green
        4: QColor("#007AFF"),    # blue
        5: QColor("#AF52DE"),    # purple
        6: QColor("#FF2D55"),    # pink
        7: QColor("#8E8E93"),    # graphite
    }
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleAccentColor"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return palette[-1]
        return palette.get(int(result.stdout.strip()), palette[-1])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _linux_accent() -> QColor | None:
    """Ask the XDG desktop portal, then fall back to Qt's own palette.

    The portal is the only cross-desktop route; KDE and GNOME both answer it.
    """
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.freedesktop.portal.Desktop",
                "--object-path", "/org/freedesktop/portal/desktop",
                "--method", "org.freedesktop.portal.Settings.Read",
                "org.freedesktop.appearance", "accent-color",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and "(" in result.stdout:
            # Reply looks like: (<<(0.2, 0.4, 0.9)>>,)
            numbers = [
                float(part)
                for part in result.stdout.replace("(", " ").replace(")", " ").split(",")
                if _is_float(part)
            ]
            if len(numbers) >= 3:
                red, green, blue = numbers[:3]
                return QColor.fromRgbF(
                    max(0.0, min(1.0, red)),
                    max(0.0, min(1.0, green)),
                    max(0.0, min(1.0, blue)),
                )
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    # Fall back to whatever the active Qt style considers a highlight, which on
    # KDE follows the user's colour scheme.
    try:
        highlight = QApplication.palette().color(QPalette.ColorRole.Highlight)
        if highlight.isValid():
            return highlight
    except RuntimeError:
        pass
    return None


def _is_float(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def system_accent() -> QColor | None:
    """The desktop's accent colour, or ``None`` if it cannot be determined."""
    try:
        if sys.platform.startswith("win"):
            colour = _windows_accent()
        elif sys.platform == "darwin":
            colour = _macos_accent()
        else:
            colour = _linux_accent()
    except Exception:  # noqa: BLE001 - never let theming break startup
        log.debug("Could not read the system accent colour", exc_info=True)
        return None

    if colour is None or not colour.isValid():
        return None
    return colour


def usable_accent(dark: bool) -> QColor | None:
    """The system accent, nudged into a range that works as a UI accent.

    Some people run a near-black or near-white accent. Used verbatim that gives
    invisible buttons or unreadable label text, so the hue is kept and only the
    lightness is corrected.
    """
    colour = system_accent()
    if colour is None:
        return None

    lightness = colour.lightnessF()
    if MIN_LIGHTNESS <= lightness <= MAX_LIGHTNESS:
        return colour

    target = 0.58 if dark else 0.46
    adjusted = QColor.fromHslF(
        max(0.0, colour.hueF()) if colour.hueF() >= 0 else 0.6,
        max(0.25, colour.saturationF()),
        target,
    )
    return adjusted


def accent_variants(accent: QColor) -> dict:
    """Hover, pressed, soft-fill and on-accent text derived from one colour."""
    hover = QColor(accent)
    hover = hover.lighter(112)
    pressed = QColor(accent).darker(112)

    soft = QColor(accent)
    soft.setAlpha(38)

    # Contrast decides the text colour, not a guess: a yellow accent needs dark
    # text where a navy one needs white.
    luminance = (
        0.2126 * accent.redF() + 0.7152 * accent.greenF() + 0.0722 * accent.blueF()
    )
    on_accent = "#FFFFFF" if luminance < 0.6 else "#14161A"

    return {
        "accent": accent.name(),
        "accent_hover": hover.name(),
        "accent_pressed": pressed.name(),
        "accent_soft": f"rgba({soft.red()}, {soft.green()}, {soft.blue()}, {soft.alpha()})",
        "accent_text": on_accent,
    }
