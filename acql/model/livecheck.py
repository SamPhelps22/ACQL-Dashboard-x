"""Are the live chances honest? (idea #96)

Game Day prices a game under way from its score, the time left and the line
before kickoff (gameday.outlook: the pre-game edge scaled by the time left,
the spread shrunk by its square root). That rule has never been checked
against how games ended. This replays every finished game with a kept
scoring timeline: at fixed points of the game it rebuilds the score, asks
the live rule for the home side's chance of winning, and compares with the
result.

Two answers: the Brier score at each checkpoint (lower is better; 0.25 is a
coin flip) and calibration bands across all checkpoints - did the 70-80%
calls win about 75%? Small samples are said to be small.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Share of regulation still to play at each checkpoint: kickoff, end of Q1, half, Q3, 6 minutes left.
CHECKPOINTS = (1.0, 0.75, 0.5, 0.25, 0.1)
QUARTER_S = 900
BANDS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))
#: Below this many calls a band is only something to watch.
FEW = 20


@dataclass(frozen=True)
class Call:
    week: int
    matchup: str
    left: float
    chance: float          # the live rule's chance the home side wins
    home_won: bool


@dataclass(frozen=True)
class Band:
    low: float
    high: float
    calls: int
    said: float            # the average chance given
    came: float            # how often it happened

    @property
    def few(self) -> bool:
        return self.calls < FEW


@dataclass(frozen=True)
class Study:
    games: int
    calls: list[Call]
    brier: dict[float, tuple[float, int]]      # checkpoint -> (Brier score, calls)
    bands: list[Band]


def _elapsed(period: int, clock: str) -> float | None:
    """Seconds of regulation played when a play happened."""
    try:
        minutes, seconds = (clock or "0:00").split(":")
        remaining = int(minutes) * 60 + int(float(seconds))
    except ValueError:
        return None
    if period < 1:
        return None
    if period > 4:
        return 4 * QUARTER_S
    return (period - 1) * QUARTER_S + (QUARTER_S - remaining)


def score_at(moments, left: float) -> tuple[int, int]:
    """(home, away) at a point of the game, from its scoring plays."""
    played = (1.0 - left) * 4 * QUARTER_S
    home = away = 0
    for m in moments:
        at = _elapsed(m.period, m.clock)
        if at is None or at > played:
            break
        home, away = m.home, m.away
    return home, away


def chance_at(home: int, away: int, left: float, expected: float, sd: float) -> float:
    from ..pool import gameday
    look = gameday.outlook(home - away, left, expected, sd, started=left < 1.0)
    return look.at_least(1) + 0.5 * (look.at_least(0) - look.at_least(1))


def calls(season) -> tuple[int, list[Call]]:
    """(games replayed, every checkpoint call) for the season's finished games."""
    from .. import analytics
    from ..feeds import results, timeline
    from . import pricing
    from .predictions import team_code
    year = results.season_year(season)
    out, games = [], 0
    for number in sorted(season.weeks):
        week = season.weeks[number]
        played = [g for g in week.games if g.played and g.home_points is not None and g.away_points is not None]
        if not played:
            continue
        try:
            margins = pricing.market_margins(number, sorted(week.games, key=lambda g: g.index))
        except Exception:  # noqa: BLE001
            continue
        scores = results.load(year, number)
        for g in played:
            expected = margins.get(g.index)
            score, _ = results.find(scores, g.away, g.home)
            if expected is None or score is None:
                continue
            kept = timeline.load(year, number, score.away, score.home)
            if kept is None:
                continue
            flipped = score.home != team_code(g.home)
            games += 1
            final = g.home_points - g.away_points
            if final == 0:
                continue                      # a tie answers neither side
            for left in CHECKPOINTS:
                home, away = score_at(kept.moments, left)
                if flipped:
                    home, away = away, home
                out.append(Call(number, g.label, left, chance_at(home, away, left, expected, analytics.SPREAD_SD),
                                final > 0))
    return games, out


def study(season, found: tuple[int, list[Call]] | None = None) -> Study:
    games, made = calls(season) if found is None else found
    brier = {}
    for left in CHECKPOINTS:
        at = [c for c in made if c.left == left]
        if at:
            brier[left] = (sum((c.chance - c.home_won) ** 2 for c in at) / len(at), len(at))
    bands = []
    for low, high in BANDS:
        inside = [c for c in made if low <= c.chance < high]
        if inside:
            bands.append(Band(low, min(high, 1.0), len(inside), sum(c.chance for c in inside) / len(inside),
                              sum(1 for c in inside if c.home_won) / len(inside)))
    return Study(games, made, brier, bands)


def describe(left: float) -> str:
    return {1.0: "Kickoff", 0.75: "End of Q1", 0.5: "Half-time", 0.25: "End of Q3", 0.1: "6 min left"}.get(
        left, f"{left:.0%} left")
