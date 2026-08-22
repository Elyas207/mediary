"""The system-tray presence.

When Mediary runs in the background - started at sign-in, or with its window
closed - the tray icon is the only way back to it. Nothing in the app is allowed
to hide the window unless this is available and visible.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from app.utils.logging import get_logger

log = get_logger("tray")


def tray_available() -> bool:
    """Whether this desktop actually offers a system tray.

    Several Linux desktops ship without one, and on those "start hidden" would
    strand the user with an unreachable process.
    """
    try:
        return bool(QSystemTrayIcon.isSystemTrayAvailable())
    except Exception:  # noqa: BLE001 - headless or unusual platform plugin
        return False


class MediaryTray(QObject):
    """Tray icon, its menu, and the notifications Mediary sends through it."""

    show_requested = Signal()
    download_requested = Signal()
    queue_requested = Signal()
    library_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_icon = icon
        self._badge_count = 0
        self._supported = tray_available()

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Mediary")
        self._tray.activated.connect(self._on_activated)

        self._menu = QMenu()
        self._build_menu()
        self._tray.setContextMenu(self._menu)

    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        self._show_action = QAction("Show Mediary", self._menu)
        self._show_action.triggered.connect(self.show_requested.emit)
        # Bold, so double-clicking the icon and picking the menu default agree.
        font = self._show_action.font()
        font.setBold(True)
        self._show_action.setFont(font)
        self._menu.addAction(self._show_action)
        self._menu.setDefaultAction(self._show_action)

        self._menu.addSeparator()

        download = QAction("Download media…", self._menu)
        download.triggered.connect(self.download_requested.emit)
        self._menu.addAction(download)

        self._queue_action = QAction("Queue", self._menu)
        self._queue_action.triggered.connect(self.queue_requested.emit)
        self._menu.addAction(self._queue_action)

        library = QAction("Library", self._menu)
        library.triggered.connect(self.library_requested.emit)
        self._menu.addAction(library)

        self._menu.addSeparator()

        quit_action = QAction("Quit Mediary", self._menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(quit_action)

    def _on_activated(self, reason) -> None:
        # Trigger is a single left click (Windows/Linux convention); macOS opens
        # the menu instead, which Qt handles for us.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    # ------------------------------------------------------------------

    @property
    def supported(self) -> bool:
        return self._supported

    def is_visible(self) -> bool:
        return self._supported and self._tray.isVisible()

    def set_visible(self, visible: bool) -> None:
        if not self._supported:
            return
        if visible:
            self._tray.show()
        else:
            self._tray.hide()

    def set_icon(self, icon: QIcon) -> None:
        self._base_icon = icon
        self._apply_icon()

    def set_active_downloads(self, count: int) -> None:
        """Badge the icon and the menu with the number of live downloads."""
        count = max(0, int(count))
        if count == self._badge_count:
            return
        self._badge_count = count
        self._queue_action.setText(f"Queue ({count})" if count else "Queue")
        self._tray.setToolTip(
            f"Mediary — {count} download{'s' if count != 1 else ''} in progress"
            if count
            else "Mediary"
        )
        self._apply_icon()

    def _apply_icon(self) -> None:
        if not self._supported:
            return
        if not self._badge_count:
            self._tray.setIcon(self._base_icon)
            return
        self._tray.setIcon(QIcon(self._badged_pixmap()))

    def _badged_pixmap(self) -> QPixmap:
        """The app mark with a small accent dot, indicating work in progress."""
        from app.ui.theme import get_theme

        size = 32
        pixmap = self._base_icon.pixmap(size, size)
        if pixmap.isNull():
            return pixmap

        theme = get_theme()
        colour = theme.palette.accent if theme is not None else "#5B7CFA"

        badged = QPixmap(pixmap.size())
        badged.setDevicePixelRatio(pixmap.devicePixelRatio())
        badged.fill(Qt.GlobalColor.transparent)

        from PySide6.QtGui import QColor

        painter = QPainter(badged)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, pixmap)

        radius = max(4, pixmap.width() // 5)
        margin = 1
        painter.setPen(Qt.PenStyle.NoPen)
        # A ring in the surrounding colour keeps the dot legible against both a
        # light and a dark tray background.
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(
            pixmap.width() - radius * 2 - margin,
            pixmap.height() - radius * 2 - margin,
            radius * 2,
            radius * 2,
        )
        painter.setBrush(QColor(colour))
        painter.drawEllipse(
            pixmap.width() - radius * 2 - margin + 1,
            pixmap.height() - radius * 2 - margin + 1,
            radius * 2 - 2,
            radius * 2 - 2,
        )
        painter.end()
        return badged

    # ------------------------------------------------------------------

    def notify(self, title: str, message: str, *, error: bool = False) -> None:
        """Send a desktop notification, if the platform shows them."""
        if not self.is_visible():
            return
        try:
            if not QSystemTrayIcon.supportsMessages():
                return
            self._tray.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Critical
                if error
                else QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
        except Exception:  # noqa: BLE001 - notifications are never critical
            log.debug("Could not show a tray notification")
