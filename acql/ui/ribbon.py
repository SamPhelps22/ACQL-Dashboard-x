"""The scoreboard ribbon: the week's games across the top of every page.

One row of Game Day's score chips under the window's edge, like a sports
network's ticker - the games on now, then the ones still to play by kickoff,
then the finals - shown only while a week is being played. Your pick in each
game is in gold. A chip opens Game Day at that game's card (app.py does the
opening). The scores are the ones Game Day reads: what ESPN gave at the last
look (pool/gameday.py), so the ribbon and the page never disagree.

At its right end: the slate in numbers, the next kickoff counting down, a
warning only when the scores on screen are stale or the last look failed,
and the way into Cinema mode (cinema.py). A score that really changed at the
last good look washes gold once; a game changing state fades into its new
look once (both decided by cinema.LiveFeed, never by a redraw).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton, QVBoxLayout, QWidget

from ..feeds import results
from ..pool import gameday as GD
from ..pool import livestate as LS
from . import icons
from .pages.gameday import ME_KEY, ScoreChip

#: One chip's width, and the gap between chips.
CHIP_WIDTH = 172
CHIP_GAP = 6
#: How far one press of an arrow moves the ribbon, in chips.
STEP_CHIPS = 3
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def playing_week(season, now: float | None = None) -> int:
    """The week being played by the calendar - from its Wednesday to the
    next - when the season has its games; 0 between seasons or before the
    first week starts."""
    if season is None or season.is_empty:
        return 0
    now = time.time() if now is None else now
    year = results.season_year(season, now)
    weeks = results.calendar_weeks(year, now)
    if not weeks or results.week_starts(year, weeks[0]) > now:
        return 0
    found = season.weeks.get(weeks[0])
    return weeks[0] if found is not None and found.games else 0


def in_order(states: list) -> list:
    """Games on now, then the ones still to play by kickoff, then the finals,
    the latest first - the order a ticker runs in."""
    live = sorted((s for s in states if s.state == "in"), key=lambda s: (s.kickoff or 0, s.index))
    upcoming = sorted((s for s in states if s.state in ("pre", "off")),
                      key=lambda s: (s.kickoff or float("inf"), s.index))
    final = sorted((s for s in states if s.state == "final"), key=lambda s: (-(s.kickoff or 0), s.index))
    return live + upcoming + final


def kickoff_words(at: float | None) -> str:
    """"Sun 1:00 PM" - the day and the exact time, never a countdown."""
    if not at:
        return ""
    when = time.localtime(at)
    hour = when.tm_hour % 12 or 12
    return f"{DAYS[when.tm_wday]} {hour}:{when.tm_min:02d} {'AM' if when.tm_hour < 12 else 'PM'}"


def viewer(season) -> str:
    """Whose picks are shown in gold: the owner of this copy, or whoever Game
    Day was last told you are."""
    from ..pool import me
    try:
        owner = me.key(season)
    except Exception:  # noqa: BLE001 - nobody is no matter
        owner = ""
    if owner:
        return owner
    for name in (ME_KEY, "thisweek/suicide_coach"):
        value = QSettings().value(name, "")
        if isinstance(value, str) and value:
            return value
    return ""


class RibbonChip(ScoreChip):
    """One game on the ribbon: Game Day's chip at a fixed width, pressable."""

    pressed = Signal(int)          # the game's index

    def __init__(self, st, you, fresh=None) -> None:
        super().__init__(st, you)
        self.index = st.index
        self.setFixedWidth(CHIP_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if st.state == "pre" and st.kickoff:
            self.state_label.setText(kickoff_words(st.kickoff))
        cs = LS.card_state(st.state, feed=fresh)
        self.setProperty("status", cs.status)
        self.setProperty("warn", cs.warn)
        tip = self.toolTip() + "\nOpen it on Game Day"
        if cs.warn and fresh is not None:
            tip += "\n" + fresh.headline()
        self.setToolTip(tip)

    def flash_score(self, gold: str) -> None:
        from .cinema import flash
        for label in self.findChildren(QLabel, "ChipScore"):
            if label.text():
                flash(label, gold)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.pressed.emit(self.index)
        super().mouseReleaseEvent(event)


class _Track(QScrollArea):
    """The chips' track: scrolled sideways by the wheel as well as the arrows."""

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        delta = event.angleDelta()
        step = delta.x() or delta.y()
        if not step:
            return super().wheelEvent(event)
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - step)
        event.accept()


class ScoreboardRibbon(QFrame):
    """The week's games in one sideways-scrolling row, above every page."""

    game_chosen = Signal(int, int)     # week, game index
    cinema_wanted = Signal()

    def __init__(self, palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ScoreRibbon")
        self.palette_ = palette
        self.week = 0
        self.states: list = []
        self.chips: list[RibbonChip] = []
        self._key: tuple | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 6, 8, 6)
        row.setSpacing(8)

        self.mark = QLabel()
        self.mark.setObjectName("RibbonIcon")
        row.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(0)
        self.title = QLabel("")
        self.title.setObjectName("RibbonTitle")
        self.count = QLabel("")
        self.count.setObjectName("RibbonCount")
        words.addStretch(1)
        words.addWidget(self.title)
        words.addWidget(self.count)
        words.addStretch(1)
        row.addLayout(words)

        self.back = self._arrow("chevron-left", "Earlier games", -1)
        row.addWidget(self.back)

        self.track = _Track()
        self.track.setObjectName("RibbonTrack")
        self.track.setFrameShape(QFrame.Shape.NoFrame)
        self.track.setWidgetResizable(True)
        self.track.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.track.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lane = QWidget()
        self.lane.setObjectName("RibbonLane")
        self.lane_row = QHBoxLayout(self.lane)
        self.lane_row.setContentsMargins(0, 0, 0, 0)
        self.lane_row.setSpacing(CHIP_GAP)
        self.lane_row.addStretch(1)
        self.track.setWidget(self.lane)
        self.track.horizontalScrollBar().rangeChanged.connect(lambda *_: self._sync_arrows())
        self.track.horizontalScrollBar().valueChanged.connect(lambda *_: self._sync_arrows())
        row.addWidget(self.track, 1)

        self.ahead = self._arrow("chevron-right", "Later games", 1)
        row.addWidget(self.ahead)

        # the next kickoff, the feed's health and Cinema mode
        clock = QVBoxLayout()
        clock.setSpacing(0)
        self.next_label = QLabel("")
        self.next_label.setObjectName("RibbonCount")
        self.countdown = QLabel("")
        self.countdown.setObjectName("RibbonCountdown")
        clock.addStretch(1)
        clock.addWidget(self.next_label, 0, Qt.AlignmentFlag.AlignRight)
        clock.addWidget(self.countdown, 0, Qt.AlignmentFlag.AlignRight)
        clock.addStretch(1)
        row.addLayout(clock)
        self.fresh_pill = QLabel("")
        self.fresh_pill.setObjectName("RibbonFresh")
        self.fresh_pill.hide()
        row.addWidget(self.fresh_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.cinema_btn = QToolButton()
        self.cinema_btn.setObjectName("RibbonCinema")
        self.cinema_btn.setText("CINEMA")
        self.cinema_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.cinema_btn.setToolTip("Cinema mode: the week full screen (F11; Esc to come back)")
        self.cinema_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cinema_btn.clicked.connect(lambda *_: self.cinema_wanted.emit())
        row.addWidget(self.cinema_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.fresh: LS.Freshness | None = None
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._tick_clock)
        self.restyle(palette)
        self.hide()

    def _arrow(self, icon: str, tip: str, way: int) -> QToolButton:
        button = QToolButton()
        button.setObjectName("RibbonArrow")
        button.setProperty("icon_name", icon)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRepeat(True)
        button.clicked.connect(lambda *_: self.scroll_by(way))
        return button

    def restyle(self, palette) -> None:
        self.palette_ = palette
        self.mark.setPixmap(icons.pixmap("football", palette.brand or palette.accent, 18))
        self.cinema_btn.setIcon(icons.icon("screen", palette.ink_secondary, palette.accent, 16))
        for button in (self.back, self.ahead):
            button.setIcon(icons.icon(button.property("icon_name"), palette.ink_secondary, palette.accent, 16))

    # ---- what it shows ------------------------------------------------------
    def set_season(self, season, *, now: float | None = None, kept=None) -> None:
        """Read the week being played again and redraw if anything changed."""
        week = playing_week(season, now)
        states, you = [], None
        if week:
            states = GD.games_now(season, week, kept=kept)
            key = viewer(season)
            if key and states:
                mine = next((c for c in GD.cards(season, week, states, key) if c.you), None)
                you = mine
        self.show_games(week, states, you)

    def set_feed(self, feed, season, changes=None) -> None:
        """The week as the window's LiveFeed read it (cinema.py): drawn, then
        whatever really changed at the last good look played once."""
        you = None
        if feed.week and feed.states:
            key = viewer(season)
            if key:
                you = next((c for c in GD.cards(season, feed.week, feed.states, key) if c.you), None)
        self.fresh = feed.fresh
        self.show_games(feed.week, feed.states, you)
        if changes:
            from .cinema import pulse
            gold = self.palette_.brand or self.palette_.accent
            for chip in self.chips:
                if chip.index in changes.states:
                    pulse(chip)
                if chip.index in changes.scores:
                    chip.flash_score(gold)

    def show_games(self, week: int, states: list, you) -> None:
        ordered = in_order(states) if week else []
        picks = tuple(sorted(you.picks.items())) if you is not None else ()
        warn = self.fresh is not None and (self.fresh.warn or self.fresh.level == "error")
        key = (week, picks, warn, tuple((s.index, s.state, s.home_points, s.away_points, s.clock, s.kickoff,
                                         s.possession) for s in ordered))
        self._show_fresh()
        if key == self._key:
            self._tick_clock()
            return
        self._key = key
        self.week, self.states = week, ordered
        for chip in self.chips:
            self.lane_row.removeWidget(chip)
            chip.deleteLater()
        self.chips = []
        for st in ordered:
            chip = RibbonChip(st, you, self.fresh)
            chip.pressed.connect(lambda index: self.game_chosen.emit(self.week, index))
            self.lane_row.insertWidget(len(self.chips), chip)
            self.chips.append(chip)
        live = sum(1 for s in ordered if s.state == "in")
        final = sum(1 for s in ordered if s.state == "final")
        self.title.setText(f"WEEK {week}")
        slate = LS.slate(week, ordered)
        self.count.setText(f"{live} LIVE \u00b7 {final} OF {slate.total} FINAL" if live else
                           "FINAL" if final == len(ordered) else
                           f"{final} OF {slate.total} FINAL" if final else f"{slate.total} GAMES")
        self.count.setToolTip(slate.text())
        self.count.setProperty("live", "true" if live else "")
        self.count.style().unpolish(self.count)
        self.count.style().polish(self.count)
        self.setVisible(bool(ordered))
        self._tick_clock()
        QTimer.singleShot(0, self._sync_arrows)

    def _show_fresh(self) -> None:
        """Said only when something is wrong: fresh data needs no badge."""
        fresh = self.fresh
        if fresh is None or fresh.level in ("fresh", "waiting"):
            self.fresh_pill.hide()
            return
        words = {"stale": f"STALE \u00b7 {fresh.age_text().upper()}", "failed": "REFRESH FAILED",
                 "error": "NO SCORES YET"}[fresh.level]
        self.fresh_pill.setText(words)
        self.fresh_pill.setToolTip("\n".join(filter(None, [fresh.headline(), fresh.detail()])))
        if self.fresh_pill.property("level") != fresh.level:
            self.fresh_pill.setProperty("level", fresh.level)
            self.fresh_pill.style().unpolish(self.fresh_pill)
            self.fresh_pill.style().polish(self.fresh_pill)
        self.fresh_pill.show()

    def _tick_clock(self) -> None:
        """The next kickoff to the second, and the data's age - labels only,
        nothing redrawn. Ticks only while the ribbon is up and a kickoff is ahead."""
        now = time.time()
        nxt = LS.next_kickoff(self.states, now) if self.states else None
        if nxt is not None:
            self.next_label.setText(f"NEXT \u00b7 {kickoff_words(nxt.at).upper()}")
            self.countdown.setText(LS.countdown_text(nxt.at - now))
        elif self.states and LS.kicking_off(self.states, now):
            self.next_label.setText("KICKOFF")
            self.countdown.setText("DUE NOW")
        else:
            self.next_label.setText("")
            self.countdown.setText("")
        if self.fresh is not None and self.fresh.last_success:
            level = self.fresh.level
            self.fresh = LS.freshness(self.fresh.category, self.fresh.last_success, self.fresh.last_attempt,
                                      failed=level in ("failed", "error"), error=self.fresh.error,
                                      live=self.live, now=now)
            if self.fresh.level != level or self.fresh.level == "stale":
                self._show_fresh()
        want = nxt is not None and self.isVisible()
        if want and not self._tick.isActive():
            self._tick.start()
        elif not want and self._tick.isActive():
            self._tick.stop()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._tick_clock()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._tick.stop()
        super().hideEvent(event)

    @property
    def live(self) -> bool:
        """A game on, as last drawn - the window asks the scoreboard every
        minute while one is."""
        return any(s.state == "in" for s in self.states)

    # ---- moving along -------------------------------------------------------
    def scroll_by(self, way: int) -> None:
        bar = self.track.horizontalScrollBar()
        bar.setValue(bar.value() + way * STEP_CHIPS * (CHIP_WIDTH + CHIP_GAP))

    def _sync_arrows(self) -> None:
        bar = self.track.horizontalScrollBar()
        overflow = bar.maximum() > 0
        self.back.setVisible(overflow)
        self.ahead.setVisible(overflow)
        self.back.setEnabled(bar.value() > bar.minimum())
        self.ahead.setEnabled(bar.value() < bar.maximum())
