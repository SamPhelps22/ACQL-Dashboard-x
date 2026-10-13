"""Deadeye's own read of every team, from results alone.

The betting line and the published computer models are other people's
opinions. This is the dashboard's own: a rating for every team, worked out
from nothing but final scores - the same rating model the long replay uses
to stand in for the line (backtest.rate), carried through to this week.

Each team starts a season part of the way back toward average, and every
result moves the two teams' ratings by a share of what the rating got
wrong, with the home edge learned the same way. Over 2011-2025 it picked
about 65% of winners straight up, where the closing line gets about 66% -
a little less sharp than the market, and never having seen a line.

It is here to be tested, not trusted: the Model Lab (modellab.py) sets it
against the line, the published models and Deadeye on the same games, and
it only joins Deadeye's card if it earns the place.

No Qt here.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from . import backtest
from ..feeds import results
from ..models import Game, Season
from .predictions import team_code


@dataclass(frozen=True)
class Strength:
    """The ratings as a week begins - what was known before its games."""

    teams: dict[str, float]         # team code -> points better than an average team
    home_edge: float
    games: int                      # results the ratings rest on, all seasons

    def margin(self, home: str, away: str) -> float | None:
        """The expected home margin for a matchup, or None for a team never seen."""
        h, a = team_code(home), team_code(away)
        if h not in self.teams or a not in self.teams:
            return None
        return self.teams[h] - self.teams[a] + self.home_edge


def _code(raw: str) -> str:
    return team_code(backtest.ALIASES.get(raw.strip(), raw.strip()))


def history(year: int) -> list[tuple[int, int, str, str, float]]:
    """(season, week, home, away, home margin) for every final game known:
    the scores file for seasons past, the scoreboard's kept finals for this one."""
    # Asked for once a game by everything that prices from the ratings - so it
    # is remembered for a moment rather than read again each time (the scores
    # file alone is four thousand lines, and a page asked for it 159 times).
    held = _HISTORY.get(year)
    if held is not None and time.monotonic() - held[0] < FRESH:
        return held[1]
    seen = dict(_past())
    for week in range(1, 19):
        for s in results.load(year, week):
            if s.final and s.home_points is not None and s.away_points is not None:
                seen[(year, week, frozenset((s.home, s.away)))] = (
                    year, week, s.home, s.away, float(s.home_points - s.away_points))
    made = sorted(seen.values(), key=lambda g: (g[0], g[1]))
    _HISTORY.clear()
    _HISTORY[year] = (time.monotonic(), made)
    return made


#: How long (seconds) a history is handed back before this season's finals
#: are read again - long enough for one page to be drawn, short enough that
#: a result just in is counted the next time anything asks.
FRESH = 3.0
_HISTORY: dict[int, tuple[float, list]] = {}
_PAST: dict[tuple, dict] = {}


def _past() -> dict:
    """Seasons past, from the scores file - parsed once for each version of the file."""
    path = backtest.SCORES_FILE
    try:
        found = path.stat()
        key = (str(path), found.st_mtime_ns, found.st_size)
    except OSError:
        return {}
    if key not in _PAST:
        seen = {}
        try:
            for g in backtest.load_games():
                home, away = _code(g.home), _code(g.away)
                if home and away:
                    seen[(g.season, g.week, frozenset((home, away)))] = (g.season, g.week, home, away, g.margin)
        except OSError:
            return {}
        _PAST.clear()
        _PAST[key] = seen
    return _PAST[key]


def forget() -> None:
    """Drop what is remembered, for a test that changes the results under it."""
    _HISTORY.clear()
    _PAST.clear()
    _KEPT.clear()


def _walk(games: list[tuple[int, int, str, str, float]]):
    """backtest.rate, kept in step with it: yields each game's pre-game
    margin, and returns the ratings as each week begins and as they stand."""
    teams: dict[str, float] = defaultdict(float)
    edge = backtest.HOME_EDGE_START
    rated: dict[tuple[int, int, frozenset], float] = {}
    starts: dict[tuple[int, int], Strength] = {}
    season = week = None
    for count, (s, w, home, away, margin) in enumerate(games):
        if s != season:
            for t in teams:
                teams[t] *= 1 - backtest.PRESEASON_REGRESSION
            season, week = s, None
        if w != week:
            week = w
            starts[(s, w)] = Strength(dict(teams), edge, count)
        predicted = teams[home] - teams[away] + edge
        rated[(s, w, frozenset((home, away)))] = predicted
        miss = max(-backtest.ERROR_CAP, min(backtest.ERROR_CAP, margin - predicted))
        teams[home] += backtest.RATING_STEP * miss
        teams[away] -= backtest.RATING_STEP * miss
        edge += backtest.HOME_EDGE_STEP * miss
    return rated, starts, Strength(dict(teams), edge, len(games)), season


_KEPT: dict[tuple, tuple] = {}


def _run(year: int):
    games = history(year)
    key = (year, len(games), sum(int(g[4]) for g in games[-40:]))
    if key not in _KEPT:
        _KEPT.clear()
        _KEPT[key] = _walk(games)
    return _KEPT[key]


def before(season: Season | None, week: int, year: int | None = None) -> Strength:
    """The ratings going into a week of this season: every result before it."""
    year = year or results.season_year(season)
    _rated, starts, final, last_season = _run(year)
    if (year, week) in starts:
        return starts[(year, week)]
    # a week with no final yet: everything known so far, with the new
    # season's pull toward average if nothing of it has been played
    later = [(w, s) for (y, w), s in starts.items() if y == year and w > week]
    if later:
        return min(later, key=lambda item: item[0])[1]
    if last_season != year:
        return Strength({t: v * (1 - backtest.PRESEASON_REGRESSION) for t, v in final.teams.items()},
                        final.home_edge, final.games)
    return final


def home_margin(season: Season | None, week: int, game: Game, year: int | None = None) -> float | None:
    """What the ratings expect of a slate's game, from its home side - using
    only the results before that week."""
    return before(season, week, year).margin(game.home, game.away)


def table(season: Season | None, week: int) -> list[tuple[str, float]]:
    """(team code, rating) going into a week, best first - this season's teams only."""
    strength = before(season, week)
    year = results.season_year(season)
    current = {t for (s, _w, pair) in _run(year)[0] if s == year for t in pair}
    teams = {t: v for t, v in strength.teams.items() if not current or t in current}
    return sorted(teams.items(), key=lambda item: -item[1])
