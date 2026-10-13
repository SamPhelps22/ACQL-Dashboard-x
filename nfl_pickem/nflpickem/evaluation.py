"""Probability and confidence-pool evaluation metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .confidence import ScoringRules, allocate, grade_sheet
from .features import POSTSEASON
from .models.ml import clip

MODEL_LABELS = {
    "market": "Market only",
    "elo": "Elo only",
    "logistic": "Logistic regression only",
    "gbm": "Gradient boosting only",
    "ml_only": "ML ensemble (no market)",
    "blend": "Market + ML ensemble",
}


def prob_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    """Accuracy, log loss, Brier on decided games (ties excluded). p=0.5 counts as a home pick."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    mask = np.isin(y, [0.0, 1.0]) & ~np.isnan(p)
    y, p = y[mask], clip(p[mask])
    if len(y) == 0:
        return {"games": 0, "accuracy": np.nan, "log_loss": np.nan, "brier": np.nan}
    pred = (p >= 0.5).astype(float)
    return {
        "games": int(len(y)),
        "accuracy": float((pred == y).mean()),
        "log_loss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()),
        "brier": float(((p - y) ** 2).mean()),
    }


def model_comparison(preds: pd.DataFrame, models: list[str], by: str | None = None) -> pd.DataFrame:
    rows = []
    groups = [(None, preds)] if by is None else preds.groupby(by)
    for key, g in groups:
        for m in models:
            if m not in g:
                continue
            r = prob_metrics(g["home_result"].to_numpy(), g[m].to_numpy())
            r["model"] = m
            r["coverage"] = float(g[m].notna().mean())
            if by is not None:
                r[by] = key
            rows.append(r)
    return pd.DataFrame(rows)


def calibration_table(preds: pd.DataFrame, model: str, bins: int = 10) -> pd.DataFrame:
    d = preds[preds["home_result"].isin([0.0, 1.0]) & preds[model].notna()]
    edges = np.linspace(0, 1, bins + 1)
    d = d.assign(bucket=pd.cut(d[model], edges, include_lowest=True))
    t = d.groupby("bucket", observed=True).agg(predicted=(model, "mean"), observed=("home_result", "mean"),
                                               games=("home_result", "size")).reset_index()
    t["bucket"] = t["bucket"].astype(str)
    t["model"] = model
    return t


def pick_buckets(preds: pd.DataFrame, model: str) -> pd.DataFrame:
    """Accuracy by the selected team's probability (favourite strength)."""
    d = preds[preds["home_result"].isin([0.0, 1.0]) & preds[model].notna()].copy()
    p = d[model]
    d["pick_prob"] = np.where(p >= 0.5, p, 1 - p)
    d["correct"] = ((p >= 0.5) == (d["home_result"] == 1)).astype(float)
    d["range"] = pd.cut(d["pick_prob"], [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9, 1.0], include_lowest=True)
    t = d.groupby("range", observed=True).agg(games=("correct", "size"), mean_prob=("pick_prob", "mean"),
                                              accuracy=("correct", "mean")).reset_index()
    t["range"] = t["range"].astype(str)
    t["model"] = model
    return t


def favorite_underdog(preds: pd.DataFrame, model: str) -> pd.DataFrame:
    """Accuracy split by whether the model's pick was the market favourite."""
    d = preds[preds["home_result"].isin([0.0, 1.0]) & preds[model].notna() & preds["market"].notna()].copy()
    pick_home = d[model] >= 0.5
    d["pick_is_market_favorite"] = pick_home == (d["market"] >= 0.5)
    d["correct"] = (pick_home == (d["home_result"] == 1)).astype(float)
    t = d.groupby("pick_is_market_favorite").agg(games=("correct", "size"), accuracy=("correct", "mean")).reset_index()
    t["model"] = model
    return t


def simulate_pool(preds: pd.DataFrame, model: str, rules: ScoringRules) -> pd.DataFrame:
    """Weekly confidence-pool score using the model's probabilities, allocated
    exactly as it would have been on the slate (all eligible games of the week)."""
    d = preds.copy()
    if not rules.include_postseason:
        d = d[~d["game_type"].isin(POSTSEASON)]
    rows = []
    for (season, week), wk in d.groupby(["season", "week"], sort=True):
        slate = wk.rename(columns={model: "_p"})[["game_id", "home_team", "away_team", "kickoff_utc", "_p",
                                                  "home_score", "away_score", "game_status"]]
        alloc = allocate(slate, rules, prob_col="_p")
        g = grade_sheet(alloc, wk[["game_id", "home_score", "away_score", "game_status"]], rules)
        rows.append({"season": season, "week": week, "model": model, "games": len(g),
                     "points": g["points_earned"].sum(), "max_points": g["confidence_points"].sum(),
                     "expected_points": g["expected_points"].sum(),
                     "correct": int((g["actual_result"] == "win").sum()),
                     "missing_probs": int(wk[model].isna().sum())})
    return pd.DataFrame(rows)


def pool_summary(weekly: pd.DataFrame) -> pd.DataFrame:
    s = weekly.groupby("model").agg(weeks=("points", "size"), total_points=("points", "sum"),
                                    avg_weekly=("points", "mean"), sd_weekly=("points", "std"),
                                    min_week=("points", "min"), max_week=("points", "max"),
                                    avg_expected=("expected_points", "mean"),
                                    pct_of_max=("points", "sum")).reset_index()
    s["pct_of_max"] = s["total_points"] / weekly.groupby("model")["max_points"].sum().reindex(s["model"]).to_numpy()
    # how often each model had the best (or tied best) week among compared models
    best = weekly.pivot_table(index=["season", "week"], columns="model", values="points")
    top = best.eq(best.max(axis=1), axis=0)
    s["weeks_best_or_tied"] = s["model"].map(top.mean())
    return s.sort_values("avg_weekly", ascending=False)


def paired_week_difference(weekly: pd.DataFrame, a: str, b: str) -> dict[str, float]:
    """Mean weekly point difference a - b with a normal-approximation 95% CI."""
    pv = weekly.pivot_table(index=["season", "week"], columns="model", values="points").dropna(subset=[a, b])
    diff = pv[a] - pv[b]
    n = len(diff)
    se = diff.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    return {"a": a, "b": b, "weeks": n, "mean_diff": float(diff.mean()),
            "ci_low": float(diff.mean() - 1.96 * se), "ci_high": float(diff.mean() + 1.96 * se)}
