"""Application shell: the window, the navigation and the data reload."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime

from PySide6.QtCore import QPoint, QSettings, QSize, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pathlib import Path

from .. import APP_NAME, __version__, analytics, places
from ..feeds import oddslock, results
from ..config import DATA_DIR, ICON_FILE, Settings
from ..models import Season
from ..version import MODEL_NAME
from . import icons
from .groups import GroupSpec, PageGroup
from .motion import fade_stack
from .pages.base import (
    CHECK_RESULTS, CHECK_UPDATES, GO_TO_DATA, INSTALL_UPDATE, KEEPING, LIVE_CHECK, LIVE_CHECK_NOW, OPEN_FOLDER,
    POOL_EXTRAS, UPDATE_SETTINGS,
    POOL_PAGE, RELOAD, SELF_CHECK, UNDO_UPDATE, Page,
    write_log,
)
from .watch import FolderWatcher, describe
from .pages.thisweek import BriefingPage
from .pages.charts import ChartsPage
from .pages.data import DataPage
from .pages.readiness import ReadinessPage
from .pages.everyone import EveryonePage
from .pages.gameday import GameDayPage
from .pages.overview import OverviewPage
from .pages.insights import InsightsPage
from .pages.model import ModelPage
from .pages.modellab import ModelLabPage
from .pages.modelcharts import ModelChartsPage
from .pages.recipe import RecipePage
from .pages.computers import ComputersPage
from .pages.hitsmisses import HitsMissesPage
from .pages.radar import RadarPage
from .pages.nextweek import NextWeekPage
from .pages.player import PlayerPage
from .pages.pools import PoolsPage
from .pages.projections import ProjectionsPage
from .pages.reportcard import ReportCardPage
from .pages.standings import StandingsPage
from .pages.teams import TeamsPage
from .pages.weekly import WeeklyPage
from .pages.winnings import WinningsPage
from .theme import PALETTES, stylesheet

#: The sidebar: eight places, the pages inside each shown as tabs (groups.py).
NAV = (
    GroupSpec(places.SEASON, "trophy", "Where the season stands: the standings, who has won money, and who can still take the title",
              (("Overview", OverviewPage), ("Standings", StandingsPage),
               ("Winnings", WinningsPage), ("Projections", ProjectionsPage),
               ("Charts", ChartsPage))),
    # Second, and on Ctrl+2: the question most visits are here to answer is
    # "what do I play this week", and it should not be four clicks away.
    GroupSpec(places.THIS_WEEK, "calendar", "What to play this week: your card, every game priced, and where the card could be wrong",
              ((places.CARD, BriefingPage), (places.EVERY_GAME, NextWeekPage), (places.RADAR, RadarPage))),
    # While the games are on: every score against the pool's lines, live.
    GroupSpec(places.GAME_DAY, "football", "The games as they happen: live scores against the pool's lines, and what you need to go your way",
              (("Game day", GameDayPage), (places.EVERYONE, EveryonePage))),
    GroupSpec(places.RESULTS, "bars", "How each week finished: every game, who won the week, and the recap to send round",
              (("Results", WeeklyPage),)),
    GroupSpec(places.SIDE_POOLS, "people", "The Big Loser and suicide pools: who leads, who is still alive, and the best picks left",
              (("Side pools", PoolsPage),)),
    GroupSpec(places.PLAYER, "person", "One coach's whole season: every week, their habits, and how they compare with the pool",
              (("Player", PlayerPage),)),
    GroupSpec(places.INSIGHTS, "search",
              "What the numbers say about the pool: its habits, its luck, and how the market rates every team",
              ((places.POOL, InsightsPage), (places.TEAMS, TeamsPage))),
    # Its own place, so "is it any good, and should I follow it?" is one
    # click from anywhere rather than a tab inside Insights.
    GroupSpec(places.MODEL, "crosshair", f"How good {MODEL_NAME}'s picks are, where they miss, and whether anything would do better",
              ((places.REPORT_CARD, ReportCardPage), (places.DETAILS, ModelPage), (places.LAB, ModelLabPage),
               (places.HITS, HitsMissesPage), (places.MODEL_CHARTS, ModelChartsPage),
               (places.RECIPE, RecipePage), (places.COMPUTERS, ComputersPage))),
    GroupSpec(places.DATA, "database", "Which files are loaded, where each result came from, and how to update the app",
              (("Data", DataPage), (places.READINESS, ReadinessPage))),
)
#: The sidebar before Game Day joined it (2.13), so a place remembered by its
#: number then still opens the same place now.
PLACES_BEFORE = (places.SEASON, places.THIS_WEEK, places.RESULTS, places.SIDE_POOLS, places.PLAYER,
                 places.INSIGHTS, places.MODEL, places.DATA)
#: Sizes, in points: a place's icon, a footer button's, and the mark by the name.
NAV_ICON, FOOTER_ICON, MARK_SIZE = 20, 15, 40
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
#: How often the window considers looking at the scoreboard. It only goes
#: online when a look is due (results.due: every few minutes while a game
#: is on, every minute while Game Day is open), and only reloads when a game
#: has finished.
RESULTS_CHECK_MS = 60 * 1000


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


from .workers import Loader, ResultsCheck, TimelineFetch, Warmer  # noqa: E402 - here so tests can stand them in
from .palette import Command, CommandPalette  # noqa: E402


class MainWindow(QMainWindow):
    #: The tray icon while the dashboard is to keep running in it (keeping.py).
    _tray = None
    _quitting = False
    remember_state = True

    def __init__(self, remember_state: bool = True) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.palette_ = PALETTES.get(self.settings.theme, PALETTES["dark"])
        self.season = Season(buy_in=self.settings.buy_in)
        self._loader: Loader | None = None
        self._warmer: Warmer | None = None
        self._closing = False
        self._close_when_published = False   # closed mid-upload: close once it's done
        self._loaded_at: datetime | None = None
        self._auto = False                   # the running load started itself
        self._retried = False                # and has already had its retry
        self._pending: list[str] | None = None   # changes seen mid-load
        # Window size and last page survive restarts (skipped for smoke tests).
        self._state = QSettings() if remember_state else None

        self.setWindowTitle(places.BRAND)
        self.resize(1440, 920)
        self.setMinimumSize(1060, 700)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        fade_stack(self.stack)
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
            button = QPushButton(f"   {spec.title}".replace("&", "&&"))
            button.setObjectName("NavButton")
            button.setIconSize(QSize(NAV_ICON, NAV_ICON))        # drawn in apply_theme
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
        self._clock.timeout.connect(self._on_clock)
        self._clock.start()
        # Results arrive by themselves while the window is open.
        self._results_timer = QTimer(self)
        self._results_timer.setInterval(RESULTS_CHECK_MS)
        self._results_timer.timeout.connect(self.check_results)
        self._results_timer.start()
        # In the tray, closing the window leaves the dashboard running (keeping.py).
        self._tray = None
        self._quitting = False
        self.remember_state = remember_state
        self.apply_keeping()

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
        elif what == POOL_EXTRAS:
            self.pool_page_extras()
        elif what == CHECK_RESULTS:
            self.check_results_now()
        elif what == LIVE_CHECK:
            self.check_results(live=True)
        elif what == KEEPING:
            self.apply_keeping()
        elif what == CHECK_UPDATES:
            self.check_updates(by_hand=True)
        elif what == UPDATE_SETTINGS:
            from . import updatecheck
            updatecheck.edit_settings(self)
        elif what == LIVE_CHECK_NOW:
            self.statusBar().showMessage("Asking ESPN for the latest scores\u2026", 4000)
            self.check_results(live=True, force=True)

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

    def pool_page_extras(self) -> None:
        from . import webpage
        webpage.edit_extras(self)

    def pool_page_private(self) -> None:
        from . import webpage
        webpage.edit_private(self)

    # ---- the website keeping itself up to date (webpage.auto_publish) -----------
    #: Off for the smoke test and the self-check, which must never publish.
    auto_site = True

    def update_site(self) -> None:
        """After a load: the website, brought up to date in the background."""
        if self._closing:
            return
        try:
            from . import webpage
            webpage.auto_publish(self, self.season)
        except Exception as exc:  # noqa: BLE001 - the dashboard carries on regardless
            write_log(f"automatic website update didn't start: {exc!r}")

    def site_published(self, url: str) -> None:
        if not self._closing:
            self.statusBar().showMessage(f"The pool website updated itself: {url}")

    def site_failed(self, why: str) -> None:
        if not self._closing:
            self.statusBar().showMessage(
                f"The pool website didn't update by itself: {why} "
                f"{places.RESULTS} › Pool page tries again."
            )

    def site_worker_finished(self) -> None:
        worker = getattr(self, "_site_worker", None)
        if worker is not None and not worker.isRunning():
            self._site_worker = None
            worker.deleteLater()
        if getattr(self, "_close_when_published", False):
            self.close()                    # the window went earlier; now the app can go too
            return
        if getattr(self, "_site_again", False) and not self._closing:
            self._site_again = False
            self.update_site()

    def install_update(self) -> None:
        from . import updating
        if not hasattr(self, "_update_flow"):
            self._update_flow = updating.UpdateFlow(self)
        self._update_flow.start()

    def _watch_folders(self) -> list[Path]:
        """Every folder the loader reads from: the watched ones, the app's
        own data folder, wherever the workbook turned out to be, and
        Downloads - where a pick sheet usually lands (only the pool's own
        files count there)."""
        from . import watch
        folders = [Path(p) for p in self.settings.search_paths()]
        folders.append(Path(DATA_DIR))
        workbook = getattr(self.season, "workbook_path", None)
        if workbook:
            folders.append(Path(workbook).parent)
        downloads = Path.home() / "Downloads"
        if downloads.is_dir() and downloads not in folders:
            watch.NARROW.add(str(downloads))
            folders.append(downloads)
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
        self.sidebar.setFixedWidth(226)       # wide enough for the name in capitals
        self.nav_layout = QVBoxLayout(self.sidebar)
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(1)

        # The name, beside its mark: the ball in the sights (icons.py).
        first, _, rest = places.BRAND.upper().partition(" ")
        lockup = QHBoxLayout()
        lockup.setContentsMargins(18, 20, 12, 8)
        lockup.setSpacing(11)
        self.mark = QLabel()
        self.mark.setFixedSize(MARK_SIZE, MARK_SIZE)
        self.mark.setToolTip(places.TAGLINE)
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(0)
        self.brand_top = QLabel(first if rest else "")
        self.brand_top.setObjectName("BrandTop")
        self.brand = QLabel(rest or first)
        self.brand.setObjectName("SidebarTitle")
        self.brand.setToolTip(places.TAGLINE)
        words.addStretch(1)
        words.addWidget(self.brand_top)
        words.addWidget(self.brand)
        words.addStretch(1)
        lockup.addWidget(self.mark)
        lockup.addLayout(words, 1)
        self.engine_label = QLabel(f"{MODEL_NAME} prediction engine".upper())
        self.engine_label.setObjectName("BrandLine")
        self.season_label = QLabel("\u2013")
        self.season_label.setObjectName("BrandLine")
        rule = QWidget()
        rule.setObjectName("BrandRule")
        rule.setFixedHeight(21)             # a one-pixel line and the margins either side of it
        self.nav_layout.addLayout(lockup)
        self.nav_layout.addWidget(self.engine_label)
        self.nav_layout.addSpacing(3)
        self.nav_layout.addWidget(self.season_label)
        self.nav_layout.addWidget(rule)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        return self.sidebar

    def _build_sidebar_footer(self) -> None:
        footer = QVBoxLayout()
        footer.setContentsMargins(10, 8, 10, 12)
        footer.setSpacing(6)

        self.jump_btn = QPushButton("  Jump to\u2026")
        self.jump_btn.setToolTip("Search pages and commands (Ctrl+K)")
        self.jump_btn.clicked.connect(self.open_palette)
        self.refresh_btn = QPushButton("  Refresh")
        self.refresh_btn.setToolTip(
            "Rescan the watched folders (F5 or Ctrl+R). New or saved files "
            "are picked up by themselves, so this is rarely needed."
        )
        self.refresh_btn.clicked.connect(self.refresh_by_hand)
        self.theme_btn = QPushButton("  Theme")
        self.theme_btn.setToolTip("Switch between light and dark (Ctrl+T)")
        self.theme_btn.clicked.connect(self.toggle_theme)
        self._footer_icons = ((self.jump_btn, "search"), (self.refresh_btn, "refresh"), (self.theme_btn, "theme"))
        for button, _name in self._footer_icons:
            button.setIconSize(QSize(FOOTER_ICON, FOOTER_ICON))
            footer.addWidget(button)

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
            titles = [spec.title for spec in NAV]
            place = self._state.value("window/place", "")
            place = places.FORMERLY.get(place, place) if isinstance(place, str) else place
            if isinstance(place, str) and place in titles:
                start = titles.index(place)
                keys = {g: f"window/tabs/{title}" for g, title in enumerate(titles)}
            else:
                # remembered by number, before places were remembered by name
                try:
                    old = int(self._state.value("window/group", 0))
                except (TypeError, ValueError):
                    old = 0
                name = PLACES_BEFORE[old] if 0 <= old < len(PLACES_BEFORE) else ""
                start = titles.index(name) if name in titles else 0
                keys = {titles.index(name): f"window/tab/{i}"
                        for i, name in enumerate(PLACES_BEFORE) if name in titles}
            for g, group in enumerate(self.groups):
                try:
                    tab = int(self._state.value(keys[g], 0)) if g in keys else 0
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
            Command("Check for results now", "", self.check_results_now),
            Command("Publish the pool page", "", self.export_pool_page),
            Command("Pool page website settings\u2026", "", self.pool_page_settings),
            Command("What the website says (announcement, champions)\u2026", "", self.pool_page_extras),
            Command("Private page (your card on your phone, locked)\u2026", "", self.pool_page_private),
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
            app.setProperty("theme", self.palette_.name)    # for widgets that draw themselves
            app.setStyleSheet(stylesheet(self.palette_))
        self._draw_icons()

    def _draw_icons(self) -> None:
        """The sidebar's icons and the mark, in the palette's colours: quiet
        at rest, the accent on the place you are in."""
        p = self.palette_
        for index, spec in enumerate(NAV):
            button = self.nav_group.button(index)
            if button is not None:
                button.setIcon(icons.icon(spec.icon, p.ink_muted, p.accent, NAV_ICON))
        for button, name in getattr(self, "_footer_icons", ()):
            button.setIcon(icons.icon(name, p.ink_muted, size=FOOTER_ICON))
        ratio = max(2.0, self.devicePixelRatioF())
        self.mark.setPixmap(icons.pixmap("mark", p.brand or p.accent, MARK_SIZE, ratio, weight=1.25))

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
        self.refresh_btn.setText("  Refreshing\u2026" if loading else "  Refresh")
        self.progress.setVisible(loading)

    def refresh_by_hand(self, *_signal_args) -> None:
        """Refresh from a button, key or command.

        Qt hands a clicked or triggered slot a `checked` flag; this soaks it
        up so it can never land in one of reload's own parameters.
        """
        self.reload()

    def reload(self, *, auto: bool = False, because: list[str] | None = None,
               force_results: bool = False) -> None:
        """Re-read every source. `auto` is a reload the app started itself;
        `force_results` asks the scoreboard about every unfinished week now."""
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
        loader.force_results = force_results
        # With a season already on the screen, This Week's sums are done before
        # the new one is handed over; the first load fills the window first (_warm_up).
        loader.warm = self.auto_warm and not self.season.is_empty
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
        if getattr(self, "_close_when_published", False):
            self.close()                    # closed mid-load: now it can go

    # ---- results, by themselves ---------------------------------------------
    #: Off for the smoke test and the self-check, which never go online by themselves.
    auto_results = True

    def _results_weeks(self) -> list[int]:
        """Weeks the dashboard grades whose games aren't all decided - and this
        week and next by the calendar, whose first kickoffs lock the odds."""
        season = self.season
        if season is None or season.is_empty:
            return []
        out, owned = set(), set()
        for number, week in season.weeks.items():
            if getattr(week, "source", None) is not None and any(
                    g.played and getattr(g, "result_from", "") in ("", "workbook") for g in week.games):
                owned.add(number)   # the workbook is being filled in by hand
                continue
            if week.games and not all(g.played for g in week.games):
                out.add(number)
        year = getattr(season, "results_year", 0) or 0
        if year:
            out |= set(results.calendar_weeks(year)) - owned
        return sorted(out)

    def check_results(self, *, live: bool | None = None, force: bool = False) -> None:
        """Every minute: ask the scoreboard if a look is due - a game under
        way or about to start; every minute while Game Day is open (`live`)
        - and reload once a game has finished. `force` asks now."""
        if self._closing or not self.auto_results:
            return
        if self._loader is not None and self._loader.isRunning():
            return
        self._fetch_timelines()
        running = getattr(self, "_results_worker", None)
        if running is not None and running.isRunning():
            return
        weeks = self._results_weeks()
        year = getattr(self.season, "results_year", 0) or 0
        if live is None:
            live = self._game_day_showing()
        every = results.LIVE_RECHECK_S if live else None
        if not weeks or not year or not (force or results.due(year, weeks, every=every)):
            return
        graded = [w for w in weeks if w in self.season.weeks]
        worker = ResultsCheck(year, weeks, graded, every=every, force=force)
        worker.found.connect(self._results_found)
        worker.finished.connect(self._results_worker_finished)
        self._results_worker = worker
        worker.start()

    # ---- the website's replay of each week: finished games' scoring plays --------
    _timeline_worker = None

    def _fetch_timelines(self) -> None:
        """Now and then, a few finished games' scoring plays (timeline.py) -
        and the website brought up to date once some arrive."""
        season = self.season
        year = getattr(season, "results_year", 0) or 0
        if season is None or not year:
            return
        running = self._timeline_worker
        if running is not None and running.isRunning():
            return
        weeks = sorted(n for n, w in season.weeks.items() if w.games and all(g.played for g in w.games))
        try:
            from ..feeds import timeline
            if not weeks or not timeline.due(year, weeks):
                return
        except Exception as exc:  # noqa: BLE001
            write_log(f"replay check failed: {exc!r}")
            return
        worker = TimelineFetch(year, weeks)
        worker.fetched.connect(self._timelines_fetched)
        worker.finished.connect(self._timeline_worker_finished)
        self._timeline_worker = worker
        worker.start()

    def _timelines_fetched(self, kept: int) -> None:
        if kept and not self._closing:
            self.update_site()

    def _timeline_worker_finished(self) -> None:
        worker = self._timeline_worker
        if worker is not None and not worker.isRunning():
            self._timeline_worker = None
            worker.deleteLater()

    def _results_found(self, changed: bool) -> None:
        if changed and not self._closing:
            self.reload(auto=True, because=["new results"])

    def _results_worker_finished(self) -> None:
        worker = getattr(self, "_results_worker", None)
        if worker is not None and not worker.isRunning():
            self._results_worker = None
            worker.deleteLater()
        if getattr(self, "_close_when_published", False):
            self.close()
            return
        # Game Day draws the scores as kept, so a look redraws it at once -
        # a finished game reloads everything anyway.
        page = self._game_day_page()
        if page is not None and self._game_day_showing():
            try:
                page.invalidate()
            except Exception as exc:  # noqa: BLE001
                write_log(f"game day redraw failed: {exc!r}")

    def _game_day_page(self) -> GameDayPage | None:
        return next((p for p in getattr(self, "pages", []) if isinstance(p, GameDayPage)), None)

    def _game_day_showing(self) -> bool:
        try:
            return isinstance(self.current_page(), GameDayPage) and bool(self.isVisible())
        except Exception:  # noqa: BLE001 - a window part-built (tests, closing)
            return False

    def check_results_now(self) -> None:
        """Data & Update's button: ask the scoreboard now, whatever the time."""
        self.statusBar().showMessage("Asking ESPN for the latest results\u2026")
        self.reload(force_results=True)

    def _files_changed(self, names: list[str]) -> None:
        """Something the dashboard reads was added, saved or removed."""
        if self._closing:
            return
        self.reload(auto=True, because=names)

    def _tick_updated(self) -> None:
        self.updated_label.setText(updated_text(self._loaded_at))

    def _on_clock(self) -> None:
        self._tick_updated()
        self._watch_lock()
        page = self._game_day_page()
        if page is not None and self._game_day_showing():
            page.tick()

    def _lock_now(self) -> tuple[int, bool] | None:
        """The week ahead, and whether its first game has kicked off."""
        season = self.season
        if season is None or season.is_empty:
            return None
        try:
            week = analytics.upcoming_week(season)
            return week, oddslock.locked_for(season, week)
        except Exception as exc:  # noqa: BLE001 - a missed look is no matter
            write_log(f"odds lock check failed: {exc!r}")
            return None

    def _watch_lock(self) -> None:
        """The week's first game has kicked off: every page shows its odds
        locked at once, not at the next reload."""
        state = self._lock_now()
        before, self._lock_state = getattr(self, "_lock_state", None), state
        if state is None or before is None or state == before or not state[1]:
            return
        for page in self.pages:
            try:
                page.invalidate()
            except Exception as exc:  # noqa: BLE001
                write_log(f"refresh at the odds lock failed on {page.title}: {exc!r}")

    def _on_loaded(self, season: Season) -> None:
        if self._closing:
            return
        first = self.season.is_empty        # nothing was on the screen until now
        self.season = season
        self._retried = False
        self._set_loading(False)
        self._loaded_at = datetime.now()
        self._tick_updated()
        self.updated_label.setToolTip(f"Last read {self._loaded_at:%A %H:%M:%S}")
        playing = season.provisional_weeks[0] if season.provisional_weeks else season.current_week
        self.season_label.setText((
            f"{season.title}  \u00b7  week {playing}"
            if playing
            else season.title
        ).upper())
        self.season_label.setToolTip(
            f"Week {season.current_week} is the last one final; week {playing} is under way"
            if playing != season.current_week else ""
        )
        if season.title:
            self.setWindowTitle(f"{places.BRAND} \u2013 {season.title}")
        # The workbook's folder is only known now; make sure it is watched.
        self.watcher.watch(self._watch_folders())
        for page in self.pages:
            # Pages contain their own refresh errors; this guards the handoff
            # so one page can never stop the rest from getting the new data.
            try:
                page.set_season(season)
            except Exception as exc:  # noqa: BLE001
                write_log(f"set_season failed on {page.title}: {exc!r}")
        self._lock_state = self._lock_now()

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
        elif not season.is_empty:
            # New results or a new pick sheet: the website follows by itself.
            self.update_site()
        self.check_updates()
        if first and not season.is_empty:
            QTimer.singleShot(300, self._warm_up)       # once the opening page is drawn

    #: Off for the smoke test and the self-check, which quit as soon as they are done.
    auto_warm = True

    def _warm_up(self) -> None:
        """This Week's sums, off the window's thread (workers.warm_this_week)."""
        if self._closing or not self.auto_warm or self._warmer is not None:
            return
        warmer = Warmer(self.season)
        warmer.finished.connect(lambda w=warmer: self._on_warmed(w))
        self._warmer = warmer
        warmer.start(QThread.Priority.LowPriority)

    def _on_warmed(self, warmer: Warmer) -> None:
        if self._warmer is warmer:
            self._warmer = None
        warmer.deleteLater()
        if getattr(self, "_close_when_published", False):
            self.close()

    # ---- updates that find themselves (autoupdate.py, updatecheck.py) ------------
    def check_updates(self, *, by_hand: bool = False) -> None:
        """Twice a day by itself after a load, or now by hand; a waiting one is offered."""
        if self._closing or not (by_hand or self.auto_site):
            return
        try:
            from .. import autoupdate
            from . import updatecheck
            if by_hand and getattr(self, "_pending_update", None):
                updatecheck.offer(self)
                return
            if by_hand or (autoupdate.UpdateSettings.load().automatic and autoupdate.due()):
                updatecheck.check(self, by_hand=by_hand)
        except Exception as exc:  # noqa: BLE001 - the dashboard carries on regardless
            write_log(f"update check didn't start: {exc!r}")

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
    # ---- out of sight: the tray (keeping.py) ---------------------------------
    def apply_keeping(self) -> None:
        """Show the tray icon when the dashboard is to keep running in it."""
        from . import keeping
        want = self.remember_state and keeping.tray_wanted() and keeping.tray_available()
        if want and self._tray is None:
            self._tray = keeping.Tray(self)
        elif not want and self._tray is not None:
            self._tray.hide()
            self._tray = None
        try:
            # in the tray, the window closing mustn't end the app
            QApplication.setQuitOnLastWindowClosed(self._tray is None)
        except Exception:  # noqa: BLE001 - no application yet (a test): nothing to tell
            pass

    def quit_for_real(self) -> None:
        """Quit from the tray: close for good, whatever the tray setting."""
        self._quitting = True
        self.showNormal()
        self.close()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._tray is not None and not self._quitting:
            # The tray keeps it going: the window goes, the work carries on.
            if self._state is not None:
                self._state.setValue("window/geometry", self.saveGeometry())
            self.hide()
            event.ignore()
            self._tray.say_once()
            return
        self._closing = True
        if self._tray is not None:
            self._tray.hide()
        self.watcher.set_enabled(False)
        self._clock.stop()
        self._results_timer.stop()
        if self._state is not None:
            self._state.setValue("window/geometry", self.saveGeometry())
            self._state.setValue("window/group", self.stack.currentIndex())
            self._state.setValue("window/place", NAV[self.stack.currentIndex()].title)
            for g, group in enumerate(self.groups):
                self._state.setValue(f"window/tab/{g}", group.current_index())
                self._state.setValue(f"window/tabs/{NAV[g].title}", group.current_index())
        # Quitting with a thread still running would destroy it and crash.
        loader = self._loader
        site = getattr(self, "_site_worker", None)
        check = getattr(self, "_results_worker", None)
        busy = [w for w in (loader, site, check, self._warmer) if w is not None and w.isRunning()]
        if busy and not all(w.wait(5_000 if w is loader else 3_000) for w in busy):
            # Still loading, uploading or asking the scoreboard, and a thread
            # can't be torn down mid-way without crashing: the window goes
            # now, the work finishes out of sight, and the app closes after.
            self._close_when_published = True
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)
        if getattr(self, "_close_when_published", False):
            QApplication.quit()             # a hidden window closing may not end the app by itself


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
    # shown as Operation Sunday; kept under its first name, where its settings are
    app.setApplicationDisplayName(places.BRAND)
    app.setOrganizationName("ACQL")
    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    background = "--background" in argv
    argv = [a for a in argv if a != "--background"]
    from . import keeping
    if not (smoke_test or self_check) and keeping.hand_over(show=not background):
        return 0                        # already running: that one comes forward instead
    if not (smoke_test or self_check):
        from . import teamlogos
        teamlogos.fetch_all()           # first run only: after that they're on disk
    window = MainWindow(remember_state=not smoke_test)
    if not (smoke_test or self_check):
        window._doorbell = keeping.listen(window)
    if smoke_test or self_check:
        window.auto_site = False        # checking the app must never publish the website
        window.auto_results = False     # nor go online by itself
        window.auto_warm = False        # nor leave a thread working when it quits
    if background and window._tray is not None and not (smoke_test or self_check):
        app.setQuitOnLastWindowClosed(False)    # started with Windows: straight to the tray
    else:
        window.show()
    if window._tray is not None:
        app.setQuitOnLastWindowClosed(False)    # closing the window leaves it in the tray

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
