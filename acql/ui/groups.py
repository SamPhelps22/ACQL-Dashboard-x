"""The sidebar's seven places, each holding one page or a few as tabs.

Eleven pages side by side had grown up one request at a time, and several
answered the same question from different ends - Next Week and This Week
both priced the same games; Overview, Standings, Winnings and Projections
are four looks at one season. Grouped the way the week is actually lived:

    Season       where it stands: overview, standings, money, projections
    This Week    what to play: the card, and every game on the slate
    Results      how last week went, and the recap to send round
    Side Pools   Big Loser and the suicide pool
    Player       one coach's season
    Insights     the pool's habits and luck, and the model's own record
    Data         what is loaded, and entering results

Each page is unchanged inside; a group only adds a row of tabs above them.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QTabBar, QVBoxLayout, QWidget

from .pages.base import Page


@dataclass(frozen=True)
class GroupSpec:
    """One place in the sidebar."""

    title: str
    icon: str
    subtitle: str
    tabs: tuple[tuple[str, type], ...]      # (tab label, page class)

    @property
    def classes(self) -> tuple[type, ...]:
        return tuple(cls for _, cls in self.tabs)


class PageGroup(QWidget):
    """A stack of pages under a row of tabs (no tabs when there is only one)."""

    tab_changed = Signal(int)

    def __init__(self, spec: GroupSpec, pages: list[Page], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageGroup")
        self.spec = spec
        self.pages = list(pages)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs: QTabBar | None = None
        if len(self.pages) > 1:
            holder = QWidget()
            holder.setObjectName("GroupTabs")
            row = QVBoxLayout(holder)
            row.setContentsMargins(18, 8, 18, 0)
            row.setSpacing(0)
            self.tabs = QTabBar()
            self.tabs.setObjectName("GroupTabBar")
            self.tabs.setDrawBase(False)
            self.tabs.setExpanding(False)
            for (label, _), page in zip(spec.tabs, self.pages):
                index = self.tabs.addTab(label)
                self.tabs.setTabToolTip(index, page.subtitle or label)
            self.tabs.currentChanged.connect(self._on_tab)
            row.addWidget(self.tabs)
            layout.addWidget(holder)

        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

    # ---- what the window asks of it ----------------------------------------
    @property
    def title(self) -> str:
        return self.spec.title

    def current_index(self) -> int:
        return self.stack.currentIndex()

    def current_page(self) -> Page:
        return self.pages[max(0, self.stack.currentIndex())]

    def select(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            return
        if self.tabs is not None and self.tabs.currentIndex() != index:
            self.tabs.setCurrentIndex(index)       # -> _on_tab
        else:
            self.stack.setCurrentIndex(index)
            self.tab_changed.emit(index)

    def index_of(self, cls: type) -> int:
        for i, page in enumerate(self.pages):
            if isinstance(page, cls):
                return i
        return -1

    def _on_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.tab_changed.emit(index)
