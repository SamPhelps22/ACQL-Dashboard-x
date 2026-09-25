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

from pathlib import Path

from .. import APP_NAME, __version__, analytics, lines, picks, predictions
from ..config import DATA_DIR, ICON_FILE, Settings
from ..models import Season
from ..names import AliasTable
from ..repository import load_season
from .groups import GroupSpec, PageGroup
from .pages.base import (
    GO_TO_DATA, INSTALL_UPDATE, OPEN_FOLDER, POOL_PAGE, RELOAD, SELF_CHECK, UNDO_UPDATE, Page,
    write_log,
)
from .watch import FolderWatcher, describe
from .pages.thisweek import BriefingPage
from .pages.charts import ChartsPage
from .pages.data import DataPage
from .pages.overview import OverviewPage
from .pages.insights import InsightsPage
from .pages.model import ModelPage
from .pages.nextweek import NextWeekPage
from .pages.player import PlayerPage
from .pages.pools import PoolsPage
from .pages.projections import ProjectionsPage
from .pages.standings import StandingsPage
from .pages.weekly import WeeklyPage
from .pages.winnings import WinningsPage
from .theme import PALETTES, stylesheet

#: The sidebar: seven places, the pages inside each shown as tabs (groups.py).
NAV = (
    GroupSpec("Season", "\N{TROPHY}", "Where the season stands: the table, the money, the odds",
              (("Overview", OverviewPage), ("Standings", StandingsPage),
               ("Winnings", WinningsPage), ("Projections", ProjectionsPage),
               ("Charts", ChartsPage))),
    # Second, and on Ctrl+2: the question most visits are here to answer is
    # "what do I play this week", and it should not be four clicks away.
    GroupSpec("This Week", "\N{MEMO}", "The card to hand in, and every game on the slate",
              (("Your card", BriefingPage), ("Every game", NextWeekPage))),
    GroupSpec("Results", "\N{SPIRAL CALENDAR PAD}", "One week at a time, and the recap to send round",
              (("Results", WeeklyPage),)),
    GroupSpec("Side Pools", "\N{DIRECT HIT}", "Big Loser and the suicide pool",
              (("Side pools", PoolsPage),)),
    GroupSpec("Player", "\N{BUST IN SILHOUETTE}", "One coach's season in detail",
              (("Player", PlayerPage),)),
    GroupSpec("Insights", "\N{LEFT-POINTING MAGNIFYING GLASS}", "The pool's habits and luck, and the model's record",
              (("The pool", InsightsPage), ("The model", ModelPage))),
    GroupSpec("Data & Update", "\N{CARD INDEX DIVIDERS}", "What is loaded, entering results, and updating the app",
              (("Data", DataPage),)),
)
#: Every page, in sidebar order - one instance of each.
PAGE_CLASSES = tuple(cls for spec in NAV for cls in spec.classes)


def group_of(cls: type) -> tuple[int, int]:
    """(sidebar place, tab) for a page class."""
    for g, spec in enumerate(NAV):
        if cls in spec.classes:
            return g, spec.classes.index(cls)
    raise KeyError(cls.__name__)


DATA_INDEX = group_of(DataPage)[0]


def page_shortcut(index: int) -> str:
    """Ctrl+1 to Ctrl+9 for the sidebar's places."""
    return f"Ctrl+{index + 1}" if index < 9 else ""


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


#: A reload the app started by itself gets one quiet retry if it fails -
#: usually the file was still being written - before anyone is bothered.
AUTO_RETRY_MS = 5000
#: How often "Updated 3 min ago" is brought up to date.
CLOCK_TICK_MS = 30_000


def updated_text(loaded: datetime | None, now: datetime | None = None) -> str:
    """"Updated just now", "Updated 4 min ago", "Updated at 14:05"."""
    if loaded is None:
        return ""
    now = now or datetime.now()
    seconds = max(0, (now - loaded).total_seconds())
    if seconds < 60:
        return "Updated just now"
    if seconds < 3600:
        return f"Updated {int(seconds // 60)} min ago"
    if loaded.date() == now.date():
        return f"Updated at {loaded:%H:%M}"
    return f"Updated {loaded:%a %H:%M}"


def failure_summary(trace: str) -> str:
    """The last line of a traceback - the one that says what went wrong."""
    lines_ = [line for line in trace.strip().splitlines() if line.strip()]
    return lines_[-1].strip() if lines_ else "Unknown error"


class Loader(QThread):
    """Parses the spreadsheets off the UI thread so the window stays live."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def run(self) -> None:
        try:
            aliases = AliasTable.load()
            season = load_season(self.settings, aliases)
        except Exception:  # noqa: BLE001 - reported in the UI, never swallowed
            self.failed.emit(traceback.format_exc())
            return
        # Pool lines live in notes the parser doesn't read; add them here, off
        # the UI thread. A problem with a note is a warning, not a failed load.
        try:
            season.warnings.extend(lines.attach_from_workbook(season))
        except Exception as exc:  # noqa: BLE001
            season.warnings.append(f"Couldn't read the pool lines: {exc}")
        # The pool's raw pick sheets, if any have been downloaded. They fill
        # in weeks the workbook hasn't been given yet and check the ones it
        # has; they never overwrite a week the workbook owns.
        try:
            workbook = getattr(season, "workbook_path", None)
            picks.refresh_from_disk(workbook)
            # Predictions for the week ahead are picked up here rather than
            # only when the Next Week page is opened, so one press of Refresh
            # takes in everything that has been dropped in the folder.
            try:
                ahead = analytics.upcoming_week(season)
                week = season.weeks.get(ahead)
                got, where, fresh = predictions.refresh_from_disk(
                    ahead, workbook,
                    sorted(week.games, key=lambda g: g.index) if week else [],
                )
                if fresh and got:
                    season.warnings.append(
                        f"Week {ahead} predictions read from "
                        f"{Path(where).name}: {len(got)} games."
                    )
            except Exception as exc:                      # noqa: BLE001
                season.warnings.append(f"Couldn't read the predictions file: {exc}")
            graded = picks.attach(season, key_for=aliases.key)
            if graded.other_season:
                season.warnings.append(
                    "Stored pick sheets from another season were ignored ("
                    + ", ".join(f"week {n}" for n in graded.other_season)
                    + "). Their games are not this season's - clear them from "
                    "Data & Update."
                )
            if graded.built:
                season.warnings.append(
                    "Built from the pool's pick sheet, not the workbook: "
                    + ", ".join(f"week {n}" for n in graded.built)
                )
            season.warnings.extend(graded.disagreements)
        except Exception as exc:  # noqa: BLE001
            season.warnings.append(f"Couldn't read the pool's pick sheets: {exc}")
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
        self._loaded_at: datetime | None = None
        self._auto = False                   # the running load started itself
        self._retried = False                # and has already had its retry
        self._pending: list[str] | None = None   # changes seen mid-load
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

        # One instance of every page, grouped into the sidebar's places.
        self.pages: list[Page] = []
        self.groups: list[PageGroup] = []
        for index, spec in enumerate(NAV):
            members = []
            for cls in spec.classes:
                page = self._make_page(cls)
                self.pages.append(page)
                members.append(page)
            group = PageGroup(spec, members)
            group.tab_changed.connect(lambda _tab, g=index: self._sync_page_theme(g))
            self.groups.append(group)
            self.stack.addWidget(group)
            # "&" in a button label is a Qt mnemonic; double it to show it.
            button = QPushButton(f"  {spec.icon}   {spec.title}".replace("&", "&&"))
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            keys = page_shortcut(index)
            button.setToolTip(" ".join(filter(None, [spec.subtitle, f"({keys})" if keys else ""])))
            button.clicked.connect(lambda _, i=index: self._show_page(i))
            self.nav_group.addButton(button, index)
            self.nav_layout.addWidget(button)
        self.nav_layout.addStretch(1)
        self._build_sidebar_footer()
        self._build_status_bar()

        # Files dropped into a watched folder reload the app by themselves.
        self.watcher = FolderWatcher(self)
        self.watcher.changed.connect(self._files_changed)
        # "Updated 3 min ago" has to keep counting to stay true.
        self._clock = QTimer(self)
        self._clock.setInterval(CLOCK_TICK_MS)
        self._clock.timeout.connect(self._tick_updated)
        self._clock.start()

        self.statusBar().showMessage("Loading\u2026")
        self._build_shortcuts()
        self.apply_theme()
        self._restore_state()
        self.reload()

    # ---- chrome ----------------------------------------------------------
    def _make_page(self, cls: type) -> Page:
        page = cls(self.palette_)
        # Buttons on a page's loading / no-data / error panel.
        page.action_requested.connect(self._page_action)
        # The Data page after a write, This Week after fetching new lines.
        if hasattr(page, "refresh_requested"):
            page.refresh_requested.connect(self.refresh_by_hand)
        # Double-clicking a standings row opens that player.
        if isinstance(page, StandingsPage):
            page.player_selected.connect(self.show_player)
        return page

    def _page_action(self, what: str) -> None:
        if what == GO_TO_DATA:
            self._select_page(DATA_INDEX)
        elif what == OPEN_FOLDER:
            self.open_data_folder()
        elif what == RELOAD:
            self.refresh_by_hand()
        elif what == SELF_CHECK:
            self.run_self_check()
        elif what == INSTALL_UPDATE:
            self.install_update()
        elif what == UNDO_UPDATE:
            from . import updating
            updating.undo(self)
        elif what == POOL_PAGE:
            self.export_pool_page()

    # ---- the self-check and updates -----------------------------------------
    def run_self_check(self, *, quiet: bool = False) -> Path | None:
        """Photograph every page and write the report (selfcheck.py)."""
        from . import selfcheck
        self.statusBar().showMessage("Self-check: opening every page\u2026")
        try:
            archive = selfcheck.run(
                self, say=lambda text: self.statusBar().showMessage(f"Self-check: {text}")
            )
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            write_log(f"self-check failed: {exc!r}\n{traceback.format_exc()}")
            if not quiet:
                QMessageBox.warning(self, "Self-check", f"The self-check stopped: {exc}")
            return None
        pages, problems = selfcheck.summary(archive)
        self.statusBar().showMessage(
            f"Self-check done: {pages} pages, {problems} thing(s) to look at \u2013 {archive.name}"
        )
        if not quiet:
            box = QMessageBox(self)
            box.setWindowTitle("Self-check done")
            box.setText(
                f"{pages} pages photographed, {problems} thing"
                f"{'' if problems == 1 else 's'} to look at."
            )
            box.setInformativeText(
                f"Everything is in {archive.name}, in the data folder's selfcheck "
                f"folder - send that one file to Claude and the next changes can "
                f"be checked against how the pages really look on this computer."
            )
            show = box.addButton("Show the file", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is show:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(archive.parent)))
        return archive

    def export_pool_page(self):
        """Put this week on the pool's website (webpage.py) - or save the Claude page's file."""
        from . import webpage
        return webpage.publish(self, self.season)

    def pool_page_settings(self) -> None:
        from . import webpage
        webpage.edit_settings(self)

    def install_update(self) -> None:
        from . import updating
        if not hasattr(self, "_update_flow"):
            self._update_flow = updating.UpdateFlow(self)
        self._update_flow.start()

    def _watch_folders(self) -> list[Path]:
        """Every folder the loader reads from: the watched ones, the app's
        own data folder, and wherever the workbook turned out to be."""
        folders = [Path(p) for p in self.settings.search_paths()]
        folders.append(Path(DATA_DIR))
        workbook = getattr(self.season, "workbook_path", None)
        if workbook:
            folders.append(Path(workbook).parent)
        return folders

    def open_data_folder(self) -> None:
        """Open the first watched folder that exists, else the app's own."""
        target = next(
            (p for p in self._watch_folders() if p.is_dir()), Path(DATA_DIR)
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def show_player(self, display: str) -> None:
        group, tab = group_of(PlayerPage)
        self._select_page(group, tab)
        # _select_page may have re-themed the page, so look it up afterwards.
        self.groups[group].pages[tab].select(display)

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
        self.refresh_btn.setToolTip(
            "Rescan the watched folders (F5 or Ctrl+R). New or saved files "
            "are picked up by themselves, so this is rarely needed."
        )
        self.refresh_btn.clicked.connect(self.refresh_by_hand)
        self.theme_btn = QPushButton("\u25d0  Theme")
        self.theme_btn.setToolTip("Switch between light and dark (Ctrl+T)")
        self.theme_btn.clicked.connect(self.toggle_theme)
        footer.addWidget(self.jump_btn)
        footer.addWidget(self.refresh_btn)
        footer.addWidget(self.theme_btn)

        try:
            from ..version import VERSION as shown_version
        except Exception:  # noqa: BLE001 - a copy from before 2.0
            shown_version = __version__
        version = QLabel(f"v{shown_version}")
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

        add("Refresh", "F5", self.refresh_by_hand)
        add("Refresh", "Ctrl+R", self.refresh_by_hand)
        add("Toggle theme", "Ctrl+T", self.toggle_theme)
        add("Jump to\u2026", "Ctrl+K", self.open_palette)
        add("Quit", QKeySequence.StandardKey.Quit, self.close)
        for i in range(len(NAV)):
            if page_shortcut(i):
                add(f"Page {i + 1}", page_shortcut(i), lambda _=False, idx=i: self._select_page(idx))

    def _restore_state(self) -> None:
        start = 0
        if self._state is not None:
            geometry = self._state.value("window/geometry")
            if geometry is not None:
                self.restoreGeometry(geometry)
            try:
                start = int(self._state.value("window/group", 0))
            except (TypeError, ValueError):
                start = 0
            for g, group in enumerate(self.groups):
                try:
                    tab = int(self._state.value(f"window/tab/{g}", 0))
                except (TypeError, ValueError):
                    tab = 0
                if 0 < tab < len(group.pages):
                    group.select(tab)
        self._select_page(start if 0 <= start < len(NAV) else 0)

    # ---- navigation ------------------------------------------------------
    def _show_page(self, index: int) -> None:
        self._sync_page_theme(index)
        self.stack.setCurrentIndex(index)

    def _select_page(self, index: int, tab: int | None = None) -> None:
        button = self.nav_group.button(index)
        if button:
            button.setChecked(True)
            if tab is not None:
                self.groups[index].select(tab)
            self._show_page(index)

    def current_page(self) -> Page:
        return self.groups[self.stack.currentIndex()].current_page()

    def open_palette(self) -> None:
        commands = []
        for i, spec in enumerate(NAV):
            commands.append(Command(spec.title, page_shortcut(i), lambda i=i: self._select_page(i)))
            if len(spec.tabs) > 1:
                for t, (label, _) in enumerate(spec.tabs):
                    commands.append(Command(
                        f"{spec.title} \u203a {label}", "",
                        lambda i=i, t=t: self._select_page(i, t),
                    ))
        other_theme = "light" if self.palette_.name == "dark" else "dark"
        commands += [
            Command("Refresh data", "F5", self.refresh_by_hand),
            Command(f"Switch to {other_theme} theme", "Ctrl+T", self.toggle_theme),
            Command("Open data folder", "", self.open_data_folder),
            Command("Publish the pool page", "", self.export_pool_page),
            Command("Pool page website settings\u2026", "", self.pool_page_settings),
            Command("Run self-check (photograph every page)", "", self.run_self_check),
            Command("Install update\u2026", "", self.install_update),
            Command("Undo last update", "", lambda: self._page_action(UNDO_UPDATE)),
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
        """Bring the page showing in one sidebar place up to the current palette.

        Charts bake their colours in at draw time, so a palette change has to
        reach them. They redraw themselves through `set_palette`, which is
        why this never destroys and rebuilds the page: a page keeps its state
        across a theme switch. Tabs not yet opened catch up when they are.
        """
        if not 0 <= index < len(self.groups):
            return
        page = self.groups[index].current_page()
        if page.palette is not self.palette_:
            page.set_palette(self.palette_)

    # ---- data ------------------------------------------------------------
    def _set_loading(self, loading: bool) -> None:
        self.refresh_btn.setEnabled(not loading)
        self.refresh_btn.setText("\u21bb  Refreshing\u2026" if loading else "\u21bb  Refresh")
        self.progress.setVisible(loading)

    def refresh_by_hand(self, *_signal_args) -> None:
        """Refresh from a button, key or command.

        Qt hands a clicked or triggered slot a `checked` flag; this soaks it
        up so it can never land in one of reload's own parameters.
        """
        self.reload()

    def reload(self, *, auto: bool = False, because: list[str] | None = None) -> None:
        """Re-read every source. `auto` is a reload the app started itself."""
        if self._loader is not None and self._loader.isRunning():
            # Mid-load: remember that something else changed and go again after.
            if auto:
                self._pending = (self._pending or []) + list(because or [])
            return
        if not auto:
            self._retried = False
        self._auto = auto
        self._set_loading(True)
        self.statusBar().showMessage(
            f"Picked up {describe(because)} \u2013 reading it\u2026"
            if because
            else "Scanning for spreadsheets\u2026"
        )
        self.settings = Settings.load()
        # What the loader is about to read is the new normal; only changes
        # after this moment should trigger another reload.
        self.watcher.watch(self._watch_folders())
        self.watcher.settle()

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

    def _files_changed(self, names: list[str]) -> None:
        """Something the dashboard reads was added, saved or removed."""
        if self._closing:
            return
        self.reload(auto=True, because=names)

    def _tick_updated(self) -> None:
        self.updated_label.setText(updated_text(self._loaded_at))

    def _on_loaded(self, season: Season) -> None:
        if self._closing:
            return
        self.season = season
        self._retried = False
        self._set_loading(False)
        self._loaded_at = datetime.now()
        self._tick_updated()
        self.updated_label.setToolTip(f"Last read {self._loaded_at:%A %H:%M:%S}")
        self.season_label.setText(
            f"{season.title}  \u00b7  week {season.current_week}"
            if season.current_week
            else season.title
        )
        if season.title:
            self.setWindowTitle(f"{season.title} \u2013 {APP_NAME}")
        # The workbook's folder is only known now; make sure it is watched.
        self.watcher.watch(self._watch_folders())
        for page in self.pages:
            # Pages contain their own refresh errors; this guards the handoff
            # so one page can never stop the rest from getting the new data.
            try:
                page.set_season(season)
            except Exception as exc:  # noqa: BLE001
                write_log(f"set_season failed on {page.title}: {exc!r}")

        conflicts = len(season.conflicts)
        self.conflict_btn.setVisible(conflicts > 0)
        if conflicts:
            self.conflict_btn.setText(f"\u26a0  {_plural(conflicts, 'disagreement')}")
            self.conflict_btn.setToolTip(f"Open {NAV[DATA_INDEX].title} to review")

        if season.is_empty:
            self.statusBar().showMessage(
                f"No data found yet. Drop this week's files into {DATA_DIR} "
                "\u2013 they are picked up as soon as they land."
            )
        else:
            files = len([s for s in season.sources if not s.error])
            self.statusBar().showMessage(
                f"{_plural(len(season.players), 'player')} \u00b7 "
                f"{_plural(len(season.final_weeks()), 'week')} final \u00b7 "
                f"{_plural(files, 'file')}"
            )

        # Files that changed while this load was running get their own load.
        pending, self._pending = self._pending, None
        if pending:
            QTimer.singleShot(0, lambda: self.reload(auto=True, because=pending))

    def _on_failed(self, trace: str) -> None:
        if self._closing:
            return
        self._set_loading(False)
        summary = failure_summary(trace)
        write_log(f"load failed{' (automatic)' if self._auto else ''}: {summary}\n{trace}")

        # A reload the app started by itself usually failed because the file
        # was still being written (Excel mid-save, OneDrive mid-sync). Try
        # once more quietly before interrupting anybody with a dialog.
        if self._auto and not self._retried:
            self._retried = True
            self.statusBar().showMessage(
                "Couldn't read the new file yet \u2013 it may still be saving. "
                "Trying again in a few seconds\u2026"
            )
            QTimer.singleShot(AUTO_RETRY_MS, lambda: self.reload(auto=True))
            return

        self.statusBar().showMessage(
            "Loading failed. Still showing the last data that loaded."
            if not self.season.is_empty
            else "Loading failed."
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Could not read the spreadsheets")
        box.setText(
            f"{summary}\n\n"
            "If a spreadsheet is open in Excel, save and close it, then press "
            "Refresh. The full details are below and in acql-log.txt in the "
            "data folder."
        )
        box.setDetailedText(trace)
        box.exec()

    # ---- lifecycle -------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._closing = True
        self.watcher.set_enabled(False)
        self._clock.stop()
        if self._state is not None:
            self._state.setValue("window/geometry", self.saveGeometry())
            self._state.setValue("window/group", self.stack.currentIndex())
            for g, group in enumerate(self.groups):
                self._state.setValue(f"window/tab/{g}", group.current_index())
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
    # Open, load, photograph every page, and close: the self-check from the
    # command line (ACQL Dashboard.bat --selfcheck).
    self_check = "--selfcheck" in argv or "--self-check" in argv
    argv = [a for a in argv if a not in ("--selfcheck", "--self-check")]

    app = QApplication(sys.argv[:1] + list(argv))
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("ACQL")
    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    window = MainWindow(remember_state=not smoke_test)
    window.show()

    if self_check:

        def when_loaded() -> None:
            # Go ahead once the first load has finished, whether it worked or
            # not - a self-check is most wanted exactly when it didn't.
            if window._loader is not None:
                QTimer.singleShot(500, when_loaded)
                return
            archive = window.run_self_check(quiet=True)
            print(f"Self-check written to {archive}" if archive else "Self-check failed - see acql-log.txt")
            app.quit()

        QTimer.singleShot(1500, when_loaded)

    if smoke_test:

        def finish() -> None:
            loader = window._loader
            if loader is not None and loader.isRunning():
                loader.wait(20_000)
            for index, group in enumerate(window.groups):
                for tab in range(len(group.pages)):
                    window._select_page(index, tab)
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
