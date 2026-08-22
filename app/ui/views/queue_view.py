"""The download queue screen.

Filter tabs, an aggregate header and a dense list of live transfers - the shape
a transfer manager needs so several downloads stay visible at once.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QScrollArea, QWidget

from app.models.download import DownloadStatus, DownloadTask
from app.ui.theme import Space
from app.ui.widgets.common import (
    EmptyState,
    SegmentedControl,
    button,
    divider,
    hbox,
    label,
    vbox,
)
from app.ui.widgets.queue_row import QueueRow
from app.utils.formatting import format_speed

FILTERS = (
    ("all", "All"),
    ("active", "Active"),
    ("complete", "Complete"),
    ("failed", "Failed"),
)


class QueueView(QWidget):
    """Live view of everything the download manager is working on."""

    open_file_requested = Signal(str)         # file path
    open_folder_requested = Signal(str)       # file path
    show_error_requested = Signal(object)     # DownloadTask
    reveal_in_library_requested = Signal(int) # media id
    start_download_requested = Signal()

    def __init__(self, manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._rows: dict = {}
        self._filter = "all"

        root = vbox(self, spacing=0)
        root.addWidget(self._build_header())
        root.addWidget(divider())

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll, 1)

        container = QWidget(self._scroll)
        self._list_layout = vbox(container, spacing=0)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(container)

        self._empty = EmptyState(
            icon="queue",
            title="Nothing in the queue",
            body="Downloads you start appear here with live progress, speed and where they landed.",
            action_text="Download media",
            on_action=self.start_download_requested.emit,
            parent=self,
        )
        root.addWidget(self._empty, 1)

        manager.task_added.connect(self._on_task_added)
        manager.task_updated.connect(self._on_task_updated)
        manager.task_removed.connect(self._on_task_removed)
        manager.queue_changed.connect(self.refresh_summary)

        self.refresh_summary()

    # -- Construction -----------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        layout = vbox(header, spacing=Space.md, margins=(Space.xxl, Space.xl, Space.xxl, Space.md))

        title_row = QWidget(header)
        title_layout = hbox(title_row, spacing=Space.md)
        title_layout.addWidget(label("Queue", "pageTitle"))
        title_layout.addStretch(1)

        self._clear_btn = button(
            "Clear finished", variant="ghost", size="sm", on_click=self._clear_finished
        )
        title_layout.addWidget(self._clear_btn)
        self._cancel_btn = button(
            "Cancel all", variant="ghost", size="sm", on_click=self._manager.cancel_all
        )
        title_layout.addWidget(self._cancel_btn)
        layout.addWidget(title_row)

        controls = QWidget(header)
        controls_layout = hbox(controls, spacing=Space.md)

        self._filter_control = SegmentedControl(list(FILTERS), parent=controls)
        self._filter_control.changed.connect(self._on_filter_changed)
        controls_layout.addWidget(self._filter_control)

        controls_layout.addStretch(1)
        self._summary = label("", "meta")
        controls_layout.addWidget(self._summary)
        layout.addWidget(controls)

        return header

    # -- Task lifecycle ---------------------------------------------------

    def _on_task_added(self, task: DownloadTask) -> None:
        row = QueueRow(task, self)
        row.pause_requested.connect(self._manager.pause)
        row.resume_requested.connect(self._manager.resume)
        row.cancel_requested.connect(self._manager.cancel)
        row.retry_requested.connect(self._manager.retry)
        row.remove_requested.connect(self._manager.remove)
        row.open_file_requested.connect(self._open_file)
        row.open_folder_requested.connect(self._open_folder)
        row.show_error_requested.connect(self._show_error)
        row.reveal_in_library_requested.connect(self._reveal)

        # Newest at the top - that is where attention already is.
        self._list_layout.insertWidget(0, row)
        self._rows[task.id] = row
        self._apply_filter_to(row)
        self._update_visibility()

    def _on_task_updated(self, task: DownloadTask) -> None:
        row = self._rows.get(task.id)
        if row is not None:
            row.update_from_task(task)
            self._apply_filter_to(row)
        self.refresh_summary()

    def _on_task_removed(self, task_id: str) -> None:
        row = self._rows.pop(task_id, None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        self._update_visibility()

    # -- Filtering --------------------------------------------------------

    def _on_filter_changed(self, value: str) -> None:
        self._filter = value
        for row in self._rows.values():
            self._apply_filter_to(row)
        self._update_visibility()

    def _matches_filter(self, row: QueueRow) -> bool:
        status = row.task.status
        return {
            "all": True,
            "active": status.is_active or status.is_pending,
            "complete": status == DownloadStatus.COMPLETE,
            "failed": status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED),
        }.get(self._filter, True)

    def _apply_filter_to(self, row: QueueRow) -> None:
        row.setVisible(self._matches_filter(row))

    def _update_visibility(self) -> None:
        # Ask the filter directly rather than each row's isVisible(): while the
        # scroll area itself is hidden, every child reports invisible and the
        # empty state would latch on permanently.
        has_visible = any(self._matches_filter(row) for row in self._rows.values())
        self._scroll.setVisible(has_visible)
        self._empty.setVisible(not has_visible)
        if not has_visible and self._rows:
            self._empty.set_text(
                "Nothing matches this filter",
                "Switch back to All to see the rest of the queue.",
            )
        else:
            self._empty.set_text(
                "Nothing in the queue",
                "Downloads you start appear here with live progress, speed and where they landed.",
            )
        self.refresh_summary()

    # -- Summary ----------------------------------------------------------

    def refresh_summary(self) -> None:
        counts = self._manager.counts()
        parts = []
        if counts["active"]:
            parts.append(f"{counts['active']} downloading")
        if counts["pending"]:
            parts.append(f"{counts['pending']} queued")
        if counts["complete"]:
            parts.append(f"{counts['complete']} complete")
        if counts["failed"]:
            parts.append(f"{counts['failed']} failed")

        speed = sum(
            task.progress.speed
            for task in self._manager.tasks
            if task.status == DownloadStatus.DOWNLOADING
        )
        if speed:
            parts.append(format_speed(speed))

        self._summary.setText("  ·  ".join(parts) if parts else "")
        self._clear_btn.setEnabled(bool(counts["complete"] or counts["failed"]))
        self._cancel_btn.setEnabled(bool(counts["active"] or counts["pending"]))

    # -- Actions ----------------------------------------------------------

    def _clear_finished(self) -> None:
        self._manager.clear_finished()
        self._update_visibility()

    def _task(self, task_id: str) -> DownloadTask | None:
        return self._manager.task(task_id)

    def _open_file(self, task_id: str) -> None:
        task = self._task(task_id)
        if task and task.output_path:
            self.open_file_requested.emit(task.output_path)

    def _open_folder(self, task_id: str) -> None:
        task = self._task(task_id)
        if task and task.output_path:
            self.open_folder_requested.emit(task.output_path)

    def _show_error(self, task_id: str) -> None:
        task = self._task(task_id)
        if task:
            self.show_error_requested.emit(task)

    def _reveal(self, task_id: str) -> None:
        task = self._task(task_id)
        if task and task.media_id:
            self.reveal_in_library_requested.emit(task.media_id)
