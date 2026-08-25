"""One row in the download queue.

Progress is drawn as a hairline along the bottom edge of the row rather than as
a chunky bar: at queue density that reads faster and keeps the row height low
enough to see several downloads at once.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget

from app.models.download import DownloadStatus, DownloadTask
from app.ui.theme import Size, Space, get_theme
from app.ui.theme.tokens import status_color
from app.ui.widgets.common import (
    Badge,
    ElidedLabel,
    hbox,
    icon_button,
    label,
    vbox,
)
from app.ui.widgets.thumbnail import Thumbnail
from app.utils.formatting import format_bytes, format_eta, format_speed


class QueueRow(QFrame):
    """A single download with live progress, speed, ETA and inline actions."""

    #: Columns keep the queue readable as a table while it scrolls. They are
    #: maximums rather than fixed widths: inline on the Download screen the row
    #: is far narrower, and fixed columns there squeeze the title to nothing.
    BADGE_COLUMN_WIDTH = 210
    METRICS_COLUMN_WIDTH = 150
    ACTIONS_COLUMN_WIDTH = 132
    #: Below this the title stops being a title.
    TITLE_MIN_WIDTH = 150

    pause_requested = Signal(str)
    resume_requested = Signal(str)
    cancel_requested = Signal(str)
    retry_requested = Signal(str)
    remove_requested = Signal(str)
    open_file_requested = Signal(str)
    open_folder_requested = Signal(str)
    show_error_requested = Signal(str)
    reveal_in_library_requested = Signal(str)

    def __init__(self, task: DownloadTask, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("QueueRow")
        self.task = task
        self._progress_fraction = 0.0
        self.setFixedHeight(Size.queue_row_height)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        layout = hbox(self, spacing=Space.md, margins=(Space.md, 0, Space.md, 0))

        self.thumb = Thumbnail(radius=4, aspect=16 / 9, fallback_icon="download", parent=self)
        self.thumb.setFixedSize(QSize(56, 32))
        layout.addWidget(self.thumb)

        # -- Title + status column ----------------------------------------
        text_column = QWidget(self)
        text_layout = vbox(text_column, spacing=1)

        self.title = ElidedLabel(task.display_title, "itemTitle", parent=text_column)
        text_layout.addWidget(self.title)

        self.status_label = ElidedLabel("", "muted", parent=text_column)
        text_layout.addWidget(self.status_label)

        text_column.setMinimumWidth(self.TITLE_MIN_WIDTH)
        layout.addWidget(text_column, 1)

        # Format and category sit in their own fixed column so the badges line
        # up down the queue instead of drifting with each title's length.
        badges = QWidget(self)
        badges.setMaximumWidth(self.BADGE_COLUMN_WIDTH)
        badges.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        badge_layout = hbox(badges, spacing=Space.xs)
        badge_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.format_badge = Badge(task.options.quality_label(), parent=badges)
        badge_layout.addWidget(self.format_badge)
        self.category_badge = Badge(task.options.category, parent=badges)
        badge_layout.addWidget(self.category_badge)
        badge_layout.addStretch(1)
        layout.addWidget(badges)

        # -- Numeric column (fixed width so rows stay aligned) -------------
        self.metrics = label("", "meta")
        self.metrics.setMaximumWidth(self.METRICS_COLUMN_WIDTH)
        self.metrics.setMinimumWidth(96)
        self.metrics.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.metrics)

        # -- Actions --------------------------------------------------------
        self.actions = QWidget(self)
        self.actions.setMaximumWidth(self.ACTIONS_COLUMN_WIDTH)
        self._actions_layout = hbox(self.actions, spacing=2)
        self._actions_layout.addStretch(1)
        layout.addWidget(self.actions)

        self._buttons: dict = {}
        for key, icon, tooltip, signal in (
            ("pause", "pause", "Pause", self.pause_requested),
            ("resume", "play", "Resume", self.resume_requested),
            ("retry", "refresh", "Retry", self.retry_requested),
            ("details", "alert", "Error details", self.show_error_requested),
            ("open", "external", "Open file", self.open_file_requested),
            ("folder", "folder", "Show in folder", self.open_folder_requested),
            ("library", "library", "View in library", self.reveal_in_library_requested),
            ("cancel", "close", "Cancel", self.cancel_requested),
            ("remove", "trash", "Remove from queue", self.remove_requested),
        ):
            btn = icon_button(icon, tooltip=tooltip, size=14, tone="muted")
            btn.clicked.connect(lambda _=False, s=signal: s.emit(self.task.id))
            btn.hide()
            self._actions_layout.addWidget(btn)
            self._buttons[key] = btn

        self.update_from_task(task)

    # ------------------------------------------------------------------

    def update_from_task(self, task: DownloadTask | None = None) -> None:
        """Re-render every mutable part of the row."""
        if task is not None:
            self.task = task
        task = self.task
        theme = get_theme()

        self.title.setText(task.display_title)
        self.format_badge.setText(task.options.quality_label())
        self.category_badge.setText(task.options.category)

        if task.info and task.info.thumbnail_path:
            self.thumb.set_source(task.info.thumbnail_path, max_edge=200)

        self._progress_fraction = self._fraction()
        self.status_label.setText(self._status_text())
        if theme is not None:
            colour = status_color(theme.palette, task.status.value)
            self.status_label.setStyleSheet(
                f"color: {colour if task.status != DownloadStatus.QUEUED else theme.palette.text_muted};"
                f" font-size: 12px;"
            )
        self.metrics.setText(self._metrics_text())
        self._sync_actions()
        self.update()

    def _fraction(self) -> float:
        task = self.task
        if task.status == DownloadStatus.COMPLETE:
            return 1.0
        if task.status in (DownloadStatus.PROCESSING, DownloadStatus.ORGANIZING):
            return max(0.97, task.progress.percent / 100.0)
        return task.progress.percent / 100.0

    def _status_text(self) -> str:
        task = self.task
        status = task.status
        platform = task.platform

        if status == DownloadStatus.FAILED:
            return task.error or "Download failed"
        if status == DownloadStatus.COMPLETE:
            return f"Added to {task.options.category}" if task.media_id else "Complete"
        if status == DownloadStatus.CANCELLED:
            return "Cancelled"
        if status == DownloadStatus.PAUSED:
            return "Paused"
        if status in (DownloadStatus.PROCESSING, DownloadStatus.ORGANIZING):
            return task.stage_note or status.value
        if status == DownloadStatus.ANALYZING:
            return task.stage_note or "Reading metadata"
        if status == DownloadStatus.DOWNLOADING:
            percent = task.progress.percent
            prefix = f"{percent:.0f}%" if percent else "Starting"
            return f"{prefix}  ·  {platform}" if platform else prefix
        return f"Queued  ·  {platform}" if platform else "Queued"

    def _metrics_text(self) -> str:
        task = self.task
        progress = task.progress
        status = task.status

        if status == DownloadStatus.DOWNLOADING:
            parts = []
            if progress.total_bytes:
                parts.append(
                    f"{format_bytes(progress.downloaded_bytes)} / {format_bytes(progress.total_bytes)}"
                )
            elif progress.downloaded_bytes:
                parts.append(format_bytes(progress.downloaded_bytes))
            tail = []
            if progress.speed:
                tail.append(format_speed(progress.speed))
            if progress.eta:
                tail.append(format_eta(progress.eta))
            if tail:
                parts.append("  ·  ".join(tail))
            return "\n".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
        if status == DownloadStatus.COMPLETE and progress.total_bytes:
            return format_bytes(progress.total_bytes)
        return ""

    def _sync_actions(self) -> None:
        status = self.task.status
        visible: set = set()

        if status in (DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED, DownloadStatus.ANALYZING):
            visible |= {"pause", "cancel"}
        elif status == DownloadStatus.PAUSED:
            visible |= {"resume", "cancel"}
        elif status in (DownloadStatus.PROCESSING, DownloadStatus.ORGANIZING):
            visible |= {"cancel"}
        elif status == DownloadStatus.COMPLETE:
            visible |= {"open", "folder", "remove"}
            if self.task.media_id:
                visible.add("library")
        elif status == DownloadStatus.FAILED:
            visible |= {"retry", "details", "remove"}
        elif status == DownloadStatus.CANCELLED:
            visible |= {"retry", "remove"}

        for key, btn in self._buttons.items():
            btn.setVisible(key in visible)

    # -- Painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        theme = get_theme()
        if theme is None:
            return
        status = self.task.status
        if status in (DownloadStatus.CANCELLED,) or self._progress_fraction <= 0:
            return

        palette = theme.palette
        colour = {
            DownloadStatus.COMPLETE: palette.success,
            DownloadStatus.FAILED: palette.danger,
            DownloadStatus.PAUSED: palette.text_muted,
            DownloadStatus.PROCESSING: palette.warning,
            DownloadStatus.ORGANIZING: palette.warning,
        }.get(status, palette.accent)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        width = self.width() * max(0.0, min(1.0, self._progress_fraction))
        painter.fillRect(
            QRectF(0, self.height() - 2, width, 2), QColor(colour)
        )
        painter.end()
