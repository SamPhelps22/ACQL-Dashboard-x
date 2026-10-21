"""Prospective shadow mode: forecast the coming week before kickoff, into the journal.

    python -m challenger shadow --season 2026 --week 7

refreshes the schedule and this season's play-by-play, rebuilds the
features as of the week's deadline, fits the season's models on every
earlier season (exactly as the backtest does for a test season), and appends
one record per game and model to challenger/journal/challenger.jsonl - only
for games that have not kicked off. The fitted model is saved under
challenger/artifacts/ and named by its content hash, so the journal points
at the exact model that made each forecast.

A market snapshot (the lines nflverse carried when the schedule was fetched)
goes to a separate journal and is never shown to the model. Deadeye's
forecast is captured on its own by `python -m challenger capture-deadeye`
(challenger/arena/capture.py); nothing here reads it.
"""

from __future__ import annotations

import hashlib
import json
import logging

import pandas as pd

from . import backtest, data, features as feat, journal
from .config import ARTIFACTS, DEFAULT
from .predictions import git_commit, model_version

log = logging.getLogger("challenger.shadow")


def _save_artifact(fitted: dict, record: dict, version: str, season: int) -> tuple[str, str]:
    lr, gbm = fitted["logistic"], fitted["boosting"]
    bundle = {
        "model_version": version, "season": season, "train_seasons": record["train_seasons"],
        "train_games": record["train_games"],
        "logistic": {"C": lr.C, "features": lr.features, "coefficients": lr.coefficients(),
                     "median": lr.median.round(10).to_dict(), "mean": lr.mean.round(10).to_dict(),
                     "std": lr.std.round(10).to_dict()},
        "boosting": {"params": gbm.params, "features": gbm.features},
        "calibration": {k: c.state() for k, c in fitted["cal"].items()},
        "stack_weights": fitted["stack"].weights(),
        "selection": {k: record[k] for k in ("inner_folds", "lr_inner_log_loss", "gbm_inner_log_loss", "inner_log_loss")},
    }
    text = json.dumps(bundle, sort_keys=True, indent=1, default=str)
    booster = gbm.model.booster_.model_to_string()
    digest = hashlib.sha256((text + booster).encode()).hexdigest()[:12]
    folder = ARTIFACTS / f"{version}_s{season}_{digest}"
    if not folder.exists():
        folder.mkdir(parents=True)
        (folder / "model.json").write_text(text)
        (folder / "boosting.txt").write_text(booster)
    return folder.name, digest


def forecast_week(season: int, week: int, refresh: bool = True, now: pd.Timestamp | None = None) -> dict:
    cfg = DEFAULT
    if refresh:
        data.fetch_schedule(force=True)
        data.fetch_pbp([season], refresh=(season,))
    now = now or journal.now_utc()
    games, X, labels = backtest.load_inputs(cfg)
    week_rows = X[(X["season"] == season) & (X["week"] == week)]
    target = week_rows[week_rows["kickoff_utc"] > now]
    if target.empty:
        raise RuntimeError(f"no game of {season} week {week} is still to kick off")
    cutoff = target["data_cutoff_utc"].max()
    if pd.notna(cutoff) and cutoff > now:
        raise RuntimeError("feature data is newer than the forecast time")
    lr_cols = list(feat.LR_FEATURES)
    gbm_cols = feat.gbm_features(X, cfg.use_epa)
    preds, record, fitted = backtest.predict_season(X, labels, season, cfg, lr_cols, gbm_cols, target=target)
    version = model_version(cfg)
    artifact, digest = _save_artifact(fitted, record, version, season)
    manifest = data.manifest()
    last_train = games[(games["season"] < season) & games["completed"]]["kickoff_utc"].max()
    info = target.set_index("game_id")
    records = []
    for r in preds.itertuples(index=False):
        row = info.loc[r.game_id]
        missing = [c for c in gbm_cols if pd.isna(row[c])]
        records.append({
            "game_id": r.game_id, "season": int(r.season), "week": int(r.week), "home": r.home, "away": r.away,
            "kickoff_utc": pd.Timestamp(r.kickoff_utc).isoformat(), "deadline_utc": pd.Timestamp(r.deadline_utc).isoformat(),
            "prediction_ts_utc": now.isoformat(), "model": r.model, "model_version": version,
            "p_home": round(float(r.p_home), 6), "p_away": round(float(r.p_away), 6),
            "training_seasons": record["train_seasons"], "training_cutoff_utc": pd.Timestamp(last_train).isoformat(),
            "data_cutoff_utc": pd.Timestamp(row["data_cutoff_utc"]).isoformat() if pd.notna(row["data_cutoff_utc"]) else None,
            "schedule_retrieved_utc": manifest.get("schedule", {}).get("retrieved_at_utc"),
            "schedule_sha256": manifest.get("schedule", {}).get("sha256"),
            "pbp_retrieved_utc": manifest.get(f"pbp_{season}", {}).get("retrieved_at_utc"),
            "qb_assumed": {"home": row["h_qb_name"], "away": row["a_qb_name"]},
            "features_missing": missing, "features_missing_count": len(missing),
            "artifact": artifact, "git_commit": git_commit(),
        })
    written = journal.append_forecasts("challenger", records, now=now)
    # the market as it stood - recorded beside, never fed to the model
    g = games.set_index("game_id")
    snap = []
    for gid in target["game_id"]:
        x = g.loc[gid]
        snap.append({"game_id": gid, "season": season, "week": week, "source": "nflverse schedule",
                     "retrieved_at_utc": manifest.get("schedule", {}).get("retrieved_at_utc"),
                     "spread_line": None if pd.isna(x["spread_line"]) else float(x["spread_line"]),
                     "home_moneyline": None if pd.isna(x["home_moneyline"]) else float(x["home_moneyline"]),
                     "away_moneyline": None if pd.isna(x["away_moneyline"]) else float(x["away_moneyline"]),
                     "total_line": None if pd.isna(x["total_line"]) else float(x["total_line"])})
    journal.append_market(snap)
    return {"games": int(len(target)), "records": len(written), "artifact": artifact, "model_version": version,
            "prediction_ts_utc": now.isoformat(), "skipped_already_kicked_off": int(len(week_rows) - len(target))}


def record_outcomes(season: int, refresh: bool = True) -> int:
    """Append final scores for every journaled game that has finished."""
    if refresh:
        data.fetch_schedule(force=True)
    games = data.load_games().set_index("game_id")
    ids = {r["game_id"] for kind in ("challenger", "deadeye") for r in journal.read(kind)}
    now = journal.now_utc()
    recs = []
    for gid in sorted(ids):
        if gid not in games.index:
            continue
        g = games.loc[gid]
        if not bool(g["completed"]) or now < g["kickoff_utc"] + pd.Timedelta(hours=DEFAULT.game_duration_hours):
            continue
        recs.append({"game_id": gid, "kickoff_utc": g["kickoff_utc"].isoformat(), "home_score": int(g["home_score"]),
                     "away_score": int(g["away_score"]), "source": "nflverse schedule",
                     "schedule_sha256": data.manifest().get("schedule", {}).get("sha256")})
    return len(journal.append_outcomes(recs, now=now))
