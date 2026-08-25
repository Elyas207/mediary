"""Where you can see, edit and delete the filing rules Mediary follows.

Every rule here was either offered after a correction on the Download screen or
typed in below. Nothing writes to this table on its own - a rule exists because
someone asked for it, which is the whole reason it can safely outrank history.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QScrollArea,
    QWidget,
)

from app.models.category import CATEGORIES_BY_KIND
from app.models.filing import FIELD_LABELS, FilingRule
from app.ui.theme import Space
from app.ui.widgets.common import (
    ElidedLabel,
    EmptyState,
    button,
    divider,
    hbox,
    icon_button,
    label,
    panel,
    vbox,
)


class RuleRow(QWidget):
    """One rule: what it matches, where it files, and how often it has fired."""

    toggled = Signal(int, bool)
    deleted = Signal(int)

    def __init__(self, rule: FilingRule, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rule = rule
        layout = hbox(self, spacing=Space.sm, margins=(0, Space.xs, 0, Space.xs))

        self.check = QCheckBox(self)
        self.check.setChecked(rule.enabled)
        self.check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check.setToolTip("Turn this rule off without deleting it")
        self.check.toggled.connect(self._on_toggled)
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)

        column = vbox(spacing=1)
        column.addWidget(ElidedLabel(rule.describe(), "itemTitle", parent=self))

        if rule.times_applied:
            times = "once" if rule.times_applied == 1 else f"{rule.times_applied} times"
            note = f"Used {times}"
        else:
            note = "Not used yet"
        column.addWidget(label(note, "meta", parent=self))
        layout.addLayout(column, 1)

        remove = icon_button("trash", tooltip="Delete this rule", size=14, tone="muted")
        remove.clicked.connect(lambda: self.deleted.emit(int(self.rule.id or 0)))
        layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignVCenter)

    def _on_toggled(self, checked: bool) -> None:
        self.rule.enabled = checked
        self.toggled.emit(int(self.rule.id or 0), checked)


class FilingRulesDialog(QDialog):
    """Manage the "always file this there" rules."""

    changed = Signal()

    def __init__(
        self,
        filing,
        library,
        settings=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._filing = filing
        self._library = library
        self._settings = settings
        self._dirty = False

        self.setWindowTitle("Filing rules")
        self.setModal(True)
        self.setMinimumSize(600, 480)

        layout = vbox(self, spacing=Space.lg, margins=(Space.xl, Space.xl, Space.xl, Space.lg))
        layout.addWidget(label("Filing rules", "heading"))
        layout.addWidget(
            label(
                "Rules win over everything else Mediary guesses from. They only "
                "come from you - either from a correction you made, or from here.",
                "heroBody",
                wrap=True,
                parent=self,
            )
        )

        # -- The list ------------------------------------------------------
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list = QWidget()
        self._list_layout = vbox(self._list, spacing=0)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list)
        layout.addWidget(self._scroll, 1)

        self._empty = EmptyState(
            icon="sparkle",
            title="No rules yet",
            body=(
                "When you change a suggested category on the Download screen, "
                "Mediary offers to remember it. Accepted offers land here."
            ),
            parent=self,
        )
        layout.addWidget(self._empty, 1)

        layout.addWidget(divider(parent=self))

        # -- Add a rule ----------------------------------------------------
        adder = panel(inset=True, parent=self)
        add_layout = vbox(adder, spacing=Space.sm, margins=(Space.md,) * 4)
        add_layout.addWidget(label("Add a rule", "sectionLabel", parent=adder))

        row = QWidget(adder)
        row_layout = hbox(row, spacing=Space.sm)

        self.field_box = QComboBox(row)
        for value, text in FIELD_LABELS.items():
            self.field_box.addItem(text, value)
        self.field_box.setCursor(Qt.CursorShape.PointingHandCursor)
        row_layout.addWidget(self.field_box)

        self.pattern_edit = QLineEdit(row)
        self.pattern_edit.setPlaceholderText("Match this…")
        self.pattern_edit.returnPressed.connect(self._add_rule)
        self.pattern_edit.textChanged.connect(self._refresh_add_state)
        row_layout.addWidget(self.pattern_edit, 1)

        row_layout.addWidget(label("→", "muted", parent=row))

        self.category_box = QComboBox(row)
        for name in self._categories():
            self.category_box.addItem(name, name)
        self.category_box.setCursor(Qt.CursorShape.PointingHandCursor)
        row_layout.addWidget(self.category_box)

        self.add_btn = button("Add", variant="secondary", size="sm", on_click=self._add_rule)
        self.add_btn.setEnabled(False)
        row_layout.addWidget(self.add_btn)
        add_layout.addWidget(row)
        layout.addWidget(adder)

        # -- Footer --------------------------------------------------------
        footer = QWidget(self)
        footer_layout = hbox(footer, spacing=Space.sm)
        footer_layout.addStretch(1)
        footer_layout.addWidget(button("Done", variant="primary", on_click=self.accept))
        layout.addWidget(footer)

        self.reload()

    # ------------------------------------------------------------------

    def _categories(self) -> list:
        """Every category a rule may file into, video and audio alike."""
        names: list = []
        for group in CATEGORIES_BY_KIND.values():
            names.extend(n for n in group if n not in names)
        custom = getattr(self._settings, "custom_categories", None) or []
        names.extend(n for n in custom if n not in names)
        return names

    def reload(self) -> None:
        """Rebuild the list from the database."""
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        rules = self._library.all_rules()
        for rule in rules:
            row = RuleRow(rule, self._list)
            row.toggled.connect(self._on_toggled)
            row.deleted.connect(self._on_deleted)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

        has_rules = bool(rules)
        self._scroll.setVisible(has_rules)
        self._empty.setVisible(not has_rules)

    def _refresh_add_state(self) -> None:
        self.add_btn.setEnabled(bool(self.pattern_edit.text().strip()))

    def _add_rule(self) -> None:
        pattern = self.pattern_edit.text().strip()
        if not pattern:
            return
        rule = FilingRule(
            field=self.field_box.currentData(),
            pattern=pattern,
            category=self.category_box.currentData(),
        )
        self._filing.save_rule(rule)
        self.pattern_edit.clear()
        self._mark_changed()
        self.reload()

    def _on_toggled(self, rule_id: int, enabled: bool) -> None:
        if rule_id:
            self._library.set_rule_enabled(rule_id, enabled)
            self._filing.invalidate()
            self._mark_changed()

    def _on_deleted(self, rule_id: int) -> None:
        if not rule_id:
            return
        self._library.delete_rule(rule_id)
        self._filing.invalidate()
        self._mark_changed()
        self.reload()

    @property
    def dirty(self) -> bool:
        """Whether any rule was added, toggled or deleted while open."""
        return self._dirty

    def _mark_changed(self) -> None:
        self._dirty = True
        self.changed.emit()


def open_filing_rules(filing, library, settings=None, parent: QWidget | None = None) -> bool:
    """Show the dialog. Returns whether anything changed."""
    dialog = FilingRulesDialog(filing, library, settings, parent)
    dialog.exec()
    return dialog.dirty
