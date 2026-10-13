"""The slate radar: every game ahead by how it could go, not only who should win.

A pick is one number. Behind it is a whole spread of results - Deadeye's
expected margin, and how widely final scores scatter around a margin like it
(analytics.margin_distribution: the real shape of NFL scores, key numbers
and blowouts included). Reading that spread gives each game:

    upset       the betting underdog winning outright
    close       decided by three points or fewer
    rout        decided by fourteen or more
    hard        0-100, how hard the game is to call: mostly how near a coin
                flip the pick is under the pool's rules, plus how far the
                published models are from agreeing, how far Deadeye sits
                from the betting line, and weather worth mentioning

These are the same chances the card is built from, read a different way -
not a second opinion. "Hard to call" in particular predicts nothing: it says
where a pick deserves the least trust.

No Qt here.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .. import analytics
from . import evidence, pricing
from ..feeds import results
from ..models import Season
from .predictions import display_team, team_code
from ..version import MODEL_NAME

#: A betting line at least this big makes the other side a real underdog.
UNDERDOG = 3.0
CLOSE, ROUT = 3, 14
#: Published models this far apart (standard deviation, points) are split.
SPLIT = 5.0
#: Deadeye this far from the betting line (points) is worth pointing out.
GAP = 0.5
#: The week's pulse, in words: at or above each number.
PULSE = ((55, "Wide open"), (45, "Tight"), (35, "Ordinary"), (0, "Chalk"))
#: What "hard to call" is made of.
WEIGHTS = {"toss": 0.60, "split": 0.20, "gap": 0.10, "weather": 0.10}


@dataclass(frozen=True)
class Shape:
    """One game still to be played, and the spread of ways it could go."""

    index: int
    matchup: str
    pick: str               # the side the card takes
    chance: float           # ...and its chance of being credited under the pool's rules
    favourite: str          # the side Deadeye expects to win the game itself
    underdog: str
    margin: float           # by how many
    line: float | None      # the betting line for that favourite (negative: the line has the other side)
    win: float              # the favourite winning outright
    upset: float            # the underdog winning outright
    close: float
    rout: float
    gap: float | None       # points Deadeye has the favourite beyond the betting line
    split: float            # how far apart the published models are (points); 0 when too few
    hard: float             # 0-100
    flags: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()      # the situations it falls in (autopsy.matching)

    @property
    def real_underdog(self) -> bool:
        return self.line is not None and self.line >= UNDERDOG


@dataclass(frozen=True)
class Slate:
    week: int
    games: list[Shape] = field(default_factory=list)

    def _top(self, key, among=None) -> Shape | None:
        pool = [g for g in self.games if among is None or among(g)]
        return max(pool, key=key, default=None)

    @property
    def hardest(self) -> Shape | None:
        return self._top(lambda g: g.hard)

    @property
    def edge(self) -> Shape | None:
        """The game Deadeye sits furthest from the betting line on."""
        return self._top(lambda g: abs(g.gap or 0.0), lambda g: g.gap is not None and abs(g.gap) >= GAP)

    @property
    def upset(self) -> Shape | None:
        """The real underdog likeliest to win outright."""
        return self._top(lambda g: g.upset, lambda g: g.real_underdog)

    @property
    def rout(self) -> Shape | None:
        return self._top(lambda g: g.rout)

    @property
    def pulse(self) -> float:
        """0-100: how hard the week as a whole is to call - its games' average."""
        return round(sum(g.hard for g in self.games) / len(self.games), 0) if self.games else 0.0

    @property
    def mood(self) -> str:
        """The pulse in a word."""
        return next(word for floor, word in PULSE if self.pulse >= floor)

    @property
    def toss_ups(self) -> int:
        return sum(1 for g in self.games if g.chance < 0.55)

    @property
    def doubts(self) -> list[str]:
        """Where the card deserves the least trust, hardest game first."""
        flagged = sorted((g for g in self.games if g.flags), key=lambda g: -g.hard)
        return [f"{g.matchup}: {'; '.join(g.flags)}" for g in flagged]


def hard_to_call(chance: float, split: float, gap: float | None, weather: bool) -> float:
    """0-100. A lock everyone agrees on in fair weather is 0; a coin flip the
    models are split on, away from the line, in a gale, is 100."""
    parts = {
        "toss": min(1.0, max(0.0, 2 * (1 - chance))),
        "split": min(1.0, split / (2 * SPLIT)),
        "gap": min(1.0, abs(gap or 0.0) / 3.0),
        "weather": 1.0 if weather else 0.0,
    }
    return round(100 * sum(WEIGHTS[name] * value for name, value in parts.items()), 0)


def _spread_of_results(margin: float, sd: float) -> tuple[float, float, float, float]:
    """(favourite wins, underdog wins, within three, by fourteen or more) for a favourite by `margin`."""
    win = upset = close = rout = 0.0
    for points, chance in analytics.margin_distribution(round(abs(margin), 1), round(max(sd, 1.0), 1)):
        if points > 0:
            win += chance
        elif points < 0:
            upset += chance
        if abs(points) <= CLOSE:
            close += chance
        if abs(points) >= ROUT:
            rout += chance
    return win, upset, close, rout


def build(season: Season, week: int | None = None) -> Slate:
    """Every priced game of the week ahead that hasn't been played."""
    week = analytics.upcoming_week(season) if week is None else week
    found = season.weeks.get(week)
    if found is None:
        return Slate(week)
    games = sorted(found.games, key=lambda g: g.index)
    ctx = pricing.context(season, week, games)
    year = results.season_year(season)
    out: list[Shape] = []
    for price in pricing.price_week(season, week, games, ctx):
        game, said = price.game, price.prediction()
        if said is None or price.margin is None or game.played:
            continue
        home_favoured = price.margin >= 0
        favourite, underdog = (game.home, game.away) if home_favoured else (game.away, game.home)
        sign = 1.0 if home_favoured else -1.0
        win, upset, close, rout = _spread_of_results(price.margin, price.sd)
        forecast = ctx.forecasts.get(game.index)
        opinions = list(getattr(forecast, "opinions", ()) or ())
        split = statistics.pstdev(opinions) if len(opinions) >= 3 else 0.0
        gap = None if price.base is None else round(sign * (price.margin - price.base), 1)
        try:
            from ..feeds import weather
            sky = weather.game(year, week, game.away, game.home)
        except Exception:  # noqa: BLE001 - the radar stands without the forecast
            sky = None
        rough = bool(sky is not None and sky.notable)
        flags = []
        if said.chance < 0.55:
            flags.append(f"a toss-up at {said.chance:.0%}")
        if split >= SPLIT:
            flags.append(f"the published models are {split:.1f} points apart")
        if gap is not None and abs(gap) >= 1.0:
            flags.append(f"{MODEL_NAME} has {display_team(favourite)} {abs(gap):g} "
                         f"point{'' if abs(gap) == 1 else 's'} {'better' if gap > 0 else 'worse'} than the betting line does")
        if game.line is None and price.base is not None and abs(price.base) >= evidence.LINE_LIKELY:
            flags.append("a pool line is likely still to come, and often changes the pick")
        if rough:
            flags.append(sky.words())
        try:
            from . import autopsy, luck
            line_side = None
            if price.base is not None:
                with_line = luck.credited_chance(game, price.base, game.home)
                line_side = None if with_line is None or with_line == 0.5 else (game.home if with_line > 0.5 else game.away)
            home_pick = team_code(said.pick) == team_code(game.home)
            kickoff = evidence._kickoff(year, week, game)
            tags = autopsy.matching(autopsy.Graded(
                week=week, index=game.index, matchup=game.label, pick=display_team(said.pick), chance=said.chance,
                right=False, margin=0.0,
                line=None if price.base is None else (price.base if home_pick else -price.base),
                line_pick=display_team(line_side) if line_side else "",
                pool_line=game.line if game.line_favourite else None, home_pick=home_pick,
                divisional=autopsy.same_division(game.home, game.away),
                night=None if not kickoff else autopsy.at_night(kickoff),
            ))
        except Exception:  # noqa: BLE001 - the radar stands without them
            tags = ()
        out.append(Shape(
            tags=tags,
            index=game.index, matchup=game.label, pick=display_team(said.pick), chance=said.chance,
            favourite=display_team(favourite), underdog=display_team(underdog), margin=abs(price.margin),
            line=None if price.base is None else sign * price.base,
            win=win, upset=upset, close=close, rout=rout, gap=gap, split=split,
            hard=hard_to_call(said.chance, split, gap, rough), flags=tuple(flags),
        ))
    return Slate(week, out)
