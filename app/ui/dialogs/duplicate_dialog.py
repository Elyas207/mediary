"""Asked when an incoming download matches something already in the library.

Mediary never blocks a deliberate duplicate - it just makes sure the user knows
before a second copy lands on disk.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QWidget

from app.services.library_service import DuplicateMatch
from app.ui.theme import Space
from app.ui.widgets.common import (
    ElidedLabel,
    button,
    divider,
    hbox,
    label,
    panel,
    vbox,
)
from app.ui.widgets.thumbnail import Thumbnail
from app.utils.formatting import format_bytes, format_duration, relative_date


class DuplicateDialog(QDialog):
    """Returns ``"skip"``, ``"download"`` or ``"replace"``."""

    def __init__(
        self,
        duplicate: DuplicateMatch,
        info=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Already in your library")
        self.setModal(True)
        self.setMinimumWidth(540)
        self._duplicate = duplicate
        self._choice = "skip"

        item = duplicate.item
        layout = vbox(self, spacing=Space.lg, margins=(Space.xl, Space.xl, Space.xl, Space.lg))

        layout.addWidget(label("This media is already in Mediary", "heading", wrap=True))
        layout.addWidget(
            label(
                f"Mediary matched it by {duplicate.description}. "
                "You can still download another copy if you meant to.",
                "pageSubtitle",
                wrap=True,
            )
        )

        # -- Existing item preview ----------------------------------------
        card = panel(inset=True, parent=self)
        card_layout = hbox(card, spacing=Space.md, margins=(Space.md, Space.md, Space.md, Space.md))

        thumb = Thumbnail(
            aspect=16 / 9,
            fallback_icon="audio" if item.is_audio else "video",
            parent=card,
        )
        thumb.setFixedSize(QSize(104, 60))
        thumb.set_source(item.thumbnail_path, max_edge=240)
        card_layout.addWidget(thumb, 0, Qt.AlignmentFlag.AlignTop)

        column = vbox(spacing=2)
        column.addWidget(ElidedLabel(item.display_title, "itemTitle", parent=card))

        meta_parts = [item.category]
        if item.duration:
            meta_parts.append(format_duration(item.duration))
        if item.container:
            meta_parts.append(item.container.upper())
        if item.file_size:
            meta_parts.append(format_bytes(item.file_size))
        meta_parts.append(f"Added {relative_date(item.downloaded_at).lower()}")
        column.addWidget(ElidedLabel("  ·  ".join(meta_parts), "muted", parent=card))

        path_label = ElidedLabel(item.file_path, "mono", parent=card)
        path_label.setToolTip(item.file_path)
        column.addWidget(path_label)

        if item.file_missing:
            column.addWidget(label("The file for this entry is missing.", "warning"))

        card_layout.addLayout(column, 1)
        layout.addWidget(card)

        layout.addWidget(divider())

        self._apply_all = QCheckBox("Do this for the rest of this batch", self)
        layout.addWidget(self._apply_all)

        actions = QWidget(self)
        actions_layout = hbox(actions, spacing=Space.sm)
        actions_layout.addWidget(
            button("Replace", variant="ghost", on_click=lambda: self._choose("replace"))
        )
        actions_layout.addStretch(1)
        actions_layout.addWidget(
            button("Download anyway", variant="subtle", on_click=lambda: self._choose("download"))
        )
        skip = button("Skip", variant="primary", on_click=lambda: self._choose("skip"))
        skip.setDefault(True)
        actions_layout.addWidget(skip)
        layout.addWidget(actions)

    def _choose(self, value: str) -> None:
        self._choice = value
        self.accept()

    @property
    def apply_to_all(self) -> bool:
        return self._apply_all.isChecked()

    def run(self) -> str:
        self.exec()
        return self._choice
