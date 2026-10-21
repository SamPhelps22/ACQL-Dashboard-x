"""Scores, reliability, and paired comparisons with week-level bootstrap intervals.

Ties (home_win = 0.5) are left out of every probability score and counted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config

BANDS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
DRAWS = 2000


def log_loss(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier(p, y):
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def summary(df: pd.DataFrame, p_col: str = "p") -> dict:
    d = df[df["home_win"].isin([0.0, 1.0])]
    p, y = d[p_col].astype(float).values, d["home_win"].values
    out = {"n": len(d), "log_loss": float(log_loss(p, y).mean()), "brier": float(brier(p, y).mean()),
           "accuracy": float(np.mean((p > 0.5) == (y == 1))), "ece": ece(p, y)}
    if "exp_margin" in d and d["exp_margin"].notna().any():
        e = d["exp_margin"].astype(float) - d["margin"]
        out["margin_mae"] = float(np.nanmean(np.abs(e)))
        out["margin_rmse"] = float(np.sqrt(np.nanmean(e ** 2)))
    if "exp_total" in d and d["exp_total"].notna().any():
        e = d["exp_total"].astype(float) - d["total_points"]
        out["total_mae"] = float(np.nanmean(np.abs(e)))
    return out


def ece(p, y, bands=BANDS) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    idx = np.clip(np.digitize(p, bands) - 1, 0, len(bands) - 2)
    tot = 0.0
    for b in range(len(bands) - 1):
        m = idx == b
        if m.any():
            tot += m.sum() * abs(p[m].mean() - y[m].mean())
    return float(tot / max(len(p), 1))


def reliability(p, y, bands=BANDS) -> pd.DataFrame:
    p, y = np.asarray(p, float), np.asarray(y, float)
    idx = np.clip(np.digitize(p, bands) - 1, 0, len(bands) - 2)
    rows = []
    for b in range(len(bands) - 1):
        m = idx == b
        if m.any():
            rows.append({"band": f"{bands[b]:.1f}-{bands[b+1]:.1f}", "n": int(m.sum()), "said": p[m].mean(),
                         "came": y[m].mean()})
    return pd.DataFrame(rows)


def block_bootstrap(values: np.ndarray, blocks: np.ndarray, draws: int = DRAWS, seed: int = config.SEED):
    """Mean and 95% interval, resampling whole blocks (weeks) with replacement."""
    values = np.asarray(values, float)
    keys, inv = np.unique(blocks, return_inverse=True)
    sums = np.bincount(inv, weights=values)
    counts = np.bincount(inv)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(keys), size=(draws, len(keys)))
    means = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return float(values.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), means


def paired(df: pd.DataFrame, a: str, b: str, metric=log_loss) -> dict:
    """a minus b, on games both priced (negative = a better), with a week-block 95% interval."""
    d = df[df["home_win"].isin([0.0, 1.0])].dropna(subset=[a, b])
    diff = metric(d[a], d["home_win"]) - metric(d[b], d["home_win"])
    blocks = d["season"].astype(str) + "-" + d["week"].astype(str)
    mean, lo, hi, draws = block_bootstrap(diff, blocks.values)
    return {"a": a, "b": b, "n": len(d), "weeks": blocks.nunique(), "diff": mean, "lo": lo, "hi": hi,
            "p_a_better": float(np.mean(draws < 0))}


def wide(forecasts: pd.DataFrame, results: pd.DataFrame, use_cal: bool = False) -> pd.DataFrame:
    """One row a game, a column of probabilities per model."""
    col = "p_home_cal" if use_cal else "p_home_raw"
    w = forecasts.pivot_table(index="game_id", columns="model", values=col, aggfunc="first")
    return results.merge(w, left_on="game_id", right_index=True, how="inner")
