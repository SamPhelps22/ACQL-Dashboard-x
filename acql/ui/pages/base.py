"""Shared page scaffolding."""

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ...models import Season
from ..theme import Palette


class Page(QWidget):
    """A dashboard page.

    Subclasses build their widgets once in `build()` and refill them in
    `refresh()`, so switching pages never rebuilds the whole tree.
    """

    title = "Page"
    subtitle = ""
    icon = ""

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette = palette
        self.season: Season | None = None
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._content = QWidget()
        self.layout_ = QVBoxLayout(self._content)
        self.layout_.setContentsMargins(22, 18, 22, 22)
        self.layout_.setSpacing(14)
        scroll.setWidget(self._content)
        self._outer.addWidget(scroll)

        self.build()

    def build(self) -> None:
        """Create the widgets. Called once."""

    def refresh(self) -> None:
        """Repopulate from self.season. Called whenever data changes."""

    def set_season(self, season: Season) -> None:
        self.season = season
        self.refresh()

    # ---- formatting helpers shared by pages ---------------------------
    @staticmethod
    def money(value: float) -> str:
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value):,.2f}"

    @staticmethod
    def pct(value: float) -> str:
        return f"{value * 100:.1f}%"
