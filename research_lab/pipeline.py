"""The lab's runs: backtest, ensembles, evaluation, ablation. Called by `python -m research_lab`."""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from . import acql_eval, config, contract
from .adapters import deadeye
from .backtest import engine
from .data.store import Store
from .ensemble import stack
from .experiments import ablation, registry
from .metrics import scoring
from .models import baselines, bayes, market, matchup, qb, situational
from .simulation import drives

WARM_FROM = 2009          # predicted to warm up calibration and stacking; not scored


def models():
    return [baselines.MarketMoneyline(), baselines.MarketSpread(), baselines.ChallengerElo(),
            baselines.SimpleLogistic(), qb.QBWeekStart(), qb.QBInjury(), qb.QBConfirmed(), drives.DriveSim(),
            situational.SituationalBase(), situational.Situational(), situational.SituationalWeather(),
            market.MarketFull(), bayes.BayesTeams(), bayes.BayesTeams(plugin=True), matchup.MatchupAdditive(),
            matchup.MatchupInteraction()]


FREE = ["challenger_elo", "logistic_pointdiff", "A_qb_weekstart", "B_drive_sim", "C_situational", "E_bayes",
        "F_matchup_additive", "F_matchup_interaction"]
INFORMED = FREE + ["market_ml_close", "D_market_full", "A_qb_confirmed", "C_sit_weather"]


def deadeye_rows(store: Store, seasons) -> pd.DataFrame:
    g = store.games[(store.games["game_type"] == "REG") & store.games["season"].isin(list(seasons))]
    lo = deadeye.line_only_proxy(g)
    meta = g.set_index("game_id")
    rows = []
    for r in lo.itertuples():
        m = meta.loc[r.game_id]
        rows.append(contract.Forecast(
            game_id=r.game_id, season=int(m["season"]), week=int(m["week"]), home_team=m["home_team"],
            away_team=m["away_team"], kickoff=m["kickoff"].isoformat(), forecast_ts=m["kickoff"].isoformat(),
            info_set=config.CLOSING_RETRO, p_home_raw=float(r.p_home), model="deadeye_line_only_proxy",
            model_version="acql.analytics.win_chance", train_cutoff="", feature_cutoff=m["kickoff"].isoformat(),
            exp_margin=float(r.exp_margin), margin_sd=None, provenance="Deadeye curve on nflverse closing spread (proxy)",
            uses_market=True).record())
    return pd.DataFrame(rows)


def backtest(seasons, tag: str, log=print, store: Store | None = None) -> pd.DataFrame:
    store = store or Store.load()
    t0 = time.time()
    df = engine.run(models(), store, seasons, log=log)
    df = pd.concat([df, deadeye_rows(store, seasons)], ignore_index=True)
    df = engine.calibrate(df.drop(columns=["p_home_cal", "p_away_cal"]), store=store)
    config.OUTPUTS.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUTS / f"forecasts_{tag}.csv.gz"
    df.to_csv(path, index=False)
    registry.record("backtest", f"walk-forward {tag}", {"seasons": [min(seasons), max(seasons)],
                                                        "models": sorted(df["model"].unique())}, "ok",
                    {"rows": len(df), "seconds": round(time.time() - t0)}, test_period=f"{min(seasons)}-{max(seasons)}",
                    train_cutoff="each week: games completed before Tuesday 09:00 ET")
    log(f"wrote {path} ({len(df)} rows)")
    return df


def ensembles(fc: pd.DataFrame, store: Store, targets, tag: str, log=print) -> tuple[pd.DataFrame, list]:
    outcomes = store.games[["game_id", "home_win"]]
    a, ca = stack.run(fc, outcomes, FREE, "G_free", config.WEEK_START, False, targets, log=log)
    b, cb = stack.run(fc, outcomes, INFORMED, "G_market", config.CLOSING_RETRO, True, targets, log=log)
    g = pd.concat([a, b], ignore_index=True)
    problems = contract.validate(g)
    if problems:
        raise ValueError(problems)
    (config.OUTPUTS / f"ensemble_choices_{tag}.json").write_text(json.dumps(ca + cb, indent=1))
    registry.record("ensemble", f"ensembles {tag}", {"free": FREE, "informed": INFORMED,
                                                     "min_gain": stack.MIN_GAIN, "val_seasons": stack.VAL_SEASONS},
                    "ok", {"rows": len(g)}, test_period=f"{min(targets)}-{max(targets)}",
                    train_cutoff="component OOF forecasts from seasons < target")
    return g, ca + cb


# ---- evaluation -----------------------------------------------------------------------------
def evaluate(fc: pd.DataFrame, store: Store, seasons, period: str) -> dict:
    res = store.games[store.games["season"].isin(list(seasons)) & (store.games["game_type"] == "REG")
                      & store.games["completed"]][["game_id", "season", "week", "home_team", "away_team",
                                                    "margin", "total_points", "home_win", "spread_line"]]
    fc = fc[fc["season"].isin(list(seasons))]
    names = sorted(fc["model"].unique())
    raw = scoring.wide(fc, res)
    matched = raw.dropna(subset=names)
    out: dict = {"period": period, "games_total": len(res), "games_matched": len(matched), "models": names}
    # coverage
    out["coverage"] = {m: int(raw[m].notna().sum()) for m in names}
    # per-model summaries on the matched set (raw and calibrated)
    cal = scoring.wide(fc, res, use_cal=True)
    cal = cal[cal["game_id"].isin(matched["game_id"])]
    meta = fc.drop_duplicates(["model"]).set_index("model")[["info_set", "uses_market"]].to_dict("index")
    em = fc.pivot_table(index="game_id", columns="model", values="exp_margin")
    et = fc.pivot_table(index="game_id", columns="model", values="exp_total")
    summ = []
    for m in names:
        d = matched[["game_id", "season", "week", "home_win", "margin", "total_points"]].copy()
        d["p"] = matched[m].values
        d["exp_margin"] = em[m].reindex(d["game_id"]).values if m in em else np.nan
        d["exp_total"] = et[m].reindex(d["game_id"]).values if m in et else np.nan
        s = scoring.summary(d)
        c = cal[["home_win", m]].dropna() if m in cal else cal[["home_win"]].iloc[:0]
        c = c[c["home_win"].isin([0.0, 1.0])]
        s["log_loss_cal"] = float(scoring.log_loss(c[m].astype(float), c["home_win"]).mean()) if len(c) else None
        s["n_cal"] = len(c)
        s.update(model=m, **meta.get(m, {}))
        summ.append(s)
    out["summary"] = sorted(summ, key=lambda r: r["log_loss"])
    # by season
    out["by_season"] = []
    for s_, grp in matched.groupby("season"):
        for m in names:
            d = grp.assign(p=grp[m])
            r = scoring.summary(d)
            out["by_season"].append({"season": int(s_), "model": m, "log_loss": r["log_loss"], "brier": r["brier"],
                                     "accuracy": r["accuracy"], "n": r["n"]})
    # early vs late season, favourite/underdog, probability buckets
    groups = {"weeks 1-4": matched["week"] <= 4, "weeks 5-9": matched["week"].between(5, 9),
              "weeks 10-18": matched["week"] >= 10}
    out["by_phase"] = [{"phase": k, "model": m, **{kk: vv for kk, vv in scoring.summary(matched[v].assign(p=matched[v][m])).items()
                                                  if kk in ("n", "log_loss", "accuracy")}}
                       for k, v in groups.items() for m in names]
    fav = np.sign(matched["spread_line"])
    out["by_side"] = []
    for m in names:
        picks_fav = np.sign(matched[m] - 0.5) == fav
        y = matched["home_win"]
        right = ((matched[m] > 0.5) == (y == 1)) & y.isin([0.0, 1.0])
        out["by_side"].append({"model": m, "picks_market_fav": int(picks_fav.sum()),
                               "acc_when_fav": float(right[picks_fav].mean()),
                               "picks_market_dog": int((~picks_fav & (fav != 0)).sum()),
                               "acc_when_dog": float(right[~picks_fav & (fav != 0)].mean()) if (~picks_fav & (fav != 0)).any() else None})
    out["reliability"] = {m: scoring.reliability(matched[m], matched["home_win"]).to_dict("records")
                          for m in names if matched["home_win"].isin([0, 1]).any()}
    # paired comparisons against the benchmarks
    benches = [b for b in ("market_ml_close", "deadeye_line_only_proxy", "challenger_elo") if b in names]
    out["paired"] = [dict(scoring.paired(matched, m, b), metric="log_loss") for b in benches for m in names if m != b]
    out["paired_brier"] = [dict(scoring.paired(matched, m, b, scoring.brier), metric="brier")
                           for b in benches for m in names if m != b]
    out["n_comparisons"] = len(out["paired"])
    # uncertainty test for E
    if {"E_bayes", "E_bayes_plugin"} <= set(names):
        out["bayes_uncertainty"] = {k: scoring.paired(matched[v], "E_bayes", "E_bayes_plugin")
                                    for k, v in groups.items()}
        out["bayes_uncertainty"]["all"] = scoring.paired(matched, "E_bayes", "E_bayes_plugin")
    # ACQL
    cards = acql_eval.cards(fc[fc["game_id"].isin(matched["game_id"])], res)
    wk = acql_eval.weekly(cards)
    tab = wk.pivot_table(index=["season", "week"], columns="model", values="points")
    acql = []
    for m in names:
        if m not in tab:
            continue
        row = {"model": m, "weeks": int(tab[m].notna().sum()), "total": int(tab[m].sum()),
               "per_week": float(tab[m].mean()), "sd_week": float(tab[m].std())}
        for b in benches:
            if m != b and b in tab:
                d = (tab[m] - tab[b]).dropna()
                blocks = np.array([f"{s}-{w}" for s, w in d.index])
                mean, lo, hi, _ = scoring.block_bootstrap(d.values, blocks)
                row[f"vs_{b}"] = {"diff_per_week": mean, "lo": lo, "hi": hi}
        acql.append(row)
    out["acql"] = sorted(acql, key=lambda r: -r["per_week"])
    out["acql_by_season"] = wk.groupby(["model", "season"])["points"].sum().reset_index().to_dict("records")
    return out


def run_ablation(fc: pd.DataFrame, store: Store, seasons, period: str, log=print) -> pd.DataFrame:
    df = ablation.family_frame(store, fc, range(WARM_FROM, max(seasons) + 1))
    return ablation.run(df, seasons, period, log=log)
