"""The Download screen: paste, analyse, choose, download.

The whole point of this screen is to get from a pasted URL to a running
download in as few decisions as possible, so the format controls carry sensible
defaults and every analysed item can still override them individually.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QWidget,
)

from app.config.settings import Settings
from app.downloader.ytdlp_adapter import parse_urls
from app.models.category import categories_for_kind
from app.models.download import (
    AUDIO_FORMATS,
    LOSSY_AUDIO_FORMATS,
    MP3_BITRATES,
    VIDEO_FORMATS,
    DownloadOptions,
    MediaInfo,
)
from app.ui.theme import Space, get_theme
from app.ui.widgets.common import (
    Badge,
    ElidedLabel,
    EmptyState,
    Notice,
    SegmentedControl,
    button,
    divider,
    hbox,
    icon_button,
    label,
    panel,
    vbox,
)
from app.ui.widgets.thumbnail import Thumbnail
from app.utils.filenames import sanitize_component
from app.utils.formatting import format_bytes, format_date, format_duration, truncate
from app.utils.logging import get_logger

log = get_logger("ui.download")

KIND_OPTIONS = (("video", "Video", "video"), ("audio", "Audio", "audio"))

#: Sentinel item data for the "New category…" entry. Never a real category
#: name, and never written anywhere.
NEW_CATEGORY = "mediary:new-category"


class OptionBar(QWidget):
    """Format, quality and category pickers.

    Used both as the screen-level default and, in compact form, inside each
    analysed item.
    """

    changed = Signal()
    #: Emitted only when a person changes the category, never when the list is
    #: rebuilt or set programmatically - otherwise every kind switch would look
    #: like a deliberate override.
    category_edited = Signal()
    #: A category the user invented here, for the app to persist.
    category_created = Signal(str)

    def __init__(
        self,
        settings: Settings,
        *,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._compact = compact
        self._available_qualities: list = list(("best", "2160p", "1440p", "1080p", "720p", "480p", "360p"))
        self._updating = False
        #: The last real category, so cancelling “New category…” can go back.
        self._last_category = ""
        #: Set when the source offers only one kind, so nothing may switch it.
        self._kind_locked = ""

        layout = hbox(self, spacing=Space.sm)

        self.kind = SegmentedControl(list(KIND_OPTIONS), parent=self)
        self.kind.changed.connect(self._on_kind_changed)
        layout.addWidget(self.kind)

        self.format_box = self._combo(96)
        layout.addWidget(self.format_box)

        self.quality_box = self._combo(118 if compact else 132)
        layout.addWidget(self.quality_box)

        if not compact:
            layout.addWidget(divider(vertical=True))

        self.category_box = self._combo(150)
        layout.addWidget(self.category_box)

        layout.addStretch(1)

        self._apply_settings()

    def _combo(self, width: int) -> QComboBox:
        box = QComboBox(self)
        box.setFixedWidth(width)
        if self._compact:
            box.setProperty("size", "sm")
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        box.currentIndexChanged.connect(self._emit_changed)
        return box

    # -- State ------------------------------------------------------------

    def _apply_settings(self) -> None:
        settings = self._settings
        self._updating = True
        self.kind.set_value(settings.default_media_kind)
        self._rebuild_format_options(settings.default_media_kind)
        self._rebuild_category_options(settings.default_media_kind)

        if settings.default_media_kind == "audio":
            self._select(self.format_box, settings.default_audio_format.upper())
            self._select(self.quality_box, f"{settings.default_audio_bitrate} kbps")
        else:
            self._select(self.format_box, settings.default_video_format.upper())
            self._select(self.quality_box, _quality_label(settings.default_video_quality))
        self._select(self.category_box, settings.default_category)
        self._updating = False

    def _on_kind_changed(self, kind: str) -> None:
        self._updating = True
        self._rebuild_format_options(kind)
        self._rebuild_category_options(kind)
        self._updating = False
        self._emit_changed()

    def _rebuild_format_options(self, kind: str) -> None:
        self.format_box.clear()
        formats = AUDIO_FORMATS if kind == "audio" else VIDEO_FORMATS
        for fmt in formats:
            self.format_box.addItem(fmt.upper(), fmt)
        self._rebuild_quality_options()

    def _rebuild_quality_options(self) -> None:
        kind = self.kind.value()
        current = self.quality_box.currentData()
        self.quality_box.clear()
        if kind == "audio":
            fmt = self.format_box.currentData() or "mp3"
            if fmt in LOSSY_AUDIO_FORMATS:
                self.quality_box.setEnabled(True)
                for rate in reversed(MP3_BITRATES):
                    self.quality_box.addItem(f"{rate} kbps", rate)
                self.quality_box.setToolTip("Target bitrate for the converted file")
            else:
                # Lossless: a bitrate choice would be meaningless.
                self.quality_box.addItem("Lossless", "lossless")
                self.quality_box.setEnabled(False)
                self.quality_box.setToolTip(
                    f"{fmt.upper()} is lossless - bitrate is determined by the source"
                )
        else:
            self.quality_box.setEnabled(True)
            self.quality_box.setToolTip("Maximum resolution to download")
            for quality in self._available_qualities:
                self.quality_box.addItem(_quality_label(quality), quality)
        if current is not None:
            self._select_data(self.quality_box, current)

    def _rebuild_category_options(self, kind: str) -> None:
        current = self.category_box.currentText()
        self.category_box.clear()
        for name in categories_for_kind(kind, self._settings.custom_categories):
            self.category_box.addItem(name, name)
        self.category_box.insertSeparator(self.category_box.count())
        self.category_box.addItem("New category…", NEW_CATEGORY)
        if current:
            self._select(self.category_box, current)

    def _on_new_category(self) -> None:
        """Let the user invent a folder without leaving the card."""
        name, accepted = QInputDialog.getText(
            self, "New category", "Folder name:", QLineEdit.EchoMode.Normal, ""
        )
        # An empty fallback rather than "Untitled": a name made entirely of
        # punctuation should cancel, not quietly create a folder the user never
        # asked for.
        name = sanitize_component(name.strip(), fallback="") if accepted else ""
        previous = self._last_category or self._settings.default_category
        if not name:
            self.set_category(previous)
            return
        existing = categories_for_kind(self.kind.value(), self._settings.custom_categories)
        match = next((c for c in existing if c.casefold() == name.casefold()), "")
        if match:
            # Re-typing a folder that already exists is not a new folder, and a
            # second entry differing only in case would file to the same place.
            name = match
        else:
            self._settings.custom_categories.append(name)
            self.category_created.emit(name)
            self._updating = True
            self._rebuild_category_options(self.kind.value())
            self._updating = False
        self.set_category(name)
        self.category_edited.emit()
        self.changed.emit()

    def set_available_qualities(self, qualities: list) -> None:
        """Restrict the resolution list to what the source actually offers."""
        self._available_qualities = list(qualities) or ["best"]
        if self.kind.value() != "audio":
            self._updating = True
            self._rebuild_quality_options()
            self._updating = False

    def set_category(self, name: str) -> None:
        """Select a category programmatically, without it reading as an edit."""
        was_updating = self._updating
        self._updating = True
        index = self.category_box.findData(name)
        if index < 0:
            # Keep an unlisted name above the "New category…" sentinel.
            index = max(0, self.category_box.count() - 2)
            self.category_box.insertItem(index, name, name)
        self.category_box.setCurrentIndex(index)
        self._last_category = name
        self._updating = was_updating

    def set_kind_locked(self, kind: str) -> None:
        """Hide the kind switch when a source offers only audio or only video.

        ``set_value`` does not emit, so the format and category lists have to be
        rebuilt here - otherwise an audio-only source would still be offering
        MP4 and video categories.
        """
        self._kind_locked = kind
        self._updating = True
        self.kind.set_value(kind)
        self._rebuild_format_options(kind)
        self._rebuild_category_options(kind)
        self._select(self.category_box, self._settings.default_category)
        if self.category_box.currentData() in (None, NEW_CATEGORY):
            self.category_box.setCurrentIndex(0)
        self._last_category = self.category_box.currentData()
        self._updating = False
        for value, _, _ in KIND_OPTIONS:
            self.kind.set_option_visible(value, value == kind)
        self._emit_changed()

    @staticmethod
    def _select(box: QComboBox, text: str) -> None:
        index = box.findText(text, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            box.setCurrentIndex(index)

    @staticmethod
    def _select_data(box: QComboBox, data) -> None:
        index = box.findData(data)
        if index >= 0:
            box.setCurrentIndex(index)

    def _emit_changed(self, *_args) -> None:
        if self._updating:
            return
        if self.sender() is self.category_box:
            if self.category_box.currentData() == NEW_CATEGORY:
                self._on_new_category()
                return
            self._last_category = self.category_box.currentData()
            self.category_edited.emit()
        if self.sender() is self.format_box:
            self._updating = True
            self._rebuild_quality_options()
            self._updating = False
        self.changed.emit()

    # -- Output -----------------------------------------------------------

    def options(self) -> DownloadOptions:
        kind = self.kind.value() or "video"
        fmt = self.format_box.currentData() or ("mp3" if kind == "audio" else "mp4")
        quality = self.quality_box.currentData()
        settings = self._settings
        return DownloadOptions(
            media_kind=kind,
            video_format=fmt if kind == "video" else settings.default_video_format,
            video_quality=(quality if kind == "video" and quality else "best"),
            audio_format=fmt if kind == "audio" else settings.default_audio_format,
            audio_bitrate=(
                quality if kind == "audio" and quality not in (None, "lossless")
                else settings.default_audio_bitrate
            ),
            category=self.category_box.currentData() or settings.default_category,
            embed_thumbnail=settings.embed_thumbnails,
            embed_metadata=settings.embed_metadata,
        )

    def apply_options(self, options: DownloadOptions) -> None:
        """Take the screen-level defaults.

        A locked kind wins: the source only offers one, so the defaults bar
        asking for the other would leave the card offering formats that cannot
        be produced.
        """
        if self._kind_locked and options.media_kind != self._kind_locked:
            options = replace(options, media_kind=self._kind_locked)
        self._updating = True
        self.kind.set_value(options.media_kind)
        self._rebuild_format_options(options.media_kind)
        self._rebuild_category_options(options.media_kind)
        if options.is_audio:
            self._select_data(self.format_box, options.audio_format)
            self._rebuild_quality_options()
            self._select_data(self.quality_box, options.audio_bitrate)
        else:
            self._select_data(self.format_box, options.video_format)
            self._rebuild_quality_options()
            self._select_data(self.quality_box, options.video_quality)
        self._select_data(self.category_box, options.category)
        self._updating = False


def _quality_label(quality: str) -> str:
    return "Best" if quality == "best" else quality


class AnalysisCard(QFrame):
    """One analysed URL: metadata, per-item options and the resolved destination."""

    removed = Signal(str)          # request id
    changed = Signal()
    rule_created = Signal()
    resuggest_requested = Signal(str)   # request id

    def __init__(
        self,
        request_id: str,
        url: str,
        settings: Settings,
        filing=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.request_id = request_id
        self.url = url
        self.info: MediaInfo | None = None
        self.error = ""
        self.error_detail = ""
        self._settings = settings
        self._filing = filing
        self._suggestion = None
        self._pending_rule = None
        #: Set once the user picks a category themselves. From then on nothing
        #: else may change it.
        self._category_touched = False
        self._applying = False
        self._kind = settings.default_media_kind

        layout = hbox(self, spacing=Space.md, margins=(Space.md, Space.md, Space.md, Space.md))

        self.thumb = Thumbnail(aspect=16 / 9, fallback_icon="link", parent=self)
        self.thumb.setFixedSize(QSize(132, 76))
        layout.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignTop)

        column = vbox(spacing=Space.xs)

        # -- Title row -----------------------------------------------------
        title_row = QWidget(self)
        title_layout = hbox(title_row, spacing=Space.sm)
        self.title = ElidedLabel(truncate(url, 80), "itemTitle", parent=title_row)
        title_layout.addWidget(self.title, 1)
        self.state_badge = Badge("Analysing", "accent", title_row)
        title_layout.addWidget(self.state_badge)
        close = icon_button("close", tooltip="Remove", size=13, tone="muted")
        close.clicked.connect(lambda: self.removed.emit(self.request_id))
        title_layout.addWidget(close)
        column.addWidget(title_row)

        self.meta = ElidedLabel("Reading metadata…", "muted", parent=self)
        column.addWidget(self.meta)

        # -- Options (hidden until analysis succeeds) ----------------------
        self.options_bar = OptionBar(settings, compact=True, parent=self)
        self.options_bar.changed.connect(self._on_options_changed)
        self.options_bar.category_edited.connect(self._on_category_changed)
        self.options_bar.hide()
        column.addSpacing(Space.xs)
        column.addWidget(self.options_bar)

        # Why this is going where it is going. A suggestion the user cannot
        # audit is one they cannot trust, so the evidence sits right here.
        self.suggestion_row = QWidget(self)
        suggestion_layout = hbox(self.suggestion_row, spacing=Space.xs)
        self.suggestion_icon = QLabel(self.suggestion_row)
        self.suggestion_icon.setFixedSize(QSize(12, 12))
        suggestion_layout.addWidget(self.suggestion_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.suggestion_label = ElidedLabel("", "muted", parent=self.suggestion_row)
        suggestion_layout.addWidget(self.suggestion_label, 1)
        self._rule_btn = button("", variant="link", size="sm")
        self._rule_btn.clicked.connect(self._create_rule)
        self._rule_btn.hide()
        suggestion_layout.addWidget(self._rule_btn)
        self.suggestion_row.hide()
        column.addWidget(self.suggestion_row)

        self.destination = ElidedLabel("", "mono", parent=self)
        self.destination.hide()
        column.addWidget(self.destination)

        self.error_row = QWidget(self)
        error_layout = hbox(self.error_row, spacing=Space.sm)
        self.error_label = ElidedLabel("", "danger", parent=self.error_row)
        self.error_label.setProperty("role", "meta")
        error_layout.addWidget(self.error_label, 1)
        self.copy_error_btn = button("Copy details", variant="link", size="sm")
        self.copy_error_btn.clicked.connect(self._copy_error)
        error_layout.addWidget(self.copy_error_btn)
        self.error_row.hide()
        column.addWidget(self.error_row)

        layout.addLayout(column, 1)

    # -- State transitions -------------------------------------------------

    def set_info(self, info: MediaInfo) -> None:
        self.info = info
        self.error = ""
        theme = get_theme()

        self.title.setText(info.title or self.url)
        self.state_badge.setText("Ready")
        self.state_badge.set_tone("success")

        parts = [p for p in (info.creator, info.platform) if p]
        if info.duration:
            parts.append(format_duration(info.duration))
        if info.upload_date:
            parts.append(format_date(info.upload_date))
        best = self._best_format_summary(info)
        if best:
            parts.append(best)
        self.meta.setText("  ·  ".join(parts))

        if info.thumbnail_path:
            self.thumb.set_source(info.thumbnail_path, max_edge=320)
        self.thumb.set_fallback_icon("audio" if not info.has_video else "video")
        if info.duration:
            self.thumb.set_duration(info.duration)

        # Offer only what the source actually has.
        self.options_bar.set_available_qualities(info.available_video_qualities)
        if not info.has_video:
            self.options_bar.set_kind_locked("audio")
        self.options_bar.show()
        self.destination.show()
        self.error_row.hide()
        self._refresh_destination()
        if theme is not None:
            self.meta.setStyleSheet(f"color: {theme.palette.text_secondary};")
        self.changed.emit()

    def set_error(self, message: str, detail: str = "") -> None:
        self.info = None
        self.error = message
        self.error_detail = detail or message
        self.state_badge.setText("Failed")
        self.state_badge.set_tone("danger")
        self.meta.setText(truncate(self.url, 90))
        self.error_label.setText(message)
        self.error_row.show()
        self.options_bar.hide()
        self.destination.hide()
        self.changed.emit()

    @property
    def is_ready(self) -> bool:
        return self.info is not None and not self.error

    def options(self) -> DownloadOptions:
        chosen = self.options_bar.options()
        chosen.category_source = self._category_source()
        return chosen

    def _category_source(self) -> str:
        """Provenance for the category this card will download with."""
        from app.models.filing import SOURCE_DEFAULT, SOURCE_USER

        if self._category_touched:
            return SOURCE_USER
        if self._suggestion is not None and self._suggestion.is_confident:
            return self._suggestion.source
        return SOURCE_DEFAULT

    def apply_defaults(self, options: DownloadOptions) -> None:
        """Take format and quality from the defaults bar.

        The *category* is deliberately excluded once this card has one of its
        own. Changing the defaults must never silently discard a per-item
        choice - or a suggestion the user has already read and accepted.
        """
        if not self.is_ready:
            return

        keep_category = self._category_touched or (
            self._suggestion is not None and self._suggestion.is_confident
        )
        current = self.options_bar.options().category if keep_category else ""

        self._applying = True
        try:
            self.options_bar.apply_options(options)
            if keep_category and current:
                self.options_bar.set_category(current)
        finally:
            self._applying = False
        self._refresh_destination()

    # -- Suggestion -------------------------------------------------------

    def apply_suggestion(self, suggestion) -> None:
        """Pre-select where Mediary thinks this belongs, and say why."""
        self._suggestion = suggestion
        if suggestion is None or not suggestion.is_confident:
            self.suggestion_row.hide()
            return

        self.options_bar.set_category(suggestion.category)
        self._show_suggestion_text(suggestion.reason)
        self._rule_btn.hide()
        self.suggestion_row.show()
        self._refresh_destination()

    def accepted_suggestion(self):
        """The suggestion this card is about to download with, if any.

        ``None`` once the user has picked a category themselves - their choice
        is not evidence that the suggestion was right.
        """
        if not self.is_ready or self._category_touched:
            return None
        if self._suggestion is None or not self._suggestion.is_confident:
            return None
        return self._suggestion

    def _show_suggestion_text(self, text: str) -> None:
        theme = get_theme()
        if theme is not None:
            self.suggestion_icon.setPixmap(theme.pixmap("sparkle", 12, "accent"))
        self.suggestion_label.setText(text)

    def _on_category_changed(self) -> None:
        """The user overrode the suggestion - offer to make it permanent."""
        if not self.is_ready or self._applying:
            return
        self._category_touched = True
        self._pending_rule = None

        chosen = self.options_bar.options().category
        self._show_suggestion_text("Using your choice")
        self.suggestion_row.show()

        offer = None
        if self._filing is not None and self.info is not None:
            offer = self._filing.rule_offer(self.info, chosen)
        if offer is None:
            self._rule_btn.hide()
            return

        self._pending_rule = offer
        self._rule_btn.setText(f"Always use {chosen} for {offer.pattern}")
        self._rule_btn.setEnabled(True)
        self._rule_btn.show()

    def _create_rule(self) -> None:
        if self._filing is None or self._pending_rule is None:
            return
        self._filing.save_rule(self._pending_rule)
        self._rule_btn.setText("Rule saved")
        self._rule_btn.setEnabled(False)
        self.rule_created.emit()

    # -- Helpers -----------------------------------------------------------

    def _on_options_changed(self) -> None:
        # Audio and video have different category sets, so a video suggestion
        # is meaningless once the user switches this card to audio.
        kind = self.options_bar.kind.value()
        if kind != self._kind and not self._category_touched:
            self._kind = kind
            self._suggestion = None
            self.suggestion_row.hide()
            self.resuggest_requested.emit(self.request_id)
        else:
            self._kind = kind
        self._refresh_destination()
        self.changed.emit()

    def _refresh_destination(self) -> None:
        if self.info is None:
            return
        from app.services.organization_service import OrganizationService

        organizer = OrganizationService(self._settings)
        options = self.options()
        path = organizer.preview_destination(options, self.info.title or "Untitled")
        try:
            shown = path.relative_to(self._settings.root_path)
        except ValueError:
            shown = path
        self.destination.setText(f"→  {shown}")
        self.destination.setToolTip(str(path))

    @staticmethod
    def _best_format_summary(info: MediaInfo) -> str:
        if not info.formats:
            return ""
        best = info.formats[0]
        bits = []
        if best.height:
            bits.append(f"{best.height}p")
            if best.fps and best.fps >= 40:
                bits.append(f"{best.fps:.0f}fps")
        if best.filesize:
            bits.append(format_bytes(best.filesize))
        return " ".join(bits)

    def _copy_error(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(f"URL: {self.url}\n\n{self.error_detail}")
        self.copy_error_btn.setText("Copied")


class DownloadView(QWidget):
    """The paste-analyse-download screen."""

    #: ``(url, DownloadOptions, MediaInfo)`` for each item the user confirmed.
    download_requested = Signal(list)
    show_queue_requested = Signal()
    #: A filing rule was created or changed from a card.
    rules_changed = Signal()
    #: A category the user invented, for the app to persist.
    category_created = Signal(str)

    def __init__(
        self,
        settings: Settings,
        manager,
        filing=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._manager = manager
        self._filing = filing
        self._cards: dict = {}
        self._pending = 0

        root = vbox(self, spacing=0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)

        # Centre a fixed-width column so the screen stays readable on ultrawide
        # displays instead of stretching the URL field across a metre of glass.
        wrapper = QWidget(scroll)
        wrapper_layout = hbox(wrapper, spacing=0)

        content = QWidget(wrapper)
        content.setMaximumWidth(940)
        self._content_layout = vbox(
            content, spacing=0, margins=(Space.x3l, Space.xxl, Space.x3l, Space.x3l)
        )

        wrapper_layout.addStretch(1)
        wrapper_layout.addWidget(content, 10)
        wrapper_layout.addStretch(1)
        scroll.setWidget(wrapper)

        self._build_header()
        self._build_input()
        self._build_defaults()
        self._build_results()

        self._shortcut_analyze = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._shortcut_analyze.activated.connect(self.analyze)
        self._shortcut_analyze_alt = QShortcut(QKeySequence("Ctrl+Enter"), self)
        self._shortcut_analyze_alt.activated.connect(self.analyze)

    # -- Construction -----------------------------------------------------

    def _build_header(self) -> None:
        self._content_layout.addWidget(label("Download", "pageTitle"))
        self._content_layout.addSpacing(Space.xs)
        self._content_layout.addWidget(
            label(
                "Paste one or more public media URLs. Mediary reads what is there, "
                "then downloads it into your library.",
                "pageSubtitle",
                wrap=True,
            )
        )
        self._content_layout.addSpacing(Space.xl)

    def _build_input(self) -> None:
        card = panel(parent=self)
        layout = vbox(card, spacing=Space.md, margins=(Space.lg, Space.lg, Space.lg, Space.lg))

        self.url_input = QPlainTextEdit(card)
        self.url_input.setPlaceholderText(
            "Paste a public media URL…\n"
            "Add more on separate lines to download a batch."
        )
        self.url_input.setFixedHeight(96)
        self.url_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.url_input.textChanged.connect(self._on_input_changed)
        layout.addWidget(self.url_input)

        # The clipboard almost always already holds the URL the user came here
        # to paste. Offering it directly turns a four-step trip through the
        # field into one click.
        self.clipboard_hint = QWidget(card)
        hint_layout = hbox(self.clipboard_hint, spacing=Space.sm)
        self._clipboard_btn = button("", variant="link")
        self._clipboard_btn.clicked.connect(self._use_clipboard)
        hint_layout.addWidget(self._clipboard_btn)
        hint_layout.addStretch(1)
        self.clipboard_hint.hide()
        layout.addWidget(self.clipboard_hint)

        actions = QWidget(card)
        actions_layout = hbox(actions, spacing=Space.sm)

        self.url_count = label("", "muted")
        actions_layout.addWidget(self.url_count)
        actions_layout.addStretch(1)

        self.paste_btn = button("Paste", variant="subtle", icon="clipboard", on_click=self.paste)
        self.paste_btn.setToolTip("Paste from clipboard  (Ctrl+V)")
        actions_layout.addWidget(self.paste_btn)

        self.analyze_btn = button("Analyse", variant="primary", icon="search", on_click=self.analyze)
        self.analyze_btn.setToolTip("Read metadata for these URLs  (Ctrl+Enter)")
        self.analyze_btn.setEnabled(False)
        actions_layout.addWidget(self.analyze_btn)

        layout.addWidget(actions)
        self._content_layout.addWidget(card)
        self._content_layout.addSpacing(Space.lg)

    def _build_defaults(self) -> None:
        self._defaults_row = QWidget(self)
        layout = hbox(self._defaults_row, spacing=Space.md)
        layout.addWidget(label("DEFAULTS", "fieldLabel"))
        self.default_options = OptionBar(self._settings, parent=self._defaults_row)
        self.default_options.category_created.connect(self.category_created.emit)
        self.default_options.changed.connect(self._apply_defaults_to_cards)
        layout.addWidget(self.default_options, 1)
        self._content_layout.addWidget(self._defaults_row)
        self._content_layout.addSpacing(Space.lg)

    def _build_results(self) -> None:
        self._notice_slot = QWidget(self)
        self._notice_layout = vbox(self._notice_slot, spacing=Space.sm)
        self._content_layout.addWidget(self._notice_slot)

        self._results = QWidget(self)
        self._results_layout = vbox(self._results, spacing=Space.sm)
        self._content_layout.addWidget(self._results)

        self._empty = EmptyState(
            icon="download",
            title="Nothing analysed yet",
            body=(
                "Paste a link above and Mediary will show you the title, creator, "
                "length and every format the source offers before anything downloads."
            ),
        )
        self._content_layout.addWidget(self._empty)

        self._footer = QWidget(self)
        footer_layout = hbox(self._footer, spacing=Space.sm)
        self.summary_label = label("", "meta")
        footer_layout.addWidget(self.summary_label)
        footer_layout.addStretch(1)
        self.clear_btn = button("Clear", variant="ghost", on_click=self.clear_results)
        footer_layout.addWidget(self.clear_btn)
        self.download_btn = button(
            "Download", variant="primary", icon="download", on_click=self._start_downloads
        )
        footer_layout.addWidget(self.download_btn)
        self._footer.hide()
        self._content_layout.addSpacing(Space.lg)
        self._content_layout.addWidget(self._footer)
        self._content_layout.addStretch(1)

    # -- Input ------------------------------------------------------------

    def paste(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text.strip():
            return
        current = self.url_input.toPlainText().strip()
        self.url_input.setPlainText(f"{current}\n{text.strip()}" if current else text.strip())
        self.url_input.moveCursor(self.url_input.textCursor().MoveOperation.End)
        self.url_input.setFocus()

    def focus_input(self) -> None:
        self.url_input.setFocus()
        self.url_input.selectAll()

    def refresh_clipboard_hint(self) -> None:
        """Offer whatever URL is on the clipboard, if it is not already listed.

        Called whenever this screen becomes visible. Reading the clipboard is
        local and passive - nothing is fetched until the user clicks.
        """
        text = (QGuiApplication.clipboard().text() or "").strip()
        urls = parse_urls(text)
        if not urls:
            self.clipboard_hint.hide()
            return

        already = {card.url for card in self._cards.values()}
        already.update(parse_urls(self.url_input.toPlainText()))
        fresh = [url for url in urls if url not in already]
        if not fresh:
            self.clipboard_hint.hide()
            return

        self._clipboard_urls = fresh
        if len(fresh) == 1:
            self._clipboard_btn.setText(f"Paste {truncate(fresh[0], 58)}")
        else:
            self._clipboard_btn.setText(f"Paste {len(fresh)} URLs from your clipboard")
        self.clipboard_hint.show()

    def _use_clipboard(self) -> None:
        urls = getattr(self, "_clipboard_urls", [])
        if not urls:
            return
        current = self.url_input.toPlainText().strip()
        joined = "\n".join(urls)
        self.url_input.setPlainText(f"{current}\n{joined}" if current else joined)
        self.clipboard_hint.hide()
        self.analyze()

    def _on_input_changed(self) -> None:
        urls = parse_urls(self.url_input.toPlainText())
        self.analyze_btn.setEnabled(bool(urls))
        raw = self.url_input.toPlainText().strip()
        if not raw:
            self.url_count.setText("")
        elif not urls:
            self.url_count.setText("No valid URL found")
        else:
            self.url_count.setText(f"{len(urls)} URL{'s' if len(urls) != 1 else ''} detected")

    # -- Analysis ---------------------------------------------------------

    def analyze(self) -> None:
        urls = parse_urls(self.url_input.toPlainText())
        if not urls:
            return

        existing = {card.url for card in self._cards.values()}
        new_urls = [url for url in urls if url not in existing]
        if not new_urls:
            self._show_notice("Those URLs are already listed below.", "info")
            return

        self._empty.hide()
        self.url_input.clear()

        for url in new_urls:
            request_id = uuid.uuid4().hex
            card = AnalysisCard(
                request_id, url, self._settings, self._filing, self._results
            )
            card.removed.connect(self._remove_card)
            card.changed.connect(self._refresh_footer)
            card.rule_created.connect(self.rules_changed.emit)
            card.resuggest_requested.connect(self._on_resuggest)
            card.options_bar.category_created.connect(self.category_created.emit)
            self._results_layout.addWidget(card)
            self._cards[request_id] = card
            self._pending += 1
            self._manager.analyze(request_id, url, self._on_analyzed, self._on_analysis_failed)

        self._set_busy(True)
        self._refresh_footer()

    def _on_analyzed(self, request_id: str, info: MediaInfo) -> None:
        card = self._cards.get(request_id)
        self._pending = max(0, self._pending - 1)
        if card is not None:
            card.set_info(info)
            card.apply_defaults(self.default_options.options())
            self._suggest_for(card, info)
            self._fetch_thumbnail(card, info)
        if self._pending == 0:
            self._set_busy(False)
        self._refresh_footer()

    def _on_analysis_failed(
        self, request_id: str, category: str, message: str, detail: str
    ) -> None:
        card = self._cards.get(request_id)
        self._pending = max(0, self._pending - 1)
        if card is not None:
            card.set_error(message, detail)
        if self._pending == 0:
            self._set_busy(False)
        self._refresh_footer()

    def _on_resuggest(self, request_id: str) -> None:
        card = self._cards.get(request_id)
        if card is not None and card.info is not None:
            self._suggest_for(card, card.info)

    def _suggest_for(self, card: AnalysisCard, info: MediaInfo) -> None:
        """Ask where this belongs, if smart filing is on."""
        if self._filing is None or not getattr(self._settings, "smart_filing", True):
            return
        kind = card.options_bar.kind.value() or self._settings.default_media_kind
        try:
            suggestion = self._filing.suggest(
                info, kind, default_category=self._settings.default_category
            )
        except Exception:  # noqa: BLE001 - a suggestion is never worth a crash
            log.exception("Could not suggest a category for %s", card.url)
            return
        card.apply_suggestion(suggestion)

    def _fetch_thumbnail(self, card: AnalysisCard, info: MediaInfo) -> None:
        """Download the preview image in the background, if there is one."""
        if not info.thumbnail_url:
            return
        from app.services.thumbnail_service import fetch_thumbnail

        def apply(path: str) -> None:
            if path and card.request_id in self._cards:
                info.thumbnail_path = path
                card.thumb.set_source(path, max_edge=320)

        fetch_thumbnail(info.thumbnail_url, info.platform_id or card.request_id, apply, self)

    def _set_busy(self, busy: bool) -> None:
        self.analyze_btn.setEnabled(not busy and bool(parse_urls(self.url_input.toPlainText())))
        self.analyze_btn.setText("Analysing…" if busy else "Analyse")

    # -- Results ----------------------------------------------------------

    def _apply_defaults_to_cards(self) -> None:
        defaults = self.default_options.options()
        for card in self._cards.values():
            card.apply_defaults(defaults)
        self._refresh_footer()

    def _remove_card(self, request_id: str) -> None:
        card = self._cards.pop(request_id, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()
        if not self._cards:
            self._empty.show()
        self._refresh_footer()

    def clear_results(self) -> None:
        for request_id in list(self._cards):
            self._remove_card(request_id)
        self._clear_notices()

    def _refresh_footer(self) -> None:
        ready = [card for card in self._cards.values() if card.is_ready]
        failed = [card for card in self._cards.values() if card.error]
        total = len(self._cards)

        self._footer.setVisible(total > 0)
        self.download_btn.setEnabled(bool(ready))
        self.download_btn.setText(
            f"Download {len(ready)}" if len(ready) > 1 else "Download"
        )

        bits = []
        if self._pending:
            bits.append(f"{self._pending} analysing")
        if ready:
            bits.append(f"{len(ready)} ready")
        if failed:
            bits.append(f"{len(failed)} failed")
        self.summary_label.setText("  ·  ".join(bits))

    def _start_downloads(self) -> None:
        requests = [
            (card.url, card.options(), card.info)
            for card in self._cards.values()
            if card.is_ready
        ]
        if not requests:
            return
        self._note_rules_used()
        self.download_requested.emit(requests)
        for card in list(self._cards.values()):
            if card.is_ready:
                self._remove_card(card.request_id)

    def _note_rules_used(self) -> None:
        """Count a rule as used only when a download actually goes out with it.

        Counting at suggestion time would inflate the number every time an item
        was analysed and then removed.
        """
        if self._filing is None:
            return
        for card in self._cards.values():
            suggestion = card.accepted_suggestion()
            if suggestion is not None:
                self._filing.note_applied(suggestion)

    # -- Notices ----------------------------------------------------------

    def _show_notice(self, message: str, tone: str = "info") -> None:
        self._clear_notices()
        notice = Notice(message, tone=tone, parent=self._notice_slot)
        self._notice_layout.addWidget(notice)

    def _clear_notices(self) -> None:
        while self._notice_layout.count():
            item = self._notice_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def add_persistent_notice(self, notice: QWidget) -> None:
        self._notice_layout.addWidget(notice)

    # -- External ---------------------------------------------------------

    def prefill(self, text: str) -> None:
        self.url_input.setPlainText(text)
        self.url_input.setFocus()

    def refresh_settings(self) -> None:
        self.default_options._apply_settings()
