"""Prospective shadow forecasting: an append-only journal, graded after the games.

Rules:
  * a forecast is written only before its game's kickoff (checked against the clock);
  * an entry is never changed: the same (game, model, info set, version) is not written twice;
  * a correction is a NEW line with `revision` > 0 and `supersedes` naming the entry it corrects,
    plus a reason - the original stays;
  * grades go to a separate file, written only once a game is final;
  * nothing here writes to the dashboard, its database, or Deadeye's files.

Each forecast run stores, beside the lab's models:
  * the market snapshot it could see (nflverse games.csv lines at that file's fetch time), and
  * Deadeye's forecast if one can be captured (the recorded forecast log if present; otherwise the
    recomputation from the tracker file Deadeye was given) - in separate, labelled entries.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config, contract
from ..data import fetch, games as games_mod
from ..data.store import Store

GRADES = config.SHADOW.parent / "grades.jsonl"
SHADOW_MODELS = ["challenger_elo", "logistic_pointdiff", "A_qb_weekstart", "A_qb_confirmed", "B_drive_sim",
                 "C_base", "C_situational", "E_bayes", "E_bayes_plugin", "F_matchup_additive", "F_matchup_interaction"]


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def read(path: Path = config.SHADOW) -> list[dict]:
    try:
        return [json.loads(x) for x in open(path) if x.strip()]
    except OSError:
        return []


def _key(e: dict) -> tuple:
    return (e["game_id"], e["model"], e["info_set"], e["model_version"], e.get("revision", 0))


def append(entries: list[dict], path: Path = config.SHADOW, now: pd.Timestamp | None = None) -> dict:
    """Write entries that are new and made before kickoff. Returns counts."""
    now = now or _now()
    have = {_key(e) for e in read(path)}
    written = skipped_dup = skipped_late = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for e in entries:
            e = dict(e)
            e.setdefault("revision", 0)
            if pd.Timestamp(e["kickoff"]) <= now and e.get("revision", 0) == 0:
                skipped_late += 1
                continue
            if _key(e) in have:
                skipped_dup += 1
                continue
            e["recorded_at"] = now.isoformat()
            f.write(json.dumps(e, default=str, sort_keys=True) + "\n")
            have.add(_key(e))
            written += 1
    return {"written": written, "duplicates_skipped": skipped_dup, "after_kickoff_skipped": skipped_late}


def correct(original: dict, changes: dict, reason: str, path: Path = config.SHADOW) -> dict:
    """A versioned correction; the original line stays untouched."""
    revs = [e.get("revision", 0) for e in read(path) if _key(e)[:4] == _key(original)[:4]]
    new = dict(original, **changes, revision=max(revs + [0]) + 1, supersedes=_key(original),
               correction_reason=reason)
    with open(path, "a") as f:
        f.write(json.dumps(dict(new, recorded_at=_now().isoformat()), default=str, sort_keys=True) + "\n")
    return new


def next_week(store: Store, now: pd.Timestamp) -> tuple[int, int] | None:
    g = store.games[(store.games["game_type"] == "REG") & (store.games["kickoff"] > now)]
    if not len(g):
        return None
    first = g.sort_values("kickoff").iloc[0]
    return int(first["season"]), int(first["week"])


def forecast_next(now: pd.Timestamp | None = None, store: Store | None = None, path: Path = config.SHADOW) -> dict:
    from .. import pipeline
    from ..adapters import deadeye
    from ..ensemble import stack
    now = now or _now()
    store = store or Store.load()
    nw = next_week(store, now)
    if nw is None:
        return {"status": "no upcoming games"}
    season, week = nw
    g = store.games
    wk = g[(g["season"] == season) & (g["week"] == week) & (g["game_type"] == "REG") & (g["kickoff"] > now)]
    snap = store.snapshot(now)
    entries = []
    rows = []
    for m in pipeline.models():
        if m.name not in SHADOW_MODELS:
            continue
        out = m.predict(snap, games_mod.blind(wk, m.info_set)).set_index("game_id").reindex(wk["game_id"])
        for gm in wk.itertuples():
            o = out.loc[gm.game_id]
            f = contract.Forecast(
                game_id=gm.game_id, season=season, week=week, home_team=gm.home_team, away_team=gm.away_team,
                kickoff=gm.kickoff.isoformat(), forecast_ts=now.isoformat(), info_set=m.info_set,
                p_home_raw=float(np.clip(o["p_home"], 1e-4, 1 - 1e-4)), model=m.name, model_version=m.version,
                train_cutoff=snap.cutoff.isoformat(), feature_cutoff=snap.cutoff.isoformat(),
                exp_margin=_f(o.get("exp_margin")), exp_total=_f(o.get("exp_total")), margin_sd=_f(o.get("margin_sd")),
                missing=o.get("missing") if isinstance(o.get("missing"), dict) else {},
                provenance=m.provenance + ("; starter = nflverse projected starter at fetch time"
                                           if m.name == "A_qb_confirmed" else ""),
                uses_market=m.uses_market)
            rows.append(f.record())
    comp = pd.DataFrame(rows)
    # market-free ensemble: selection and weights from historical out-of-fold forecasts only
    hist = _history_forecasts()
    if len(hist):
        both = pd.concat([hist, comp], ignore_index=True)
        ens, chosen = stack.run(both, store.games[["game_id", "home_win"]], pipeline.FREE, "G_free",
                                config.WEEK_START, False, [season], log=lambda *_: None)
        ens = ens[ens["game_id"].isin(wk["game_id"])]
        ens["forecast_ts"] = now.isoformat()
        rows += ens.to_dict("records")
    for r in rows:
        r["kind"] = "lab_model"
        r["prospective"] = True
    entries += rows
    # market snapshot (as nflverse published it when games.csv was fetched)
    fetched = fetch.read_manifest().get("games.csv", {}).get("fetched_at")
    for gm in wk.itertuples():
        if pd.notna(gm.spread_line):
            from ..models.baselines import devig
            p = devig(gm.home_moneyline, gm.away_moneyline) if pd.notna(gm.home_moneyline) else np.nan
            entries.append({"kind": "market_snapshot", "game_id": gm.game_id, "season": season, "week": week,
                            "home_team": gm.home_team, "away_team": gm.away_team, "kickoff": gm.kickoff.isoformat(),
                            "model": "market_snapshot", "model_version": "nflverse-games.csv", "info_set": "market_at_fetch",
                            "forecast_ts": fetched, "p_home_raw": None if np.isnan(p) else float(p),
                            "spread_line": gm.spread_line, "total_line": gm.total_line,
                            "home_moneyline": gm.home_moneyline, "away_moneyline": gm.away_moneyline,
                            "provenance": f"nflverse games.csv fetched {fetched} (sha256 {fetch.read_manifest().get('games.csv', {}).get('sha256', '')[:12]})"})
    # Deadeye, captured separately
    dd = deadeye.recorded()
    status = "recorded forecast log" if len(dd) else None
    rec = deadeye.recomputed(store.games)
    rec = rec[(rec["season"] == season) & (rec["week"] == week)] if len(rec) else rec
    for r in rec.itertuples() if len(rec) else []:
        if not isinstance(r.game_id, str):
            continue
        gm = wk[wk["game_id"] == r.game_id]
        if not len(gm):
            continue
        entries.append({"kind": "deadeye", "game_id": r.game_id, "season": season, "week": week,
                        "home_team": r.home_team, "away_team": r.away_team, "kickoff": gm["kickoff"].iloc[0].isoformat(),
                        "model": "deadeye_recomputed", "model_version": "acql predictions.Forecast.expected @ default share",
                        "info_set": "deadeye_inputs_recomputed", "forecast_ts": now.isoformat(),
                        "p_home_raw": r.p_home, "exp_margin": r.exp_margin, "market_in_file": r.market,
                        "provenance": f"Deadeye's code on {r.source}; NOT Deadeye's displayed forecast"})
        status = status or "recomputed from tracker file"
    if status is None:
        entries.append({"kind": "deadeye_unavailable", "game_id": f"{season}_{week:02d}_ALL", "season": season,
                        "week": week, "kickoff": wk["kickoff"].min().isoformat(), "model": "deadeye_status",
                        "model_version": "-", "info_set": "-", "forecast_ts": now.isoformat(),
                        "note": "no acql.db forecast log and no tracker file for this week"})
    result = append(entries, path, now)
    result.update(season=season, week=week, games=len(wk), deadeye=status or "unavailable",
                  as_of=now.isoformat(), data_cutoff=snap.cutoff.isoformat())
    return result


def _f(x):
    return None if x is None or pd.isna(x) else float(x)


def _history_forecasts() -> pd.DataFrame:
    frames = []
    for name in ("forecasts_dev.csv.gz", "forecasts_holdout.csv.gz"):
        p = config.OUTPUTS / name
        if p.exists():
            frames.append(pd.read_csv(p))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def grade(store: Store | None = None, path: Path = config.SHADOW, grades: Path = GRADES) -> dict:
    store = store or Store.load()
    done = store.games.set_index("game_id")
    have = {(g["game_id"], g["model"], g.get("revision", 0)) for g in read(grades)}
    new = 0
    with open(grades, "a") as f:
        for e in read(path):
            if e.get("p_home_raw") is None or e["game_id"] not in done.index:
                continue
            gm = done.loc[e["game_id"]]
            if not gm["completed"] or (e["game_id"], e["model"], e.get("revision", 0)) in have:
                continue
            y = gm["home_win"]
            p = float(e["p_home_raw"])
            row = {"game_id": e["game_id"], "model": e["model"], "revision": e.get("revision", 0),
                   "season": e["season"], "week": e["week"], "p_home": p, "home_win": y, "margin": gm["margin"],
                   "log_loss": None if y == 0.5 else float(-(y * np.log(p) + (1 - y) * np.log(1 - p))),
                   "brier": float((p - y) ** 2), "graded_at": _now().isoformat(), "prospective": True}
            f.write(json.dumps(row, default=str) + "\n")
            new += 1
    return {"graded": new}
