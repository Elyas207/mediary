"""Motion primitives.

Every animation in Mediary comes from here so timing and easing stay coherent.
The rules the durations encode:

* Nothing the user is waiting on is ever animated. Motion decorates a result,
  it never delays one.
* Hover and press feedback is 90-140ms - fast enough to feel like the widget
  responded, not like it is playing an animation at you.
* Things entering the screen take 180-260ms and ease out, so they decelerate
  into place.
* Nothing loops or pulses except a genuine indeterminate progress state.

All of it can be switched off: some people find motion distracting, and some
find it nauseating. ``set_reduce_motion(True)`` makes every helper here jump
straight to the final value instead of animating.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


class Duration:
    """Milliseconds. Named for intent rather than for length."""

    instant = 0
    micro = 90       # press states
    fast = 140       # hover, colour shifts
    normal = 200     # panels, cards, most entrances
    slow = 280       # view transitions, dialogs
    lazy = 420       # deliberate, once-per-session flourishes


class Easing:
    """Curves chosen for what they communicate, not for novelty."""

    #: Entering: decelerate into place.
    enter = QEasingCurve.Type.OutCubic
    #: Leaving: accelerate away.
    exit = QEasingCurve.Type.InCubic
    #: Moving between two on-screen states.
    move = QEasingCurve.Type.InOutCubic
    #: A small overshoot, for things that should feel physical (a toast, a
    #: newly added card). Used sparingly - it reads as playful once and as
    #: annoying by the tenth time.
    spring = QEasingCurve.Type.OutBack
    #: Emphasis without overshoot.
    emphasis = QEasingCurve.Type.OutQuint


_reduce_motion = False


def set_reduce_motion(value: bool) -> None:
    global _reduce_motion
    _reduce_motion = bool(value)


def reduce_motion() -> bool:
    return _reduce_motion


def _finish_immediately(animation: QPropertyAnimation) -> None:
    """Apply an animation's end value without playing it."""
    animation.setDuration(0)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def animate(
    target,
    prop: bytes,
    end,
    *,
    start=None,
    duration: int = Duration.normal,
    easing=Easing.enter,
    delay: int = 0,
    on_finished=None,
    owner=None,
) -> QPropertyAnimation:
    """Animate one Qt property.

    The animation is parented to its target, which is not optional. Without a
    parent, nothing holds a reference once this function returns, Python
    collects the wrapper, and Qt destroys the animation mid-flight - leaving
    the widget frozen at its *start* value. For a fade-in that means permanently
    invisible.
    """
    # ``owner`` lets the caller keep the animation alive somewhere other than
    # the target - needed when the target is a graphics effect that gets torn
    # down the moment the animation ends.
    animation = QPropertyAnimation(target, prop, owner if owner is not None else target)
    animation.setDuration(0 if _reduce_motion else duration)
    animation.setEasingCurve(easing)
    if start is not None:
        animation.setStartValue(start)
    animation.setEndValue(end)
    if on_finished is not None:
        animation.finished.connect(on_finished)

    if delay and not _reduce_motion:
        QTimer.singleShot(
            delay,
            lambda: animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped),
        )
    else:
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


# ---------------------------------------------------------------------------
# Opacity
# ---------------------------------------------------------------------------


def _opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
    """Reuse an existing opacity effect rather than stacking new ones.

    A widget can only hold one QGraphicsEffect, so replacing one that is
    already there (a drop shadow, say) would silently remove it.
    """
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        return effect
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    return effect


def fade_in(
    widget: QWidget,
    *,
    duration: int = Duration.normal,
    delay: int = 0,
    on_finished=None,
) -> None:
    """Fade a widget in, then take the effect back off.

    Removing the effect afterwards is not tidiness, it is required. A widget
    carrying a QGraphicsOpacityEffect is rendered into an offscreen pixmap for
    as long as the effect is installed, and on a scroll area that leaves the
    viewport blank even at full opacity. Fade, then get out of the way.
    """
    widget.show()
    if _reduce_motion:
        if on_finished:
            on_finished()
        return

    effect = _opacity_effect(widget)
    effect.setOpacity(0.0)

    def done() -> None:
        _clear_opacity_effect(widget)
        if on_finished:
            on_finished()

    animate(
        effect, b"opacity", 1.0,
        start=0.0, duration=duration, easing=Easing.enter, delay=delay,
        on_finished=done, owner=widget,
    )


def _clear_opacity_effect(widget: QWidget) -> None:
    """Detach a fade's opacity effect and restore normal painting."""
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        effect.setOpacity(1.0)
        # Deferred: this runs from the animation's finished signal, and the
        # animation is a child of the widget, not of the effect being dropped.
        QTimer.singleShot(0, lambda: _detach(widget, effect))


def _detach(widget: QWidget, effect) -> None:
    try:
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
    except RuntimeError:
        # The widget went away first; nothing to restore.
        pass


def fade_out(widget: QWidget, *, duration: int = Duration.fast, hide: bool = True) -> None:
    if _reduce_motion:
        if hide:
            widget.hide()
        return

    effect = _opacity_effect(widget)

    def done() -> None:
        if hide:
            widget.hide()
        _clear_opacity_effect(widget)

    animate(
        effect, b"opacity", 0.0,
        start=effect.opacity(), duration=duration, easing=Easing.exit,
        on_finished=done, owner=widget,
    )


def fade_to(widget: QWidget, opacity: float, *, duration: int = Duration.fast) -> None:
    """Fade to a partial opacity, e.g. dimming a disabled row."""
    effect = _opacity_effect(widget)
    if _reduce_motion:
        effect.setOpacity(opacity)
        return
    animate(effect, b"opacity", opacity, start=effect.opacity(), duration=duration, owner=widget)


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------


def slide_in(
    widget: QWidget,
    *,
    offset: QPoint | None = None,
    duration: int = Duration.normal,
    easing=Easing.enter,
    fade: bool = True,
) -> None:
    """Slide a widget in from a nearby offset.

    Only for widgets you position yourself - toasts, popovers, overlays. A
    layout owns the geometry of its children, so animating ``pos`` on one of
    them fights the layout and loses.
    """
    widget.show()
    if _reduce_motion:
        return

    end = widget.pos()
    start = end + (offset if offset is not None else QPoint(0, 12))
    widget.move(start)
    animate(widget, b"pos", end, start=start, duration=duration, easing=easing)
    if fade:
        fade_in(widget, duration=duration)


def slide_to(
    widget: QWidget,
    position: QPoint,
    *,
    duration: int = Duration.normal,
    easing=Easing.move,
) -> None:
    animate(widget, b"pos", position, start=widget.pos(), duration=duration, easing=easing)


def grow_height(
    widget: QWidget,
    end_height: int,
    *,
    duration: int = Duration.normal,
    easing=Easing.move,
    on_finished=None,
) -> None:
    """Animate maximumHeight, for expanding and collapsing panels."""
    if _reduce_motion:
        widget.setMaximumHeight(end_height)
        if on_finished:
            on_finished()
        return
    animate(
        widget, b"maximumHeight", end_height,
        start=widget.height(), duration=duration, easing=easing, on_finished=on_finished,
    )


def geometry_to(
    widget: QWidget,
    rect: QRect,
    *,
    duration: int = Duration.normal,
    easing=Easing.move,
) -> None:
    animate(widget, b"geometry", rect, start=widget.geometry(), duration=duration, easing=easing)


# ---------------------------------------------------------------------------
# Composed effects
# ---------------------------------------------------------------------------


def pop_in(widget: QWidget, *, duration: int = Duration.normal, delay: int = 0) -> None:
    """Fade a widget in where it already sits.

    Deliberately opacity-only. An earlier version also animated ``pos`` to make
    the widget rise into place, which is wrong for anything inside a layout:
    the layout owns child geometry, ``pos()`` is still stale when a freshly
    populated grid is measured, and the animation then fights the layout and
    strands every card in the corner.

    Use :func:`slide_in` for widgets you position yourself.
    """
    widget.show()
    if _reduce_motion:
        return
    fade_in(widget, duration=duration, delay=delay)


def stagger(widgets, action, *, step: int = 26, cap: int = 12) -> None:
    """Run ``action(widget, delay)`` across a list with increasing delays.

    Capped deliberately: staggering forty cards means the last one appears most
    of a second late, which stops reading as polish and starts reading as lag.
    """
    for index, widget in enumerate(widgets):
        delay = 0 if _reduce_motion else min(index, cap) * step
        action(widget, delay)


def parallel(*animations) -> QParallelAnimationGroup:
    group = QParallelAnimationGroup()
    for animation in animations:
        group.addAnimation(animation)
    group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return group


def shake(widget: QWidget, *, distance: int = 6) -> None:
    """A short horizontal shake, for a rejected input.

    The one place a negative animation earns its keep: it says "that did not
    work" faster than any text can.
    """
    if _reduce_motion:
        return
    origin = widget.pos()
    animation = QPropertyAnimation(widget, b"pos", widget)
    animation.setDuration(Duration.slow)
    animation.setEasingCurve(QEasingCurve.Type.Linear)
    for step, factor in enumerate((0.0, -1.0, 0.8, -0.5, 0.25, 0.0)):
        animation.setKeyValueAt(step / 5, origin + QPoint(int(distance * factor), 0))
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


__all__ = [
    "Duration",
    "Easing",
    "animate",
    "fade_in",
    "fade_out",
    "fade_to",
    "geometry_to",
    "grow_height",
    "parallel",
    "pop_in",
    "reduce_motion",
    "set_reduce_motion",
    "shake",
    "slide_in",
    "slide_to",
    "stagger",
    "Qt",
]
