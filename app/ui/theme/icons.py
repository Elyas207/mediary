"""Vector icons drawn from inline SVG paths.

Icons are recoloured at render time to match the active palette, so a single
definition serves both themes and no binary assets ship with the app. Rendered
pixmaps are cached per (name, colour, size, dpr).
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

#: 24x24 stroke paths, drawn on a 24-unit grid with round caps and joins.
#: Kept visually consistent: 1.7 stroke width, generous negative space.
_PATHS: dict = {
    # Navigation
    "download": "M12 3.5v11.5M12 15l-4.2-4.2M12 15l4.2-4.2M4.5 19h15",
    "library": "M4 5.5h16M4 12h16M4 18.5h16",
    "grid": "M4 4.5h6.5v6.5H4zM13.5 4.5H20v6.5h-6.5zM4 13.5h6.5V20H4zM13.5 13.5H20V20h-6.5z",
    "video": "M3.5 6.5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2z"
             "M15.5 10l4.2-2.6a.6.6 0 0 1 .9.5v8.2a.6.6 0 0 1-.9.5l-4.2-2.6z",
    "audio": "M9.5 18.2V6.4l9-1.9v11.4M9.5 18.2a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z"
             "M18.5 15.9a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
    "waveform": "M3 12h2M7 8v8M11 4.5v15M15 8v8M19 10.5v3M21.5 12h.5",
    "music": "M9 18V5l10-2v13M9 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0zM19 16a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
    "sparkle": "M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9z"
               "M18.5 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z",
    "star": "M12 3.8l2.6 5.3 5.9.9-4.3 4.2 1 5.9-5.2-2.8-5.2 2.8 1-5.9-4.3-4.2 5.9-.9z",
    "settings": "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4z"
                "M19.1 14.4a1.5 1.5 0 0 0 .3 1.7l.1.1a1.8 1.8 0 1 1-2.6 2.6l-.1-.1a1.5 1.5 0 0 0-1.7-.3 1.5 1.5 0 0 0-.9 1.4v.2a1.8 1.8 0 1 1-3.6 0v-.1a1.5 1.5 0 0 0-1-1.4 1.5 1.5 0 0 0-1.7.3l-.1.1a1.8 1.8 0 1 1-2.6-2.6l.1-.1a1.5 1.5 0 0 0 .3-1.7 1.5 1.5 0 0 0-1.4-.9h-.2a1.8 1.8 0 1 1 0-3.6h.1a1.5 1.5 0 0 0 1.4-1 1.5 1.5 0 0 0-.3-1.7l-.1-.1A1.8 1.8 0 1 1 7.7 4.6l.1.1a1.5 1.5 0 0 0 1.7.3h.1a1.5 1.5 0 0 0 .9-1.4v-.2a1.8 1.8 0 1 1 3.6 0v.1a1.5 1.5 0 0 0 .9 1.4 1.5 1.5 0 0 0 1.7-.3l.1-.1a1.8 1.8 0 1 1 2.6 2.6l-.1.1a1.5 1.5 0 0 0-.3 1.7v.1a1.5 1.5 0 0 0 1.4.9h.2a1.8 1.8 0 1 1 0 3.6h-.1a1.5 1.5 0 0 0-1.4.9z",

    # Actions
    "search": "M10.8 17.6a6.8 6.8 0 1 0 0-13.6 6.8 6.8 0 0 0 0 13.6zM20 20l-4.4-4.4",
    "close": "M6 6l12 12M18 6L6 18",
    "plus": "M12 5v14M5 12h14",
    "minus": "M5 12h14",
    "check": "M4.5 12.5l5 5 10-11",
    "chevron-down": "M6 9.5l6 6 6-6",
    "chevron-up": "M6 14.5l6-6 6 6",
    "chevron-right": "M9.5 5.5l7 6.5-7 6.5",
    "chevron-left": "M14.5 5.5l-7 6.5 7 6.5",
    "more-horizontal": "M6 12h.01M12 12h.01M18 12h.01",
    "more-vertical": "M12 6v.01M12 12v.01M12 18v.01",
    "filter": "M3.5 5.5h17l-6.6 7.8v5.4l-3.8 2v-7.4z",
    "sort": "M7 4.5v15M7 19.5l-3-3M7 19.5l3-3M17 19.5v-15M17 4.5l-3 3M17 4.5l3 3",
    "refresh": "M20 5.5v5h-5M4 18.5v-5h5"
               "M19.2 10.5a7.5 7.5 0 0 0-13-3.2L4 10.5M4.8 13.5a7.5 7.5 0 0 0 13 3.2l2.2-3.2",
    "external": "M14 4.5h5.5V10M19.5 4.5L11 13M17 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7H10",
    "copy": "M9 9.5a2 2 0 0 1 2-2h7.5a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H11a2 2 0 0 1-2-2z"
            "M5.5 14.5A2 2 0 0 1 3.5 12.5V5.5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2",
    "folder": "M3.5 7.5a2 2 0 0 1 2-2h3.4l2 2.5h7.6a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z",
    "file": "M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9zM13.5 3.5V9H19",
    "trash": "M4.5 7h15M9.5 7V5.2a1.2 1.2 0 0 1 1.2-1.2h2.6a1.2 1.2 0 0 1 1.2 1.2V7"
             "M6.5 7l.9 12a1.5 1.5 0 0 0 1.5 1.4h6.2a1.5 1.5 0 0 0 1.5-1.4l.9-12M10 11v6M14 11v6",
    "edit": "M4 20h4l10.3-10.3a2.1 2.1 0 0 0-3-3L5 17v3zM14.5 6.5l3 3",
    "tag": "M3.8 11.4V4.8a1 1 0 0 1 1-1h6.6a1 1 0 0 1 .7.3l8 8a1 1 0 0 1 0 1.4l-6.6 6.6a1 1 0 0 1-1.4 0l-8-8a1 1 0 0 1-.3-.7zM8 8.5h.01",
    "link": "M10.5 13.5a4 4 0 0 0 5.7 0l3-3a4 4 0 1 0-5.7-5.7l-1.7 1.7"
            "M13.5 10.5a4 4 0 0 0-5.7 0l-3 3a4 4 0 1 0 5.7 5.7l1.7-1.7",
    "clipboard": "M9 4.5h6a1 1 0 0 1 1 1V7a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1z"
                 "M16 6h1.5a2 2 0 0 1 2 2v10.5a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2H8",

    # Playback / queue
    "play": "M8 5.5l11 6.5-11 6.5z",
    "pause": "M9 5.5v13M15 5.5v13",
    "stop": "M6 6.5h12v11H6z",
    "skip": "M6 5.5l9 6.5-9 6.5zM18 5.5v13",
    "volume": "M11 5.5L6.5 9.5H3.5v5h3L11 18.5zM15 9.5a3.5 3.5 0 0 1 0 5M17.8 7a7 7 0 0 1 0 10",
    "clock": "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17zM12 7.5V12l3 2",
    "queue": "M4 6.5h11M4 12h11M4 17.5h7M17.5 14.5l3 3-3 3M20.5 17.5H15",

    # Status
    "alert": "M12 8.5V13M12 16.5v.01M10.3 4.4L2.6 17.6a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.4a2 2 0 0 0-3.4 0z",
    "info": "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17zM12 11v5.5M12 7.8v.01",
    "check-circle": "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17zM8 12.2l2.8 2.8L16 9.5",
    "x-circle": "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17zM9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6",
    "shield": "M12 3.5l7 2.8v5.2c0 4.2-2.9 7.5-7 9-4.1-1.5-7-4.8-7-9V6.3z",

    # Theme
    "sun": "M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4"
           "M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
    "moon": "M20 14.4A8.5 8.5 0 0 1 9.6 4a8.5 8.5 0 1 0 10.4 10.4z",
    "monitor": "M4 5.5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM8.5 20.5h7M12 16.5v4",

    # Misc
    "image": "M4.5 4.5h15a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1z"
             "M8.5 10.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM20.5 15l-5-5-11 9.5",
    "eye": "M2.5 12s3.6-6.5 9.5-6.5S21.5 12 21.5 12s-3.6 6.5-9.5 6.5S2.5 12 2.5 12z"
           "M12 14.8a2.8 2.8 0 1 0 0-5.6 2.8 2.8 0 0 0 0 5.6z",
    "layers": "M12 3.5l9 4.5-9 4.5-9-4.5zM3 12.5l9 4.5 9-4.5M3 16.8l9 4.5 9-4.5",
    "list": "M8 6.5h13M8 12h13M8 17.5h13M3.5 6.5h.01M3.5 12h.01M3.5 17.5h.01",
    "inbox": "M3.5 12.5H8l1.5 3h5l1.5-3h4.5M3.5 12.5l3-8h11l3 8v5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z",
    "globe": "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17zM3.5 12h17"
             "M12 3.5a13 13 0 0 1 0 17 13 13 0 0 1 0-17z",
    "arrow-up": "M12 19V5M12 5l-6 6M12 5l6 6",
    "arrow-down": "M12 5v14M12 19l-6-6M12 19l6-6",
    "arrow-right": "M5 12h14M19 12l-6-6M19 12l-6 6",
    "arrow-left": "M19 12H5M5 12l6-6M5 12l6 6",
}

#: Icons drawn filled rather than stroked.
_FILLED = {"play", "star-filled", "stop", "skip"}

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
    '<path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

_cache: dict = {}


def available_icons() -> list:
    return sorted(_PATHS)


def icon_svg(name: str, color: str, *, stroke_width: float = 1.7, filled: bool = False) -> str:
    """Raw SVG markup for an icon in a given colour."""
    path = _PATHS.get(name)
    if path is None:
        path = _PATHS["info"]
    use_fill = filled or name in _FILLED
    return _SVG_TEMPLATE.format(
        path=path,
        fill=color if use_fill else "none",
        stroke="none" if use_fill else color,
        width=0 if use_fill else stroke_width,
    )


def icon_pixmap(
    name: str,
    color: str,
    size: int = 16,
    *,
    stroke_width: float = 1.7,
    filled: bool = False,
    dpr: float = 1.0,
) -> QPixmap:
    """Render an icon to a device-pixel-ratio-aware pixmap."""
    key = (name, color, size, round(stroke_width, 2), filled, round(dpr, 2))
    cached = _cache.get(key)
    if cached is not None:
        return cached

    svg = icon_svg(name, color, stroke_width=stroke_width, filled=filled)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    physical = max(1, int(round(size * dpr)))
    pixmap = QPixmap(physical, physical)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, physical, physical))
    painter.end()

    _cache[key] = pixmap
    return pixmap


def make_icon(
    name: str,
    color: str,
    size: int = 16,
    *,
    disabled_color: str = "",
    active_color: str = "",
    stroke_width: float = 1.7,
    filled: bool = False,
    dpr: float = 1.0,
) -> QIcon:
    """A :class:`QIcon` with optional disabled and active (hover) variants."""
    icon = QIcon()
    icon.addPixmap(
        icon_pixmap(name, color, size, stroke_width=stroke_width, filled=filled, dpr=dpr),
        QIcon.Mode.Normal,
    )
    if disabled_color:
        icon.addPixmap(
            icon_pixmap(
                name, disabled_color, size, stroke_width=stroke_width, filled=filled, dpr=dpr
            ),
            QIcon.Mode.Disabled,
        )
    if active_color:
        for mode in (QIcon.Mode.Active, QIcon.Mode.Selected):
            icon.addPixmap(
                icon_pixmap(
                    name, active_color, size, stroke_width=stroke_width, filled=filled, dpr=dpr
                ),
                mode,
            )
    return icon


def colored_pixmap(source: QPixmap, color: str) -> QPixmap:
    """Tint an existing pixmap - used for the checkbox tick in QSS."""
    tinted = QPixmap(source.size())
    tinted.setDevicePixelRatio(source.devicePixelRatio())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    return tinted


def clear_cache() -> None:
    """Drop cached pixmaps - called when the theme changes."""
    _cache.clear()


def icon_size(size: int) -> QSize:
    return QSize(size, size)
