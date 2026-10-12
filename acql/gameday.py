"""Game day: the week while it is being played.

Everything the Game Day page shows is worked out here, away from Qt, so it can
be checked against real pick sheets without a screen:

* each game as it stands - the score, the clock, who has the ball - against
  the pool's line: who is credited if it ended now, and each side's chance of
  being credited when it does;
* every coach's week - banked (games over), if it ended now, and the most
  they can still reach - and, played out a few thousand times from here,
  their chance of finishing first and what the week is worth to them;
* for you: the games still to be decided that matter most and which way to
  root, your Big Losers, and the suicide pool as it stands.

A game under way is priced from its score, the time left and the line before
kickoff. What is left of it is the pre-game expectation scaled by the time
remaining, spread as widely as whole games are (analytics' two bells) and
narrowing as the clock runs down - so a 7-point lead means little in the first
quarter and nearly everything with two minutes left. Before kickoff a game is
priced exactly as This Week prices it.
"""

from __future__ import annotations

import math
import re
import time
import zlib
from dataclasses import dataclass, field

import numpy as np

from . import analytics, results
from .models import Game, Season, same_team
from .predictions import display_team, team_code

#: Games played out per look. A chance moves by well under a point between
#: two looks when nothing has happened (and not at all: the draw is seeded by
#: the scores, so the same scores give the same numbers).
SIMS = 4000
REGULATION = 3600.0
QUARTER = 900.0
OVERTIME = 600.0
#: A game level at the end of regulation goes to overtime. Most are settled
#: there - by a field goal as often as not - and about one in twenty stays level.
OT_TIE = 0.05
OT_MARGIN = 3
BLOWOUT = analytics.BIG_LOSER_MARGIN + 1
#: Under this share of the pool on the side that was credited, it's an upset.
UPSET = 0.30
#: How far either way a final margin is followed.
REACH = 80
HOME, AWAY, NOBODY = 1, -1, 0


# ---- the clock ----------------------------------------------------------------------
_RUNNING = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(1st|2nd|3rd|4th|OT)", re.IGNORECASE)
_ENDED = re.compile(r"end of (?:the )?(1st|2nd|3rd|4th)", re.IGNORECASE)
_PERIODS = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "ot": 5}


def _from_detail(detail: str) -> tuple[int, float | None]:
    """(period, seconds left in it) from the scoreboard's words, for a score
    kept before the clock itself was."""
    text = str(detail or "")
    if "half" in text.casefold():
        return 2, 0.0
    ended = _ENDED.search(text)
    if ended:
        return _PERIODS[ended.group(1).casefold()], 0.0
    running = _RUNNING.search(text)
    if running:
        return _PERIODS[running.group(3).casefold()], int(running.group(1)) * 60.0 + int(running.group(2))
    return 0, None


def time_left(score: results.Score | None) -> float:
    """The share of regulation still to play: 1 before kickoff, 0 at the end.
    Overtime counts as the sliver it is."""
    if score is None or score.state == "pre":
        return 1.0
    if score.final or score.state == "post":
        return 0.0
    period, clock = score.period, score.clock
    if not period:
        period, clock = _from_detail(score.detail)
    if not period:
        return 0.5                          # on, but nobody said where
    clock = QUARTER if clock is None else max(0.0, float(clock))
    if period <= 4:
        return max(0.0, min(1.0, ((4 - period) * QUARTER + min(clock, QUARTER)) / REGULATION))
    return min(clock, OVERTIME) / REGULATION


def clock_text(score: results.Score | None) -> str:
    """"Q3 4:12", "Halftime", "End of Q3", "OT 2:10" - the clock as a TV shows it."""
    if score is None:
        return ""
    detail = str(score.detail or "").strip()
    if "half" in detail.casefold():
        return "Halftime"
    ended = _ENDED.search(detail)
    if ended:
        return f"End of Q{_PERIODS[ended.group(1).casefold()]}"
    period, clock = score.period, score.clock
    if not period:
        period, clock = _from_detail(detail)
    if period and clock is not None:
        minutes, seconds = divmod(int(round(clock)), 60)
        return f"{'OT' if period > 4 else f'Q{period}'} {minutes}:{seconds:02d}"
    return detail


def kickoff_text(kickoff: float | None, now: float | None = None) -> str:
    """"Sun 12:00 PM" on this computer's clock; "Today 7:15 PM" on the day."""
    if not kickoff:
        return ""
    when = time.localtime(kickoff)
    today = time.localtime(time.time() if now is None else now)
    day = "Today" if (when.tm_year, when.tm_yday) == (today.tm_year, today.tm_yday) else \
        ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[when.tm_wday]
    hour = when.tm_hour % 12 or 12
    return f"{day} {hour}:{when.tm_min:02d} {'AM' if when.tm_hour < 12 else 'PM'}"


# ---- where a game may finish --------------------------------------------------------
def _tail(x: np.ndarray, center: float, narrow: float, wide: float) -> np.ndarray:
    """P(final margin > x) for the two-bell spread of results."""
    from math import sqrt
    z1 = (x - center) / (narrow * sqrt(2))
    z2 = (x - center) / (wide * sqrt(2))
    erfc = np.vectorize(math.erfc)
    return (1 - analytics.TAIL_SHARE) * 0.5 * erfc(z1) + analytics.TAIL_SHARE * 0.5 * erfc(z2)


@dataclass(frozen=True)
class Outlook:
    """Where a game's final home margin may land from here: margins and their
    chances (summing to one)."""

    margins: tuple[int, ...]
    chances: tuple[float, ...]

    def at_least(self, k: int) -> float:
        return float(sum(p for d, p in zip(self.margins, self.chances) if d >= k))

    def at_most(self, k: int) -> float:
        return float(sum(p for d, p in zip(self.margins, self.chances) if d <= k))

    def sample(self, rng: np.random.Generator, n: int) -> np.ndarray:
        if len(self.margins) == 1:
            return np.full(n, self.margins[0], dtype=int)
        return rng.choice(np.asarray(self.margins, dtype=int), size=n, p=np.asarray(self.chances))


def outlook(now_margin: int, left: float, expected: float, sd: float, *, started: bool) -> Outlook:
    """The final home margin's chances from a score, the time left and the
    expectation before kickoff (home side).

    Before kickoff it is This Week's own distribution (key numbers and all).
    Once under way, what is left of the game carries the pre-game edge in
    proportion to the time left and the spread of a whole game shrunk by the
    square root of it; a game level when regulation runs out goes to overtime.
    """
    sd = max(float(sd or analytics.SPREAD_SD), 1.0)
    if not started:
        dist = analytics.margin_distribution(round(float(expected), 1), round(sd, 1))
        return Outlook(tuple(d for d, _ in dist), tuple(p for _, p in dist))
    if left * REGULATION < 1.0:
        if now_margin != 0:
            return Outlook((int(now_margin),), (1.0,))
        left, expected = OVERTIME / REGULATION, 0.0      # level after 60 minutes
    extra = max(0.0, sd * sd - analytics.SPREAD_SD ** 2)
    scale = math.sqrt(left)
    narrow = math.sqrt(analytics.SPREAD_SD ** 2 + extra) * scale
    wide = math.sqrt((analytics.SPREAD_SD * analytics.TAIL_RATIO) ** 2 + extra) * scale
    center = now_margin + float(expected) * left
    span = np.arange(int(now_margin) - REACH, int(now_margin) + REACH + 1)
    chances = _tail(span - 0.5, center, narrow, wide) - _tail(span + 0.5, center, narrow, wide)
    chances = np.clip(chances, 0.0, None)
    chances = chances / chances.sum()
    found = dict(zip(span.tolist(), chances.tolist()))
    level = found.get(0, 0.0)
    if level:
        settled = level * (1 - OT_TIE) / 2
        found[0] = level * OT_TIE
        found[OT_MARGIN] = found.get(OT_MARGIN, 0.0) + settled
        found[-OT_MARGIN] = found.get(-OT_MARGIN, 0.0) + settled
    kept = [(d, p) for d, p in sorted(found.items()) if p > 1e-9]
    total = sum(p for _, p in kept)
    return Outlook(tuple(d for d, _ in kept), tuple(p / total for _, p in kept))


def credited_by(game: Game, margins: np.ndarray) -> np.ndarray:
    """HOME / AWAY / NOBODY for each final home margin, by the pool's rule."""
    margins = np.asarray(margins)
    if game.line is not None and game.line_favourite:
        need = analytics.line_need(game.line)
        if same_team(game.line_favourite, game.home) or team_code(game.line_favourite) == team_code(game.home):
            return np.where(margins >= need, HOME, AWAY)
        return np.where(-margins >= need, AWAY, HOME)
    return np.sign(margins).astype(int)


# ---- one game, now ------------------------------------------------------------------
@dataclass(frozen=True)
class GameNow:
    """One game as it stands, set against the pool's line. Home and away are
    the pick sheet's, whatever the scoreboard calls them."""

    game: Game
    state: str                     # "pre", "in", "final" or "off" (postponed)
    home_points: int | None
    away_points: int | None
    left: float                    # share of regulation still to play
    kickoff: float | None
    clock: str                     # "Q3 4:12", "Halftime", "Final", "Final/OT"
    possession: str                # "home", "away" or ""
    situation: str
    red_zone: bool
    last_play: str
    broadcast: str
    home_record: str
    away_record: str
    home_color: str
    away_color: str
    expected: float                # the home side's expected margin before kickoff
    sd: float
    outlook: Outlook
    p_home: float                  # chance each side is credited at the end
    p_away: float
    leader: int                    # HOME / AWAY / NOBODY if it ended now (NOBODY before kickoff)
    blowout_home: float            # chance the home side loses by 15 or more
    blowout_away: float

    @property
    def index(self) -> int:
        return self.game.index

    @property
    def started(self) -> bool:
        return self.state in ("in", "final")

    @property
    def decided(self) -> bool:
        return self.state == "final"

    @property
    def margin(self) -> int | None:
        if self.home_points is None or self.away_points is None:
            return None
        return self.home_points - self.away_points

    def team(self, side: int) -> str:
        return self.game.home if side == HOME else self.game.away if side == AWAY else ""

    def side_of(self, team: object) -> int:
        code = team_code(team)
        if code and code == team_code(self.game.home):
            return HOME
        if code and code == team_code(self.game.away):
            return AWAY
        return NOBODY

    def chance(self, side: int) -> float:
        return self.p_home if side == HOME else self.p_away if side == AWAY else 0.0

    def blowout(self, side: int) -> float:
        """Chance this side loses by 15 or more."""
        return self.blowout_home if side == HOME else self.blowout_away if side == AWAY else 0.0

    @property
    def lined(self) -> bool:
        return self.game.line is not None and bool(self.game.line_favourite)

    @property
    def favourite(self) -> int:
        if not self.lined:
            return NOBODY
        return self.side_of(self.game.line_favourite) or HOME

    def line_text(self) -> str:
        """"Dallas by 9" - the pool's line - or "straight up"."""
        if not self.lined:
            return "straight up"
        return f"{display_team(self.game.line_favourite)} by {self.game.line:g}"

    def standing_text(self) -> str:
        """Where the pool's line stands now: "Dallas +11, covering the 9",
        "Dallas +5, 4 short of the 9", "Tampa Bay leads by 3"."""
        margin = self.margin
        if margin is None or not self.started:
            return ""
        if self.lined:
            fav = self.favourite
            by = margin if fav == HOME else -margin
            need = analytics.line_need(self.game.line)
            name = display_team(self.team(fav))
            lead = f"{name} {'+' if by > 0 else ''}{by}" if by else f"{name} level"
            if by >= need:
                return f"{lead}, {'covered' if self.decided else 'covering'} the {self.game.line:g}"
            return f"{lead}, {need - by} short of the {self.game.line:g}"
        if margin == 0:
            return "Level" if not self.decided else "Tied"
        side = HOME if margin > 0 else AWAY
        verb = "won" if self.decided else "leads"
        return f"{display_team(self.team(side))} {verb} by {abs(margin)}"


def _pairs(scores: list[results.Score]) -> dict:
    return {frozenset((s.away, s.home)): s for s in scores}


def games_now(season: Season, week: int, *, kept: list[results.Score] | None = None) -> list[GameNow]:
    """Every game of a week as it stands, in the week's own order."""
    from . import pricing
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found else []
    if not games:
        return []
    year = results.season_year(season)
    kept = results.load(year, week) if kept is None else kept
    try:
        prices = pricing.price_week(season, week, games)
    except Exception:  # noqa: BLE001 - a game with no price is a coin flip
        prices = [None] * len(games)
    listed = {team_code(t) for t in (getattr(season, "big_losers_by_week", {}) or {}).get(week, [])}
    out = []
    for game, price in zip(games, prices):
        score, flipped = results.find(kept, game.away, game.home)
        both = results.points(game, score) if score is not None else None
        hp, ap = both if both else (game.home_points, game.away_points)
        played = bool(str(game.winner or "").strip())
        if played or (score is not None and score.final):
            state = "final"
        elif score is not None and score.called_off:
            state = "off"
        elif score is not None and score.state == "in":
            state = "in"
        else:
            state = "pre"
        expected = getattr(price, "margin", None) if price is not None else None
        if expected is None and score is not None and score.home_spread is not None:
            expected = -score.home_spread if flipped else score.home_spread
        expected = float(expected or 0.0)
        sd = float(getattr(price, "sd", None) or analytics.SPREAD_SD)
        left = 0.0 if state == "final" else time_left(score) if state == "in" else 1.0
        margin = (hp - ap) if hp is not None and ap is not None else None

        if state == "final":
            if margin is not None:
                look = Outlook((margin,), (1.0,))
            else:
                look = Outlook((0,), (1.0,))
            if played:
                side = HOME if same_team(game.winner, game.home) or team_code(game.winner) == team_code(game.home) \
                    else AWAY if same_team(game.winner, game.away) or team_code(game.winner) == team_code(game.away) \
                    else NOBODY
            else:
                side = int(credited_by(game, np.asarray([margin or 0]))[0])
            p_home, p_away = float(side == HOME), float(side == AWAY)
            leader = side
            if margin is not None:
                bh, ba = float(margin <= -BLOWOUT), float(margin >= BLOWOUT)
            else:
                bh = float(team_code(game.home) in listed)
                ba = float(team_code(game.away) in listed)
        else:
            look = outlook(margin or 0, left, expected, sd, started=state == "in")
            margins = np.asarray(look.margins)
            weights = np.asarray(look.chances)
            sides = credited_by(game, margins)
            p_home = float(weights[sides == HOME].sum())
            p_away = float(weights[sides == AWAY].sum())
            leader = int(credited_by(game, np.asarray([margin]))[0]) if state == "in" and margin is not None else NOBODY
            if state == "in":
                bh = analytics.big_loser_chance_in_play(float(weights[margins <= -BLOWOUT].sum()), expected, sd, left)
                ba = analytics.big_loser_chance_in_play(float(weights[margins >= BLOWOUT].sum()), -expected, sd, left)
            else:                                # before kickoff: This Week's own numbers
                bh, ba = analytics.big_loser_chance(expected, sd), analytics.big_loser_chance(-expected, sd)

        def oriented(home_value, away_value):
            return (away_value, home_value) if flipped else (home_value, away_value)

        home_record, away_record = oriented(getattr(score, "home_record", ""), getattr(score, "away_record", "")) \
            if score is not None else ("", "")
        home_color, away_color = oriented(getattr(score, "home_color", ""), getattr(score, "away_color", "")) \
            if score is not None else ("", "")
        holder = getattr(score, "possession", "") if score is not None and state == "in" else ""
        possession = "home" if holder and holder == team_code(game.home) else \
            "away" if holder and holder == team_code(game.away) else ""
        if state == "final":
            clock = str(getattr(score, "detail", "") or "Final") if score is not None and score.final else "Final"
            if not clock.casefold().startswith("final"):
                clock = "Final"
        elif state == "in":
            clock = clock_text(score)
        elif state == "off":
            clock = "Postponed"
        else:
            clock = ""
        out.append(GameNow(
            game=game, state=state, home_points=hp, away_points=ap, left=left,
            kickoff=getattr(score, "kickoff", None) if score is not None else None,
            clock=clock, possession=possession,
            situation=getattr(score, "situation", "") if state == "in" else "",
            red_zone=bool(getattr(score, "red_zone", False)) if state == "in" else False,
            last_play=getattr(score, "last_play", "") if state == "in" else "",
            broadcast=getattr(score, "broadcast", "") if score is not None else "",
            home_record=home_record, away_record=away_record,
            home_color=home_color, away_color=away_color,
            expected=expected, sd=sd, outlook=look,
            p_home=p_home, p_away=p_away, leader=leader,
            blowout_home=bh, blowout_away=ba,
        ))
    return out


# ---- everyone's card ----------------------------------------------------------------------
@dataclass
class Card:
    """One coach's week: a side for each game, three Big Losers, a suicide pick."""

    key: str
    name: str
    picks: dict[int, int] = field(default_factory=dict)          # game index -> HOME / AWAY
    losers: list[tuple[int, int]] = field(default_factory=list)  # (game index, side) held to lose big
    suicide: tuple[int, int] | None = None
    suicide_team: str = ""
    in_field: bool = True          # on the commissioner's sheet
    you: bool = False
    ghost: bool = False            # Deadeye: shown, never counted


def _norm(text: object) -> str:
    return "".join(c for c in str(text or "").casefold() if c.isalnum())


def _side_in(states: list[GameNow], team: object) -> tuple[int, int] | None:
    """(game index, side) for a team playing this week."""
    for st in states:
        side = st.side_of(team)
        if side:
            return st.index, side
    return None


def cards(season: Season, week: int, states: list[GameNow], you: str = "") -> list[Card]:
    """The commissioner's sheet as cards, plus yours if you aren't on it (your
    saved card) and Deadeye's. The sheet's coaches are the field."""
    from . import cards as kept_cards, picks as sheets, pricing
    from .version import MODEL_NAME
    out: list[Card] = []
    sheet = sheets.load(week)
    players = {}
    for key, person in season.players.items():
        players.setdefault(_norm(person.display), key)
        players.setdefault(_norm(key), key)
    if sheet is not None and sheet.coaches:
        for coach in sheet.coaches:
            key = players.get(_norm(coach), "") or f"sheet:{coach}"
            person = season.players.get(key)
            card = Card(key=key, name=person.display if person else str(coach).strip())
            for st in states:
                found = sheet.game_for(st.game.away, st.game.home)
                side = st.side_of(found.picks.get(coach, "")) if found is not None else NOBODY
                if side:
                    card.picks[st.index] = side
            for team in sheet.losers.get(coach, []) or []:
                spot = _side_in(states, team)
                if spot:
                    card.losers.append(spot)
            pick = str((sheet.suicide or {}).get(coach, "") or "").strip()
            if pick and pick.casefold() not in sheets.OUT_MARKERS:
                card.suicide, card.suicide_team = _side_in(states, pick), pick
            card.you = bool(you) and key == you
            out.append(card)
    if you and not any(c.you for c in out):
        saved = kept_cards.mine(week)
        if saved is not None:
            saved = kept_cards.aligned(saved, [(st.index, st.game.away, st.game.home) for st in states])
            person = season.players.get(you)
            card = Card(key=you, name=person.display if person else "You", in_field=False, you=True)
            for st in states:
                side = st.side_of(saved.take.get(st.index, ""))
                if side:
                    card.picks[st.index] = side
            if card.picks:
                out.append(card)
    model = kept_cards.model(week)
    if model is not None:
        model = kept_cards.aligned(model, [(st.index, st.game.away, st.game.home) for st in states])
        ghost = Card(key="deadeye", name=MODEL_NAME, in_field=False, ghost=True)
        for st in states:
            side = st.side_of((model.plain or model.take).get(st.index, ""))
            if side:
                ghost.picks[st.index] = side
        try:
            # the three on its kept card; the likeliest by the lines for a card kept before they were
            teams = list(model.losers)
            if not teams:
                prices = pricing.price_week(season, week, [st.game for st in states])
                teams = [b.team for b in pricing.big_loser_candidates(prices, include_played=True)[:3]]
            for team in teams[:3]:
                spot = _side_in(states, team)
                if spot:
                    ghost.losers.append(spot)
        except Exception:  # noqa: BLE001 - its card without Big Losers
            pass
        if ghost.picks:
            out.append(ghost)
    return out


# ---- the week, played out ---------------------------------------------------------------
@dataclass(frozen=True)
class Standing:
    card: Card
    banked: int            # games over, credited to this card
    banked_losers: int
    now: int               # if it ended now: banked plus the games under way it is ahead in
    now_losers: int
    most: int              # the most it can still reach
    place: int | None      # in the field, by "now" (None for a card outside it)
    chance: float | None   # of finishing first (ties share)
    money: float | None    # what the week is worth on average, by the pool's rule
    money_now: float | None    # what it would pay if it ended now

    @property
    def total_now(self) -> int:
        return self.now + self.now_losers

    @property
    def total_banked(self) -> int:
        return self.banked + self.banked_losers


@dataclass(frozen=True)
class Root:
    """A result still to come that matters to you."""

    state: GameNow
    side: int                  # the side to root for
    kind: str                  # "pick" (who is credited) or "loser" (a Big Loser)
    chance_if: float           # your chance of finishing first if it happens
    chance_if_not: float
    likely: float              # the chance it happens

    @property
    def swing(self) -> float:
        return self.chance_if - self.chance_if_not

    def phrase(self) -> str:
        """"Houston to win by 7 or more", "Tennessee to stay within 6" (a
        7-point line: losing by 7 credits Houston), "Atlanta to win",
        "Atlanta to lose by 15 or more"."""
        st, team = self.state, display_team(self.state.team(self.side))
        if self.kind == "loser":
            return f"{team} to lose by {BLOWOUT} or more"
        if st.lined:
            need = analytics.line_need(st.game.line)
            if self.side == st.favourite:
                return f"{team} to win by {need} or more" if need > 1 else f"{team} to win"
            return f"{team} to stay within {need - 1}" if need > 1 else f"{team} to win or tie"
        return f"{team} to win"


@dataclass(frozen=True)
class Board:
    year: int
    week: int
    states: list[GameNow]
    standings: list[Standing]          # the field, best "now" first
    you: Standing | None
    ghost: Standing | None
    roots: list[Root]
    entrants: int
    has_sheet: bool
    checked: float | None              # when ESPN was last asked about the week

    @property
    def live(self) -> list[GameNow]:
        return [s for s in self.states if s.state == "in"]

    @property
    def final(self) -> list[GameNow]:
        return [s for s in self.states if s.state == "final"]

    @property
    def upcoming(self) -> list[GameNow]:
        return sorted((s for s in self.states if s.state in ("pre", "off")),
                      key=lambda s: (s.kickoff or float("inf"), s.index))

    @property
    def mode(self) -> str:
        """"live" (a game on), "between" (some played, more to come), "pre", or "final"."""
        if self.live:
            return "live"
        if not self.states or all(s.state in ("final", "off") for s in self.states):
            return "final" if self.final else "pre"
        return "between" if self.final else "pre"

    @property
    def next_kickoff(self) -> float | None:
        times = [s.kickoff for s in self.states if s.state == "pre" and s.kickoff]
        return min(times) if times else None


def _seed(year: int, week: int, states: list[GameNow], cards_: list[Card]) -> int:
    text = repr((year, week, [(s.index, s.state, s.home_points, s.away_points, round(s.left, 3))
                              for s in states], sorted((c.key, sorted(c.picks.items())) for c in cards_)))
    return zlib.crc32(text.encode("utf-8"))


def _routs(draws: np.ndarray, states: list[GameNow], seed: int) -> dict[int, np.ndarray]:
    """Which side is routed in each played-out week, game by game.

    The margins drawn come off the margin curve, which puts fewer routs on
    the board than history does (analytics.rout_chance) - so counting the
    draws of 15 or more would not add up to the chances the games carry. A
    game still to finish has its routs made up to its own chance instead:
    its most lopsided draws are the routs, equal margins settled by lot.
    """
    sims = len(draws)
    blown = {HOME: draws <= -BLOWOUT, AWAY: draws >= BLOWOUT}
    lots = np.random.default_rng(seed).random(draws.shape)
    for g, st in enumerate(states):
        if st.state not in ("pre", "in"):
            continue
        worst = np.lexsort((lots[:, g], draws[:, g]))               # the home side's worst days first
        for side, chance, order in ((HOME, st.blowout_home, worst), (AWAY, st.blowout_away, worst[::-1])):
            hit = np.zeros(sims, dtype=bool)
            hit[order[:int(round(chance * sims))]] = True
            blown[side][:, g] = hit
    return blown


def board(season: Season, week: int, you: str = "", *, sims: int = SIMS,
          kept: list[results.Score] | None = None) -> Board:
    """The whole week as it stands, played out `sims` times from here."""
    year = results.season_year(season)
    states = games_now(season, week, kept=kept)
    every = cards(season, week, states, you) if states else []
    field_cards = [c for c in every if c.in_field]
    standings: list[Standing] = []
    roots: list[Root] = []
    you_standing = ghost_standing = None
    if states and every:
        index = {st.index: g for g, st in enumerate(states)}
        seed = _seed(year, week, states, every)
        rng = np.random.default_rng(seed)
        draws = np.stack([st.outlook.sample(rng, sims) for st in states], axis=1)     # sims x games
        credited = np.stack([credited_by(st.game, draws[:, g]) for g, st in enumerate(states)], axis=1)
        # a game over or postponed is what it is, whatever its margin said
        for g, st in enumerate(states):
            if st.state == "final":
                credited[:, g] = st.leader
            elif st.state == "off":
                credited[:, g] = NOBODY
        blown = _routs(draws, states, seed + 1)
        for g, st in enumerate(states):
            if st.state == "final" and st.margin is None:
                blown[HOME][:, g] = st.blowout_home >= 0.5
                blown[AWAY][:, g] = st.blowout_away >= 0.5
            elif st.state == "off":
                blown[HOME][:, g] = blown[AWAY][:, g] = False

        picks = np.zeros((len(every), len(states)), dtype=int)
        for c, card in enumerate(every):
            for game_index, side in card.picks.items():
                if game_index in index:
                    picks[c, index[game_index]] = side
        hits = ((picks[None, :, :] == credited[:, None, :]) & (picks[None, :, :] != 0)).sum(axis=2)
        losers = np.zeros((sims, len(every)), dtype=int)
        for c, card in enumerate(every):
            for game_index, side in card.losers:
                if game_index in index:
                    losers[:, c] += blown[side][:, index[game_index]]
        totals = hits + losers                                              # sims x cards

        in_field = np.array([c.in_field for c in every])
        if in_field.any():
            field_totals = totals[:, in_field]
            top = field_totals.max(axis=1)
            winners = field_totals == top[:, None]
            count = winners.sum(axis=1)
            pot = (top[:, None] - field_totals).sum(axis=1)
            share = np.zeros(totals.shape, dtype=float)
            net = np.zeros(totals.shape, dtype=float)
            share[:, in_field] = winners / count[:, None]
            net[:, in_field] = np.where(winners, (pot / count)[:, None],
                                        -(top[:, None] - field_totals).astype(float))
            # A card outside the field (Deadeye; yours when the sheet hasn't
            # you on it): what the week would have done for it had it been in.
            for c, card in enumerate(every):
                if card.in_field:
                    continue
                mine = totals[:, c]
                best = np.maximum(top, mine)
                level = (field_totals == best[:, None]).sum(axis=1) + (mine == best)
                pot_with = (best[:, None] - field_totals).sum(axis=1) + (best - mine)
                share[:, c] = np.where(mine == best, 1.0 / level, 0.0)
                net[:, c] = np.where(mine == best, pot_with / level, -(best - mine).astype(float))
        else:
            share = net = None

        # where everyone stands now
        def banked_of(card: Card) -> tuple[int, int, int, int, int]:
            banked = now = most = 0
            banked_l = now_l = 0
            for st in states:
                side = card.picks.get(st.index, NOBODY)
                if side:
                    if st.state == "final":
                        banked += st.leader == side
                        now += st.leader == side
                        most += st.leader == side
                    elif st.state == "in":
                        now += st.leader == side
                        most += 1
                    elif st.state == "pre":
                        most += 1
            for game_index, side in card.losers:
                st = states[index[game_index]] if game_index in index else None
                if st is None:
                    continue
                if st.state == "final":
                    hit = st.blowout(side) >= 0.5
                    banked_l += hit
                    now_l += hit
                    most += hit
                elif st.state == "in":
                    m = st.margin
                    if m is not None:
                        now_l += (m <= -BLOWOUT) if side == HOME else (m >= BLOWOUT)
                    most += 1
                elif st.state == "pre":
                    most += 1
            return banked, banked_l, now, now_l, most

        now_totals = {}
        rows = []
        for c, card in enumerate(every):
            banked, banked_l, now, now_l, most = banked_of(card)
            now_totals[c] = now + now_l
            rows.append((c, card, banked, banked_l, now, now_l, most))
        field_now = [now_totals[c] for c, card in enumerate(every) if card.in_field]
        best_now = max(field_now, default=0)
        pot_now = sum(best_now - v for v in field_now)
        leaders_now = sum(1 for v in field_now if v == best_now)
        for c, card, banked, banked_l, now, now_l, most in rows:
            total = now + now_l
            if card.in_field:
                place = 1 + sum(1 for v in field_now if v > total)
                money_now = (pot_now / leaders_now) if total == best_now else -(best_now - total)
            else:
                place = None
                if not field_now:
                    money_now = None
                else:
                    best = max(best_now, total)
                    level = sum(1 for v in field_now if v == best) + (total == best)
                    pot_with = sum(best - v for v in field_now) + (best - total)
                    money_now = pot_with / level if total == best else -(best - total)
            standing = Standing(
                card=card, banked=banked, banked_losers=banked_l, now=now, now_losers=now_l,
                most=most, place=place,
                chance=float(share[:, c].mean()) if share is not None else None,
                money=float(net[:, c].mean()) if net is not None else None,
                money_now=float(money_now) if money_now is not None else None,
            )
            if card.ghost:
                ghost_standing = standing
            else:
                if card.in_field:
                    standings.append(standing)
                if card.you:
                    you_standing = standing
        standings.sort(key=lambda s: (-s.total_now, -(s.chance or 0.0), s.card.name.casefold()))

        # what to root for: the results still to come that move your chance most
        mine = next((c for c, card in enumerate(every) if card.you), None)
        if mine is not None and share is not None:
            yours = share[:, mine]
            floor = max(20, sims // 100)
            for g, st in enumerate(states):
                if st.state not in ("pre", "in"):
                    continue
                home = credited[:, g] == HOME
                away = credited[:, g] == AWAY
                if home.sum() >= floor and away.sum() >= floor:
                    if_home, if_away = float(yours[home].mean()), float(yours[away].mean())
                    side = HOME if if_home >= if_away else AWAY
                    roots.append(Root(st, side, "pick",
                                      max(if_home, if_away), min(if_home, if_away),
                                      float((home if side == HOME else away).mean())))
            for game_index, side in every[mine].losers:
                g = index.get(game_index)
                if g is None or states[g].state not in ("pre", "in"):
                    continue
                hit = blown[side][:, g]
                if hit.sum() >= floor and (~hit).sum() >= floor:
                    roots.append(Root(states[g], side, "loser", float(yours[hit].mean()),
                                      float(yours[~hit].mean()), float(hit.mean())))
            roots.sort(key=lambda r: -abs(r.swing))
    return Board(
        year=year, week=week, states=states, standings=standings,
        you=you_standing, ghost=ghost_standing, roots=roots,
        entrants=sum(1 for c in every if c.in_field),
        has_sheet=any(c.in_field for c in every),
        checked=results.checked_at(year, week) if states else None,
    )


# ---- the side pools, as they stand -----------------------------------------------------------
@dataclass(frozen=True)
class LoserNow:
    state: GameNow
    side: int                  # the team held to lose big
    held: int                  # cards holding it
    yours: bool
    status: str                # "hit", "missed", "on" (losing by 15+ now), "close", "alive", "to play"


def losers_now(bd: Board) -> list[LoserNow]:
    """Every Big Loser someone holds, as it stands - hits and live ones first."""
    holders: dict[tuple[int, int], list[Card]] = {}
    for st in bd.standings + ([bd.you] if bd.you and not bd.you.card.in_field else []):
        for spot in st.card.losers:
            holders.setdefault(spot, []).append(st.card)
    by_index = {st.index: st for st in bd.states}
    out = []
    for (game_index, side), held in holders.items():
        st = by_index.get(game_index)
        if st is None:
            continue
        m = st.margin
        lost_by = None if m is None else (-m if side == HOME else m)
        if st.state == "final":
            status = "hit" if st.blowout(side) >= 0.5 else "missed"
        elif st.state == "in" and lost_by is not None:
            status = "on" if lost_by >= BLOWOUT else "close" if lost_by >= BLOWOUT - 7 else "alive"
        else:
            status = "to play"
        out.append(LoserNow(st, side, len(held), any(c.you for c in held), status))
    order = {"on": 0, "hit": 1, "close": 2, "alive": 3, "to play": 4, "missed": 5}
    out.sort(key=lambda l: (order[l.status], -l.held))
    return out


@dataclass(frozen=True)
class SurvivorNow:
    card: Card
    state: GameNow | None
    side: int
    status: str                # "safe", "out", "winning", "losing", "to play"
    chance: float              # of surviving the week


def suicide_now(season: Season, bd: Board) -> list[SurvivorNow]:
    """The suicide pool this week: everyone still in, their team, and how it stands.
    The pool's lines apply - a lined favourite has to cover to survive."""
    by_index = {st.index: st for st in bd.states}
    out = []
    pool = bd.standings + ([bd.you] if bd.you and not bd.you.card.in_field else [])
    for standing in pool:
        card = standing.card
        if card.suicide is None:
            continue
        person = season.players.get(card.key)
        if person is not None and not person.suicide_alive and person.suicide_out_week not in (None, bd.week):
            continue                     # out in an earlier week
        st = by_index.get(card.suicide[0])
        side = card.suicide[1]
        if st is None:
            continue
        if st.state == "final":
            status = "safe" if st.leader == side else "out"
        elif st.state == "in":
            status = "winning" if st.leader == side else "losing"
        else:
            status = "to play"
        out.append(SurvivorNow(card, st, side, status, st.chance(side)))
    order = {"losing": 0, "winning": 1, "to play": 2, "safe": 3, "out": 4}
    out.sort(key=lambda s: (order[s.status], s.card.name.casefold()))
    return out


def upsets(bd: Board) -> list[tuple[GameNow, float]]:
    """Finished games the pool mostly got wrong: (game, share of the field that had it)."""
    field_cards = [s.card for s in bd.standings]
    if not field_cards:
        return []
    out = []
    for st in bd.final:
        if st.leader == NOBODY:
            continue
        on = [c.picks.get(st.index) for c in field_cards if c.picks.get(st.index)]
        if not on:
            continue
        share = sum(1 for side in on if side == st.leader) / len(on)
        if share < UPSET:
            out.append((st, share))
    out.sort(key=lambda pair: pair[1])
    return out


def split(bd: Board, st: GameNow) -> tuple[int, int]:
    """(cards on home, cards on away) in the field."""
    home = sum(1 for s in bd.standings if s.card.picks.get(st.index) == HOME)
    away = sum(1 for s in bd.standings if s.card.picks.get(st.index) == AWAY)
    return home, away


def sweat(bd: Board) -> tuple[GameNow, int, int] | None:
    """The game under way with the most of the field on the side that is
    behind: (game, cards behind, side they need)."""
    best = None
    for st in bd.live:
        home, away = split(bd, st)
        behind_side = AWAY if st.leader == HOME else HOME if st.leader == AWAY else NOBODY
        behind = home if behind_side == HOME else away if behind_side == AWAY else 0
        if behind and (best is None or behind > best[1]):
            best = (st, behind, behind_side)
    return best


# ---- which week -------------------------------------------------------------------------------
def default_week(season: Season, now: float | None = None) -> int:
    """The week Game Day opens on: the one being played - from its Wednesday
    to the next, so Tuesday still shows Monday night's final - or failing
    that the latest week with games."""
    year = results.season_year(season, now)
    for week in results.calendar_weeks(year, now):
        found = season.weeks.get(week)
        if found is not None and found.games:
            return week
    weeks = [n for n, w in season.weeks.items() if w.games]
    return max(weeks, default=0)
