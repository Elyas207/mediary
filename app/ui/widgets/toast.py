"""Transient confirmations, anchored to the bottom-right of the main window."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QWidget

from app.ui.theme import Space, get_theme
from app.ui.widgets.common import ElidedLabel, apply_shadow, button, hbox, icon_button, vbox


class Toast(QFrame):
    """A single self-dismissing message card."""

    closed = Signal(object)

    def __init__(
        self,
        message: str,
        *,
        tone: str = "info",
        title: str = "",
        action_text: str = "",
        on_action=None,
        duration_ms: int = 4200,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(340)

        layout = hbox(self, spacing=Space.md, margins=(Space.md, Space.md, Space.sm, Space.md))

        theme = get_theme()
        if theme is not None:
            glyph = QLabel(self)
            glyph.setPixmap(
                theme.pixmap(
                    {
                        "info": "info",
                        "success": "check-circle",
                        "warning": "alert",
                        "danger": "x-circle",
                    }.get(tone, "info"),
                    16,
                    {"info": "accent", "success": "success",
                     "warning": "warning", "danger": "danger"}.get(tone, "accent"),
                )
            )
            glyph.setFixedSize(16, 16)
            layout.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        column = vbox(spacing=2)
        if title:
            heading = ElidedLabel(title, "itemTitle", parent=self)
            column.addWidget(heading)
        body = QLabel(message, self)
        body.setWordWrap(True)
        body.setProperty("role", "meta" if title else "")
        column.addWidget(body)

        if action_text and on_action is not None:
            action = button(action_text, variant="link", on_click=on_action)
            column.addWidget(action)

        layout.addLayout(column, 1)

        close = icon_button("close", tooltip="Dismiss", size=12, tone="muted")
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        apply_shadow(self, blur=32, y_offset=10)

        self._opacity = QGraphicsOpacityEffect(self)
        # A drop shadow and an opacity effect cannot both own the widget, so the
        # fade animates the window opacity of the shadowed frame instead.
        self._opacity.setOpacity(1.0)

        if duration_ms > 0:
            QTimer.singleShot(duration_ms, self.dismiss)

    def dismiss(self) -> None:
        self.closed.emit(self)
        self.hide()
        self.deleteLater()


class ToastHost(QWidget):
    """Stacks toasts in the bottom-right corner of its parent."""

    MARGIN = 20
    GAP = Space.sm
    MAX_VISIBLE = 4

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._toasts: list = []
        parent.installEventFilter(self)
        self.hide()

    def show_toast(
        self,
        message: str,
        *,
        tone: str = "info",
        title: str = "",
        action_text: str = "",
        on_action=None,
        duration_ms: int = 4200,
    ) -> Toast:
        toast = Toast(
            message,
            tone=tone,
            title=title,
            action_text=action_text,
            on_action=on_action,
            duration_ms=duration_ms,
            parent=self.parentWidget(),
        )
        toast.closed.connect(self._remove)
        self._toasts.append(toast)
        while len(self._toasts) > self.MAX_VISIBLE:
            oldest = self._toasts[0]
            oldest.dismiss()
        toast.show()
        toast.raise_()
        self._reflow()
        self._animate_in(toast)
        return toast

    def _animate_in(self, toast: Toast) -> None:
        end = toast.pos()
        start = QPoint(end.x() + 24, end.y())
        animation = QPropertyAnimation(toast, b"pos", toast)
        animation.setDuration(180)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reflow()

    def _reflow(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        y = parent.height() - self.MARGIN
        for toast in reversed(self._toasts):
            height = toast.sizeHint().height()
            toast.resize(toast.width(), height)
            y -= height
            toast.move(parent.width() - toast.width() - self.MARGIN, y)
            toast.raise_()
            y -= self.GAP

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        from PySide6.QtCore import QEvent

        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._reflow()
        return super().eventFilter(watched, event)

    def clear(self) -> None:
        for toast in list(self._toasts):
            toast.dismiss()
