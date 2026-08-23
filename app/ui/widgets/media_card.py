"""Grid and list presentations of a library item.

Both share one contract: they show the minimum a user needs to recognise an
asset, keep every other action behind hover or the context menu, and emit the
same signals so the Library view can swap between them freely.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QToolButton, QWidget

from app.models.category import resolve_category
from app.models.media import MediaItem
from app.ui.theme import Size, Space, get_theme
from app.ui.widgets.common import (
    Badge,
    CategoryDot,
    ElidedLabel,
    hbox,
    icon_button,
    label,
    set_property,
    vbox,
)
from app.ui.widgets.thumbnail import Thumbnail
from app.utils.formatting import format_bytes, format_duration, relative_date

#: Uniform tile aspect for the library grid.
CARD_ASPECT = 16 / 9


def _fallback_icon(item: MediaItem) -> str:
    if item.is_audio:
        return "waveform" if item.category != "Music" else "music"
    return "video"


def _category_color(item: MediaItem) -> str:
    theme = get_theme()
    if theme is None:
        return "#7A8090"
    return theme.palette.category(resolve_category(item.category).accent)


class MediaCard(QFrame):
    """A grid tile: artwork, title, and one line of meta."""

    activated = Signal(object)          # MediaItem  (double-click / Enter)
    selected = Signal(object)           # MediaItem  (single click)
    favorite_toggled = Signal(object)   # MediaItem
    context_requested = Signal(object, object)   # MediaItem, global QPoint
    preview_requested = Signal(object)  # MediaItem

    def __init__(self, item: MediaItem, *, width: int = 200, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MediaCard")
        self.item = item
        self._is_selected = False
        self._is_playing = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = vbox(self, spacing=0, margins=(Space.sm, Space.sm, Space.sm, Space.sm))

        # -- Artwork ------------------------------------------------------
        # Every tile is 16:9 regardless of media kind. Mixing square audio art
        # with widescreen video in one grid produces ragged rows, and square
        # artwork letterboxes cleanly inside a 16:9 frame.
        self.thumb = Thumbnail(
            aspect=CARD_ASPECT,
            fallback_icon=_fallback_icon(item),
            parent=self,
        )
        self.thumb.set_placeholder(item.display_title, _category_color(item))
        self.thumb.set_source(item.thumbnail_path)
        if item.duration:
            self.thumb.set_duration(item.duration)
        if item.file_missing:
            self.thumb.set_dimmed(True)
            self.thumb.set_badge("MISSING")
        layout.addWidget(self.thumb)

        # Favourite star floats over the artwork, revealed on hover or when set.
        self._favorite_btn = QToolButton(self)
        self._favorite_btn.setAutoRaise(True)
        self._favorite_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._favorite_btn.setFixedSize(QSize(26, 26))
        self._favorite_btn.setIconSize(QSize(14, 14))
        self._favorite_btn.setToolTip("Favourite")
        self._favorite_btn.clicked.connect(lambda: self.favorite_toggled.emit(self.item))
        self._favorite_btn.setStyleSheet(
            "QToolButton { background: rgba(0,0,0,140); border-radius: 6px; }"
            "QToolButton:hover { background: rgba(0,0,0,190); }"
        )
        self._refresh_favorite_icon()

        layout.addSpacing(Space.sm)

        # -- Title --------------------------------------------------------
        self.title = ElidedLabel(item.display_title, "itemTitle", parent=self)
        layout.addWidget(self.title)

        layout.addSpacing(3)

        # -- Meta line ----------------------------------------------------
        meta_row = QWidget(self)
        meta_layout = hbox(meta_row, spacing=Space.xs)
        self._dot = CategoryDot(_category_color(item), 6, meta_row)
        meta_layout.addWidget(self._dot)
        self._meta = ElidedLabel(self._meta_text(), "muted", parent=meta_row)
        meta_layout.addWidget(self._meta, 1)
        layout.addWidget(meta_row)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.set_card_width(width)

    # -- Content ----------------------------------------------------------

    def _meta_text(self) -> str:
        item = self.item
        parts = [item.category]
        if item.is_audio:
            if item.duration:
                parts.append(format_duration(item.duration))
        elif item.height:
            parts.append(f"{item.height}p")
        elif item.duration:
            parts.append(format_duration(item.duration))
        if item.container:
            parts.append(item.container.upper())
        return "  ·  ".join(part for part in parts if part)

    def refresh(self, item: MediaItem | None = None) -> None:
        if item is not None:
            self.item = item
        self.title.setText(self.item.display_title)
        self._meta.setText(self._meta_text())
        self._dot.set_color(_category_color(self.item))
        self.thumb.set_source(self.item.thumbnail_path)
        self.thumb.set_dimmed(self.item.file_missing)
        self.thumb.set_badge("MISSING" if self.item.file_missing else "")
        self._refresh_favorite_icon()

    def _refresh_favorite_icon(self) -> None:
        # The star sits on a dark scrim over the artwork, so it uses fixed
        # colours rather than palette tones - a light-theme "warning" brown
        # would be invisible there.
        from app.ui.theme.icons import make_icon

        self._favorite_btn.setIcon(
            make_icon(
                "star",
                "#FFC94D" if self.item.favorite else "#FFFFFF",
                14,
                filled=self.item.favorite,
                dpr=self.devicePixelRatioF(),
            )
        )
        self._favorite_btn.setVisible(self.item.favorite or self.underMouse())

    def set_selected(self, value: bool) -> None:
        if self._is_selected == value:
            return
        self._is_selected = value
        set_property(self, "selected", "true" if value else "false")

    def set_card_width(self, width: int) -> None:
        """Resize the tile, keeping the artwork exactly 16:9."""
        self.setFixedWidth(width)
        inner = max(40, width - Space.sm * 2)
        self.thumb.setFixedHeight(int(round(inner / CARD_ASPECT)))

    # -- Interaction ------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._favorite_btn.move(self.width() - 26 - Space.sm - 4, Space.sm + 4)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.HoverEnter:
            self._favorite_btn.setVisible(True)
            self._favorite_btn.raise_()
            # A play affordance on the artwork tells the user the tile is
            # playable without them having to open it to find out.
            if self.item.exists:
                self.thumb.set_overlay_icon("play")
        elif event.type() == QEvent.Type.HoverLeave:
            self._favorite_btn.setVisible(self.item.favorite)
            if not self._is_playing:
                self.thumb.set_overlay_icon("")
        return super().event(event)

    def set_playing(self, playing: bool) -> None:
        self._is_playing = playing
        self.thumb.set_overlay_icon("pause" if playing else "")
        set_property(self, "playing", "true" if playing else "false")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.item)
            # Clicking the artwork of an audio tile auditions it; clicking the
            # text selects. Opening the full detail view is a double-click.
            if self.item.is_audio and self.item.exists and self.thumb.underMouse():
                self.preview_requested.emit(self.item)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.item)
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.item)
            return
        super().keyPressEvent(event)

    def _emit_context(self, position) -> None:
        self.selected.emit(self.item)
        self.context_requested.emit(self.item, self.mapToGlobal(position))


class MediaRow(QFrame):
    """A dense list row: the right shape for large sound-effect libraries."""

    COLUMN_WIDTHS = {
        "category": 130,
        "duration": 70,
        "format": 80,
        "size": 80,
        "added": 100,
    }

    activated = Signal(object)
    selected = Signal(object)
    favorite_toggled = Signal(object)
    context_requested = Signal(object, object)
    preview_requested = Signal(object)

    def __init__(self, item: MediaItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MediaRow")
        self.item = item
        self._is_selected = False
        self.setFixedHeight(Size.row_height)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context)

        layout = hbox(self, spacing=Space.md, margins=(Space.md, 0, Space.md, 0))

        # Small square artwork keeps the row scannable without dominating it.
        self.thumb = Thumbnail(
            radius=5,
            aspect=1.0,
            fallback_icon=_fallback_icon(item),
            parent=self,
        )
        self.thumb.setFixedSize(QSize(32, 32))
        self.thumb.set_placeholder(item.display_title, _category_color(item))
        self.thumb.set_source(item.thumbnail_path, max_edge=120)
        self.thumb.set_dimmed(item.file_missing)
        layout.addWidget(self.thumb)

        # Auditioning is the whole point of a sound-effects library, so the
        # play affordance sits on the row itself rather than behind a modal.
        self.preview_btn = icon_button(
            "play", tooltip="Preview", size=13, tone="text",
            on_click=lambda: self.preview_requested.emit(self.item),
        )
        self.preview_btn.setVisible(False)
        layout.addWidget(self.preview_btn)

        # Title + creator stacked in the flexible column.
        title_column = QWidget(self)
        title_layout = vbox(title_column, spacing=0)
        self.title = ElidedLabel(item.display_title, "itemTitle", parent=title_column)
        title_layout.addWidget(self.title)
        if item.creator:
            self.creator = ElidedLabel(item.creator, "muted", parent=title_column)
            title_layout.addWidget(self.creator)
        layout.addWidget(title_column, 1)

        if item.file_missing:
            layout.addWidget(Badge("MISSING", "danger", self))

        self._category = self._column(
            item.category, self.COLUMN_WIDTHS["category"], with_dot=True
        )
        layout.addWidget(self._category)

        self._duration = self._column(
            format_duration(item.duration) if item.duration else "—",
            self.COLUMN_WIDTHS["duration"],
            align=Qt.AlignmentFlag.AlignRight,
        )
        layout.addWidget(self._duration)

        self._format = self._column(self._format_text(), self.COLUMN_WIDTHS["format"])
        layout.addWidget(self._format)

        self._size = self._column(
            format_bytes(item.file_size) if item.file_size else "—",
            self.COLUMN_WIDTHS["size"],
            align=Qt.AlignmentFlag.AlignRight,
        )
        layout.addWidget(self._size)

        self._added = self._column(
            relative_date(item.downloaded_at), self.COLUMN_WIDTHS["added"]
        )
        layout.addWidget(self._added)

        self._favorite_btn = icon_button(
            "star", tooltip="Favourite", size=14,
            tone="warning" if item.favorite else "muted",
        )
        self._favorite_btn.clicked.connect(lambda: self.favorite_toggled.emit(self.item))
        self._refresh_favorite_icon()
        layout.addWidget(self._favorite_btn)

    def _column(
        self,
        text: str,
        width: int,
        *,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
        with_dot: bool = False,
    ) -> QWidget:
        holder = QWidget(self)
        holder.setFixedWidth(width)
        layout = hbox(holder, spacing=Space.xs)
        if with_dot:
            self._dot = CategoryDot(_category_color(self.item), 6, holder)
            layout.addWidget(self._dot)
        value = ElidedLabel(text, "meta", parent=holder)
        value.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(value, 1)
        holder.setProperty("valueLabel", value)
        return holder

    def _format_text(self) -> str:
        item = self.item
        if item.is_audio:
            if item.audio_bitrate:
                return f"{item.container.upper()} {item.audio_bitrate}k"
            return item.container.upper() or "—"
        if item.height:
            return f"{item.container.upper()} {item.height}p"
        return item.container.upper() or "—"

    def refresh(self, item: MediaItem | None = None) -> None:
        if item is not None:
            self.item = item
        self.title.setText(self.item.display_title)
        self.thumb.set_dimmed(self.item.file_missing)
        for holder, text in (
            (self._category, self.item.category),
            (self._duration, format_duration(self.item.duration) if self.item.duration else "—"),
            (self._format, self._format_text()),
            (self._size, format_bytes(self.item.file_size) if self.item.file_size else "—"),
            (self._added, relative_date(self.item.downloaded_at)),
        ):
            value = holder.property("valueLabel")
            if isinstance(value, QLabel):
                value.setText(text)
        self._refresh_favorite_icon()

    def _refresh_favorite_icon(self) -> None:
        theme = get_theme()
        if theme is None:
            return
        self._favorite_btn.setIcon(
            theme.icon("star", 14, "warning" if self.item.favorite else "muted",
                       filled=self.item.favorite)
        )

    def set_selected(self, value: bool) -> None:
        if self._is_selected == value:
            return
        self._is_selected = value
        set_property(self, "selected", "true" if value else "false")

    def event(self, event: QEvent) -> bool:
        # Swap the artwork for a play button while hovering an audio row, so
        # auditioning a folder of whooshes is one click each.
        if event.type() == QEvent.Type.HoverEnter and self.item.is_audio and self.item.exists:
            self.preview_btn.setVisible(True)
            self.thumb.setVisible(False)
        elif event.type() == QEvent.Type.HoverLeave:
            self.preview_btn.setVisible(False)
            self.thumb.setVisible(True)
        return super().event(event)

    def set_playing(self, playing: bool) -> None:
        """Reflect that this row is the one currently being previewed."""
        theme = get_theme()
        if theme is None:
            return
        self.preview_btn.setIcon(theme.icon("pause" if playing else "play", 13, "text"))
        if playing:
            self.preview_btn.setVisible(True)
            self.thumb.setVisible(False)
        set_property(self, "playing", "true" if playing else "false")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.item)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.item)
        super().mouseDoubleClickEvent(event)

    def _emit_context(self, position) -> None:
        self.selected.emit(self.item)
        self.context_requested.emit(self.item, self.mapToGlobal(position))


class MediaRowHeader(QWidget):
    """Column headings that line up with :class:`MediaRow`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(30)
        layout = hbox(self, spacing=Space.md, margins=(Space.md, 0, Space.md, 0))
        layout.addSpacing(30)   # artwork column
        layout.addWidget(label("Title", "fieldLabel"), 1)
        for key, text, align in (
            ("category", "Category", Qt.AlignmentFlag.AlignLeft),
            ("duration", "Length", Qt.AlignmentFlag.AlignRight),
            ("format", "Format", Qt.AlignmentFlag.AlignLeft),
            ("size", "Size", Qt.AlignmentFlag.AlignRight),
            ("added", "Added", Qt.AlignmentFlag.AlignLeft),
        ):
            heading = label(text, "fieldLabel")
            heading.setFixedWidth(MediaRow.COLUMN_WIDTHS[key])
            heading.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(heading)
        layout.addSpacing(26)   # favourite column
