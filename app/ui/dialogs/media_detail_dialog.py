"""The media detail view: a large preview beside an editable inspector.

Left is the asset (artwork, or a transport for audio); right is everything
Mediary knows about it, grouped into collapsible sections. Licensing is a
first-class group because Mediary deliberately never infers it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QToolButton,
    QWidget,
)

from app.config.settings import Settings
from app.models.category import suggested_tags
from app.models.media import (
    ATTRIBUTION_OPTIONS,
    LICENSE_OPTIONS,
    MediaItem,
)
from app.services.library_service import LibraryService
from app.ui.theme import Size, Space, get_theme
from app.ui.widgets.audio_player import AudioPlayer
from app.ui.widgets.common import (
    Badge,
    ElidedLabel,
    FlowLayout,
    TagChip,
    button,
    divider,
    hbox,
    icon_button,
    label,
    selectable_label,
    vbox,
)
from app.ui.widgets.thumbnail import Thumbnail
from app.utils.formatting import (
    format_bitrate,
    format_bytes,
    format_date,
    format_duration,
)


class InspectorSection(QWidget):
    """A collapsible group of fields in the right-hand inspector."""

    def __init__(
        self,
        title: str,
        *,
        expanded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = vbox(self, spacing=0)

        self._toggle = QToolButton(self)
        self._toggle.setObjectName("InspectorSection")
        self._toggle.setText(title.upper())
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setSizePolicy(
            self._toggle.sizePolicy().horizontalPolicy().Expanding,
            self._toggle.sizePolicy().verticalPolicy(),
        )
        self._toggle.clicked.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self._body = QWidget(self)
        self._body_layout = vbox(self._body, spacing=Space.md, margins=(0, 0, 0, Space.md))
        layout.addWidget(self._body)

        self._body.setVisible(expanded)
        self._refresh_arrow()

    def add(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._body_layout.addLayout(layout)

    def _on_toggled(self) -> None:
        self._body.setVisible(self._toggle.isChecked())
        self._refresh_arrow()

    def _refresh_arrow(self) -> None:
        theme = get_theme()
        if theme is None:
            return
        self._toggle.setIcon(
            theme.icon("chevron-down" if self._toggle.isChecked() else "chevron-right", 12, "muted")
        )


def field(name: str, widget: QWidget) -> QWidget:
    """A labelled inspector field: micro uppercase label above the control."""
    holder = QWidget()
    layout = vbox(holder, spacing=Space.xs)
    layout.addWidget(label(name, "fieldLabel"))
    layout.addWidget(widget)
    return holder


def read_only_row(name: str, value: str, *, mono: bool = False) -> QWidget:
    """A compact ``LABEL   value`` row for technical facts."""
    holder = QWidget()
    layout = hbox(holder, spacing=Space.md)
    key = label(name, "fieldLabel")
    key.setFixedWidth(104)
    key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    layout.addWidget(key)
    text = selectable_label(value or "—", "mono" if mono else "meta")
    layout.addWidget(text, 1)
    return holder


class MediaDetailDialog(QDialog):
    """Inspect and edit one library item."""

    item_changed = Signal(object)      # MediaItem
    item_removed = Signal(int)         # media id
    open_path_requested = Signal(str)
    reveal_path_requested = Signal(str)

    def __init__(
        self,
        item: MediaItem,
        library: LibraryService,
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self._library = library
        self._settings = settings
        self._dirty = False

        self.setWindowTitle(item.display_title)
        self.setModal(True)
        self.resize(QSize(1000, 640))
        self.setMinimumSize(QSize(760, 520))

        layout = hbox(self, spacing=0)
        layout.addWidget(self._build_preview(), 1)
        layout.addWidget(self._build_inspector())

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _build_preview(self) -> QWidget:
        pane = QWidget(self)
        pane.setObjectName("PreviewCanvas")
        pane.setMinimumWidth(360)
        layout = vbox(pane, spacing=0, margins=(Space.xl, Space.xl, Space.xl, Space.lg))

        item = self.item

        self._thumb = Thumbnail(
            aspect=0,
            fallback_icon="audio" if item.is_audio else "video",
            parent=pane,
        )
        has_art = self._thumb.set_source(item.thumbnail_path, max_edge=1200)

        if item.is_audio and not has_art:
            # A full-bleed empty rectangle reads as a broken image. Audio with
            # no cover art gets a compact square plate instead, which leaves the
            # transport and waveform as the focus of the pane.
            layout.addStretch(1)
            self._thumb.setFixedSize(QSize(208, 208))
            layout.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addSpacing(Space.lg)
            heading = label(item.display_title, "heading", wrap=True)
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(heading)
            if item.creator:
                creator = label(item.creator, "meta")
                creator.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(creator)
            layout.addStretch(1)
        else:
            if item.is_audio:
                self._thumb.setMaximumHeight(420)
            layout.addWidget(self._thumb, 1)

        if item.file_missing or not item.exists:
            layout.addSpacing(Space.md)
            warning = label("File unavailable — it is no longer at the recorded path.", "warning")
            warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(warning)

        if item.is_audio:
            layout.addSpacing(Space.lg)
            self._player = AudioPlayer(pane)
            self._player.set_source(item.file_path if item.exists else "")
            layout.addWidget(self._player)
        else:
            layout.addSpacing(Space.lg)
            actions = QWidget(pane)
            actions_layout = hbox(actions, spacing=Space.sm)
            actions_layout.addStretch(1)
            play = button(
                "Play", variant="primary", icon="play",
                on_click=lambda: self.open_path_requested.emit(item.file_path),
            )
            play.setEnabled(item.exists)
            actions_layout.addWidget(play)
            actions_layout.addStretch(1)
            layout.addWidget(actions)

        return pane

    # ------------------------------------------------------------------
    # Inspector
    # ------------------------------------------------------------------

    def _build_inspector(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("Inspector")
        panel.setFixedWidth(Size.inspector_width + 20)
        outer = vbox(panel, spacing=0)

        outer.addWidget(self._build_inspector_header())
        outer.addWidget(divider())

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        content = QWidget(scroll)
        layout = vbox(content, spacing=0, margins=(Space.lg, Space.sm, Space.lg, Space.lg))
        scroll.setWidget(content)

        layout.addWidget(self._section_details())
        layout.addWidget(self._section_tags())
        layout.addWidget(self._section_source())
        layout.addWidget(self._section_technical())
        layout.addWidget(self._section_licensing())
        layout.addWidget(self._section_notes())
        layout.addStretch(1)

        outer.addWidget(divider())
        outer.addWidget(self._build_inspector_footer())
        return panel

    def _build_inspector_header(self) -> QWidget:
        header = QWidget(self)
        layout = vbox(header, spacing=Space.sm, margins=(Space.lg, Space.lg, Space.md, Space.md))

        title_row = QWidget(header)
        title_layout = hbox(title_row, spacing=Space.sm)

        self._title_label = label(self.item.display_title, "heading", wrap=True)
        title_layout.addWidget(self._title_label, 1)

        self._favorite_btn = icon_button(
            "star",
            tooltip="Favourite",
            size=16,
            tone="warning" if self.item.favorite else "muted",
            on_click=self._toggle_favorite,
        )
        title_layout.addWidget(self._favorite_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(title_row)

        badges = QWidget(header)
        badge_layout = hbox(badges, spacing=Space.xs)
        item = self.item
        for text, tone in self._header_badges():
            badge_layout.addWidget(Badge(text, tone, badges))
        badge_layout.addStretch(1)
        layout.addWidget(badges)

        if item.creator:
            layout.addWidget(ElidedLabel(item.creator, "meta", parent=header))
        return header

    def _header_badges(self) -> list:
        item = self.item
        badges = [(item.category.upper(), "accent")]
        if item.container:
            badges.append((item.container.upper(), ""))
        if item.is_audio and item.audio_bitrate:
            badges.append((f"{item.audio_bitrate} KBPS", ""))
        elif item.height:
            badges.append((f"{item.height}P", ""))
        if item.file_missing:
            badges.append(("MISSING", "danger"))
        return badges

    def _section_details(self) -> QWidget:
        section = InspectorSection("Details")

        self._title_input = QLineEdit(self.item.title)
        self._title_input.textChanged.connect(self._mark_dirty)
        section.add(field("Title", self._title_input))

        self._creator_input = QLineEdit(self.item.creator)
        self._creator_input.textChanged.connect(self._mark_dirty)
        section.add(field("Creator", self._creator_input))

        self._category_box = QComboBox()
        for entry in self._library.all_categories():
            self._category_box.addItem(entry["name"], entry["name"])
        index = self._category_box.findData(self.item.category)
        if index < 0:
            self._category_box.addItem(self.item.category, self.item.category)
            index = self._category_box.count() - 1
        self._category_box.setCurrentIndex(index)
        self._category_box.currentIndexChanged.connect(self._mark_dirty)
        section.add(field("Category", self._category_box))
        return section

    def _section_tags(self) -> QWidget:
        section = InspectorSection("Tags")

        self._tag_holder = QWidget()
        self._tag_layout = FlowLayout(self._tag_holder, h_spacing=Space.xs, v_spacing=Space.xs)
        section.add(self._tag_holder)

        entry_row = QWidget()
        entry_layout = hbox(entry_row, spacing=Space.xs)
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Add a tag and press Enter")
        self._tag_input.returnPressed.connect(self._add_tag_from_input)
        entry_layout.addWidget(self._tag_input, 1)
        section.add(entry_row)

        suggestions = [t for t in suggested_tags(self.item.category) if t not in self.item.tags]
        if suggestions:
            suggest_holder = QWidget()
            suggest_layout = FlowLayout(suggest_holder, h_spacing=Space.xs, v_spacing=Space.xs)
            for name in suggestions[:8]:
                # Neutral styling so a suggestion is never mistaken for a tag
                # that has already been applied.
                chip = TagChip(name, parent=suggest_holder)
                chip.setObjectName("Chip")
                chip.clicked.connect(self._add_tag)
                suggest_layout.addWidget(chip)
            section.add(label("SUGGESTED", "fieldLabel"))
            section.add(suggest_holder)

        self._render_tags()
        return section

    def _section_source(self) -> QWidget:
        section = InspectorSection("Source")
        item = self.item

        section.add(read_only_row("Platform", item.platform or "—"))
        section.add(read_only_row("Uploaded", format_date(item.upload_date)))
        section.add(read_only_row("Added", format_date(item.downloaded_at, with_time=True)))

        if item.source_url:
            url_row = QWidget()
            url_layout = vbox(url_row, spacing=Space.xs)
            url_layout.addWidget(label("SOURCE URL", "fieldLabel"))
            url_value = selectable_label(item.source_url, "mono")
            url_value.setWordWrap(True)
            url_layout.addWidget(url_value)
            actions = QWidget()
            actions_layout = hbox(actions, spacing=Space.sm)
            actions_layout.addWidget(
                button("Copy URL", variant="link", on_click=lambda: self._copy(item.source_url))
            )
            actions_layout.addWidget(
                button("Open source", variant="link", on_click=self._open_source)
            )
            actions_layout.addStretch(1)
            url_layout.addWidget(actions)
            section.add(url_row)

        path_row = QWidget()
        path_layout = vbox(path_row, spacing=Space.xs)
        path_layout.addWidget(label("FILE", "fieldLabel"))
        path_value = selectable_label(item.file_path, "mono")
        path_value.setWordWrap(True)
        path_layout.addWidget(path_value)
        section.add(path_row)
        return section

    def _section_technical(self) -> QWidget:
        section = InspectorSection("Technical", expanded=False)
        item = self.item

        section.add(read_only_row("Duration", format_duration(item.duration)))
        section.add(read_only_row("Size", format_bytes(item.file_size)))
        section.add(read_only_row("Container", item.container.upper() or "—"))
        if item.is_video or item.width:
            section.add(read_only_row("Resolution", item.resolution or "—"))
            section.add(read_only_row("Frame rate", f"{item.fps:g} fps" if item.fps else "—"))
            section.add(read_only_row("Video codec", item.video_codec or "—"))
        section.add(read_only_row("Audio codec", item.audio_codec or "—"))
        section.add(read_only_row("Audio bitrate", format_bitrate(item.audio_bitrate)))
        if item.sample_rate:
            section.add(read_only_row("Sample rate", f"{item.sample_rate / 1000:g} kHz"))
        return section

    def _section_licensing(self) -> QWidget:
        section = InspectorSection("Licensing")

        note = label(
            "Mediary never determines licensing for you. Record what you have "
            "confirmed yourself.",
            "muted",
            wrap=True,
        )
        section.add(note)

        self._license_box = QComboBox()
        for option in LICENSE_OPTIONS:
            self._license_box.addItem(option, option)
        index = self._license_box.findData(self.item.license_type)
        self._license_box.setCurrentIndex(max(0, index))
        self._license_box.currentIndexChanged.connect(self._mark_dirty)
        section.add(field("License", self._license_box))

        self._license_url_input = QLineEdit(self.item.license_url)
        self._license_url_input.setPlaceholderText("https://…")
        self._license_url_input.textChanged.connect(self._mark_dirty)
        section.add(field("License URL", self._license_url_input))

        self._attribution_box = QComboBox()
        for option in ATTRIBUTION_OPTIONS:
            self._attribution_box.addItem(option, option)
        index = self._attribution_box.findData(self.item.attribution_required)
        self._attribution_box.setCurrentIndex(max(0, index))
        self._attribution_box.currentIndexChanged.connect(self._mark_dirty)
        section.add(field("Attribution required", self._attribution_box))

        self._license_notes_input = QPlainTextEdit(self.item.license_notes)
        self._license_notes_input.setPlaceholderText("Credit the creator in the description…")
        self._license_notes_input.setFixedHeight(64)
        self._license_notes_input.textChanged.connect(self._mark_dirty)
        section.add(field("License notes", self._license_notes_input))
        return section

    def _section_notes(self) -> QWidget:
        section = InspectorSection("Notes")
        self._notes_input = QPlainTextEdit(self.item.notes)
        self._notes_input.setPlaceholderText("Anything you want to remember about this asset…")
        self._notes_input.setFixedHeight(84)
        self._notes_input.textChanged.connect(self._mark_dirty)
        section.add(self._notes_input)
        return section

    def _build_inspector_footer(self) -> QWidget:
        footer = QWidget(self)
        layout = vbox(footer, spacing=Space.sm, margins=(Space.lg, Space.md, Space.lg, Space.lg))

        row = QWidget(footer)
        row_layout = hbox(row, spacing=Space.sm)
        open_btn = button(
            "Open file", variant="subtle", icon="external",
            on_click=lambda: self.open_path_requested.emit(self.item.file_path),
        )
        open_btn.setEnabled(self.item.exists)
        row_layout.addWidget(open_btn)

        folder_btn = button(
            "Show in folder", variant="subtle", icon="folder",
            on_click=lambda: self.reveal_path_requested.emit(self.item.file_path),
        )
        folder_btn.setEnabled(self.item.exists)
        row_layout.addWidget(folder_btn)
        row_layout.addStretch(1)
        layout.addWidget(row)

        actions = QWidget(footer)
        actions_layout = hbox(actions, spacing=Space.sm)

        remove_btn = button("Remove", variant="ghost", on_click=self._remove_from_library)
        remove_btn.setToolTip("Remove from the library but keep the file")
        actions_layout.addWidget(remove_btn)

        delete_btn = button("Delete file", variant="ghost", on_click=self._delete_file)
        delete_btn.setEnabled(self.item.exists)
        actions_layout.addWidget(delete_btn)

        actions_layout.addStretch(1)

        self._save_btn = button("Save", variant="primary", on_click=self._save)
        self._save_btn.setEnabled(False)
        actions_layout.addWidget(self._save_btn)
        layout.addWidget(actions)
        return footer

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def _render_tags(self) -> None:
        self._tag_layout.clear()
        if not self.item.tags:
            placeholder = label("No tags yet", "muted")
            self._tag_layout.addWidget(placeholder)
            return
        for name in self.item.tags:
            chip = TagChip(name, removable=True, parent=self._tag_holder)
            chip.removed.connect(self._remove_tag)
            self._tag_layout.addWidget(chip)

    def _add_tag_from_input(self) -> None:
        self._add_tag(self._tag_input.text())
        self._tag_input.clear()

    def _add_tag(self, name: str) -> None:
        clean = " ".join(str(name or "").split())
        if not clean or clean.lower() in {t.lower() for t in self.item.tags}:
            return
        self._library.add_tag(self.item.id, clean)
        self.item.tags = self._library.tags_for(self.item.id)
        self._render_tags()
        self.item_changed.emit(self.item)

    def _remove_tag(self, name: str) -> None:
        self._library.remove_tag(self.item.id, name)
        self.item.tags = self._library.tags_for(self.item.id)
        self._render_tags()
        self.item_changed.emit(self.item)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._save_btn.setEnabled(True)

    def _toggle_favorite(self) -> None:
        self.item.favorite = self._library.toggle_favorite(self.item.id)
        theme = get_theme()
        if theme is not None:
            self._favorite_btn.setIcon(
                theme.icon("star", 16, "warning" if self.item.favorite else "muted",
                           filled=self.item.favorite)
            )
        self.item_changed.emit(self.item)

    def _save(self) -> None:
        item = self.item
        item.title = self._title_input.text().strip() or item.filename
        item.creator = self._creator_input.text().strip()
        item.category = self._category_box.currentData() or item.category
        item.license_type = self._license_box.currentData()
        item.license_url = self._license_url_input.text().strip()
        item.attribution_required = self._attribution_box.currentData()
        item.license_notes = self._license_notes_input.toPlainText().strip()
        item.notes = self._notes_input.toPlainText().strip()

        from app.models.category import kind_for_category

        item.media_kind = kind_for_category(item.category) or item.media_kind

        self._library.update(item)
        self._dirty = False
        self._save_btn.setEnabled(False)
        self._save_btn.setText("Saved")
        self._title_label.setText(item.display_title)
        self.setWindowTitle(item.display_title)
        self.item_changed.emit(item)

    def _remove_from_library(self) -> None:
        answer = QMessageBox.question(
            self,
            "Remove from library",
            f"Remove “{self.item.display_title}” from your library?\n\n"
            "The file stays exactly where it is on disk.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._library.remove(self.item.id)
        self.item_removed.emit(self.item.id)
        self.accept()

    def _delete_file(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Delete file")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"Permanently delete “{self.item.display_title}”?")
        box.setInformativeText(
            f"This deletes the file from disk and removes it from your library.\n\n"
            f"{self.item.file_path}\n\nThis cannot be undone."
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Discard
        )
        box.button(QMessageBox.StandardButton.Discard).setText("Delete file")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Discard:
            return
        ok, message = self._library.delete_file(self.item.id)
        if ok:
            self.item_removed.emit(self.item.id)
            self.accept()
        else:
            QMessageBox.warning(self, "Could not delete", message)

    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text or "")

    def _open_source(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if self.item.source_url:
            QDesktopServices.openUrl(QUrl(self.item.source_url))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._dirty:
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                "You have unsaved changes. Save them before closing?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
                | QMessageBox.StandardButton.Save,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                self._save()
        if hasattr(self, "_player"):
            self._player.stop()
        super().closeEvent(event)


_ = Path  # re-exported for callers that build paths from this module
