"""The Mediary main window: navigation, view stack and cross-view plumbing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QTextEdit,
    QWidget,
)

from app.config.settings import SettingsStore
from app.downloader.manager import DownloadManager
from app.media.ffmpeg import get_ffmpeg
from app.models.download import DownloadTask
from app.services.download_service import DownloadService
from app.services.filing_service import FilingService
from app.services.library_service import LibraryService
from app.services.organization_service import OrganizationService
from app.ui.dialogs.duplicate_dialog import DuplicateDialog
from app.ui.dialogs.error_dialog import ErrorDialog
from app.ui.sidebar import NAV_FILTERS, Sidebar
from app.ui.theme import Theme
from app.ui.theme.motion import Duration, fade_in, set_reduce_motion
from app.ui.tray import MediaryTray, tray_available
from app.ui.views.download_view import DownloadView
from app.ui.views.library_view import LibraryView
from app.ui.views.queue_view import QueueView
from app.ui.views.settings_view import SettingsView
from app.ui.views.tags_view import TagsView
from app.ui.widgets.common import Notice, hbox, vbox
from app.ui.widgets.toast import ToastHost
from app.utils.logging import get_logger

log = get_logger("ui")


class MainWindow(QMainWindow):
    """Owns the services and wires every screen together."""

    closing = Signal()

    def __init__(
        self,
        store: SettingsStore,
        theme: Theme,
        library: LibraryService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = store.settings
        self._theme = theme
        self._library = library

        self.setWindowTitle("Mediary")
        self.setMinimumSize(QSize(1020, 660))

        self._organizer = OrganizationService(self._settings)
        self._filing = FilingService(self._library, self._settings)
        self._manager = DownloadManager(self._settings, self)
        self._downloads = DownloadService(
            self._settings, self._manager, self._library, self._organizer, self
        )

        self._build_ui()
        self._connect()
        self._install_shortcuts()
        self._restore_window_state()

        self._toasts = ToastHost(self)
        self._tray: MediaryTray | None = None
        self._quitting = False
        self._tray_hint_shown = False
        self._setup_tray()

        self._refresh_counts()
        self._check_environment()

        self.navigate(self._settings.last_view or "download")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("ContentArea")
        layout = hbox(central, spacing=0)

        self.sidebar = Sidebar(central)
        layout.addWidget(self.sidebar)

        right = QWidget(central)
        right.setObjectName("ContentArea")
        right_layout = vbox(right, spacing=0)

        self.stack = QStackedWidget(right)
        right_layout.addWidget(self.stack, 1)
        layout.addWidget(right, 1)

        self.download_view = DownloadView(
            self._settings, self._manager, self._filing, self.stack
        )
        self.queue_view = QueueView(self._manager, self.stack)
        self.library_view = LibraryView(self._settings, self._library, self._theme, self.stack)
        self.tags_view = TagsView(self._library, self.stack)
        self.settings_view = SettingsView(
            self._store, self._theme, self._library, self._filing, self.stack
        )

        for widget in (
            self.download_view,
            self.queue_view,
            self.library_view,
            self.tags_view,
            self.settings_view,
        ):
            self.stack.addWidget(widget)

        self.setCentralWidget(central)

    def _connect(self) -> None:
        self.sidebar.navigate.connect(self.navigate)
        self.download_view.category_created.connect(self._on_category_created)
        self.download_view.rules_changed.connect(self._filing.invalidate)

        self.download_view.download_requested.connect(self._on_download_requested)
        self.download_view.show_queue_requested.connect(lambda: self.navigate("queue"))

        self.queue_view.open_file_requested.connect(self.open_path)
        self.queue_view.open_folder_requested.connect(self.reveal_path)
        self.queue_view.show_error_requested.connect(self.show_task_error)
        self.queue_view.reveal_in_library_requested.connect(self._reveal_media)
        self.queue_view.start_download_requested.connect(lambda: self.navigate("download"))

        self.library_view.open_path_requested.connect(self.open_path)
        self.library_view.reveal_path_requested.connect(self.reveal_path)
        self.library_view.library_changed.connect(self._refresh_counts)
        self.library_view.download_requested.connect(lambda: self.navigate("download"))

        self.tags_view.tags_changed.connect(self._on_tags_changed)
        self.tags_view.tag_selected.connect(self._on_tag_selected)

        self.settings_view.settings_changed.connect(self._on_settings_changed)
        self.settings_view.rescan_requested.connect(self._rescan_library)
        self.settings_view.uninstall_requested.connect(self._open_uninstall)

        self._downloads.item_added.connect(self._on_item_added)
        self._downloads.library_changed.connect(self._refresh_counts)
        # New items change what the title model has learned.
        self._downloads.library_changed.connect(self._filing.invalidate)
        self._downloads.notice.connect(self._on_service_notice)

        self._manager.queue_changed.connect(self._on_queue_changed)
        self._manager.queue_changed.connect(self._on_tray_queue_changed)
        self._manager.task_failed.connect(self._on_task_failed)

    def _install_shortcuts(self) -> None:
        def bind(sequence: str, handler) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(handler)

        bind(QKeySequence.StandardKey.Find, self._focus_search)
        bind(QKeySequence.StandardKey.Preferences, lambda: self.navigate("settings"))
        bind("Ctrl+,", lambda: self.navigate("settings"))
        bind("Ctrl+N", lambda: self.navigate("download"))
        bind("Ctrl+L", lambda: self.navigate("all"))
        bind("Ctrl+J", lambda: self.navigate("queue"))
        bind("Ctrl+R", self._rescan_library)
        bind("F5", self._refresh_current)
        bind("Space", self._preview_selected)
        bind("Esc", self._close_preview)

    # ------------------------------------------------------------------
    # System tray / background running
    # ------------------------------------------------------------------

    def _setup_tray(self) -> None:
        """Create the tray icon when a background setting needs one."""
        if not tray_available():
            if self._settings.wants_tray:
                # Nothing here can hide the window if there is no way back.
                log.warning("No system tray on this desktop; background mode disabled")
                self._store.update({"start_hidden": False, "close_to_tray": False})
            return

        self._tray = MediaryTray(QApplication.windowIcon(), self)
        self._tray.show_requested.connect(self.show_from_tray)
        self._tray.download_requested.connect(lambda: self.show_from_tray("download"))
        self._tray.queue_requested.connect(lambda: self.show_from_tray("queue"))
        self._tray.library_requested.connect(lambda: self.show_from_tray("all"))
        self._tray.quit_requested.connect(self.quit_application)
        self._sync_tray_visibility()

    def _sync_tray_visibility(self) -> None:
        if self._tray is None:
            return
        visible = self._settings.wants_tray
        self._tray.set_visible(visible)
        # Qt exits when the last window closes. That has to be off while the
        # tray is the only thing keeping Mediary alive.
        QApplication.setQuitOnLastWindowClosed(not visible)

    @property
    def has_tray(self) -> bool:
        return self._tray is not None and self._tray.is_visible()

    def show_from_tray(self, view: str = "") -> None:
        """Bring the window back from the tray and focus it."""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
        if view:
            self.navigate(view)

    def hide_to_tray(self) -> None:
        """Hide the window. It leaves the taskbar; the tray icon remains."""
        if not self.has_tray:
            return
        self.hide()
        if not self._tray_hint_shown and self._settings.tray_notifications:
            self._tray_hint_shown = True
            self._tray.notify(
                "Mediary is still running",
                "Downloads carry on in the background. "
                "Click the tray icon to bring the window back.",
            )

    def quit_application(self) -> None:
        """Quit for real, regardless of the close-to-tray setting."""
        self._quitting = True
        self.close()
        QApplication.quit()

    def _on_tray_queue_changed(self) -> None:
        if self._tray is None:
            return
        counts = self._manager.counts()
        self._tray.set_active_downloads(counts["active"] + counts["pending"])

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate(self, key: str) -> None:
        """Switch screens. Library keys also apply their filter."""
        self.sidebar.set_active(key)

        if key == "download":
            self._show_view(self.download_view)
            self.download_view.refresh_clipboard_hint()
        elif key == "queue":
            self._show_view(self.queue_view)
        elif key == "settings":
            self.settings_view.reload()
            self._show_view(self.settings_view)
        elif key == "tags":
            self.tags_view.reload()
            self._show_view(self.tags_view)
        elif key in NAV_FILTERS:
            self.library_view.apply_nav_filter(key, NAV_FILTERS[key])
            self._show_view(self.library_view)
        else:
            self._show_view(self.download_view)

        self._store.set("last_view", key)

    def _show_view(self, widget: QWidget) -> None:
        """Switch screens with a short cross-fade.

        Instant swaps make the app feel like it jumped rather than moved; a
        fade is enough to carry the eye without delaying anything, since the
        widget is already fully built before it animates.
        """
        if self.stack.currentWidget() is widget:
            return
        self.stack.setCurrentWidget(widget)
        fade_in(widget, duration=Duration.fast)

    def _focus_search(self) -> None:
        current = self.stack.currentWidget()
        if current is self.library_view:
            self.library_view.focus_search()
        elif current is self.download_view:
            self.download_view.focus_input()
        else:
            self.navigate("all")
            self.library_view.focus_search()

    def _preview_selected(self) -> None:
        """Space auditions the selected item, the way a sound library should."""
        if self.stack.currentWidget() is not self.library_view:
            return
        focused = QApplication.focusWidget()
        # Never steal the space bar from a text field.
        if isinstance(focused, (QLineEdit, QPlainTextEdit, QTextEdit)):
            return
        self.library_view.toggle_preview_selected()

    def _close_preview(self) -> None:
        if self.stack.currentWidget() is self.library_view:
            self.library_view.stop_preview()

    def _refresh_current(self) -> None:
        current = self.stack.currentWidget()
        if current is self.library_view:
            self.library_view.reload()
        elif current is self.tags_view:
            self.tags_view.reload()
        self._refresh_counts()

    # ------------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------------

    def _on_download_requested(self, requests: list) -> None:
        """``requests`` is a list of ``(url, DownloadOptions, MediaInfo)``."""
        queued = 0
        remembered_choice = ""

        for url, options, info in requests:
            duplicate = self._downloads.check_duplicate(url, info)
            replace_path = ""

            if duplicate is not None:
                action = remembered_choice or self._settings.duplicate_action
                if action == "ask":
                    dialog = DuplicateDialog(duplicate, info, self)
                    action = dialog.run()
                    if dialog.apply_to_all:
                        remembered_choice = action
                if action == "skip":
                    continue
                if action == "replace":
                    replace_path = duplicate.item.file_path

            self._downloads.queue(url, options, info, replace_path=replace_path)
            queued += 1

        if queued:
            self.navigate("queue")
            self._toast(
                f"{queued} download{'s' if queued != 1 else ''} started",
                tone="info",
            )
        elif requests:
            self._toast("Everything was already in your library.", tone="info")

    def _on_item_added(self, item) -> None:
        self.library_view.note_item_added(item)
        self._toast(
            f"Added to {item.category}",
            title=item.display_title,
            tone="success",
            action_text="View in library",
            on_action=lambda: self._reveal_media(item.id),
        )
        # An in-window toast is invisible when Mediary is in the tray, so route
        # the same news through the desktop notification system instead.
        self._notify_in_background(item.display_title, f"Added to {item.category}")

    def _on_task_failed(self, task: DownloadTask) -> None:
        self._toast(
            task.error or "Download failed",
            title=task.display_title,
            tone="danger",
            action_text="Details",
            on_action=lambda: self.show_task_error(task),
            duration_ms=7000,
        )
        self._notify_in_background(
            task.display_title, task.error or "Download failed", error=True
        )

    def _notify_in_background(self, title: str, message: str, *, error: bool = False) -> None:
        if self.isVisible() or self._tray is None:
            return
        if not self._settings.tray_notifications:
            return
        self._tray.notify(title, message, error=error)

    def _on_queue_changed(self) -> None:
        counts = self._manager.counts()
        self.sidebar.set_queue_badge(counts["active"] + counts["pending"])
        self.sidebar.set_queue_progress(self._overall_progress())
        active = counts["active"]
        if active:
            self.sidebar.set_status_text(f"{active} downloading")
        elif counts["pending"]:
            self.sidebar.set_status_text(f"{counts['pending']} queued")
        else:
            self.sidebar.set_status_text("")

    def _overall_progress(self) -> float:
        """Combined progress of everything still running, 0 when idle."""
        active = [
            task for task in self._manager.tasks
            if task.status.is_active or task.status.is_pending
        ]
        if not active:
            return 0.0
        return sum(task.progress.percent for task in active) / (len(active) * 100.0)

    def _on_service_notice(self, level: str, message: str) -> None:
        self._toast(message, tone=level)

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    def _on_category_created(self, name: str) -> None:
        """Persist a category the user invented on the Download screen."""
        self._store.save()
        log.info("Added custom category %r", name)

    def _refresh_counts(self) -> None:
        try:
            counts = self._library.kind_counts()
            counts.update(self._library.category_counts())
            counts["tags"] = len(self._library.all_tags())
        except Exception:  # noqa: BLE001 - the sidebar is not worth crashing for
            log.exception("Could not refresh sidebar counts")
            return
        self.sidebar.set_counts(counts)

    def _reveal_media(self, media_id: int) -> None:
        self.navigate("all")
        self.library_view.reveal(media_id)

    def _on_tag_selected(self, tag: str) -> None:
        self.navigate("all")
        self.library_view.filter_by_tag(tag)

    def _on_tags_changed(self) -> None:
        self.library_view.reload()
        self._refresh_counts()

    def _open_uninstall(self) -> None:
        """Let the user clear Mediary's local data."""
        from app.services.uninstall_service import UninstallService
        from app.ui.dialogs.uninstall_dialog import UninstallDialog

        dialog = UninstallDialog(
            UninstallService(self._settings.library_root), self
        )
        dialog.finished_uninstall.connect(self._on_uninstalled)
        dialog.exec()

    def _on_uninstalled(self, result) -> None:
        if result.failed:
            detail = "\n".join(f"{label}: {reason}" for label, reason in result.failed)
            ErrorDialog(
                title="Some items could not be removed",
                message=result.summary(),
                detail=detail,
                parent=self,
            ).exec()
            return

        QMessageBox.information(
            self,
            "Data removed",
            f"{result.summary()}\n\n"
            "Mediary will now close. Anything you kept is untouched.",
        )
        # Settings and the database may be gone; carrying on would recreate
        # them, which is exactly what the user just asked not to happen.
        self.quit_application()

    def _rescan_library(self) -> None:
        from app.services.rescan_service import RescanService

        service = RescanService(self._settings, self._library, self._organizer)
        result = service.run()
        self.library_view.reload()
        self._refresh_counts()
        self._toast(result.summary(), tone="success" if not result.missing else "warning",
                    title="Library rescanned", duration_ms=6000)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _on_settings_changed(self, changed_keys: list) -> None:
        self._settings = self._store.settings
        self._filing.set_settings(self._settings)
        if any(k in changed_keys for k in ("theme", "use_system_accent")):
            self._theme.set_use_system_accent(self._settings.use_system_accent)
            self._theme.apply(self._settings.theme)
            self.sidebar.refresh_theme()
            self.library_view.refresh_theme()
            self.settings_view.reload()
        if "reduce_motion" in changed_keys:
            set_reduce_motion(self._settings.reduce_motion)
        if "concurrent_downloads" in changed_keys:
            self._manager.set_concurrency(self._settings.concurrent_downloads)
        if "ffmpeg_path" in changed_keys:
            get_ffmpeg(self._settings.ffmpeg_path, refresh=True)
            self._check_environment()
        if any(k in changed_keys for k in ("library_root", "filename_template", "default_category")):
            self._organizer = OrganizationService(self._settings)
            self.download_view.refresh_settings()
        if any(k in changed_keys for k in ("start_hidden", "close_to_tray")):
            self._sync_tray_visibility()
        if any(k in changed_keys for k in ("launch_at_startup", "start_hidden")):
            self._sync_autostart()

    def _sync_autostart(self) -> None:
        """Keep the OS sign-in entry in step with the settings."""
        from app.services.autostart_service import AutostartService

        ok, error = AutostartService.sync(
            self._settings.launch_at_startup, self._settings.start_hidden
        )
        if not ok:
            self._toast(
                error or "Mediary could not update the sign-in setting.",
                title="Couldn't change startup behaviour",
                tone="danger",
                duration_ms=7000,
            )
            # Do not leave the checkbox claiming something that is not true.
            self._store.set("launch_at_startup", AutostartService.is_enabled())
            self.settings_view.reload()

    # ------------------------------------------------------------------
    # Environment checks
    # ------------------------------------------------------------------

    def _check_environment(self) -> None:
        ffmpeg = get_ffmpeg(self._settings.ffmpeg_path)
        if ffmpeg.available:
            return
        notice = Notice(
            "Without FFmpeg, Mediary can only download single-stream files: "
            "audio extraction, format conversion and high-resolution merging are unavailable.",
            tone="warning",
            title="FFmpeg isn't configured",
            action_text="Choose FFmpeg",
            parent=self.download_view,
        )
        notice.action_clicked.connect(self._choose_ffmpeg)
        self.download_view.add_persistent_notice(notice)

    def _choose_ffmpeg(self) -> None:
        filter_text = "FFmpeg (ffmpeg.exe)" if sys.platform.startswith("win") else "FFmpeg (ffmpeg)"
        path, _ = QFileDialog.getOpenFileName(
            self, "Locate the FFmpeg executable", str(Path.home()), f"{filter_text};;All files (*)"
        )
        if not path:
            return
        self._store.set("ffmpeg_path", path)
        info = get_ffmpeg(path, refresh=True)
        if info.available:
            self._toast(f"FFmpeg {info.version} configured", tone="success")
            self.settings_view.reload()
        else:
            self._toast("That file is not a working FFmpeg binary.", tone="danger")

    # ------------------------------------------------------------------
    # Shell integration
    # ------------------------------------------------------------------

    def open_path(self, path: str) -> None:
        """Open a file with the user's default application."""
        target = Path(path)
        if not target.exists():
            self._toast("That file is no longer on disk.", tone="warning")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def reveal_path(self, path: str) -> None:
        """Show a file in the platform file manager, selected where supported."""
        target = Path(path)
        folder = target.parent if target.suffix else target
        if not folder.exists():
            self._toast("That folder no longer exists.", tone="warning")
            return
        try:
            if sys.platform.startswith("win") and target.exists():
                subprocess.run(["explorer", "/select,", os.path.normpath(str(target))], check=False)
                return
            if sys.platform == "darwin" and target.exists():
                subprocess.run(["open", "-R", str(target)], check=False)
                return
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def copy_text(self, text: str, message: str = "Copied") -> None:
        QGuiApplication.clipboard().setText(text)
        self._toast(message, tone="info", duration_ms=1800)

    def show_task_error(self, task: DownloadTask) -> None:
        ErrorDialog(
            title="Download failed",
            message=task.error or "The download failed.",
            detail=(
                f"URL: {task.url}\n"
                f"Format: {task.options.quality_label()}\n"
                f"Category: {task.options.category}\n\n"
                f"{task.error_detail or 'No further detail was reported.'}"
            ),
            parent=self,
        ).exec()

    def _toast(self, message: str, **kwargs) -> None:
        if hasattr(self, "_toasts"):
            self._toasts.show_toast(message, **kwargs)

    # ------------------------------------------------------------------
    # Window state
    # ------------------------------------------------------------------

    def _restore_window_state(self) -> None:
        geometry = self._settings.window_geometry
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
                return
            except Exception:  # noqa: BLE001 - corrupt state must not block launch
                log.debug("Could not restore window geometry")
        self.resize(QSize(1280, 820))
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Closing the window is not the same as quitting when Mediary is set to
        # keep running: hide instead, and leave downloads going.
        if not self._quitting and self._settings.close_to_tray and self.has_tray:
            self._save_window_state()
            self.hide_to_tray()
            event.ignore()
            return

        counts = self._manager.counts()
        pending = counts["active"] + counts["pending"]
        if pending:
            answer = QMessageBox.question(
                self,
                "Downloads in progress",
                f"{pending} download{'s are' if pending != 1 else ' is'} still running.\n\n"
                "Closing Mediary will cancel them.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Close,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Close:
                event.ignore()
                return

        self._save_window_state()
        self.closing.emit()
        if self._tray is not None:
            self._tray.set_visible(False)
        self._manager.shutdown()
        super().closeEvent(event)

    def _save_window_state(self) -> None:
        try:
            self._store.update(
                {
                    "window_geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
                    "library_view": self.library_view.current_view_mode(),
                }
            )
        except Exception:  # noqa: BLE001
            log.debug("Could not persist window state")
