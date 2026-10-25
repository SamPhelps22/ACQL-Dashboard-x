"""Cinema mode: the week being played as a broadcast, full screen.

The analytics workspace steps aside for a scoreboard: every game large, the
next kickoff counting down, a strip of the pool's standings, what just
happened, and - discreetly - how fresh the data is. Escape, F11 or the Exit
button goes back to the window as it was.

It reads exactly what the ribbon and Game Day read - the scores as kept by
the window's own every-30-seconds look (feeds/results.py) and the pool's
standings as gameday.board works them out - and asks for nothing itself. What
changed between two good looks is decided once, in `LiveFeed`, which the
window feeds; the ribbon and this screen both play its changes, once.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPropertyAnimation, Qt, QTimer, QVariantAnimation,
                            Signal)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .. import places
from ..feeds import results
from ..model.predictions import display_team
from ..pool import gameday as GD
from ..pool import livestate as LS
from ..version import MODEL_NAME
from . import icons, motion, teamlogos
from .theme import DISPLAY_STACK, MONO_STACK, mix
from .tokens import MOTION, RADIUS
from .widgets import ElidedLabel

#: The slate's columns by the width it has (the screen less the side column):
#: four on a large monitor, two on a laptop.
COLUMNS = ((1400, 4), (1050, 3), (0, 2))
#: The side column: standings, what just happened, the feed's health.
SIDE_WIDTH = 380
#: One row of the standings strip.
ROW_HEIGHT = 30
#: What just happened: how many moments are kept, and shown.
RECENT_KEPT, RECENT_SHOWN = 30, 7


# ---- what changed: one decision, played by every screen ----------------------------------
@dataclass(frozen=True)
class Changes:
    week: int
    scores: frozenset = frozenset()                       # game indices whose score really changed
    states: dict = field(default_factory=dict)            # game index -> (state before, state now)

    def __bool__(self) -> bool:
        return bool(self.scores or self.states)


class LiveFeed(QObject):
    """The week being played as the window last read it, and what changed
    between two good looks at the scoreboard. Owned by the window; it lives
    for the session, so closing and opening Cinema mode, switching pages or
    redrawing never plays a change twice."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.week = 0
        self.year = 0
        self.states: list = []
        self.kept: list = []
        self.fresh: LS.Freshness | None = None
        self.recent: deque = deque(maxlen=RECENT_KEPT)
        self._scores = LS.ScoreWatch()
        self._game_states = LS.StateWatch()
        self.standings = LS.StandingsWatch()

    @property
    def live(self) -> bool:
        return any(s.state == "in" for s in self.states)

    def update(self, season, *, now: float | None = None) -> Changes:
        """Read the week being played again; say what really changed."""
        from .ribbon import playing_week
        week = playing_week(season, now)
        if week != self.week:                    # a new week: a new baseline, nothing "changed"
            self._scores, self._game_states, self.standings = LS.ScoreWatch(), LS.StateWatch(), LS.StandingsWatch()
            self.recent.clear()
        self.week = week
        self.year = results.season_year(season, now) if week else 0
        self.kept = results.load(self.year, week) if week else []
        self.states = GD.games_now(season, week, kept=self.kept) if week else []
        self.fresh = LS.scores_freshness(self.year, week, live=self.live, now=now) if week else None
        if not week or not self.states:
            return Changes(week)
        # only a good look is compared: the scores on screen came from it
        token = self.fresh.last_success if self.fresh is not None else None
        if token is None:
            return Changes(week)
        scores = {st.index: (st.home_points, st.away_points) if st.started else None for st in self.states}
        moved = frozenset(self._scores.accept(scores, token=token))
        turned = self._game_states.accept({st.index: st.state for st in self.states})
        at = token
        by_index = {st.index: st for st in self.states}
        for index, (before, after) in sorted(turned.items()):
            st = by_index[index]
            if after == "in" and before in ("pre", "off"):
                self.recent.appendleft((at, f"Kickoff · {_matchup(st)}", "state"))
            elif after == "final":
                self.recent.appendleft((at, f"Final · {_score_line(st)}", "final"))
        for index in sorted(moved):
            st = by_index[index]
            if index not in turned or turned[index][1] != "final":
                self.recent.appendleft((at, f"{st.clock or 'Score'} · {_score_line(st)}", "score"))
        return Changes(week, moved, turned)


def _matchup(st) -> str:
    return f"{display_team(st.game.away)} at {display_team(st.game.home)}"


def _score_line(st) -> str:
    a = "" if st.away_points is None else f" {st.away_points}"
    h = "" if st.home_points is None else f" {st.home_points}"
    return f"{display_team(st.game.away)}{a}, {display_team(st.game.home)}{h}"


# ---- motion, once ------------------------------------------------------------------------
def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_prop(widget: QWidget, name: str, value: str) -> None:
    """A style property, repolished only when it really changed (no flicker)."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        _repolish(widget)


def flash(widget: QWidget, gold: str) -> None:
    """The gold wash on a score that really changed: in, then away, once.
    With reduced motion, a still gold outline for the same time instead."""
    if motion.reduced():
        set_prop(widget, "flash", "still")
        def clear() -> None:
            try:
                set_prop(widget, "flash", "")
            except RuntimeError:        # the label went with a redraw
                pass
        QTimer.singleShot(MOTION["flash"], clear)
        return
    colour = QColor(gold)
    anim = QVariantAnimation(widget)
    anim.setDuration(MOTION["flash"])
    anim.setStartValue(150)
    anim.setEndValue(0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def paint(alpha) -> None:
        widget.setStyleSheet(f"background-color: rgba({colour.red()},{colour.green()},{colour.blue()},{int(alpha)});"
                             f" border-radius: {RADIUS['sm']}px;")
    anim.valueChanged.connect(paint)
    anim.finished.connect(lambda: widget.setStyleSheet(""))
    anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)


def pulse(widget: QWidget) -> None:
    """A card changing state: a short fade up into its new look."""
    if motion.reduced() or not widget.isVisible():
        return
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.45)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(MOTION["state"])
    anim.setStartValue(0.45)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


# ---- one game, large ---------------------------------------------------------------------
class CinemaTile(QFrame):
    """One game as the broadcast shows it. Its status (upcoming, live, final,
    postponed), whether it is the chosen card and any data warning are three
    separate properties, each drawn its own way."""

    chosen = Signal(int)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.setObjectName("CinemaTile")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)
        top = QHBoxLayout()
        self.state = QLabel()
        self.state.setObjectName("CinemaState")
        top.addWidget(self.state)
        top.addStretch(1)
        self.warn = QLabel()
        self.warn.setObjectName("CinemaWarn")
        self.warn.hide()
        top.addWidget(self.warn)
        self.tv = QLabel()
        self.tv.setObjectName("CinemaMeta")
        top.addWidget(self.tv)
        box.addLayout(top)
        self.logos: dict[int, QLabel] = {}
        self.teams: dict[int, ElidedLabel] = {}
        self.scores: dict[int, QLabel] = {}
        for side in (GD.AWAY, GD.HOME):
            row = QHBoxLayout()
            row.setSpacing(10)
            logo = QLabel()
            logo.setFixedSize(28, 28)
            row.addWidget(logo)
            team = ElidedLabel()
            team.setObjectName("CinemaTeam")
            row.addWidget(team, 1)
            score = QLabel()
            score.setObjectName("CinemaScore")
            score.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            score.setMinimumWidth(64)
            row.addWidget(score)
            box.addLayout(row)
            self.logos[side], self.teams[side], self.scores[side] = logo, team, score
        self.line = ElidedLabel()
        self.line.setObjectName("CinemaMeta")
        box.addWidget(self.line)
        self.model = ElidedLabel()
        self.model.setObjectName("CinemaModel")
        box.addWidget(self.model)
        self.stake = ElidedLabel()
        self.stake.setObjectName("CinemaMeta")
        self.stake.hide()
        box.addWidget(self.stake)
        self._drawn: tuple | None = None

    def show_game(self, st, mine: int, market: str, cs: LS.CardState, kick_text: str, stake: str = "") -> None:
        drawn = (st.state, st.home_points, st.away_points, st.clock, st.possession, mine, market, cs, kick_text,
                 stake, st.red_zone, st.espn)
        if drawn == self._drawn:
            return                       # nothing new: nothing redrawn
        self._drawn = drawn
        if cs.status == "live":
            state = f"● LIVE · {st.clock}" if st.clock else "● LIVE"
            if st.red_zone:
                state += " · RED ZONE"
        elif cs.status == "final":
            state = (st.clock or "Final").upper()
        elif cs.status == "postponed":
            state = "POSTPONED"
        else:
            state = kick_text or "KICKOFF TIME TO COME"
        self.state.setText(state)
        self.tv.setText(st.broadcast if cs.status != "final" else "")
        self.warn.setText({"stale": "▲ STALE DATA", "error": "▲ DATA ERROR"}.get(cs.warn, ""))
        self.warn.setVisible(bool(cs.warn))
        margin = st.margin
        for side, name, points in ((GD.AWAY, st.game.away, st.away_points), (GD.HOME, st.game.home, st.home_points)):
            logo = teamlogos.pixmap(name, 28)
            if logo is not None:
                self.logos[side].setPixmap(logo)
            ball = " ◂" if cs.status == "live" and st.possession == ("home" if side == GD.HOME else "away") else ""
            self.teams[side].setText(display_team(name) + ball)
            behind = st.decided and margin is not None and ((margin < 0) if side == GD.HOME else (margin > 0))
            set_prop(self.teams[side], "pick", "true" if mine and side == mine else "")
            set_prop(self.teams[side], "faded", "true" if behind else "")
            set_prop(self.scores[side], "faded", "true" if behind else "")
            self.scores[side].setText("" if points is None or not st.started else str(points))
        self.line.setText(" · ".join(filter(None, [f"Pool line {st.line_text()}", market, st.standing_text()])))
        if cs.status == "final":
            self.model.setText("")
        else:
            fav = GD.HOME if st.p_home >= st.p_away else GD.AWAY
            self.model.setText(f"{MODEL_NAME.upper()}  {display_team(st.team(fav))} {st.chance(fav):.0%} to be credited"
                               + ("  · ESPN live" if st.espn is not None else ""))
        self.stake.setText(stake)
        self.stake.setVisible(bool(stake))
        set_prop(self, "status", cs.status)
        set_prop(self, "selected", "true" if cs.selected else "")
        set_prop(self, "warn", cs.warn)
        tip = [st.game.label, f"Pool line: {st.line_text()}"]
        if mine:
            tip.append(f"Your pick: {display_team(st.team(mine))}")
        if cs.warn:
            tip.append("The scores here may be out of date - see the feed's health on the right.")
        self.setToolTip("\n".join(tip))
        self.setAccessibleName(f"{st.game.label}, {state.replace(chr(0x25cf), '').strip()}"
                               + (", selected" if cs.selected else ""))

    def flash_score(self, gold: str) -> None:
        for label in self.scores.values():
            if label.text():
                flash(label, gold)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.chosen.emit(self.index)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.chosen.emit(self.index)
            return
        super().keyPressEvent(event)


# ---- the standings strip -----------------------------------------------------------------
class _Row(QFrame):
    def __init__(self, key: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("CinemaRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)
        self.place = QLabel()
        self.place.setObjectName("CinemaPlace")
        self.place.setFixedWidth(30)
        self.name = ElidedLabel()
        self.name.setObjectName("CinemaName")
        self.points = QLabel()
        self.points.setObjectName("CinemaPoints")
        self.points.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.points.setMinimumWidth(34)
        row.addWidget(self.place)
        row.addWidget(self.name, 1)
        row.addWidget(self.points)
        self.anim: QPropertyAnimation | None = None
        self.counter: QVariantAnimation | None = None


class Leaderboard(QWidget):
    """The pool's week, best first, as gameday.board ranks it. A row moving
    place glides there; a total that rose counts up, once. Nothing here
    ranks anyone: the order and the ties are the board's."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: dict[str, _Row] = {}
        self.order: list[str] = []
        self.gold = "#e8b84e"

    def show_rows(self, rows: list[tuple[str, int, int, bool]], movement: LS.Movement) -> None:
        """`rows`: (name, place, points now, you) in the board's order."""
        reduced = motion.reduced()
        keep = {name for name, *_ in rows}
        for name in list(self.rows):
            if name not in keep:
                self.rows.pop(name).deleteLater()
        self.order = [name for name, *_ in rows]
        for i, (name, place, points, you) in enumerate(rows):
            row = self.rows.get(name)
            fresh = row is None
            if fresh:
                row = _Row(name, self)
                row.resize(self.width(), ROW_HEIGHT)
                row.move(0, i * ROW_HEIGHT)
                row.show()
                self.rows[name] = row
            row.place.setText(str(place))
            row.name.setText(name)
            set_prop(row, "you", "true" if you else "")
            target = QPoint(0, i * ROW_HEIGHT)
            if not fresh and name in movement.moved and not reduced and row.pos() != target:
                if row.anim is not None:
                    row.anim.stop()
                row.anim = QPropertyAnimation(row, b"pos", row)
                row.anim.setDuration(MOTION["rank"])
                row.anim.setStartValue(row.pos())
                row.anim.setEndValue(target)
                row.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                row.anim.start()
            else:
                if row.anim is not None:
                    row.anim.stop()
                row.move(target)
            gain = movement.gained.get(name)
            if gain is not None and not fresh:
                self._count(row, gain[0], gain[1], reduced)
            elif row.counter is None or row.counter.state() != QVariantAnimation.State.Running:
                row.points.setText(str(points))
        self.setFixedHeight(max(1, len(rows)) * ROW_HEIGHT)

    def _count(self, row: _Row, before: int, after: int, reduced: bool) -> None:
        if row.counter is not None:
            row.counter.stop()
        flash(row.points, self.gold)
        if reduced:
            row.points.setText(str(after))
            return
        row.counter = QVariantAnimation(row)
        row.counter.setDuration(MOTION["count"])
        row.counter.setStartValue(before)
        row.counter.setEndValue(after)
        row.counter.valueChanged.connect(lambda v, r=row: r.points.setText(str(int(v))))
        row.counter.finished.connect(lambda r=row, a=after: r.points.setText(str(a)))
        row.counter.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        for row in self.rows.values():
            row.resize(self.width(), ROW_HEIGHT)


# ---- the screen --------------------------------------------------------------------------
class CinemaWindow(QWidget):
    """The broadcast. Built by the window (app.py), fed by it, and closed back to it."""

    closed = Signal()

    def __init__(self, window, feed: LiveFeed, palette) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.window_ = window
        self.feed = feed
        self.palette_ = palette
        self.selected: int | None = None
        self.tiles: dict[int, CinemaTile] = {}
        self._columns = 0
        self.standings_at: float | None = None
        self.standings_from: float | None = None
        self._you = None
        self._order: list[int] = []
        #: The stakes quad (Q): only the four live games that matter most to you.
        self.quad = False
        self._stakes: list[tuple[int, float]] = []
        self._quad_was: set[int] = set()
        self.setObjectName("Cinema")
        self.setWindowTitle(f"{places.BRAND} – Cinema mode")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 20, 28, 20)
        outer.setSpacing(16)
        outer.addWidget(self._build_head())
        body = QHBoxLayout()
        body.setSpacing(20)
        self.slate_area = QScrollArea()
        self.slate_area.setObjectName("CinemaScroll")
        self.slate_area.setFrameShape(QFrame.Shape.NoFrame)
        self.slate_area.setWidgetResizable(True)
        self.slate_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lane = QWidget()
        lane.setObjectName("CinemaLane")
        self.grid = QGridLayout(lane)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.empty = QLabel()
        self.empty.setObjectName("CinemaEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.hide()
        self.slate_area.setWidget(lane)
        body.addWidget(self.slate_area, 1)
        body.addWidget(self._build_side())
        outer.addLayout(body, 1)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._tick_clock)
        self.restyle(palette)

    # ---- the parts -------------------------------------------------------------------
    def _build_head(self) -> QWidget:
        head = QFrame()
        head.setObjectName("CinemaHead")
        row = QHBoxLayout(head)
        row.setContentsMargins(20, 12, 12, 12)
        row.setSpacing(24)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        self.brand = QLabel(places.BRAND.upper())
        self.brand.setObjectName("CinemaBrand")
        self.week_label = QLabel()
        self.week_label.setObjectName("CinemaWeek")
        brand.addWidget(self.brand)
        brand.addWidget(self.week_label)
        row.addLayout(brand)
        self.counts: dict[str, QLabel] = {}
        for key, words in (("total", "GAMES"), ("live", "LIVE"), ("final", "FINAL"), ("upcoming", "TO PLAY")):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            number = QLabel("–")
            number.setObjectName("CinemaCount")
            number.setProperty("kind", key)
            caption = QLabel(words)
            caption.setObjectName("CinemaCaption")
            cell.addWidget(number, 0, Qt.AlignmentFlag.AlignHCenter)
            cell.addWidget(caption, 0, Qt.AlignmentFlag.AlignHCenter)
            row.addLayout(cell)
            self.counts[key] = number
        row.addStretch(1)
        clock = QVBoxLayout()
        clock.setSpacing(0)
        self.next_caption = QLabel("NEXT KICKOFF")
        self.next_caption.setObjectName("CinemaCaption")
        self.countdown = QLabel("")
        self.countdown.setObjectName("CinemaCountdown")
        self.next_detail = ElidedLabel("")
        self.next_detail.setObjectName("CinemaMeta")
        self.next_detail.setMinimumWidth(260)
        clock.addWidget(self.next_caption, 0, Qt.AlignmentFlag.AlignRight)
        clock.addWidget(self.countdown, 0, Qt.AlignmentFlag.AlignRight)
        clock.addWidget(self.next_detail, 0, Qt.AlignmentFlag.AlignRight)
        row.addLayout(clock)
        self.quad_label = QLabel("Q · stakes quad")
        self.quad_label.setObjectName("CinemaCaption")
        self.quad_label.setToolTip("Q shows only the four live games that matter most to your week, re-ranked "
                                   "on every score; Q again shows every game")
        row.addWidget(self.quad_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.exit_btn = QPushButton("  Exit  (Esc)")
        self.exit_btn.setObjectName("CinemaExit")
        self.exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exit_btn.setToolTip("Back to the dashboard (Esc or F11)")
        self.exit_btn.clicked.connect(self.leave)
        row.addWidget(self.exit_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return head

    def _build_side(self) -> QWidget:
        side = QFrame()
        side.setObjectName("CinemaSide")
        side.setFixedWidth(SIDE_WIDTH)
        box = QVBoxLayout(side)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)

        def heading(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("CinemaHeading")
            return label
        box.addWidget(heading("POOL · IF IT ENDED NOW"))
        self.board_scroll = QScrollArea()
        self.board_scroll.setObjectName("CinemaScroll")
        self.board_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.board_scroll.setWidgetResizable(True)
        self.board_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.board = Leaderboard()
        self.board_scroll.setWidget(self.board)
        box.addWidget(self.board_scroll, 3)
        self.board_note = QLabel("")
        self.board_note.setObjectName("CinemaMeta")
        self.board_note.setWordWrap(True)
        box.addWidget(self.board_note)
        box.addWidget(heading("JUST HAPPENED"))
        self.recent = QLabel("")
        self.recent.setObjectName("CinemaRecent")
        self.recent.setWordWrap(True)
        self.recent.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        box.addWidget(self.recent, 2)
        box.addWidget(heading("SYSTEM"))
        self.health = QLabel("")
        self.health.setObjectName("CinemaHealth")
        self.health.setWordWrap(True)
        box.addWidget(self.health)
        return side

    def restyle(self, palette) -> None:
        self.palette_ = palette
        self.board.gold = palette.brand or palette.accent
        self.setStyleSheet(stylesheet(palette))
        self.exit_btn.setIcon(icons.icon("cross", palette.ink, palette.ink, 16))

    # ---- in and out --------------------------------------------------------------------
    def enter(self) -> None:
        from . import extras
        screen = extras.cinema_screen(self.window_.screen())
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.refresh(Changes(self.feed.week))
        if not motion.reduced():
            self.setWindowOpacity(0.0)
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
        if not motion.reduced():
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(MOTION["cinema"])
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def leave(self) -> None:
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            self.leave()
            return
        if event.key() == Qt.Key.Key_Q:
            self.toggle_quad()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._tick.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._tick.stop()               # nothing ticks while nobody can see it
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._tick.stop()
        super().closeEvent(event)
        self.closed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._columns and self._columns != self._columns_for(self.width()):
            self._place_tiles()

    # ---- what it shows -------------------------------------------------------------------
    def refresh(self, changes: Changes | None = None) -> None:
        """Draw the feed as it stands, then play whatever really changed."""
        feed = self.feed
        season = self.window_.season
        states = list(feed.states)
        self.week_label.setText(f"WEEK {feed.week}" if feed.week else "NO WEEK BEING PLAYED")
        sl = LS.slate(feed.week, states)
        for key, label in self.counts.items():
            label.setText(str(getattr(sl, key)) if feed.week else "–")
        from .ribbon import viewer
        you_key = viewer(season) if feed.week else ""
        bd = None
        if feed.week and states:
            try:
                bd = GD.board(season, feed.week, you_key, kept=feed.kept)
            except Exception:  # noqa: BLE001 - the scores still show without the standings
                bd = None
        you = bd.you.card if bd is not None and bd.you is not None else None
        self._you = you
        try:
            self._stakes = GD.stakes_order(bd) if bd is not None else []
        except Exception:  # noqa: BLE001 - the quad falls back to the live games in order
            self._stakes = []
        self._show_tiles(states, you)
        self._show_board(bd)
        self._show_recent()
        self._show_health()
        self._tick_clock()
        if changes:
            gold = self.palette_.brand or self.palette_.accent
            for index in changes.states:
                tile = self.tiles.get(index)
                if tile is not None:
                    pulse(tile)
            for index in changes.scores:
                tile = self.tiles.get(index)
                if tile is not None:
                    tile.flash_score(gold)

    def _show_tiles(self, states: list, you) -> None:
        feed = self.feed
        if not states:
            for tile in self.tiles.values():
                tile.deleteLater()
            self.tiles = {}
            self.empty.setText("No week is being played right now.\nCinema mode fills in once a week's pick sheet "
                               "is in and its games are on the calendar.")
            if self.grid.indexOf(self.empty) < 0:
                self.grid.addWidget(self.empty, 0, 0)
            self._columns = 0
            self.empty.show()
            return
        self.empty.hide()
        market = self._market()
        ordered = _broadcast_order(states)
        stakes = dict(self._stakes)
        if self.quad:
            ordered = self._quad_states(ordered)
        known = {st.index for st in ordered}
        for index in list(self.tiles):
            if index not in known:
                self.tiles.pop(index).deleteLater()
        for st in ordered:
            tile = self.tiles.get(st.index)
            if tile is None:
                tile = CinemaTile(st.index)
                tile.chosen.connect(self._choose)
                self.tiles[st.index] = tile
            mine = you.picks.get(st.index, GD.NOBODY) if you is not None else GD.NOBODY
            cs = LS.card_state(st.state, selected=st.index == self.selected, feed=feed.fresh)
            kick = LS.kickoff_et(st.kickoff) if st.kickoff else ""
            size = stakes.get(st.index)
            stake = (f"YOUR STAKE  ±{size * 100:.0f} pts on the next touchdown" if size else
                     "No stake for you in this one" if self.quad and size is not None else "")
            tile.show_game(st, mine, market.get(st.index, ""), cs, kick.upper(), stake)
        self._order = [st.index for st in ordered]
        if self.quad:
            now_in = set(self._order)
            for index in now_in - self._quad_was:
                if self._quad_was and index in self.tiles and not motion.reduced():
                    pulse(self.tiles[index])      # a game that has just come into the quad
            self._quad_was = now_in
        self._place_tiles()

    def _market(self) -> dict[int, str]:
        """The scoreboard's betting line for each game, beside the pool's."""
        out = {}
        for st in self.feed.states:
            score, flipped = results.find(self.feed.kept, st.game.away, st.game.home)
            spread = score.home_spread if score is not None else None
            if spread is None:
                continue
            home_margin = -spread if flipped else spread
            if abs(home_margin) < 0.25:
                out[st.index] = "Market pick'em"
                continue
            fav = st.game.home if home_margin > 0 else st.game.away
            out[st.index] = f"Market {display_team(fav)} −{abs(home_margin):g}"
        return out

    def _quad_states(self, ordered: list) -> list:
        """The stakes quad: the live games ranked by your stake (gameday.stakes_order);
        with nothing live, the next kickoffs."""
        by_index = {st.index: st for st in ordered}
        chosen = [by_index[i] for i, _ in self._stakes if i in by_index]
        if not chosen:
            chosen = [st for st in ordered if st.state == "pre"][:GD.QUAD]
        return chosen

    def toggle_quad(self) -> None:
        self.quad = not self.quad
        self._quad_was = set()
        self.quad_label.setText("STAKES QUAD · Q for every game" if self.quad else "Q · stakes quad")
        self._show_tiles(list(self.feed.states), self._you)

    def _columns_for(self, width: int) -> int:
        if self.quad:
            return 2
        room = width - SIDE_WIDTH - 76          # the margins and the gap beside the side column
        return next(n for edge, n in COLUMNS if room >= edge)

    def _place_tiles(self) -> None:
        columns = self._columns_for(self.width() or 1600)
        order = self._order
        placed = [self.grid.itemAt(i).widget() for i in range(self.grid.count())]
        target = [self.tiles[i] for i in order if i in self.tiles]
        if columns == self._columns and placed == target:
            return                     # where it already is: nothing moves
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for n, tile in enumerate(target):
            self.grid.addWidget(tile, n // columns, n % columns)
        rows = (len(target) + columns - 1) // columns
        for r in range(rows + 2):
            self.grid.setRowStretch(r, 1 if r == rows else 0)      # the cards at the top, the room below
        for c in range(4):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)

    def _choose(self, index: int) -> None:
        """A card chosen (click, Enter or Space): gold round it; chosen again, off.
        Only the two cards whose look changed are redrawn."""
        self.selected = None if self.selected == index else index
        self._show_tiles(list(self.feed.states), self._you)

    def _show_board(self, bd) -> None:
        if bd is None or not bd.standings:
            self.board.show_rows([], LS.Movement())
            self.board_note.setText("Standings appear once the week's pick sheet is in."
                                    if self.feed.week else "")
            return
        rows = [(s.card.name, s.place, s.total_now, s.card.you)
                for s in bd.standings if s.place is not None and s.card.name]
        movement = self.feed.standings.accept([(n, p, pts) for n, p, pts, _ in rows])
        if movement or self.standings_at is None:
            self.standings_at = time.time()
        self.standings_from = self.feed.fresh.last_success if self.feed.fresh is not None else None
        self.board.show_rows(rows, movement)
        note = f"Worked out by the pool's rules at {LS.clock_et(self.standings_at, seconds=True)}"
        if self.standings_from:
            note += f", from scores at {LS.clock_et(self.standings_from, seconds=True)}"
        self.board_note.setText(note + ".")

    def _show_recent(self) -> None:
        items = list(self.feed.recent)[:RECENT_SHOWN]
        if not items:
            self.recent.setText("Nothing yet this session - scores that change while the dashboard is open show here.")
            return
        self.recent.setText("\n".join(f"{LS.clock_et(at)}   {text}" for at, text, _kind in items))

    def _show_health(self) -> None:
        fresh = self.feed.fresh
        if fresh is None:
            self.health.setText("Score feed: no week being played.")
            set_prop(self.health, "level", "")
            return
        lines = [f"Scores (ESPN): {fresh.headline()}"]
        if fresh.detail():
            lines.append(fresh.detail())
        self.health.setText("\n".join(lines))
        set_prop(self.health, "level", fresh.level)

    def _tick_clock(self) -> None:
        """Every second while shown: the countdown and the age words only."""
        states = self.feed.states
        now = time.time()
        nxt = LS.next_kickoff(states, now)
        due = LS.kicking_off(states, now)
        sl = LS.slate(self.feed.week, states)
        if nxt is not None:
            self.next_caption.setText("NEXT KICKOFF")
            self.countdown.setText(LS.countdown_text(nxt.at - now))
            names = [st for st in states if st.index in nxt.indices]
            more = f" + {len(names) - 1} more" if len(names) > 1 else ""
            self.next_detail.setText(f"{LS.kickoff_et(nxt.at)} · {_matchup(names[0])}{more}" if names else "")
        elif due:
            self.next_caption.setText("KICKOFF")
            self.countdown.setText("KICKING OFF")
            self.next_detail.setText("Waiting for the scoreboard to show the game under way")
        elif sl.live:
            self.next_caption.setText("ON NOW")
            self.countdown.setText(f"{sl.live} LIVE")
            self.next_detail.setText("No more kickoffs to come" if not sl.upcoming else "")
        elif sl.total and sl.over:
            self.next_caption.setText("SLATE")
            self.countdown.setText("COMPLETE")
            self.next_detail.setText("Every game played is final")
        else:
            self.next_caption.setText("NEXT KICKOFF")
            self.countdown.setText("–")
            self.next_detail.setText("No kickoff time from the scoreboard yet" if sl.total else "")
        if self.feed.fresh is not None:
            fresh = LS.freshness(self.feed.fresh.category, self.feed.fresh.last_success, self.feed.fresh.last_attempt,
                                 failed=self.feed.fresh.level in ("failed", "error"), error=self.feed.fresh.error,
                                 live=self.feed.live, now=now)
            turned = fresh.level != self.feed.fresh.level
            self.feed.fresh = fresh
            self._show_health()
            if turned:                   # fresh -> stale on the clock alone: the cards say so too
                self._show_tiles(list(states), self._you)


def _broadcast_order(states: list) -> list:
    """Games on now, then the next kickoffs, then the finals (latest first),
    postponed games last - the order the ribbon runs in."""
    live = sorted((s for s in states if s.state == "in"), key=lambda s: (s.kickoff or 0, s.index))
    upcoming = sorted((s for s in states if s.state == "pre"), key=lambda s: (s.kickoff or float("inf"), s.index))
    final = sorted((s for s in states if s.state == "final"), key=lambda s: (-(s.kickoff or 0), s.index))
    off = sorted((s for s in states if s.state == "off"), key=lambda s: s.index)
    return live + upcoming + final + off


def stylesheet(p) -> str:
    """Cinema mode's own look: deep graphite, gold for what is chosen and for
    your picks, electric blue for what is live, amber for stale data, red only
    for a real data error."""
    gold = p.brand or p.accent
    blue = p.accent
    amber = p.warning
    red = p.critical
    plane = "#05070a" if p.name == "dark" else p.plane
    panel = mix(p.ink, plane, 0.035) if p.name == "dark" else p.raised
    line = p.grid
    r = RADIUS
    return f"""
    #Cinema {{ background: {plane}; }}
    #Cinema QLabel {{ color: {p.ink}; background: transparent; }}
    #CinemaScroll, #CinemaLane, #CinemaScroll > QWidget > QWidget {{ background: transparent; }}
    #CinemaHead {{ background: {panel}; border: 1px solid {line}; border-top: 1px solid {mix(gold, panel, 0.55)};
                   border-radius: {r['md']}px; }}
    #CinemaBrand {{ color: {gold}; font-size: 11px; font-weight: 700; letter-spacing: 3px; }}
    #CinemaWeek {{ font-family: {DISPLAY_STACK}; font-size: 30px; font-weight: 700; letter-spacing: 2px; }}
    #CinemaCount {{ font-family: {MONO_STACK}; font-size: 26px; font-weight: 700; }}
    #CinemaCount[kind="live"] {{ color: {blue}; }}
    #CinemaCaption {{ color: {p.ink_muted}; font-size: 10px; font-weight: 700; letter-spacing: 2px; }}
    #CinemaCountdown {{ font-family: {MONO_STACK}; font-size: 30px; font-weight: 700; color: {gold}; }}
    #CinemaMeta {{ color: {p.ink_secondary}; font-size: 12px; }}
    #CinemaModel {{ color: {p.ink_muted}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
    QPushButton#CinemaExit {{ background: transparent; color: {p.ink}; border: 1px solid {mix(p.ink, panel, 0.35)};
                              border-radius: {r['sm']}px; padding: 9px 16px; font-weight: 700; letter-spacing: 1px; }}
    QPushButton#CinemaExit:hover, QPushButton#CinemaExit:focus {{ border-color: {gold}; }}
    #CinemaTile {{ background: {panel}; border: 1px solid {line}; border-left: 3px solid {line};
                   border-radius: {r['md']}px; }}
    #CinemaTile:hover {{ border-color: {mix(gold, line, 0.45)}; }}
    #CinemaTile:focus {{ border-color: {mix(gold, line, 0.75)}; }}
    #CinemaTile[status="live"] {{ border-left-color: {blue}; }}
    #CinemaTile[status="final"] {{ background: {mix(p.ink, plane, 0.02) if p.name == 'dark' else p.surface}; }}
    #CinemaTile[status="postponed"] {{ border-style: dashed; }}
    #CinemaTile[warn="stale"] {{ border-top: 2px solid {amber}; }}
    #CinemaTile[warn="error"] {{ border-top: 2px solid {red}; }}
    #CinemaTile[selected="true"] {{ border: 2px solid {gold}; border-left: 3px solid {gold}; }}
    #CinemaTile[selected="true"][status="live"] {{ border-left-color: {blue}; }}
    #CinemaState {{ font-size: 12px; font-weight: 700; letter-spacing: 1.5px; color: {p.ink_secondary}; }}
    #CinemaTile[status="live"] #CinemaState {{ color: {blue}; }}
    #CinemaTile[status="final"] #CinemaState {{ color: {p.ink_muted}; }}
    #CinemaWarn {{ font-size: 11px; font-weight: 700; letter-spacing: 1px; color: {amber}; }}
    #CinemaTile[warn="error"] #CinemaWarn {{ color: {red}; }}
    #CinemaTeam {{ font-size: 19px; font-weight: 600; }}
    #CinemaTeam[pick="true"] {{ color: {gold}; font-weight: 700; }}
    #CinemaTeam[faded="true"], #CinemaScore[faded="true"] {{ color: {p.ink_muted}; }}
    #CinemaScore {{ font-family: {DISPLAY_STACK}; font-size: 34px; font-weight: 700; padding: 0 6px; }}
    #CinemaScore[flash="still"], #CinemaPoints[flash="still"] {{ border: 1px solid {gold}; border-radius: {r['sm']}px; }}
    #CinemaHeading {{ color: {gold}; font-size: 11px; font-weight: 700; letter-spacing: 2px; }}
    #CinemaRow {{ border-bottom: 1px solid {line}; }}
    #CinemaRow[you="true"] {{ background: {mix(gold, plane, 0.10)}; border-left: 3px solid {gold}; }}
    #CinemaRow[you="true"] #CinemaName {{ color: {gold}; font-weight: 700; }}
    #CinemaPlace {{ font-family: {MONO_STACK}; color: {p.ink_muted}; font-size: 13px; }}
    #CinemaName {{ font-size: 14px; }}
    #CinemaPoints {{ font-family: {MONO_STACK}; font-size: 15px; font-weight: 700; padding: 0 4px; }}
    #CinemaRecent {{ font-family: {MONO_STACK}; font-size: 12px; color: {p.ink_secondary}; }}
    #CinemaHealth {{ font-size: 12px; color: {p.ink_secondary}; border-left: 3px solid {p.good}; padding-left: 8px; }}
    #CinemaHealth[level="stale"], #CinemaHealth[level="failed"] {{ border-left-color: {amber}; color: {amber}; }}
    #CinemaHealth[level="error"] {{ border-left-color: {red}; color: {red}; }}
    #CinemaHealth[level="waiting"] {{ border-left-color: {p.ink_muted}; }}
    #CinemaEmpty {{ color: {p.ink_secondary}; font-size: 18px; padding: 60px; }}
    """
