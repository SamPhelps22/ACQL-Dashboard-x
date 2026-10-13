"""The same games for every recipe, scored the same way.

Two things are marked, and kept apart, because a recipe can be good at one
and not the other:

    the margin    how far the final margin landed from the one expected - the
                  average miss, the root of the average squared miss, and the
                  average error with its sign (plus is too kind to home teams)
    the chance    whether the side it favoured was credited under the pool's
                  rules, and how good its chances were: log loss and Brier
                  score (lower is better; a coin flip scores 0.693 and 0.250),
                  how many it expected to get right by its own chances, and
                  how far those chances were from what came in

Nothing is compared unless both recipes priced the game. And no gap is
called real because a record looks better: a difference is given with the
range it could plausibly lie in (whole weeks drawn again and again, since
games in a week share their news), and two records are only told apart on
the games they split (the Model Lab's own test, modellab.Pair).

No Qt here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..model import modellab
from .probability import CEILING, FLOOR
from .walkforward import Result

#: Times the weeks are drawn again to put a range on a difference.
DRAWS = 2000
SEED = 2026
#: How finely a recipe's own confidence is cut up to see whether it was earned.
ECE_BANDS = ((0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 0.90),
             (0.90, 1.01))


def held(chance: np.ndarray) -> np.ndarray:
    return np.clip(chance, FLOOR, CEILING)


def losses(chance: np.ndarray, came: np.ndarray) -> np.ndarray:
    """Log loss, game by game: how surprised the chance was by the result."""
    p = held(chance)
    return -(came * np.log(p) + (1 - came) * np.log(1 - p))


def hits(chance: np.ndarray, came: np.ndarray) -> np.ndarray:
    """Whether the side it favoured was credited. A dead-level 50% favours nobody (as the Model Lab scores it)."""
    return ((chance > 0.5) == (came > 0.5)) & (chance != 0.5)


@dataclass(frozen=True)
class Score:
    games: int = 0
    right: int = 0
    expected: float = 0.0           # how many it expected to get right, by its own chances
    logloss: float = 0.0
    brier: float = 0.0
    off: float = 0.0                # calibration error: how far its chances were from what came in, on average
    miss: float | None = None       # average miss on the margin, points
    rms: float | None = None        # root of the average squared miss
    lean: float | None = None       # average error, plus is too kind to home teams
    scored: int = 0                 # games with a final score to measure the margin against

    @property
    def rate(self) -> float:
        return self.right / self.games if self.games else 0.0


def calibration_error(chance: np.ndarray, came: np.ndarray) -> float:
    """The gap between how sure it was of its own side and how often that side
    came in, averaged over bands of sureness and weighted by their size."""
    sure = np.maximum(chance, 1 - chance)
    landed = hits(chance, came).astype(float)
    total = 0.0
    for low, high in ECE_BANDS:
        inside = (sure >= low) & (sure < high)
        if inside.any():
            total += inside.sum() * abs(float(sure[inside].mean()) - float(landed[inside].mean()))
    return float(total / len(chance)) if len(chance) else 0.0


def score(chance: np.ndarray, came: np.ndarray, margin: np.ndarray | None = None,
          actual: np.ndarray | None = None) -> Score:
    """One recipe over one set of games. `came` is 1 where the home side was credited."""
    if not len(chance):
        return Score()
    p = held(chance)
    out = dict(games=len(p), right=int(hits(p, came).sum()), expected=float(np.maximum(p, 1 - p).sum()),
               logloss=float(losses(p, came).mean()), brier=float(((p - came) ** 2).mean()),
               off=calibration_error(p, came))
    if margin is not None and actual is not None:
        known = ~np.isnan(actual) & ~np.isnan(margin)
        if known.any():
            error = margin[known] - actual[known]
            out.update(miss=float(np.abs(error).mean()), rms=float(np.sqrt((error ** 2).mean())),
                       lean=float(error.mean()), scored=int(known.sum()))
    return Score(**out)


def reliability(chance: np.ndarray, came: np.ndarray, bands=modellab.BANDS) -> list[dict]:
    """The picks by how sure it was of its own side, against how often they came in."""
    p = held(chance)
    sure, landed = np.maximum(p, 1 - p), hits(p, came)
    out = []
    for low, high in bands:
        inside = (sure >= low) & (sure < high)
        out.append({"band": f"{low:.0%} and up" if high > 1 else f"{low:.0%}-{high:.0%}", "picks": int(inside.sum()),
                    "said": float(sure[inside].mean()) if inside.any() else None,
                    "came": float(landed[inside].mean()) if inside.any() else None})
    return out


# ---- two recipes on the same games ---------------------------------------------------------------
def interval(values: np.ndarray, weeks: np.ndarray, draws: int = DRAWS, seed: int = SEED) -> tuple[float, float]:
    """The range the average of `values` could plausibly lie in (19 times in
    20), from drawing whole weeks again: games in a week share their news, so
    it is weeks, not games, that are independent."""
    if len(values) < 2:
        return (float("nan"), float("nan"))
    _, where = np.unique(weeks, return_inverse=True)
    sums = np.bincount(where, weights=values)
    counts = np.bincount(where).astype(float)
    if len(sums) < 2:
        return (float("nan"), float("nan"))
    picks = np.random.default_rng(seed).integers(0, len(sums), size=(draws, len(sums)))
    means = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


@dataclass(frozen=True)
class Duel:
    """`first` against `second`, game for game."""

    games: int = 0
    first_right: int = 0
    second_right: int = 0
    only_first: int = 0             # games only the first got right
    only_second: int = 0
    edge: float = 0.0               # log loss a game the first is better by (minus: worse)
    low: float = float("nan")       # the range that edge could plausibly lie in
    high: float = float("nan")
    closer: float | None = None     # points a game the first's margin is closer to the result
    closer_low: float = float("nan")
    closer_high: float = float("nan")
    sides: int = 0                  # games the two took different sides of

    @property
    def split(self) -> int:
        return self.only_first + self.only_second

    @property
    def luck(self) -> float | None:
        """The chance of a split this lopsided if the two were equally good
        (the Model Lab's test). None with too few split games to ask."""
        return modellab.Pair(games=self.games, first=self.only_first, second=self.only_second).luck

    @property
    def reading(self) -> str:
        if not self.games:
            return "no games in common"
        if math.isnan(self.low):
            return "too few weeks to put a range on it"
        if self.low > 0:
            return "better - the whole range is above zero"
        if self.high < 0:
            return "worse - the whole range is below zero"
        return "cannot be told apart - the range takes in zero"


def duel(first: np.ndarray, second: np.ndarray, came: np.ndarray, weeks: np.ndarray,
         first_margin: np.ndarray | None = None, second_margin: np.ndarray | None = None,
         actual: np.ndarray | None = None) -> Duel:
    if not len(first):
        return Duel()
    a, b = hits(held(first), came), hits(held(second), came)
    gain = losses(second, came) - losses(first, came)
    low, high = interval(gain, weeks)
    out = dict(games=len(first), first_right=int(a.sum()), second_right=int(b.sum()), only_first=int((a & ~b).sum()),
               only_second=int((b & ~a).sum()), edge=float(gain.mean()), low=low, high=high,
               sides=int(((first > 0.5) != (second > 0.5)).sum()))
    if first_margin is not None and second_margin is not None and actual is not None:
        known = ~np.isnan(actual)
        if known.any():
            nearer = np.abs(second_margin[known] - actual[known]) - np.abs(first_margin[known] - actual[known])
            out["closer"] = float(nearer.mean())
            out["closer_low"], out["closer_high"] = interval(nearer, weeks[known])
    return Duel(**out)


# ---- a walk-forward, marked -----------------------------------------------------------------------
def marks(result: Result, chances: dict[str, np.ndarray], names: list[str], keep: np.ndarray) -> dict[str, Score]:
    """Each recipe over the games in `keep`."""
    came = result.games["credited"].to_numpy(dtype=float)[keep]
    actual = result.games["actual"].to_numpy(dtype=float)[keep]
    return {name: score(chances[name][keep], came, result.margins[name][keep], actual) for name in names}


def against(result: Result, chances: dict[str, np.ndarray], name: str, other: str, keep: np.ndarray) -> Duel:
    games = result.games
    return duel(chances[name][keep], chances[other][keep], games["credited"].to_numpy(dtype=float)[keep],
                games["order"].to_numpy()[keep], result.margins[name][keep], result.margins[other][keep],
                games["actual"].to_numpy(dtype=float)[keep])


def by_group(result: Result, chances: dict[str, np.ndarray], names: list[str], keep: np.ndarray,
             group: str = "season") -> pd.DataFrame:
    """Each recipe's record in each season (or each week of the season), on the same games."""
    rows = []
    keys = result.games[group].to_numpy()
    for key in sorted(set(keys[keep].tolist())):
        inside = keep & (keys == key)
        found = marks(result, chances, names, inside)
        for name in names:
            s = found[name]
            rows.append({group: int(key), "recipe": name, "games": s.games, "right": s.right, "rate": s.rate,
                         "logloss": s.logloss, "brier": s.brier, "miss": s.miss})
    return pd.DataFrame(rows)


def changed_sides(result: Result, chances: dict[str, np.ndarray], name: str, other: str,
                  keep: np.ndarray) -> pd.DataFrame:
    """Every game `name` took a different side of from `other`, and how it came out."""
    games = result.games
    a, b = chances[name], chances[other]
    differ = keep & ((a > 0.5) != (b > 0.5))
    came = games["credited"].to_numpy(dtype=float)
    rows = []
    for i in np.flatnonzero(differ):
        row = games.iloc[i]
        took_home = a[i] > 0.5
        rows.append({
            "season": int(row["season"]), "week": int(row["week"]), "game": f"{row['away']} @ {row['home']}",
            "line": float(row["market"]),
            "pool line": "" if np.isnan(row["pool_line"]) else f"{row[f'{row.pool_favourite}']} by {row['pool_line']:g}",
            f"{other} margin": round(float(result.margins[other][i]), 2),
            f"{name} margin": round(float(result.margins[name][i]), 2),
            f"{name} took": row["home"] if took_home else row["away"],
            f"{name} chance": round(float(a[i] if took_home else 1 - a[i]), 3),
            "final margin (home)": None if np.isnan(row["actual"]) else float(row["actual"]),
            "credited": row["home"] if came[i] > 0.5 else row["away"],
            "helped": bool(took_home == (came[i] > 0.5)),
        })
    return pd.DataFrame(rows)


# ---- the Model Lab's own rule for a switch --------------------------------------------------------
@dataclass(frozen=True)
class Standing:
    """A challenger against the one in service, by the Model Lab's rule (modellab.Entry.verdict)."""

    games: int
    edge: float
    right: int
    service_right: int

    @property
    def enough(self) -> bool:
        return self.games >= modellab.ENOUGH_GAMES

    @property
    def clearly(self) -> bool:
        return self.edge >= modellab.CLEARLY_BETTER and self.right >= self.service_right

    @property
    def verdict(self) -> str:
        if not self.games:
            return "no games in common yet"
        if not self.enough:
            lean = "ahead" if self.edge > 0 else "behind" if self.edge < 0 else "level"
            return f"{lean}, {self.games} of {modellab.ENOUGH_GAMES} games"
        return "has earned the switch" if self.clearly else f"not better than {modellab.MODEL_NAME}"


def standing(found: Duel) -> Standing:
    return Standing(found.games, found.edge, found.first_right, found.second_right)
