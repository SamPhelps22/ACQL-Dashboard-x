"""Historical twins (idea #37): the past games most like this one, and how they ended.

For a game this week, the 30 regular-season games since 2011 closest to it
on what was known before kickoff - the betting line most of all, then the
over/under, the week, the rest gap and whether it was a division game - and
how those games actually finished: did the favourite win, cover, win big.

Mostly this is the line again, seen as real games, so it is always shown
beside what the line alone says; the point is a concrete, checkable picture
of the range of outcomes, not a second opinion. Reads the nflverse games
file already on disk (feeds/nflverse.py). No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

FIRST = 2011
COUNT = 30
#: How far apart two games are: each difference divided by its scale, added up.
SCALES = {"spread": 1.0, "total": 4.0, "week": 6.0, "rest": 7.0}
DIVISION_STEP = 1.5
BIG = 15


@dataclass(frozen=True)
class Past:
    season: int
    week: int
    label: str
    fav_spread: float          # the favourite's line, points (positive)
    total: float | None
    rest: float                # the favourite's rest minus the underdog's, days
    division: bool
    fav_margin: float          # the favourite's final margin


@dataclass(frozen=True)
class Twins:
    games: list[Past]
    fav_won: int
    fav_covered: int
    fav_big: int               # won by 15 or more
    pushes: int
    line_win: float            # what the line alone says: the favourite's chance to win
    line_cover: float

    @property
    def count(self) -> int:
        return len(self.games)


@lru_cache(maxsize=1)
def history() -> tuple[Past, ...]:
    from ..feeds import nflverse
    out = []
    for row in nflverse._rows(nflverse.GAMES_FILE):
        try:
            season = int(row["season"])
            if season < FIRST or row["game_type"] != "REG" or not row["home_score"] or not row["spread_line"]:
                continue
            spread = float(row["spread_line"])              # + home favoured
            margin = float(row["home_score"]) - float(row["away_score"])
            rest = float(row.get("home_rest") or 0) - float(row.get("away_rest") or 0)
            total = float(row["total_line"]) if row.get("total_line") else None
        except (KeyError, ValueError):
            continue
        home_fav = spread >= 0
        out.append(Past(season, int(row["week"]), f"{row['away_team']} @ {row['home_team']} {season} wk {row['week']}",
                        abs(spread), total, rest if home_fav else -rest, row.get("div_game") == "1",
                        margin if home_fav else -margin))
    return tuple(out)


def distance(p: Past, spread: float, total: float | None, week: int, rest: float, division: bool) -> float:
    d = abs(p.fav_spread - spread) / SCALES["spread"]
    if total is not None and p.total is not None:
        d += abs(p.total - total) / SCALES["total"]
    d += abs(p.week - week) / SCALES["week"] + abs(p.rest - rest) / SCALES["rest"]
    return d + (0 if p.division == division else DIVISION_STEP)


def find(spread: float, total: float | None = None, week: int = 9, rest: float = 0.0, division: bool = False,
         past: tuple[Past, ...] | None = None, count: int = COUNT) -> Twins | None:
    """The twins of a game whose favourite gives `spread` points (positive)."""
    from .. import analytics
    past = history() if past is None else past
    if not past:
        return None
    spread = abs(spread)
    near = sorted(past, key=lambda p: distance(p, spread, total, week, rest, division))[:count]
    dist = analytics.margin_distribution(round(spread, 1))
    win = sum(pr for d, pr in dist if d > 0) + 0.5 * sum(pr for d, pr in dist if d == 0)
    cover = sum(pr for d, pr in dist if d > spread)
    return Twins(near, sum(1 for p in near if p.fav_margin > 0), sum(1 for p in near if p.fav_margin > p.fav_spread),
                 sum(1 for p in near if p.fav_margin >= BIG), sum(1 for p in near if p.fav_margin == p.fav_spread),
                 win, cover)
