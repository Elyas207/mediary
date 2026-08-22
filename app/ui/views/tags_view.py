"""Tag management: rename, merge and delete the vocabulary of the library."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QInputDialog,
    QMenu,
    QMessageBox,
    QScrollArea,
    QWidget,
)

from app.services.library_service import LibraryService
from app.ui.theme import Space, get_theme
from app.ui.widgets.common import (
    EmptyState,
    FlowLayout,
    SearchInput,
    button,
    divider,
    hbox,
    label,
    panel,
    vbox,
)


class TagPill(QFrame):
    """One tag with its usage count and a context menu."""

    clicked = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, name: str, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.count = count
        self.setObjectName("Chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        layout = hbox(self, spacing=Space.sm, margins=(Space.md, Space.sm, Space.md, Space.sm))
        layout.addWidget(label(name, "itemTitle"))
        counter = label(str(count), "muted")
        counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(counter)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)

    def _menu(self, position) -> None:
        theme = get_theme()
        menu = QMenu(self)
        show = menu.addAction(theme.icon("library", 14, "secondary"), "Show tagged media")
        show.triggered.connect(lambda: self.clicked.emit(self.name))
        rename = menu.addAction(theme.icon("edit", 14, "secondary"), "Rename…")
        rename.triggered.connect(lambda: self.rename_requested.emit(self.name))
        menu.addSeparator()
        delete = menu.addAction(theme.icon("trash", 14, "secondary"), "Delete tag")
        delete.triggered.connect(lambda: self.delete_requested.emit(self.name))
        menu.exec(self.mapToGlobal(position))


class TagsView(QWidget):
    """Browse and curate the tag vocabulary."""

    tag_selected = Signal(str)
    tags_changed = Signal()

    def __init__(self, library: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._library = library
        self._tags: list = []

        root = vbox(self, spacing=0)
        root.addWidget(self._build_header())
        root.addWidget(divider())

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll, 1)

        content = QWidget(self._scroll)
        content_layout = vbox(
            content, spacing=Space.lg, margins=(Space.xxl, Space.lg, Space.xxl, Space.xxl)
        )

        card = panel(parent=content)
        card_layout = vbox(card, spacing=Space.sm, margins=(Space.lg, Space.lg, Space.lg, Space.lg))
        self._flow_holder = QWidget(card)
        self._flow = FlowLayout(self._flow_holder, h_spacing=Space.sm, v_spacing=Space.sm)
        card_layout.addWidget(self._flow_holder)
        content_layout.addWidget(card)
        content_layout.addStretch(1)

        self._scroll.setWidget(content)

        self._empty = EmptyState(
            icon="tag",
            title="No tags yet",
            body=(
                "Tags are how a library stays findable once it grows. Add them from any "
                "item's detail view — whoosh, cinematic, dark, transition."
            ),
            parent=self,
        )
        root.addWidget(self._empty, 1)

        self.reload()

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        layout = vbox(header, spacing=Space.md, margins=(Space.xxl, Space.xl, Space.xxl, Space.md))

        title_row = QWidget(header)
        title_layout = hbox(title_row, spacing=Space.md)
        title_layout.addWidget(label("Tags", "pageTitle"))
        title_layout.addStretch(1)

        self.search = SearchInput("Filter tags", title_row)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(lambda _: self._render())
        title_layout.addWidget(self.search)

        title_layout.addWidget(
            button("Remove unused", variant="ghost", size="sm", on_click=self._prune)
        )
        layout.addWidget(title_row)

        self._summary = label("", "fieldLabel")
        layout.addWidget(self._summary)
        return header

    # ------------------------------------------------------------------

    def reload(self) -> None:
        try:
            self._tags = self._library.all_tags(with_counts=True)
        except Exception:  # noqa: BLE001
            self._tags = []
        self._render()

    def _render(self) -> None:
        self._flow.clear()
        needle = self.search.text().strip().lower()
        visible = [
            (name, count) for name, count in self._tags if not needle or needle in name.lower()
        ]

        has_any = bool(self._tags)
        self._scroll.setVisible(has_any)
        self._empty.setVisible(not has_any)

        if not has_any:
            self._summary.setText("")
            return

        used = sum(1 for _, count in self._tags if count)
        self._summary.setText(
            f"{len(self._tags)} TAG{'S' if len(self._tags) != 1 else ''}   ·   "
            f"{used} IN USE"
        )

        for name, count in visible:
            pill = TagPill(name, count, self._flow_holder)
            pill.clicked.connect(self.tag_selected.emit)
            pill.rename_requested.connect(self._rename)
            pill.delete_requested.connect(self._delete)
            self._flow.addWidget(pill)

    def _rename(self, name: str) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename tag", "New name:", text=name)
        if not ok:
            return
        new_name = " ".join(new_name.split()).strip()
        if not new_name or new_name == name:
            return
        existing = {t.lower() for t, _ in self._tags}
        if new_name.lower() in existing:
            answer = QMessageBox.question(
                self,
                "Merge tags",
                f"“{new_name}” already exists. Merge “{name}” into it?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._library.rename_tag(name, new_name)
        self.reload()
        self.tags_changed.emit()

    def _delete(self, name: str) -> None:
        count = next((c for n, c in self._tags if n == name), 0)
        answer = QMessageBox.question(
            self,
            "Delete tag",
            f"Delete the tag “{name}”?\n\n"
            + (
                f"It will be removed from {count} item{'s' if count != 1 else ''}. "
                "No files are affected."
                if count
                else "It is not used by anything."
            ),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._library.delete_tag(name)
        self.reload()
        self.tags_changed.emit()

    def _prune(self) -> None:
        removed = self._library.prune_orphan_tags()
        self.reload()
        if removed:
            self.tags_changed.emit()
        QMessageBox.information(
            self,
            "Unused tags",
            f"Removed {removed} unused tag{'s' if removed != 1 else ''}."
            if removed
            else "Every tag is in use.",
        )
