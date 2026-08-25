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
    QProgressBar,
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
from app.utils.formatting import format_bytes

#: ``(key, label, icon, section)`` - the whole navigation model in one place.
NAV_ITEMS: tuple = (
    ("download", "Download", "download", "DOWNLOAD"),
    ("queue", "Queue", "queue", "DOWNLOAD"),
    ("all", "All Media", "layers", "LIBRARY"),
    ("video", "Video", "video", "LIBRARY"),
    ("audio", "Audio", "audio", "LIBRARY"),
    ("music", "Music", "music", "LIBRARY"),
    ("sfx", "Sound Effects", "waveform", "LIBRARY"),
    ("inspiration", "Inspiration", "sparkle", "LIBRARY"),
    ("favorites", "Favourites", "star", "LIBRARY"),
    ("recent", "Recent", "clock", "LIBRARY"),
    ("tags", "Tags", "tag", "TOOLS"),
    ("settings", "Settings", "settings", "TOOLS"),
)

#: Entries whose number is live activity rather than a library total. These
#: read as a filled pill so a queue of three does not look like a folder of
#: three.
BADGE_KEYS: frozenset = frozenset({"queue", "recent"})

#: Which library filter each nav key selects.
NAV_FILTERS: dict = {
    "all": {},
    "video": {"media_kind": "video"},
    "audio": {"media_kind": "audio"},
    "sfx": {"category": "Sound Effects"},
    "music": {"category": "Music"},
    "inspiration": {"category": "Inspiration"},
    "favorites": {"favorites_only": True},
    "recent": {"sort": "recent"},
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
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._count.setFixedHeight(16)
        self._count.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._count.hide()
        layout.addWidget(self._count, 0, Qt.AlignmentFlag.AlignVCenter)

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
        # An empty badge would still paint its pill, so hide the label rather
        # than leaving a blue block sitting next to "Queue".
        self._count.setText(f"{value:,}" if value else "")
        self._count.setVisible(bool(value))

    def set_badge(self, on: bool) -> None:
        """Render the count as a filled pill rather than plain text."""
        self._count.setProperty("badge", "true" if on else "false")
        style = self._count.style()
        style.unpolish(self._count)
        style.polish(self._count)

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


class StorageMeter(QFrame):
    """Free space on the drive holding the library.

    Downloading is the one thing this app does that can fill a disk, so the
    number belongs where it is always visible rather than buried in settings.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StorageMeter")
        layout = vbox(self, spacing=Space.xs, margins=(Space.sm, Space.sm, Space.sm, Space.sm))

        self._title = QLabel("Storage", self)
        self._title.setObjectName("StorageTitle")
        layout.addWidget(self._title)

        self._detail = QLabel("—", self)
        self._detail.setObjectName("StorageDetail")
        layout.addWidget(self._detail)

        self._bar = QProgressBar(self)
        self._bar.setObjectName("StorageBar")
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        self._bar.setRange(0, 1000)
        self._bar.setValue(0)
        layout.addWidget(self._bar)

        self.hide()

    def set_values(self, free: int, total: int) -> None:
        if total <= 0:
            self.hide()
            return
        used = max(0, total - free)
        self._detail.setText(f"{format_bytes(free)} free of {format_bytes(total)}")
        self._bar.setValue(int(round(used / total * 1000)))
        # Only shout about it when it actually matters.
        low = free < total * 0.1
        self._bar.setProperty("tone", "danger" if low else "")
        style = self._bar.style()
        style.unpolish(self._bar)
        style.polish(self._bar)
        self.show()


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
        header.setFixedHeight(Size.topbar_height + 14)
        layout = hbox(header, spacing=Space.sm, margins=(Space.lg, 0, Space.md, 0))

        self._mark = MediaryMark(header)
        layout.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)

        words = vbox(spacing=0)
        wordmark = QLabel("Mediary", header)
        wordmark.setObjectName("SidebarBrand")
        words.addWidget(wordmark)

        tagline = QLabel("Find it. Fetch it. Organise it.", header)
        tagline.setObjectName("SidebarTagline")
        words.addWidget(tagline)

        layout.addLayout(words, 1)
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
            btn.set_badge(key in BADGE_KEYS)
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

        self._storage = StorageMeter(footer)
        layout.addWidget(self._storage)
        return footer

    def set_storage(self, free: int, total: int) -> None:
        """Show how much room is left where the library lives."""
        self._storage.set_values(free, total)

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
            "recent": counts.get("recent", 0),
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
