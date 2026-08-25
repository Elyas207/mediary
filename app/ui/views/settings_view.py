"""Settings.

Grouped cards of labelled rows - the convention every desktop preferences pane
uses, because it lets someone scan for the one control they came for.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QWidget,
)

from app.config.settings import (
    THEME_DARK,
    THEME_LIGHT,
    THEME_SYSTEM,
    SettingsStore,
)
from app.downloader.ytdlp_adapter import ytdlp_version
from app.media.ffmpeg import get_ffmpeg
from app.models.category import KIND_AUDIO, KIND_VIDEO, categories_for_kind
from app.models.download import AUDIO_FORMATS, MP3_BITRATES, VIDEO_FORMATS, VIDEO_QUALITIES
from app.services.library_service import LibraryService
from app.ui.theme import Size, Space, get_theme
from app.ui.widgets.common import (
    Badge,
    ElidedLabel,
    button,
    divider,
    hbox,
    label,
    panel,
    vbox,
)
from app.utils.filenames import TEMPLATE_FIELDS
from app.utils.formatting import format_bytes
from app.utils.logging import get_logger
from app.utils.paths import config_dir, data_dir, logs_dir

log = get_logger("ui.settings")


class AccentSwatch(QWidget):
    """A dot showing the accent colour currently in effect."""

    SIZE = 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(self.SIZE, self.SIZE))
        self.setToolTip("The accent colour Mediary is using")

    def refresh(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        from PySide6.QtGui import QColor, QPainter

        theme = get_theme()
        if theme is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.palette.accent))
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.end()


class SettingRow(QWidget):
    """One labelled control: title, optional description, control on the right."""

    def __init__(
        self,
        title: str,
        control: QWidget,
        *,
        description: str = "",
        stacked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SettingRow")

        if stacked:
            layout = vbox(self, spacing=Space.sm, margins=(Space.lg, Space.md, Space.lg, Space.md))
            text = vbox(spacing=2)
            text.addWidget(label(title, "itemTitle"))
            if description:
                text.addWidget(label(description, "muted", wrap=True))
            layout.addLayout(text)
            layout.addWidget(control)
            return

        layout = hbox(self, spacing=Space.xl, margins=(Space.lg, Space.md, Space.lg, Space.md))
        text = vbox(spacing=2)
        text.addWidget(label(title, "itemTitle"))
        if description:
            description_label = label(description, "muted", wrap=True)
            description_label.setMaximumWidth(420)
            text.addWidget(description_label)
        layout.addLayout(text, 1)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class SettingsGroup(QWidget):
    """A titled card containing setting rows."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = vbox(self, spacing=Space.sm)
        layout.addWidget(label(title, "sectionLabel"))

        self._card = panel(parent=self)
        self._card.setObjectName("SettingsGroup")
        self._card_layout = vbox(self._card, spacing=0)
        layout.addWidget(self._card)
        self._rows: list = []

    def add(self, row: QWidget) -> QWidget:
        if self._rows:
            self._card_layout.addWidget(divider())
        self._card_layout.addWidget(row)
        self._rows.append(row)
        return row


class SettingsView(QWidget):
    """The preferences screen."""

    settings_changed = Signal(list)     # changed keys
    rescan_requested = Signal()
    uninstall_requested = Signal()

    def __init__(
        self,
        store: SettingsStore,
        theme,
        library: LibraryService,
        filing=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._theme = theme
        self._library = library
        self._filing = filing
        self._loading = False
        self._controls: dict = {}

        root = vbox(self, spacing=0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)

        wrapper = QWidget(scroll)
        wrapper_layout = hbox(wrapper, spacing=0)

        content = QWidget(wrapper)
        content.setMaximumWidth(820)
        self._layout = vbox(
            content, spacing=Space.xxl, margins=(Space.x3l, Space.xxl, Space.x3l, Space.x3l)
        )

        wrapper_layout.addStretch(1)
        wrapper_layout.addWidget(content, 10)
        wrapper_layout.addStretch(1)
        scroll.setWidget(wrapper)

        self._build_header()
        self._build_downloads()
        self._build_organisation()
        self._build_performance()
        self._build_appearance()
        self._build_startup()
        self._build_tools()
        self._build_data()
        self._layout.addStretch(1)

        self.reload()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = QWidget(self)
        layout = vbox(header, spacing=Space.xs)
        layout.addWidget(label("Settings", "pageTitle"))
        layout.addWidget(
            label("Changes save as you make them.", "pageSubtitle")
        )
        self._layout.addWidget(header)

    def _build_downloads(self) -> None:
        group = SettingsGroup("Downloads", self)

        root_row = QWidget(group)
        root_layout = hbox(root_row, spacing=Space.sm)
        self._library_root = QLineEdit(root_row)
        self._library_root.setReadOnly(True)
        self._library_root.setMinimumWidth(300)
        root_layout.addWidget(self._library_root, 1)
        root_layout.addWidget(
            button("Change…", variant="subtle", size="sm", on_click=self._choose_root)
        )
        root_layout.addWidget(
            button("Open", variant="ghost", size="sm", on_click=self._open_root)
        )
        group.add(
            SettingRow(
                "Media library folder",
                root_row,
                description="Where Mediary stores every file it downloads.",
                stacked=True,
            )
        )

        self._default_kind = self._combo(
            [("video", "Video"), ("audio", "Audio")], "default_media_kind", width=120
        )
        self._default_kind.currentIndexChanged.connect(self._on_kind_changed)
        group.add(SettingRow("Default type", self._default_kind))

        self._default_video_format = self._combo(
            [(f, f.upper()) for f in VIDEO_FORMATS], "default_video_format", width=120
        )
        group.add(SettingRow("Default video format", self._default_video_format))

        self._default_video_quality = self._combo(
            [(q, "Best available" if q == "best" else q) for q in VIDEO_QUALITIES],
            "default_video_quality",
            width=140,
        )
        group.add(
            SettingRow(
                "Default video quality",
                self._default_video_quality,
                description="Mediary never downloads above what the source actually offers.",
            )
        )

        self._default_audio_format = self._combo(
            [(f, f.upper()) for f in AUDIO_FORMATS], "default_audio_format", width=120
        )
        self._default_audio_format.currentIndexChanged.connect(self._sync_bitrate_enabled)
        group.add(SettingRow("Default audio format", self._default_audio_format))

        self._default_audio_bitrate = self._combo(
            [(b, f"{b} kbps") for b in reversed(MP3_BITRATES)],
            "default_audio_bitrate",
            width=120,
        )
        group.add(
            SettingRow(
                "Default audio bitrate",
                self._default_audio_bitrate,
                description=(
                    "Only applies to lossy formats. Converting a low-quality source to a "
                    "higher bitrate does not improve it."
                ),
            )
        )

        self._default_category = self._combo([], "default_category", width=160)
        group.add(SettingRow("Default category", self._default_category))

        self._duplicate_action = self._combo(
            [
                ("ask", "Ask me"),
                ("skip", "Skip"),
                ("download", "Download anyway"),
                ("replace", "Replace"),
            ],
            "duplicate_action",
            width=160,
        )
        group.add(
            SettingRow(
                "When media is already in the library",
                self._duplicate_action,
                description="Matched by source URL or platform media ID.",
            )
        )

        self._layout.addWidget(group)

    def _build_organisation(self) -> None:
        group = SettingsGroup("Organisation", self)

        self._smart_filing = self._check("smart_filing")
        group.add(
            SettingRow(
                "Suggest a category for each download",
                self._smart_filing,
                description=(
                    "Learns from where you have filed things before. Off means every "
                    "download starts in your default category."
                ),
            )
        )

        group.add(
            SettingRow(
                "Filing rules",
                button(
                    "Manage rules…", variant="subtle", size="sm",
                    on_click=self._open_filing_rules,
                ),
                description="Always file a particular creator or platform in one place.",
            )
        )

        self._auto_organize = self._check("auto_organize")
        group.add(
            SettingRow(
                "Organise into category folders",
                self._auto_organize,
                description="Off puts every download directly in the library root.",
            )
        )

        self._auto_add = self._check("auto_add_to_library")
        group.add(SettingRow("Add downloads to the library index", self._auto_add))

        self._embed_thumbnails = self._check("embed_thumbnails")
        group.add(
            SettingRow(
                "Embed artwork",
                self._embed_thumbnails,
                description="Writes cover art into MP3, M4A, FLAC and MP4 files. Needs FFmpeg.",
            )
        )

        self._embed_metadata = self._check("embed_metadata")
        group.add(
            SettingRow(
                "Embed title and creator metadata",
                self._embed_metadata,
                description="Needs FFmpeg.",
            )
        )

        template_row = QWidget(group)
        template_layout = vbox(template_row, spacing=Space.xs)
        self._filename_template = QLineEdit(template_row)
        self._filename_template.setPlaceholderText("{title}")
        self._filename_template.editingFinished.connect(
            lambda: self._save("filename_template", self._filename_template.text())
        )
        template_layout.addWidget(self._filename_template)
        self._template_preview = ElidedLabel("", "mono", parent=template_row)
        template_layout.addWidget(self._template_preview)
        self._filename_template.textChanged.connect(self._update_template_preview)
        tokens = label(
            "Available: " + "  ".join("{" + name + "}" for name in TEMPLATE_FIELDS),
            "muted",
            wrap=True,
        )
        template_layout.addWidget(tokens)
        group.add(
            SettingRow(
                "Filename template",
                template_row,
                description="How Mediary names files it saves.",
                stacked=True,
            )
        )

        self._layout.addWidget(group)

    def _build_performance(self) -> None:
        group = SettingsGroup("Performance", self)

        self._concurrency = QSpinBox(group)
        self._concurrency.setRange(1, 8)
        self._concurrency.setFixedWidth(80)
        self._concurrency.valueChanged.connect(
            lambda value: self._save("concurrent_downloads", value)
        )
        group.add(
            SettingRow(
                "Concurrent downloads",
                self._concurrency,
                description="Two is a good balance. Higher values hammer the source site.",
            )
        )

        speed_row = QWidget(group)
        speed_layout = hbox(speed_row, spacing=Space.sm)
        self._max_speed = QSpinBox(speed_row)
        self._max_speed.setRange(0, 1_000_000)
        self._max_speed.setSingleStep(256)
        self._max_speed.setFixedWidth(120)
        self._max_speed.setSpecialValueText("Unlimited")
        self._max_speed.setSuffix(" KB/s")
        self._max_speed.valueChanged.connect(lambda value: self._save("max_speed_kbps", value))
        speed_layout.addWidget(self._max_speed)
        group.add(SettingRow("Maximum download speed", speed_row))

        self._retries = QSpinBox(group)
        self._retries.setRange(0, 10)
        self._retries.setFixedWidth(80)
        self._retries.valueChanged.connect(lambda value: self._save("retry_count", value))
        group.add(SettingRow("Retry attempts", self._retries))

        self._timeout = QSpinBox(group)
        self._timeout.setRange(5, 300)
        self._timeout.setFixedWidth(90)
        self._timeout.setSuffix(" s")
        self._timeout.valueChanged.connect(lambda value: self._save("socket_timeout", value))
        group.add(SettingRow("Network timeout", self._timeout))

        self._layout.addWidget(group)

    def _build_appearance(self) -> None:
        group = SettingsGroup("Appearance", self)

        self._theme_box = self._combo(
            [(THEME_SYSTEM, "Follow system"), (THEME_DARK, "Dark"), (THEME_LIGHT, "Light")],
            "theme",
            width=160,
        )
        group.add(
            SettingRow(
                "Theme",
                self._theme_box,
                description="Follow system tracks your desktop's light/dark setting live.",
            )
        )

        accent_row = QWidget(group)
        accent_layout = hbox(accent_row, spacing=Space.sm)
        self._accent_swatch = AccentSwatch(accent_row)
        accent_layout.addWidget(self._accent_swatch)
        self._use_system_accent = self._check("use_system_accent")
        accent_layout.addWidget(self._use_system_accent)
        group.add(
            SettingRow(
                "Use my system accent colour",
                accent_row,
                description=(
                    "Takes the highlight colour from your desktop settings. "
                    "Turn this off to use Mediary's own blue."
                ),
            )
        )

        self._reduce_motion = self._check("reduce_motion")
        group.add(
            SettingRow(
                "Reduce motion",
                self._reduce_motion,
                description="Skip animations and transitions throughout the app.",
            )
        )

        self._thumb_size = QSpinBox(group)
        self._thumb_size.setRange(140, 340)
        self._thumb_size.setSingleStep(20)
        self._thumb_size.setFixedWidth(90)
        self._thumb_size.setSuffix(" px")
        self._thumb_size.valueChanged.connect(
            lambda value: self._save("grid_thumbnail_size", value)
        )
        group.add(SettingRow("Grid card width", self._thumb_size))

        self._layout.addWidget(group)

    def _build_startup(self) -> None:
        from app.services.autostart_service import AutostartService
        from app.ui.tray import tray_available

        group = SettingsGroup("Startup and background", self)
        has_tray = tray_available()
        supported = AutostartService.is_supported()

        self._launch_at_startup = self._check("launch_at_startup")
        self._launch_at_startup.setEnabled(supported)
        group.add(
            SettingRow(
                "Launch Mediary when I sign in",
                self._launch_at_startup,
                description=(
                    AutostartService.describe_location()
                    if supported
                    else "Not supported on this platform."
                ),
            )
        )

        self._start_hidden = self._check("start_hidden")
        self._start_hidden.setEnabled(has_tray)
        group.add(
            SettingRow(
                "Start hidden in the background",
                self._start_hidden,
                description=(
                    "No window and no taskbar entry at sign-in — Mediary waits in the "
                    "system tray. Click the tray icon to open it."
                    if has_tray
                    else "Unavailable: this desktop has no system tray, so a hidden "
                         "Mediary would have no way back."
                ),
            )
        )

        self._close_to_tray = self._check("close_to_tray")
        self._close_to_tray.setEnabled(has_tray)
        group.add(
            SettingRow(
                "Keep running when the window is closed",
                self._close_to_tray,
                description=(
                    "Closing the window hides it to the tray instead of quitting, so "
                    "downloads finish. Quit from the tray menu."
                    if has_tray
                    else "Unavailable: this desktop has no system tray."
                ),
            )
        )

        self._tray_notifications = self._check("tray_notifications")
        self._tray_notifications.setEnabled(has_tray)
        group.add(
            SettingRow(
                "Notify me when a background download finishes",
                self._tray_notifications,
                description="Uses your desktop's notification system.",
            )
        )

        self._layout.addWidget(group)

    def _build_tools(self) -> None:
        group = SettingsGroup("Tools", self)

        # -- yt-dlp -------------------------------------------------------
        ytdlp_row = QWidget(group)
        ytdlp_layout = hbox(ytdlp_row, spacing=Space.sm)
        self._ytdlp_badge = Badge(ytdlp_version(), "success", ytdlp_row)
        ytdlp_layout.addWidget(self._ytdlp_badge)
        ytdlp_layout.addWidget(
            button("Check for updates", variant="subtle", size="sm", on_click=self._check_ytdlp)
        )
        group.add(
            SettingRow(
                "yt-dlp",
                ytdlp_row,
                description="The extractor Mediary uses. Mediary never updates it silently.",
            )
        )

        # -- FFmpeg -------------------------------------------------------
        ffmpeg_row = QWidget(group)
        ffmpeg_layout = hbox(ffmpeg_row, spacing=Space.sm)
        self._ffmpeg_badge = Badge("Checking…", "", ffmpeg_row)
        ffmpeg_layout.addWidget(self._ffmpeg_badge)
        ffmpeg_layout.addWidget(
            button("Detect", variant="ghost", size="sm", on_click=self._detect_ffmpeg)
        )
        ffmpeg_layout.addWidget(
            button("Choose…", variant="subtle", size="sm", on_click=self._choose_ffmpeg)
        )
        self._ffmpeg_row = SettingRow(
            "FFmpeg",
            ffmpeg_row,
            description="Required for audio extraction, format conversion and merged video.",
        )
        group.add(self._ffmpeg_row)

        self._ffmpeg_path_label = ElidedLabel("", "mono", parent=group)
        group.add(SettingRow("FFmpeg location", self._ffmpeg_path_label, stacked=True))

        self._layout.addWidget(group)

    def _build_data(self) -> None:
        group = SettingsGroup("Library data", self)

        self._stats_label = label("", "meta", wrap=True)
        group.add(SettingRow("Library", self._stats_label, stacked=True))

        rescan_row = QWidget(group)
        rescan_layout = hbox(rescan_row, spacing=Space.sm)
        rescan_layout.addWidget(
            button("Rescan library", variant="subtle", size="sm",
                   on_click=self.rescan_requested.emit)
        )
        rescan_layout.addWidget(
            button("Rebuild search index", variant="ghost", size="sm",
                   on_click=self._rebuild_index)
        )
        group.add(
            SettingRow(
                "Maintenance",
                rescan_row,
                description=(
                    "Rescan finds files you moved or added outside Mediary and flags "
                    "anything that has gone missing."
                ),
            )
        )

        folders_row = QWidget(group)
        folders_layout = hbox(folders_row, spacing=Space.sm)
        folders_layout.addWidget(
            button("Open logs folder", variant="ghost", size="sm",
                   on_click=lambda: self._open_folder(logs_dir()))
        )
        folders_layout.addWidget(
            button("Open data folder", variant="ghost", size="sm",
                   on_click=lambda: self._open_folder(data_dir()))
        )
        folders_layout.addWidget(
            button("Open config folder", variant="ghost", size="sm",
                   on_click=lambda: self._open_folder(config_dir()))
        )
        group.add(SettingRow("Local files", folders_row, stacked=True))

        privacy = label(
            "Mediary is local-first. It has no backend, sends no analytics, and never "
            "uploads your media, URLs, notes or library data.",
            "muted",
            wrap=True,
        )
        group.add(SettingRow("Privacy", privacy, stacked=True))

        uninstall_row = QWidget(group)
        uninstall_layout = hbox(uninstall_row, spacing=Space.sm)
        uninstall_layout.addWidget(
            button("Remove Mediary's data…", variant="danger", size="sm",
                   on_click=self.uninstall_requested.emit)
        )
        uninstall_layout.addStretch(1)
        group.add(
            SettingRow(
                "Uninstall",
                uninstall_row,
                description=(
                    "Delete settings, the library index, caches and logs. Your "
                    "downloaded media is kept unless you explicitly choose otherwise."
                ),
                stacked=True,
            )
        )

        self._layout.addWidget(group)

    # ------------------------------------------------------------------
    # Control factories
    # ------------------------------------------------------------------

    def _combo(self, options: list, key: str, *, width: int = 140) -> QComboBox:
        box = QComboBox(self)
        box.setFixedWidth(width)
        for value, text in options:
            box.addItem(text, value)
        box.currentIndexChanged.connect(
            lambda _index, k=key, b=box: self._save(k, b.currentData())
        )
        self._controls[key] = box
        return box

    def _check(self, key: str) -> QCheckBox:
        box = QCheckBox(self)
        box.toggled.connect(lambda checked, k=key: self._save(k, checked))
        self._controls[key] = box
        return box

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def reload(self) -> None:
        self._loading = True
        settings = self._store.settings

        self._library_root.setText(settings.library_root)
        self._select(self._default_kind, settings.default_media_kind)
        self._select(self._default_video_format, settings.default_video_format)
        self._select(self._default_video_quality, settings.default_video_quality)
        self._select(self._default_audio_format, settings.default_audio_format)
        self._select(self._default_audio_bitrate, settings.default_audio_bitrate)
        self._rebuild_categories(settings.default_media_kind, settings.default_category)
        self._select(self._duplicate_action, settings.duplicate_action)

        self._smart_filing.setChecked(settings.smart_filing)
        self._auto_organize.setChecked(settings.auto_organize)
        self._auto_add.setChecked(settings.auto_add_to_library)
        self._embed_thumbnails.setChecked(settings.embed_thumbnails)
        self._embed_metadata.setChecked(settings.embed_metadata)
        self._filename_template.setText(settings.filename_template)

        self._concurrency.setValue(settings.concurrent_downloads)
        self._max_speed.setValue(settings.max_speed_kbps)
        self._retries.setValue(settings.retry_count)
        self._timeout.setValue(settings.socket_timeout)

        self._select(self._theme_box, settings.theme)
        self._use_system_accent.setChecked(settings.use_system_accent)
        self._reduce_motion.setChecked(settings.reduce_motion)
        self._accent_swatch.refresh()
        self._thumb_size.setValue(settings.grid_thumbnail_size)

        # Read the real OS state rather than trusting the stored flag: the user
        # may have removed the entry from Task Manager, System Settings or a
        # login-items pane since Mediary last ran.
        from app.services.autostart_service import AutostartService

        registered = AutostartService.is_enabled()
        if registered != settings.launch_at_startup:
            settings.launch_at_startup = registered
        self._launch_at_startup.setChecked(registered)
        self._start_hidden.setChecked(settings.start_hidden)
        self._close_to_tray.setChecked(settings.close_to_tray)
        self._tray_notifications.setChecked(settings.tray_notifications)

        self._loading = False
        self._sync_bitrate_enabled()
        self._update_template_preview()
        self._refresh_ffmpeg_status()
        self._refresh_stats()

    def _save(self, key: str, value) -> None:
        if self._loading:
            return
        try:
            self._store.set(key, value)
        except KeyError:
            log.warning("Attempted to save unknown setting %r", key)
            return
        self.settings_changed.emit([key])

    @staticmethod
    def _select(box: QComboBox, value) -> None:
        index = box.findData(value)
        if index >= 0:
            box.setCurrentIndex(index)

    def _on_kind_changed(self) -> None:
        kind = self._default_kind.currentData() or KIND_VIDEO
        self._rebuild_categories(kind, self._default_category.currentData())

    def _rebuild_categories(self, kind: str, current: str) -> None:
        was_loading = self._loading
        self._loading = True
        self._default_category.clear()
        names = categories_for_kind(kind, self._store.settings.custom_categories)
        for name in names:
            self._default_category.addItem(name, name)
        index = self._default_category.findData(current)
        self._default_category.setCurrentIndex(index if index >= 0 else 0)
        self._loading = was_loading
        if not was_loading:
            self._save("default_category", self._default_category.currentData())

    def _sync_bitrate_enabled(self) -> None:
        fmt = self._default_audio_format.currentData() or "mp3"
        lossless = fmt in ("wav", "flac")
        self._default_audio_bitrate.setEnabled(not lossless)
        self._default_audio_bitrate.setToolTip(
            f"{fmt.upper()} is lossless - bitrate comes from the source" if lossless else ""
        )

    def _update_template_preview(self) -> None:
        from app.utils.filenames import render_template

        preview = render_template(
            self._filename_template.text() or "{title}",
            {
                "title": "Epic Cinematic Whoosh",
                "creator": "Example Creator",
                "platform": "YouTube",
                "category": "Sound Effects",
                "quality": "320 kbps",
                "ext": "mp3",
                "date": "2025-01-04",
                "id": "dQw4w9WgXcQ",
            },
        )
        self._template_preview.setText(f"Preview:  {preview}.mp3")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _choose_root(self) -> None:
        current = self._store.settings.library_root
        path = QFileDialog.getExistingDirectory(
            self, "Choose your Mediary library folder", current or str(Path.home())
        )
        if not path:
            return
        self._store.set("library_root", path)
        self._library_root.setText(path)

        from app.services.organization_service import OrganizationService

        organizer = OrganizationService(self._store.settings)
        writable, error = organizer.ensure_writable()
        if not writable:
            QMessageBox.warning(
                self,
                "Folder is not writable",
                f"Mediary cannot write to that folder.\n\n{error}",
            )
            return
        organizer.ensure_library_tree()
        self.settings_changed.emit(["library_root"])

    def _open_root(self) -> None:
        self._open_folder(Path(self._store.settings.library_root))

    def _open_folder(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _detect_ffmpeg(self) -> None:
        get_ffmpeg("", refresh=True)
        self._store.set("ffmpeg_path", "")
        self._refresh_ffmpeg_status()
        self.settings_changed.emit(["ffmpeg_path"])

    def _choose_ffmpeg(self) -> None:
        pattern = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Locate the FFmpeg executable",
            str(Path.home()),
            f"FFmpeg ({pattern});;All files (*)",
        )
        if not path:
            return
        info = get_ffmpeg(path, refresh=True)
        if not info.available:
            QMessageBox.warning(
                self,
                "Not a working FFmpeg",
                "Mediary could not run that file as FFmpeg. Pick the ffmpeg executable itself.",
            )
            get_ffmpeg(self._store.settings.ffmpeg_path, refresh=True)
            return
        self._store.set("ffmpeg_path", path)
        self._refresh_ffmpeg_status()
        self.settings_changed.emit(["ffmpeg_path"])

    def _refresh_ffmpeg_status(self) -> None:
        info = get_ffmpeg(self._store.settings.ffmpeg_path)
        if info.available:
            self._ffmpeg_badge.setText(info.version or "Installed")
            self._ffmpeg_badge.set_tone("success")
            self._ffmpeg_path_label.setText(info.path)
        else:
            self._ffmpeg_badge.setText("Not found")
            self._ffmpeg_badge.set_tone("danger")
            self._ffmpeg_path_label.setText(
                "Install FFmpeg, or choose the executable manually."
            )

    def _open_filing_rules(self) -> None:
        """Show every rule Mediary follows, and let the user change them."""
        if self._filing is None:
            return
        from app.ui.dialogs.filing_rules_dialog import open_filing_rules

        open_filing_rules(self._filing, self._library, self._store.settings, self)

    def _check_ytdlp(self) -> None:
        """Report the installed version and how to upgrade. Never auto-updates."""
        current = ytdlp_version()
        box = QMessageBox(self)
        box.setWindowTitle("yt-dlp")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"yt-dlp {current} is installed.")
        box.setInformativeText(
            "Extractors break when sites change, so keeping yt-dlp current is the single "
            "best fix for a download that suddenly stops working.\n\n"
            "Mediary will not update it behind your back. Update it yourself with:\n\n"
            f"    {Path(sys.executable).name} -m pip install --upgrade yt-dlp\n\n"
            "then restart Mediary."
        )
        box.addButton("Copy command", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        clicked = box.clickedButton()
        if clicked is not None and clicked.text() == "Copy command":
            from PySide6.QtGui import QGuiApplication

            QGuiApplication.clipboard().setText(
                f"{sys.executable} -m pip install --upgrade yt-dlp"
            )

    def _rebuild_index(self) -> None:
        count = self._library.rebuild_index()
        QMessageBox.information(
            self,
            "Search index rebuilt",
            f"Re-indexed {count} item{'s' if count != 1 else ''}.",
        )

    def _refresh_stats(self) -> None:
        try:
            summary = self._library.summary()
            stats = self._library.db.stats()
        except Exception:  # noqa: BLE001
            self._stats_label.setText("Library statistics are unavailable.")
            return
        parts = [
            f"{summary['items']} item{'s' if summary['items'] != 1 else ''}",
            format_bytes(summary["bytes"]) + " of media",
            f"{len(self._library.all_tags())} tags",
        ]
        if summary["missing"]:
            parts.append(f"{summary['missing']} missing")
        parts.append(f"database {format_bytes(stats['size_bytes'])}")
        self._stats_label.setText("   ·   ".join(parts))


_ = (QSize, get_theme, Size, subprocess, KIND_AUDIO)  # keep imports meaningful to linters
