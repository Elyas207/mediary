"""Primary navigation.

Grouped, small-caps sections with a single active item - the convention every
serious desktop tool uses, because it stays readable as the list grows.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from app.ui.theme import Size, Space, get_theme
from app.ui.widgets.common import (
    SectionLabel,
    hbox,
    label,
    vbox,
)

#: ``(key, label, icon, section)`` - the whole navigation model in one place.
NAV_ITEMS: tuple = (
    ("download", "Download", "download", "DOWNLOAD"),
    ("queue", "Queue", "queue", "DOWNLOAD"),
    ("all", "All Media", "layers", "LIBRARY"),
    ("video", "Video", "video", "LIBRARY"),
    ("audio", "Audio", "audio", "LIBRARY"),
    ("sfx", "Sound Effects", "waveform", "LIBRARY"),
    ("music", "Music", "music", "LIBRARY"),
    ("inspiration", "Inspiration", "sparkle", "LIBRARY"),
    ("favorites", "Favourites", "star", "LIBRARY"),
    ("tags", "Tags", "tag", "ORGANISE"),
    ("settings", "Settings", "settings", "ORGANISE"),
)

#: Which library filter each nav key selects.
NAV_FILTERS: dict = {
    "all": {},
    "video": {"media_kind": "video"},
    "audio": {"media_kind": "audio"},
    "sfx": {"category": "Sound Effects"},
    "music": {"category": "Music"},
    "inspiration": {"category": "Inspiration"},
    "favorites": {"favorites_only": True},
}


class NavButton(QPushButton):
    """One navigation entry: icon, label and an optional right-aligned count."""

    def __init__(self, key: str, text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavItem")
        self.key = key
        self.icon_name = icon_name
        self._progress = 0.0
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(30)

        layout = hbox(self, spacing=Space.sm, margins=(Space.sm, 0, Space.sm, 0))

        self._glyph = QLabel(self)
        self._glyph.setFixedSize(QSize(Size.icon, Size.icon))
        self._glyph.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._glyph)

        self._text = QLabel(text, self)
        self._text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._text, 1)

        self._count = QLabel("", self)
        self._count.setObjectName("NavCount")
        self._count.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._count)

        self.toggled.connect(lambda _checked: self.refresh_icon())
        self.refresh_icon()

    def refresh_icon(self) -> None:
        theme = get_theme()
        if theme is None:
            return
        tone = "text" if self.isChecked() else "muted"
        self._glyph.setPixmap(theme.pixmap(self.icon_name, Size.icon, tone))
        colour = theme.palette.text if self.isChecked() else theme.palette.text_secondary
        weight = 600 if self.isChecked() else 500
        self._text.setStyleSheet(
            f"background: transparent; border: none; color: {colour}; font-weight: {weight};"
        )

    def set_count(self, value: int | None) -> None:
        self._count.setText(str(value) if value else "")

    def set_progress(self, fraction: float) -> None:
        """Show a hairline of progress under this entry.

        Downloads run in the background while the user is somewhere else
        entirely, so the sidebar carries the only always-visible signal that
        work is happening.
        """
        fraction = max(0.0, min(1.0, fraction))
        if abs(fraction - self._progress) < 0.005:
            return
        self._progress = fraction
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        if self._progress <= 0:
            return
        theme = get_theme()
        if theme is None:
            return

        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        width = (self.width() - Space.sm * 2) * self._progress
        painter.fillRect(
            QRectF(Space.sm, self.height() - 3, width, 2),
            QColor(theme.palette.accent),
        )
        painter.end()


class Sidebar(QFrame):
    """The application's left navigation rail."""

    navigate = Signal(str)          # nav key
    new_download = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(Size.sidebar_width)

        self._buttons: dict = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._badge_text = ""

        outer = vbox(self, spacing=0, margins=(0, 0, 0, 0))
        outer.addWidget(self._build_header())
        outer.addSpacing(Space.xs)
        outer.addWidget(self._build_nav(), 1)
        outer.addWidget(self._build_footer())

    # -- Construction -----------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        header.setFixedHeight(Size.topbar_height)
        layout = hbox(header, spacing=Space.sm, margins=(Space.lg, 0, Space.md, 0))

        self._mark = MediaryMark(header)
        layout.addWidget(self._mark)

        wordmark = QLabel("Mediary", header)
        wordmark.setObjectName("SidebarBrand")
        layout.addWidget(wordmark)
        layout.addStretch(1)
        return header

    def _build_nav(self) -> QWidget:
        container = QWidget(self)
        layout = vbox(container, spacing=1, margins=(Space.sm, 0, Space.sm, Space.sm))

        current_section = ""
        for key, text, icon_name, section in NAV_ITEMS:
            if section != current_section:
                if current_section:
                    layout.addSpacing(Space.lg)
                heading = SectionLabel(section, container)
                heading.setContentsMargins(Space.sm, 0, 0, Space.xs)
                layout.addWidget(heading)
                current_section = section

            btn = NavButton(key, text, icon_name, container)
            btn.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            self._group.addButton(btn)
            layout.addWidget(btn)
            self._buttons[key] = btn

        layout.addStretch(1)
        return container

    def _build_footer(self) -> QWidget:
        footer = QWidget(self)
        layout = vbox(footer, spacing=Space.sm, margins=(Space.md, Space.sm, Space.md, Space.md))

        self._status = label("", "muted", wrap=True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._status)
        return footer

    # -- State ------------------------------------------------------------

    def set_active(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        for btn in self._buttons.values():
            btn.refresh_icon()

    def active_key(self) -> str:
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return "download"

    def set_counts(self, counts: dict) -> None:
        """Update the right-aligned totals next to library entries."""
        mapping = {
            "all": counts.get("all", 0),
            "video": counts.get("video", 0),
            "audio": counts.get("audio", 0),
            "sfx": counts.get("Sound Effects", 0),
            "music": counts.get("Music", 0),
            "inspiration": counts.get("Inspiration", 0),
            "favorites": counts.get("favorites", 0),
            "tags": counts.get("tags", 0),
        }
        for key, value in mapping.items():
            button = self._buttons.get(key)
            if button is not None:
                button.set_count(value)

    def set_queue_badge(self, active: int) -> None:
        button = self._buttons.get("queue")
        if button is not None:
            button.set_count(active or None)

    def set_queue_progress(self, fraction: float) -> None:
        """Overall download progress, drawn under the Queue entry."""
        button = self._buttons.get("queue")
        if button is not None:
            button.set_progress(fraction)

    def set_status_text(self, text: str) -> None:
        self._status.setText(text)

    def refresh_theme(self) -> None:
        for btn in self._buttons.values():
            btn.refresh_icon()
        self._mark.update()


class MediaryMark(QWidget):
    """The Mediary glyph: a play triangle nested in a rounded square.

    Drawn rather than shipped as an asset so it recolours with the theme.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(22, 22))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        theme = get_theme()
        if theme is None:
            return
        palette = theme.palette

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.accent))
        painter.drawRoundedRect(rect, 6, 6)

        # An off-centre play mark reads as motion rather than a generic button.
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPolygonF

        cx, cy = rect.center().x() + 1.2, rect.center().y() + 0.5
        triangle = QPolygonF(
            [
                QPointF(cx - 3.2, cy - 4.4),
                QPointF(cx + 4.4, cy),
                QPointF(cx - 3.2, cy + 4.4),
            ]
        )
        painter.setBrush(QColor(palette.accent_text))
        painter.drawPolygon(triangle)
        painter.end()
