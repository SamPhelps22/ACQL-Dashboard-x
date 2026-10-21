"""Model G - combining components, trained only on their earlier out-of-fold forecasts.

Every component forecast in the walk-forward was made by a model fitted on
games before it, so each is out-of-fold. For target season s the ensemble
sees component forecasts and outcomes from seasons < s only:

  1. selection   forward selection on the training seasons: start from the
                 component with the best validation score, add another only
                 if it lowers validation log loss by MIN_GAIN. Validation is
                 itself walk-forward inside the training seasons (fit on
                 seasons < v, score v, for the last VAL_SEASONS seasons).
  2. combiners   equal-weight average of logits; a weighted average of logits
                 (weights >= 0, summing to 1, pulled toward equal); logistic
                 stacking (intercept + L2-penalised slopes).
  3. calibration equal and weighted averages are Platt-scaled on the training
                 seasons' (out-of-fold) combined forecasts; stacking is its own.

Two families: market-free (week-start components only) and market-informed
(adds closing-market and other retrospective components; labelled so).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from ..models.base import expit, logistic, logit

MIN_GAIN = 0.0005
VAL_SEASONS = 3
MIN_TRAIN_SEASONS = 3
STACK_LAMBDA = 2.0
METHODS = ("equal", "weighted", "stack")


def _ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def simplex_weights(Z: np.ndarray, y: np.ndarray, pull: float = 0.5, iters: int = 300) -> np.ndarray:
    """Non-negative weights summing to 1 on logits, by exponentiated gradient, pulled toward equal."""
    k = Z.shape[1]
    w = np.ones(k) / k
    eq = w.copy()
    for _ in range(iters):
        p = expit(Z @ w)
        g = Z.T @ (p - y) / len(y) + pull * (w - eq) / len(y) * 100
        w = w * np.exp(-0.5 * g)
        w = w / w.sum()
    return w


def fit(method: str, Z: np.ndarray, y: np.ndarray) -> dict:
    if method == "equal":
        w = np.ones(Z.shape[1]) / Z.shape[1]
    elif method == "weighted":
        w = simplex_weights(Z, y)
    else:
        X = np.column_stack([np.ones(len(Z)), Z])
        return {"stack": logistic(X, y, lam=STACK_LAMBDA)}
    comb = Z @ w
    X = np.column_stack([np.ones(len(Z)), comb])
    return {"w": w, "platt": logistic(X, y, lam=1.0)}


def apply(model: dict, Z: np.ndarray) -> np.ndarray:
    if "stack" in model:
        return expit(np.column_stack([np.ones(len(Z)), Z]) @ model["stack"])
    a, b = model["platt"]
    return expit(a + b * (Z @ model["w"]))


def _validate(method, Z, y, seasons, cols) -> float:
    vs = sorted(set(seasons))[-VAL_SEASONS:]
    losses = []
    for v in vs:
        tr, te = seasons < v, seasons == v
        if len(set(seasons[tr])) < 1 or te.sum() == 0:
            continue
        m = fit(method, Z[tr][:, cols], y[tr])
        losses.append(_ll(apply(m, Z[te][:, cols]), y[te]) * te.sum())
    return sum(losses) / max(sum((seasons == v).sum() for v in vs), 1)


def select(method, Z, y, seasons, names) -> list[int]:
    remaining = list(range(len(names)))
    scores = {i: _validate(method, Z, y, seasons, [i]) for i in remaining}
    chosen = [min(scores, key=scores.get)]
    best = scores[chosen[0]]
    remaining.remove(chosen[0])
    while remaining:
        trial = {i: _validate(method, Z, y, seasons, chosen + [i]) for i in remaining}
        i = min(trial, key=trial.get)
        if trial[i] < best - MIN_GAIN:
            chosen.append(i)
            best = trial[i]
            remaining.remove(i)
        else:
            break
    return chosen


def run(forecasts: pd.DataFrame, outcomes: pd.DataFrame, components: list[str], label: str,
        info_set: str, uses_market: bool, target_seasons, methods=METHODS, log=print) -> tuple[pd.DataFrame, list]:
    """Ensemble forecasts for each target season, plus a record of what was chosen."""
    w = forecasts[forecasts["model"].isin(components)].pivot_table(
        index="game_id", columns="model", values="p_home_raw", aggfunc="first")
    w = w.dropna()[components]
    # the ensemble is only as early as its latest component: take that component's timestamps
    sub = forecasts[forecasts["model"].isin(components)].sort_values("forecast_ts", ascending=False)
    meta = sub.drop_duplicates("game_id").set_index("game_id").loc[w.index]
    res = outcomes.set_index("game_id")["home_win"].reindex(w.index)
    Z_all = logit(w.values)
    seasons_all = meta["season"].values
    rows, chosen_log = [], []
    for s in target_seasons:
        tr = (seasons_all < s) & res.isin([0.0, 1.0]).values
        te = seasons_all == s
        if len(set(seasons_all[tr])) < MIN_TRAIN_SEASONS or te.sum() == 0:
            continue
        Z, y, ss = Z_all[tr], res.values[tr].astype(float), seasons_all[tr]
        for method in methods:
            cols = select(method, Z, y, ss, components)
            m = fit(method, Z[:, cols], y)
            p = apply(m, Z_all[te][:, cols])
            name = f"{label}_{method}"
            chosen_log.append({"season": int(s), "ensemble": name, "chosen": [components[c] for c in cols],
                               "weights": (m.get("w").round(3).tolist() if "w" in m else m["stack"].round(3).tolist())})
            for gid, pp in zip(w.index[te], p):
                g = meta.loc[gid]
                rows.append({"game_id": gid, "season": int(g["season"]), "week": int(g["week"]),
                             "home_team": g["home_team"], "away_team": g["away_team"], "kickoff": g["kickoff"],
                             "forecast_ts": g["forecast_ts"], "info_set": info_set,
                             "p_home_raw": float(np.clip(pp, 1e-4, 1 - 1e-4)),
                             "p_away_raw": float(1 - np.clip(pp, 1e-4, 1 - 1e-4)), "p_home_cal": None, "p_away_cal": None,
                             "exp_margin": None, "exp_total": None, "margin_sd": None, "model": name,
                             "model_version": "1", "train_cutoff": f"seasons<{s}", "feature_cutoff": g["feature_cutoff"],
                             "missing": "{}", "provenance": "out-of-fold component forecasts: " + ",".join(components),
                             "uses_market": uses_market})
        log(f"  {label} {s}: " + "; ".join(f"{c['ensemble'].split('_')[-1]}={c['chosen']}" for c in chosen_log[-len(methods):]))
    return pd.DataFrame(rows), chosen_log


def error_correlation(forecasts: pd.DataFrame, outcomes: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    w = forecasts[forecasts["model"].isin(models)].pivot_table(index="game_id", columns="model", values="p_home_raw")
    w = w.dropna()
    y = outcomes.set_index("game_id")["home_win"].reindex(w.index)
    keep = y.isin([0.0, 1.0])
    resid = (w[keep].values - y[keep].values[:, None])
    return pd.DataFrame(np.corrcoef(resid.T), index=w.columns, columns=w.columns)


def incremental(forecasts: pd.DataFrame, outcomes: pd.DataFrame, models: list[str], target_seasons) -> pd.DataFrame:
    """Does each component add information given all the others? Walk-forward logistic stacks
    with and without it; per-game log-loss differences for bootstrap."""
    w = forecasts[forecasts["model"].isin(models)].pivot_table(index="game_id", columns="model", values="p_home_raw")
    w = w.dropna()[models]
    meta = forecasts.drop_duplicates("game_id").set_index("game_id").loc[w.index]
    y_all = outcomes.set_index("game_id")["home_win"].reindex(w.index).values
    Z_all = logit(w.values)
    s_all = meta["season"].values
    out = []
    for j, name in enumerate(models):
        others = [i for i in range(len(models)) if i != j]
        for s in target_seasons:
            tr = (s_all < s) & np.isin(y_all, [0.0, 1.0])
            te = (s_all == s) & np.isin(y_all, [0.0, 1.0])
            if len(set(s_all[tr])) < MIN_TRAIN_SEASONS or not te.any():
                continue
            full = fit("stack", Z_all[tr], y_all[tr])
            less = fit("stack", Z_all[tr][:, others], y_all[tr])
            pf, pl = apply(full, Z_all[te]), apply(less, Z_all[te][:, others])
            yy = y_all[te]
            lf = -(yy * np.log(pf) + (1 - yy) * np.log(1 - pf))
            ll = -(yy * np.log(pl) + (1 - yy) * np.log(1 - pl))
            for gid, d, wk in zip(w.index[te], lf - ll, meta["week"].values[te]):
                out.append({"component": name, "game_id": gid, "season": s, "week": wk, "diff": d})
    return pd.DataFrame(out)
