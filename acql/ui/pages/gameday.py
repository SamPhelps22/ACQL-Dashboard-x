"""Game Day: every game as it happens, against the pool's lines.

The scores, the clock and who has the ball for each game on; whether each of
your picks is being credited right now; where you stand in the week and your
chance of finishing first; what to root for; the Big Losers and the suicide
pool as they stand. While this page is open and a game is on, the scoreboard
is asked every minute and the page redraws itself (the window does the
asking - app.py). All the working out is in gameday.py.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ... import gameday as GD
from ...predictions import display_team
from ...version import MODEL_NAME
from ...wording import ordinal as _ordinal, plural as _plural
from ..theme import mix
from ..widgets import Card, ElidedLabel, IconButton, Pill, StatTile, TableModel, make_table, section, tile_grid
from .base import LIVE_CHECK, LIVE_CHECK_NOW, Page

#: Shared with the Report card and Deadeye's details, so every page knows who you are.
ME_KEY = "insights/me"
CARD_COLUMNS = 3
#: A game card needs about this much width; narrower windows get fewer columns.
CARD_MIN_WIDTH = 430
ROOTS_SHOWN = 5
LOSERS_SHOWN = 8
BOARD_HEADERS = ["#", "Coach", "Now", "Games", "Big L.", "Banked", "Can reach", "To win", "If it ended now"]


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0.005 else "-" if value < -0.005 else ""
    return f"{sign}${abs(value):,.2f}"


def _ago(at: float | None, now: float | None = None) -> str:
    if not at:
        return "not yet"
    seconds = max(0, (time.time() if now is None else now) - at)
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    return time.strftime("%a %I:%M %p", time.localtime(at)).replace(" 0", " ")


def _countdown(at: float | None, now: float | None = None) -> str:
    """"in 2 days 3 hours", "in 45 min", "now"."""
    if not at:
        return ""
    seconds = at - (time.time() if now is None else now)
    if seconds <= 60:
        return "now"
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"in {_plural(days, 'day')} {_plural(hours, 'hour')}" if hours else f"in {_plural(days, 'day')}"
    if hours:
        return f"in {hours} hr {minutes} min" if minutes else f"in {_plural(hours, 'hour')}"
    return f"in {minutes} min"


def _readable(color: str, palette) -> str:
    """A team's colour, lifted off the background when it would vanish into it
    (navy on the dark theme, say); the accent when ESPN gave none."""
    if not color or not color.startswith("#") or len(color) != 7:
        return palette.accent
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    light = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if palette.name == "dark" and light < 0.12:
        return mix("#ffffff", color, 0.35)
    if palette.name != "dark" and light > 0.85:
        return mix("#000000", color, 0.35)
    return color


class ChanceBar(QWidget):
    """Two teams' chances of being credited as one bar, each in its own colour,
    with a tick at even money."""

    def __init__(self, palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_ = palette
        self._left, self._colors = 0.5, (palette.accent, palette.series_color(1))
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, left: float, left_color: str, right_color: str) -> None:
        self._left = min(max(float(left), 0.0), 1.0)
        self._colors = (left_color, right_color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = self.rect()
        radius = self.height() / 2
        painter.setBrush(QColor(self._colors[1]))
        painter.drawRoundedRect(rect, radius, radius)
        split = int(rect.width() * self._left)
        if split > 0:
            painter.setBrush(QColor(self._colors[0]))
            left = rect.adjusted(0, 0, -(rect.width() - max(split, self.height())), 0)
            painter.drawRoundedRect(left, radius, radius)
        painter.setBrush(QColor(self.palette_.ink))
        middle = rect.width() // 2
        painter.drawRect(middle - 1, 0, 2, self.height())
        painter.end()


class GameCard(QFrame):
    """One game: the clock, the two teams and the score, the pool's line and
    where it stands, each side's chance, and your pick against it."""

    def __init__(self, st: GD.GameNow, bd: GD.Board, palette, you: GD.Card | None,
                 ghost: GD.Card | None) -> None:
        super().__init__()
        self.setObjectName("GameCard")
        self.state = st
        mine = you.picks.get(st.index, GD.NOBODY) if you is not None else GD.NOBODY
        tone = ""
        if mine and st.started and st.leader:
            tone = "good" if st.leader == mine else "bad"
        elif st.state == "in":
            tone = "live"
        self.setProperty("tone", tone)
        self.tone = tone
        self.setMinimumHeight(176)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 11)
        layout.setSpacing(5)

        # the clock and the channel
        top = QHBoxLayout()
        top.setSpacing(6)
        if st.state == "in":
            state_text = f"● LIVE · {st.clock}" if st.clock else "● LIVE"
        elif st.state == "final":
            state_text = st.clock.upper() if st.clock else "FINAL"
        elif st.state == "off":
            state_text = "POSTPONED"
        else:
            state_text = GD.kickoff_text(st.kickoff) or "TO PLAY"
        self.state_label = QLabel(state_text)
        self.state_label.setObjectName("GameState")
        self.state_label.setProperty("live", "true" if st.state == "in" else "")
        top.addWidget(self.state_label)
        top.addStretch(1)
        if st.red_zone:
            top.addWidget(Pill("RED ZONE", "bad"))
        if st.broadcast:
            tv = QLabel(st.broadcast)
            tv.setObjectName("GameMeta")
            top.addWidget(tv)
        layout.addLayout(top)

        # the teams, away above home as on a scoreboard
        margin = st.margin
        for side, name, points, record, color in (
            (GD.AWAY, st.game.away, st.away_points, st.away_record, st.away_color),
            (GD.HOME, st.game.home, st.home_points, st.home_record, st.home_color),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            bar = QFrame()
            bar.setObjectName("TeamBar")
            bar.setFixedSize(4, 24)
            bar.setStyleSheet(f"background: {_readable(color, palette)}; border-radius: 2px;")
            row.addWidget(bar)
            team = ElidedLabel(display_team(name))
            team.setObjectName("GameTeam")
            behind = st.decided and margin is not None and ((margin < 0) if side == GD.HOME else (margin > 0))
            team.setProperty("faded", "true" if behind else "")
            row.addWidget(team, 1)
            if record:
                rec = QLabel(record)
                rec.setObjectName("GameMeta")
                row.addWidget(rec)
            if st.possession == ("home" if side == GD.HOME else "away"):
                ball = QLabel("\N{AMERICAN FOOTBALL}")
                ball.setObjectName("Ball")
                ball.setToolTip("Has the ball")
                row.addWidget(ball)
            score = QLabel("" if points is None or not st.started else str(points))
            score.setObjectName("GameScore")
            score.setProperty("faded", "true" if behind else "")
            score.setMinimumWidth(34)
            score.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(score)
            layout.addLayout(row)

        # the pool's line, and where it stands
        standing = st.standing_text()
        line = QLabel(f"Pool line: {st.line_text()}" + (f"  ·  {standing}" if standing else ""))
        line.setObjectName("GameLine")
        line.setWordWrap(True)
        layout.addWidget(line)

        # each side's chance of being credited
        away_color = _readable(st.away_color, palette)
        home_color = _readable(st.home_color, palette)
        if st.decided:
            credited = st.team(st.leader)
            chance_text = (f"{display_team(credited)} credited" if credited else "Tied - nobody credited")
        else:
            chance_text = (f"{display_team(st.game.away)} {st.p_away:.0%}  ·  "
                           f"{display_team(st.game.home)} {st.p_home:.0%} to be credited")
            bar = ChanceBar(palette)
            share = st.p_away / (st.p_away + st.p_home) if (st.p_away + st.p_home) else 0.5
            bar.set_values(share, away_color, home_color)
            bar.setToolTip(chance_text)
            layout.addWidget(bar)
        chances = QLabel(chance_text)
        chances.setObjectName("GameMeta")
        layout.addWidget(chances)

        # your pick, Deadeye's, and the pool's
        picks = QHBoxLayout()
        picks.setSpacing(6)
        if mine:
            mark = ""
            if st.started and st.leader:
                mark = " ✓" if st.leader == mine else " ✗"
            picks.addWidget(Pill(f"You: {display_team(st.team(mine))}{mark}",
                                 "good" if mark.strip() == "✓" else "bad" if mark else ""))
        theirs = ghost.picks.get(st.index, GD.NOBODY) if ghost is not None else GD.NOBODY
        if theirs:
            mark = ""
            if st.started and st.leader:
                mark = " ✓" if st.leader == theirs else " ✗"
            picks.addWidget(Pill(f"{MODEL_NAME}: {display_team(st.team(theirs))}{mark}", ""))
        home_n, away_n = GD.split(bd, st)
        if home_n + away_n:
            side = GD.HOME if home_n >= away_n else GD.AWAY
            most = max(home_n, away_n)
            pool = QLabel(f"The pool: {most / (home_n + away_n):.0%} on {display_team(st.team(side))}")
            pool.setObjectName("GameMeta")
            pool.setToolTip(f"{home_n} on {display_team(st.game.home)}, {away_n} on {display_team(st.game.away)}")
        else:
            pool = None
        picks.addStretch(1)
        layout.addLayout(picks)
        if pool is not None:
            layout.addWidget(pool)

        # down and distance, and the last play
        if st.state == "in" and (st.situation or st.last_play):
            holder = st.team(GD.HOME if st.possession == "home" else GD.AWAY) if st.possession else ""
            where = " · ".join(filter(None, [
                f"{display_team(holder)} ball" if holder else "", st.situation]))
            if where:
                situation = QLabel(where)
                situation.setObjectName("GameMeta")
                layout.addWidget(situation)
            if st.last_play:
                play = ElidedLabel(st.last_play)
                play.setObjectName("GameNote")
                play.setToolTip(st.last_play)
                layout.addWidget(play)
        layout.addStretch(1)
        self.setToolTip(self._tooltip(st, mine, home_n, away_n))

    @staticmethod
    def _tooltip(st: GD.GameNow, mine: int, home_n: int, away_n: int) -> str:
        lines = [st.game.label, f"Pool line: {st.line_text()}"]
        if st.started and st.margin is not None:
            lines.append(st.standing_text())
        if not st.decided:
            lines.append(f"Chance to be credited: {display_team(st.game.home)} {st.p_home:.0%}, "
                         f"{display_team(st.game.away)} {st.p_away:.0%}")
            lines.append(f"Expected before kickoff: {display_team(st.game.home if st.expected >= 0 else st.game.away)} "
                         f"by {abs(st.expected):.1f}")
        lines.append(f"Big Loser chances: {display_team(st.game.home)} {st.blowout_home:.0%}, "
                     f"{display_team(st.game.away)} {st.blowout_away:.0%}")
        if home_n + away_n:
            lines.append(f"The pool: {home_n} on {display_team(st.game.home)}, {away_n} on {display_team(st.game.away)}")
        if mine:
            lines.append(f"You: {display_team(st.team(mine))}")
        return "\n".join(lines)


class GameDayPage(Page):
    from ...places import GAME_DAY as title
    subtitle = "Live scores against the pool's lines, where you stand this week, and what to root for"
    icon = "\N{TELEVISION}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self._placed: dict = {}         # each game grid: (grid, its cards, the columns they're laid in)
        self._board: GD.Board | None = None
        self._week = 0
        self._user_week = False
        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Week"))
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(130)
        self.week_picker.currentIndexChanged.connect(lambda _: self._week_chosen())
        controls.addWidget(self.week_picker)
        controls.addSpacing(12)
        controls.addWidget(QLabel("You are"))
        self.me_picker = QComboBox()
        self.me_picker.setMinimumWidth(180)
        self.me_picker.currentIndexChanged.connect(lambda _: self._me_chosen())
        controls.addWidget(self.me_picker)
        controls.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        controls.addWidget(self.status)
        self.refresh_button = IconButton("Scores now", "refresh")
        self.refresh_button.setToolTip("Ask ESPN for the latest scores now")
        self.refresh_button.clicked.connect(lambda *_: self.action_requested.emit(LIVE_CHECK_NOW))
        controls.addWidget(self.refresh_button)
        self.layout_.addLayout(controls)

        self.tile_score = StatTile("Your Week")
        self.tile_place = StatTile("Your Place")
        self.tile_chance = StatTile("Chance To Win The Week")
        self.tile_money = StatTile("If It Ended Now")
        self._tiles = (self.tile_score, self.tile_place, self.tile_chance, self.tile_money)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.root_card = Card("What to root for")
        self.root_box = QVBoxLayout()
        self.root_box.setSpacing(6)
        self.root_card.body().addLayout(self.root_box)
        self.layout_.addWidget(self.root_card)

        self.live_card, self.live_grid = self._game_section("On now")
        self.next_card, self.next_grid = self._game_section("Still to play")
        self.final_card, self.final_grid = self._game_section("Final")

        self.board_card = Card("The week so far")
        self.board_box = QVBoxLayout()
        self.board_card.body().addLayout(self.board_box)
        self.board_note = QLabel("")
        self.board_note.setObjectName("Muted")
        self.board_note.setWordWrap(True)
        self.board_card.add(self.board_note)
        self.layout_.addWidget(self.board_card)

        self.side_card = Card("The side pools, as they stand")
        self.side_box = QVBoxLayout()
        self.side_box.setSpacing(6)
        self.side_card.body().addLayout(self.side_box)
        self.layout_.addWidget(self.side_card)

        self.footnote = QLabel(
            "Scores are checked every minute while a game is on. A game's chances come from the score, "
            "the time left and the betting line. Your chance of finishing first plays the rest of the "
            f"week out {GD.SIMS:,} times against everyone's cards. Money follows the pool's rule: a "
            "dollar for each game behind the week's best card."
        )
        self.footnote.setObjectName("Muted")
        self.footnote.setWordWrap(True)
        self.layout_.addWidget(self.footnote)

    def _game_section(self, title: str) -> tuple[Card, QGridLayout]:
        card = Card(title)
        grid = QGridLayout()
        grid.setSpacing(12)
        for column in range(CARD_COLUMNS):
            grid.setColumnStretch(column, 1)
        card.body().addLayout(grid)
        self.layout_.addWidget(card)
        return card, grid

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        # opened: the scores as they are now, not as they were at the last look
        self.action_requested.emit(LIVE_CHECK)

    # ---- choosing ------------------------------------------------------------
    def _week_chosen(self) -> None:
        data = self.week_picker.currentData()
        if isinstance(data, int) and data and data != self._week:
            self._week, self._user_week = data, True
            self.refresh_now()

    def _me_chosen(self) -> None:
        key = self.me_picker.currentData()
        if isinstance(key, str) and key:
            QSettings().setValue(ME_KEY, key)
            self.refresh_now()

    def _you(self) -> str:
        key = self.me_picker.currentData()
        if isinstance(key, str) and key:
            return key
        from ... import me
        owner = me.key(self.season)
        if owner:
            return owner
        for name in (ME_KEY, "thisweek/suicide_coach"):
            value = QSettings().value(name, "")
            if isinstance(value, str) and value:
                return value
        return ""

    def _fill_pickers(self) -> None:
        season = self.season
        weeks = sorted(n for n, w in season.weeks.items() if w.games)
        default = GD.default_week(season)
        if not self._user_week or self._week not in weeks:
            self._week, self._user_week = default, False
        self.week_picker.blockSignals(True)
        self.week_picker.clear()
        for n in weeks:
            self.week_picker.addItem(f"Week {n}" + ("  (now)" if n == default else ""), n)
        found = self.week_picker.findData(self._week)
        if isinstance(found, int) and found >= 0:
            self.week_picker.setCurrentIndex(found)
        self.week_picker.blockSignals(False)

        wanted = self._you()
        self.me_picker.blockSignals(True)
        self.me_picker.clear()
        players = sorted(season.players.values(), key=lambda p: p.display.casefold())
        for p in players:
            self.me_picker.addItem(p.display, p.key)
        found = self.me_picker.findData(wanted) if wanted else -1
        if isinstance(found, int) and found >= 0:
            self.me_picker.setCurrentIndex(found)
        self.me_picker.blockSignals(False)

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        self._fill_pickers()
        you = self._you()
        week = self._week
        bd = GD.board(season, week, you) if week else None
        self._board = bd
        self._render_status()
        if bd is None or not bd.states:
            self._show_no_games(week)
            return
        self._render_tiles(bd)
        self._render_roots(bd)
        you_card = bd.you.card if bd.you is not None else None
        ghost_card = bd.ghost.card if bd.ghost is not None else None
        self._render_games(self.live_card, self.live_grid, bd.live, bd, you_card, ghost_card,
                           f"On now · {_plural(len(bd.live), 'game')}")
        self._render_games(self.next_card, self.next_grid, bd.upcoming, bd, you_card, ghost_card,
                           f"Still to play · {_plural(len(bd.upcoming), 'game')}")
        self._render_games(self.final_card, self.final_grid,
                           sorted(bd.final, key=lambda s: (-(s.kickoff or 0), s.index)), bd, you_card, ghost_card,
                           f"Final · {_plural(len(bd.final), 'game')}")
        self._render_board(bd)
        self._render_side(bd)

    def tick(self) -> None:
        """Every half minute from the window: the clock words only."""
        self._render_status()

    def _render_status(self) -> None:
        bd = self._board
        if bd is None:
            self.status.setText("")
            return
        parts = [f"ESPN checked {_ago(bd.checked)}"]
        if bd.mode in ("pre", "between") and bd.next_kickoff:
            parts.insert(0, f"Next kickoff {GD.kickoff_text(bd.next_kickoff)} ({_countdown(bd.next_kickoff)})")
        if bd.live:
            parts.append("updating every minute")
        self.status.setText("  ·  ".join(parts))

    def _show_no_games(self, week: int) -> None:
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "")
        for card, grid in ((self.live_card, self.live_grid), (self.next_card, self.next_grid),
                           (self.final_card, self.final_grid)):
            self.clear_layout(grid)
            self._placed.pop(id(grid), None)
            card.hide()
        self.clear_layout(self.root_box)
        self.root_card.hide()
        self.clear_layout(self.board_box)
        self.board_note.setText(
            f"Week {week} has no games set up yet." if week else "No week to show yet.")
        self.side_card.hide()

    # ---- the headline numbers ----------------------------------------------
    def _render_tiles(self, bd: GD.Board) -> None:
        me = bd.you
        fair = 1 / bd.entrants if bd.entrants else None
        if me is None:
            leader = bd.standings[0] if bd.standings else None
            self.tile_score.set_title("Games")
            self.tile_score.update_values(
                f"{len(bd.final)}/{len(bd.states)}",
                f"final · {_plural(len(bd.live), 'game')} on · {len(bd.upcoming)} to play")
            self.tile_place.set_title("Leading Now")
            self.tile_place.update_values(
                leader.card.name if leader else self.NO_VALUE,
                f"{leader.total_now} so far" if leader else "the pick sheet isn't in yet")
            self.tile_chance.set_title("Chance To Win The Week")
            likeliest = max(bd.standings, key=lambda s: s.chance or 0.0) if bd.standings else None
            self.tile_chance.update_values(
                f"{likeliest.chance:.0%}" if likeliest and likeliest.chance is not None else self.NO_VALUE,
                f"{likeliest.card.name}, the likeliest - choose who you are above" if likeliest else
                "choose who you are above" if bd.has_sheet else "once the commissioner's sheet is in")
            self._kickoff_tile(bd)
            return

        self.tile_score.set_title("Your Week")
        losers = f" + {_plural(me.now_losers, 'Big Loser')}" if me.now_losers else ""
        self.tile_score.update_values(
            str(me.total_now),
            f"{me.now} {'game' if me.now == 1 else 'games'}{losers} · {me.total_banked} banked · "
            f"can still reach {me.most}")

        self.tile_place.set_title("Your Place")
        if me.place is not None and bd.standings:
            top = bd.standings[0].total_now
            level = sum(1 for s in bd.standings if s.total_now == me.total_now) - 1
            gap = top - me.total_now
            if gap:
                detail = f"of {bd.entrants} · {gap} behind the lead"
            else:
                second = max((s.total_now for s in bd.standings if s.total_now < top), default=top)
                detail = (f"of {bd.entrants} · level at the top with {_plural(level, 'other')}" if level
                          else f"of {bd.entrants} · {top - second} clear")
            self.tile_place.update_values(("T-" if level else "") + _ordinal(me.place), detail,
                                          "good" if me.place == 1 else "")
        else:
            ghost = bd.ghost
            self.tile_place.update_values(
                self.NO_VALUE,
                "not on the commissioner's sheet yet - your saved card is shown"
                + (f" · {MODEL_NAME} has {ghost.total_now}" if ghost else ""))

        self.tile_chance.set_title("Chance To Win The Week")
        if me.chance is not None and fair:
            self.tile_chance.update_values(
                f"{me.chance:.1%}", f"a fair share is {fair:.1%}",
                "good" if me.chance > fair * 1.2 else "bad" if me.chance < fair * 0.5 else "")
            self.tile_chance.show_bar(me.chance, fair, palette=self.palette)
        else:
            self.tile_chance.update_values(self.NO_VALUE, "once the commissioner's sheet is in")
            self.tile_chance.hide_bar()

        if bd.mode in ("pre", "between") and not bd.final and bd.next_kickoff:
            self._kickoff_tile(bd)
            return
        self.tile_money.set_title("If It Ended Now")
        if me.money_now is not None:
            average = f"about {_money(me.money)} by the end" if me.money is not None else ""
            self.tile_money.update_values(
                _money(me.money_now),
                ("you'd collect" if me.money_now > 0 else "you'd pay" if me.money_now < 0 else "even")
                + (f" · {average}" if average else ""),
                "good" if me.money_now > 0 else "bad" if me.money_now < 0 else "")
        else:
            self.tile_money.update_values(self.NO_VALUE, "once the commissioner's sheet is in")

    def _kickoff_tile(self, bd: GD.Board) -> None:
        self.tile_money.set_title("Next Kickoff")
        nxt = bd.next_kickoff
        game = next((s for s in bd.upcoming if s.kickoff == nxt), None)
        self.tile_money.update_values(
            GD.kickoff_text(nxt) if nxt else self.NO_VALUE,
            (f"{game.game.label} · {_countdown(nxt)}" if game else "") +
            (f" · {game.broadcast}" if game is not None and game.broadcast else ""))

    # ---- what to root for ------------------------------------------------------
    def _render_roots(self, bd: GD.Board) -> None:
        self.clear_layout(self.root_box)
        self.root_card.show()
        lines = 0
        if bd.you is None or bd.you.chance is None:
            note = QLabel(
                "Choose who you are above." if bd.you is None and bd.has_sheet else
                "Once the commissioner's pick sheet is in, the results that matter most to "
                "you show here - and which way to root.")
            note.setObjectName("Muted")
            note.setWordWrap(True)
            self.root_box.addWidget(note)
            lines += 1
        else:
            for root in bd.roots[:ROOTS_SHOWN]:
                if abs(root.swing) < 0.005:
                    continue
                self.root_box.addLayout(self._root_row(root))
                lines += 1
            if not lines:
                note = QLabel("Nothing left to root for - the week is settled for you."
                              if bd.mode == "final" else
                              "No single result left moves your chance much either way.")
                note.setObjectName("Muted")
                self.root_box.addWidget(note)
        sweat = GD.sweat(bd)
        if sweat is not None:
            st, count, side = sweat
            text = QLabel(
                f"The pool's biggest sweat: <b>{count} of {bd.entrants}</b> need "
                f"{display_team(st.team(side))} \u2014 {st.standing_text() or 'level'}, {st.clock}.")
            text.setTextFormat(Qt.TextFormat.RichText)
            text.setWordWrap(True)
            text.setObjectName("StatDetail")
            self.root_box.addWidget(text)
        upsets = GD.upsets(bd)
        if upsets:
            names = ", ".join(f"{display_team(st.team(st.leader))} ({share:.0%} had them)" for st, share in upsets[:4])
            text = QLabel(f"Upsets so far: {names}.")
            text.setWordWrap(True)
            text.setObjectName("StatDetail")
            self.root_box.addWidget(text)

    def _root_row(self, root: GD.Root) -> QHBoxLayout:
        st = root.state
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(Pill(f"+{root.swing:.0%}" if root.swing >= 0.005 else "+<1%", "good"),
                      0, Qt.AlignmentFlag.AlignTop)
        where = st.clock if st.state == "in" else (GD.kickoff_text(st.kickoff) or "to play")
        score = ""
        if st.state == "in" and st.margin is not None:
            score = f"{display_team(st.game.away)} {st.away_points}-{st.home_points} {display_team(st.game.home)}, "
        text = QLabel(
            f"<b>{root.phrase()}</b> &nbsp;<span>{st.game.label} · {score}{where}</span><br>"
            f"Your chance of finishing first: {root.chance_if_not:.1%} if not, "
            f"<b>{root.chance_if:.1%}</b> if so · it happens {root.likely:.0%} of the time")
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        row.addWidget(text, 1)
        return row

    # ---- the games ---------------------------------------------------------------
    def _render_games(self, card: Card, grid: QGridLayout, states: list[GD.GameNow], bd: GD.Board,
                      you: GD.Card | None, ghost: GD.Card | None, title: str) -> None:
        self.clear_layout(grid)
        self._placed.pop(id(grid), None)
        if not states:
            card.hide()
            return
        card.show()
        card.set_title(title)
        cards = [GameCard(st, bd, self.palette, you, ghost) for st in states]
        self._placed[id(grid)] = (grid, cards, 0)
        self._place(grid)

    def _columns(self) -> int:
        """As many card columns as the page's width takes, up to three."""
        try:
            width = int(self.width())
        except (TypeError, ValueError):
            return CARD_COLUMNS
        return max(1, min(CARD_COLUMNS, width // CARD_MIN_WIDTH)) if width > 0 else CARD_COLUMNS

    def _place(self, grid: QGridLayout) -> None:
        grid_, cards, laid = self._placed.get(id(grid), (grid, [], 0))
        columns = self._columns()
        if laid == columns:
            return
        for card in cards:
            grid.removeWidget(card)
        for column in range(CARD_COLUMNS):
            grid.setColumnStretch(column, 1 if column < columns else 0)
        for i, card in enumerate(cards):
            grid.addWidget(card, i // columns, i % columns)
        self._placed[id(grid)] = (grid, cards, columns)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        for grid, _cards, _laid in list(self._placed.values()):
            self._place(grid)

    # ---- everyone ---------------------------------------------------------------
    def _render_board(self, bd: GD.Board) -> None:
        self.clear_layout(self.board_box)
        if not bd.has_sheet:
            self.board_card.set_title("The week so far")
            self.board_note.setText(
                f"The commissioner's pick sheet for week {bd.week} isn't in yet. Once it is, "
                "everyone's live score, their chance of finishing first and what the week is "
                "worth to them show here."
                + (f" Until then: your saved card has {bd.you.total_now}"
                   + (f", {MODEL_NAME}'s {bd.ghost.total_now}" if bd.ghost else "") + "."
                   if bd.you is not None and bd.states and any(s.started for s in bd.states) else ""))
            return
        self.board_card.set_title(
            f"The week so far - if it ended now ({len(bd.final)} of {len(bd.states)} final)")
        rows, tones, colors, sort_place = [], {}, {}, []
        entries: list[tuple[GD.Standing, float]] = [(s, float(s.place or 0)) for s in bd.standings]
        for extra in (bd.ghost, bd.you if bd.you is not None and not bd.you.card.in_field else None):
            if extra is not None:
                ahead = sum(1 for s in bd.standings if s.total_now > extra.total_now)
                entries.append((extra, ahead + 1.5))
        entries.sort(key=lambda pair: (pair[1], -(pair[0].chance or 0.0)))
        highlight = mix(self.palette.accent, self.palette.surface, 0.22)
        for r, (st, place) in enumerate(entries):
            card = st.card
            name = card.name
            if card.ghost:
                name = f"{MODEL_NAME} \N{BOW AND ARROW}  (not in the pool)"
            elif card.you:
                name = f"{card.name}  (you)" + ("" if card.in_field else " - saved card")
            rows.append([
                st.place if st.place is not None else "–",
                name,
                st.total_now,
                st.now,
                st.now_losers or "",
                st.total_banked,
                st.most,
                f"{st.chance:.1%}" if st.chance is not None else "–",
                _money(st.money_now),
            ])
            sort_place.append(place)
            if st.chance is not None and st.chance >= 0.10:
                tones[(r, 7)] = "good"
            if st.money_now is not None:
                tones[(r, 8)] = "good" if st.money_now > 0 else "muted"
            if card.ghost:
                tones[(r, 1)] = "muted"
            if card.you:
                for column in range(len(BOARD_HEADERS)):
                    colors[(r, column)] = highlight
        model = TableModel(
            BOARD_HEADERS, rows, palette=self.palette, numeric_columns={0, 2, 3, 4, 5, 6, 7, 8},
            sort_values={
                0: sort_place,
                7: [st.chance if st.chance is not None else -1 for st, _ in entries],
                8: [st.money_now if st.money_now is not None else 0 for st, _ in entries],
            },
            tones=tones, cell_colors=colors, bold_columns={1},
        )
        view, _ = make_table(model, stretch_column=1, row_height=27)
        self.board_box.addWidget(view)
        self.board_note.setText(
            "Now counts finished games and games in progress. Banked counts finished games only. "
            "Can reach is the most a card can still score. To win is the chance of finishing first, "
            "with ties shared. If it ended now is the money at today's scores. "
            f"{MODEL_NAME} is shown for comparison and takes no place or prize.")

    # ---- the side pools ------------------------------------------------------------
    def _render_side(self, bd: GD.Board) -> None:
        self.clear_layout(self.side_box)
        losers = GD.losers_now(bd)
        survivors = GD.suicide_now(self.season, bd) if self.season is not None else []
        if not losers and not survivors:
            self.side_card.hide()
            return
        self.side_card.show()
        if losers:
            heading = QLabel("Big Losers held this week")
            heading.setObjectName("CardTitle")
            self.side_box.addWidget(heading)
            words = {"on": ("ON PACE", "good"), "hit": ("HIT", "good"), "close": ("CLOSE", "warning"),
                     "alive": ("LIVE", ""), "to play": ("TO PLAY", ""), "missed": ("MISSED", "muted")}
            for item in losers[:LOSERS_SHOWN]:
                st = item.state
                team = display_team(st.team(item.side))
                other = display_team(st.team(-item.side))
                margin = st.margin
                lost_by = None if margin is None else (-margin if item.side == GD.HOME else margin)
                if st.state == "final" and lost_by is not None:
                    how = f"lost to {other} by {lost_by}" if lost_by > 0 else f"beat {other}"
                elif st.state == "in" and lost_by is not None:
                    how = (f"down {lost_by} to {other}" if lost_by > 0 else
                           f"up {-lost_by} on {other}" if lost_by < 0 else f"level with {other}") + f", {st.clock}"
                else:
                    how = f"v {other}, {GD.kickoff_text(st.kickoff) or 'to play'}"
                label, tone = words[item.status]
                row = QHBoxLayout()
                row.setSpacing(10)
                row.addWidget(Pill(label, tone))
                text = QLabel(f"<b>{team}</b> {how} · held by {item.held}"
                              + (" - including you" if item.yours else ""))
                text.setTextFormat(Qt.TextFormat.RichText)
                row.addWidget(text, 1)
                self.side_box.addLayout(row)
        if survivors:
            heading = QLabel(f"Suicide pool - {_plural(len([s for s in survivors if s.status != 'out']), 'coach', 'coaches')} still standing")
            heading.setObjectName("CardTitle")
            self.side_box.addWidget(heading)
            words = {"safe": ("SAFE", "good"), "winning": ("WINNING", "good"), "losing": ("LOSING", "bad"),
                     "to play": ("TO PLAY", ""), "out": ("OUT", "bad")}
            for item in survivors:
                label, tone = words[item.status]
                row = QHBoxLayout()
                row.setSpacing(10)
                row.addWidget(Pill(label, tone))
                st = item.state
                where = st.clock if st.state == "in" else (GD.kickoff_text(st.kickoff) if st.state == "pre" else st.clock)
                text = QLabel(f"<b>{item.card.name}</b> - {display_team(st.team(item.side))}"
                              f" ({st.standing_text() or st.line_text()}{', ' + where if where else ''})"
                              + (f" · {item.chance:.0%} to survive" if st.state in ("pre", "in") else ""))
                text.setTextFormat(Qt.TextFormat.RichText)
                row.addWidget(text, 1)
                self.side_box.addLayout(row)
