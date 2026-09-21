"""Shared page scaffolding."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QFrame, QLayout, QScrollArea, QVBoxLayout, QWidget

from ...models import Season
from ..theme import Palette


class Page(QWidget):
    """A dashboard page.

    Subclasses build their widgets once in `build()` and refill them in
    `refresh()`, so switching pages never rebuilds the whole tree.

    Lifecycle
    ---------
    * `build()` runs once, from the base `__init__`. Because of that, a
      subclass must not rely on attributes it assigns *after* calling
      `super().__init__()`; read from `self.palette` and class attributes
      instead.
    * `set_season()` / `invalidate()` mark the page as stale. If the page
      is on screen it refreshes immediately; otherwise the refresh is
      deferred until the page is next shown. With a dozen pages, a data
      change then costs one refresh, not twelve.
    * `refresh()` is only ever called by the base class with `self.season`
      set, so subclasses don't need their own `None` guard. Call
      `refresh_now()` (not `refresh()`) from outside so the guard, the
      repaint batching and the stale flag all apply.
    * `restyle()` is called when the palette changes.
    """

    title: str = "Page"
    subtitle: str = ""
    icon: str = ""

    #: Defer refreshes on hidden pages until they are shown.
    lazy_refresh: bool = True
    #: Keep content top-aligned when a page is shorter than the window.
    stretch_bottom: bool = True
    #: Text shown for missing or non-finite numbers.
    NO_VALUE: str = "\u2014"

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette = palette
        self.season: Season | None = None
        self._dirty = False

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget()
        self.layout_ = QVBoxLayout(self._content)
        self.layout_.setContentsMargins(22, 18, 22, 22)
        self.layout_.setSpacing(14)
        self._scroll.setWidget(self._content)
        self._outer.addWidget(self._scroll)

        self.build()
        if self.stretch_bottom:
            self.layout_.addStretch(1)

    # ---- hooks for subclasses -----------------------------------------
    def build(self) -> None:
        """Create the widgets. Called once."""

    def refresh(self) -> None:
        """Repopulate from `self.season` (never None when called by Page)."""

    def restyle(self) -> None:
        """Re-apply palette-dependent styling. Called by `set_palette()`."""

    # ---- data flow -----------------------------------------------------
    def set_season(self, season: Season) -> None:
        self.season = season
        self.invalidate()

    def invalidate(self, *, eager: bool = False) -> None:
        """Mark the data as changed.

        Use this after mutating `self.season` in place. Refreshes right
        away if the page is visible (or `eager`/`lazy_refresh` says so),
        otherwise waits until the page is shown.
        """
        self._dirty = True
        if eager or not self.lazy_refresh or self.isVisible():
            self.refresh_now()

    def refresh_now(self) -> None:
        """Refresh immediately, batching repaints to avoid flicker."""
        if self.season is None:
            return
        self.setUpdatesEnabled(False)
        try:
            self.refresh()
        finally:
            self.setUpdatesEnabled(True)
        self._dirty = False

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.restyle()
        self.update()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        if self._dirty:
            self.refresh_now()

    def scroll_to_top(self) -> None:
        self._scroll.verticalScrollBar().setValue(0)

    # ---- layout helpers ------------------------------------------------
    @staticmethod
    def clear_layout(layout: QLayout) -> None:
        """Remove and delete everything in a layout, including nested ones."""
        while (item := layout.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                Page.clear_layout(child)
                child.deleteLater()

    # ---- formatting helpers shared by pages ---------------------------
    @staticmethod
    def _sign(value: float, signed: bool) -> str:
        if value < 0:
            return "-"
        return "+" if signed and value > 0 else ""

    @classmethod
    def money(cls, value: float | None, *, signed: bool = False) -> str:
        """Format as dollars, e.g. `$1,234.50`, `-$3.00`, or `+$3.00` if signed."""
        if value is None or not math.isfinite(value):
            return cls.NO_VALUE
        value = round(value, 2)  # round first so -0.004 becomes $0.00, not -$0.00
        return f"{cls._sign(value, signed)}${abs(value):,.2f}"

    @classmethod
    def pct(cls, value: float | None, digits: int = 1, *, signed: bool = False) -> str:
        """Format a 0-1 fraction as a percentage, e.g. `0.253` -> `25.3%`."""
        if value is None or not math.isfinite(value):
            return cls.NO_VALUE
        scaled = round(value * 100, digits)
        return f"{cls._sign(scaled, signed)}{abs(scaled):.{digits}f}%"