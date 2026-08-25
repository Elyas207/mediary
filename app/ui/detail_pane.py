"""The right-hand rail: everything known about one item.

A docked pane rather than a modal, because the job it supports - working
through a shelf of near-identical sound effects deciding which is the right
one - means selecting the next item constantly. A dialog per file would make
that unbearable.

Licensing lives here as three plain fields the user fills in. Mediary does not
determine, detect or verify any of it, so nothing on this pane may look like a
verdict: no ticks, no "verified", no green.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QWidget,
)

from app.models.media import (
    ATTRIBUTION_OPTIONS,
    LICENSE_OPTIONS,
    MediaItem,
)
from app.ui.theme import Radius, Size, Space
from app.ui.widgets.common import (
    Badge,
    ElidedLabel,
    EmptyState,
    FlowLayout,
    TagChip,
    WrappedLabel,
    button,
    divider,
    hbox,
    icon_button,
    label,
    vbox,
)
from app.ui.widgets.thumbnail import Thumbnail
from app.utils.formatting import (
    format_bitrate,
    format_bytes,
    format_date,
    format_duration,
)


class MetaRow(QWidget):
    """``Duration        3:45`` - a label on the left, its value on the right."""

    def __init__(
        self,
        name: str,
        value: str = "",
        *,
        mono: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = hbox(self, spacing=Space.sm, margins=(0, 3, 0, 3))

        self._name = label(name, "meta", parent=self)
        self._name.setFixedWidth(78)
        layout.addWidget(self._name, 0, Qt.AlignmentFlag.AlignTop)

        self._value = ElidedLabel(value, "mono" if mono else "", parent=self)
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._value, 1)

    def set_value(self, value: str) -> None:
        self._value.setText(value or "—")

    def set_widget(self, widget: QWidget) -> None:
        """Swap the value for a real widget - a chip, a copy button, a row."""
        layout = self.layout()
        layout.replaceWidget(self._value, widget)
        self._value.hide()
        self._value.deleteLater()
        self._value = widget


class DetailPane(QFrame):
    """Everything Mediary knows about the selected item."""

    #: The user edited something that needs writing back.
    item_changed = Signal(object)         # MediaItem
    favorite_toggled = Signal(object)     # MediaItem
    open_requested = Signal(object)
    reveal_requested = Signal(object)
    close_requested = Signal()

    WIDTH = 320

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DetailPane")
        self.setFixedWidth(self.WIDTH)

        self.item: MediaItem | None = None
        self._loading = False
        #: Text areas that write back when focus leaves them.
        self._commit_on_blur: set = set()

        outer = vbox(self, spacing=0)
        outer.addWidget(self._build_header())

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        self._body = QWidget()
        self._body_layout = vbox(
            self._body, spacing=Space.md, margins=(Space.lg, Space.md, Space.lg, Space.lg)
        )
        self._build_body()
        self._body_layout.addStretch(1)
        self._scroll.setWidget(self._body)

        self._empty = EmptyState(
            icon="eye",
            title="Nothing selected",
            body="Pick something from your library and its details land here.",
            parent=self,
        )
        self._empty.set_text_width(self.WIDTH - 2 * Space.xl)
        outer.addWidget(self._empty, 1)

        self.clear()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        header.setObjectName("DetailHeader")
        header.setFixedHeight(Size.topbar_height)
        layout = hbox(header, spacing=Space.sm, margins=(Space.lg, 0, Space.md, 0))

        layout.addWidget(label("Media Detail", "heading", parent=header))
        layout.addStretch(1)

        self._close_btn = icon_button("close", tooltip="Hide this pane", size=Size.icon_sm)
        self._close_btn.clicked.connect(self.close_requested.emit)
        layout.addWidget(self._close_btn)
        return header

    def _build_body(self) -> None:
        layout = self._body_layout

        self.thumb = Thumbnail(radius=Radius.lg, aspect=16 / 10, parent=self._body)
        self.thumb.setMinimumHeight(150)
        layout.addWidget(self.thumb)

        # -- Title block ---------------------------------------------------
        title_row = QWidget(self._body)
        title_layout = hbox(title_row, spacing=Space.sm)

        title_column = vbox(spacing=2)
        self.title = WrappedLabel("", "heading", self.WIDTH - 90, title_row)
        title_column.addWidget(self.title)

        self.creator = ElidedLabel("", "muted", parent=title_row)
        title_column.addWidget(self.creator)

        source_row = QWidget(title_row)
        source_layout = hbox(source_row, spacing=Space.xs)
        self.platform = Badge("", parent=source_row)
        source_layout.addWidget(self.platform)
        self.uploaded = label("", "meta", parent=source_row)
        source_layout.addWidget(self.uploaded)
        source_layout.addStretch(1)
        title_column.addWidget(source_row)

        title_layout.addLayout(title_column, 1)

        self.favorite_btn = icon_button(
            "star", tooltip="Favourite", size=Size.icon, checkable=True
        )
        self.favorite_btn.clicked.connect(self._on_favorite)
        title_layout.addWidget(self.favorite_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(title_row)

        layout.addWidget(divider(parent=self._body))

        # -- Tabs ----------------------------------------------------------
        self.tabs = QTabWidget(self._body)
        self.tabs.setObjectName("DetailTabs")
        self.tabs.addTab(self._tab_details(), "Details")
        self.tabs.addTab(self._tab_license(), "License")
        self.tabs.addTab(self._tab_tags(), "Tags")
        layout.addWidget(self.tabs)

        # -- Actions -------------------------------------------------------
        actions = QWidget(self._body)
        actions_layout = hbox(actions, spacing=Space.sm)
        self._open_btn = button("Open", variant="secondary", size="sm", icon="play")
        self._open_btn.clicked.connect(lambda: self._emit_with_item(self.open_requested))
        actions_layout.addWidget(self._open_btn, 1)
        self._reveal_btn = button("Show in folder", variant="subtle", size="sm", icon="folder")
        self._reveal_btn.clicked.connect(lambda: self._emit_with_item(self.reveal_requested))
        actions_layout.addWidget(self._reveal_btn, 1)
        layout.addWidget(actions)

    def _tab_details(self) -> QWidget:
        page = QWidget(self)
        layout = vbox(page, spacing=0, margins=(0, Space.sm, 0, 0))

        self._rows: dict = {}
        for key, name in (
            ("type", "Type"),
            ("duration", "Duration"),
            ("format", "Format"),
            ("bitrate", "Bitrate"),
            ("resolution", "Resolution"),
            ("size", "Size"),
        ):
            row = MetaRow(name, parent=page)
            self._rows[key] = row
            layout.addWidget(row)

        category_row = MetaRow("Category", parent=page)
        self.category_chip = Badge("", "accent", category_row)
        category_row.set_widget(self._right_aligned(self.category_chip, category_row))
        layout.addWidget(category_row)

        layout.addSpacing(Space.sm)
        layout.addWidget(divider(parent=page))
        layout.addSpacing(Space.sm)

        source_row = MetaRow("Source", parent=page)
        source_holder = QWidget(source_row)
        source_layout = hbox(source_holder, spacing=Space.xs)
        source_layout.addStretch(1)
        self.source_url = ElidedLabel("", "mono", parent=source_holder)
        self.source_url.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        source_layout.addWidget(self.source_url, 1)
        copy_url = icon_button("copy", tooltip="Copy the source URL", size=Size.icon_sm)
        copy_url.clicked.connect(lambda: self._copy(self.item.source_url if self.item else ""))
        source_layout.addWidget(copy_url)
        source_row.set_widget(source_holder)
        layout.addWidget(source_row)

        for key, name in (("downloaded", "Downloaded"), ("added", "Added")):
            row = MetaRow(name, parent=page)
            self._rows[key] = row
            layout.addWidget(row)

        path_row = MetaRow("File path", parent=page)
        path_holder = QWidget(path_row)
        path_layout = hbox(path_holder, spacing=Space.xs)
        path_layout.addStretch(1)
        self.file_path = ElidedLabel(
            "", "mono", mode=Qt.TextElideMode.ElideLeft, parent=path_holder
        )
        self.file_path.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        path_layout.addWidget(self.file_path, 1)
        copy_path = icon_button("copy", tooltip="Copy the file path", size=Size.icon_sm)
        copy_path.clicked.connect(lambda: self._copy(str(self.item.file_path) if self.item else ""))
        path_layout.addWidget(copy_path)
        path_row.set_widget(path_holder)
        layout.addWidget(path_row)

        layout.addStretch(1)
        return page

    def _tab_license(self) -> QWidget:
        page = QWidget(self)
        layout = vbox(page, spacing=Space.sm, margins=(0, Space.sm, 0, 0))

        # This sentence is the whole reason this tab looks the way it does.
        # Everything below is a field the user fills in, and nothing on this
        # pane is allowed to read as a verdict Mediary reached.
        layout.addWidget(
            WrappedLabel(
                "Mediary never works out whether you may use something. "
                "Being able to download it says nothing about the rights. "
                "Record what you have checked yourself.",
                "meta",
                self.WIDTH - 56,
                page,
            )
        )
        layout.addSpacing(Space.xs)

        layout.addWidget(label("License", "fieldLabel", parent=page))
        self.license_box = QComboBox(page)
        for option in LICENSE_OPTIONS:
            self.license_box.addItem(option, option)
        self.license_box.currentIndexChanged.connect(self._on_edited)
        layout.addWidget(self.license_box)

        layout.addWidget(label("License URL", "fieldLabel", parent=page))
        self.license_url = QLineEdit(page)
        self.license_url.setPlaceholderText("https://…")
        self.license_url.editingFinished.connect(self._on_edited)
        layout.addWidget(self.license_url)

        layout.addWidget(label("Attribution required", "fieldLabel", parent=page))
        self.attribution_box = QComboBox(page)
        for option in ATTRIBUTION_OPTIONS:
            self.attribution_box.addItem(option, option)
        self.attribution_box.currentIndexChanged.connect(self._on_edited)
        layout.addWidget(self.attribution_box)

        layout.addWidget(label("Notes", "fieldLabel", parent=page))
        self.license_notes = QPlainTextEdit(page)
        self.license_notes.setPlaceholderText("Credit the creator in the description…")
        self.license_notes.setFixedHeight(60)
        self._commit_when_blurred(self.license_notes)
        layout.addWidget(self.license_notes)

        layout.addStretch(1)
        return page

    def _tab_tags(self) -> QWidget:
        page = QWidget(self)
        layout = vbox(page, spacing=Space.sm, margins=(0, Space.sm, 0, 0))

        self._tag_holder = QWidget(page)
        self._tag_flow = FlowLayout(self._tag_holder)
        layout.addWidget(self._tag_holder)

        self.tag_input = QLineEdit(page)
        self.tag_input.setPlaceholderText("Add a tag and press Enter…")
        self.tag_input.returnPressed.connect(self._add_tag_from_input)
        layout.addWidget(self.tag_input)

        layout.addSpacing(Space.xs)
        layout.addWidget(label("Notes", "fieldLabel", parent=page))
        self.notes = QPlainTextEdit(page)
        self.notes.setPlaceholderText("Anything worth remembering about this one…")
        self.notes.setFixedHeight(76)
        self._commit_when_blurred(self.notes)
        layout.addWidget(self.notes)

        layout.addStretch(1)
        return page

    @staticmethod
    def _right_aligned(widget: QWidget, parent: QWidget) -> QWidget:
        holder = QWidget(parent)
        layout = hbox(holder, spacing=0)
        layout.addStretch(1)
        layout.addWidget(widget)
        return holder

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        """Commit a text area when focus leaves it, not on every keystroke.

        An event filter rather than a reassigned ``focusOutEvent``: patching a
        virtual onto an instance works by accident of how PySide dispatches,
        and silently stops working if that ever changes. A dropped edit is not
        something the user would notice until the note was gone.
        """
        if event.type() == QEvent.Type.FocusOut and watched in self._commit_on_blur:
            self._on_edited()
        return super().eventFilter(watched, event)

    def _commit_when_blurred(self, widget: QPlainTextEdit) -> None:
        self._commit_on_blur.add(widget)
        widget.installEventFilter(self)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self.item = None
        self._scroll.hide()
        self._empty.show()

    def show_item(self, item: MediaItem | None) -> None:
        """Render one library item, or fall back to the empty state."""
        if item is None:
            self.clear()
            return

        self._loading = True
        try:
            self.item = item
            self._empty.hide()
            self._scroll.show()

            self.title.setText(item.title or item.filename)
            self.creator.setText(item.creator or "Unknown creator")
            self.platform.setText(item.platform or "Local")
            self.uploaded.setText(format_date(item.upload_date) if item.upload_date else "")
            self.favorite_btn.setChecked(bool(item.favorite))

            if item.thumbnail_path:
                self.thumb.set_source(item.thumbnail_path, max_edge=640)
            else:
                self.thumb.set_source("")
            self.thumb.set_fallback_icon("audio" if item.is_audio else "video")
            if item.duration:
                self.thumb.set_duration(item.duration)

            self._rows["type"].set_value(item.media_kind.title() or "—")
            self._rows["duration"].set_value(format_duration(item.duration))
            self._rows["format"].set_value(item.container.upper() or "—")
            self._rows["bitrate"].set_value(format_bitrate(item.audio_bitrate))
            self._rows["resolution"].set_value(item.resolution or "—")
            self._rows["size"].set_value(format_bytes(item.file_size))
            self._rows["downloaded"].set_value(
                format_date(item.downloaded_at) if item.downloaded_at else "—"
            )
            self._rows["added"].set_value(
                format_date(item.downloaded_at) if item.downloaded_at else "—"
            )
            self.category_chip.setText(item.category or "Other")
            self.source_url.setText(item.source_url or "—")
            self.source_url.setToolTip(item.source_url or "")
            self.file_path.setText(str(item.file_path) or "—")
            self.file_path.setToolTip(str(item.file_path))

            self._select(self.license_box, item.license_type)
            self.license_url.setText(item.license_url)
            self._select(self.attribution_box, item.attribution_required)
            self.license_notes.setPlainText(item.license_notes)
            self.notes.setPlainText(item.notes)
            self._render_tags()
        finally:
            self._loading = False

    @staticmethod
    def _select(box: QComboBox, value: str) -> None:
        index = box.findData(value)
        box.setCurrentIndex(max(0, index))

    def _render_tags(self) -> None:
        while self._tag_flow.count():
            widget = self._tag_flow.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        if self.item is None:
            return
        for name in self.item.tags:
            chip = TagChip(name, removable=True, parent=self._tag_holder)
            chip.removed.connect(self._remove_tag)
            self._tag_flow.addWidget(chip)

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def _on_edited(self, *_args) -> None:
        if self._loading or self.item is None:
            return
        self.item.license_type = self.license_box.currentData() or ""
        self.item.license_url = self.license_url.text().strip()
        self.item.attribution_required = self.attribution_box.currentData() or ""
        self.item.license_notes = self.license_notes.toPlainText().strip()
        self.item.notes = self.notes.toPlainText().strip()
        self.item_changed.emit(self.item)

    def _add_tag_from_item(self, name: str) -> None:
        if self.item is None:
            return
        name = name.strip()
        if not name or any(t.casefold() == name.casefold() for t in self.item.tags):
            return
        self.item.tags.append(name)
        self._render_tags()
        self.item_changed.emit(self.item)

    def _add_tag_from_input(self) -> None:
        self._add_tag_from_item(self.tag_input.text())
        self.tag_input.clear()

    def _remove_tag(self, name: str) -> None:
        if self.item is None:
            return
        self.item.tags = [t for t in self.item.tags if t != name]
        self._render_tags()
        self.item_changed.emit(self.item)

    def _on_favorite(self) -> None:
        if self.item is None:
            return
        self.item.favorite = self.favorite_btn.isChecked()
        self.favorite_toggled.emit(self.item)

    def _emit_with_item(self, signal) -> None:
        if self.item is not None:
            signal.emit(self.item)

    @staticmethod
    def _copy(text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)

    def refresh_theme(self) -> None:
        if self.item is not None:
            self.show_item(self.item)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(self.WIDTH, 600)


__all__ = ["DetailPane", "MetaRow"]
