"""Evaluate one split: capture every source, then (only then) join results and score.

Writes challenger/results/<split>/: REPORT.md, the tables as CSV, summary.json,
and the captured Deadeye/market forecasts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .. import data, metrics, predictions
from ..config import RESULTS
from . import deadeye, headtohead as h2h, market, pool

log = logging.getLogger("challenger.arena")

CHALLENGER_MODELS = ["challenger", "elo", "logistic", "boosting"]
DEADEYE_MODELS = ["deadeye_proxy", "deadeye_core_closing"]
MARKET_MODELS = ["market_moneyline", "market_spread"]
MAIN = CHALLENGER_MODELS + DEADEYE_MODELS + MARKET_MODELS
ACQL_MODELS = ["challenger", "elo", "logistic", "boosting", "deadeye_proxy", "deadeye_core_closing",
               "market_spread_line", "home_team"]
PAIRS = [("challenger", "deadeye_proxy"), ("challenger", "deadeye_core_closing"), ("challenger", "market_moneyline"),
         ("challenger", "market_spread"), ("challenger", "elo"), ("challenger", "logistic"), ("challenger", "boosting"),
         ("boosting", "logistic"), ("deadeye_proxy", "market_moneyline"), ("deadeye_core_closing", "market_moneyline")]

LABELS = {
    "challenger": "Challenger (market-free stack)",
    "elo": "Challenger Elo baseline",
    "logistic": "Challenger logistic regression",
    "boosting": "Challenger gradient boosting",
    "deadeye_proxy": "Deadeye historical proxy (its own backtest model)",
    "deadeye_core_closing": "Deadeye curve on closing spread (no model nudge)",
    "deadeye_live": "Deadeye live rule (2026 weekly files)",
    "market_moneyline": "Market: de-vigged closing moneyline",
    "market_spread": "Market: closing spread -> logistic",
    "market_spread_line": "Market: closing spread (normal margin)",
    "home_team": "Simple baseline: always the home team",
}


def latest_run(split: str, variant: str = "market_free") -> Path | None:
    folder = RESULTS / "backtests"
    found = sorted(folder.glob(f"predictions_{variant}_{split}_*.csv.gz"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def _challenger(path: Path) -> tuple[pd.DataFrame, dict]:
    if not predictions.verify(path):
        raise RuntimeError(f"{path.name} no longer matches its recorded hash")
    manifest = json.loads(path.with_name(path.name.replace(".csv.gz", ".manifest.json")).read_text())
    return predictions.read(path), manifest


def capture(games: pd.DataFrame, seasons) -> tuple[pd.DataFrame, dict]:
    """Deadeye and market forecasts, each captured on its own (no results read)."""
    prox, prox_info = deadeye.proxy(games)
    core = deadeye.core_closing(games)
    live, live_notes = deadeye.live(games)
    ml = market.moneyline(games)
    sp = market.spread(games, sorted(set(seasons) | set(range(2006, max(seasons) + 1))))
    frames = [prox, core, live, ml, sp]
    out = pd.concat(frames, ignore_index=True, sort=False)
    return out, {"deadeye_proxy": prox_info, "deadeye_live": live_notes}


def _fmt_ci(ci: dict, scale: float = 1000.0, digits: int = 1) -> str:
    return f"{ci['mean'] * scale:+.{digits}f} [{ci['lo'] * scale:+.{digits}f}, {ci['hi'] * scale:+.{digits}f}]"


def evaluate(split: str, run_path: Path | None = None) -> dict:
    games = data.load_games()
    run_path = run_path or latest_run(split)
    if run_path is None:
        raise FileNotFoundError(f"no stored market-free backtest for split {split}")
    ch, manifest = _challenger(run_path)
    seasons = manifest["seasons"]
    others, info = capture(games, seasons)
    # extra Challenger variants, kept in their own section
    variants = {}
    for variant in ("market_informed", "no_epa"):
        p = latest_run(split, variant)
        if p is not None:
            variants[variant] = _challenger(p)[0]
    out_dir = RESULTS / split
    out_dir.mkdir(parents=True, exist_ok=True)
    others.to_csv(out_dir / "captured_deadeye_and_market.csv.gz", index=False, compression="gzip")
    forecasts = pd.concat([ch[["model", "game_id", "p_home"]], others], ignore_index=True, sort=False)

    # ---- probability head-to-head (regular season) ----------------------------------
    w, cov = h2h.matched_set(forecasts, games, MAIN, seasons=seasons)
    scores = h2h.score_table(w, MAIN)
    seasons_t = h2h.by_season(w, MAIN)
    pairs = []
    for a, b in PAIRS:
        for measure in ("log_loss", "brier", "accuracy"):
            ci = h2h.paired(w, a, b, measure)
            pairs.append({"a": a, "b": b, "measure": measure, **ci})
    pairs_t = pd.DataFrame(pairs)
    cal = h2h.calibration(w, MAIN)
    conf = h2h.by_confidence(w, MAIN)
    side = h2h.by_market_side(w, MAIN)
    weekly = h2h.by_week(w, MAIN)
    # per-season paired log-loss difference Challenger - Deadeye proxy
    season_pairs = []
    for season, part in w.groupby("season"):
        for b in ("deadeye_proxy", "market_moneyline"):
            ci = h2h.paired(part, "challenger", b, "log_loss")
            season_pairs.append({"season": season, "vs": b, **ci})
    season_pairs_t = pd.DataFrame(season_pairs)

    # ---- playoffs (Deadeye's proxy covers the regular season only) ------------------
    po_models = CHALLENGER_MODELS + MARKET_MODELS
    wpo, cov_po = h2h.matched_set(forecasts, games, po_models, seasons=seasons, game_types=("WC", "DIV", "CON", "SB"))
    po_scores = h2h.score_table(wpo, po_models) if len(wpo) else pd.DataFrame()

    # ---- Deadeye live (2026 weekly files only) -----------------------------------------
    live_t = pd.DataFrame()
    live_models = ["challenger", "deadeye_live", "deadeye_core_closing", "market_moneyline", "elo"]
    if 2026 in seasons:
        wl, cov_live = h2h.matched_set(forecasts, games, live_models, seasons=[2026])
        if len(wl):
            live_t = h2h.score_table(wl, live_models)
            live_pair = h2h.paired(wl, "challenger", "deadeye_live", "log_loss")
        else:
            live_pair = None
    else:
        cov_live, live_pair = {}, None

    # ---- variants (never mixed into the main table) ----------------------------------
    var_rows = []
    for variant, frame in variants.items():
        name = f"challenger__{variant}"
        f2 = pd.concat([forecasts, frame[frame["model"] == name][["model", "game_id", "p_home"]]], ignore_index=True)
        wv, _ = h2h.matched_set(f2, games, MAIN + [name], seasons=seasons)
        s = metrics.summary(wv[f"p_{name}"], wv["home_win"])
        row = {"variant": name, **s}
        for b in ("challenger", "deadeye_proxy", "market_moneyline"):
            ci = h2h.paired(wv, name, b, "log_loss")
            row[f"vs_{b}_logloss_x1000"] = _fmt_ci(ci)
            row[f"vs_{b}_verdict"] = ci["verdict"]
        var_rows.append(row)
    var_t = pd.DataFrame(var_rows)

    # ---- ACQL ---------------------------------------------------------------------------
    slates = pool.replay_slates(games, forecasts, ACQL_MODELS, seasons)
    acql_weeks, acql_info = pool.score_weeks(slates, ACQL_MODELS)
    acql_rows = []
    for m in ACQL_MODELS:
        pts = acql_weeks[f"acql_{m}"]
        row = {"model": m, "weeks": len(pts), "total_points": int(pts.sum()), "per_week": float(pts.mean()),
               "weekly_sd": float(pts.std()), "worst_week": int(pts.min()), "best_week": int(pts.max())}
        if f"confidence_{m}" in acql_weeks:
            row["confidence_points_total"] = float(acql_weeks[f"confidence_{m}"].sum())
        if m != "challenger":
            d = (acql_weeks["acql_challenger"] - pts).to_numpy(dtype=float)
            ci = metrics.bootstrap_paired(d, np.arange(len(d)))
            row["challenger_minus_this_per_week"] = _fmt_ci(ci, 1.0, 2)
        acql_rows.append(row)
    acql_t = pd.DataFrame(acql_rows)
    acql_season = acql_weeks.groupby("season")[[f"acql_{m}" for m in ACQL_MODELS]].sum().reset_index()
    # rank agreement: within each week, do two models order the games' home chances alike?
    mm = forecasts[forecasts["model"] == "market_moneyline"].drop_duplicates("game_id").set_index("game_id")["p_home"]
    slates["p_market_moneyline"] = slates["game_id"].map(mm)
    rank_corr = pd.DataFrame([
        {"a": a, "b": b, "mean_within_week_spearman":
         pool.rank_correlation(slates.dropna(subset=[f"p_{a}", f"p_{b}"]), a, b)}
        for a, b in (("challenger", "deadeye_proxy"), ("challenger", "deadeye_core_closing"),
                     ("challenger", "market_moneyline"), ("deadeye_proxy", "market_moneyline"), ("challenger", "elo"))])

    real = pool.real_weeks(games)
    real_in = [r for r in real if r["season"] in seasons]
    field_models = ["challenger", "deadeye_proxy", "deadeye_live", "deadeye_core_closing", "market_spread_line", "home_team"]
    field_t = pool.field_comparison(real_in, forecasts, field_models) if real_in else pd.DataFrame()

    # ---- write -----------------------------------------------------------------------
    tables = {"scores": scores, "by_season": seasons_t, "paired": pairs_t, "paired_by_season": season_pairs_t,
              "calibration": cal, "by_confidence": conf, "by_market_side": side, "by_week": weekly,
              "playoffs": po_scores, "deadeye_live_2026": live_t, "variants": var_t, "acql_summary": acql_t,
              "acql_by_season": acql_season, "acql_weeks": acql_weeks, "acql_rank_correlation": rank_corr,
              "acql_real_weeks": field_t}
    for name, t in tables.items():
        if isinstance(t, pd.DataFrame) and len(t):
            t.to_csv(out_dir / f"{name}.csv", index=False)
    summary = {"split": split, "seasons": seasons, "challenger_run": manifest["run_id"],
               "challenger_file_sha256": manifest["sha256"], "model_version": manifest["model_version"],
               "coverage": cov, "playoff_coverage": cov_po, "deadeye_live_coverage": cov_live,
               "deadeye_capture": info, "acql": acql_info,
               "live_pair_challenger_vs_deadeye_live": live_pair}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    from .report import write_report
    write_report(out_dir, split, summary, tables)
    return summary
