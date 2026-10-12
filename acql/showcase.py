"""The numbers behind the model's charts: Deadeye's season, drawn seven ways.

Every chart here is cut from the same thing - each graded game as Deadeye
had it going in (autopsy.graded) - so the seven agree with each other and
with the Hits & misses page:

    trajectory      who is ahead, pick by pick: Deadeye, the betting line's
                    own side, and a baseline (the dashboard's ratings alone)
    calibration     picks it called 60%: did about 60% of them come in?
    buckets         the same, in four confidence bands
    matrix          where it does well and badly, by the kind of game
    scope           the margin it expected against the margin that happened
    rolling         its last twenty picks, against what luck alone covers
    miss_sizes      how far off its margins were, in bands of points

"Right" always means credited under the pool's rules - the pool's line on
the big favourites, straight up otherwise - which is what a card is scored
on. Nothing here is money: the pool is not a book of bets, so there are no
units won or lost to draw, and none are invented.

No Qt here: ui/modelcharts.py draws them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import autopsy, luck, results, teamstrength
from .models import Season
from .predictions import team_code
from .version import MODEL_NAME

LINE, BASELINE = "Betting line", "Ratings alone"
#: Picks in the rolling window.
WINDOW = 20
#: A cell of the matrix needs this many picks to be shaded at all.
CELL = 5
#: The confidence bands: (label, from, up to but not including).
BANDS = (("50-54%", 0.50, 0.55), ("55-59%", 0.55, 0.60), ("60-64%", 0.60, 0.65), ("65% and up", 0.65, 1.01))
FINER = (("50-54%", 0.50, 0.55), ("55-59%", 0.55, 0.60), ("60-64%", 0.60, 0.65), ("65-69%", 0.65, 0.70),
         ("70-79%", 0.70, 0.80), ("80% and up", 0.80, 1.01))
#: How far off a margin was, in points: (label, from, up to but not including).
MISS_BANDS = (("0-3", 0.0, 3.5), ("4-7", 3.5, 7.5), ("8-13", 7.5, 13.5), ("14-20", 13.5, 20.5), ("21 or more", 20.5, 999.0))
#: The kinds of game the matrix shows, by their names in autopsy.CUTS.
KINDS = ("The betting favourite", "The betting underdog", "The home team", "The road team",
         "Division games", "Outside the division", "Line within 3", "Line 3.5 to 6.5", "Line 7 or more",
         "Pool-line games", "Straight-up games", "Night games", "Day games")


def ordered(games: list[autopsy.Graded]) -> list[autopsy.Graded]:
    return sorted(games, key=lambda g: (g.week, g.index))


def baseline(season: Season) -> dict[tuple[int, int], bool]:
    """(week, game) -> whether the dashboard's ratings alone had the credited side.
    The ratings are the ones standing as each week began, so this is a fair fight."""
    year = results.season_year(season)
    out: dict[tuple[int, int], bool] = {}
    for number in sorted(season.weeks):
        strength = None
        for game in season.weeks[number].games:
            winner = team_code(game.winner)
            if not game.played or winner not in (team_code(game.home), team_code(game.away)):
                continue
            strength = strength or teamstrength.before(season, number, year)
            margin = strength.margin(game.home, game.away)
            chance = luck.credited_chance(game, margin, game.home) if margin is not None else None
            if chance is None or chance == 0.5:
                continue
            out[(number, game.index)] = (chance > 0.5) == (winner == team_code(game.home))
    return out


# ---- who is ahead, pick by pick -------------------------------------------------------------
@dataclass(frozen=True)
class Line:
    name: str
    above: list[float]          # games above a coin flip after each pick
    right: int
    picks: int

    @property
    def rate(self) -> float:
        return self.right / self.picks if self.picks else 0.0


@dataclass(frozen=True)
class Trajectory:
    lines: list[Line]
    weeks: list[tuple[int, int]]        # (the pick each week starts at, the week)
    labels: list[str]                   # one per pick: "Week 3 - Dallas @ Miami"

    @property
    def picks(self) -> int:
        return len(self.labels)


def trajectory(games: list[autopsy.Graded], base: dict[tuple[int, int], bool] | None = None) -> Trajectory:
    """Deadeye, the betting line and the baseline over the games all three had a side in."""
    base = base or {}
    shared = [g for g in ordered(games) if g.line_right is not None and (not base or (g.week, g.index) in base)]
    weeks, seen = [], set()
    for n, g in enumerate(shared, 1):
        if g.week not in seen:
            seen.add(g.week)
            weeks.append((n, g.week))

    def line(name: str, hits: list[bool]) -> Line:
        above, total = [], 0.0
        for hit in hits:
            total += 0.5 if hit else -0.5
            above.append(total)
        return Line(name, above, sum(hits), len(hits))

    lines = [line(MODEL_NAME, [g.right for g in shared]), line(LINE, [bool(g.line_right) for g in shared])]
    if base:
        lines.append(line(BASELINE, [base[(g.week, g.index)] for g in shared]))
    return Trajectory(lines, weeks, [f"Week {g.week} - {g.matchup}" for g in shared])


# ---- are its chances honest -----------------------------------------------------------------
@dataclass(frozen=True)
class Band:
    label: str
    picks: int = 0
    right: int = 0
    said: float = 0.0           # the average chance it gave these picks
    luck: float = 0.0           # how far luck alone moves the rate, one spread

    @property
    def rate(self) -> float:
        return self.right / self.picks if self.picks else 0.0


def _bands(games: list[autopsy.Graded], bands) -> list[Band]:
    out = []
    for label, low, high in bands:
        inside = [g for g in games if low <= g.chance < high]
        if not inside:
            out.append(Band(label))
            continue
        n = len(inside)
        out.append(Band(label, n, sum(g.right for g in inside), sum(g.chance for g in inside) / n,
                        math.sqrt(sum(g.chance * (1 - g.chance) for g in inside)) / n))
    return out


def buckets(games: list[autopsy.Graded]) -> list[Band]:
    """The four confidence bands, every one listed (an empty one has no picks)."""
    return _bands(games, BANDS)


def calibration(games: list[autopsy.Graded]) -> list[Band]:
    """Finer bands, the empty ones left out."""
    return [b for b in _bands(games, FINER) if b.picks]


# ---- where it does well and badly ------------------------------------------------------------
@dataclass(frozen=True)
class Kind:
    name: str
    picks: int
    rate: float | None          # Deadeye's hit rate; None with too few picks to shade
    line: float | None          # the betting line's own side, on the same games
    said: float | None          # what its own chances called for
    right: int = 0


def matrix(games: list[autopsy.Graded]) -> list[Kind]:
    rows = {row.name: row for _title, cut in autopsy.situations(games) for row in cut}
    out = []
    for name in KINDS:
        row = rows.get(name)
        if row is None or not row.picks:
            continue
        enough = row.picks >= CELL
        out.append(Kind(
            name, row.picks, row.rate if enough else None,
            row.line_right / row.line_games if enough and row.line_games == row.picks else None,
            row.expected_rate if enough else None, row.right,
        ))
    return out


# ---- the margin it expected against the one that happened -------------------------------------
@dataclass(frozen=True)
class Point:
    label: str
    expected: float             # from the pick's side
    actual: float
    right: bool
    short: str = ""             # "Chicago, wk 3" - for the few that are named on the chart

    @property
    def error(self) -> float:
        return abs(self.actual - self.expected)


def scope(games: list[autopsy.Graded]) -> list[Point]:
    return [Point(f"Week {g.week} - {g.matchup}: took {g.pick}", g.margin, g.actual, g.right,
                  f"{g.pick}, wk {g.week}")
            for g in ordered(games) if g.actual is not None]


def mean_error(points: list[Point]) -> float:
    return sum(p.error for p in points) / len(points) if points else 0.0


def miss_sizes(games: list[autopsy.Graded]) -> list[tuple[str, int, int]]:
    """(band of points, games Deadeye's margin was off by that much, games the betting line's was)."""
    scored = [g for g in games if g.actual is not None and g.line is not None]
    out = []
    for label, low, high in MISS_BANDS:
        out.append((label, sum(low <= abs(g.actual - g.margin) < high for g in scored),
                    sum(low <= abs(g.actual - g.line) < high for g in scored)))
    return out


# ---- its last twenty picks ---------------------------------------------------------------------
@dataclass(frozen=True)
class Rolling:
    picks: list[int]            # the pick each window ends on
    rate: list[float]           # share right over the window
    said: list[float]           # what its chances called for over the same window
    reach: list[float]          # how far luck alone moves the rate, one spread
    window: int = WINDOW

    @property
    def latest(self) -> float | None:
        return self.rate[-1] if self.rate else None


def rolling(games: list[autopsy.Graded], window: int = WINDOW) -> Rolling:
    played = ordered(games)
    picks, rate, said, reach = [], [], [], []
    for end in range(window, len(played) + 1):
        part = played[end - window:end]
        picks.append(end)
        rate.append(sum(g.right for g in part) / window)
        said.append(sum(g.chance for g in part) / window)
        reach.append(math.sqrt(sum(g.chance * (1 - g.chance) for g in part)) / window)
    return Rolling(picks, rate, said, reach, window)


# ---- all of it ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Showcase:
    games: list[autopsy.Graded]
    trajectory: Trajectory
    calibration: list[Band]
    buckets: list[Band]
    matrix: list[Kind]
    scope: list[Point]
    rolling: Rolling
    miss_sizes: list[tuple[str, int, int]]

    @property
    def weeks(self) -> list[int]:
        return sorted({g.week for g in self.games})


def build(season: Season) -> Showcase:
    games = autopsy.graded(season)
    try:
        base = baseline(season)
    except Exception:  # noqa: BLE001 - the trajectory stands without the baseline
        base = {}
    return Showcase(games, trajectory(games, base), calibration(games), buckets(games), matrix(games),
                    scope(games), rolling(games), miss_sizes(games))
