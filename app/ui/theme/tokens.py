"""The Mediary design system: colour, type, spacing and radius tokens.

Every visual value in the app comes from here. Widgets reference token *names*,
never literal hex codes, so both themes stay coherent and a palette change is a
one-file edit.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields


@dataclass(frozen=True)
class Palette:
    """One complete colour theme."""

    name: str

    # -- Surfaces, back to front ---------------------------------------
    app: str            # window chrome, behind everything
    sidebar: str        # primary navigation
    surface: str        # main content area
    elevated: str       # cards, menus, dialogs, popovers
    inset: str          # inputs, wells, code blocks
    overlay: str        # scrim behind modals (rgba)

    # -- Interaction states --------------------------------------------
    hover: str
    active: str
    selected: str
    selected_text: str

    # -- Lines ----------------------------------------------------------
    border: str         # hairlines between regions
    border_strong: str  # input outlines, focused separators
    divider: str

    # -- Text -----------------------------------------------------------
    text: str
    text_secondary: str
    text_muted: str
    text_inverted: str

    # -- Brand ------------------------------------------------------------
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    accent_text: str    # text drawn on top of `accent`

    # -- Semantics --------------------------------------------------------
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_hover: str
    danger_soft: str
    info: str

    # -- Media chrome -----------------------------------------------------
    thumb_bg: str       # letterbox behind artwork
    scrollbar: str
    scrollbar_hover: str
    shadow: str

    # -- Category accents, keyed by Category.accent -----------------------
    categories: dict = field(default_factory=dict)

    def category(self, key: str) -> str:
        return self.categories.get(key, self.categories.get("slate", self.text_muted))

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


# Category hues are deliberately desaturated: they carry information at 8px
# (a dot on a card) without turning the library into a rainbow.
_CATEGORY_DARK = {
    "blue": "#5B8CFF",
    "violet": "#9B7BF5",
    "magenta": "#D96BB4",
    "amber": "#E0A94A",
    "teal": "#3EC0AE",
    "green": "#57B26A",
    "orange": "#E8894A",
    "slate": "#828894",
}

_CATEGORY_LIGHT = {
    "blue": "#3F6FE8",
    "violet": "#7A56DE",
    "magenta": "#C4489B",
    "amber": "#B37A11",
    "teal": "#12907F",
    "green": "#3D8A4E",
    "orange": "#C4661F",
    "slate": "#6B7280",
}


DARK = Palette(
    name="dark",
    app="#0E0F11",
    sidebar="#131418",
    surface="#17181C",
    elevated="#1D1E23",
    inset="#101114",
    overlay="rgba(8, 9, 11, 190)",
    hover="#212228",
    active="#26272E",
    selected="#272932",
    selected_text="#FFFFFF",
    border="#24252B",
    border_strong="#33353D",
    divider="#1F2026",
    text="#ECEDF0",
    text_secondary="#9CA0AA",
    text_muted="#6A6E78",
    text_inverted="#101114",
    accent="#5B7CFA",
    accent_hover="#6E8CFB",
    accent_pressed="#4A6AE6",
    accent_soft="rgba(91, 124, 250, 38)",
    accent_text="#FFFFFF",
    success="#4FB865",
    success_soft="rgba(79, 184, 101, 34)",
    warning="#D9A23C",
    warning_soft="rgba(217, 162, 60, 34)",
    danger="#E5594F",
    danger_hover="#EE6A60",
    danger_soft="rgba(229, 89, 79, 34)",
    info="#5B9BD5",
    thumb_bg="#0B0C0E",
    scrollbar="#2E3038",
    scrollbar_hover="#3C3F49",
    shadow="rgba(0, 0, 0, 140)",
    categories=_CATEGORY_DARK,
)


LIGHT = Palette(
    name="light",
    app="#F1F2F4",
    sidebar="#F7F7F9",
    surface="#FFFFFF",
    elevated="#FFFFFF",
    inset="#F6F7F9",
    overlay="rgba(24, 26, 30, 120)",
    hover="#F0F1F4",
    active="#E7E9ED",
    selected="#EBEFFE",
    selected_text="#1A2E7A",
    border="#E4E5EA",
    border_strong="#CBCDD5",
    divider="#EDEEF1",
    text="#15161A",
    text_secondary="#5A5E68",
    text_muted="#8A8E98",
    text_inverted="#FFFFFF",
    accent="#3D5FE8",
    accent_hover="#3355DC",
    accent_pressed="#2A49C9",
    accent_soft="rgba(61, 95, 232, 28)",
    accent_text="#FFFFFF",
    success="#2E8B45",
    success_soft="rgba(46, 139, 69, 28)",
    warning="#9A6B0C",
    warning_soft="rgba(200, 150, 30, 40)",
    danger="#CF3B32",
    danger_hover="#BC332B",
    danger_soft="rgba(207, 59, 50, 26)",
    info="#2F6FB3",
    thumb_bg="#EDEEF1",
    scrollbar="#C9CBD2",
    scrollbar_hover="#B0B3BC",
    shadow="rgba(20, 22, 28, 34)",
    categories=_CATEGORY_LIGHT,
)


PALETTES: dict = {"dark": DARK, "light": LIGHT}


# ---------------------------------------------------------------------------
# Spacing, radius, type
# ---------------------------------------------------------------------------


class Space:
    """A strict 4px rhythm. Nothing in the UI uses an off-scale gap."""

    xxs = 2
    xs = 4
    sm = 8
    md = 12
    lg = 16
    xl = 20
    xxl = 24
    x3l = 32
    x4l = 40
    x5l = 56


class Radius:
    xs = 3
    sm = 5
    md = 7
    lg = 10
    xl = 14
    pill = 999


class Size:
    """Fixed dimensions that several widgets must agree on."""

    sidebar_width = 232
    sidebar_min = 200
    sidebar_max = 320
    topbar_height = 52
    control_height = 32
    control_height_sm = 26
    control_height_lg = 40
    input_height = 34
    row_height = 44
    queue_row_height = 58
    inspector_width = 340
    icon = 16
    icon_sm = 14
    icon_lg = 20


class Type:
    """Font sizes in px. Qt scales these for high-DPI displays."""

    micro = 10
    label = 11        # uppercase section labels, badges
    small = 12        # secondary metadata
    body = 13         # default UI text
    medium = 14       # emphasised body, list titles
    large = 16        # section headings
    title = 21        # page titles
    hero = 27         # empty-state and onboarding headlines

    weight_regular = 400
    weight_medium = 500
    weight_semibold = 600
    weight_bold = 700

    tracking_label = "0.07em"


#: Preferred UI families per platform, best first.
UI_FAMILIES: dict = {
    "win32": ["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "Arial"],
    "darwin": ["SF Pro Text", "Helvetica Neue", "Inter", "Helvetica"],
    "linux": ["Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans"],
}

MONO_FAMILIES: dict = {
    "win32": ["Cascadia Mono", "Consolas", "Courier New"],
    "darwin": ["SF Mono", "Menlo", "Monaco", "Courier New"],
    "linux": ["JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono"],
}


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _first_installed(candidates: list, fallback: str) -> str:
    """The first candidate the font database actually has.

    Qt's stylesheet parser does not reliably fall through a comma-separated
    ``font-family`` list the way a browser does, so Mediary resolves the family
    itself and emits a single known-good name.
    """
    try:
        from PySide6.QtGui import QFontDatabase

        available = {name.lower() for name in QFontDatabase.families()}
    except Exception:  # noqa: BLE001 - no QApplication yet, or a headless build
        available = set()
    if not available:
        # Some headless/offscreen platform plugins expose no font database at
        # all. Trusting the platform's canonical family beats a generic alias.
        return candidates[0] if candidates else fallback
    for name in candidates:
        if name.lower() in available:
            return name
    return fallback


_resolved_ui: str | None = None
_resolved_mono: str | None = None


def resolve_fonts(*, force: bool = False) -> tuple:
    """Pick and cache the UI and monospace families for this machine."""
    global _resolved_ui, _resolved_mono
    if force or _resolved_ui is None:
        key = _platform_key()
        _resolved_ui = _first_installed(UI_FAMILIES[key], "sans-serif")
        _resolved_mono = _first_installed(MONO_FAMILIES[key], "monospace")
    return _resolved_ui, _resolved_mono


def font_family() -> str:
    """The resolved UI family name."""
    return resolve_fonts()[0]


def mono_family() -> str:
    """The resolved monospace family name."""
    return resolve_fonts()[1]


def font_stack() -> str:
    """QSS ``font-family`` value for UI text."""
    family = font_family()
    return f'"{family}"' if " " in family else family


def mono_stack() -> str:
    """QSS ``font-family`` value for technical text."""
    family = mono_family()
    return f'"{family}"' if " " in family else family


# ---------------------------------------------------------------------------
# Status colouring
# ---------------------------------------------------------------------------

def status_color(palette: Palette, status_value: str) -> str:
    """Colour for a :class:`DownloadStatus` label."""
    return {
        "Queued": palette.text_muted,
        "Analyzing": palette.info,
        "Downloading": palette.accent,
        "Processing": palette.warning,
        "Organizing": palette.warning,
        "Complete": palette.success,
        "Failed": palette.danger,
        "Cancelled": palette.text_muted,
        "Paused": palette.text_secondary,
    }.get(status_value, palette.text_secondary)
