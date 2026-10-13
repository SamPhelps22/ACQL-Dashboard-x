"""Model D: betting-market baseline.

American odds -> implied probability -> remove the bookmaker margin (de-vig).

De-vig methods
--------------
* ``multiplicative`` (default, a.k.a. proportional/basic normalisation):
  p_i = q_i / (q_home + q_away). Simple, widely used, and close to the other
  methods for two-way NFL markets with typical ~4.5% overround.
* ``additive``: subtract half the overround from each side.
* ``power``: find k with q_home^k + q_away^k = 1 (shifts more margin onto
  longshots, partially correcting favourite-longshot bias).

When only a spread is available, the home win probability is approximated by
a normal margin model: P(home win) = Phi(-home_spread / 13.45), sigma being the
long-run standard deviation of NFL results around the closing spread.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

SPREAD_SIGMA = 13.45


def american_to_implied(odds: float | None) -> float:
    """Implied probability (with vig) of American odds. NaN for invalid input.

    Valid American odds satisfy |odds| >= 100. +150 -> 0.4, -150 -> 0.6.
    """
    if odds is None:
        return math.nan
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return math.nan
    if math.isnan(o) or math.isinf(o) or abs(o) < 100:
        return math.nan
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def devig(q_home: float, q_away: float, method: str = "multiplicative") -> tuple[float, float]:
    """Return de-vigged (p_home, p_away) summing to 1, or (nan, nan) if invalid."""
    if any(math.isnan(x) for x in (q_home, q_away)) or q_home <= 0 or q_away <= 0:
        return math.nan, math.nan
    total = q_home + q_away
    if method == "multiplicative":
        return q_home / total, q_away / total
    if method == "additive":
        margin = (total - 1.0) / 2.0
        ph = min(max(q_home - margin, 1e-6), 1 - 1e-6)
        return ph, 1.0 - ph
    if method == "power":
        lo, hi = 0.01, 100.0
        for _ in range(200):
            k = (lo + hi) / 2
            s = q_home ** k + q_away ** k
            if s > 1:
                lo = k
            else:
                hi = k
        ph = q_home ** k
        return ph / (ph + q_away ** k), q_away ** k / (ph + q_away ** k)
    raise ValueError(f"Unknown de-vig method {method!r}")


def moneyline_home_probability(home_ml, away_ml, method: str = "multiplicative") -> float:
    return devig(american_to_implied(home_ml), american_to_implied(away_ml), method)[0]


def spread_home_probability(home_spread: float | None, sigma: float = SPREAD_SIGMA) -> float:
    if home_spread is None or (isinstance(home_spread, float) and math.isnan(home_spread)):
        return math.nan
    return 0.5 * (1.0 + math.erf((-float(home_spread) / sigma) / math.sqrt(2.0)))


def snapshot_home_probability(row: pd.Series | dict, method: str = "multiplicative") -> tuple[float, str]:
    """Probability from one odds snapshot; prefers moneylines, falls back to spread."""
    p = moneyline_home_probability(row.get("home_moneyline"), row.get("away_moneyline"), method)
    if not math.isnan(p):
        return p, "moneyline"
    p = spread_home_probability(row.get("home_spread"))
    return (p, "spread") if not math.isnan(p) else (math.nan, "missing")


def aggregate_providers(probs: Iterable[float]) -> float:
    """Average de-vigged probabilities across bookmakers, ignoring NaN."""
    arr = np.array([p for p in probs if p is not None and not math.isnan(p)], dtype=float)
    return float(arr.mean()) if arr.size else math.nan


def select_snapshots(odds: pd.DataFrame, cutoffs: pd.Series, closing_line_proxy: bool) -> pd.DataFrame:
    """Latest snapshot per (game, provider) observed at or before each game's cutoff.

    Snapshots with unknown capture time (nflverse closing lines) are only used
    when ``closing_line_proxy`` is True; they are then marked as such.
    ``cutoffs``: Series indexed by game_id.
    """
    if odds.empty:
        return odds.assign(odds_status=pd.Series(dtype=str))
    o = odds.copy()
    o["cutoff"] = o["game_id"].map(cutoffs)
    o = o[o["cutoff"].notna()]
    timed = o[o["captured_at"].notna() & (o["captured_at"] <= o["cutoff"])]
    timed = timed.sort_values("captured_at").groupby(["game_id", "provider"]).tail(1)
    timed = timed.assign(odds_status="timestamped")
    parts = [timed]
    if closing_line_proxy:
        closing = o[o["captured_at"].isna()]
        closing = closing[~closing["game_id"].isin(timed["game_id"])]
        parts.append(closing.assign(odds_status="closing_proxy"))
    return pd.concat(parts, ignore_index=True)


def market_probabilities(odds: pd.DataFrame, cutoffs: pd.Series, closing_line_proxy: bool = True,
                         method: str = "multiplicative", stale_hours: float = 24.0) -> pd.DataFrame:
    """Per-game market home probability, home spread, odds timestamp and status."""
    snaps = select_snapshots(odds, cutoffs, closing_line_proxy)
    cols = ["game_id", "market_home_prob", "market_home_spread", "odds_captured_at", "odds_status", "market_source"]
    if snaps.empty:
        return pd.DataFrame(columns=cols)
    res = snaps.apply(lambda r: snapshot_home_probability(r, method), axis=1, result_type="expand")
    snaps["p"], snaps["src"] = res[0], res[1]
    rows = []
    for gid, grp in snaps.groupby("game_id"):
        p = aggregate_providers(grp["p"])
        cap = grp["captured_at"].max()
        status = grp["odds_status"].iloc[-1]
        if status == "timestamped":
            age = (cutoffs[gid] - cap) / pd.Timedelta(hours=1)
            status = "stale" if age > stale_hours else "current"
        if math.isnan(p):
            status = "missing"
        rows.append({"game_id": gid, "market_home_prob": p,
                     "market_home_spread": grp["home_spread"].dropna().mean() if grp["home_spread"].notna().any() else np.nan,
                     "odds_captured_at": cap, "odds_status": status,
                     "market_source": ",".join(sorted(set(grp["src"])))})
    return pd.DataFrame(rows, columns=cols)
