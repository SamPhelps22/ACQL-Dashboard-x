"""From an expected margin to a chance of being credited - and whether a
curve fitted to results would do it better.

A better margin does not by itself make a better pick: the pool pays for
being credited with a game, and on a lined game that means the favourite
winning by the commissioner's number. So the step from "home by 4.2" to "58%
to be credited" is its own model, and it is tested on its own here.

The pool's rules, exactly as the dashboard grades them (results.credited):

    a lined game      the favourite is credited if it wins by at least the
                      line (a win by exactly a whole-number line counts);
                      otherwise the underdog is. There is always a winner.
    a straight game   whoever wins. A tie credits nobody, and is left out of
                      every score here, as the Model Lab leaves it out.

Four ways of making the step:

    In use            the dashboard's own curve (analytics.margin_distribution):
                      two bells and the key numbers, with constants set by hand
    Refitted          the same shape, its three widths and its key numbers
                      fitted to the results it is taught on
    Counted           no shape at all: among past games with a line near this
                      one, how often did the margin clear the bar
    Recalibrated      the curve in use, its chances stretched or squeezed by
                      whatever past results say they were off by

Each is taught only on seasons before the one it is marked on.

No Qt here.
"""

from __future__ import annotations

import math

import numpy as np

from .. import analytics

MARGINS = np.array(analytics.MARGIN_RANGE, dtype=float)
_LOW = analytics.MARGIN_RANGE[0]
#: Chances are held inside this before they are scored, as the Model Lab holds them.
FLOOR, CEILING = 0.01, 0.99
#: Results before a curve's key numbers are counted afresh rather than borrowed from the one in use.
KEY_GAMES = 2000
#: The widths tried when the curve is refitted. The ones in use are among them, so "no change" can win.
NARROWS = (7.5, 8.0, 8.4, 8.7, 9.0, 9.4, 9.8, 10.4)
RATIOS = (1.6, 1.9, 2.26, 2.6, 3.0)
SHARES = (0.10, 0.20, 0.34, 0.45, 0.60)
#: How near (points) a past game's line has to be to count toward a game's chance, when chances are counted.
NEAR = 1.5


# ---- the pool's rules ----------------------------------------------------------------------------
def credited_home(actual: np.ndarray, pool_line: np.ndarray, favourite: list[str]) -> np.ndarray:
    """1 where the home side was credited, 0 where the road side was, nan
    where nobody was (a tie on a straight game) or there is no result."""
    out = np.full(len(actual), np.nan)
    for i, (margin, line, side) in enumerate(zip(actual, pool_line, favourite)):
        if np.isnan(margin):
            continue
        if not np.isnan(line) and side in ("home", "away"):
            by = margin if side == "home" else -margin
            covered = by >= analytics.line_need(float(line))
            out[i] = 1.0 if covered == (side == "home") else 0.0
        elif margin != 0:
            out[i] = 1.0 if margin > 0 else 0.0
    return out


def _place(need: float) -> int:
    return math.ceil(need) - _LOW


def _pick(at_least: np.ndarray, need: float) -> float:
    place = _place(need)
    if place >= len(at_least):
        return 0.0
    return float(at_least[max(place, 0)])


def clears(curve: "Curve", margin: float, need: int) -> float:
    """Chance a side expected to win by `margin` wins by at least `need` - the
    way luck.favourite_covers reads it off the curve, either side of level."""
    if margin >= 0:
        return _pick(curve.at_least(margin), need)
    return 1 - _pick(curve.at_least(-margin), -need + 1)


def home_chance(curve: "Curve", margin: float, pool_line: float, favourite: str) -> float:
    """Chance the home side is credited, as luck.credited_chance has it."""
    if not np.isnan(pool_line) and favourite in ("home", "away"):
        by = margin if favourite == "home" else -margin
        covers = clears(curve, by, analytics.line_need(float(pool_line)))
        return covers if favourite == "home" else 1 - covers
    if margin >= 0:
        return _pick(curve.at_least(margin), 1)
    return 1 - _pick(curve.at_least(-margin), 1)


# ---- curves: the chance of each final margin, given the one expected ------------------------------
class Curve:
    """A spread of results around an expected margin."""

    name = ""
    about = ""

    def fit(self, market: np.ndarray, actual: np.ndarray) -> "Curve":
        return self

    def at_least(self, margin: float) -> np.ndarray:
        """For a side expected to win by `margin` (0 or more): its chance of
        winning by at least each margin in analytics.MARGIN_RANGE."""
        raise NotImplementedError

    def state(self) -> dict:
        return {}


def _tails(chances: np.ndarray) -> np.ndarray:
    return chances[::-1].cumsum()[::-1]


class InUse(Curve):
    name = "In use"
    about = "The dashboard's own curve, constants as they are."

    def __init__(self, sd: float = analytics.SPREAD_SD) -> None:
        self.sd, self._kept = sd, {}

    def at_least(self, margin: float) -> np.ndarray:
        key = round(float(margin), 1)
        if key not in self._kept:
            self._kept[key] = _tails(np.array([p for _, p in analytics.margin_distribution(key, self.sd)]))
        return self._kept[key]


def key_weights(frequency: dict[int, float]) -> np.ndarray:
    """Each margin's weight for being a key number, from how often each
    margin has turned up - analytics._key_weights, for any count of results."""
    reach = 15
    kernel = np.array([math.exp(-(k / analytics.KEY_SMOOTHING) ** 2 / 2) for k in range(-reach, reach + 1)])
    kernel /= kernel.sum()
    top = max(frequency)

    def signed(d: int) -> float:
        f = frequency.get(abs(d), 0.0)
        return f if d == 0 else f / 2

    weights = {}
    for d in range(0, top + 1):
        smooth = sum(k * signed(d + off) for off, k in zip(range(-reach, reach + 1), kernel))
        here = signed(d)
        weights[d] = here / smooth if here > 0 and smooth > 0 else analytics.KEY_FLOOR
    return np.array([weights.get(abs(int(d)), 1.0) for d in analytics.MARGIN_RANGE])


def _shapes(centres: np.ndarray, narrow: float, ratio: float, share: float, keys: np.ndarray) -> np.ndarray:
    """analytics._shape for many centres at once: one row of chances each."""
    off = MARGINS[None, :] - centres[:, None]
    wide = narrow * ratio
    bell = ((1 - share) * np.exp(-(off / narrow) ** 2 / 2) / narrow
            + share * np.exp(-(off / wide) ** 2 / 2) / wide)
    weighted = bell * keys[None, :]
    return weighted / weighted.sum(axis=1, keepdims=True)


def distributions(margins: np.ndarray, narrow: float, ratio: float, share: float, keys: np.ndarray) -> np.ndarray:
    """The chance of each final margin for each expected one, the centre
    moved until the average comes out at the margin expected (as
    analytics.margin_distribution moves it)."""
    margins = np.asarray(margins, dtype=float)
    low, high = margins - 8, margins + 8
    for _ in range(40):
        mid = (low + high) / 2
        short = _shapes(mid, narrow, ratio, share, keys) @ MARGINS < margins
        low, high = np.where(short, mid, low), np.where(short, high, mid)
    return _shapes((low + high) / 2, narrow, ratio, share, keys)


class Refitted(Curve):
    name = "Refitted"
    about = ("The same two bells and key numbers, with the widths and the key numbers fitted to the results it is "
             "taught on.")

    def __init__(self) -> None:
        self.narrow, self.ratio, self.share = analytics.SPREAD_SD, analytics.TAIL_RATIO, analytics.TAIL_SHARE
        self.keys = np.array([analytics.KEY_WEIGHT.get(abs(d), 1.0) for d in analytics.MARGIN_RANGE])
        self.games, self.own_keys, self._kept = 0, False, {}

    def fit(self, market: np.ndarray, actual: np.ndarray) -> "Refitted":
        """The widths that make the results taught on likeliest. Every game
        is read from its favourite's side, so home and road are not told apart."""
        keep = ~(np.isnan(market) | np.isnan(actual))
        market, actual = np.asarray(market, dtype=float)[keep], np.asarray(actual, dtype=float)[keep]
        self.games, self._kept = len(market), {}
        if not self.games:
            return self
        side = np.where(market < 0, -1.0, 1.0)
        expected, came = np.round(market * side * 2) / 2, np.clip(actual * side, MARGINS[0], MARGINS[-1])
        self.own_keys = self.games >= KEY_GAMES
        if self.own_keys:
            counts = np.bincount(np.abs(actual).astype(int), minlength=61)[:61]
            self.keys = key_weights({d: 100.0 * c / self.games for d, c in enumerate(counts) if c})
        levels, where = np.unique(expected, return_inverse=True)
        column = (came - MARGINS[0]).astype(int)
        best = None
        for narrow in NARROWS:
            for ratio in RATIOS:
                for share in SHARES:
                    table = distributions(levels, narrow, ratio, share, self.keys)
                    loss = -float(np.log(np.maximum(table[where, column], 1e-12)).mean())
                    if best is None or loss < best[0]:
                        best = (loss, narrow, ratio, share)
        _, self.narrow, self.ratio, self.share = best
        return self

    def at_least(self, margin: float) -> np.ndarray:
        key = round(float(margin), 1)
        if key not in self._kept:
            self._kept[key] = _tails(distributions(np.array([key]), self.narrow, self.ratio, self.share, self.keys)[0])
        return self._kept[key]

    def state(self) -> dict:
        return {"narrow": self.narrow, "ratio": self.ratio, "share": self.share, "games": self.games,
                "own key numbers": self.own_keys}


class Counted(Curve):
    name = "Counted"
    about = (f"No shape: among the games taught on whose line was within about {NEAR:g} points of this one, how "
             "often the favourite won by each margin.")

    def __init__(self, near: float = NEAR) -> None:
        self.near, self.lines, self.came, self._kept = near, np.empty(0), np.empty(0, dtype=int), {}

    def fit(self, market: np.ndarray, actual: np.ndarray) -> "Counted":
        keep = ~(np.isnan(market) | np.isnan(actual))
        market, actual = np.asarray(market, dtype=float)[keep], np.asarray(actual, dtype=float)[keep]
        # each game counts from both sides: a home side favoured by 3 and a road side favoured by 3 are one case
        self.lines = np.concatenate([market, -market])
        self.came = (np.clip(np.concatenate([actual, -actual]), MARGINS[0], MARGINS[-1]) - MARGINS[0]).astype(int)
        self._kept = {}
        return self

    def at_least(self, margin: float) -> np.ndarray:
        key = round(float(margin), 1)
        if key not in self._kept:
            if not len(self.lines):
                self._kept[key] = InUse().at_least(key)
            else:
                weight = np.exp(-((self.lines - key) / self.near) ** 2 / 2)
                counts = np.bincount(self.came, weights=weight, minlength=len(MARGINS))
                self._kept[key] = _tails(counts / counts.sum())
        return self._kept[key]

    def state(self) -> dict:
        return {"near": self.near, "games": len(self.lines) // 2}


# ---- layers: a whole step from margins to chances -------------------------------------------------
class Layer:
    """Everything between an expected margin and a chance of being credited."""

    def __init__(self, curve: Curve, recalibrate: bool = False) -> None:
        self.curve, self.recalibrate = curve, recalibrate
        self.name = "Recalibrated" if recalibrate else curve.name
        self.about = ("The curve in use, its chances stretched or squeezed by what past results say they were off by."
                      if recalibrate else curve.about)
        self.shift, self.stretch = 0.0, 1.0

    def fit(self, market: np.ndarray, actual: np.ndarray, pool_line: np.ndarray, favourite: list[str]) -> "Layer":
        self.curve.fit(market, actual)
        if self.recalibrate:
            said = self._raw(market, pool_line, favourite)
            came = credited_home(actual, pool_line, favourite)
            keep = ~np.isnan(came) & ~np.isnan(said)
            self.shift, self.stretch = _logistic(_logit(said[keep]), came[keep])
        return self

    def _raw(self, margin: np.ndarray, pool_line: np.ndarray, favourite: list[str]) -> np.ndarray:
        return np.array([np.nan if np.isnan(m) else home_chance(self.curve, float(m), float(line), side)
                         for m, line, side in zip(margin, pool_line, favourite)])

    def chance(self, margin: np.ndarray, pool_line: np.ndarray, favourite: list[str]) -> np.ndarray:
        """The home side's chance of being credited with each game."""
        raw = self._raw(np.asarray(margin, dtype=float), np.asarray(pool_line, dtype=float), list(favourite))
        if not self.recalibrate:
            return raw
        return 1 / (1 + np.exp(-(self.shift + self.stretch * _logit(raw))))

    def state(self) -> dict:
        return {**self.curve.state(), **({"shift": self.shift, "stretch": self.stretch} if self.recalibrate else {})}


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _logistic(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(shift, stretch) that best turn log-odds said into what came in. With
    too little to go on, the chances are left as they were."""
    if len(x) < 200 or x.std() < 1e-6:
        return 0.0, 1.0
    design = np.column_stack([np.ones(len(x)), x])
    weights = np.array([0.0, 1.0])
    for _ in range(50):
        said = 1 / (1 + np.exp(-design @ weights))
        hessian = (design * (said * (1 - said))[:, None]).T @ design + 1e-9 * np.eye(2)
        step = np.linalg.solve(hessian, design.T @ (said - y))
        weights -= step
        if np.abs(step).max() < 1e-9:
            break
    return float(weights[0]), float(weights[1])


def layers() -> list[Layer]:
    """Every way of making the step, the one in use first."""
    return [Layer(InUse()), Layer(Refitted()), Layer(Counted()), Layer(InUse(), recalibrate=True)]


# ---- the Big Loser chance, taught on the seasons before -------------------------------------------
def rout_terms(margin: np.ndarray) -> np.ndarray:
    """analytics._rout_terms for many teams at once: one row each."""
    tens = np.asarray(margin, dtype=float) / 10
    return np.column_stack([np.ones(len(tens)), tens] + [np.maximum(0.0, tens - bend / 10) for bend in analytics.ROUT_BENDS])


def rout_chances(margin: np.ndarray, weights=analytics.ROUT_WEIGHTS) -> np.ndarray:
    """Each team's chance of losing by 15 or more, from its own expected margin."""
    return 1 / (1 + np.exp(-rout_terms(margin) @ np.asarray(weights, dtype=float)))
