"""Running a backtest end to end and storing its forecasts (no results joined here)."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace

import numpy as np
import pandas as pd

from . import backtest, data
from .config import DEFAULT, RESULTS, Config, config_hash
from .journal import now_utc
from .predictions import model_version, write_once

log = logging.getLogger("challenger.runs")

VARIANTS = ("market_free", "market_informed", "no_epa")


def data_fingerprint() -> str:
    book = data.manifest()
    text = json.dumps({k: v["sha256"] for k, v in sorted(book.items())}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def variant_config(variant: str) -> Config:
    return replace(DEFAULT, use_epa=False) if variant == "no_epa" else DEFAULT


def add_market_columns(X: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Closing spread and de-vigged moneyline chance as inputs (market-informed variant only)."""
    g = games.set_index("game_id")
    X = X.copy()
    X["spread_line"] = X["game_id"].map(g["spread_line"])
    h, a = data.implied_chance(g["home_moneyline"]), data.implied_chance(g["away_moneyline"])
    ml = pd.Series(np.asarray(h) / (np.asarray(h) + np.asarray(a)), index=g.index)
    X["ml_prob"] = X["game_id"].map(ml)
    return X


def run(split: str, variant: str = "market_free", seasons=None) -> dict:
    if variant not in VARIANTS:
        raise ValueError(variant)
    cfg = variant_config(variant)
    seasons = list(seasons or (cfg.dev_seasons if split == "dev" else cfg.holdout_seasons))
    games, X, labels = backtest.load_inputs(cfg)
    market = variant == "market_informed"
    extra_lr, extra_gbm = (), ()
    if market:
        X = add_market_columns(X, games)
        extra_lr, extra_gbm = ("spread_line",), ("spread_line", "ml_prob")
    started = now_utc()
    preds, records = backtest.walk_forward(X, labels, cfg, seasons, market=market,
                                           extra_lr=extra_lr, extra_gbm=extra_gbm)
    # only forecasts whose deadline has passed: the future is the shadow mode's job
    preds = preds[pd.to_datetime(preds["deadline_utc"], utc=True) < started].reset_index(drop=True)
    version = model_version(cfg) + ("" if variant == "market_free" else f"-{variant}")
    preds.insert(0, "model_version", version)
    if variant != "market_free":
        preds["model"] = preds["model"] + f"__{variant}"
    run_id = f"{variant}_{split}_{config_hash(cfg)}_{data_fingerprint()}"
    preds.insert(0, "run_id", run_id)
    folder = RESULTS / "backtests"
    meta = {"split": split, "variant": variant, "seasons": seasons, "model_version": version,
            "config_hash": config_hash(cfg), "config": cfg.to_dict(), "data_manifest": data.manifest(),
            "started_at_utc": started.isoformat(), "retraining": "once per season, before week 1"}
    path = write_once(preds, folder, run_id, meta)
    (folder / f"seasons_{run_id}.json").write_text(backtest.record_json(records))
    log.info("wrote %s (%d rows)", path.name, len(preds))
    return {"run_id": run_id, "path": str(path), "rows": len(preds)}
