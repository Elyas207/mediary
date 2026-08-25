"""The bar across the top of the content area: search, and the theme switch.

Search here is global - it jumps to the library with the query applied, rather
than filtering whatever screen happens to be open. One search box that always
means the same thing beats three that each mean something local.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLineEdit, QWidget

from app.ui.theme import Size, Space, get_theme
from app.ui.widgets.common import SegmentedControl, hbox, icon_button

#: ``(value, tooltip, icon)`` for the light/dark switch.
THEME_OPTIONS: tuple = (
    ("light", "", "sun"),
    ("dark", "", "moon"),
)


class SearchField(QLineEdit):
    """A rounded search input with a leading magnifier and a clear action."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SearchField")
        self.setPlaceholderText("Search your library…")
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(Size.input_height)
        self.refresh_icon()

    def refresh_icon(self) -> None:
        theme = get_theme()
        if theme is None:
            return
        # Qt draws the action inside the field, so the padding in the
        # stylesheet has to leave room for it.
        for action in self.actions():
            self.removeAction(action)
        self.addAction(
            theme.icon("search", Size.icon_sm, "muted"),
            QLineEdit.ActionPosition.LeadingPosition,
        )


class TopBar(QWidget):
    """Search on the left, theme switch on the right."""

    search_submitted = Signal(str)
    search_cleared = Signal()
    theme_selected = Signal(str)      # "light" | "dark"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(Size.topbar_height)

        layout = hbox(self, spacing=Space.md, margins=(Space.lg, Space.sm, Space.lg, Space.sm))

        self.search = SearchField(self)
        self.search.returnPressed.connect(self._on_submit)
        self.search.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.search, 1)

        layout.addStretch(0)

        self.theme_switch = SegmentedControl(list(THEME_OPTIONS), parent=self)
        self.theme_switch.setObjectName("ThemeSwitch")
        self.theme_switch.changed.connect(self.theme_selected.emit)
        layout.addWidget(self.theme_switch)

        self.notifications = icon_button(
            "inbox", tooltip="Recent activity", size=Size.icon, tone="secondary"
        )
        self.notifications.hide()
        layout.addWidget(self.notifications)

        focus = QShortcut(QKeySequence.StandardKey.Find, self)
        focus.activated.connect(self.focus_search)

    # -- State ------------------------------------------------------------

    def focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def set_theme_value(self, name: str) -> None:
        """Reflect the active palette without re-emitting."""
        self.theme_switch.set_value("dark" if name == "dark" else "light")

    def refresh_theme(self) -> None:
        self.search.refresh_icon()
        self.theme_switch.refresh_icons()

    def set_query(self, text: str) -> None:
        blocked = self.search.blockSignals(True)
        self.search.setText(text)
        self.search.blockSignals(blocked)

    # -- Signals ----------------------------------------------------------

    def _on_submit(self) -> None:
        self.search_submitted.emit(self.search.text().strip())

    def _on_text_changed(self, text: str) -> None:
        if not text.strip():
            self.search_cleared.emit()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(600, Size.topbar_height)
