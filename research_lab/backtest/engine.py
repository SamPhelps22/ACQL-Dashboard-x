"""Walk-forward: every regular-season week priced with only what was known before it.

For each (season, week), in kickoff order:
  1. forecast_ts = the week's Tuesday 09:00 ET (or 90 min before each kickoff
     for pre-kickoff models; the closing time for retrospective benchmarks);
  2. the model gets Store.snapshot(week_start) - games completed by then - and
     the week's games blinded to its information set;
  3. its rows are stamped with the contract fields and kept;
  4. results are attached afterwards, for scoring only.

Calibration (Platt on the logit) for season s is fitted on the same model's
forecasts from seasons before s only.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .. import config, contract
from ..data import games as games_mod
from ..data.store import Store
from ..models.base import Model, expit, logistic, logit

#: Seasons before this are predicted only to warm up calibration and stacking.
CALIBRATION_MIN_SEASONS = 2


def weeks(store: Store, seasons) -> list[tuple[int, int]]:
    g = store.games
    reg = g[(g["game_type"] == "REG") & g["season"].isin(list(seasons))]
    return sorted(set(zip(reg["season"], reg["week"])))


def _ts(row_week: pd.DataFrame, info_set: str) -> pd.Series:
    if info_set == config.PRE_KICKOFF:
        return row_week["ts_pre_kickoff"]
    if info_set == config.CLOSING_RETRO:
        return row_week["kickoff"]
    return row_week["ts_week_start"]


def predict_week(model: Model, store: Store, season: int, week: int, completed_only: bool = False) -> pd.DataFrame:
    g = store.games
    wk = g[(g["season"] == season) & (g["week"] == week) & (g["game_type"] == "REG")]
    if completed_only:
        wk = wk[wk["completed"]]
    if not len(wk):
        return pd.DataFrame(columns=contract.FIELDS)
    as_of = wk["ts_week_start"].iloc[0]
    snap = store.snapshot(as_of)
    out = model.predict(snap, games_mod.blind(wk, model.info_set))
    out = out.set_index("game_id").reindex(wk["game_id"]).reset_index()
    ts = _ts(wk, model.info_set).values
    cutoff = snap.cutoff
    rows = []
    for i, (_, gm) in enumerate(wk.iterrows()):
        o = out.iloc[i]
        p = float(np.clip(o["p_home"], 1e-4, 1 - 1e-4)) if pd.notna(o["p_home"]) else np.nan
        if np.isnan(p):
            continue
        f = contract.Forecast(
            game_id=gm["game_id"], season=int(season), week=int(week), home_team=gm["home_team"],
            away_team=gm["away_team"], kickoff=gm["kickoff"].isoformat(), forecast_ts=pd.Timestamp(ts[i]).isoformat(),
            info_set=model.info_set, p_home_raw=p, model=model.name, model_version=model.version,
            train_cutoff=cutoff.isoformat() if cutoff is not None else "",
            feature_cutoff=(cutoff.isoformat() if cutoff is not None else pd.Timestamp(ts[i]).isoformat()),
            exp_margin=_num(o.get("exp_margin")), exp_total=_num(o.get("exp_total")), margin_sd=_num(o.get("margin_sd")),
            missing=o.get("missing") if isinstance(o.get("missing"), dict) else {},
            provenance=model.provenance, uses_market=model.uses_market)
        rows.append(f.record())
    return pd.DataFrame(rows, columns=contract.FIELDS)


def _num(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x) else float(x)


def run(models: list[Model], store: Store, seasons, log=print) -> pd.DataFrame:
    frames = []
    for m in models:
        t0 = time.time()
        for s, w in weeks(store, seasons):
            frames.append(predict_week(m, store, s, w))
        log(f"  {m.name}: {time.time() - t0:.1f}s")
    out = pd.concat([f for f in frames if len(f)], ignore_index=True)
    problems = contract.validate(out)
    if problems:
        raise ValueError(f"forecast contract violated: {problems}")
    return calibrate(out, store=store)


def calibrate(df: pd.DataFrame, outcomes: pd.DataFrame | None = None, store: Store | None = None) -> pd.DataFrame:
    """Platt-scale each model's season s on its own forecasts from earlier seasons (outcomes known then)."""
    df = df.copy()
    if outcomes is None and store is not None:
        outcomes = store.games[["game_id", "home_win"]]
    if outcomes is None:
        df["p_home_cal"], df["p_away_cal"] = None, None
        return df
    merged = df.merge(outcomes, on="game_id", how="left")
    cal = np.full(len(df), np.nan)
    for name, grp in merged.groupby("model"):
        seasons = sorted(grp["season"].unique())
        for s in seasons:
            past = grp[(grp["season"] < s) & grp["home_win"].isin([0.0, 1.0])]
            idx = grp.index[grp["season"] == s]
            if past["season"].nunique() < CALIBRATION_MIN_SEASONS:
                continue
            X = np.column_stack([np.ones(len(past)), logit(past["p_home_raw"].astype(float))])
            beta = logistic(X, past["home_win"].values, lam=1.0)
            now = merged.loc[idx, "p_home_raw"].astype(float)
            cal[idx] = expit(beta[0] + beta[1] * logit(now))
    df["p_home_cal"] = np.where(np.isnan(cal), None, cal)
    df["p_away_cal"] = np.where(np.isnan(cal), None, 1 - cal)
    return df


def attach_results(df: pd.DataFrame, store: Store) -> pd.DataFrame:
    cols = ["game_id", "home_score", "away_score", "margin", "total_points", "home_win", "spread_line"]
    return df.merge(store.games[cols], on="game_id", how="left")
