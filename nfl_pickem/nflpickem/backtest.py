"""Walk-forward backtesting.

For each evaluation season S (in order):
  1. train  = completed games in seasons <  S-1
     valid  = completed games in season    S-1 (hyper-parameter selection only)
     -> models refit on train+valid with the selected hyper-parameters.
  2. Calibrators and learned blend weights are fitted only on *earlier*
     walk-forward out-of-sample predictions (seasons < S).
  3. Season S games are predicted with features computed at each game's
     prediction cutoff (point-in-time), and the predictions are stored in
     ``backtest_predictions`` *before* any metric looks at outcomes.
  4. Weekly confidence points are allocated exactly as on the real slate.

Models are refit once per season; Elo, rolling EPA, rest, QB and market
inputs update every week. Holdout seasons are excluded unless explicitly
requested with include_holdout=True.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import db
from .confidence import ScoringRules
from .evaluation import (calibration_table, favorite_underdog, model_comparison, paired_week_difference,
                         pick_buckets, pool_summary, prob_metrics, simulate_pool)
from .features import FeatureSettings, build_features, model_feature_columns, validate_point_in_time
from .models.ensemble import COMPONENTS, blend, blend_with_fallback, learn_weights, weights_from_config
from .models.ml import choose_calibration, tune_and_fit

log = logging.getLogger(__name__)

ALL_MODELS = ["market", "elo", "logistic", "gbm", "residual", "ml_only", "blend"]


@dataclass
class BacktestResult:
    backtest_id: str
    predictions: pd.DataFrame
    metrics: pd.DataFrame
    metrics_by_season: pd.DataFrame
    weekly: pd.DataFrame
    pool: pd.DataFrame
    calibration: pd.DataFrame
    buckets: pd.DataFrame
    favorite: pd.DataFrame
    blend_ratio_analysis: pd.DataFrame
    paired: list[dict]
    season_log: list[dict] = field(default_factory=list)
    seasons: list[int] = field(default_factory=list)


def load_inputs(con) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    games = db.load_games(con)
    stats = con.execute("SELECT * FROM team_game_stats").df()
    odds = con.execute("SELECT * FROM odds_snapshots").df()
    return games, stats, odds


def load_football_inputs(con) -> dict:
    """Optional play-by-play detail tables (empty frames if not ingested yet)."""
    return {"detail": con.execute("SELECT * FROM team_game_detail").df(),
            "qbs": con.execute("SELECT * FROM qb_game_stats").df()}


def features_from_db(con, cfg: dict, as_of=None, target_game_ids=None) -> pd.DataFrame:
    games, stats, odds = load_inputs(con)
    return build_features(games, stats, odds, cfg, as_of=as_of, target_game_ids=target_game_ids,
                          **load_football_inputs(con))


def eval_seasons(cfg: dict, available: list[int], include_holdout: bool,
                 seasons: list[int] | None = None) -> list[int]:
    bt = cfg["backtest"]
    holdout = set(int(s) for s in bt.get("holdout_seasons", []))
    if seasons is None:
        seasons = [s for s in available if int(bt["first_eval_season"]) <= s <= int(bt["last_eval_season"])
                   and s not in holdout]
        if include_holdout:
            seasons += sorted(holdout & set(available))
    seasons = sorted(set(seasons))
    if not include_holdout and holdout & set(seasons):
        raise ValueError(f"Seasons {sorted(holdout & set(seasons))} are the untouched holdout; "
                         "pass include_holdout=True only once model development is final.")
    first = min(available)
    min_train = int(bt.get("min_train_seasons", 4))
    return [s for s in seasons if s - first >= min_train]


def run_backtest(con, cfg: dict, seasons: list[int] | None = None, include_holdout: bool = False,
                 save: bool = True, features: pd.DataFrame | None = None) -> BacktestResult:
    games, stats, odds = load_inputs(con)
    if games.empty:
        raise RuntimeError("No games in the database. Run `ingest` (real data) or `demo` first.")
    available = sorted(games.loc[games["game_status"] == "final", "season"].unique().tolist())
    target = eval_seasons(cfg, available, include_holdout, seasons)
    if not target:
        raise RuntimeError(f"No evaluable seasons. Available completed seasons: {available}")
    fs = FeatureSettings.from_config(cfg["features"])
    cols = model_feature_columns(fs)
    if features is None:
        features = build_features(games, stats, odds, cfg, **load_football_inputs(con))
    validate_point_in_time(features)
    feats = features[features["game_status"] == "final"]

    rules = ScoringRules.from_config(cfg["pool"])
    blend_cfg = cfg["blend"]
    fixed_w = weights_from_config(blend_cfg)
    created = datetime.now(timezone.utc).replace(tzinfo=None)
    fingerprint = hashlib.sha1(json.dumps({"cfg": cfg, "seasons": target, "holdout": include_holdout},
                                          sort_keys=True, default=str).encode()).hexdigest()[:10]
    backtest_id = f"bt_{created:%Y%m%dT%H%M%S}_{fingerprint}"
    oos_parts: list[pd.DataFrame] = []
    season_log = []
    for S in target:
        train = feats[feats["season"] < S - 1]
        valid = feats[feats["season"] == S - 1]
        test = feats[feats["season"] == S].copy()
        if train.empty or test.empty:
            continue
        assert train["kickoff_utc"].max() < valid["kickoff_utc"].min() if len(valid) else True
        assert (valid if len(valid) else train)["kickoff_utc"].max() < test["kickoff_utc"].min()
        models = tune_and_fit(train, valid if len(valid) else None, cols, cfg)
        raw = models.predict(test)
        test["logistic_raw"], test["gbm_raw"] = raw["logistic"], raw["gbm"]
        prior = pd.concat(oos_parts) if oos_parts else pd.DataFrame()
        cal_info = {}
        for comp in ("logistic", "gbm"):
            if len(prior):
                d = prior[prior["home_result"].isin([0.0, 1.0])].sort_values("kickoff_utc")
                cal = choose_calibration(d[f"{comp}_raw"], d["home_result"], cfg["models"]["calibration"])
            else:
                cal = choose_calibration([], [], "none")
            test[comp] = cal.transform(test[f"{comp}_raw"])
            cal_info[comp] = cal.method
        test["residual"] = raw.get("residual", np.full(len(test), np.nan))
        test["market"] = test["market_home_prob"]
        test["elo"] = test["elo_home_prob"]
        test["ml_only"] = blend(test[["elo", "logistic", "gbm"]], {"elo": 1, "logistic": 1, "gbm": 1},
                                blend_cfg["space"])
        weights, wsrc = fixed_w, "fixed"
        if blend_cfg["mode"] == "learned" and len(prior) >= 100:
            try:
                weights, _ = learn_weights(prior, components=blend_cfg.get("learned_components"),
                                           step=float(blend_cfg.get("learned_step", 0.1)),
                                           space=blend_cfg["space"])
                wsrc = "learned"
            except ValueError as exc:
                log.warning("Falling back to fixed weights for %s: %s", S, exc)
        test["blend"] = blend_with_fallback(test[COMPONENTS], weights, blend_cfg["space"])
        test["blend_weights"] = json.dumps({k: round(v, 3) for k, v in weights.items()})
        test["predicted_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
        oos_parts.append(test)
        season_log.append({"season": S, "train_seasons": f"{int(train.season.min())}-{int(train.season.max())}",
                           "valid_season": S - 1 if len(valid) else None, "test_games": len(test),
                           "params": models.params, "calibration": cal_info,
                           "weights": weights, "weights_source": wsrc})
        log.info("Backtest season %s done (%d games, weights=%s)", S, len(test), wsrc)

    preds = pd.concat(oos_parts, ignore_index=True)
    if save:
        _store_predictions(con, backtest_id, preds)  # stored before outcomes are scored

    metrics = model_comparison(preds, ALL_MODELS)
    by_season = model_comparison(preds, ALL_MODELS, by="season")
    weekly = pd.concat([simulate_pool(preds, m, rules) for m in ALL_MODELS], ignore_index=True)
    pool = pool_summary(weekly)
    calib = pd.concat([calibration_table(preds, m) for m in ALL_MODELS], ignore_index=True)
    buckets = pd.concat([pick_buckets(preds, m) for m in ALL_MODELS], ignore_index=True)
    fav = pd.concat([favorite_underdog(preds, m) for m in ALL_MODELS], ignore_index=True)
    ratio = blend_ratio_analysis(preds, rules, blend_cfg["space"])
    paired = [paired_week_difference(weekly, "blend", b) for b in ("market", "elo", "logistic", "gbm", "ml_only")]
    paired += [paired_week_difference(weekly, "residual", "market")]
    result = BacktestResult(backtest_id, preds, metrics, by_season, weekly, pool, calib, buckets, fav,
                            ratio, paired, season_log, target)
    if save:
        _store_run(con, result, cfg, include_holdout, created)
    return result


def blend_ratio_analysis(preds: pd.DataFrame, rules: ScoringRules, space: str) -> pd.DataFrame:
    """Ex-post comparison of market/ML ratios on the stored OOS predictions.

    This is *analysis*, not model selection: choosing the best row here and
    reporting its score would be in-sample. The ex-ante blend is 'blend'.
    """
    rows = []
    for mw in (0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        w = {"market": mw, "elo": (1 - mw) / 3, "logistic": (1 - mw) / 3, "gbm": (1 - mw) / 3}
        p = blend(preds[["market", "elo", "logistic", "gbm"]], w, space)
        tmp = preds.assign(_r=p)
        r = prob_metrics(tmp["home_result"].to_numpy(), p)
        wk = simulate_pool(tmp, "_r", rules)
        r.update({"market_weight": mw, "ml_weight": 1 - mw, "avg_weekly_points": wk["points"].mean(),
                  "total_points": wk["points"].sum()})
        rows.append(r)
    return pd.DataFrame(rows)


def _store_predictions(con, backtest_id: str, preds: pd.DataFrame) -> None:
    d = preds.rename(columns={"cutoff": "prediction_cutoff"}).assign(backtest_id=backtest_id)
    cols = ["backtest_id", "game_id", "season", "week", "game_type", "kickoff_utc", "prediction_cutoff",
            "home_team", "away_team", "market", "elo", "logistic", "gbm", "residual", "ml_only", "blend", "logistic_raw",
            "gbm_raw", "odds_status", "blend_weights", "predicted_at"]
    db.upsert(con, "backtest_predictions", d, cols)


def _store_run(con, res: BacktestResult, cfg: dict, include_holdout: bool, created: datetime) -> None:
    summary = {
        "metrics": res.metrics.to_dict(orient="records"),
        "pool": res.pool.to_dict(orient="records"),
        "paired": res.paired,
        "season_log": res.season_log,
        "blend_ratio_analysis": res.blend_ratio_analysis.to_dict(orient="records"),
        "date_range": [str(res.predictions["kickoff_utc"].min()), str(res.predictions["kickoff_utc"].max())],
    }
    sources = ",".join(sorted(set(db.load_games(con)["data_source"])))
    con.execute("INSERT OR REPLACE INTO backtest_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                [res.backtest_id, created, ",".join(map(str, res.seasons)), include_holdout,
                 json.dumps(cfg, default=str), sources, json.dumps(summary, default=_json_default)])


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return str(o)


def latest_backtest(con) -> tuple[dict | None, pd.DataFrame]:
    row = con.execute("SELECT backtest_id, created_at, seasons, includes_holdout, data_source, summary_json "
                      "FROM backtest_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return None, pd.DataFrame()
    meta = {"backtest_id": row[0], "created_at": row[1], "seasons": row[2], "includes_holdout": row[3],
            "data_source": row[4], "summary": json.loads(row[5])}
    preds = con.execute("SELECT b.*, g.home_score, g.away_score, g.game_status FROM backtest_predictions b "
                        "JOIN games g USING (game_id) WHERE backtest_id = ?", [row[0]]).df()
    hs, as_ = preds["home_score"].astype(float), preds["away_score"].astype(float)
    preds["home_result"] = np.where(hs > as_, 1.0, np.where(hs < as_, 0.0, 0.5))
    return meta, preds
