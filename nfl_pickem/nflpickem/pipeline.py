"""Weekly workflow: update data, train, predict, allocate, freeze, export, grade.

Every prediction run gets a unique run_id, a generated_at timestamp, the data
cutoff used for its features, and a model version. Runs are insert-only;
``freeze_run`` marks the one you submitted and frozen runs can never be
modified or deleted through this API. Re-running predictions creates a new run
and never touches a frozen submission.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import __version__, db
from .backtest import latest_backtest, load_football_inputs, load_inputs
from .confidence import ScoringRules, allocate, grade_sheet, validate_allocation
from .config import resolve_path
from .features import (FeatureSettings, build_features, model_feature_columns, save_team_features,
                       validate_point_in_time)
from .models.ensemble import blend, blend_with_fallback, learn_weights, weights_from_config
from .models.ml import FittedModels, choose_calibration, tune_and_fit

log = logging.getLogger(__name__)


PICK_SOURCES = {
    "blend": "blended_home_probability", "market": "market_home_probability",
    "elo": "elo_home_probability", "logistic": "logistic_home_probability",
    "gbm": "gradient_boosting_home_probability", "residual": "residual_home_probability",
}


class FrozenRunError(RuntimeError):
    """Attempt to modify a frozen (submitted) prediction run."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def data_mode(con) -> str:
    return db.get_meta(con, "data_mode", "real") or "real"


def effective_now(con, now: datetime | None = None) -> datetime:
    """Synthetic databases have a pinned 'now' so the demo has an upcoming slate."""
    if now is not None:
        return now
    if data_mode(con) == "synthetic":
        return datetime.fromisoformat(db.get_meta(con, "synthetic_now"))
    return utcnow()


def next_slate(con, now: datetime) -> tuple[int, int] | None:
    row = con.execute("""SELECT season, week FROM games WHERE game_status = 'scheduled' AND kickoff_utc > ?
                         ORDER BY kickoff_utc LIMIT 1""", [now]).fetchone()
    return (int(row[0]), int(row[1])) if row else None


# ---------------------------------------------------------------- training
@dataclass
class ProductionModel:
    models: FittedModels
    calibrators: dict
    weights: dict
    weights_source: str
    model_version: str
    trained_through: str
    feature_columns: list


def train_production(con, cfg: dict, now: datetime, features: pd.DataFrame | None = None,
                     save: bool = True) -> ProductionModel:
    games, stats, odds = load_inputs(con)
    if features is None:
        features = build_features(games, stats, odds, cfg, as_of=pd.Timestamp(now), **load_football_inputs(con))
    fs = FeatureSettings.from_config(cfg["features"])
    cols = model_feature_columns(fs)
    done = features[(features["game_status"] == "final") & (features["kickoff_utc"] < pd.Timestamp(now))]
    if done["season"].nunique() < 2:
        raise RuntimeError("Need at least two seasons of completed games to train.")
    current = int(done["season"].max())
    # validation = the most recent completed data; earlier seasons are training
    split = current - 1 if done[done.season == current].shape[0] < 100 else current
    train, valid = done[done["season"] < split], done[done["season"] >= split]
    models = tune_and_fit(train, valid, cols, cfg)

    meta, bt = latest_backtest(con)
    calibrators, weights, wsrc = {}, weights_from_config(cfg["blend"]), "fixed (config)"
    if meta is not None and len(bt):
        d = bt[bt["home_result"].isin([0.0, 1.0])].sort_values("kickoff_utc")
        for comp in ("logistic", "gbm"):
            if d[f"{comp}_raw"].notna().sum() >= 200:
                calibrators[comp] = choose_calibration(d[f"{comp}_raw"], d["home_result"],
                                                       cfg["models"]["calibration"])
        if cfg["blend"]["mode"] == "learned":
            try:
                weights, _ = learn_weights(d, components=cfg["blend"].get("learned_components"), step=float(cfg["blend"].get("learned_step", 0.1)),
                                           space=cfg["blend"]["space"])
                wsrc = f"learned from backtest {meta['backtest_id']}"
            except ValueError as exc:
                log.warning("Using fixed weights: %s", exc)
    models.calibrators = calibrators
    h = hashlib.sha1(json.dumps({"cfg": cfg, "params": models.params, "through": str(done.kickoff_utc.max())},
                                sort_keys=True, default=str).encode()).hexdigest()[:8]
    version = f"v{__version__}-{done.kickoff_utc.max():%Y%m%d}-{h}"
    pm = ProductionModel(models, {k: c.method for k, c in calibrators.items()}, weights, wsrc, version,
                         str(done.kickoff_utc.max()), cols)
    if save:
        mdir = resolve_path(cfg["data"]["model_dir"])
        mdir.mkdir(parents=True, exist_ok=True)
        joblib.dump(pm, mdir / f"{version}.joblib")
        joblib.dump(pm, mdir / "latest.joblib")
    return pm


def load_latest_model(cfg: dict) -> ProductionModel | None:
    p = resolve_path(cfg["data"]["model_dir"]) / "latest.joblib"
    return joblib.load(p) if p.exists() else None


# -------------------------------------------------------------- prediction
def predict_week(con, cfg: dict, season: int | None = None, week: int | None = None,
                 now: datetime | None = None, model: ProductionModel | None = None,
                 save: bool = True, retrain: bool = True) -> tuple[str | None, pd.DataFrame]:
    """Predict a slate and allocate confidence points. Returns (run_id, picks)."""
    now = effective_now(con, now)
    if season is None or week is None:
        nxt = next_slate(con, now)
        if nxt is None:
            raise RuntimeError("No upcoming scheduled games found. Update the schedule or pass --season/--week.")
        season, week = nxt
    games, stats, odds = load_inputs(con)
    # A past week is re-predicted as of its own cutoff so later results cannot leak in.
    wk = games[(games["season"] == season) & (games["week"] == week)]
    if wk.empty:
        raise RuntimeError(f"No games for season {season} week {week}")
    slate_cut = wk["kickoff_utc"].min() - pd.Timedelta(hours=float(cfg["pool"]["cutoff_offset_hours"]))
    if pd.Timestamp(now) > slate_cut:
        now = pd.Timestamp(slate_cut).to_pydatetime()
        model = None if model is None or retrain else model
    feats = build_features(games, stats, odds, cfg, as_of=pd.Timestamp(now), **load_football_inputs(con))
    validate_point_in_time(feats)
    if model is None:
        model = (None if retrain else load_latest_model(cfg)) or train_production(con, cfg, now, feats)
    slate = feats[(feats["season"] == season) & (feats["week"] == week)].copy()
    if slate.empty:
        raise RuntimeError(f"No games for season {season} week {week}")
    probs = model.models.predict(slate)
    slate["market_home_probability"] = slate["market_home_prob"]
    slate["elo_home_probability"] = slate["elo_home_prob"]
    slate["logistic_home_probability"] = probs["logistic"]
    slate["gradient_boosting_home_probability"] = probs["gbm"]
    slate["residual_home_probability"] = probs.get("residual", np.full(len(slate), np.nan))
    comp = pd.DataFrame({"market": slate["market_home_prob"].to_numpy(), "elo": slate["elo_home_prob"].to_numpy(),
                         "logistic": probs["logistic"], "gbm": probs["gbm"],
                         "residual": slate["residual_home_probability"].to_numpy()})
    slate["blended_home_probability"] = blend_with_fallback(comp, model.weights, cfg["blend"]["space"])
    slate["injury_status"] = injury_status(con, slate)
    slate["data_flags"] = data_flags(slate)
    rules = ScoringRules.from_config(cfg["pool"])
    # Standard pool: every game of the week is picked before the slate cutoff, so all are eligible.
    pick_col = PICK_SOURCES.get(cfg["models"].get("pick_model", "blend"), "blended_home_probability")
    if rules.line_rule == "acql":
        from . import poollines
        slate = slate.drop(columns=[c for c in ("pool_line_team", "pool_line", "line_source") if c in slate])
        slate = slate.merge(poollines.lines_for_slate(con, slate, cfg["pool"]), on="game_id", how="left")
        slate["credited_home_probability"] = poollines.apply(slate, pick_col).to_numpy()
        slate["data_flags"] = [f if s != "estimated" else ("POOL_LINE_ESTIMATED" if f == "ok" else f + ", POOL_LINE_ESTIMATED")
                               for f, s in zip(slate["data_flags"], slate["line_source"])]
        pick_col = "credited_home_probability"
    picks = allocate(slate, rules, prob_col=pick_col)
    validate_allocation(picks, rules)
    data_cutoff = pd.Timestamp(slate["cutoff"].min()).to_pydatetime()
    picks["generated_at"] = utcnow()
    picks["model_version"] = model.model_version
    run_id = None
    from .reports import build_reports, save_reports
    inj = con.execute("SELECT * FROM injuries WHERE season = ? AND week = ?", [season, week]).df()
    reports = build_reports(slate, picks, feats[feats["game_status"] == "final"], inj)
    picks.attrs["reports"] = reports
    if save:
        run_id = save_run(con, picks, season, week, data_cutoff, model, cfg)
        save_team_features(con, slate, model.model_version)
        save_reports(con, run_id, reports)
    picks["run_id"] = run_id
    return run_id, picks


def injury_status(con, slate: pd.DataFrame) -> list[str]:
    """QB injury-report status per game from the injuries table, if any was ingested."""
    out = []
    for r in slate.itertuples(index=False):
        rows = con.execute("""SELECT team, player_name, report_status FROM injuries
                              WHERE season = ? AND week = ? AND team IN (?, ?) AND position = 'QB'
                              AND report_status IS NOT NULL""",
                           [int(r.season), int(r.week), r.home_team, r.away_team]).fetchall()
        has_data = con.execute("SELECT count(*) FROM injuries WHERE season = ? AND week = ?",
                               [int(r.season), int(r.week)]).fetchone()[0]
        if not has_data:
            out.append("no injury data")
        elif not rows:
            out.append("no QB designations")
        else:
            out.append("; ".join(f"{t} {n}: {s}" for t, n, s in rows))
    return out


def data_flags(slate: pd.DataFrame) -> list[str]:
    flags = []
    for r in slate.itertuples(index=False):
        f = []
        if r.odds_status == "missing":
            f.append("NO_ODDS (blend uses models only - lower data coverage)")
        elif r.odds_status == "stale":
            f.append("STALE_ODDS")
        elif r.odds_status == "closing_proxy":
            f.append("CLOSING_LINE_PROXY")
        if r.home_quarterback_status == "unknown" or r.away_quarterback_status == "unknown":
            f.append("QB_UNKNOWN")
        if r.early_season:
            f.append("EARLY_SEASON")
        if pd.isna(r.home_feature_ts) or pd.isna(r.away_feature_ts):
            f.append("NO_TEAM_HISTORY")
        if isinstance(r.injury_status, str) and any(s in r.injury_status for s in ("Out", "Doubtful")):
            f.append("QB_INJURY_REPORTED")
        flags.append(", ".join(f) if f else "ok")
    return flags


PRED_COLUMNS = [
    "run_id", "game_id", "generated_at", "model_version", "season", "week", "home_team", "away_team",
    "kickoff_utc", "market_home_probability", "elo_home_probability", "logistic_home_probability",
    "gradient_boosting_home_probability", "residual_home_probability", "blended_home_probability", "selected_team",
    "selected_team_probability", "confidence_points", "expected_points", "pool_line_team", "pool_line",
    "line_source", "credited_home_probability", "odds_captured_at",
    "odds_status", "injury_status", "data_flags",
]


def save_run(con, picks: pd.DataFrame, season: int, week: int, data_cutoff: datetime,
             model: ProductionModel, cfg: dict, run_id: str | None = None) -> str:
    run_id = run_id or f"run_{utcnow():%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}"
    if con.execute("SELECT count(*) FROM prediction_runs WHERE run_id = ?", [run_id]).fetchone()[0]:
        raise FrozenRunError(f"Run {run_id} already exists; prediction runs are insert-only")
    generated = picks["generated_at"].iloc[0]
    con.execute("INSERT INTO prediction_runs VALUES (?, ?, ?, ?, ?, ?, ?, FALSE, NULL, ?, ?)",
                [run_id, generated, data_cutoff, season, week, model.model_version,
                 json.dumps({"blend": cfg["blend"], "pool": cfg["pool"], "weights": model.weights,
                             "weights_source": model.weights_source, "calibration": model.calibrators},
                            default=str),
                 data_mode(con), f"trained through {model.trained_through}"])
    d = picks.assign(run_id=run_id)
    db.upsert(con, "predictions", d, PRED_COLUMNS)
    return run_id


def freeze_run(con, run_id: str) -> None:
    row = con.execute("SELECT frozen FROM prediction_runs WHERE run_id = ?", [run_id]).fetchone()
    if row is None:
        raise KeyError(f"Unknown run {run_id}")
    if row[0]:
        return  # idempotent
    con.execute("UPDATE prediction_runs SET frozen = TRUE, frozen_at = ? WHERE run_id = ?", [utcnow(), run_id])


def assert_not_frozen(con, run_id: str) -> None:
    row = con.execute("SELECT frozen FROM prediction_runs WHERE run_id = ?", [run_id]).fetchone()
    if row and row[0]:
        raise FrozenRunError(f"Run {run_id} is frozen (submitted) and cannot be changed")


def delete_run(con, run_id: str) -> None:
    """Delete an unfrozen draft run. Frozen runs are permanent."""
    assert_not_frozen(con, run_id)
    con.execute("DELETE FROM predictions WHERE run_id = ?", [run_id])
    con.execute("DELETE FROM prediction_runs WHERE run_id = ?", [run_id])


def get_run(con, run_id: str) -> pd.DataFrame:
    return con.execute("SELECT * FROM predictions WHERE run_id = ? ORDER BY confidence_points DESC",
                       [run_id]).df()


def list_runs(con, season: int | None = None, week: int | None = None) -> pd.DataFrame:
    q, args = "SELECT * FROM prediction_runs WHERE 1=1", []
    if season is not None:
        q += " AND season = ?"
        args.append(int(season))
    if week is not None:
        q += " AND week = ?"
        args.append(int(week))
    return con.execute(q + " ORDER BY generated_at DESC", args).df()


def submitted_run(con, season: int, week: int) -> str | None:
    row = con.execute("""SELECT run_id FROM prediction_runs WHERE season=? AND week=? AND frozen
                         ORDER BY frozen_at DESC LIMIT 1""", [season, week]).fetchone()
    return row[0] if row else None


EXPORT_COLUMNS = [
    "season", "week", "game_id", "kickoff_utc", "away_team", "home_team", "selected_team",
    "confidence_points", "selected_team_probability", "expected_points", "pool_line_team", "pool_line",
    "line_source", "blended_home_probability",
    "market_home_probability", "elo_home_probability", "logistic_home_probability",
    "gradient_boosting_home_probability", "odds_status", "odds_captured_at", "injury_status", "data_flags",
    "model_version", "generated_at", "run_id",
]


def export_csv(picks: pd.DataFrame, path: Path, data_label: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = picks.reindex(columns=EXPORT_COLUMNS).sort_values("confidence_points", ascending=False)
    out.insert(0, "data_label", data_label)
    out.to_csv(path, index=False, float_format="%.4f")
    return path


# ---------------------------------------------------------------- grading
def grade_week(con, cfg: dict, season: int, week: int, run_id: str | None = None) -> pd.DataFrame:
    """Grade the submitted (frozen) run for a week into pool_results (idempotent)."""
    run_id = run_id or submitted_run(con, season, week)
    if run_id is None:
        raise RuntimeError(f"No frozen (submitted) run for {season} week {week}; freeze one first")
    picks = get_run(con, run_id)
    results = con.execute("SELECT game_id, home_score, away_score, game_status FROM games WHERE season=? AND week=?",
                          [season, week]).df()
    rules = ScoringRules.from_config(cfg["pool"])
    if rules.line_rule == "acql":
        # The commissioner's posted line is what gets graded, even if the run used an estimate.
        from . import poollines
        posted = poollines.entered(con, season, week).set_index("game_id")
        if len(posted):
            picks = picks.copy()
            hit = picks["game_id"].isin(posted.index)
            picks.loc[hit, "pool_line_team"] = picks.loc[hit, "game_id"].map(posted["favourite_team"])
            picks.loc[hit, "pool_line"] = picks.loc[hit, "game_id"].map(posted["line"])
    g = grade_sheet(picks, results, rules)
    pool_id = cfg["pool"]["pool_id"]
    out = pd.DataFrame({"pool_id": pool_id, "season": season, "week": week, "game_id": g["game_id"],
                        "run_id": run_id, "selected_team": g["selected_team"],
                        "confidence_points": g["confidence_points"], "actual_result": g["actual_result"],
                        "points_earned": g["points_earned"], "graded_at": utcnow()})
    db.upsert(con, "pool_results", out, list(out.columns))
    return out


def grade_all(con, cfg: dict) -> int:
    weeks = con.execute("SELECT DISTINCT season, week FROM prediction_runs WHERE frozen").fetchall()
    n = 0
    for s, w in weeks:
        grade_week(con, cfg, int(s), int(w))
        n += 1
    return n


def season_tracker(con, pool_id: str, season: int | None = None) -> pd.DataFrame:
    q = """SELECT season, week, sum(points_earned) AS points, sum(confidence_points) AS max_points,
                  sum(CASE WHEN actual_result='win' THEN 1 ELSE 0 END) AS correct,
                  sum(CASE WHEN actual_result IN ('win','loss','tie') THEN 1 ELSE 0 END) AS decided,
                  sum(CASE WHEN actual_result='pending' THEN 1 ELSE 0 END) AS pending
           FROM pool_results WHERE pool_id = ?"""
    args: list = [pool_id]
    if season is not None:
        q += " AND season = ?"
        args.append(season)
    df = con.execute(q + " GROUP BY 1, 2 ORDER BY 1, 2", args).df()
    if len(df):
        df["accuracy"] = df["correct"] / df["decided"].replace(0, np.nan)
        df["cumulative_points"] = df.groupby("season")["points"].cumsum()
    return df


def import_pool_scores(con, df: pd.DataFrame, pool_id: str) -> int:
    """Import competitor weekly scores: columns season, week, participant, points[, is_me]."""
    need = {"season", "week", "participant", "points"}
    if not need.issubset(df.columns):
        raise ValueError(f"Pool score CSV needs columns {sorted(need)}")
    d = df.copy()
    d["pool_id"] = pool_id
    d["is_me"] = d.get("is_me", False)
    d["is_me"] = d["is_me"].fillna(False).astype(bool)
    return db.upsert(con, "pool_scores", d, ["pool_id", "season", "week", "participant", "points", "is_me"])


# ------------------------------------------------------------ automation
def update_data(con, cfg: dict, seasons: list[int] | None = None, now: datetime | None = None) -> dict:
    """Refresh schedules/results/lines, play-by-play and injuries (real-data mode)."""
    from .ingest import nflverse
    from .ingest.providers import ProviderUnavailable, get_odds_provider

    if data_mode(con) == "synthetic":
        return {"skipped": "synthetic database - nothing to update"}
    report = {}
    games = nflverse.ingest_schedule(con, int(cfg["data"]["first_season"]), now=now)
    current = int(games.loc[games["kickoff_utc"] <= pd.Timestamp(now or utcnow()), "season"].max())
    seasons = seasons or [current]
    report["games"] = len(games)
    report["pbp_rows"] = nflverse.ingest_pbp(con, seasons, resolve_path(cfg["data"]["cache_dir"]))
    if cfg["data"].get("odds_provider", "nflverse") != "nflverse":
        try:
            prov = get_odds_provider(cfg["data"]["odds_provider"])
            upcoming = games[games["game_status"] == "scheduled"]
            report["odds_rows"] = db.upsert_odds(con, prov.fetch(upcoming))
        except ProviderUnavailable as exc:
            report["odds_error"] = str(exc)
            log.warning("Odds provider unavailable: %s (falling back to nflverse lines)", exc)
    if cfg["data"].get("injury_provider") == "nflverse":
        report["injury_rows"] = nflverse.ingest_injuries(con, current)
    db.set_meta(con, "data_mode", "real")
    db.set_meta(con, "last_update", utcnow().isoformat())
    return report


def run_weekly(con, cfg: dict, freeze: bool = False, update: bool = True,
               export_dir: Path | None = None, now: datetime | None = None) -> dict:
    """The full weekly job: update -> grade finished weeks -> predict -> export (-> freeze)."""
    report: dict = {}
    if update:
        report["update"] = update_data(con, cfg, now=now)
    report["graded_weeks"] = grade_all(con, cfg)
    run_id, picks = predict_week(con, cfg, now=now)
    report["run_id"] = run_id
    season, week = int(picks["season"].iloc[0]), int(picks["week"].iloc[0])
    if freeze:
        if submitted_run(con, season, week):
            report["freeze"] = "skipped: a frozen submission already exists for this week"
        else:
            freeze_run(con, run_id)
            report["freeze"] = run_id
    label = "SYNTHETIC DEMO - NOT REAL NFL" if data_mode(con) == "synthetic" else "nflverse data"
    export_dir = export_dir or resolve_path(cfg["data"]["export_dir"])
    path = export_csv(picks, Path(export_dir) / f"picks_{season}_wk{week:02d}_{run_id}.csv", label)
    report["export"] = str(path)
    report["season"], report["week"] = season, week
    return report
