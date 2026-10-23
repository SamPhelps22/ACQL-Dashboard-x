"""The suicide pool as a path: one team a week to the end of the season (idea #56).

survivor.advise answers "which team this week". This lays out the whole road
ahead with the same numbers: every week left, each unused team's chance of
surviving it (this week from the market, later weeks from the line-based
ratings), and a path that uses each team once. The path is chosen greedily -
the surest week-and-team pairing first, then the next among what's left -
which is simple, fast and close to the best possible, and it shows the
runner-up for each week too.

A plan, not a pick: next week's lines will move it. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Season
from . import survivor

#: How many weeks ahead the path runs (the pool rarely lasts longer).
AHEAD = 8


@dataclass(frozen=True)
class Step:
    week: int
    team: str
    opponent: str
    home: bool
    chance: float
    alternate: str = ""          # the next-best unused team that week
    alternate_chance: float | None = None


@dataclass(frozen=True)
class Path:
    coach: str
    steps: list[Step]

    @property
    def survive_all(self) -> float:
        out = 1.0
        for s in self.steps:
            out *= s.chance
        return out


def grid(season: Season, coach_key: str, week: int, last: int) -> dict[tuple[int, str], tuple[float, str, bool]]:
    """{(week, team code): (chance, opponent, home)} for every unused team, weeks week..last."""
    from ..feeds import schedule
    from ..model import predictions
    spent = {code for _w, code in survivor.used_teams(season, coach_key)}
    rating = survivor.ratings(survivor._lines_so_far(week))
    market = survivor._this_week_lines(week, season)
    out = {}
    for team in schedule.teams():
        code = predictions.team_code(team)
        if not code or code in spent:
            continue
        for w in range(week, last + 1):
            found = schedule.fixture(team, w)
            if found is None:
                continue
            opponent, home = found
            if w == week and code in market:
                chance = survive_chance_now(season, w, team, market[code])
            else:
                chance = survivor._chance(rating, code, predictions.team_code(opponent), home)
            out[(w, code)] = (chance, predictions.display_team(opponent), home)
    return out


def survive_chance_now(season: Season, week: int, team: str, margin: float) -> float:
    posted = survivor._posted_line(season, week, team)
    if posted is not None:
        line, is_fav = posted
    else:
        line, is_fav = survivor.assumed_line(margin), margin > 0
    return survivor.survive_chance(margin, line, is_fav)


def choose(cells: dict[tuple[int, str], tuple[float, str, bool]], weeks: list[int]) -> list[Step]:
    """The greedy path: the surest (week, team) first, each week and team once."""
    from ..model import predictions
    left_weeks, used, chosen = set(weeks), set(), {}
    for (w, code), (chance, opp, home) in sorted(cells.items(), key=lambda kv: -kv[1][0]):
        if w in left_weeks and code not in used:
            chosen[w] = (code, chance, opp, home)
            left_weeks.discard(w)
            used.add(code)
        if not left_weeks:
            break
    steps = []
    for w in sorted(chosen):
        code, chance, opp, home = chosen[w]
        others = sorted(((c, k) for (wk, k), (c, _o, _h) in cells.items() if wk == w and k not in used),
                        reverse=True)
        alt = others[0] if others else None
        steps.append(Step(w, predictions.display_team(code), opp, home, chance,
                          predictions.display_team(alt[1]) if alt else "", alt[0] if alt else None))
    return steps


def plan(season: Season, coach_key: str, week: int, ahead: int = AHEAD) -> Path | None:
    from ..feeds import schedule
    player = season.players.get(coach_key)
    if player is None or not player.suicide_alive:
        return None
    last = min(week + ahead - 1, survivor.WEEKS_IN_SEASON, schedule.WEEKS)
    cells = grid(season, coach_key, week, last)
    return Path(player.display, choose(cells, list(range(week, last + 1))))
