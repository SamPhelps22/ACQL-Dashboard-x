"""Scoring rules and uncertainty. Probability quality first (log loss, then
Brier and calibration); accuracy and margin error are reported, not chased."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models import clip


def per_game_logloss(p, y):
    p = clip(p)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def per_game_brier(p, y):
    return (np.asarray(p, float) - y) ** 2


def calibration(p, y, bins=10) -> dict:
    """Expected calibration error and the logistic recalibration slope."""
    p, y = clip(p), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece, table = 0.0, []
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
            table.append({"bucket": f"{edges[b]:.1f}-{edges[b+1]:.1f}", "n": int(m.sum()),
                          "forecast": round(float(p[m].mean()), 4), "observed": round(float(y[m].mean()), 4)})
    from .models import fit_logistic
    z = np.log(p / (1 - p))[:, None]
    slope = float(fit_logistic(z, y, 0.0)[1]) if len(y) > 30 and 0 < y.mean() < 1 else float("nan")
    return {"ece": float(ece), "slope": slope, "table": table}


def summary(df: pd.DataFrame, col="p_home") -> dict:
    d = df[df["home_win"].isin([0.0, 1.0]) & df[col].notna()]
    if d.empty:
        return {"games": 0}
    p, y = d[col].to_numpy(float), d["home_win"].to_numpy(float)
    out = {"games": int(len(d)), "weeks": int(d["week_key"].nunique()),
           "log_loss": float(per_game_logloss(p, y).mean()), "brier": float(per_game_brier(p, y).mean()),
           "accuracy": float(((p > 0.5) == (y == 1)).mean())}
    cal = calibration(p, y)
    out.update({"ece": cal["ece"], "cal_slope": cal["slope"]})
    mcol = col.replace("p_home", "exp_margin")
    if mcol in d and d[mcol].notna().any():
        e = (d[mcol] - d["margin"]).dropna()
        out.update({"margin_mae": float(e.abs().mean()), "margin_rmse": float(np.sqrt((e ** 2).mean()))})
    return out


def paired_week_bootstrap(diff: pd.Series, weeks: pd.Series, n: int = 2000, level=0.95, seed=0) -> dict:
    """Mean per-game difference with a CI from resampling whole weeks (games in
    a week share conditions, so resampling games would overstate certainty)."""
    frame = pd.DataFrame({"d": diff.to_numpy(float), "w": weeks.astype(str).to_numpy()})
    agg = frame.groupby("w")["d"].agg(["sum", "count"])
    sums, counts = agg["sum"].to_numpy(), agg["count"].to_numpy()
    if len(sums) < 2:
        return {"mean": float(frame["d"].mean()) if len(frame) else float("nan"), "lo": float("nan"),
                "hi": float("nan"), "weeks": int(len(sums))}
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(sums), size=(n, len(sums)))
    means = sums[draws].sum(1) / counts[draws].sum(1)
    a = (1 - level) / 2
    return {"mean": float(sums.sum() / counts.sum()), "lo": float(np.quantile(means, a)),
            "hi": float(np.quantile(means, 1 - a)), "weeks": int(len(sums))}
