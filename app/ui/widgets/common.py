"""Reusable Mediary components.

Every screen is assembled from these, so spacing, type and interaction states
stay identical across the app rather than being re-invented per view.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import Size, Space, get_theme

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def label(
    text: str = "",
    role: str = "",
    *,
    wrap: bool = False,
    elide: bool = False,
    parent: QWidget | None = None,
) -> QLabel:
    """A :class:`QLabel` carrying a design-system ``role`` property."""
    widget = QLabel(text, parent)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    if elide:
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return widget


def selectable_label(text: str = "", role: str = "", *, wrap: bool = True) -> QLabel:
    """A label whose text the user can select and copy."""
    widget = label(text, role, wrap=wrap)
    widget.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    widget.setCursor(Qt.CursorShape.IBeamCursor)
    return widget


class ElidedLabel(QLabel):
    """A label that truncates with an ellipsis instead of forcing a wider layout."""

    def __init__(
        self,
        text: str = "",
        role: str = "",
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full_text = text
        self._mode = mode
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full_text = text or ""
        self.setToolTip(self._full_text if len(self._full_text) > 24 else "")
        super().setText(self._elided())

    def fullText(self) -> str:  # noqa: N802 - Qt naming
        return self._full_text

    def _elided(self) -> str:
        metrics = self.fontMetrics()
        width = max(0, self.width() - 2)
        if width <= 0:
            return self._full_text
        return metrics.elidedText(self._full_text, self._mode, width)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        super().setText(self._elided())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        hint = super().minimumSizeHint()
        return QSize(24, hint.height())


class WrappedLabel(QLabel):
    """A fixed-width word-wrapped label that reports its true height.

    A plain ``QLabel`` with ``wordWrap`` returns a *single-line* ``sizeHint``,
    so any layout that sizes to the hint clips the last line of a paragraph.
    Measuring in ``sizeHint`` (rather than once at construction) also means the
    stylesheet's font is already in effect by the time it matters.
    """

    def __init__(
        self,
        text: str = "",
        role: str = "",
        width: int = 400,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        if role:
            self.setProperty("role", role)
        self.setWordWrap(True)
        self._wrap_width = width
        self.setFixedWidth(width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

    def set_wrap_width(self, width: int) -> None:
        self._wrap_width = max(80, int(width))
        self.setFixedWidth(self._wrap_width)
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        from PySide6.QtCore import QRect

        metrics = self.fontMetrics()
        rect = metrics.boundingRect(
            QRect(0, 0, max(1, width), 100_000),
            int(Qt.TextFlag.TextWordWrap),
            self.text(),
        )
        return max(metrics.height(), rect.height())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(self._wrap_width, self.heightForWidth(self._wrap_width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.sizeHint()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        super().setText(text)
        self.updateGeometry()


class SectionLabel(QLabel):
    """A small uppercase group heading, as used in the sidebar and inspector."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setProperty("role", "sectionLabel")


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def divider(vertical: bool = False, parent: QWidget | None = None) -> QFrame:
    line = QFrame(parent)
    line.setObjectName("VDivider" if vertical else "Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    if vertical:
        line.setFixedWidth(1)
        line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    else:
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return line


def spacer(width: int = 0, height: int = 0) -> QWidget:
    widget = QWidget()
    widget.setFixedSize(QSize(width, height))
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return widget


def stretch_spacer() -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return widget


def hbox(
    parent: QWidget | None = None,
    *,
    spacing: int = Space.sm,
    margins: tuple = (0, 0, 0, 0),
) -> QHBoxLayout:
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def vbox(
    parent: QWidget | None = None,
    *,
    spacing: int = Space.sm,
    margins: tuple = (0, 0, 0, 0),
) -> QVBoxLayout:
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def panel(*, inset: bool = False, parent: QWidget | None = None) -> QFrame:
    frame = QFrame(parent)
    frame.setObjectName("InsetPanel" if inset else "Panel")
    return frame


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------


def button(
    text: str = "",
    *,
    variant: str = "",
    size: str = "",
    icon: str = "",
    icon_tone: str = "",
    on_click: Callable | None = None,
    tooltip: str = "",
    parent: QWidget | None = None,
) -> QPushButton:
    """A styled :class:`QPushButton`. ``variant`` maps to the stylesheet."""
    widget = QPushButton(text, parent)
    if variant:
        widget.setProperty("variant", variant)
    if size:
        widget.setProperty("size", size)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon:
        theme = get_theme()
        if theme is not None:
            tone = icon_tone or ("inverted" if variant in ("primary", "danger") else "secondary")
            widget.setIcon(theme.icon(icon, Size.icon_sm, tone))
            widget.setIconSize(QSize(Size.icon_sm, Size.icon_sm))
    if tooltip:
        widget.setToolTip(tooltip)
    if on_click is not None:
        widget.clicked.connect(on_click)
    return widget


def icon_button(
    name: str,
    *,
    tooltip: str = "",
    size: int = Size.icon,
    tone: str = "secondary",
    checkable: bool = False,
    on_click: Callable | None = None,
    parent: QWidget | None = None,
) -> QToolButton:
    """A compact icon-only action button."""
    widget = QToolButton(parent)
    widget.setAutoRaise(True)
    widget.setCheckable(checkable)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setIconSize(QSize(size, size))
    widget.setFixedSize(QSize(size + 12, size + 12))
    widget.setProperty("iconName", name)
    widget.setProperty("iconTone", tone)
    theme = get_theme()
    if theme is not None:
        widget.setIcon(theme.icon(name, size, tone))
    if tooltip:
        widget.setToolTip(tooltip)
    if on_click is not None:
        widget.clicked.connect(on_click)
    return widget


def refresh_icon_button(widget: QToolButton) -> None:
    """Re-render an icon button after a theme change."""
    theme = get_theme()
    if theme is None:
        return
    name = widget.property("iconName")
    tone = widget.property("iconTone") or "secondary"
    if name:
        widget.setIcon(theme.icon(name, widget.iconSize().width(), tone))


# ---------------------------------------------------------------------------
# Chips and badges
# ---------------------------------------------------------------------------


class Chip(QPushButton):
    """A small filter pill, as used above the library grid."""

    def __init__(
        self,
        text: str,
        *,
        checkable: bool = True,
        value=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.value = value if value is not None else text
        self.toggled.connect(self._sync)
        self._sync(self.isChecked())

    def _sync(self, checked: bool) -> None:
        self.setProperty("active", "true" if checked else "false")
        _repolish(self)


class Badge(QLabel):
    """A tiny status pill: ``MP3``, ``1080p``, ``Missing``."""

    HEIGHT = 18

    def __init__(self, text: str, tone: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Badge")
        if tone:
            self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A badge must never stretch to its container's height; in a tall row
        # it would render as a large filled block instead of a pill.
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        _repolish(self)


class TagChip(QFrame):
    """A tag pill with an optional remove affordance."""

    removed = Signal(str)
    clicked = Signal(str)

    def __init__(
        self,
        name: str,
        *,
        removable: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TagChip")
        self.name = name
        layout = hbox(self, spacing=Space.xs, margins=(Space.sm, 2, Space.xs if removable else Space.sm, 2))

        self._label = QLabel(name, self)
        self._label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._label)

        if removable:
            close = QToolButton(self)
            close.setAutoRaise(True)
            close.setCursor(Qt.CursorShape.PointingHandCursor)
            close.setFixedSize(QSize(14, 14))
            close.setIconSize(QSize(9, 9))
            theme = get_theme()
            if theme is not None:
                close.setIcon(theme.icon("close", 9, "accent"))
            close.setToolTip(f"Remove {name}")
            close.clicked.connect(lambda: self.removed.emit(self.name))
            layout.addWidget(close)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)


class CategoryDot(QWidget):
    """A 7px colour dot identifying a category at a glance."""

    def __init__(self, color: str = "#7A8090", size: int = 7, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(QSize(size, size))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())
        painter.end()


# ---------------------------------------------------------------------------
# Segmented control
# ---------------------------------------------------------------------------


class SegmentedControl(QFrame):
    """An exclusive inline switch, e.g. Grid / List or Video / Audio."""

    changed = Signal(object)   # the selected value

    def __init__(self, options: list, *, parent: QWidget | None = None) -> None:
        """``options`` is a list of ``(value, label)`` or ``(value, label, icon)``."""
        super().__init__(parent)
        self.setObjectName("SegmentedControl")
        self._layout = hbox(self, spacing=2, margins=(2, 2, 2, 2))
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict = {}

        theme = get_theme()
        for entry in options:
            value, text = entry[0], entry[1]
            icon_name = entry[2] if len(entry) > 2 else ""
            btn = QPushButton(text, self)
            btn.setObjectName("SegmentButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if icon_name and theme is not None:
                btn.setIcon(theme.icon(icon_name, Size.icon_sm, "secondary"))
                btn.setIconSize(QSize(Size.icon_sm, Size.icon_sm))
                if not text:
                    btn.setFixedWidth(30)
            btn.clicked.connect(lambda _=False, v=value: self._select(v))
            self._group.addButton(btn)
            self._layout.addWidget(btn)
            self._buttons[value] = btn

        if self._buttons:
            first = next(iter(self._buttons.values()))
            first.setChecked(True)

    def _select(self, value) -> None:
        self.changed.emit(value)

    def set_value(self, value, *, emit: bool = False) -> None:
        btn = self._buttons.get(value)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        if emit:
            self.changed.emit(value)

    def value(self):
        for value, btn in self._buttons.items():
            if btn.isChecked():
                return value
        return None

    def set_option_visible(self, value, visible: bool) -> None:
        btn = self._buttons.get(value)
        if btn is not None:
            btn.setVisible(visible)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchInput(QLineEdit):
    """A search field with an inline leading icon and clear affordance."""

    def __init__(self, placeholder: str = "Search", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "search")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self._icon_pixmap = None
        self.refresh_icon()

    def refresh_icon(self) -> None:
        theme = get_theme()
        if theme is None:
            return
        self._icon_pixmap = theme.pixmap("search", 14, "muted")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        if self._icon_pixmap is None:
            return
        painter = QPainter(self)
        ratio = self._icon_pixmap.devicePixelRatio() or 1.0
        width = self._icon_pixmap.width() / ratio
        height = self._icon_pixmap.height() / ratio
        y = int((self.height() - height) / 2)
        painter.drawPixmap(QPoint(11, y), self._icon_pixmap)
        painter.end()
        _ = width  # kept for clarity of the centring maths


# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------


class EmptyState(QWidget):
    """A centred icon + headline + body + optional action."""

    #: Measure for the wrapped copy. Narrow enough to stay readable, wide
    #: enough that two short sentences do not become five lines.
    TEXT_WIDTH = 420

    def __init__(
        self,
        *,
        icon: str = "inbox",
        title: str = "",
        body: str = "",
        action_text: str = "",
        on_action: Callable | None = None,
        secondary_text: str = "",
        on_secondary: Callable | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        outer = vbox(self, spacing=0, margins=(Space.x3l, Space.x3l, Space.x3l, Space.x3l))
        outer.addStretch(1)

        holder = QWidget(self)
        layout = vbox(holder, spacing=0)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        theme = get_theme()
        if theme is not None:
            badge = QLabel(holder)
            badge.setObjectName("EmptyStateIcon")
            badge.setFixedSize(QSize(56, 56))
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setPixmap(theme.pixmap(icon, 24, "muted"))
            layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addSpacing(Space.xl)

        self._title = WrappedLabel(title, "heroTitle", self.TEXT_WIDTH, holder)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("font-size: 19px;")
        layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignHCenter)

        self._body = None
        if body:
            layout.addSpacing(Space.sm)
            self._body = WrappedLabel(body, "heroBody", self.TEXT_WIDTH, holder)
            self._body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._body, 0, Qt.AlignmentFlag.AlignHCenter)

        if action_text or secondary_text:
            layout.addSpacing(Space.xl)
            row = QWidget(holder)
            row_layout = hbox(row, spacing=Space.sm)
            row_layout.addStretch(1)
            if action_text:
                primary = button(action_text, variant="primary", on_click=on_action)
                row_layout.addWidget(primary)
            if secondary_text:
                secondary = button(secondary_text, variant="subtle", on_click=on_secondary)
                row_layout.addWidget(secondary)
            row_layout.addStretch(1)
            layout.addWidget(row)

        outer.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def set_text(self, title: str, body: str = "") -> None:
        self._title.setText(title)
        if body and self._body is not None:
            self._body.setText(body)
        self.updateGeometry()


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------


class Notice(QFrame):
    """An inline, dismissible message strip."""

    dismissed = Signal()
    action_clicked = Signal()

    def __init__(
        self,
        message: str,
        *,
        tone: str = "info",
        title: str = "",
        action_text: str = "",
        dismissible: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Notice")
        self.setProperty("tone", tone)
        layout = hbox(self, spacing=Space.md, margins=(Space.md, Space.md, Space.md, Space.md))

        theme = get_theme()
        if theme is not None:
            icon_name = {
                "info": "info",
                "success": "check-circle",
                "warning": "alert",
                "danger": "x-circle",
            }.get(tone, "info")
            glyph = QLabel(self)
            glyph.setPixmap(theme.pixmap(icon_name, 16, tone if tone != "info" else "accent"))
            glyph.setFixedWidth(16)
            layout.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        text_column = vbox(spacing=2)
        if title:
            text_column.addWidget(label(title, "itemTitle", wrap=True))
        self._message = label(message, "meta" if title else "", wrap=True)
        text_column.addWidget(self._message)
        layout.addLayout(text_column, 1)

        if action_text:
            action = button(action_text, variant="link", on_click=self.action_clicked.emit)
            layout.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)

        if dismissible:
            close = icon_button("close", tooltip="Dismiss", size=12, tone="muted")
            close.clicked.connect(self._dismiss)
            layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

    def _dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()

    def set_message(self, message: str) -> None:
        self._message.setText(message)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


class FlowLayout(QLayout):
    """A left-to-right wrapping layout, used for tag and filter chips."""

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        h_spacing: int = Space.xs,
        v_spacing: int = Space.xs,
    ) -> None:
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item) -> None:  # noqa: N802 - Qt naming
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt naming
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802 - Qt naming
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802 - Qt naming
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return self._layout(QSize(width, 0), apply=False)

    def setGeometry(self, rect) -> None:  # noqa: N802 - Qt naming
        super().setGeometry(rect)
        self._layout(rect.size(), apply=True, origin=rect.topLeft())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt naming
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def clear(self) -> None:
        while self._items:
            item = self._items.pop()
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _layout(self, size: QSize, *, apply: bool, origin: QPoint | None = None) -> int:
        margins = self.contentsMargins()
        origin = origin or QPoint(0, 0)
        x = origin.x() + margins.left()
        y = origin.y() + margins.top()
        line_height = 0
        right = origin.x() + size.width() - margins.right()

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > right and line_height > 0:
                x = origin.x() + margins.left()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if apply:
                from PySide6.QtCore import QRect

                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - origin.y() + margins.bottom()


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def _repolish(widget: QWidget) -> None:
    """Force Qt to re-evaluate the stylesheet after a dynamic property change."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def repolish(widget: QWidget) -> None:
    _repolish(widget)


def set_property(widget: QWidget, name: str, value) -> None:
    """Set a dynamic property and immediately restyle the widget."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    _repolish(widget)


def apply_shadow(
    widget: QWidget,
    *,
    blur: int = 28,
    y_offset: int = 8,
    color: str = "rgba(0,0,0,90)",
) -> None:
    """A soft elevation shadow for modals and popovers."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(y_offset)
    effect.setColor(QColor(0, 0, 0, 90) if color.startswith("rgba") else QColor(color))
    widget.setGraphicsEffect(effect)


def monospace_font(size: int = 12) -> QFont:
    from app.ui.theme.tokens import mono_stack

    family = mono_stack().split(",")[0].strip().strip('"')
    font = QFont(family, -1)
    font.setPixelSize(size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


class HoverTracker(QWidget):
    """Mixin-style helper that repaints a widget on hover enter/leave."""

    hover_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    @property
    def hovered(self) -> bool:
        return self._hovered

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.HoverEnter:
            self._hovered = True
            self.hover_changed.emit(True)
            self.update()
        elif event.type() == QEvent.Type.HoverLeave:
            self._hovered = False
            self.hover_changed.emit(False)
            self.update()
        return super().event(event)


def draw_rounded_border(
    painter: QPainter,
    rect,
    radius: int,
    color: str,
    width: float = 1.0,
) -> None:
    """Crisp 1px rounded outline aligned to the pixel grid."""
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = width / 2.0
    painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), radius, radius)


__all__ = [
    "Badge",
    "CategoryDot",
    "Chip",
    "ElidedLabel",
    "EmptyState",
    "WrappedLabel",
    "FlowLayout",
    "HoverTracker",
    "Notice",
    "SearchInput",
    "SectionLabel",
    "SegmentedControl",
    "TagChip",
    "apply_shadow",
    "button",
    "divider",
    "draw_rounded_border",
    "hbox",
    "icon_button",
    "label",
    "monospace_font",
    "panel",
    "refresh_icon_button",
    "repolish",
    "selectable_label",
    "set_property",
    "spacer",
    "stretch_spacer",
    "vbox",
    "QAbstractButton",
    "QCursor",
]
