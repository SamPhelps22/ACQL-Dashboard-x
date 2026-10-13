"""Football intelligence: opponent-adjusted unit ratings, quarterback ratings and
matchup interactions, all computed point-in-time.

Method (documented in docs/FEATURES.md):

1. Per team-game offensive rates come from play-by-play aggregates
   (``team_game_detail``); defensive "allowed" rates are the opponent's offence.
2. Opponent adjustment (one pass): a game's offensive value is corrected by how
   good the opponent's defence was *before* that game,
   ``adj_off = off - (opp_def_pre - league_prior)``, and symmetrically for defence.
3. Ratings are exponentially weighted (half-life ``unit_halflife_games``) across
   seasons, with the carry-over halved at each new season and ``unit_prior_games``
   pseudo-games of the previous season's league mean (shrinkage for small samples).
4. Quarterback rating = dropback-weighted EWMA of the QB's own EPA/dropback across
   his career, shrunk toward a replacement-level prior (league prior - 0.10) with
   ``qb_prior_dropbacks`` pseudo-dropbacks. New/backup QBs therefore start near
   replacement level rather than at the team's average.
5. States become available at kickoff + 4h and are joined with merge_asof on the
   prediction cutoff (backward, strict), exactly like the base features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models.elo import GAME_DURATION

# Offensive per-game rates derived from team_game_detail. (name, numerator, denominator)
RATES = {
    "db_epa": ("dropback_epa_sum", "dropbacks"),
    "rush_epa": ("rush_epa_sum", "rush_plays"),
    "rush_succ": ("rush_success_sum", "rush_plays"),
    "early_epa": ("early_epa_sum", "early_plays"),
    "early_succ": ("early_success_sum", "early_plays"),
    "early_pass": ("early_pass", "early_plays"),
    "neutral_epa": ("neutral_epa_sum", "neutral_plays"),
    "sack_rate": ("sacks", "dropbacks"),
    "hit_rate": ("qb_hits", "dropbacks"),
    "int_rate": ("interceptions", "dropbacks"),
    "xpass_rate": ("explosive_passes", "dropbacks"),
    "third_rate": ("third_conv", "third_att"),
    "rz_td_rate": ("rz_td_drives", "rz_drives"),
    "cpoe": ("cpoe_sum", "cpoe_n"),
}
ADJUSTED = ["db_epa", "rush_epa", "early_epa", "neutral_epa", "sack_rate"]

UNIT_FEATURES = [
    "off_db_epa_adj_diff", "def_db_epa_adj_diff", "off_rush_epa_adj_diff", "def_rush_epa_adj_diff",
    "off_neutral_epa_adj_diff", "def_neutral_epa_adj_diff", "off_early_epa_adj_diff", "def_early_epa_adj_diff",
    "off_sack_rate_adj_diff", "def_sack_rate_adj_diff", "off_third_rate_diff", "def_third_rate_diff",
    "off_rz_td_rate_diff", "def_rz_td_rate_diff", "off_int_rate_diff", "def_int_rate_diff",
    "off_early_pass_diff",
]
QB_RATING_FEATURES = ["qb_rating_diff", "home_qb_vs_team", "away_qb_vs_team"]
MATCHUP_FEATURES = ["pass_matchup", "rush_matchup", "protection_matchup", "explosive_pass_matchup"]

FEATURE_GROUPS = {"units": UNIT_FEATURES, "qb_rating": QB_RATING_FEATURES, "matchup": MATCHUP_FEATURES}


def _ewma_states(df: pd.DataFrame, key: str, cols: list[str], weight: str | None, halflife: float,
                 prior: pd.DataFrame, prior_weight: float, season_carry: float = 0.5) -> pd.DataFrame:
    """Shrunk EWMA state *after* each row, per ``key`` in chronological order.

    prior: DataFrame indexed by season with one column per metric (prior mean).
    """
    d = df.sort_values([key, "kickoff_utc", "game_id"]).reset_index(drop=True)
    decay = 0.5 ** (1.0 / halflife)
    X = d[cols].to_numpy(dtype=float)
    w = d[weight].to_numpy(dtype=float) if weight else np.ones(len(d))
    keys = d[key].to_numpy()
    seasons = d["season"].to_numpy()
    P = prior.reindex(seasons)[cols].to_numpy(dtype=float)
    S = np.zeros_like(X)
    W = np.zeros_like(X)
    out = np.full_like(X, np.nan)
    s_run = np.zeros(len(cols))
    w_run = np.zeros(len(cols))
    for i in range(len(d)):
        if i == 0 or keys[i] != keys[i - 1]:
            s_run[:] = 0.0
            w_run[:] = 0.0
        elif seasons[i] != seasons[i - 1]:
            s_run *= season_carry
            w_run *= season_carry
        s_run *= decay
        w_run *= decay
        ok = ~np.isnan(X[i]) & (w[i] > 0)
        s_run[ok] += w[i] * X[i, ok]
        w_run[ok] += w[i]
        S[i], W[i] = s_run, w_run
        out[i] = (s_run + prior_weight * P[i]) / (w_run + prior_weight)
    res = d[[key, "game_id", "season", "kickoff_utc"]].copy()
    res["available_at"] = res["kickoff_utc"] + GAME_DURATION
    for j, c in enumerate(cols):
        res[c] = out[:, j]
        res[f"{c}__w"] = W[:, j]
    return res


def _asof(queries: pd.DataFrame, states: pd.DataFrame, by: str, cols: list[str]) -> pd.DataFrame:
    """Latest state strictly before each query cutoff (adds state_season, available_at)."""
    q = queries.copy()
    q["_ord"] = np.arange(len(q))
    if states.empty:
        for c in cols + ["available_at", "state_season"]:
            q[c] = np.nan
        return q.sort_values("_ord")
    st = states[[by, "available_at", "season"] + cols].rename(columns={"season": "state_season"})
    m = pd.merge_asof(q.sort_values("cutoff"), st.sort_values("available_at"), left_on="cutoff",
                      right_on="available_at", by=by, direction="backward", allow_exact_matches=False)
    return m.sort_values("_ord").reset_index(drop=True)


def team_game_rates(games: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    done = games[games["game_status"] == "final"]
    sides = []
    for side, opp in (("home", "away"), ("away", "home")):
        sides.append(pd.DataFrame({"game_id": done["game_id"], "season": done["season"],
                                   "kickoff_utc": done["kickoff_utc"], "team": done[f"{side}_team"],
                                   "opp": done[f"{opp}_team"]}))
    tg = pd.concat(sides, ignore_index=True).merge(detail, on=["game_id", "team"], how="inner")
    for name, (num, den) in RATES.items():
        tg[f"off_{name}"] = tg[num] / tg[den].where(tg[den] > 0)
    opp_cols = {f"off_{n}": f"def_{n}" for n in RATES}
    opp = tg[["game_id", "team"] + list(opp_cols)].rename(columns={"team": "opp", **opp_cols})
    return tg.merge(opp, on=["game_id", "opp"], how="left")


def _league_prior(tg: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Prior for season S = league mean of season S-1 (earlier seasons only). The very first
    season in the data has no history, so it uses its own mean; it is a training-only season."""
    by = tg.groupby("season")[cols].mean()
    prior = by.shift(1).fillna(by.expanding().mean().shift(1))
    return prior.fillna(by.iloc[:1].reindex(by.index, method="ffill"))


def build_unit_states(tg: pd.DataFrame, halflife: float, prior_games: float) -> pd.DataFrame:
    off_cols = [f"off_{n}" for n in RATES]
    def_cols = [f"def_{n}" for n in RATES]
    cols = off_cols + def_cols
    prior = _league_prior(tg, cols)
    raw = _ewma_states(tg, "team", cols, None, halflife, prior, prior_games)
    # Opponent's raw state before each game (strictly before its kickoff).
    q = pd.DataFrame({"team": tg["opp"], "cutoff": tg["kickoff_utc"]})
    pre = _asof(q, raw.drop(columns=[c for c in raw if c.endswith("__w")]), "team", cols)
    lp = prior.reindex(tg["season"]).reset_index(drop=True)
    adj = tg.reset_index(drop=True).copy()
    for n in ADJUSTED:
        opp_def = pre[f"def_{n}"].fillna(lp[f"def_{n}"])
        opp_off = pre[f"off_{n}"].fillna(lp[f"off_{n}"])
        adj[f"off_{n}_adj"] = adj[f"off_{n}"] - (opp_def - lp[f"def_{n}"])
        adj[f"def_{n}_adj"] = adj[f"def_{n}"] - (opp_off - lp[f"off_{n}"])
    adj_cols = [f"{s}_{n}_adj" for n in ADJUSTED for s in ("off", "def")]
    state_cols = adj_cols + [c for c in cols if not any(c == f"{s}_{n}" for n in ADJUSTED for s in ("off", "def"))]
    prior2 = _league_prior(adj, state_cols)
    return _ewma_states(adj, "team", state_cols, None, halflife, prior2, prior_games)


def build_qb_states(games: pd.DataFrame, qbs: pd.DataFrame, tg: pd.DataFrame, halflife_games: float,
                    prior_dropbacks: float) -> pd.DataFrame:
    if qbs.empty:
        return pd.DataFrame()
    q = qbs.merge(games[["game_id", "season", "kickoff_utc"]], on="game_id")
    q = q[q["dropbacks"] > 0].copy()
    q["qb_epa"] = q["epa_sum"] / q["dropbacks"]
    league = tg.groupby("season")["off_db_epa"].mean()
    prior = pd.DataFrame({"qb_epa": league.shift(1).fillna(league.iloc[0]) - 0.10})
    return _ewma_states(q, "qb_id", ["qb_epa"], "dropbacks", halflife_games, prior, prior_dropbacks,
                        season_carry=0.8)


def add_football_features(out: pd.DataFrame, games: pd.DataFrame, detail: pd.DataFrame | None,
                          qbs: pd.DataFrame | None, fcfg: dict) -> pd.DataFrame:
    """Append unit, QB and matchup features (all groups) to the base feature frame."""
    out = out.copy()
    allcols = UNIT_FEATURES + QB_RATING_FEATURES + MATCHUP_FEATURES
    if detail is None or detail.empty:
        for c in allcols:
            out[c] = np.nan
        out["football_feature_ts"] = pd.NaT
        return out
    halflife = float(fcfg.get("unit_halflife_games", 8))
    prior_games = float(fcfg.get("unit_prior_games", 3))
    tg = team_game_rates(games, detail)
    states = build_unit_states(tg, halflife, prior_games)
    scols = [c for c in states.columns if c not in ("team", "game_id", "season", "kickoff_utc", "available_at")
             and not c.endswith("__w")]
    new = {}
    side_vals = {}
    for side in ("home", "away"):
        q = pd.DataFrame({"team": out[f"{side}_team"].to_numpy(), "cutoff": out["cutoff"].to_numpy()})
        m = _asof(q, states, "team", scols)
        side_vals[side] = m
        new[f"{side}_football_ts"] = m["available_at"].to_numpy()

    def v(side, col):
        return side_vals[side][col].to_numpy(dtype=float)

    for n in ADJUSTED:
        new[f"off_{n}_adj_diff"] = v("home", f"off_{n}_adj") - v("away", f"off_{n}_adj")
        new[f"def_{n}_adj_diff"] = v("home", f"def_{n}_adj") - v("away", f"def_{n}_adj")
    for n in ("third_rate", "rz_td_rate", "int_rate"):
        new[f"off_{n}_diff"] = v("home", f"off_{n}") - v("away", f"off_{n}")
        new[f"def_{n}_diff"] = v("home", f"def_{n}") - v("away", f"def_{n}")
    new["off_early_pass_diff"] = v("home", "off_early_pass") - v("away", "off_early_pass")
    # Matchups: home unit vs the away unit it faces, minus the reverse (higher favours home).
    new["pass_matchup"] = ((v("home", "off_db_epa_adj") + v("away", "def_db_epa_adj"))
                           - (v("away", "off_db_epa_adj") + v("home", "def_db_epa_adj")))
    new["rush_matchup"] = ((v("home", "off_rush_epa_adj") + v("away", "def_rush_epa_adj"))
                           - (v("away", "off_rush_epa_adj") + v("home", "def_rush_epa_adj")))
    # sack rate: offence allowed (bad) vs defence generated (good for that defence)
    new["protection_matchup"] = ((v("away", "off_sack_rate_adj") + v("home", "def_sack_rate_adj"))
                                 - (v("home", "off_sack_rate_adj") + v("away", "def_sack_rate_adj")))
    new["explosive_pass_matchup"] = ((v("home", "off_xpass_rate") + v("away", "def_xpass_rate"))
                                     - (v("away", "off_xpass_rate") + v("home", "def_xpass_rate")))
    # Quarterbacks
    qstates = build_qb_states(games, qbs if qbs is not None else pd.DataFrame(), tg,
                              float(fcfg.get("qb_halflife_games", 10)), float(fcfg.get("qb_prior_dropbacks", 150)))
    lp = tg.groupby("season")["off_db_epa"].mean()
    repl = out["season"].map(lp.shift(1).fillna(lp.iloc[0])).to_numpy(dtype=float) - 0.10
    for side in ("home", "away"):
        qid = out[f"{side}_qb_id"].astype(object).where(out[f"{side}_qb_id"].notna(), "__none__").astype(str)
        if len(qstates):
            m = _asof(pd.DataFrame({"qb_id": qid.to_numpy(), "cutoff": out["cutoff"].to_numpy()}),
                      qstates, "qb_id", ["qb_epa", "qb_epa__w"])
            rating = m["qb_epa"].to_numpy(dtype=float)
            dbs = m["qb_epa__w"].to_numpy(dtype=float)
        else:
            rating, dbs = np.full(len(out), np.nan), np.zeros(len(out))
        known = (qid != "__none__").to_numpy()
        rating = np.where(known & np.isnan(rating), repl, rating)  # never-seen QB -> replacement level
        rating = np.where(known, rating, np.nan)
        new[f"{side}_qb_rating"] = rating
        new[f"{side}_qb_dropbacks_weighted"] = np.where(known, np.nan_to_num(dbs), np.nan)
        new[f"{side}_qb_vs_team"] = rating - v(side, "off_db_epa_adj")
    new["qb_rating_diff"] = new["home_qb_rating"] - new["away_qb_rating"]
    add = pd.DataFrame(new, index=out.index)
    out = pd.concat([out.drop(columns=[c for c in add.columns if c in out.columns]), add], axis=1)
    out["football_feature_ts"] = out[["home_football_ts", "away_football_ts"]].max(axis=1)
    # keep raw unit ratings for reports
    for side in ("home", "away"):
        for c in ("off_db_epa_adj", "def_db_epa_adj", "off_rush_epa_adj", "def_rush_epa_adj",
                  "off_sack_rate_adj", "def_sack_rate_adj", "off_xpass_rate", "def_xpass_rate",
                  "off_third_rate", "off_rz_td_rate", "off_int_rate", "def_int_rate", "off_cpoe"):
            out[f"{side}_{c}"] = side_vals[side][c].to_numpy(dtype=float)
    return out
