"""The live queue, shown inline beneath the download screen.

The Queue screen is where a download gets managed; this is where it gets
*watched*. After hitting download the natural next move is to paste the next
link, so the progress has to be visible without navigating away from the box
you are about to type in.

Only unfinished work appears here. A finished download belongs in the library,
not in a list of things still happening.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QProgressBar, QWidget

from app.models.download import DownloadStatus
from app.ui.theme import Space
from app.ui.widgets.common import Badge, button, hbox, label, vbox
from app.ui.widgets.queue_row import QueueRow

#: Rows past this are counted in the summary rather than drawn. A queue of
#: sixty would otherwise push the paste box off the screen entirely.
MAX_VISIBLE_ROWS = 4


class QueuePanel(QFrame):
    """A compact live view of whatever is still downloading."""

    show_queue_requested = Signal()
    pause_requested = Signal(str)
    resume_requested = Signal(str)
    cancel_requested = Signal(str)
    retry_requested = Signal(str)

    def __init__(self, manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._manager = manager
        self._rows: dict = {}

        layout = vbox(self, spacing=Space.sm, margins=(Space.md,) * 4)

        # -- Header --------------------------------------------------------
        header = QWidget(self)
        header_layout = hbox(header, spacing=Space.sm)
        header_layout.addWidget(label("Download queue", "sectionLabel", parent=header))

        self.count_badge = Badge("0", "accent", header)
        header_layout.addWidget(self.count_badge)
        header_layout.addStretch(1)

        self.open_queue_btn = button(
            "Open queue", variant="link", size="sm", on_click=self.show_queue_requested.emit
        )
        header_layout.addWidget(self.open_queue_btn)
        layout.addWidget(header)

        # -- Rows ----------------------------------------------------------
        self._rows_holder = QWidget(self)
        self._rows_layout = vbox(self._rows_holder, spacing=Space.xs)
        layout.addWidget(self._rows_holder)

        self.more_label = label("", "meta", parent=self)
        self.more_label.hide()
        layout.addWidget(self.more_label)

        # -- Overall -------------------------------------------------------
        overall = QWidget(self)
        overall_layout = hbox(overall, spacing=Space.sm)
        overall_layout.addWidget(label("Overall", "meta", parent=overall))

        self.overall_bar = QProgressBar(overall)
        self.overall_bar.setObjectName("OverallProgress")
        self.overall_bar.setTextVisible(False)
        self.overall_bar.setFixedHeight(6)
        self.overall_bar.setRange(0, 1000)
        overall_layout.addWidget(self.overall_bar, 1)

        self.overall_label = label("", "meta", parent=overall)
        self.overall_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        overall_layout.addWidget(self.overall_label)
        layout.addWidget(overall)

        manager.task_added.connect(self._on_task_changed)
        manager.task_updated.connect(self._on_task_changed)
        manager.task_removed.connect(self._on_task_removed)
        manager.task_completed.connect(lambda task, _result: self._on_task_changed(task))
        manager.task_failed.connect(self._on_task_changed)

        self.refresh()

    # ------------------------------------------------------------------

    def _live_tasks(self) -> list:
        """Everything not yet finished, oldest first."""
        return [
            task
            for task in self._manager.tasks
            if task.status is not DownloadStatus.COMPLETE
            and task.status is not DownloadStatus.CANCELLED
        ]

    def refresh(self) -> None:
        tasks = self._live_tasks()
        if not tasks:
            self.hide()
            self._clear_rows()
            return

        visible = tasks[:MAX_VISIBLE_ROWS]
        wanted = {task.id for task in visible}

        for task_id in list(self._rows):
            if task_id not in wanted:
                row = self._rows.pop(task_id)
                self._rows_layout.removeWidget(row)
                row.deleteLater()

        for index, task in enumerate(visible):
            row = self._rows.get(task.id)
            if row is None:
                row = QueueRow(task, self._rows_holder)
                row.pause_requested.connect(self.pause_requested.emit)
                row.resume_requested.connect(self.resume_requested.emit)
                row.cancel_requested.connect(self.cancel_requested.emit)
                row.retry_requested.connect(self.retry_requested.emit)
                self._rows[task.id] = row
                self._rows_layout.insertWidget(index, row)
            row.task = task
            row.update_from_task(task)

        hidden = len(tasks) - len(visible)
        self.more_label.setText(
            f"and {hidden} more waiting" if hidden else ""
        )
        self.more_label.setVisible(bool(hidden))

        self.count_badge.setText(str(len(tasks)))
        self._refresh_overall(tasks)
        self.show()

    def _refresh_overall(self, tasks: list) -> None:
        """Progress across the whole batch, weighted by bytes where known.

        Averaging percentages would make a 4 MB file that is nearly done count
        as much as a 2 GB file that has barely started.
        """
        total = sum(t.progress.total_bytes for t in tasks)
        if total > 0:
            done = sum(t.progress.downloaded_bytes for t in tasks)
            fraction = done / total
        else:
            samples = [t.progress.percent / 100.0 for t in tasks]
            fraction = sum(samples) / len(samples) if samples else 0.0

        finished = sum(1 for t in self._manager.tasks if t.status is DownloadStatus.COMPLETE)
        overall = len(tasks) + finished

        self.overall_bar.setValue(int(round(max(0.0, min(1.0, fraction)) * 1000)))
        self.overall_label.setText(f"{finished} of {overall}  ·  {fraction * 100:.0f}%")

    def _clear_rows(self) -> None:
        for row in self._rows.values():
            row.deleteLater()
        self._rows.clear()

    def _on_task_changed(self, _task) -> None:
        self.refresh()

    def _on_task_removed(self, _task_id: str) -> None:
        self.refresh()


__all__ = ["QueuePanel"]
