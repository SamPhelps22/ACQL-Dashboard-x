"""Application shell: the window, the navigation and the data reload."""

from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__, lines
from ..config import DATA_DIR, ICON_FILE, Settings
from ..models import Season
from ..names import AliasTable
from ..repository import load_season
from .pages.base import Page
from .pages.data import DataPage
from .pages.overview import OverviewPage
from .pages.insights import InsightsPage
from .pages.nextweek import NextWeekPage
from .pages.player import PlayerPage
from .pages.pools import PoolsPage
from .pages.projections import ProjectionsPage
from .pages.standings import StandingsPage
from .pages.weekly import WeeklyPage
from .pages.winnings import WinningsPage
from .theme import PALETTES, stylesheet

PAGE_CLASSES = (
    OverviewPage,
    StandingsPage,
    WeeklyPage,
    NextWeekPage,
    PlayerPage,
    WinningsPage,
    PoolsPage,
    ProjectionsPage,
    InsightsPage,
    DataPage,
)
DATA_INDEX = PAGE_CLASSES.index(DataPage)


def page_shortcut(index: int) -> str:
    """Ctrl+1 to Ctrl+9 for the first nine pages; the rest are reached from
    the sidebar or the Ctrl+K switcher. There is no Ctrl+10 to give them."""
    return f"Ctrl+{index + 1}" if index < 9 else ""


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


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
            return
        # Pool lines live in notes the parser doesn't read; add them here, off
        # the UI thread. A problem with a note is a warning, not a failed load.
        try:
            season.warnings.extend(lines.attach_from_workbook(season))
        except Exception as exc:  # noqa: BLE001
            season.warnings.append(f"Couldn't read the pool lines: {exc}")
        self.finished_ok.emit(season)


@dataclass(frozen=True)
class Command:
    label: str
    hint: str  # shortcut shown beside the label
    run: Callable[[], None]


class CommandPalette(QDialog):
    """Ctrl+K quick switcher: type a few letters, press Enter.

    Styled by the app stylesheet; target `QDialog#CommandPalette` in the
    theme to give it its own look.
    """

    def __init__(self, commands: list[Command], parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("CommandPalette")
        self.setModal(True)
        self.setFixedWidth(520)
        self._commands = commands

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Jump to a page or run a command\u2026")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_current)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results.setFixedHeight(260)
        self.results.itemClicked.connect(lambda _item: self._run_current())
        layout.addWidget(self.results)

        self._filter("")
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        terms = text.lower().split()
        self.results.clear()
        for index, command in enumerate(self._commands):
            label = command.label.lower()
            if all(term in label for term in terms):
                shown = f"{command.label}   ({command.hint})" if command.hint else command.label
                item = QListWidgetItem(shown)
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        else:
            empty = QListWidgetItem("No matches")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(empty)

    def _run_current(self) -> None:
        item = self.results.currentItem()
        index = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if index is None:
            return
        command = self._commands[index]
        self.accept()
        # Run after the dialog has closed so page switches don't fight its focus.
        QTimer.singleShot(0, command.run)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                count = self.results.count()
                if count:
                    step = 1 if key == Qt.Key.Key_Down else -1
                    self.results.setCurrentRow((self.results.currentRow() + step) % count)
                return True
        return super().eventFilter(obj, event)


class MainWindow(QMainWindow):
    def __init__(self, remember_state: bool = True) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.palette_ = PALETTES.get(self.settings.theme, PALETTES["dark"])
        self.season = Season(buy_in=self.settings.buy_in)
        self._loader: Loader | None = None
        self._closing = False
        # Window size and last page survive restarts (skipped for smoke tests).
        self._state = QSettings() if remember_state else None

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

        self.pages: list[Page] = []
        for index, cls in enumerate(PAGE_CLASSES):
            page = self._make_page(index)
            self.pages.append(page)
            self.stack.addWidget(page)
            # "&" in a button label is a Qt mnemonic; double it to show it.
            button = QPushButton(f"  {cls.icon}   {cls.title}".replace("&", "&&"))
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            keys = page_shortcut(index)
            button.setToolTip(" ".join(filter(None, [cls.subtitle, f"({keys})" if keys else ""])))
            button.clicked.connect(lambda _, i=index: self._show_page(i))
            self.nav_group.addButton(button, index)
            self.nav_layout.addWidget(button)
        self.nav_layout.addStretch(1)
        self._build_sidebar_footer()
        self._build_status_bar()

        self.statusBar().showMessage("Loading\u2026")
        self._build_shortcuts()
        self.apply_theme()
        self._restore_state()
        self.reload()

    # ---- chrome ----------------------------------------------------------
    def _make_page(self, index: int) -> Page:
        page = PAGE_CLASSES[index](self.palette_)
        # The Data page asks the window to reload after a write.
        if isinstance(page, DataPage):
            page.refresh_requested.connect(self.reload)
        # Double-clicking a standings row opens that player.
        if isinstance(page, StandingsPage):
            page.player_selected.connect(self.show_player)
        return page

    def show_player(self, display: str) -> None:
        index = PAGE_CLASSES.index(PlayerPage)
        self._select_page(index)
        # _select_page may have re-themed the page, so look it up afterwards.
        self.pages[index].select(display)

    def _build_sidebar(self) -> QWidget:
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(208)
        self.nav_layout = QVBoxLayout(self.sidebar)
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(1)

        self.brand = QLabel(APP_NAME)
        self.brand.setObjectName("SidebarTitle")
        self.season_label = QLabel("\u2013")
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

        self.jump_btn = QPushButton("\u2315  Jump to\u2026")
        self.jump_btn.setToolTip("Search pages and commands (Ctrl+K)")
        self.jump_btn.clicked.connect(self.open_palette)
        self.refresh_btn = QPushButton("\u21bb  Refresh")
        self.refresh_btn.setToolTip("Rescan the watched folders (F5)")
        self.refresh_btn.clicked.connect(self.reload)
        self.theme_btn = QPushButton("\u25d0  Theme")
        self.theme_btn.setToolTip("Switch between light and dark (Ctrl+T)")
        self.theme_btn.clicked.connect(self.toggle_theme)
        footer.addWidget(self.jump_btn)
        footer.addWidget(self.refresh_btn)
        footer.addWidget(self.theme_btn)

        version = QLabel(f"v{__version__}")
        version.setObjectName("SidebarSubtitle")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.addWidget(version)
        self.nav_layout.addLayout(footer)

    def _build_status_bar(self) -> None:
        bar = self.statusBar()

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(96, 8)
        self.progress.hide()

        # Clickable: jumps straight to the page where conflicts get resolved.
        self.conflict_btn = QPushButton()
        self.conflict_btn.setFlat(True)
        self.conflict_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.conflict_btn.clicked.connect(lambda: self._select_page(DATA_INDEX))
        self.conflict_btn.hide()

        self.updated_label = QLabel()

        for widget in (self.progress, self.conflict_btn, self.updated_label):
            bar.addPermanentWidget(widget)

    def _build_shortcuts(self) -> None:
        def add(text: str, keys, slot) -> None:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(slot)
            self.addAction(action)

        add("Refresh", "F5", self.reload)
        add("Toggle theme", "Ctrl+T", self.toggle_theme)
        add("Jump to\u2026", "Ctrl+K", self.open_palette)
        add("Quit", QKeySequence.StandardKey.Quit, self.close)
        for i in range(len(PAGE_CLASSES)):
            if page_shortcut(i):
                add(f"Page {i + 1}", page_shortcut(i), lambda _=False, idx=i: self._select_page(idx))

    def _restore_state(self) -> None:
        start = 0
        if self._state is not None:
            geometry = self._state.value("window/geometry")
            if geometry is not None:
                self.restoreGeometry(geometry)
            try:
                start = int(self._state.value("window/page", 0))
            except (TypeError, ValueError):
                start = 0
        self._select_page(start if 0 <= start < len(PAGE_CLASSES) else 0)

    # ---- navigation ------------------------------------------------------
    def _show_page(self, index: int) -> None:
        self._sync_page_theme(index)
        self.stack.setCurrentIndex(index)

    def _select_page(self, index: int) -> None:
        button = self.nav_group.button(index)
        if button:
            button.setChecked(True)
            self._show_page(index)

    def open_palette(self) -> None:
        commands = [
            Command(cls.title, page_shortcut(i), lambda i=i: self._select_page(i))
            for i, cls in enumerate(PAGE_CLASSES)
        ]
        other_theme = "light" if self.palette_.name == "dark" else "dark"
        commands += [
            Command("Refresh data", "F5", self.reload),
            Command(f"Switch to {other_theme} theme", "Ctrl+T", self.toggle_theme),
            Command(
                "Open data folder",
                "",
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR))),
            ),
        ]
        dialog = CommandPalette(commands, self)
        dialog.move(self.mapToGlobal(QPoint((self.width() - dialog.width()) // 2, 80)))
        dialog.exec()
        dialog.deleteLater()

    # ---- theme -----------------------------------------------------------
    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet(self.palette_))

    def toggle_theme(self) -> None:
        self.settings.theme = "light" if self.palette_.name == "dark" else "dark"
        self.settings.save()
        self.palette_ = PALETTES[self.settings.theme]
        self.setUpdatesEnabled(False)
        try:
            self.apply_theme()
            # Only the visible page re-themes now; the rest do it the first
            # time they're opened, so the switch is instant and untouched
            # pages keep their scroll position, selection and sort.
            self._sync_page_theme(self.stack.currentIndex())
        finally:
            self.setUpdatesEnabled(True)

    def _sync_page_theme(self, index: int) -> None:
        """Bring one page up to the current palette.

        Charts bake their colours in at draw time, so a palette change has to
        reach them. They now redraw themselves through `set_palette`, which is
        why this no longer destroys and rebuilds the page: a page keeps its
        state across a theme switch.
        """
        page = self.pages[index]
        if page.palette is not self.palette_:
            page.set_palette(self.palette_)

    # ---- data ------------------------------------------------------------
    def _set_loading(self, loading: bool) -> None:
        self.refresh_btn.setEnabled(not loading)
        self.refresh_btn.setText("\u21bb  Refreshing\u2026" if loading else "\u21bb  Refresh")
        self.progress.setVisible(loading)

    def reload(self) -> None:
        if self._loader is not None and self._loader.isRunning():
            return
        self._set_loading(True)
        self.statusBar().showMessage("Scanning for spreadsheets\u2026")
        self.settings = Settings.load()

        loader = Loader(self.settings)
        loader.finished_ok.connect(self._on_loaded)
        loader.failed.connect(self._on_failed)
        loader.finished.connect(lambda l=loader: self._on_loader_finished(l))
        self._loader = loader
        loader.start()

    def _on_loader_finished(self, loader: Loader) -> None:
        # Only release the thread object once it has really stopped.
        if self._loader is loader:
            self._loader = None
        loader.deleteLater()

    def _on_loaded(self, season: Season) -> None:
        if self._closing:
            return
        self.season = season
        self._set_loading(False)
        self.updated_label.setText(f"Updated {datetime.now():%H:%M}")
        self.season_label.setText(
            f"{season.title}  \u00b7  week {season.current_week}"
            if season.current_week
            else season.title
        )
        if season.title:
            self.setWindowTitle(f"{season.title} \u2013 {APP_NAME}")
        for page in self.pages:
            page.set_season(season)

        conflicts = len(season.conflicts)
        self.conflict_btn.setVisible(conflicts > 0)
        if conflicts:
            self.conflict_btn.setText(f"\u26a0  {_plural(conflicts, 'disagreement')}")
            self.conflict_btn.setToolTip(f"Open {PAGE_CLASSES[DATA_INDEX].title} to review")

        if season.is_empty:
            self.statusBar().showMessage(
                f"No data found. Drop this week's files into {DATA_DIR} and press Refresh."
            )
        else:
            files = len([s for s in season.sources if not s.error])
            self.statusBar().showMessage(
                f"{_plural(len(season.players), 'player')} \u00b7 "
                f"{_plural(len(season.final_weeks()), 'week')} final \u00b7 "
                f"{_plural(files, 'file')}"
            )

    def _on_failed(self, trace: str) -> None:
        if self._closing:
            return
        self._set_loading(False)
        self.statusBar().showMessage(
            "Loading failed. Still showing the last data that loaded."
            if not self.season.is_empty
            else "Loading failed."
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Could not read the spreadsheets")
        box.setText("Something went wrong while loading. The details are below.")
        box.setDetailedText(trace)
        box.exec()

    # ---- lifecycle -------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._closing = True
        if self._state is not None:
            self._state.setValue("window/geometry", self.saveGeometry())
            self._state.setValue("window/page", self.stack.currentIndex())
        # Quitting mid-load would destroy a running QThread and crash.
        loader = self._loader
        if loader is not None and loader.isRunning():
            loader.wait(5000)
        super().closeEvent(event)


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
    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    window = MainWindow(remember_state=not smoke_test)
    window.show()

    if smoke_test:

        def finish() -> None:
            loader = window._loader
            if loader is not None and loader.isRunning():
                loader.wait(20_000)
            for index in range(len(PAGE_CLASSES)):
                window._select_page(index)
                QApplication.processEvents()
            # Report the icon too: a frozen build can lose bundled data files
            # without the app failing, and CI should catch that.
            icon = "found" if ICON_FILE.is_file() else f"MISSING at {ICON_FILE}"
            print(
                f"Smoke test OK: {len(window.season.players)} player(s) loaded, "
                f"{len(PAGE_CLASSES)} pages rendered, icon {icon}."
            )
            app.quit()

        QTimer.singleShot(4000, finish)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())