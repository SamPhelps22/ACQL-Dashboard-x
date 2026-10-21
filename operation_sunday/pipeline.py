"""The weekly job: ingest -> validate -> features -> train -> validate models
-> select -> forecast -> verify -> lock -> record results.

`run_week` can be pointed at any moment in the past ("now"): every result
published after that moment is hidden first, so a historical Thursday can be
replayed exactly as it would have run.
"""

from __future__ import annotations

import json
import math
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import data as data_mod
from .acql_rules import credited_home_prob, pool_line_for
from .backtest import HoldoutGuard, attach_outcomes, eval_week_keys, training_rows, walk_forward
from .config import Settings
from .ensemble import ENSEMBLES, ensemble_walk_forward, live_weights, combine
from .features import FEATURE_VERSION, MarketSnapshot, build_features
from .journal import Journal, LockError
from .models import base_candidates, build, logit
from .registry import Registry, code_revision
from .schedule import deadline_for, next_week, timing
from .selection import add_slices, decide
from .tz import iso, utc_now


@dataclass
class RunResult:
    season: int
    week: int
    status: str
    package_id: str | None = None
    lock: dict | None = None
    decision: dict | None = None
    experiment_id: str | None = None
    alerts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    report_path: str | None = None


def as_of(games: pd.DataFrame, now: datetime, settings: Settings) -> pd.DataFrame:
    """Hide every result not yet published at `now`."""
    g = games.copy()
    hidden = (g["status"] == "final") & (g["kickoff_utc"] + pd.Timedelta(hours=settings.result_delay_hours) > pd.Timestamp(now))
    g.loc[hidden, ["home_score", "away_score"]] = np.nan
    g.loc[hidden, "status"] = "scheduled"
    return g


def _ingest(settings: Settings, games_csv, fetch: bool, journal: Journal, warnings: list, now: datetime):
    cache = settings.state_path / "cache" / "games.csv"
    if games_csv:
        return data_mod.load_csv(games_csv, now)
    if fetch:
        try:
            data_mod.fetch(settings.games_csv_url, cache)
        except Exception as exc:  # noqa: BLE001
            msg = f"INGEST FAILED ({type(exc).__name__}: {exc}); "
            if cache.exists():
                msg += "using the cached copy - data may be stale"
                warnings.append(msg)
                journal.alert(None, None, "ingest", msg)
            else:
                raise RuntimeError(msg + "and no cached copy exists") from exc
    if not cache.exists():
        raise RuntimeError(f"no game data: {cache} missing (run with fetch, or pass --games)")
    return data_mod.load_csv(cache, now)


def candidate_meta(models) -> dict:
    meta = {m.name: {"kind": m.kind, "thursday_eligible": m.thursday_eligible, "label": m.label} for m in models}
    for name, (_, comps, eligible) in ENSEMBLES.items():
        meta[name] = {"kind": "ensemble", "thursday_eligible": eligible, "label": f"ensemble of {comps}"}
    return meta


def evaluate(feats: pd.DataFrame, settings: Settings, week_keys: list, guard=None, unlock_reason=None):
    models = base_candidates()
    preds = walk_forward(feats, models, week_keys, settings, guard, unlock_reason)
    scored = attach_outcomes(preds, feats)
    ens, weights = ensemble_walk_forward(scored, settings.holdout_seasons)
    if len(ens):
        scored = pd.concat([scored, attach_outcomes(ens, feats)], ignore_index=True)
    return scored, weights, models


def selection_weeks(feats: pd.DataFrame, settings: Settings, season: int, target_cutoff) -> list:
    keys = eval_week_keys(feats, settings.dev_eval_seasons)
    if season not in settings.holdout_seasons and season not in settings.dev_eval_seasons:
        live = feats[(feats["season"] == season) & (feats["game_type"] == "REG")
                     & (feats["cutoff_utc"] < target_cutoff)]
        keys += list(dict.fromkeys(live.sort_values("cutoff_utc")["week_key"]))
    return keys


def _predict_live(name: str, feats, week_rows, cutoff, scored, settings, registry, dataset_version):
    """Fit `name` on everything published by the cutoff and predict the slate."""
    train = training_rows(feats, cutoff)
    if name in ENSEMBLES:
        method, comps, _ = ENSEMBLES[name]
        comp_preds = {}
        for c in comps:
            m = build(c).fit(train)
            comp_preds[c] = m.predict(week_rows)["p_home"]
        frame = pd.DataFrame(comp_preds)
        w, n = live_weights(scored, name, settings.holdout_seasons)
        if w is None or frame.isna().any().any():
            raise RuntimeError(f"{name}: components unavailable for this slate")
        p = combine(w, frame, comps)
        state = {"intercept": float(w[1][0]), "weights": np.round(w[1][1:], 6).tolist(), "oof_games": n, "components": comps}
        out = pd.DataFrame({"p_home": p, "exp_margin": np.nan, "exp_total": np.nan}, index=week_rows.index)
        config = {"name": name, "method": method, "components": comps, "feature_version": FEATURE_VERSION}
    else:
        m = build(name).fit(train)
        out = m.predict(week_rows)
        state, config = m.state(), m.config()
    if out["p_home"].isna().any():
        raise RuntimeError(f"{name} produced no probability for {int(out['p_home'].isna().sum())} games")
    version = registry.save_artifact(name, config, state, iso(pd.Timestamp(cutoff).to_pydatetime()), dataset_version)
    return out, version, len(train)


def run_week(settings: Settings, season: int | None = None, week: int | None = None,
             now: datetime | None = None, games_csv=None, fetch: bool = True,
             snapshots: list[MarketSnapshot] | None = None, lock: bool = True,
             game_type: str = "REG", write_report: bool = True,
             fail_stage: str | None = None, dataset: data_mod.Dataset | None = None) -> RunResult:
    real = utc_now()
    now = now or real
    mode = "live" if abs((now - real).total_seconds()) <= 300 else "replay"
    state = settings.state_path
    journal = Journal(state / "journal.sqlite")
    registry = Registry(state)
    run_id = uuid.uuid4().hex[:12]
    warnings: list[str] = []
    res = RunResult(season or 0, week or 0, "started")

    def stage(name, status, detail=None):
        journal.stage(run_id, res.season, res.week, name, status, detail)
        if fail_stage == name and status == "running":
            raise RuntimeError(f"simulated failure in stage {name}")

    try:
        stage("ingest", "running")
        ds = dataset if dataset is not None else _ingest(settings, games_csv, fetch, journal, warnings, now)
        stage("ingest", "done", ds.version)

        stage("validate", "running")
        warnings += ds.warnings
        games = as_of(ds.games, now, settings)
        age_h = (now - ds.loaded_at).total_seconds() / 3600
        if age_h > settings.stale_after_hours:
            warnings.append(f"STALE DATA: game file last updated {age_h:.0f} h before this run")
        if season is None or week is None:
            d = next_week(games, now, settings)
            if d is None:
                raise RuntimeError("no upcoming week found in the data")
        else:
            d = deadline_for(games, season, week, settings, game_type)
        res.season, res.week = d.season, d.week
        n_int = journal.mark_interrupted(d.season, d.week)
        if n_int:
            warnings.append(f"recovered from {n_int} interrupted stage(s) of an earlier run")
        t = timing(d, now)
        if t.alert:
            journal.alert(d.season, d.week, t.status, t.alert)
            res.alerts.append(t.alert)
        stage("validate", "done", json.dumps({"deadline": d.as_dict(), "timing": t.status}))

        existing = journal.package(d.season, d.week, d.game_type, 0)
        if existing and existing["status"] == "locked":
            res.status, res.package_id = "already_locked", existing["package_id"]
            _record_results(journal, ds.games, now, settings, d.season)
            res.warnings = warnings
            return res

        stage("features", "running")
        snapshots = list(snapshots or [])
        archived = journal_snapshots(journal)
        feats = build_features(games, settings, archived + snapshots)
        target = feats[(feats["season"] == d.season) & (feats["week"] == d.week)
                       & ((feats["game_type"] == "REG") == (d.game_type == "REG"))]
        started = target[target["kickoff_utc"] <= pd.Timestamp(now)]
        if len(started):
            msg = (f"{len(started)} game(s) already kicked off and get NO forecast from this run: "
                   f"{list(started['game_id'])}")
            journal.alert(d.season, d.week, "late", msg)
            res.alerts.append(msg)
            target = target[target["kickoff_utc"] > pd.Timestamp(now)]
        if target.empty:
            raise RuntimeError("every game of the week has already kicked off; nothing can be forecast")
        cutoff = d.lock_utc
        stage("features", "done", f"{len(feats)} rows, {FEATURE_VERSION}")

        stage("train", "running")
        guard = HoldoutGuard(settings)
        keys = selection_weeks(feats, settings, d.season, pd.Timestamp(cutoff))
        stage("train", "done", f"{len(keys)} walk-forward weeks")

        stage("validate_models", "running")
        scored, ens_weights, models = evaluate(feats, settings, keys, guard)
        scored = add_slices(scored, feats)
        stage("validate_models", "done", f"{scored['game_id'].nunique()} games scored")

        stage("select", "running")
        approved = registry.approved()
        incumbent = approved["model"] if approved and approved.get("model") else None
        meta = candidate_meta(models)
        meta = {k: v for k, v in meta.items() if k in set(scored["model"])}
        decision = decide(scored, meta, incumbent, settings.designated_baseline, settings.promotion, settings.seed)
        exp = {
            "kind": "weekly_selection", "season": d.season, "week": d.week,
            "dataset_version": ds.version, "dataset_source": ds.source, "feature_version": FEATURE_VERSION,
            "training_cutoff": iso(cutoff), "seed": settings.seed, "code_revision": code_revision(),
            "validation_weeks": [list(map(str, k)) for k in keys],
            "models": {m.name: m.config() for m in models}, "ensemble_weights": ens_weights,
            "decision": {k: v for k, v in decision.items() if k != "candidates"},
            "candidates": [{k: v for k, v in c.items()} for c in decision["candidates"]],
            "data_warnings": warnings, "holdout_seasons": list(settings.holdout_seasons),
            "holdout_viewings": guard.viewings(),
        }
        res.experiment_id = registry.record_experiment(exp)
        if decision["action"] == "promote":
            registry.promote(decision["model"], res.experiment_id, decision["reason"])
        res.decision = decision
        stage("select", "done", decision["action"] + ":" + decision["model"])

        stage("forecast", "running")
        chosen, fallback = decision["model"], None
        try:
            out, version, ntrain = _predict_live(chosen, feats, target, cutoff, scored, settings, registry, ds.version)
        except Exception as exc:  # noqa: BLE001 - never miss the deadline over one model
            fallback = (f"{chosen} failed ({exc}); designated baseline {settings.designated_baseline} used")
            warnings.append("FALLBACK: " + fallback)
            journal.alert(d.season, d.week, "fallback", fallback)
            chosen = settings.designated_baseline
            out, version, ntrain = _predict_live(chosen, feats, target, cutoff, scored, settings, registry, ds.version)
        if decision["action"] == "fallback":
            fallback = fallback or decision["reason"]
        created = iso(utc_now() if mode == "live" else now)
        rows = []
        snaps = {s.game_id: s for s in sorted(snapshots, key=lambda s: s.taken_at) if s.taken_at <= cutoff}
        for i, r in target.iterrows():
            p = float(out.loc[i, "p_home"])
            snap = snaps.get(r.game_id)
            line_spread = snap.home_spread if snap and snap.home_spread is not None else None
            flags = list(r.missing_flags)
            if line_spread is None:
                flags.append("pool_line_unknown_no_spread_at_cutoff")
            pc = credited_home_prob(p, line_spread)
            rows.append({
                "season": int(r.season), "week": int(r.week), "game_id": r.game_id, "home": r.home, "away": r.away,
                "kickoff_utc": iso(r.kickoff_utc.to_pydatetime()), "created_at": created, "cutoff_utc": iso(cutoff),
                "model_name": chosen, "model_version": version, "training_cutoff": iso(cutoff),
                "feature_cutoff": iso(r.feature_cutoff_utc.to_pydatetime()),
                "market_ts": iso(r.market_ts) if r.market_ts is not None and not pd.isna(r.market_ts) else None,
                "p_home": p, "p_away": 1.0 - p,
                "exp_margin": float(out.loc[i, "exp_margin"]), "exp_total": float(out.loc[i, "exp_total"]),
                "provenance_json": json.dumps({"dataset_version": ds.version, "source": ds.source,
                                               "feature_version": FEATURE_VERSION, "train_games": ntrain,
                                               "families_used": "see model config",
                                               "excluded": ["qb", "injuries", "weather", "closing line"]}),
                "missing_flags_json": json.dumps(flags), "selection_decision": decision["action"],
                "pick": r.home if pc >= 0.5 else r.away, "p_pick_credited": max(pc, 1 - pc),
                "pool_line": pool_line_for(line_spread),
            })
        header = {"model_name": chosen, "model_version": version, "fallback": fallback,
                  "selection": {k: v for k, v in decision.items() if k != "candidates"},
                  "market_snapshot": {g: {"taken_at": iso(s.taken_at), "home_prob": s.home_prob,
                                          "home_spread": s.home_spread, "source": s.source}
                                      for g, s in snaps.items()}}
        pid = journal.save_draft(d.season, d.week, d.game_type, d.lock_utc, header, rows, mode=mode,
                                 now=None if mode == "live" else now)
        res.package_id = pid
        stage("forecast", "done", pid)

        stage("verify", "running")
        scheduled = list(target["game_id"])
        problems = journal.verify(pid, scheduled)
        if problems:
            raise LockError("; ".join(problems))
        stage("verify", "done")

        if lock:
            stage("lock", "running")
            res.lock = journal.lock(pid, scheduled, None if mode == "live" else now)
            if res.lock["late_alert"]:
                res.alerts.append(res.lock["late_alert"])
            stage("lock", "done", res.lock["content_hash"])

        stage("record_results", "running")
        n = _record_results(journal, ds.games, now, settings, d.season)
        stage("record_results", "done", f"{n} new results queued for the next cycle")
        res.status = "locked" if lock else "draft"
        res.warnings = warnings
        if write_report:
            from .report import weekly_report
            res.report_path = str(weekly_report(settings, journal, registry, res, scored, feats, d))
        return res
    except Exception as exc:
        journal.alert(res.season, res.week, "error", f"{type(exc).__name__}: {exc}")
        for r in journal.interrupted_runs(res.season, res.week):
            if r["run_id"] == run_id:
                journal.stage(run_id, res.season, res.week, r["stage"], "failed", traceback.format_exc()[-2000:])
        raise
    finally:
        journal.close()


def journal_snapshots(journal: Journal) -> list[MarketSnapshot]:
    """Thursday market snapshots stored in earlier OFFICIAL locked packages.
    Each was at or before its own cutoff when locked, so the walk-forward can
    score the market as it stood on Thursday - evidence that builds week by week."""
    out = []
    for p in journal.packages():
        if p["status"] != "locked" or p["revision"] != 0 or p["mode"] != "live":
            continue
        for gid, s in json.loads(p["market_snapshot_json"] or "{}").items():
            out.append(MarketSnapshot(gid, datetime.fromisoformat(s["taken_at"]), s.get("home_prob"),
                                      s.get("home_spread"), s.get("source", "") + " (journal)"))
    return out


def _record_results(journal: Journal, games: pd.DataFrame, now, settings, season: int) -> int:
    done = as_of(games, now, settings)
    done = done[done["status"] == "final"]
    n = 0
    for r in done.itertuples():
        if r.season >= season - 1:
            n += journal.record_result(r.game_id, int(r.season), int(r.week), float(r.home_score), float(r.away_score))
    return n
