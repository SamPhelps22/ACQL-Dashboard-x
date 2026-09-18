"""Application shell: the window, the navigation and the data reload."""

from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..config import DATA_DIR, Settings
from ..models import Season
from ..names import AliasTable
from ..repository import load_season
from .pages.data import DataPage
from .pages.overview import OverviewPage
from .pages.player import PlayerPage
from .pages.pools import PoolsPage
from .pages.standings import StandingsPage
from .pages.weekly import WeeklyPage
from .pages.winnings import WinningsPage
from .theme import PALETTES, stylesheet

PAGE_CLASSES = (
    OverviewPage,
    StandingsPage,
    WeeklyPage,
    PlayerPage,
    WinningsPage,
    PoolsPage,
    DataPage,
)


class Loader(QThread):
    """Parses the spreadsheets off the UI thread so the window stays live."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def run(self) -> None:
        try:
            season = load_season(self.settings, AliasTable.load())
        except Exception:  # noqa: BLE001 - reported in the UI, never swallowed
            self.failed.emit(traceback.format_exc())
        else:
            self.finished_ok.emit(season)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.palette_ = PALETTES.get(self.settings.theme, PALETTES["dark"])
        self.season = Season(buy_in=self.settings.buy_in)
        self._loader: Loader | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(1440, 920)
        self.setMinimumSize(1060, 700)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.pages = []
        for index, cls in enumerate(PAGE_CLASSES):
            page = cls(self.palette_)
            self.pages.append(page)
            self.stack.addWidget(page)
            # "&" in a button label is a Qt mnemonic; double it to show it.
            button = QPushButton(f"  {cls.icon}   {cls.title}".replace("&", "&&"))
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _, i=index: self._show_page(i))
            self.nav_group.addButton(button, index)
            self.nav_layout.addWidget(button)
        self.nav_layout.addStretch(1)
        self._build_sidebar_footer()

        # The Data page asks the window to reload after a write.
        for page in self.pages:
            if isinstance(page, DataPage):
                page.refresh_requested.connect(self.reload)

        self.statusBar().showMessage("Loading…")
        self._build_shortcuts()
        self.apply_theme()
        self.nav_group.button(0).setChecked(True)
        self.reload()

    # ---- chrome ----------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(208)
        self.nav_layout = QVBoxLayout(self.sidebar)
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(1)

        self.brand = QLabel(APP_NAME)
        self.brand.setObjectName("SidebarTitle")
        self.season_label = QLabel("–")
        self.season_label.setObjectName("SidebarSubtitle")
        self.nav_layout.addWidget(self.brand)
        self.nav_layout.addWidget(self.season_label)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        return self.sidebar

    def _build_sidebar_footer(self) -> None:
        footer = QVBoxLayout()
        footer.setContentsMargins(10, 8, 10, 12)
        footer.setSpacing(6)
        self.refresh_btn = QPushButton("↻  Refresh")
        self.refresh_btn.setToolTip("Rescan the watched folders (F5)")
        self.refresh_btn.clicked.connect(self.reload)
        self.theme_btn = QPushButton("◐  Theme")
        self.theme_btn.setToolTip("Switch between light and dark")
        self.theme_btn.clicked.connect(self.toggle_theme)
        footer.addWidget(self.refresh_btn)
        footer.addWidget(self.theme_btn)
        version = QLabel(f"v{__version__}")
        version.setObjectName("SidebarSubtitle")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.addWidget(version)
        self.nav_layout.addLayout(footer)

    def _build_shortcuts(self) -> None:
        reload_action = QAction("Refresh", self)
        reload_action.setShortcut(QKeySequence("F5"))
        reload_action.triggered.connect(self.reload)
        self.addAction(reload_action)

        theme_action = QAction("Toggle theme", self)
        theme_action.setShortcut(QKeySequence("Ctrl+T"))
        theme_action.triggered.connect(self.toggle_theme)
        self.addAction(theme_action)

        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

        for i in range(len(PAGE_CLASSES)):
            action = QAction(f"Page {i + 1}", self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            action.triggered.connect(lambda _=False, idx=i: self._select_page(idx))
            self.addAction(action)

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def _select_page(self, index: int) -> None:
        button = self.nav_group.button(index)
        if button:
            button.setChecked(True)
            self._show_page(index)

    # ---- theme -----------------------------------------------------------
    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet(self.palette_))

    def toggle_theme(self) -> None:
        self.settings.theme = "light" if self.palette_.name == "dark" else "dark"
        self.settings.save()
        self.palette_ = PALETTES[self.settings.theme]
        self.apply_theme()
        # Charts bake their colours in at draw time, so rebuild the pages.
        current = self.stack.currentIndex()
        for i, cls in enumerate(PAGE_CLASSES):
            old = self.pages[i]
            page = cls(self.palette_)
            if isinstance(page, DataPage):
                page.refresh_requested.connect(self.reload)
            page.set_season(self.season)
            self.stack.insertWidget(i, page)
            self.stack.removeWidget(old)
            old.deleteLater()
            self.pages[i] = page
        self.stack.setCurrentIndex(current)

    # ---- data ------------------------------------------------------------
    def reload(self) -> None:
        if self._loader is not None and self._loader.isRunning():
            return
        self.statusBar().showMessage("Scanning for spreadsheets…")
        self.refresh_btn.setEnabled(False)
        self.settings = Settings.load()
        self._loader = Loader(self.settings)
        self._loader.finished_ok.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._loader.start()

    def _on_loaded(self, season: Season) -> None:
        self.season = season
        self.refresh_btn.setEnabled(True)
        self.season_label.setText(
            f"{season.title}  ·  week {season.current_week}"
            if season.current_week
            else season.title
        )
        for page in self.pages:
            page.set_season(season)

        files = len([s for s in season.sources if not s.error])
        if season.is_empty:
            self.statusBar().showMessage(
                f"No data found. Drop this week's files into {DATA_DIR} and press Refresh."
            )
        else:
            message = (
                f"{len(season.players)} players · "
                f"{len(season.final_weeks())} week(s) final · "
                f"{files} file(s)"
            )
            if season.conflicts:
                message += f" · {len(season.conflicts)} disagreement(s) - see Data & Update"
            self.statusBar().showMessage(message)

    def _on_failed(self, trace: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.statusBar().showMessage("Loading failed.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Could not read the spreadsheets")
        box.setText("Something went wrong while loading. The details are below.")
        box.setDetailedText(trace)
        box.exec()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # A packaged build is smoke-tested in CI by starting it headless and
    # letting it shut itself down, which proves the frozen bundle really runs
    # rather than only that a file was produced.
    smoke_test = "--smoke-test" in argv or os.environ.get("ACQL_SMOKE_TEST") == "1"
    if smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        argv = [a for a in argv if a != "--smoke-test"]

    app = QApplication(sys.argv[:1] + list(argv))
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("ACQL")

    window = MainWindow()
    window.show()

    if smoke_test:
        from PySide6.QtCore import QTimer

        def finish() -> None:
            loader = window._loader
            if loader is not None and loader.isRunning():
                loader.wait(20_000)
            for index in range(len(PAGE_CLASSES)):
                window._select_page(index)
                QApplication.processEvents()
            print(f"Smoke test OK: {len(window.season.players)} player(s) loaded.")
            app.quit()

        QTimer.singleShot(4000, finish)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
