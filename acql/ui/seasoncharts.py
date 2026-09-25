"""The numbers behind the Charts tab - worked out once, drawn by funcharts.py.

Every function here reads the same finished, official weeks as the pool page
(poolpage.finished_weeks), so the dashboard's charts and the website agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from .. import analytics
from ..config import WEEKS_IN_SEASON
from ..models import Season
from ..predictions import display_team
from . import poolpage

TITLE_SIMS = 2000        # per week; enough for a smooth line, quick to redraw
TITLE_LINES = 6          # contenders drawn on the title-odds chart


def weeks(season: Season) -> list[int]:
    return poolpage.finished_weeks(season)


def _names(season: Season) -> dict[str, str]:
    return {key: p.display for key, p in season.players.items()}


def _weekly(season: Season, shown: list[int]) -> dict[str, dict[int, int]]:
    """key -> week -> total wins (Big Loser points included), from the week sheets."""
    out: dict[str, dict[int, int]] = {}
    for number in shown:
        for key, line in season.weeks[number].lines.items():
            out.setdefault(key, {})[number] = int(line.total_wins or 0)
    return out


def _places(totals: dict[str, int]) -> dict[str, int]:
    """Competition ranking: players level on wins share the better place."""
    return {k: 1 + sum(1 for v in totals.values() if v > mine) for k, mine in totals.items()}


# ---- the season race ------------------------------------------------------------
def race(season: Season) -> tuple[list[int], list[tuple[str, list[int]]]]:
    """(weeks, [(coach, place after each week)]) - current order, leader first."""
    shown = weeks(season)
    names = _names(season)
    weekly = _weekly(season, shown)
    places_by_week = []
    running = {key: 0 for key in weekly}
    for number in shown:
        for key, scores in weekly.items():
            running[key] += scores.get(number, 0)
        places_by_week.append(_places(running))
    if not places_by_week:
        return [], []
    last = places_by_week[-1]
    order = sorted(weekly, key=lambda k: (last[k], names.get(k, k).casefold()))
    return shown, [(names.get(k, k), [pw[k] for pw in places_by_week]) for k in order]


# ---- where everyone landed ---------------------------------------------------------
@dataclass(frozen=True)
class Landed:
    week: int
    scores: list[tuple[str, int]]      # every coach's total, best first
    winners: list[str]
    average: float


def landed(season: Season, number: int) -> Landed | None:
    week = season.weeks.get(number)
    if week is None or not week.lines:
        return None
    names = _names(season)
    scores = sorted(((names.get(k, line.player), int(line.total_wins or 0)) for k, line in week.lines.items()),
                    key=lambda s: (-s[1], s[0].casefold()))
    top = scores[0][1] if scores else 0
    return Landed(
        week=number,
        scores=scores,
        winners=[n for n, t in scores if t == top],
        average=sum(t for _, t in scores) / len(scores) if scores else 0.0,
    )


# ---- the suicide pool funnel ----------------------------------------------------------
@dataclass(frozen=True)
class FunnelWeek:
    week: int
    alive_before: int
    knocked: int
    teams: list[tuple[str, int]]       # (team, coaches it knocked out), most first

    @property
    def left(self) -> int:
        return self.alive_before - self.knocked


def funnel(season: Season) -> list[FunnelWeek]:
    shown = weeks(season)
    status = poolpage._suicide_status(season, shown)
    entered = {k for k, (alive, out) in status.items() if alive or out is not None}
    rows = []
    for number in shown:
        before = sum(1 for k in entered if status[k][1] is None or status[k][1] >= number)
        out_now = [k for k in entered if status[k][1] == number]
        teams: dict[str, int] = {}
        for key in out_now:
            pick = season.players[key].suicide_picks.get(number, "")
            team = display_team(pick) if pick else "?"
            teams[team] = teams.get(team, 0) + 1
        rows.append(FunnelWeek(number, before, len(out_now),
                               sorted(teams.items(), key=lambda t: (-t[1], t[0]))))
    return rows


# ---- hot and cold --------------------------------------------------------------------
def hot_cold(season: Season) -> tuple[list[str], list[int], list[list[float | None]]]:
    """(coaches in standings order, weeks, wins above/below that week's average)."""
    shown, order = race(season)
    names = _names(season)
    by_name = {names.get(k, k): k for k in season.players}
    weekly = _weekly(season, shown)
    averages = {}
    for number in shown:
        scores = [s[number] for s in weekly.values() if number in s]
        averages[number] = sum(scores) / len(scores) if scores else 0.0
    rows, values = [], []
    for name, _ in order:
        key = by_name.get(name)
        mine = weekly.get(key, {})
        rows.append(name)
        values.append([round(mine[n] - averages[n], 1) if n in mine else None for n in shown])
    return rows, shown, values


# ---- the crowd against the results -----------------------------------------------------
@dataclass(frozen=True)
class CrowdGame:
    week: int
    matchup: str
    winner: str
    line: str
    right: int
    entrants: int

    @property
    def share(self) -> float:
        return self.right / self.entrants if self.entrants else 0.0


def crowd(season: Season) -> list[CrowdGame]:
    out = []
    for number in weeks(season):
        entrants = len(season.weeks[number].lines)
        for game in poolpage._week_games(season, number):
            if game["right"] is None or not game["winner"]:
                continue
            out.append(CrowdGame(number, game["matchup"], game["winner"], game["line"],
                                 int(game["right"]), entrants))
    return out


# ---- title odds, week by week ----------------------------------------------------------
def title_history(season: Season, *, highlight: str = "", sims: int = TITLE_SIMS,
                  ) -> tuple[list[int], list[tuple[str, list[float]]]]:
    """(weeks, [(coach, % chance of the title as it stood after each week)]).

    The same simulation as the Projections tab, re-run as the season stood
    after each finished week. The contenders drawn are the current top few,
    plus whoever is highlighted.
    """
    shown = weeks(season)
    if not shown:
        return [], []
    names = _names(season)
    weekly = _weekly(season, shown)
    keys = sorted(weekly)
    history: dict[str, list[float]] = {k: [] for k in keys}
    for number in shown:
        players = []
        for key in keys:
            done = {w: v for w, v in weekly[key].items() if w <= number}
            total = sum(done.values())
            players.append(SimpleNamespace(wins=total, season_wins=total, weekly_wins=done))
        remaining = max(0, WEEKS_IN_SEASON - number)
        title, _ = analytics.simulate(players, remaining, sims=sims)
        for key, odds in zip(keys, title):
            history[key].append(round(100 * float(odds), 1))     # percent
    latest = sorted(keys, key=lambda k: (-history[k][-1], names.get(k, k).casefold()))
    chosen = latest[:TITLE_LINES]
    wanted = next((k for k in keys if names.get(k, k) == highlight), None)
    if wanted and wanted not in chosen:
        chosen.append(wanted)
    return shown, [(names.get(k, k), history[k]) for k in chosen]
