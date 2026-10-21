"""Scoring rules and uncertainty for probability forecasts.

Log loss and Brier score are the primary measures (both proper scoring
rules); straight-up accuracy is secondary. A forecast of exactly 0.5 earns
half a correct pick. Paired differences are bootstrapped by week (all games
of a week resampled together), since games in one week share news and noise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-6


def log_loss_each(p, y) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier_each(p, y) -> np.ndarray:
    return (np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2


def correct_each(p, y) -> np.ndarray:
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    return np.where(p == 0.5, 0.5, ((p > 0.5) == (y == 1)).astype(float))


def summary(p, y) -> dict:
    return {"games": int(len(y)), "log_loss": float(np.mean(log_loss_each(p, y))),
            "brier": float(np.mean(brier_each(p, y))), "accuracy": float(np.mean(correct_each(p, y)))}


def calibration_table(p, y, edges=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0)) -> pd.DataFrame:
    """Forecast vs observed home-win rate by probability bucket."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    bucket = np.clip(np.digitize(p, edges[1:-1]), 0, len(edges) - 2)
    rows = []
    for b in range(len(edges) - 1):
        m = bucket == b
        if not m.any():
            continue
        n = int(m.sum())
        obs = float(y[m].mean())
        se = np.sqrt(max(obs * (1 - obs), 1e-9) / n)
        rows.append({"bucket": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "games": n, "forecast": float(p[m].mean()),
                     "observed": obs, "gap": obs - float(p[m].mean()), "se": float(se)})
    return pd.DataFrame(rows)


def ece(p, y, bins: int = 10) -> float:
    t = calibration_table(p, y, tuple(np.linspace(0, 1, bins + 1)))
    return float((t["games"] * t["gap"].abs()).sum() / t["games"].sum()) if len(t) else float("nan")


def bootstrap_paired(diff: np.ndarray, clusters: np.ndarray, n: int = 4000, seed: int = 11) -> dict:
    """Mean paired difference with a 95% cluster-bootstrap interval (clusters = weeks)."""
    diff = np.asarray(diff, dtype=float)
    keys, inverse = np.unique(clusters, return_inverse=True)
    sums = np.bincount(inverse, weights=diff, minlength=len(keys))
    counts = np.bincount(inverse, minlength=len(keys)).astype(float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(keys), size=(n, len(keys)))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    mean = float(diff.mean())
    return {"mean": mean, "lo": float(lo), "hi": float(hi), "clusters": int(len(keys)), "games": int(len(diff)),
            "p_two_sided": float(min(1.0, 2 * min((means <= 0).mean(), (means >= 0).mean())))}


def verdict(ci: dict, better_when_negative: bool = True) -> str:
    """Plain words for an interval on (model A - model B)."""
    lo, hi = ci["lo"], ci["hi"]
    if lo > 0:
        return "B better (CI excludes 0)" if better_when_negative else "A better (CI excludes 0)"
    if hi < 0:
        return "A better (CI excludes 0)" if better_when_negative else "B better (CI excludes 0)"
    return "no clear difference (CI includes 0)"
