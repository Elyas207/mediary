"""Mediary application entry point."""

from __future__ import annotations

import logging
import os
import signal
import sys
import traceback
from pathlib import Path

# Allow `python app/main.py` from a source checkout as well as `python -m app.main`.
if __package__ in (None, ""):  # pragma: no cover - direct-script convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.config.settings import get_settings_store  # noqa: E402
from app.database.database import get_database  # noqa: E402
from app.media.ffmpeg import get_ffmpeg  # noqa: E402
from app.services.library_service import LibraryService  # noqa: E402
from app.services.organization_service import OrganizationService  # noqa: E402
from app.ui.theme import Theme, set_theme  # noqa: E402
from app.ui.theme.icons import icon_pixmap  # noqa: E402
from app.ui.theme.motion import set_reduce_motion  # noqa: E402
from app.utils.logging import configure_logging, get_logger  # noqa: E402
from app.utils.paths import ensure_app_dirs  # noqa: E402
from app.utils.single_instance import SingleInstanceGuard  # noqa: E402

APP_NAME = "Mediary"
ORG_NAME = "Mediary"
APP_VERSION = "1.0.0"

log = get_logger("main")


def _install_excepthook(app: QApplication) -> None:
    """Log unhandled exceptions and show a readable dialog instead of dying."""
    def handle(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("Unhandled exception:\n%s", detail)
        try:
            from app.ui.dialogs.error_dialog import ErrorDialog

            ErrorDialog(
                title="Mediary hit an unexpected problem",
                message=(
                    "Something went wrong that Mediary did not anticipate. "
                    "Your library and files are unaffected."
                ),
                detail=detail,
                parent=app.activeWindow(),
            ).exec()
        except Exception:  # noqa: BLE001 - the dialog itself may be unavailable
            QMessageBox.critical(None, "Mediary", str(exc_value))

    sys.excepthook = handle


def _application_icon() -> QIcon:
    """The window/taskbar icon, rendered from the Mediary mark."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QPainter, QPolygonF

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5B7CFA"))
        painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.26, size * 0.26)

        cx, cy, unit = size * 0.54, size * 0.5, size / 22
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx - 3.2 * unit, cy - 4.4 * unit),
                    QPointF(cx + 4.4 * unit, cy),
                    QPointF(cx - 3.2 * unit, cy + 4.4 * unit),
                ]
            )
        )
        painter.end()
        icon.addPixmap(pixmap)
    _ = icon_pixmap  # the mark is drawn directly; icons module stays for the UI
    return icon


def parse_arguments(argv: list):
    """Parse Mediary's own flags, leaving Qt's arguments alone."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="mediary",
        description="Mediary - a personal media downloader and library.",
        add_help=True,
    )
    parser.add_argument(
        "--hidden",
        "--background",
        dest="hidden",
        action="store_true",
        help="start in the system tray with no window (used by the sign-in entry)",
    )
    parser.add_argument(
        "--version", action="version", version=f"{APP_NAME} {APP_VERSION}"
    )
    # Unrecognised arguments belong to Qt (-style, -platform, ...), so they are
    # returned rather than rejected.
    return parser.parse_known_args(argv[1:])


def main(argv: list | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    options, qt_arguments = parse_arguments(argv)
    argv = [argv[0], *qt_arguments]

    # High-DPI is on by default in Qt 6; this only affects fractional scaling.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    ensure_app_dirs()
    configure_logging(
        level=logging.DEBUG if os.environ.get("MEDIARY_DEBUG") else logging.INFO
    )
    log.info("Starting %s %s (Python %s)", APP_NAME, APP_VERSION, sys.version.split()[0])

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(_application_icon())
    app.setStyle("Fusion")   # a consistent base for the stylesheet on every OS

    _install_excepthook(app)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Mediary can live in the tray with no window, so a second launch must hand
    # off to the running copy rather than starting a rival queue.
    guard = SingleInstanceGuard(app)
    if not guard.try_acquire():
        return 0

    store = get_settings_store()
    settings = store.settings

    set_reduce_motion(settings.reduce_motion)
    theme = Theme(app, settings.theme, use_system_accent=settings.use_system_accent)
    theme.apply()
    set_theme(theme)

    try:
        database = get_database()
    except Exception as exc:  # noqa: BLE001 - without a database there is no app
        log.exception("Could not open the library database")
        QMessageBox.critical(
            None,
            "Mediary could not start",
            "Mediary could not open its library database.\n\n"
            f"{exc}\n\nCheck that the data folder is writable.",
        )
        return 1

    library = LibraryService(database)

    # Warm the FFmpeg lookup once so no screen pays for the subprocess later.
    get_ffmpeg(settings.ffmpeg_path)

    if not settings.first_run_complete:
        from app.ui.views.onboarding import OnboardingDialog

        wizard = OnboardingDialog(store)
        if wizard.exec() != OnboardingDialog.DialogCode.Accepted:
            log.info("First-run setup was cancelled; exiting")
            return 0
        settings = store.settings
    else:
        # Recreate any library folder the user deleted between sessions.
        try:
            OrganizationService(settings).ensure_library_tree()
        except Exception:  # noqa: BLE001 - a missing folder is not fatal
            log.warning("Could not verify the library folder tree", exc_info=True)

    from app.ui.main_window import MainWindow

    window = MainWindow(store, theme, library)

    # A hidden start is only honoured when there is a tray icon to get back
    # from, and never on the very first launch.
    start_hidden = (
        (options.hidden or settings.start_hidden)
        and settings.first_run_complete
        and window.has_tray
    )
    if start_hidden:
        log.info("Starting in the background; the window is available from the tray")
    else:
        window.show()

    guard.wake_requested.connect(window.show_from_tray)

    exit_code = app.exec()

    from app.services import thumbnail_service

    guard.release()
    thumbnail_service.shutdown()
    database.close()
    log.info("Mediary exited with code %s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
