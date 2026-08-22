"""Thumbnail rendering: rounded, aspect-correct artwork with graceful fallbacks.

Decoded pixmaps are shared through a small LRU cache so scrolling a large grid
does not re-decode the same JPEG hundreds of times.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.theme import Radius, get_theme
from app.ui.theme.icons import icon_pixmap
from app.utils.formatting import format_duration

_CACHE_LIMIT = 400
_cache: OrderedDict = OrderedDict()


def load_pixmap(path: str, max_edge: int = 640) -> QPixmap | None:
    """Load and downscale artwork, caching the result by path and size."""
    if not path:
        return None
    key = (path, max_edge)
    cached = _cache.get(key)
    if cached is not None:
        _cache.move_to_end(key)
        return cached if not cached.isNull() else None

    try:
        if not Path(path).is_file():
            return None
    except OSError:
        return None

    pixmap = QPixmap(path)
    if pixmap.isNull():
        _cache[key] = pixmap
        return None
    if max(pixmap.width(), pixmap.height()) > max_edge:
        pixmap = pixmap.scaled(
            max_edge,
            max_edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    _cache[key] = pixmap
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return pixmap


def clear_cache() -> None:
    _cache.clear()


class Thumbnail(QWidget):
    """Rounded artwork with a letterbox background and optional overlays.

    Falls back to a media-kind glyph when there is no image, so a card never
    shows an empty hole.
    """

    def __init__(
        self,
        *,
        radius: int = Radius.md,
        aspect: float = 16 / 9,
        fallback_icon: str = "video",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Thumbnail")
        self._radius = radius
        self._aspect = aspect
        self._fallback_icon = fallback_icon
        self._pixmap: QPixmap | None = None
        self._duration_text = ""
        self._badge_text = ""
        self._overlay_icon = ""
        self._dim = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

    # -- Content ----------------------------------------------------------

    def set_source(self, path: str, *, max_edge: int = 640) -> bool:
        self._pixmap = load_pixmap(path, max_edge)
        self.update()
        return self._pixmap is not None

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def set_fallback_icon(self, name: str) -> None:
        self._fallback_icon = name
        self.update()

    def set_duration(self, seconds: float | None) -> None:
        self._duration_text = format_duration(seconds) if seconds else ""
        self.update()

    def set_badge(self, text: str) -> None:
        self._badge_text = text or ""
        self.update()

    def set_overlay_icon(self, name: str) -> None:
        self._overlay_icon = name or ""
        self.update()

    def set_dimmed(self, dim: bool) -> None:
        if self._dim != dim:
            self._dim = dim
            self.update()

    def has_image(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    # -- Geometry ---------------------------------------------------------

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return int(width / self._aspect) if self._aspect else width

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return bool(self._aspect)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(200, int(200 / self._aspect) if self._aspect else 200)

    # -- Painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        theme = get_theme()
        if theme is None:
            return
        palette = theme.palette

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        painter.fillRect(rect, QColor(palette.thumb_bg))

        if self.has_image():
            self._paint_image(painter, rect)
        else:
            self._paint_fallback(painter, rect, palette)

        if self._dim:
            painter.fillRect(rect, QColor(0, 0, 0, 120))

        painter.setClipping(False)
        self._paint_overlays(painter, rect, palette)

        # Hairline so light-mode artwork does not float against a white card.
        pen = QPen(QColor(palette.border))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        painter.end()

    def _paint_image(self, painter: QPainter, rect: QRectF) -> None:
        pixmap = self._pixmap
        target = rect.size()
        scaled = pixmap.size().scaled(
            target.toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding
        )
        x = rect.x() + (rect.width() - scaled.width()) / 2
        y = rect.y() + (rect.height() - scaled.height()) / 2
        painter.drawPixmap(QRect(int(x), int(y), scaled.width(), scaled.height()), pixmap)

    def _paint_fallback(self, painter: QPainter, rect: QRectF, palette) -> None:
        glyph = icon_pixmap(
            self._fallback_icon,
            palette.text_muted,
            28,
            dpr=self.devicePixelRatioF(),
        )
        ratio = glyph.devicePixelRatio() or 1.0
        width = glyph.width() / ratio
        height = glyph.height() / ratio
        painter.setOpacity(0.55)
        painter.drawPixmap(
            int(rect.center().x() - width / 2),
            int(rect.center().y() - height / 2),
            glyph,
        )
        painter.setOpacity(1.0)

    def _paint_overlays(self, painter: QPainter, rect: QRectF, palette) -> None:
        if self._overlay_icon:
            glyph = icon_pixmap(
                self._overlay_icon, "#FFFFFF", 20, filled=True, dpr=self.devicePixelRatioF()
            )
            ratio = glyph.devicePixelRatio() or 1.0
            size = 34
            cx, cy = rect.center().x(), rect.center().y()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 130)))
            painter.drawEllipse(QRectF(cx - size / 2, cy - size / 2, size, size))
            painter.drawPixmap(
                int(cx - glyph.width() / ratio / 2 + 1),
                int(cy - glyph.height() / ratio / 2),
                glyph,
            )

        if self._duration_text:
            self._paint_pill(painter, rect, self._duration_text, corner="br")
        if self._badge_text:
            self._paint_pill(painter, rect, self._badge_text, corner="tl")

    def _paint_pill(self, painter: QPainter, rect: QRectF, text: str, *, corner: str) -> None:
        font = QFont(painter.font())
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        pad_x, pad_y, margin = 5, 2, 6
        width = metrics.horizontalAdvance(text) + pad_x * 2
        height = metrics.height() + pad_y * 2

        if corner == "br":
            x = rect.right() - width - margin
            y = rect.bottom() - height - margin
        else:
            x = rect.left() + margin
            y = rect.top() + margin

        pill = QRectF(x, y, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 165)))
        painter.drawRoundedRect(pill, 3, 3)
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
