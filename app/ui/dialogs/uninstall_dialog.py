"""The uninstall dialog.

Deliberately not a yes/no prompt. It lists every item, its real size on disk,
and lets the user choose. The media library is unticked by default and needs a
typed confirmation, because it is the one choice here that destroys work rather
than settings.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLineEdit,
    QScrollArea,
    QWidget,
)

from app.services.uninstall_service import UninstallPlan, UninstallService
from app.ui.theme import Space, get_theme
from app.ui.widgets.common import (
    ElidedLabel,
    Notice,
    button,
    divider,
    hbox,
    label,
    panel,
    vbox,
)
from app.utils.formatting import format_bytes

#: Typed by hand before the media library can be deleted.
CONFIRM_WORD = "DELETE"


class UninstallDialog(QDialog):
    """Choose what to remove, see what it costs, then confirm."""

    finished_uninstall = Signal(object)   # UninstallResult

    def __init__(
        self,
        service: UninstallService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._plan: UninstallPlan = service.plan()
        self._checks: dict = {}

        self.setWindowTitle("Remove Mediary's data")
        self.setModal(True)
        self.setMinimumWidth(620)

        layout = vbox(self, spacing=Space.lg, margins=(Space.xl, Space.xl, Space.xl, Space.lg))

        layout.addWidget(label("Remove Mediary's data", "heading"))
        layout.addWidget(
            label(
                "Choose what to delete from this machine. Nothing is removed until "
                "you confirm, and anything you leave unticked stays exactly as it is.",
                "pageSubtitle",
                wrap=True,
            )
        )

        layout.addWidget(self._build_target_list(), 1)

        self._library_confirm_row = self._build_library_confirmation()
        self._library_confirm_row.hide()
        layout.addWidget(self._library_confirm_row)

        if self._plan.autostart_registered:
            self._autostart_check = QCheckBox(
                "Also remove the entry that launches Mediary when you sign in", self
            )
            self._autostart_check.setChecked(True)
            layout.addWidget(self._autostart_check)
        else:
            self._autostart_check = None

        layout.addWidget(
            label(UninstallService.application_hint(), "muted", wrap=True)
        )

        layout.addWidget(divider())
        layout.addWidget(self._build_actions())

        self._update_state()

    # ------------------------------------------------------------------

    def _build_target_list(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(300)

        content = QWidget(scroll)
        layout = vbox(content, spacing=Space.sm)

        for target in self._plan.targets:
            layout.addWidget(self._build_target_row(target))

        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _build_target_row(self, target) -> QWidget:
        card = panel(inset=True, parent=self)
        layout = hbox(card, spacing=Space.md, margins=(Space.md, Space.md, Space.md, Space.md))

        check = QCheckBox(card)
        # Everything harmless is on by default; the library is not.
        check.setChecked(target.exists and not target.destructive)
        check.setEnabled(target.exists)
        check.toggled.connect(self._update_state)
        self._checks[target.key] = check
        layout.addWidget(check, 0, Qt.AlignmentFlag.AlignTop)

        column = vbox(spacing=2)

        heading = QWidget(card)
        heading_layout = hbox(heading, spacing=Space.sm)
        title = label(target.label, "itemTitle")
        heading_layout.addWidget(title)

        if target.exists:
            detail = f"{format_bytes(target.size)}"
            if target.file_count:
                detail += f"  ·  {target.file_count:,} file{'s' if target.file_count != 1 else ''}"
        else:
            detail = "Not present"
        heading_layout.addWidget(label(detail, "muted"))
        heading_layout.addStretch(1)
        column.addWidget(heading)

        column.addWidget(label(target.description, "muted", wrap=True))

        path_label = ElidedLabel(str(target.path), "mono", parent=card)
        path_label.setToolTip(str(target.path))
        column.addWidget(path_label)

        layout.addLayout(column, 1)
        return card

    def _build_library_confirmation(self) -> QWidget:
        holder = QWidget(self)
        layout = vbox(holder, spacing=Space.sm)

        notice = Notice(
            "You have chosen to delete your downloaded media. Those files are not "
            "backed up by Mediary and cannot be recovered from it.",
            tone="danger",
            title="This deletes your media files",
            dismissible=False,
            parent=holder,
        )
        layout.addWidget(notice)

        row = QWidget(holder)
        row_layout = hbox(row, spacing=Space.sm)
        row_layout.addWidget(label(f"Type {CONFIRM_WORD} to confirm", "fieldLabel"))
        self._confirm_input = QLineEdit(row)
        self._confirm_input.setPlaceholderText(CONFIRM_WORD)
        self._confirm_input.setFixedWidth(160)
        self._confirm_input.textChanged.connect(self._update_state)
        row_layout.addWidget(self._confirm_input)
        row_layout.addStretch(1)
        layout.addWidget(row)
        return holder

    def _build_actions(self) -> QWidget:
        actions = QWidget(self)
        layout = hbox(actions, spacing=Space.sm)

        self._summary = label("", "meta")
        layout.addWidget(self._summary)
        layout.addStretch(1)

        layout.addWidget(button("Cancel", variant="ghost", on_click=self.reject))

        self._remove_btn = button("Remove", variant="danger", on_click=self._run)
        layout.addWidget(self._remove_btn)
        return actions

    # ------------------------------------------------------------------

    def _selected_keys(self) -> list:
        return [key for key, check in self._checks.items() if check.isChecked()]

    def _update_state(self) -> None:
        keys = self._selected_keys()
        library_selected = "library" in keys

        self._library_confirm_row.setVisible(library_selected)
        if not library_selected:
            self._confirm_input.clear()

        total = self._plan.total_size(keys)
        if keys:
            self._summary.setText(
                f"{len(keys)} item{'s' if len(keys) != 1 else ''}  ·  {format_bytes(total)}"
            )
        else:
            self._summary.setText("Nothing selected")

        confirmed = (not library_selected) or self._confirm_input.text().strip() == CONFIRM_WORD
        self._remove_btn.setEnabled(bool(keys) and confirmed)
        self._remove_btn.setText("Remove everything" if library_selected else "Remove")

    def _run(self) -> None:
        keys = self._selected_keys()
        if not keys:
            return

        remove_autostart = bool(
            self._autostart_check is not None and self._autostart_check.isChecked()
        )
        self._remove_btn.setEnabled(False)
        self._remove_btn.setText("Removing…")

        result = self._service.execute(keys, remove_autostart=remove_autostart)
        self.finished_uninstall.emit(result)
        self.accept()


_ = get_theme  # kept so this module follows the same theming import convention
