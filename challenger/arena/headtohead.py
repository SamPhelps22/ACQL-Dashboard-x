"""Head-to-head scoring on one matched set of games.

The forecasts arrive already captured, one frame per source; results are
joined here and nowhere earlier. A game is in the matched set only if every
compared model has a forecast for it and it was decided (ties are left out of
every probability score, and counted).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import metrics


def matched_set(forecasts: pd.DataFrame, games: pd.DataFrame, models: list[str], *,
                seasons=None, game_types=("REG",)) -> tuple[pd.DataFrame, dict]:
    """Wide table: one row per game with p_<model> for each model and the outcome."""
    g = games[games["game_type"].isin(game_types)]
    if seasons is not None:
        g = g[g["season"].isin(list(seasons))]
    wide = g[["game_id", "season", "week", "home", "away", "spread_line", "home_win", "home_score", "away_score"]].copy()
    coverage = {"scheduled_games": int(len(wide)), "completed": int(g["completed"].sum()),
                "ties": int((g["completed"] & g["home_win"].isna()).sum())}
    for m in models:
        f = forecasts[forecasts["model"] == m].drop_duplicates("game_id")[["game_id", "p_home"]]
        wide = wide.merge(f.rename(columns={"p_home": f"p_{m}"}), on="game_id", how="left")
        coverage[f"with_{m}"] = int(wide[f"p_{m}"].notna().sum())
    keep = wide["home_win"].notna()
    for m in models:
        keep &= wide[f"p_{m}"].notna()
    out = wide[keep].reset_index(drop=True)
    coverage["matched_decided_games"] = int(len(out))
    return out, coverage


def score_table(w: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    rows = []
    for m in models:
        s = metrics.summary(w[f"p_{m}"], w["home_win"])
        rows.append({"model": m, **s, "ece": metrics.ece(w[f"p_{m}"], w["home_win"])})
    return pd.DataFrame(rows).sort_values("log_loss").reset_index(drop=True)


def by_season(w: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    rows = []
    for season, part in w.groupby("season"):
        for m in models:
            rows.append({"season": season, "model": m, **metrics.summary(part[f"p_{m}"], part["home_win"])})
    return pd.DataFrame(rows)


def paired(w: pd.DataFrame, a: str, b: str, measure: str = "log_loss") -> dict:
    """Mean of (a - b) per game for a loss (negative = a better), week-clustered 95% CI."""
    f = metrics.log_loss_each if measure == "log_loss" else metrics.brier_each
    if measure == "accuracy":
        f = metrics.correct_each
    diff = f(w[f"p_{a}"], w["home_win"]) - f(w[f"p_{b}"], w["home_win"])
    ci = metrics.bootstrap_paired(diff, (w["season"].astype(str) + "-" + w["week"].astype(str)).to_numpy())
    ci["verdict"] = metrics.verdict(ci, better_when_negative=measure != "accuracy").replace("A", a).replace("B", b)
    return ci


def by_confidence(w: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Each model's record by how sure it was (its own favourite's chance)."""
    rows = []
    edges = [0.5, 0.6, 0.7, 0.8, 1.0001]
    for m in models:
        p = w[f"p_{m}"].to_numpy()
        conf = np.maximum(p, 1 - p)
        for lo, hi in zip(edges[:-1], edges[1:]):
            sel = (conf >= lo) & (conf < hi)
            if not sel.any():
                continue
            s = metrics.summary(p[sel], w["home_win"].to_numpy()[sel])
            rows.append({"model": m, "confidence": f"{lo:.1f}-{min(hi, 1):.1f}", **s,
                         "mean_confidence": float(conf[sel].mean())})
    return pd.DataFrame(rows)


def by_market_side(w: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Picks of the closing-market favourite vs the underdog, and how each fared."""
    rows = []
    has = w["spread_line"].notna() & (w["spread_line"] != 0)
    fav_home = w["spread_line"] > 0
    for m in models:
        pick_home = w[f"p_{m}"] > 0.5
        on_fav = has & (pick_home == fav_home)
        on_dog = has & (pick_home != fav_home)
        right = (pick_home == (w["home_win"] == 1))
        rows.append({"model": m, "picked_favourite": int(on_fav.sum()), "favourite_pick_accuracy": float(right[on_fav].mean()),
                     "picked_underdog": int(on_dog.sum()),
                     "underdog_pick_accuracy": float(right[on_dog].mean()) if on_dog.any() else float("nan")})
    return pd.DataFrame(rows)


def calibration(w: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    frames = []
    for m in models:
        t = metrics.calibration_table(w[f"p_{m}"], w["home_win"])
        t.insert(0, "model", m)
        frames.append(t)
    return pd.concat(frames, ignore_index=True)


def by_week(w: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    rows = []
    for (season, week), part in w.groupby(["season", "week"]):
        r = {"season": season, "week": week, "games": len(part)}
        for m in models:
            r[f"ll_{m}"] = float(metrics.log_loss_each(part[f"p_{m}"], part["home_win"]).mean())
        rows.append(r)
    return pd.DataFrame(rows)


def to_markdown(frame: pd.DataFrame, digits: int = 4) -> str:
    """A plain markdown table (no extra dependency)."""
    cols = list(frame.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in frame.itertuples(index=False):
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append("" if np.isnan(v) else f"{v:.{digits}f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
