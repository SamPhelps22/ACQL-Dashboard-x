"""Expanding-window, season-by-season walk-forward backtest.

For each test season S:

  1. the training pool is every decided game from `first_train_season` to S-1;
  2. the last `inner_folds` seasons before S are inner validation folds: for
     each fold f, models are fitted on seasons < f and predict f. The logistic
     C and the boosting settings with the lowest pooled inner log loss are
     chosen; their out-of-fold predictions fit the Platt calibrators and the
     stacker. Nothing in season S or later is touched;
  3. the chosen models are refitted on the whole pool and predict every game
     of season S from its deadline-time features - no result is joined;
  4. the predictions are returned (and written once by `run`); results are
     revealed only in challenger.evaluate / challenger.arena.

Models are refitted once per season, before week 1. That uses less
information than was available mid-season (the features still update every
week), never more. Ties are left out of training (they are neither a home
win nor a home loss).
"""

from __future__ import annotations

import json
import logging
import time

import numpy as np
import pandas as pd

from . import calibration, features as feat
from .config import Config
from .data import MARKET_COLUMNS, OUTCOME_COLUMNS
from .elo import log_loss
from .models import GbmModel, LogisticModel, Stacker

log = logging.getLogger("challenger.backtest")

MODELS = ("elo", "logistic", "boosting", "challenger")


def _check_inputs(frame: pd.DataFrame, market: bool) -> None:
    leaked = set(OUTCOME_COLUMNS) & set(frame.columns)
    if leaked:
        raise ValueError(f"feature table carries outcome columns: {sorted(leaked)}")
    if not market:
        priced = set(MARKET_COLUMNS) & set(frame.columns)
        if priced:
            raise ValueError(f"market-free run was handed betting columns: {sorted(priced)}")


def _fit_predict(kind: str, setting, cfg: Config, Xtr, ytr, Xte, lr_cols, gbm_cols):
    if kind == "logistic":
        return LogisticModel(lr_cols, setting).fit(Xtr, ytr).predict(Xte)
    return GbmModel(gbm_cols, setting, cfg.models.gbm_common).fit(Xtr, ytr).predict(Xte)


def season_models(X: pd.DataFrame, y: pd.Series, season: int, cfg: Config,
                  lr_cols: list[str], gbm_cols: list[str]) -> tuple[dict, dict]:
    """Choose settings and fit calibrators/stacker for test season `season` using earlier seasons only.

    Returns (fitted objects, a JSON-able record of what was chosen and why).
    """
    m = cfg.models
    decided = y.notna()
    pool = X[(X["season"] < season) & (X["season"] >= cfg.first_train_season) & decided]
    folds = [f for f in range(season - m.inner_folds, season) if (pool["season"] < f).any() and (pool["season"] == f).any()]
    oof = {"elo": [], "y": [], "season": []}
    lr_oof = {C: [] for C in m.lr_C_grid}
    gbm_oof = {i: [] for i in range(len(m.gbm_grid))}
    for f in folds:
        tr, va = pool[pool["season"] < f], pool[pool["season"] == f]
        ytr, yva = y.loc[tr.index].to_numpy(), y.loc[va.index].to_numpy()
        for C in m.lr_C_grid:
            lr_oof[C].append(_fit_predict("logistic", C, cfg, tr, ytr, va, lr_cols, gbm_cols))
        for i, params in enumerate(m.gbm_grid):
            gbm_oof[i].append(_fit_predict("boosting", params, cfg, tr, ytr, va, lr_cols, gbm_cols))
        oof["elo"].append(va["elo_prob"].to_numpy())
        oof["y"].append(yva)
        oof["season"].append(np.full(len(va), f))
    y_oof = np.concatenate(oof["y"])
    lr_loss = {C: log_loss(np.concatenate(v), y_oof) for C, v in lr_oof.items()}
    gbm_loss = {i: log_loss(np.concatenate(v), y_oof) for i, v in gbm_oof.items()}
    C = min(lr_loss, key=lambda k: (lr_loss[k], k))
    gi = min(gbm_loss, key=lambda k: (gbm_loss[k], k))
    parts = {"elo": np.concatenate(oof["elo"]), "logistic": np.concatenate(lr_oof[C]),
             "boosting": np.concatenate(gbm_oof[gi])}
    cal = {k: calibration.make(m.calibration).fit(v, y_oof) for k, v in parts.items()}
    cal_parts = np.column_stack([cal[k](parts[k]) for k in ("elo", "logistic", "boosting")])
    stack = Stacker(m.stack_C).fit(cal_parts, y_oof)
    record = {
        "season": season, "inner_folds": folds, "inner_games": int(len(y_oof)),
        "lr_C": C, "lr_inner_log_loss": {str(k): round(v, 5) for k, v in lr_loss.items()},
        "gbm_setting": m.gbm_grid[gi], "gbm_inner_log_loss": {str(k): round(v, 5) for k, v in gbm_loss.items()},
        "inner_log_loss": {k: round(log_loss(v, y_oof), 5) for k, v in parts.items()}
        | {"challenger": round(log_loss(stack.predict(cal_parts), y_oof), 5)},
        "calibration": {k: c.state() for k, c in cal.items()},
        "stack_weights": stack.weights(),
    }
    fitted = {"C": C, "gbm_params": m.gbm_grid[gi], "cal": cal, "stack": stack}
    return fitted, record


def predict_season(X: pd.DataFrame, y: pd.Series, season: int, cfg: Config, lr_cols: list[str],
                   gbm_cols: list[str], target: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict, dict]:
    """Fit on every decided game before `season`, predict `target` (default: all of `season`)."""
    fitted, record = season_models(X, y, season, cfg, lr_cols, gbm_cols)
    pool = X[(X["season"] < season) & (X["season"] >= cfg.first_train_season) & y.notna()]
    ytr = y.loc[pool.index].to_numpy()
    lr = LogisticModel(lr_cols, fitted["C"]).fit(pool, ytr)
    gbm = GbmModel(gbm_cols, fitted["gbm_params"], cfg.models.gbm_common).fit(pool, ytr)
    test = X[X["season"] == season] if target is None else target
    cal = fitted["cal"]
    raw = {"elo": test["elo_prob"].to_numpy(), "logistic": lr.predict(test), "boosting": gbm.predict(test)}
    out = {"elo": raw["elo"], "logistic": cal["logistic"](raw["logistic"]), "boosting": cal["boosting"](raw["boosting"])}
    stack_in = np.column_stack([cal["elo"](raw["elo"]), out["logistic"], out["boosting"]])
    out["challenger"] = fitted["stack"].predict(stack_in)
    record |= {"train_seasons": f"{int(pool['season'].min())}-{int(pool['season'].max())}",
               "train_games": int(len(pool)), "lr_coefficients": lr.coefficients(),
               "gbm_top_features": gbm.importance()}
    frames = []
    for name, p in out.items():
        frames.append(pd.DataFrame({
            "model": name, "game_id": test["game_id"].to_numpy(), "season": test["season"].to_numpy(),
            "week": test["week"].to_numpy(), "game_type": test["game_type"].to_numpy(),
            "home": test["home"].to_numpy(), "away": test["away"].to_numpy(),
            "kickoff_utc": test["kickoff_utc"].to_numpy(), "deadline_utc": test["deadline_utc"].to_numpy(),
            "data_cutoff_utc": test["data_cutoff_utc"].to_numpy(), "train_seasons": record["train_seasons"],
            "p_home": np.clip(p, 1e-4, 1 - 1e-4)}))
    preds = pd.concat(frames, ignore_index=True)
    preds["p_away"] = 1.0 - preds["p_home"]
    return preds, record, {"logistic": lr, "boosting": gbm, **fitted}


def walk_forward(X: pd.DataFrame, labels: pd.Series, cfg: Config, seasons, *, market: bool = False,
                 extra_lr: tuple[str, ...] = (), extra_gbm: tuple[str, ...] = ()) -> tuple[pd.DataFrame, list[dict]]:
    """Predictions for every game of every season in `seasons`, each from earlier seasons only.

    `X` is the feature table (features.build + add_differences); `labels` is
    home_win indexed like X. X must not carry outcome columns, and a
    market-free run must not carry betting columns either.
    """
    _check_inputs(X, market)
    use_pbp = cfg.use_epa
    lr_cols = list(feat.LR_FEATURES if use_pbp else feat.LR_FEATURES_NO_EPA) + list(extra_lr)
    gbm_cols = feat.gbm_features(X, use_pbp) + list(extra_gbm)
    gbm_cols = [c for c in dict.fromkeys(gbm_cols) if c in X.columns]
    out, records = [], []
    for season in seasons:
        t0 = time.time()
        preds, record, _ = predict_season(X, labels, season, cfg, lr_cols, gbm_cols)
        record["seconds"] = round(time.time() - t0, 1)
        log.info("season %s: %s games, inner LL %s", season, (X["season"] == season).sum(), record["inner_log_loss"])
        out.append(preds)
        records.append(record)
    return pd.concat(out, ignore_index=True), records


def load_inputs(cfg: Config, seasons_needed=None):
    """Schedule, pbp aggregates and the feature table, built from the local cache."""
    from . import data, pbp

    games = data.load_games()
    games = games[games["season"] >= cfg.first_pbp_season - 2].reset_index(drop=True)
    first = cfg.first_pbp_season
    last = int(games["season"].max())
    teams, qbs = pbp.aggregate(range(first, last + 1))
    X = feat.add_differences(feat.build(games, teams, qbs, cfg), cfg.use_epa)
    labels = X["game_id"].map(games.set_index("game_id")["home_win"])
    return games, X, labels


def record_json(records: list[dict]) -> str:
    return json.dumps(records, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
