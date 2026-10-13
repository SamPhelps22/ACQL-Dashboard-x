"""Model E: blended ensemble of market, Elo, logistic and gradient-boosting probabilities.

Baseline hypothesis: 70% market / 30% ML, where the ML share is split across
Elo / logistic / GBM by ``ml_weights``. Weights can be fixed or *learned* by a
simplex grid search that minimises log loss on prior out-of-sample predictions
only. Missing components (e.g. no odds) are dropped and the remaining weights
renormalised; such rows are flagged by the caller.
"""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .ml import clip, logit, safe_log_loss

COMPONENTS = ["market", "elo", "logistic", "gbm"]


def weights_from_config(blend_cfg: dict) -> dict[str, float]:
    mw = float(blend_cfg["market_weight"])
    ml = {k: float(v) for k, v in blend_cfg["ml_weights"].items()}
    tot = sum(ml.values()) or 1.0
    w = {"market": mw}
    w.update({k: (1 - mw) * v / tot for k, v in ml.items()})
    return normalize(w)


def normalize(w: dict[str, float]) -> dict[str, float]:
    tot = sum(max(v, 0.0) for v in w.values())
    if tot <= 0:
        raise ValueError("Blend weights must have a positive sum")
    return {k: max(v, 0.0) / tot for k, v in w.items()}


def blend(probs: pd.DataFrame | dict, weights: dict[str, float], space: str = "probability") -> np.ndarray:
    """Weighted blend per row; NaN components are excluded and weights renormalised.

    Returns NaN only if every weighted component is missing for a row.
    """
    df = pd.DataFrame(probs)
    keys = [k for k, w in weights.items() if w > 0 and k in df.columns]
    if not keys:
        raise ValueError("No blend components with positive weight are available")
    P = df[keys].to_numpy(dtype=float)
    W = np.array([weights[k] for k in keys])[None, :] * ~np.isnan(P)
    wsum = W.sum(axis=1)
    if space == "logit":
        L = np.where(np.isnan(P), 0.0, logit(np.nan_to_num(P, nan=0.5)))
        val = (W * L).sum(axis=1) / np.where(wsum > 0, wsum, np.nan)
        out = 1 / (1 + np.exp(-val))
    elif space == "probability":
        out = (W * np.nan_to_num(P)).sum(axis=1) / np.where(wsum > 0, wsum, np.nan)
    else:
        raise ValueError(f"Unknown blend space {space!r}")
    return np.where(wsum > 0, clip(out), np.nan)


def simplex_grid(keys: list[str], step: float) -> list[dict[str, float]]:
    n = int(round(1 / step))
    grids = []
    for combo in product(range(n + 1), repeat=len(keys)):
        if sum(combo) == n:
            grids.append({k: c / n for k, c in zip(keys, combo)})
    return grids


def learn_weights(oos: pd.DataFrame, components: list[str] | None = None, step: float = 0.1,
                  space: str = "probability", y_col: str = "home_result") -> tuple[dict[str, float], float]:
    """Grid-search blend weights on historical *out-of-sample* predictions.

    Deterministic: ties in log loss resolve to the first grid point (market-heavy
    orderings come first because 'market' is the first component).
    """
    components = components or COMPONENTS
    d = oos[oos[y_col].isin([0.0, 1.0])].dropna(subset=components)
    if len(d) < 100:
        raise ValueError("Need at least 100 out-of-sample games to learn blend weights")
    y = d[y_col].astype(int).to_numpy()
    best, best_ll = None, np.inf
    for w in simplex_grid(components, step):
        if sum(w.values()) == 0:
            continue
        ll = safe_log_loss(y, blend(d[components], w, space))
        if ll < best_ll - 1e-12:
            best, best_ll = w, ll
    return best, best_ll
