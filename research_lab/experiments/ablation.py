"""Signal discovery: does a feature family add anything, on top of what?

For every family F and two bases (the closing market; a football-only base,
Model E's out-of-fold probability):

    base            vs  base + F
    full (all F)    vs  full without F      (market base)

Each arm is a logistic regression (standardised inputs, fixed penalty LAMBDA -
set before any result was seen) trained walk-forward: season s is scored by a
fit on seasons < s. Every arm in a comparison uses the same games. Results go
to the registry, weak or not. Families with no usable historical data are
registered as not run.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from ..data import games as games_mod
from ..features import qb, ratings, situational
from ..features.bank import bank_for
from ..metrics.scoring import block_bootstrap, log_loss
from ..models import matchup
from ..models.base import Standardizer, expit, logistic, logit
from . import registry

LAMBDA = 10.0
MIN_TRAIN_SEASONS = 3

FAMILIES = {
    "qb_weekstart": "quarterback (last game's starter; week start)",
    "qb_confirmed": "quarterback (confirmed starter; pre-kickoff)",
    "rest_travel": "rest, byes, travel, time zones, altitude, surface (schedule-time)",
    "environment": "observed game weather (retrospective upper bound)",
    "tactical": "matchup interactions from play-by-play unit ratings",
    "team_strength": "Model E Bayesian team strength (OOF probability)",
    "drive_sim": "Model B drive simulation (OOF probability)",
    "unit_ratings": "additive opponent-adjusted unit ratings (Model F additive OOF)",
    "market_detail": "closing spread-vs-moneyline disagreement, spread prices, total (retrospective)",
}
NOT_AVAILABLE = {
    "market_movement": "no historical opening lines or timestamped odds in any accessible source "
                       "(nflverse keeps closing numbers only; The Odds API history needs a paid key)",
    "cross_book": "no per-sportsbook historical quotes accessible",
    "weather_forecast": "no archived pre-game weather forecasts before 2022 accessible; observed weather used as an "
                        "upper bound instead",
}


def family_frame(store, forecasts: pd.DataFrame, seasons) -> pd.DataFrame:
    """One row per regular-season game in `seasons`: every family's features, all point-in-time."""
    bank = bank_for(store)
    g = store.games
    reg = g[(g["game_type"] == "REG") & g["season"].isin(list(seasons)) & g["completed"]]
    frames = []
    for (s, w), wk in reg.groupby(["season", "week"]):
        q1 = bank.week_rows("qb_last", qb.builder("last"), s, w)
        q2 = bank.week_rows("qb_confirmed", qb.builder("confirmed"), s, w, config.PRE_KICKOFF)
        st = bank.week_rows("situational", situational.build, s, w)
        rt = bank.week_rows("ratings", matchup._with_site, s, w)
        f = pd.DataFrame({"game_id": wk["game_id"].values})
        for name, src in (("qbw", q1), ("qbc", q2)):
            for c in ("qb_rating", "qb_changed", "qb_exp", "qb_vs_team", "qb_sack", "qb_int"):
                f[f"{name}_{c}"] = (src.set_index("game_id")[f"h_{c}"] - src.set_index("game_id")[f"a_{c}"]
                                    ).reindex(f["game_id"]).values
        for c in ("rest_diff", "h_short", "a_short", "h_bye", "a_bye", "a_km", "a_tz_east", "a_tz_west",
                  "early_west_away", "altitude", "turf", "dome", "div_game"):
            f[f"rt_{c}"] = st.set_index("game_id")[c].reindex(f["game_id"]).values
        f["rt_altitude"] = (f["rt_altitude"].fillna(0) > 1500).astype(float)
        f["rt_a_km"] = f["rt_a_km"].fillna(0) / 1000
        inter = matchup.interactions(rt.set_index("game_id").reindex(f["game_id"]).reset_index())
        for c in inter.columns:
            f[f"tac_{c}"] = inter[c].values
        wx = situational.weather(games_mod.blind(wk, config.CLOSING_RETRO))
        for c in ("wind", "cold", "windy"):
            f[f"env_{c}"] = wx[c].values
        f["env_dome_team_cold"] = (st.set_index("game_id")["a_dome_team"].reindex(f["game_id"]).values
                                   * wx["cold"].values * (1 - f["rt_dome"].values))
        frames.append(f)
    df = pd.concat(frames, ignore_index=True)
    # out-of-fold model probabilities as features
    piv = forecasts.pivot_table(index="game_id", columns="model", values="p_home_raw")
    for model, col in (("E_bayes", "ts_bayes"), ("B_drive_sim", "ds_sim"), ("F_matchup_additive", "ur_additive"),
                       ("market_ml_close", "base_market")):
        df[col] = logit(piv[model].reindex(df["game_id"]).values) if model in piv else np.nan
    from ..models.market import market_features
    mf = market_features(g.set_index("game_id").loc[df["game_id"]].reset_index())
    for c in ("disagree", "spread_tilt", "total_x"):
        df[f"mkt_{c}"] = mf[c].values
    meta = g.set_index("game_id").loc[df["game_id"], ["season", "week", "home_win"]].reset_index(drop=True)
    return pd.concat([df.reset_index(drop=True), meta], axis=1)


PREFIX = {"qb_weekstart": "qbw_", "qb_confirmed": "qbc_", "rest_travel": "rt_", "environment": "env_",
          "tactical": "tac_", "team_strength": "ts_", "drive_sim": "ds_", "unit_ratings": "ur_",
          "market_detail": "mkt_"}


def cols_of(df, family):
    return [c for c in df.columns if c.startswith(PREFIX[family])]


def walk(df: pd.DataFrame, cols: list[str], seasons) -> np.ndarray:
    """Out-of-sample probabilities, season by season."""
    out = np.full(len(df), np.nan)
    y = df["home_win"].values
    for s in seasons:
        tr = (df["season"] < s).values & np.isin(y, [0.0, 1.0])
        te = (df["season"] == s).values
        if df.loc[tr, "season"].nunique() < MIN_TRAIN_SEASONS or not te.any():
            continue
        sc = Standardizer().fit(df.loc[tr, cols].values.astype(float))
        X = np.column_stack([np.ones(tr.sum()), sc.transform(df.loc[tr, cols].values.astype(float))])
        b = logistic(X, y[tr], lam=LAMBDA)
        Xt = np.column_stack([np.ones(te.sum()), sc.transform(df.loc[te, cols].values.astype(float))])
        out[te] = expit(Xt @ b)
    return out


def compare(df, a_cols, b_cols, seasons) -> dict:
    pa, pb = walk(df, a_cols, seasons), walk(df, b_cols, seasons)
    ok = ~np.isnan(pa) & ~np.isnan(pb) & df["home_win"].isin([0.0, 1.0]).values
    y = df["home_win"].values[ok]
    diff = log_loss(pa[ok], y) - log_loss(pb[ok], y)
    blocks = (df["season"].astype(str) + "-" + df["week"].astype(str)).values[ok]
    mean, lo, hi, draws = block_bootstrap(diff, blocks)
    return {"n": int(ok.sum()), "ll_with": float(log_loss(pa[ok], y).mean()), "ll_without": float(log_loss(pb[ok], y).mean()),
            "diff": mean, "lo": lo, "hi": hi, "p_improves": float(np.mean(draws < 0))}


def run(df: pd.DataFrame, seasons, period: str, log=print) -> pd.DataFrame:
    rows = []
    fams = list(FAMILIES)
    football_base = ["ts_bayes"]
    market_base = ["base_market"]
    all_cols = market_base + [c for f in fams for c in cols_of(df, f) if c not in market_base]
    all_cols = list(dict.fromkeys(all_cols))
    for fam in fams:
        fc = cols_of(df, fam)
        if not fc:
            continue
        tests = [("market + family vs market", market_base + fc, market_base)]
        if fam != "team_strength":
            tests.append(("football + family vs football", football_base + fc, football_base))
        tests.append(("full vs full without family", all_cols, [c for c in all_cols if c not in fc]))
        for label, a, b in tests:
            try:
                r = compare(df, a, b, seasons)
                status = "ok"
            except Exception as exc:  # noqa: BLE001 - recorded
                r, status = {"error": str(exc)}, "failed"
            r.update({"family": fam, "comparison": label})
            rows.append(r)
            registry.record("ablation", f"{fam}: {label}", {"family": fam, "with": a, "without": b, "lambda": LAMBDA,
                                                           "description": FAMILIES[fam]},
                            status, {k: v for k, v in r.items() if k not in ("family", "comparison")},
                            test_period=period, train_cutoff="expanding window, seasons < test season")
            if status == "ok":
                log(f"  {fam:14s} {label:32s} diff {r['diff']:+.4f} [{r['lo']:+.4f}, {r['hi']:+.4f}] n={r['n']}")
    for fam, why in NOT_AVAILABLE.items():
        registry.record("ablation", f"{fam}: not run", {"family": fam}, "not_run", note=why, test_period=period)
        rows.append({"family": fam, "comparison": "not run", "note": why})
    return pd.DataFrame(rows)
