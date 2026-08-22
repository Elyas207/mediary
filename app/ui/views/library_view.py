"""The Library screen: search, filter, browse, act.

Layout follows the pattern that works for real asset managers: a compact
toolbar (search + filter chips + sort + view switch), a result-count strip, and
then either a responsive grid or a dense table. Actions live in the context
menu and the detail panel, never scattered across every card.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QMenu,
    QMessageBox,
    QScrollArea,
    QWidget,
)

from app.config.settings import VIEW_GRID, VIEW_LIST, Settings
from app.models.media import MediaItem
from app.services.library_service import SORT_LABELS, LibraryQuery, LibraryService
from app.ui.dialogs.media_detail_dialog import MediaDetailDialog
from app.ui.theme import Space
from app.ui.widgets.common import (
    Chip,
    EmptyState,
    FlowLayout,
    SearchInput,
    SegmentedControl,
    button,
    divider,
    hbox,
    label,
    vbox,
)
from app.ui.widgets.media_card import MediaCard, MediaRow, MediaRowHeader
from app.utils.formatting import format_bytes, format_duration
from app.utils.logging import get_logger

log = get_logger("ui.library")

#: Chips shown above the results. Each maps onto a LibraryQuery field.
KIND_CHIPS = (("video", "Video"), ("audio", "Audio"))
CATEGORY_CHIPS = (
    "Sound Effects", "Music", "Inspiration", "Voice", "Ambience", "Foley",
)

GRID_MIN_WIDTH = 168
GRID_GAP = Space.md


class LibraryView(QWidget):
    """Browse and manage everything in the library."""

    open_path_requested = Signal(str)
    reveal_path_requested = Signal(str)
    library_changed = Signal()
    download_requested = Signal()

    def __init__(
        self,
        settings: Settings,
        library: LibraryService,
        theme,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._library = library
        self._theme = theme

        self._query = LibraryQuery(sort="recent")
        self._nav_key = "all"
        self._nav_title = "All Media"
        self._items: list = []
        self._widgets: dict = {}
        self._selected_id: int | None = None
        self._view_mode = settings.library_view or VIEW_GRID
        self._pending_reveal: int | None = None

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._run_search)

        root = vbox(self, spacing=0)
        root.addWidget(self._build_header())
        root.addWidget(divider())
        root.addWidget(self._build_results(), 1)

        self.reload()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        layout = vbox(header, spacing=Space.md, margins=(Space.xxl, Space.xl, Space.xxl, Space.md))

        # -- Title + search -------------------------------------------------
        title_row = QWidget(header)
        title_layout = hbox(title_row, spacing=Space.md)

        self._title = label("All Media", "pageTitle")
        title_layout.addWidget(self._title)
        title_layout.addStretch(1)

        self.search = SearchInput("Search titles, creators, tags, notes…", title_row)
        self.search.setFixedWidth(320)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        title_layout.addWidget(self.search)

        layout.addWidget(title_row)

        # -- Filter chips ----------------------------------------------------
        chips_holder = QWidget(header)
        self._chips_layout = FlowLayout(chips_holder, h_spacing=Space.xs, v_spacing=Space.xs)
        self._chips: dict = {}

        for value, text in KIND_CHIPS:
            chip = Chip(text, value=("kind", value), parent=chips_holder)
            chip.toggled.connect(lambda checked, c=chip: self._on_chip(c, checked))
            self._chips_layout.addWidget(chip)
            self._chips[("kind", value)] = chip

        for name in CATEGORY_CHIPS:
            chip = Chip(name, value=("category", name), parent=chips_holder)
            chip.toggled.connect(lambda checked, c=chip: self._on_chip(c, checked))
            self._chips_layout.addWidget(chip)
            self._chips[("category", name)] = chip

        favorite_chip = Chip("Favourites", value=("favorite", True), parent=chips_holder)
        favorite_chip.toggled.connect(lambda checked, c=favorite_chip: self._on_chip(c, checked))
        self._chips_layout.addWidget(favorite_chip)
        self._chips[("favorite", True)] = favorite_chip

        missing_chip = Chip("Missing files", value=("missing", True), parent=chips_holder)
        missing_chip.toggled.connect(lambda checked, c=missing_chip: self._on_chip(c, checked))
        self._chips_layout.addWidget(missing_chip)
        self._chips[("missing", True)] = missing_chip

        self._tag_chips: dict = {}
        self._chips_holder = chips_holder
        layout.addWidget(chips_holder)

        # -- Count / sort / view strip ---------------------------------------
        strip = QWidget(header)
        strip_layout = hbox(strip, spacing=Space.md)

        self._count_label = label("", "fieldLabel")
        strip_layout.addWidget(self._count_label)

        self._clear_filters_btn = button(
            "Clear filters", variant="link", on_click=self.clear_filters
        )
        self._clear_filters_btn.hide()
        strip_layout.addWidget(self._clear_filters_btn)

        strip_layout.addStretch(1)

        self._sort_box = QComboBox(strip)
        self._sort_box.setProperty("size", "sm")
        self._sort_box.setFixedWidth(150)
        for key, text in SORT_LABELS:
            self._sort_box.addItem(text, key)
        self._sort_box.currentIndexChanged.connect(self._on_sort_changed)
        strip_layout.addWidget(self._sort_box)

        self._view_switch = SegmentedControl(
            [(VIEW_GRID, "", "grid"), (VIEW_LIST, "", "list")], parent=strip
        )
        self._view_switch.set_value(self._view_mode)
        self._view_switch.changed.connect(self._on_view_changed)
        strip_layout.addWidget(self._view_switch)

        layout.addWidget(strip)
        return header

    def _build_results(self) -> QWidget:
        container = QWidget(self)
        layout = vbox(container, spacing=0)

        self._list_header = MediaRowHeader(container)
        self._list_header.hide()
        layout.addWidget(self._list_header)
        self._list_header_divider = divider()
        self._list_header_divider.hide()
        layout.addWidget(self._list_header_divider)

        self._scroll = QScrollArea(container)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._scroll, 1)

        self._canvas = QWidget(self._scroll)
        self._canvas_layout = vbox(self._canvas, spacing=0)
        self._scroll.setWidget(self._canvas)

        self._grid_host = _GridHost(self._canvas)
        self._canvas_layout.addWidget(self._grid_host)

        self._rows_host = QWidget(self._canvas)
        self._rows_layout = vbox(self._rows_host, spacing=0)
        self._canvas_layout.addWidget(self._rows_host)

        self._canvas_layout.addStretch(1)

        self._empty = EmptyState(
            icon="library",
            title="Your library is empty",
            body="Download something to start building your collection.",
            action_text="Download media",
            on_action=self.download_requested.emit,
            parent=container,
        )
        layout.addWidget(self._empty, 1)
        return container

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def apply_nav_filter(self, key: str, filters: dict) -> None:
        """Called when a sidebar library entry is selected."""
        self._nav_key = key
        titles = {
            "all": "All Media",
            "video": "Video",
            "audio": "Audio",
            "sfx": "Sound Effects",
            "music": "Music",
            "inspiration": "Inspiration",
            "favorites": "Favourites",
        }
        self._nav_title = titles.get(key, "Library")
        self._title.setText(self._nav_title)

        self._query = LibraryQuery(
            text=self.search.text(),
            media_kind=filters.get("media_kind", ""),
            category=filters.get("category", ""),
            favorites_only=filters.get("favorites_only", False),
            sort=self._query.sort,
        )
        self._sync_chips_to_query()
        self.reload()

    def _sync_chips_to_query(self) -> None:
        """Reflect the nav filter in the chip row without re-triggering search."""
        for key, chip in self._chips.items():
            kind, value = key
            should_check = (
                (kind == "kind" and self._query.media_kind == value)
                or (kind == "category" and self._query.category == value)
                or (kind == "favorite" and self._query.favorites_only)
                or (kind == "missing" and self._query.missing_only)
            )
            chip.blockSignals(True)
            chip.setChecked(should_check)
            chip.blockSignals(False)
            chip._sync(should_check)
            # A nav-driven filter is already expressed by the page title.
            chip.setVisible(not self._is_chip_redundant(kind, value))

    def _is_chip_redundant(self, kind: str, value) -> bool:
        if self._nav_key == "all":
            return False
        if kind == "kind" and self._query.media_kind == value:
            return True
        if kind == "category" and self._query.category == value:
            return True
        if kind == "favorite" and self._query.favorites_only:
            return True
        return False

    def _on_chip(self, chip: Chip, checked: bool) -> None:
        kind, value = chip.value
        if kind == "kind":
            if checked:
                # Kind chips are mutually exclusive.
                for other_key, other in self._chips.items():
                    if other_key[0] == "kind" and other is not chip and other.isChecked():
                        other.blockSignals(True)
                        other.setChecked(False)
                        other.blockSignals(False)
                        other._sync(False)
                self._query.media_kind = value
            elif self._query.media_kind == value:
                self._query.media_kind = ""
        elif kind == "category":
            categories = set(self._query.categories)
            categories.add(value) if checked else categories.discard(value)
            self._query.categories = list(categories)
        elif kind == "favorite":
            self._query.favorites_only = checked
        elif kind == "missing":
            self._query.missing_only = checked
        elif kind == "tag":
            tags = set(self._query.tags)
            tags.add(value) if checked else tags.discard(value)
            self._query.tags = list(tags)
            if not checked:
                self._remove_tag_chip(value)
        self.reload()

    def filter_by_tag(self, tag: str) -> None:
        """Add a tag filter chip and apply it - used from the Tags screen."""
        key = ("tag", tag)
        if key not in self._tag_chips:
            chip = Chip(f"#{tag}", value=key, parent=self._chips_holder)
            chip.toggled.connect(lambda checked, c=chip: self._on_chip(c, checked))
            self._chips_layout.addWidget(chip)
            self._tag_chips[key] = chip
            self._chips[key] = chip
        chip = self._tag_chips[key]
        chip.setChecked(True)

    def _remove_tag_chip(self, tag: str) -> None:
        key = ("tag", tag)
        chip = self._tag_chips.pop(key, None)
        self._chips.pop(key, None)
        if chip is not None:
            chip.setParent(None)
            chip.deleteLater()

    def clear_filters(self) -> None:
        self.search.clear()
        for key in list(self._tag_chips):
            self._remove_tag_chip(key[1])
        self._query = LibraryQuery(sort=self._query.sort)
        if self._nav_key != "all":
            from app.ui.sidebar import NAV_FILTERS

            filters = NAV_FILTERS.get(self._nav_key, {})
            self._query.media_kind = filters.get("media_kind", "")
            self._query.category = filters.get("category", "")
            self._query.favorites_only = filters.get("favorites_only", False)
        self._sync_chips_to_query()
        self.reload()

    def _on_sort_changed(self) -> None:
        self._query.sort = self._sort_box.currentData() or "recent"
        self.reload()

    def _run_search(self) -> None:
        self._query.text = self.search.text()
        self.reload()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def reload(self) -> None:
        try:
            self._items = self._library.search(self._query)
        except Exception:  # noqa: BLE001 - a bad query must not blank the app
            log.exception("Library query failed")
            self._items = []
        self._render()

    def _render(self) -> None:
        self._clear_widgets()

        total = len(self._items)
        has_items = total > 0
        self._empty.setVisible(not has_items)
        self._scroll.setVisible(has_items)
        self._list_header.setVisible(has_items and self._view_mode == VIEW_LIST)
        self._list_header_divider.setVisible(has_items and self._view_mode == VIEW_LIST)

        if not has_items:
            self._apply_empty_copy()
            self._count_label.setText("")
            self._clear_filters_btn.setVisible(self._has_active_filters())
            return

        self._count_label.setText(self._count_text(total))
        self._clear_filters_btn.setVisible(self._has_active_filters())

        if self._view_mode == VIEW_GRID:
            self._grid_host.setVisible(True)
            self._rows_host.setVisible(False)
            self._render_grid()
        else:
            self._grid_host.setVisible(False)
            self._rows_host.setVisible(True)
            self._render_rows()

        if self._pending_reveal is not None:
            self._scroll_to(self._pending_reveal)
            self._pending_reveal = None

    def _count_text(self, total: int) -> str:
        duration = sum(item.duration or 0 for item in self._items)
        size = sum(item.file_size or 0 for item in self._items)
        parts = [f"{total} ITEM{'S' if total != 1 else ''}"]
        if duration:
            parts.append(format_duration(duration))
        if size:
            parts.append(format_bytes(size))
        return "   ·   ".join(parts)

    def _render_grid(self) -> None:
        width = self._settings.grid_thumbnail_size
        self._grid_host.set_preferred_width(width)
        for item in self._items:
            card = MediaCard(item, width=width, parent=self._grid_host)
            self._wire(card)
            self._grid_host.add_card(card)
            self._widgets[item.id] = card
        self._grid_host.relayout()

    def _render_rows(self) -> None:
        for item in self._items:
            row = MediaRow(item, self._rows_host)
            self._wire(row)
            self._rows_layout.addWidget(row)
            self._widgets[item.id] = row

    def _wire(self, widget) -> None:
        widget.activated.connect(self.open_detail)
        widget.selected.connect(self._on_selected)
        widget.favorite_toggled.connect(self._toggle_favorite)
        widget.context_requested.connect(self._show_context_menu)

    def _clear_widgets(self) -> None:
        self._grid_host.clear()
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._widgets.clear()

    def _apply_empty_copy(self) -> None:
        if self._has_active_filters() or self._query.text:
            self._empty.set_text(
                "No matches",
                "Try a different search, or clear the filters to see everything again.",
            )
            return
        copy = {
            "sfx": (
                "No sound effects yet",
                "Build your personal sound library - whooshes, impacts, transitions and foley, "
                "all searchable in one place.",
            ),
            "music": (
                "No music yet",
                "Download tracks and record their licensing so you always know what you can use.",
            ),
            "inspiration": (
                "No references saved",
                "Keep the reels, edits and cinematography you want to learn from in one place.",
            ),
            "favorites": (
                "Nothing saved yet",
                "Favourite media to find it quickly later.",
            ),
            "video": ("No video yet", "Downloaded video will appear here."),
            "audio": ("No audio yet", "Downloaded audio will appear here."),
        }.get(
            self._nav_key,
            (
                "Your library is empty",
                "Download something to start building your collection.",
            ),
        )
        self._empty.set_text(*copy)

    def _has_active_filters(self) -> bool:
        return bool(
            self._query.text
            or self._query.categories
            or self._query.tags
            or self._query.missing_only
            or (self._query.favorites_only and self._nav_key != "favorites")
            or (self._query.media_kind and self._nav_key not in ("video", "audio"))
        )

    # ------------------------------------------------------------------
    # View mode
    # ------------------------------------------------------------------

    def _on_view_changed(self, mode: str) -> None:
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self._settings.library_view = mode
        self._render()

    def current_view_mode(self) -> str:
        return self._view_mode

    def refresh_theme(self) -> None:
        self.search.refresh_icon()
        self._render()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self._view_mode == VIEW_GRID:
            self._grid_host.relayout()

    # ------------------------------------------------------------------
    # Selection and actions
    # ------------------------------------------------------------------

    def _on_selected(self, item: MediaItem) -> None:
        if self._selected_id == item.id:
            return
        previous = self._widgets.get(self._selected_id)
        if previous is not None:
            previous.set_selected(False)
        current = self._widgets.get(item.id)
        if current is not None:
            current.set_selected(True)
        self._selected_id = item.id

    def open_detail(self, item: MediaItem) -> None:
        dialog = MediaDetailDialog(item, self._library, self._settings, self)
        dialog.open_path_requested.connect(self.open_path_requested.emit)
        dialog.reveal_path_requested.connect(self.reveal_path_requested.emit)
        dialog.item_changed.connect(self._on_item_changed)
        dialog.item_removed.connect(self._on_item_removed)
        dialog.exec()

    def _on_item_changed(self, item: MediaItem) -> None:
        widget = self._widgets.get(item.id)
        if widget is not None:
            widget.refresh(item)
        for index, existing in enumerate(self._items):
            if existing.id == item.id:
                self._items[index] = item
                break
        self.library_changed.emit()

    def _on_item_removed(self, media_id: int) -> None:
        self._items = [item for item in self._items if item.id != media_id]
        self._render()
        self.library_changed.emit()

    def _toggle_favorite(self, item: MediaItem) -> None:
        item.favorite = self._library.toggle_favorite(item.id)
        widget = self._widgets.get(item.id)
        if widget is not None:
            widget.refresh(item)
        if self._query.favorites_only and not item.favorite:
            self.reload()
        self.library_changed.emit()

    def note_item_added(self, item: MediaItem) -> None:
        """A download finished - refresh if it would appear in this view."""
        self.reload()

    def reveal(self, media_id: int) -> None:
        self._pending_reveal = media_id
        item = self._library.get(media_id)
        if item is not None:
            self._on_selected(item)
        self.reload()

    def _scroll_to(self, media_id: int) -> None:
        widget = self._widgets.get(media_id)
        if widget is None:
            return
        self._scroll.ensureWidgetVisible(widget, 40, 60)
        widget.set_selected(True)
        self._selected_id = media_id

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, item: MediaItem, position: QPoint) -> None:
        menu = QMenu(self)
        theme = self._theme

        def action(text: str, icon: str, handler, *, enabled: bool = True):
            entry = menu.addAction(theme.icon(icon, 14, "secondary"), text)
            entry.setEnabled(enabled)
            entry.triggered.connect(handler)
            return entry

        exists = item.exists
        action("Open", "eye", lambda: self.open_detail(item))
        action("Play file", "play", lambda: self.open_path_requested.emit(item.file_path),
               enabled=exists)
        action("Show in folder", "folder", lambda: self.reveal_path_requested.emit(item.file_path),
               enabled=exists)
        menu.addSeparator()

        action("Copy source URL", "link", lambda: self._copy(item.source_url),
               enabled=bool(item.source_url))
        action("Copy file path", "copy", lambda: self._copy(item.file_path))
        menu.addSeparator()

        favourite_text = "Remove from favourites" if item.favorite else "Add to favourite"
        action(favourite_text, "star", lambda: self._toggle_favorite(item))
        action("Edit details", "edit", lambda: self.open_detail(item))

        category_menu = menu.addMenu(theme.icon("layers", 14, "secondary"), "Change category")
        for entry in self._library.all_categories():
            name = entry["name"]
            act = category_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(name == item.category)
            act.triggered.connect(lambda _=False, n=name: self._change_category(item, n))

        menu.addSeparator()
        action("Remove from library", "minus", lambda: self._remove_from_library(item))
        delete = action("Delete file…", "trash", lambda: self._delete_file(item))
        delete.setEnabled(exists)

        menu.exec(position)

    def _copy(self, text: str) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(text or "")

    def _change_category(self, item: MediaItem, category: str) -> None:
        self._library.set_category(item.id, category)
        refreshed = self._library.get(item.id)
        if refreshed is not None:
            self._on_item_changed(refreshed)
        self.reload()

    def _remove_from_library(self, item: MediaItem) -> None:
        answer = QMessageBox.question(
            self,
            "Remove from library",
            f"Remove “{item.display_title}” from your Mediary library?\n\n"
            "The file stays exactly where it is on disk.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._library.remove(item.id)
        self._on_item_removed(item.id)

    def _delete_file(self, item: MediaItem) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Delete file")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"Permanently delete “{item.display_title}”?")
        box.setInformativeText(
            f"This deletes the file from disk and removes it from your library.\n\n{item.file_path}\n\n"
            "This cannot be undone."
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Discard
        )
        box.button(QMessageBox.StandardButton.Discard).setText("Delete file")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Discard:
            return

        ok, message = self._library.delete_file(item.id)
        if ok:
            self._on_item_removed(item.id)
        else:
            QMessageBox.warning(self, "Could not delete", message)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Delete and self._selected_id:
            item = next((i for i in self._items if i.id == self._selected_id), None)
            if item is not None:
                self._remove_from_library(item)
                return
        super().keyPressEvent(event)


class _GridHost(QWidget):
    """A responsive grid that reflows cards to fill the available width."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QGridLayout

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(Space.xxl, Space.lg, Space.xxl, Space.xxl)
        self._layout.setHorizontalSpacing(GRID_GAP)
        self._layout.setVerticalSpacing(Space.xl)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._cards: list = []
        self._columns = 0
        self._card_width = 0
        self._preferred_width = GRID_MIN_WIDTH

    def add_card(self, card: QWidget) -> None:
        self._cards.append(card)

    def set_preferred_width(self, width: int) -> None:
        self._preferred_width = max(GRID_MIN_WIDTH, int(width))

    def clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards.clear()
        self._columns = 0
        self._card_width = 0

    def relayout(self) -> None:
        """Fit whole columns to the viewport, then share the slack between them.

        Left-over horizontal space looks like a mistake in a grid, so the cards
        grow to consume it rather than leaving a ragged gutter on the right.
        """
        if not self._cards:
            return
        margins = self._layout.contentsMargins()
        available = max(
            self._preferred_width,
            self.width() - margins.left() - margins.right(),
        )
        columns = max(1, int((available + GRID_GAP) // (self._preferred_width + GRID_GAP)))
        columns = min(columns, max(1, len(self._cards)))
        card_width = int((available - GRID_GAP * (columns - 1)) / columns)

        if columns == self._columns and card_width == self._card_width:
            return

        if card_width != self._card_width:
            for card in self._cards:
                card.set_card_width(card_width)
            self._card_width = card_width

        if columns != self._columns or self._layout.count() != len(self._cards):
            self._columns = columns
            while self._layout.count():
                self._layout.takeAt(0)
            for index, card in enumerate(self._cards):
                self._layout.addWidget(card, index // columns, index % columns)
                card.show()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.relayout()
