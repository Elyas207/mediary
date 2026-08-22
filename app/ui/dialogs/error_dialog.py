"""A human-readable error dialog with the raw detail kept one click away.

Mediary never puts a stack trace or a raw extractor message in the main UI, but
the exact text is always recoverable for a bug report.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QWidget

from app.ui.theme import Space, get_theme
from app.ui.widgets.common import button, hbox, label, monospace_font, vbox


class ErrorDialog(QDialog):
    """Shows what went wrong, with an expandable technical detail panel."""

    def __init__(
        self,
        *,
        title: str = "Something went wrong",
        message: str = "",
        detail: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        self._detail = detail

        layout = vbox(self, spacing=Space.md, margins=(Space.xl, Space.xl, Space.xl, Space.lg))

        header = QWidget(self)
        header_layout = hbox(header, spacing=Space.md)
        theme = get_theme()
        if theme is not None:
            from PySide6.QtWidgets import QLabel

            glyph = QLabel(header)
            glyph.setPixmap(theme.pixmap("alert", 20, "danger"))
            glyph.setFixedSize(20, 20)
            header_layout.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        heading_column = vbox(spacing=Space.xs)
        heading_column.addWidget(label(title, "heading", wrap=True))
        heading_column.addWidget(label(message, "pageSubtitle", wrap=True))
        header_layout.addLayout(heading_column, 1)
        layout.addWidget(header)

        self._detail_box = QPlainTextEdit(self)
        self._detail_box.setPlainText(detail or "No further detail was reported.")
        self._detail_box.setReadOnly(True)
        self._detail_box.setFont(monospace_font(11))
        self._detail_box.setFixedHeight(150)
        self._detail_box.setVisible(False)
        layout.addWidget(self._detail_box)

        actions = QWidget(self)
        actions_layout = hbox(actions, spacing=Space.sm)

        self._toggle_btn = button("Show details", variant="ghost", on_click=self._toggle_detail)
        actions_layout.addWidget(self._toggle_btn)
        actions_layout.addStretch(1)

        self._copy_btn = button("Copy error details", variant="subtle", on_click=self._copy)
        actions_layout.addWidget(self._copy_btn)

        close_btn = button("Close", variant="primary", on_click=self.accept)
        close_btn.setDefault(True)
        actions_layout.addWidget(close_btn)

        layout.addWidget(actions)

    def _toggle_detail(self) -> None:
        showing = not self._detail_box.isVisible()
        self._detail_box.setVisible(showing)
        self._toggle_btn.setText("Hide details" if showing else "Show details")
        self.adjustSize()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._detail or "")
        self._copy_btn.setText("Copied")
