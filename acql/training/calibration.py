"""Are Deadeye's chances honest? A shadow audit of the margin-to-chance step.

Prompted by the 2026-10-18 thread on ESPN's fantasy win chances, which went
wrong by mixing up standard deviation and variance: adding the players' SDs
where only variances add (about 3x too wide), and shrinking the SD in step
with the time left where it is the variance that shrinks. The audit of
Deadeye's own arithmetic is in CALIBRATION_AUDIT.md beside this file; this
module is the evidence from results.

Everything is priced from what was known before the games, walked forward:

    the margins     the market's line at one timing (midweek is the headline:
                    it is the nearest the archive has to the Thursday
                    deadline; the opening line and the archive's last update
                    are reported apart, the last update flagged as possibly
                    later than a Thursday card could see), and Deadeye's
                    margin from the picks' own code at the share in use
    the curves      the dashboard's own curve (analytics.margin_distribution),
                    as priced - Deadeye's game-by-game width included - and a
                    set of alternatives fixed in advance: the curve 10%
                    narrower or wider, and plain normal curves at chosen widths
    fitted ones     a normal width and a logistic recalibration, each fitted
                    as a season begins on the seasons before it - never on
                    the season it is marked on

The question is the straight-up winner (ties left out): the thread's question,
and the one every lined game's chance is built on. The last HELD_BACK seasons
are the final test; the "best alternative width" is chosen on the seasons
before them and only then marked on them.

Nothing here changes a pick, and the dashboard never imports it. It writes
only under data/training/calibration.

No Qt here.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np
import pandas as pd

from .. import analytics
from ..model import predictions
from . import data, features, recipes
from .data import Notes

#: The seasons at the end kept for the final test.
HELD_BACK = 3
#: Seasons only fitted from, never marked, at the start of each timing.
WARM_UP = 3
#: Times whole weeks are drawn again for a range.
DRAWS = 1000
SEED = 2026
#: Groups smaller than this get no calibration slope (too noisy to read).
MIN_SLOPE = 100
#: How finely P(home wins) is cut for the reliability table.
BINS = np.linspace(0.0, 1.0, 11)
#: Favourite strength, by the size of the market's line.
STRENGTHS = ((0.0, 3.0), (3.0, 7.0), (7.0, 10.0), (10.0, 99.0))
TIMINGS = ("midweek", "opening", "updated")

#: The curve's own margin SD (about 13.1 points: the narrow 8.7 bell and the
#: wide 19.7 one together) - measured, not assumed; see curve_sd.
#: If that spread were two independent team scores of equal SD, each would be
#: SD/sqrt(2). The thread's two errors then give: adding the SDs, SD*sqrt(2);
#: the reply's sqrt((a^2+b^2)/2), SD/sqrt(2). Both are scored as illustrations.
_NORMAL = NormalDist()


# ---- the arithmetic ---------------------------------------------------------------------------------
def margin_sd(home_sd: float, away_sd: float, correlation: float = 0.0) -> float:
    """SD of home points less away points. Variances add (less twice the
    covariance); SDs do not, and nothing is divided by two."""
    variance = home_sd ** 2 + away_sd ** 2 - 2 * correlation * home_sd * away_sd
    return math.sqrt(max(variance, 0.0))


def combined_sd(*sds: float) -> float:
    """SD of a sum of independent pieces: the root of the summed variances."""
    return math.sqrt(sum(s * s for s in sds))


def remaining_sd(sd: float, left: float) -> float:
    """SD still to come with a share `left` of the game unplayed, if scoring
    is independent over time: the variance shrinks in step, the SD by its root."""
    return sd * math.sqrt(min(1.0, max(0.0, left)))


def curve_sd(spread: float = 0.0, sd: float = analytics.SPREAD_SD) -> float:
    """The true SD of the dashboard's margin curve around `spread`."""
    found = analytics.margin_distribution(float(spread), sd)
    mean = sum(k * p for k, p in found)
    return math.sqrt(sum((k - mean) ** 2 * p for k, p in found))


def normal_home(margin, sd: float) -> np.ndarray:
    """P(home wins) when the final margin is normal around `margin`: Phi(mu / sd)."""
    margin = np.asarray(margin, dtype=float)
    return np.array([np.nan if np.isnan(m) else _NORMAL.cdf(m / sd) for m in margin])


def curve_home(margin: float, sd: float = analytics.SPREAD_SD) -> float:
    """P(home wins | somebody wins) off the dashboard's curve, the way the
    picks read it: cover_chance(margin, 1, sd) for each side, the tie's small
    share (about 0.4%) set aside so the two sides add to one. The picks' own
    pick chance counts a tie as a miss; the gap between the two is under 0.3 points."""
    sd = round(max(sd, 1.0), 1)                    # as analytics.predict_margin rounds it
    home = analytics.cover_chance(margin, 1, sd)
    away = analytics.cover_chance(-margin, 1, sd)
    return home / (home + away)


def curves_home(margin, sd=analytics.SPREAD_SD) -> np.ndarray:
    margin = np.asarray(margin, dtype=float)
    sds = np.broadcast_to(np.asarray(sd, dtype=float), margin.shape)
    return np.array([np.nan if np.isnan(m) else curve_home(float(m), float(s)) for m, s in zip(margin, sds)])


def scaled_curve_home(margin, factor: float) -> np.ndarray:
    """The dashboard's curve with both bells `factor` times as wide (the key
    numbers kept): the alternative to "8.7 is the right width"."""
    from .probability import distributions
    keys = np.array([analytics.KEY_WEIGHT.get(abs(d), 1.0) for d in analytics.MARGIN_RANGE])
    margin = np.asarray(margin, dtype=float)
    out = np.full(len(margin), np.nan)
    known = ~np.isnan(margin)
    levels, where = np.unique(np.round(margin[known], 1), return_inverse=True)
    table = distributions(levels, analytics.SPREAD_SD * factor, analytics.TAIL_RATIO, analytics.TAIL_SHARE, keys)
    margins = np.array(analytics.MARGIN_RANGE)
    home, away = table[:, margins >= 1].sum(axis=1), table[:, margins <= -1].sum(axis=1)
    out[known] = (home / (home + away))[where]
    return out


# ---- scoring ----------------------------------------------------------------------------------------
def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def logistic_fit(x: np.ndarray, y: np.ndarray, *, slope: bool = True) -> tuple[float, float]:
    """(intercept, slope) of y on x by maximum likelihood. With slope=False the
    slope is held at one and only the intercept is fitted."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    a, b = 0.0, 1.0
    for _ in range(100):
        p = _sigmoid(a + b * x)
        w = p * (1 - p) + 1e-12
        if slope:
            design = np.column_stack([np.ones(len(x)), x])
            step = np.linalg.solve((design * w[:, None]).T @ design + 1e-9 * np.eye(2), design.T @ (p - y))
            a, b = a - step[0], b - step[1]
            done = np.abs(step).max()
        else:
            step = float((p - y).sum() / w.sum())
            a -= step
            done = abs(step)
        if done < 1e-10:
            break
    return float(a), float(b)


def wilson(hits: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """The 95% Wilson range for a rate."""
    if n <= 0:
        return (float("nan"), float("nan"))
    rate = hits / n
    centre = (rate + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def block_draws(weeks: np.ndarray, draws: int = DRAWS, seed: int = SEED):
    """Index sets drawn by whole weeks (games in a week share their news)."""
    labels, where = np.unique(weeks, return_inverse=True)
    members = [np.flatnonzero(where == i) for i in range(len(labels))]
    rng = np.random.default_rng(seed)
    for _ in range(draws):
        picked = rng.integers(0, len(members), size=len(members))
        yield np.concatenate([members[i] for i in picked])


@dataclass
class Marks:
    games: int
    brier: float
    logloss: float
    accuracy: float
    intercept: float            # calibration-in-the-large: slope held at one (0 is right)
    slope: float                # calibration slope (1 is right; under 1, too sure)
    slope_low: float = float("nan")
    slope_high: float = float("nan")
    ece: float = 0.0            # average gap between said and came, over the ten bins


def mark(p: np.ndarray, y: np.ndarray, weeks: np.ndarray | None = None, ranges: bool = True) -> Marks:
    p = np.clip(np.asarray(p, dtype=float), 0.001, 0.999)
    y = np.asarray(y, dtype=float)
    n = len(p)
    if not n:
        return Marks(0, *(float("nan"),) * 5)
    x = _logit(p)
    brier = float(((p - y) ** 2).mean())
    logloss = float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
    accuracy = float(((p > 0.5) == (y > 0.5)).mean())
    # calibration-in-the-large: the forecast's log-odds as an offset, only the intercept fitted
    intercept = logistic_fit(x, y, slope=False)[0] if n >= 30 else float("nan")
    slope = logistic_fit(x, y)[1] if n >= MIN_SLOPE else float("nan")
    low = high = float("nan")
    if ranges and weeks is not None and n >= MIN_SLOPE:
        found = [logistic_fit(x[i], y[i])[1] for i in block_draws(weeks, draws=300)]
        low, high = (float(v) for v in np.percentile(found, [2.5, 97.5]))
    which = np.clip(np.digitize(p, BINS) - 1, 0, len(BINS) - 2)
    ece = sum(abs(p[which == b].mean() - y[which == b].mean()) * (which == b).sum()
              for b in range(len(BINS) - 1) if (which == b).any()) / n
    return Marks(n, brier, logloss, accuracy, intercept, slope, low, high, float(ece))


def paired(p: np.ndarray, q: np.ndarray, y: np.ndarray, weeks: np.ndarray) -> dict:
    """How much better `p` scores than `q` on the same games, a game, with a
    range from whole weeks drawn again. Plus is better for `p`."""
    p, q = np.clip(p, 0.001, 0.999), np.clip(q, 0.001, 0.999)
    ll = (-(y * np.log(q) + (1 - y) * np.log(1 - q))) - (-(y * np.log(p) + (1 - y) * np.log(1 - p)))
    br = (q - y) ** 2 - (p - y) ** 2
    out = {}
    for name, gain in (("logloss", ll), ("brier", br)):
        means = [float(gain[i].mean()) for i in block_draws(weeks)]
        low, high = np.percentile(means, [2.5, 97.5])
        out[name] = {"gain": float(gain.mean()), "low": float(low), "high": float(high)}
    return out


def reliability(p: np.ndarray, y: np.ndarray) -> list[dict]:
    which = np.clip(np.digitize(p, BINS) - 1, 0, len(BINS) - 2)
    out = []
    for b in range(len(BINS) - 1):
        inside = which == b
        n = int(inside.sum())
        hits = float(y[inside].sum())
        low, high = wilson(hits, n)
        out.append({"bin": f"{BINS[b]:.0%}-{BINS[b + 1]:.0%}", "games": n,
                    "said": float(p[inside].mean()) if n else None,
                    "came": hits / n if n else None, "low": low if n else None, "high": high if n else None})
    return out


# ---- the margins and the walk-forward fits -----------------------------------------------------------
def deadeye(prepared: pd.DataFrame, weight: float = predictions.CONSENSUS_WEIGHT) -> tuple[np.ndarray, np.ndarray]:
    """(Deadeye's home margin, its game's width) for each row, by the picks' own
    code: Forecast.expected for the margin, and pricing.price's
    hypot(SPREAD_SD, Forecast.extra_spread) for the width. The archive has no
    over/under, so the total's widening (pricing._total_factor) is 1 here."""
    margin = np.full(len(prepared), np.nan)
    sd = np.full(len(prepared), np.nan)
    for where, made, lean, typical in recipes._slates(prepared):
        for i, forecast in zip(where, made):
            margin[i] = forecast.expected(weight, lean, typical)
            sd[i] = math.hypot(analytics.SPREAD_SD, forecast.extra_spread(weight, typical))
    crowd = prepared["n_models"].to_numpy(dtype=float) >= features.ENOUGH_MODELS
    margin[~crowd] = np.nan
    return margin, sd


def best_normal(margin: np.ndarray, y: np.ndarray) -> float:
    """The normal width that made these results likeliest (grid, 0.1 points)."""
    grid = np.arange(8.0, 22.01, 0.1)
    best = min(grid, key=lambda s: -np.mean(y * np.log(np.clip(normal_home(margin, s), 1e-6, 1))
                                            + (1 - y) * np.log(np.clip(1 - normal_home(margin, s), 1e-6, 1))))
    return float(round(best, 1))


def season_fitted(season: np.ndarray, fit, apply) -> tuple[np.ndarray, dict]:
    """Walk seasons forward: as each begins, `fit(earlier rows)` and
    `apply(state, this season's rows)`. Rows of the first season have nothing
    before them and are left nan."""
    out = np.full(len(season), np.nan)
    states = {}
    for year in sorted(set(season.tolist())):
        before, now = season < year, season == year
        if not before.any():
            continue
        state = fit(before)
        states[int(year)] = state
        out[now] = apply(state, now)
    return out, states


@dataclass
class Timing:
    key: str
    title: str
    games: pd.DataFrame
    chances: dict[str, np.ndarray]
    about: dict[str, str]
    fits: dict[str, dict] = field(default_factory=dict)
    dev: list[int] = field(default_factory=list)
    final: list[int] = field(default_factory=list)
    chosen: str = ""

    @property
    def y(self) -> np.ndarray:
        return self.games["home_won"].to_numpy(dtype=float)

    @property
    def weeks(self) -> np.ndarray:
        return self.games["order"].to_numpy()

    def keep(self, seasons=None) -> np.ndarray:
        out = ~np.isnan(self.y)                    # a result, and not a tie
        for said in self.chances.values():
            out &= ~np.isnan(said)
        out &= np.isin(self.games["season"].to_numpy(), self.dev + self.final if seasons is None else list(seasons))
        return out


MARKET = "Market line, curve in use"
DEADEYE = "Deadeye, as priced"


def candidates(prepared: pd.DataFrame) -> tuple[dict[str, np.ndarray], dict[str, str], dict[str, dict], pd.DataFrame]:
    """Every candidate's P(home wins) for each game."""
    games = prepared.copy()
    market = games["market"].to_numpy(dtype=float)
    actual = games["actual"].to_numpy(dtype=float)
    games["home_won"] = np.where(actual > 0, 1.0, np.where(actual < 0, 0.0, np.nan))
    season = games["season"].to_numpy()
    y = games["home_won"].to_numpy(dtype=float)
    margin, width = deadeye(games)
    games["deadeye"], games["width"] = margin, width
    sd = curve_sd()
    out: dict[str, np.ndarray] = {}
    about: dict[str, str] = {}

    def add(name, values, what):
        out[name], about[name] = values, what

    add(MARKET, curves_home(market), "The market's line through the dashboard's curve: the bar to clear.")
    add(DEADEYE, curves_home(margin, width),
        "Deadeye's margin and its game-by-game width, through the curve - what the picks are priced with.")
    add("Deadeye, fixed width", curves_home(margin),
        "Deadeye's margin with every game at the usual width (what the training ground scores).")
    add("Market, curve 10% narrower", scaled_curve_home(market, 0.9), "Both bells 10% narrower, key numbers kept.")
    add("Market, curve 10% wider", scaled_curve_home(market, 1.1), "Both bells 10% wider, key numbers kept.")
    add(f"Market, normal SD {sd:.1f}", normal_home(market, sd),
        "A plain bell with the curve's own true SD - variances combined correctly.")
    add("Market, normal SD 11.0", normal_home(market, 11.0), "A plain bell near the width the curve's chances imply.")
    add(f"Market, normal SD {sd / math.sqrt(2):.1f} (ESPN /2 error)", normal_home(market, sd / math.sqrt(2)),
        "Illustration: the reply's sqrt((a^2+b^2)/2) - too narrow, so too sure.")
    add(f"Market, normal SD {sd * math.sqrt(2):.1f} (ESPN SD-sum error)", normal_home(market, sd * math.sqrt(2)),
        "Illustration: two team SDs added instead of their variances - too wide, so too timid.")

    eligible = ~np.isnan(y) & ~np.isnan(market)
    fits: dict[str, dict] = {}
    fitted, fits["normal"] = season_fitted(
        season,
        lambda before: best_normal(market[before & eligible], y[before & eligible]),
        lambda s, now: normal_home(market[now], s))
    add("Market, normal SD fitted on earlier seasons", fitted,
        "A plain bell, its width fitted as each season begins on the seasons before it.")

    def recalibrated(base: np.ndarray, label: str, what: str):
        usable = eligible & ~np.isnan(base)
        values, fits[label] = season_fitted(
            season,
            lambda before: logistic_fit(_logit(base[before & usable]), y[before & usable])
            if (before & usable).sum() >= 200 else (0.0, 1.0),
            lambda state, now: _sigmoid(state[0] + state[1] * _logit(base[now])))
        add(label, values, what)

    recalibrated(out[MARKET], "Market, recalibrated on earlier seasons",
                 "The market's chances stretched or squeezed by a logistic fit on the seasons before.")
    recalibrated(out[DEADEYE], "Deadeye, recalibrated on earlier seasons",
                 "Deadeye's chances stretched or squeezed by a logistic fit on the seasons before.")
    return out, about, fits, games


def timing(history: pd.DataFrame, key: str, notes: Notes) -> Timing | None:
    setting = features.SETTINGS[key]
    archived = history[history["source"] == "archive"] if "source" in history.columns else history
    prepared = features.prepare(archived, setting, notes)
    if prepared.empty:
        return None
    prepared = prepared.sort_values(["order", "game"], kind="stable").reset_index(drop=True)
    chances, about, fits, games = candidates(prepared)
    seasons = sorted(set(games["season"].tolist()))
    marked = seasons[WARM_UP:]
    if len(marked) < HELD_BACK + 2:
        notes.note("calibration", f"{setting.title}: too few seasons to hold any back")
        return None
    found = Timing(key, setting.title, games, chances, about, fits,
                   dev=marked[:-HELD_BACK], final=marked[-HELD_BACK:])
    # the alternative widths, chosen on the development seasons only
    widths = [n for n in chances if n.startswith("Market,") and "recalibrated" not in n and "fitted" not in n]
    keep = found.keep(found.dev)
    found.chosen = min(widths, key=lambda n: mark(chances[n][keep], found.y[keep], ranges=False).logloss)
    return found


# ---- the report -------------------------------------------------------------------------------------
def _f(value: float, digits: int = 4) -> str:
    return "-" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.{digits}f}"


def _table(found: Timing, keep: np.ndarray) -> list[str]:
    y, weeks = found.y[keep], found.weeks[keep]
    base = found.chances[MARKET][keep]
    lines = ["| Candidate | Games | Brier | Log loss | Accuracy | Cal. intercept | Cal. slope (95%) | ECE "
             "| Log loss vs market a game (95%) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    rows = {}
    for name, said in found.chances.items():
        p = said[keep]
        m = mark(p, y, weeks)
        vs = paired(p, base, y, weeks)["logloss"] if name != MARKET else None
        rows[name] = {"marks": m.__dict__, "vs_market": vs}
        lines.append(
            f"| {name}{' *' if name == found.chosen else ''} | {m.games:,} | {_f(m.brier)} | {_f(m.logloss)} "
            f"| {m.accuracy:.1%} | {_f(m.intercept, 3)} | {_f(m.slope, 2)} ({_f(m.slope_low, 2)} to "
            f"{_f(m.slope_high, 2)}) | {_f(m.ece, 3)} | "
            + ("bar" if vs is None else f"{vs['gain']:+.4f} ({vs['low']:+.4f} to {vs['high']:+.4f})") + " |")
    return lines, rows


def _reliability_lines(found: Timing, keep: np.ndarray, names) -> list[str]:
    y = found.y[keep]
    head = "| P(home wins) | " + " | ".join(f"{n}: games / said / came (95%)" for n in names) + " |"
    lines = [head, "|---|" + "---|" * len(names)]
    tables = [reliability(found.chances[n][keep], y) for n in names]
    for b in range(len(BINS) - 1):
        cells = []
        for t in tables:
            r = t[b]
            cells.append("-" if not r["games"] else
                         f"{r['games']} / {r['said']:.1%} / {r['came']:.1%} ({r['low']:.0%}-{r['high']:.0%})")
        lines.append(f"| {tables[0][b]['bin']} | " + " | ".join(cells) + " |")
    return lines


def _breakdowns(found: Timing, keep: np.ndarray) -> list[str]:
    y, weeks = found.y, found.weeks
    out = ["**By season** (log loss; plus = Deadeye better than the market)", "",
           "| Season | Games | Market | Deadeye | Deadeye gain (95%) | Deadeye slope |", "|---|---:|---:|---:|---:|---:|"]
    seasons = found.games["season"].to_numpy()
    for year in sorted(set(seasons[keep].tolist())):
        k = keep & (seasons == year)
        a, b = mark(found.chances[MARKET][k], y[k], ranges=False), mark(found.chances[DEADEYE][k], y[k], ranges=False)
        g = paired(found.chances[DEADEYE][k], found.chances[MARKET][k], y[k], weeks[k])["logloss"]
        out.append(f"| {year}{' (held out)' if year in found.final else ''} | {a.games} | {_f(a.logloss)} "
                   f"| {_f(b.logloss)} | {g['gain']:+.4f} ({g['low']:+.4f} to {g['high']:+.4f}) | {_f(b.slope, 2)} |")
    out += ["", "**By favourite strength** (size of the market's line)", "",
            "| Line | Games | Market said / came | Market slope | Deadeye said / came | Deadeye gain (95%) |",
            "|---|---:|---:|---:|---:|---:|"]
    size = np.abs(found.games["market"].to_numpy(dtype=float))
    for low, high in STRENGTHS:
        k = keep & (size >= low) & (size < high)
        if k.sum() < 30:
            continue
        fav_home = found.games["market"].to_numpy(dtype=float)[k] >= 0
        came = np.where(fav_home, y[k], 1 - y[k]).mean()
        said_m = np.where(fav_home, found.chances[MARKET][k], 1 - found.chances[MARKET][k]).mean()
        said_d = np.where(fav_home, found.chances[DEADEYE][k], 1 - found.chances[DEADEYE][k]).mean()
        m = mark(found.chances[MARKET][k], y[k], ranges=False)
        g = paired(found.chances[DEADEYE][k], found.chances[MARKET][k], y[k], weeks[k])["logloss"]
        label = f"{low:g} to {high:g}" if high < 99 else f"{low:g}+"
        out.append(f"| {label} | {int(k.sum())} | {said_m:.1%} / {came:.1%} | {_f(m.slope, 2)} "
                   f"| {said_d:.1%} / {came:.1%} | {g['gain']:+.4f} ({g['low']:+.4f} to {g['high']:+.4f}) |")
    return out


def diagram(found: Timing, keep: np.ndarray, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    y = found.y[keep]
    names = [MARKET, DEADEYE] + [n for n in found.chances if "ESPN" in n]
    colours = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"]
    fig, ax = plt.subplots(figsize=(6.4, 6.0), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.plot([0, 1], [0, 1], color="#8a8985", lw=1, ls="--", label="Perfectly calibrated")
    for name, colour in zip(names, colours):
        rows = [r for r in reliability(found.chances[name][keep], y) if r["games"] >= 15]
        said = [r["said"] for r in rows]
        came = [r["came"] for r in rows]
        ax.plot(said, came, color=colour, lw=2, marker="o", ms=6, mec="#fcfcfb", mew=1.5, label=name)
        if name == DEADEYE:
            ax.fill_between(said, [r["low"] for r in rows], [r["high"] for r in rows], color=colour, alpha=0.12, lw=0)
    ax.set_xlim(0, 1), ax.set_ylim(0, 1)
    ax.set_xlabel("Said: chance the home side wins", color="#52514e")
    ax.set_ylabel("Came in: share of home wins", color="#52514e")
    ax.set_title(f"{found.title}, seasons {min(found.dev + found.final)}-{max(found.final)}", color="#0b0b0b",
                 fontsize=11, loc="left")
    ax.grid(color="#e6e5e1", lw=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)




def _intro() -> list[str]:
    return ["# Deadeye probability calibration - shadow audit", "",
            "Straight-up winner, ties left out. Every chance is made from what was known before the games; fitted "
            "candidates are fitted on earlier seasons only. `*` marks the alternative width chosen on the "
            "development seasons (then marked, unchanged, on the held-out ones). Ranges: 95%, whole weeks drawn "
            f"again {DRAWS} times. Calibration slope under 1 means too sure, over 1 too timid; intercept 0 is right.",
            "", f"Curve in use: narrow bell {analytics.SPREAD_SD}, wide bell x{analytics.TAIL_RATIO} carrying "
            f"{analytics.TAIL_SHARE:.0%}; its true margin SD is {curve_sd():.2f} points. Deadeye share "
            f"{predictions.CONSENSUS_WEIGHT:.0%}.", ""]


def run_part(key: str) -> tuple[str, object]:
    """One timing's section of the report, kept as part-<key>.md (the
    three together take longer than one sitting of ten minutes)."""
    notes = Notes()
    history = data.check(data.history(notes=notes), notes)
    where = data.folder() / "calibration"
    where.mkdir(parents=True, exist_ok=True)
    found = timing(history, key, notes)
    text: list[str] = []
    kept: dict = {}
    if found is not None:
        flag = (" - the archive's last update can be later than the Thursday deadline: an upper bound, not a "
                "pre-deadline test" if key == "updated" else "")
        text += [f"## {found.title}{flag}", "",
                 f"Development seasons {found.dev[0]}-{found.dev[-1]}; held out {found.final[0]}-{found.final[-1]}. "
                 f"Seasons before {found.dev[0]} are only fitted from.", ""]
        kept = {"dev": found.dev, "final": found.final, "chosen": found.chosen,
                "fits": {k: {str(s): v for s, v in f.items()} for k, f in found.fits.items()},
                "about": found.about}
        for label, seasons in (("Development seasons", found.dev), ("Held-out seasons (final test)", found.final)):
            lines, rows = _table(found, found.keep(seasons))
            text += [f"### {label}", ""] + lines + [""]
            kept[label] = rows
        keep = found.keep()
        text += ["### Reliability, all marked seasons", ""] + _reliability_lines(found, keep, [MARKET, DEADEYE]) + [""]
        text += _breakdowns(found, keep) + [""]
        text += ["Normal width fitted as each season began: " + ", ".join(
            f"{s} {v:.1f}" for s, v in found.fits["normal"].items()), "",
                 "Deadeye recalibration (intercept, slope) as each season began: " + ", ".join(
            f"{s} ({a:+.3f}, {b:.2f})" for s, (a, b) in found.fits["Deadeye, recalibrated on earlier seasons"].items()),
                 ""]
        picture = where / f"reliability-{key}.png"
        diagram(found, keep, picture)
        text += [f"![reliability]({picture.name})", ""]
    else:
        text += [f"## {features.SETTINGS[key].title}", "", "Not run: " + "; ".join(
            i.detail for i in notes.items if i.code in ("calibration", "setting")) or "no games.", ""]
    path = where / f"part-{key}.md"
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    (where / f"results-{key}.json").write_text(json.dumps(kept, indent=1, default=float), encoding="utf-8")
    (where / "notes.md").write_text("\n".join(
        f"- {i.level} [{i.code}] {i.detail}" + (f" ({i.rows} rows)" if i.rows else "") for i in notes.items) + "\n",
        encoding="utf-8")
    return "\n".join(text), path


def join() -> tuple[str, object]:
    """The parts on disk, in TIMINGS order, as one report.md."""
    where = data.folder() / "calibration"
    text = _intro()
    about = {}
    for key in TIMINGS:
        part = where / f"part-{key}.md"
        if part.is_file():
            text.append(part.read_text(encoding="utf-8"))
        found = where / f"results-{key}.json"
        if found.is_file():
            about.update(json.loads(found.read_text(encoding="utf-8")).get("about") or {})
    text += ["## Candidates", ""] + [f"- **{n}** - {a}" for n, a in about.items()] + [""]
    notes = where / "notes.md"
    if notes.is_file():
        text += ["## Data notes (rows the archive check left out)", "", notes.read_text(encoding="utf-8")]
    path = where / "report.md"
    path.write_text("\n".join(text), encoding="utf-8")
    return "\n".join(text), path


def run(timings=TIMINGS) -> tuple[str, object]:
    """Every timing, one after another (about fifteen minutes), then the report."""
    for key in timings:
        run_part(key)
    return join()
