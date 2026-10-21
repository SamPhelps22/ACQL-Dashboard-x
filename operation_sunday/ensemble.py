"""Ensembles trained ONLY on chronological out-of-fold predictions.

Base-model predictions from the walk-forward are out-of-fold by construction
(each week was predicted by models fitted before it). An ensemble's weights
for week w are learned from base predictions of earlier weeks whose results
were published by w's cutoff, never from the holdout seasons, never in-sample.

Methods:
  equal      equal weights in logit space
  stack      L2-regularised logistic stacking on component logits; with fewer
             than MIN_OOF games it falls back to equal weights
  perf       weights from out-of-fold log loss, shrunk toward equal by
             n / (n + SHRINK_GAMES) so a short noisy record can't dominate

A component with no repeatable incremental value gets its stacking weight
pulled to zero by the penalty; the report lists the learned weights.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import per_game_logloss
from .models import fit_logistic, logit

MIN_OOF = 300
SHRINK_GAMES = 2000
STACK_L2 = 20.0

FOOTBALL = ["elo", "bayes_strength", "logistic", "situational"]
ENSEMBLES = {
    "ens_equal_football": ("equal", FOOTBALL, True),
    "ens_stack_football": ("stack", FOOTBALL, True),
    "ens_perf_football": ("perf", FOOTBALL, True),
    # live only: needs a market snapshot at the cutoff, so it has no backtest yet
    "ens_market_informed": ("stack", FOOTBALL + ["market_snapshot"], True),
    # retrospective benchmark: stacks the CLOSING line - never a Thursday input
    "ens_market_close_bench": ("stack", FOOTBALL + ["market_close"], False),
}


def _weights(method, oof: pd.DataFrame, comps, holdout_seasons):
    oof = oof[~oof["season"].isin(holdout_seasons)].dropna(subset=comps + ["home_win"])
    oof = oof[oof["home_win"].isin([0.0, 1.0])]
    k = len(comps)
    equal = ("logit", np.r_[0.0, np.full(k, 1.0 / k)])
    if method == "equal" or len(oof) < MIN_OOF:
        return equal, len(oof)
    y = oof["home_win"].to_numpy(float)
    if method == "stack":
        Z = np.column_stack([logit(oof[c]) for c in comps])
        # penalise departures from equal weights, not from zero, so noise shrinks to equal
        prior = np.full(k, 1.0 / k)
        b = fit_logistic(Z, y, STACK_L2)
        b[1:] = prior + (b[1:] - prior) * len(oof) / (len(oof) + SHRINK_GAMES / 4)
        b[1:] = np.clip(b[1:], 0, None)
        return ("logit", b), len(oof)
    if method == "perf":
        ll = np.array([per_game_logloss(oof[c], y).mean() for c in comps])
        raw = np.exp(-(ll - ll.min()) * 400)
        raw /= raw.sum()
        lam = len(oof) / (len(oof) + SHRINK_GAMES)
        w = (1 - lam) / k + lam * raw
        return ("logit", np.r_[0.0, w]), len(oof)
    raise ValueError(method)


def combine(weights, frame, comps):
    _, b = weights
    Z = np.column_stack([logit(frame[c]) for c in comps])
    return 1 / (1 + np.exp(-(b[0] + Z @ b[1:])))


def _wide(scored: pd.DataFrame) -> pd.DataFrame:
    meta = scored.drop_duplicates("game_id").set_index("game_id")[
        ["week_key", "season", "week", "home_win", "cutoff_utc", "published_utc"]]
    p = scored.pivot_table(index="game_id", columns="model", values="p_home", aggfunc="first")
    return meta.join(p, how="left").reset_index()


def ensemble_walk_forward(scored: pd.DataFrame, holdout_seasons=()) -> tuple[pd.DataFrame, dict]:
    """scored: long base predictions with outcomes. Returns long ensemble
    predictions and the last weights learned per ensemble."""
    wide = _wide(scored)
    weeks = wide.drop_duplicates("week_key").sort_values("cutoff_utc")[["week_key", "cutoff_utc"]]
    out, last = [], {}
    for name, (method, comps, eligible) in ENSEMBLES.items():
        if any(c not in wide for c in comps):
            continue
        for key, cut in weeks.itertuples(index=False):
            week = wide[wide["week_key"] == key]
            if week[comps].isna().all(axis=0).any():
                continue
            prior = wide[(wide["published_utc"] <= cut) & (wide["cutoff_utc"] < cut)]
            w, n = _weights(method, prior, comps, holdout_seasons)
            ok = week[comps].notna().all(axis=1)
            p = np.full(len(week), np.nan)
            if ok.any():
                p[ok.to_numpy()] = combine(w, week[ok], comps)
            out.append(pd.DataFrame({"week_key": [key] * len(week), "season": week["season"].to_numpy(),
                                     "week": week["week"].to_numpy(), "game_id": week["game_id"].to_numpy(),
                                     "model": name, "p_home": p, "exp_margin": np.nan, "exp_total": np.nan,
                                     "train_games": n, "train_cutoff": cut}))
            last[name] = {"method": method, "components": comps, "intercept": round(float(w[1][0]), 4), "weights": np.round(w[1][1:], 4).tolist(),
                          "oof_games": n, "thursday_eligible": eligible}
    return (pd.concat(out, ignore_index=True) if out else pd.DataFrame()), last


def live_weights(scored: pd.DataFrame, name: str, holdout_seasons=()):
    method, comps, _ = ENSEMBLES[name]
    wide = _wide(scored)
    if any(c not in wide for c in comps):
        return None, 0
    return _weights(method, wide, comps, holdout_seasons)
