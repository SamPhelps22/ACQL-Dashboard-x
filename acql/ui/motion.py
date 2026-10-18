"""The window's one piece of motion: a page fades in when it is switched to.

Brief (tokens.MOTION_MS), never in the way - the page is there and usable
from the first frame - and off entirely when Windows' own animations are
off (Settings > Accessibility > Visual effects), the desktop's version of
the website's prefers-reduced-motion.
"""

from __future__ import annotations

import sys
from functools import lru_cache

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

from .tokens import MOTION_MS

FADE_MS = int(MOTION_MS * 1.2)


@lru_cache(maxsize=1)
def reduced() -> bool:
    """True when the computer asks for less motion."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        on = ctypes.c_int(1)
        SPI_GETCLIENTAREAANIMATION = 0x1042
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(on), 0)
        return not on.value
    except Exception:       # noqa: BLE001 - motion is a nicety; never fail over it
        return False


def fade_in(widget: QWidget) -> None:
    """Fade `widget` from faint to solid, then take the effect off again
    (an opacity effect left in place makes every later paint slower)."""
    if reduced() or not widget.isVisible():
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.35)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(FADE_MS)
    anim.setStartValue(0.35)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def fade_stack(stack: QStackedWidget) -> None:
    """Fade in whichever page `stack` switches to."""
    stack.currentChanged.connect(lambda _i: fade_in(stack.currentWidget()))
