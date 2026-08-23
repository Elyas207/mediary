"""Generated placeholder artwork.

Most sound effects and a fair amount of music arrive with no cover art, so a
library built on real downloads is largely thumbnail-less. Filling those tiles
with an identical grey rectangle makes a full library look broken and an empty
one look identical to a full one.

Instead each item gets a gradient. The hue comes from its *category*, so the
colour carries the same information as the category dot; the variation within
that hue comes from a hash of the title, so two whooshes are still tellable
apart at a glance and a given file always looks the same.
"""

from __future__ import annotations

import hashlib

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter

#: How far the per-item hash may push the hue, in degrees. Small enough that a
#: category still reads as one colour family.
HUE_SPREAD = 16


def _seed(text: str) -> int:
    return int(hashlib.sha1((text or "untitled").encode("utf-8", "ignore")).hexdigest()[:8], 16)


def gradient_colors(key: str, base: str, *, dark: bool) -> tuple:
    """Two colours for an item's placeholder, derived from its category hue."""
    seed = _seed(key)
    anchor = QColor(base)

    hue = anchor.hslHue()
    if hue < 0:            # a grey base has no hue; give it a cool one
        hue = 220
    saturation = anchor.hslSaturation()

    # Deterministic per-item variation.
    hue = (hue + ((seed % (HUE_SPREAD * 2)) - HUE_SPREAD)) % 360
    tilt = ((seed >> 8) % 9) - 4

    # Qt's HSL components are 0-255, not 0-100. Saturation and lightness below
    # are on that scale: 98 is roughly 38% lightness, not 98%.
    if dark:
        top = QColor.fromHsl(
            hue, _clamp(saturation * 0.78, 72, 168), _clamp(100 + tilt * 3, 78, 122)
        )
        bottom = QColor.fromHsl(
            (hue + 20) % 360, _clamp(saturation * 0.66, 56, 148), _clamp(62 + tilt * 3, 44, 84)
        )
    else:
        top = QColor.fromHsl(
            hue, _clamp(saturation * 0.70, 70, 190), _clamp(202 + tilt * 2, 180, 224)
        )
        bottom = QColor.fromHsl(
            (hue + 20) % 360, _clamp(saturation * 0.62, 58, 172), _clamp(168 + tilt * 2, 146, 198)
        )
    return top, bottom


def _clamp(value: float, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def paint_placeholder(
    painter: QPainter,
    rect: QRectF,
    key: str,
    base_color: str,
    *,
    dark: bool,
) -> None:
    """Fill ``rect`` with the generated gradient for ``key``."""
    top, bottom = gradient_colors(key, base_color, dark=dark)

    gradient = QLinearGradient(
        QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.bottom())
    )
    gradient.setColorAt(0.0, top)
    gradient.setColorAt(1.0, bottom)
    painter.fillRect(rect, QBrush(gradient))

    # A soft highlight in one corner stops large tiles reading as a flat slab.
    sheen = QLinearGradient(
        QPointF(rect.left(), rect.top()), QPointF(rect.center().x(), rect.center().y())
    )
    highlight = QColor(255, 255, 255, 26 if dark else 40)
    sheen.setColorAt(0.0, highlight)
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillRect(rect, QBrush(sheen))


def glyph_color(dark: bool) -> str:
    """Colour for the media-kind glyph drawn over a placeholder."""
    return "#FFFFFF" if dark else "#1B1D22"


def glyph_opacity() -> float:
    # Present enough to identify the media kind, faint enough that the tile
    # does not look like an error icon.
    return 0.62
