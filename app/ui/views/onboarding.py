"""First-run setup.

Three short steps with a persistent left rail, so it reads as a welcome rather
than a developer install wizard. Everything it asks can be changed later in
Settings, and the defaults are good enough to skip straight through.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLineEdit,
    QStackedWidget,
    QWidget,
)

from app.config.settings import SettingsStore
from app.downloader.ytdlp_adapter import ytdlp_version
from app.media.ffmpeg import get_ffmpeg
from app.models.category import BUILTIN_CATEGORIES
from app.services.organization_service import OrganizationService
from app.ui.sidebar import MediaryMark
from app.ui.theme import Space, get_theme
from app.ui.widgets.common import (
    Badge,
    ElidedLabel,
    button,
    divider,
    hbox,
    label,
    panel,
    set_property,
    vbox,
)
from app.utils.logging import get_logger
from app.utils.paths import default_library_root

log = get_logger("onboarding")

STEPS = ("Welcome", "Library folder", "Tools")


class OnboardingDialog(QDialog):
    """Runs once, before the main window appears."""

    def __init__(self, store: SettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._step = 0
        self._chosen_root = store.settings.library_root or str(default_library_root())

        self.setWindowTitle("Welcome to Mediary")
        self.setModal(True)
        self.setFixedSize(QSize(720, 460))

        layout = hbox(self, spacing=0)
        layout.addWidget(self._build_side())

        right = QWidget(self)
        right.setObjectName("OnboardingPane")
        right_layout = vbox(right, spacing=0)

        self._stack = QStackedWidget(right)
        self._stack.addWidget(self._page_welcome())
        self._stack.addWidget(self._page_folder())
        self._stack.addWidget(self._page_tools())
        right_layout.addWidget(self._stack, 1)

        right_layout.addWidget(divider())
        right_layout.addWidget(self._build_footer())
        layout.addWidget(right, 1)

        self._sync()

    # ------------------------------------------------------------------

    def _build_side(self) -> QWidget:
        side = QWidget(self)
        side.setObjectName("OnboardingSide")
        side.setFixedWidth(228)
        layout = vbox(side, spacing=0, margins=(Space.xl, Space.xl, Space.xl, Space.xl))

        brand = QWidget(side)
        brand_layout = hbox(brand, spacing=Space.sm)
        brand_layout.addWidget(MediaryMark(brand))
        wordmark = label("Mediary", "heading")
        brand_layout.addWidget(wordmark)
        brand_layout.addStretch(1)
        layout.addWidget(brand)

        layout.addSpacing(Space.sm)
        layout.addWidget(label("Your media, organised.", "muted"))
        layout.addSpacing(Space.x3l)

        self._step_labels: list = []
        for name in STEPS:
            row = QWidget(side)
            row_layout = hbox(row, spacing=Space.md)
            dot = QWidget(row)
            dot.setObjectName("StepDot")
            dot.setFixedSize(QSize(6, 6))
            row_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            text = label(name, "meta")
            row_layout.addWidget(text, 1)
            layout.addWidget(row)
            layout.addSpacing(Space.md)
            self._step_labels.append((dot, text))

        layout.addStretch(1)
        return side

    def _build_footer(self) -> QWidget:
        footer = QWidget(self)
        layout = hbox(footer, spacing=Space.sm, margins=(Space.xl, Space.md, Space.xl, Space.md))

        self._back_btn = button("Back", variant="ghost", on_click=self._back)
        layout.addWidget(self._back_btn)
        layout.addStretch(1)

        self._next_btn = button("Continue", variant="primary", on_click=self._next)
        self._next_btn.setDefault(True)
        layout.addWidget(self._next_btn)
        return footer

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def _page(self, title: str, subtitle: str) -> tuple:
        page = QWidget(self)
        layout = vbox(page, spacing=0, margins=(Space.x3l, Space.x3l, Space.x3l, Space.xl))
        layout.addWidget(label(title, "heroTitle", wrap=True))
        layout.addSpacing(Space.sm)
        layout.addWidget(label(subtitle, "pageSubtitle", wrap=True))
        layout.addSpacing(Space.xl)
        return page, layout

    def _page_welcome(self) -> QWidget:
        page, layout = self._page(
            "Find it. Fetch it. Organise it.",
            "Mediary turns publicly accessible media into a searchable personal library "
            "of clips, music, sound effects and references.",
        )

        for icon, title, body in (
            ("download", "Paste and go",
             "Analyse a URL, pick a format, and Mediary handles the rest."),
            ("layers", "Organised automatically",
             "Every download lands in the right folder and is indexed for search."),
            ("shield", "Yours alone",
             "No account, no backend, no analytics. Everything stays on this machine."),
        ):
            layout.addWidget(self._feature_row(icon, title, body))
            layout.addSpacing(Space.md)

        layout.addStretch(1)
        note = label(
            "Publicly accessible does not mean royalty-free. Mediary records licensing "
            "information you provide — it never decides for you what you may reuse.",
            "muted",
            wrap=True,
        )
        layout.addWidget(note)
        return page

    def _feature_row(self, icon: str, title: str, body: str) -> QWidget:
        row = QWidget(self)
        layout = hbox(row, spacing=Space.md)
        theme = get_theme()
        if theme is not None:
            from PySide6.QtWidgets import QLabel

            glyph = QLabel(row)
            glyph.setPixmap(theme.pixmap(icon, 16, "accent"))
            glyph.setFixedSize(16, 16)
            layout.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        column = vbox(spacing=2)
        column.addWidget(label(title, "itemTitle"))
        column.addWidget(label(body, "muted", wrap=True))
        layout.addLayout(column, 1)
        return row

    def _page_folder(self) -> QWidget:
        page, layout = self._page(
            "Where should your library live?",
            "Mediary keeps its folders here. You can move it later in Settings.",
        )

        row = QWidget(page)
        row_layout = hbox(row, spacing=Space.sm)
        self._root_input = QLineEdit(self._chosen_root, row)
        row_layout.addWidget(self._root_input, 1)
        row_layout.addWidget(button("Browse…", variant="subtle", on_click=self._browse))
        layout.addWidget(row)

        layout.addSpacing(Space.lg)
        layout.addWidget(label("MEDIARY WILL CREATE", "fieldLabel"))
        layout.addSpacing(Space.sm)

        tree = panel(inset=True, parent=page)
        tree_layout = vbox(tree, spacing=2, margins=(Space.md, Space.md, Space.md, Space.md))
        for folder in sorted({c.folder for c in BUILTIN_CATEGORIES}):
            tree_layout.addWidget(ElidedLabel(folder, "mono", parent=tree))
        layout.addWidget(tree)

        self._folder_error = label("", "danger")
        self._folder_error.setProperty("role", "meta")
        self._folder_error.hide()
        layout.addSpacing(Space.sm)
        layout.addWidget(self._folder_error)

        layout.addStretch(1)
        return page

    def _page_tools(self) -> QWidget:
        page, layout = self._page(
            "You're set up",
            "Mediary uses two well-known open-source tools to do the actual work.",
        )

        ytdlp_row = self._tool_row(
            "yt-dlp",
            "Reads what is available at a URL and fetches it.",
            ytdlp_version(),
            "success",
        )
        layout.addWidget(ytdlp_row)
        layout.addSpacing(Space.md)

        ffmpeg = get_ffmpeg(self._store.settings.ffmpeg_path)
        self._ffmpeg_row = self._tool_row(
            "FFmpeg",
            "Merges streams, converts audio and embeds artwork."
            if ffmpeg.available
            else "Not found. Without it, Mediary can only save single-stream files.",
            ffmpeg.version if ffmpeg.available else "Not found",
            "success" if ffmpeg.available else "warning",
        )
        layout.addWidget(self._ffmpeg_row)

        if not ffmpeg.available:
            layout.addSpacing(Space.sm)
            actions = QWidget(page)
            actions_layout = hbox(actions, spacing=Space.sm)
            actions_layout.addWidget(
                button("Choose FFmpeg…", variant="subtle", on_click=self._choose_ffmpeg)
            )
            actions_layout.addWidget(
                button("How to install", variant="link", on_click=self._ffmpeg_help)
            )
            actions_layout.addStretch(1)
            layout.addWidget(actions)

        layout.addStretch(1)
        layout.addWidget(
            label(
                "Everything here is adjustable in Settings whenever you like.",
                "muted",
                wrap=True,
            )
        )
        return page

    def _tool_row(self, name: str, body: str, version: str, tone: str) -> QWidget:
        card = panel(parent=self)
        layout = hbox(card, spacing=Space.md, margins=(Space.lg, Space.md, Space.lg, Space.md))
        column = vbox(spacing=2)
        column.addWidget(label(name, "itemTitle"))
        column.addWidget(label(body, "muted", wrap=True))
        layout.addLayout(column, 1)
        layout.addWidget(Badge(version, tone, card), 0, Qt.AlignmentFlag.AlignTop)
        return card

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _sync(self) -> None:
        self._stack.setCurrentIndex(self._step)
        self._back_btn.setVisible(self._step > 0)
        self._next_btn.setText("Start using Mediary" if self._step == len(STEPS) - 1 else "Continue")
        for index, (dot, text) in enumerate(self._step_labels):
            active = index <= self._step
            set_property(dot, "active", "true" if active else "false")
            theme = get_theme()
            if theme is not None:
                colour = theme.palette.text if index == self._step else theme.palette.text_muted
                weight = 600 if index == self._step else 400
                text.setStyleSheet(f"color: {colour}; font-weight: {weight}; font-size: 12px;")

    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._sync()

    def _next(self) -> None:
        if self._step == 1 and not self._commit_folder():
            return
        if self._step < len(STEPS) - 1:
            self._step += 1
            self._sync()
            return
        self._finish()

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose your Mediary library folder", self._root_input.text() or str(Path.home())
        )
        if path:
            self._root_input.setText(str(Path(path) / "Mediary"))

    def _commit_folder(self) -> bool:
        raw = self._root_input.text().strip()
        if not raw:
            self._show_folder_error("Choose a folder for your library.")
            return False

        self._store.set("library_root", raw)
        organizer = OrganizationService(self._store.settings)
        writable, error = organizer.ensure_writable()
        if not writable:
            self._show_folder_error(f"Mediary cannot write there: {error}")
            return False
        try:
            organizer.ensure_library_tree()
        except Exception as exc:  # noqa: BLE001
            self._show_folder_error(str(exc))
            return False

        self._folder_error.hide()
        self._chosen_root = raw
        return True

    def _show_folder_error(self, message: str) -> None:
        self._folder_error.setText(message)
        self._folder_error.show()

    def _choose_ffmpeg(self) -> None:
        import sys

        pattern = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
        path, _ = QFileDialog.getOpenFileName(
            self, "Locate FFmpeg", str(Path.home()), f"FFmpeg ({pattern});;All files (*)"
        )
        if not path:
            return
        info = get_ffmpeg(path, refresh=True)
        if info.available:
            self._store.set("ffmpeg_path", path)
            self._stack.removeWidget(self._stack.widget(2))
            self._stack.insertWidget(2, self._page_tools())
            self._stack.setCurrentIndex(2)

    def _ffmpeg_help(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl("https://ffmpeg.org/download.html"))

    def _finish(self) -> None:
        self._store.update({"first_run_complete": True})
        self.accept()
