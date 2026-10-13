"""Point-in-time feature engineering.

Every feature for a game is computed from information available strictly before
that game's *prediction cutoff* (see ``compute_cutoffs``):

* Team performance states are built *after* each completed game and become
  available at kickoff + 4h. A game's features are joined with ``merge_asof``
  (direction=backward, exact matches excluded) on its cutoff, so a state from a
  game that had not finished by the cutoff can never leak in.
* Odds snapshots are taken from the latest capture at or before the cutoff
  (nflverse closing lines without a timestamp are a documented proxy).
* Schedule facts (home/away, rest days, division game, roof, week) are known
  in advance and are not leakage.

``validate_point_in_time`` enforces these rules and raises ``LeakageError``.
Feature definitions are documented in docs/FEATURES.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .models.elo import GAME_DURATION, EloModel, EloParams
from .models.market import market_probabilities

log = logging.getLogger(__name__)

POSTSEASON = {"WC", "DIV", "CON", "SB", "POST"}

BASE_FEATURES = [
    "elo_diff", "home_field",
    "off_epa_l4_diff", "def_epa_l4_diff", "off_epa_l8_diff", "def_epa_l8_diff",
    "off_epa_season_diff", "def_epa_season_diff",
    "success_l8_diff", "def_success_l8_diff", "explosive_l8_diff", "def_explosive_l8_diff",
    "turnover_l8_diff", "takeaway_l8_diff",
    "rest_diff", "home_short_week", "away_short_week", "home_off_bye", "away_off_bye",
    "early_season", "week", "is_postseason", "div_game", "dome",
]
QB_FEATURES = ["home_qb_changed", "away_qb_changed", "qb_exp_diff"]
MARKET_FEATURES = ["market_home_prob", "market_home_spread"]
WEATHER_FEATURES = ["wind", "temp"]

METRICS = ["off_epa", "def_epa", "success", "def_success", "explosive", "def_explosive", "turnover", "takeaway"]


class LeakageError(AssertionError):
    """A feature was computed with information unavailable at the prediction cutoff."""


@dataclass
class FeatureSettings:
    short_rest_days: int = 5
    bye_rest_days: int = 13
    early_season_weeks: int = 4
    rolling_short: int = 4
    rolling_long: int = 8
    shrinkage_games: float = 3.0
    prior_season_weight: float = 0.4
    use_weather: bool = False
    use_qb_features: bool = True
    ml_include_market_features: bool = False

    @classmethod
    def from_config(cls, cfg: dict) -> "FeatureSettings":
        return cls(**{k: cfg[k] for k in cls.__dataclass_fields__ if k in cfg})


def model_feature_columns(fs: FeatureSettings) -> list[str]:
    cols = list(BASE_FEATURES)
    if fs.use_qb_features:
        cols += QB_FEATURES
    if fs.ml_include_market_features:
        cols += MARKET_FEATURES
    if fs.use_weather:
        cols += WEATHER_FEATURES
    return cols


# ----------------------------------------------------------------------- cutoffs
def compute_cutoffs(games: pd.DataFrame, mode: str = "slate", offset_hours: float = 1.0,
                    as_of: pd.Timestamp | None = None) -> pd.Series:
    """Prediction cutoff per game (indexed by game_id).

    slate: one cutoff per (season, week) = first kickoff of the week minus offset
    (picks for the whole week lock together, as in a typical pool).
    per_game: each game's own kickoff minus offset.
    as_of: live predictions cannot use data later than 'now'.
    """
    g = games.set_index("game_id")
    if mode == "slate":
        first = g.groupby(["season", "week"])["kickoff_utc"].transform("min")
        cut = first - pd.Timedelta(hours=offset_hours)
    elif mode == "per_game":
        cut = g["kickoff_utc"] - pd.Timedelta(hours=offset_hours)
    else:
        raise ValueError(f"Unknown cutoff mode {mode!r}")
    if as_of is not None:
        cut = cut.clip(upper=pd.Timestamp(as_of))
    return cut


# ------------------------------------------------------------------- team states
def team_game_table(games: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    """One row per team per completed game with per-play rates."""
    done = games[games["game_status"] == "final"]
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        rows.append(pd.DataFrame({
            "game_id": done["game_id"], "season": done["season"], "kickoff_utc": done["kickoff_utc"],
            "team": done[f"{side}_team"], "opp": done[f"{opp}_team"],
            "qb_id": done[f"{side}_qb_id"],
        }))
    from .db import STATS_COLUMNS
    stats = stats.reindex(columns=STATS_COLUMNS)  # tolerate missing play-by-play
    for c in STATS_COLUMNS[2:-1]:
        stats[c] = pd.to_numeric(stats[c], errors="coerce")
    tg = pd.concat(rows, ignore_index=True).merge(stats, on=["game_id", "team"], how="left")
    plays = tg["plays"].where(tg["plays"] > 0)
    dplays = tg["def_plays"].where(tg["def_plays"] > 0)
    tg["off_epa"] = tg["off_epa_sum"] / plays
    tg["def_epa"] = tg["def_epa_sum"] / dplays
    tg["success"] = tg["off_success_sum"] / plays
    tg["def_success"] = tg["def_success_sum"] / dplays
    tg["explosive"] = tg["explosive_plays"] / plays
    tg["def_explosive"] = tg["def_explosive_plays"] / dplays
    tg["turnover"] = tg["turnovers"] / plays
    tg["takeaway"] = tg["takeaways"] / dplays
    tg["available_at"] = tg["kickoff_utc"] + GAME_DURATION
    return tg.sort_values(["team", "kickoff_utc", "game_id"]).reset_index(drop=True)


def league_season_means(tg: pd.DataFrame) -> pd.DataFrame:
    return tg.groupby("season")[METRICS].mean()


def build_team_states(tg: pd.DataFrame, fs: FeatureSettings) -> pd.DataFrame:
    """Rolling state of each team after each of its completed games."""
    if tg.empty:
        return pd.DataFrame(columns=["team", "available_at", "season"])
    league = league_season_means(tg)
    # Prior mean for a season = previous season's league mean (point-in-time).
    prior_league = league.shift(1).reindex(league.index)
    prior_league = prior_league.fillna(league.expanding().mean().shift(1)).fillna(0.0)
    st = tg[["team", "game_id", "season", "kickoff_utc", "available_at", "qb_id"]].copy()
    grp = tg.groupby("team", sort=False)
    for m in METRICS:
        x = tg[m]
        has = x.notna().astype(float)
        xs = x.fillna(0.0)
        prior = tg["season"].map(prior_league[m])
        for k, label in ((fs.rolling_short, "l4"), (fs.rolling_long, "l8")):
            s = xs.groupby(tg["team"]).transform(lambda v: v.rolling(k, min_periods=1).sum())
            n = has.groupby(tg["team"]).transform(lambda v: v.rolling(k, min_periods=1).sum())
            pseudo = fs.shrinkage_games * (k - n).clip(lower=0) / k
            st[f"{m}_{label}"] = (s + pseudo * prior) / (n + pseudo).replace(0, np.nan)
        # season-to-date sums (reset each season)
        st[f"{m}_ssum"] = xs.groupby([tg["team"], tg["season"]]).cumsum()
        st[f"{m}_sn"] = has.groupby([tg["team"], tg["season"]]).cumsum()
    del grp
    return st


def team_season_means(tg: pd.DataFrame) -> pd.DataFrame:
    return tg.groupby(["team", "season"])[METRICS].mean()


# ------------------------------------------------------------------ main builder
def build_features(games: pd.DataFrame, stats: pd.DataFrame, odds: pd.DataFrame,
                   cfg: dict, as_of: pd.Timestamp | None = None,
                   target_game_ids: list[str] | None = None) -> pd.DataFrame:
    """Return one row per target game with point-in-time features and the label.

    ``games`` must contain the full history needed (all seasons used for states).
    """
    fs = FeatureSettings.from_config(cfg["features"])
    pool = cfg["pool"]
    data_cfg = cfg["data"]
    games = games.copy()
    games["kickoff_utc"] = pd.to_datetime(games["kickoff_utc"])
    cutoffs = compute_cutoffs(games, pool["cutoff_mode"], float(pool["cutoff_offset_hours"]), as_of)
    tgt = games if target_game_ids is None else games[games["game_id"].isin(target_game_ids)]
    tgt = tgt[tgt["game_status"] != "canceled"].copy()
    tgt["cutoff"] = tgt["game_id"].map(cutoffs)

    # Team performance states
    tg = team_game_table(games, stats)
    states = build_team_states(tg, fs)
    ts_means = team_season_means(tg)
    league = league_season_means(tg)

    out = tgt[["game_id", "season", "week", "game_type", "kickoff_utc", "cutoff", "home_team",
               "away_team", "location", "game_status", "home_score", "away_score", "div_game",
               "roof", "temp", "wind", "home_qb_id", "away_qb_id", "home_qb_name", "away_qb_name"]].copy()
    out = out.reset_index(drop=True)

    for side in ("home", "away"):
        q = pd.DataFrame({"team": out[f"{side}_team"], "season": out["season"], "cutoff": out["cutoff"],
                          "_ord": np.arange(len(out))})
        if len(states):
            m = pd.merge_asof(q.sort_values("cutoff"),
                              states.rename(columns={"season": "state_season"}).sort_values("available_at"),
                              left_on="cutoff", right_on="available_at", by="team",
                              direction="backward", allow_exact_matches=False).sort_values("_ord")
            m.index = out.index
        else:
            m = q.assign(available_at=pd.NaT, state_season=np.nan, qb_id=None)
            m.index = out.index
        out[f"{side}_feature_ts"] = m["available_at"]
        out[f"{side}_last_qb"] = m.get("qb_id")
        same_season = (m["state_season"] == out["season"]).to_numpy()
        for metric in METRICS:
            for label in ("l4", "l8"):
                col = f"{metric}_{label}"
                out[f"{side}_{col}"] = m[col] if col in m else np.nan
            # season-to-date shrunk toward a prior from last season
            prev = out["season"] - 1
            lg_prev = prev.map(league[metric]) if metric in league else np.nan
            lg_prev = pd.Series(lg_prev, index=out.index).fillna(0.0)
            team_prev = pd.Series([ts_means[metric].get((t, s), np.nan)
                                   for t, s in zip(out[f"{side}_team"], prev)], index=out.index)
            prior = lg_prev + fs.prior_season_weight * (team_prev - lg_prev).fillna(0.0)
            ssum = np.where(same_season, m.get(f"{metric}_ssum", 0.0), 0.0)
            sn = np.where(same_season, m.get(f"{metric}_sn", 0.0), 0.0)
            ssum = np.nan_to_num(ssum.astype(float))
            sn = np.nan_to_num(sn.astype(float))
            out[f"{side}_{metric}_season"] = (ssum + fs.shrinkage_games * prior) / (sn + fs.shrinkage_games)
        out = out.copy()
        out[f"{side}_games_played_season"] = np.nan_to_num(
            np.where(same_season, m.get("off_epa_sn", 0.0), 0.0).astype(float))

    # Elo
    elo = EloModel(EloParams.from_config(cfg["elo"]))
    _, elo_states = elo.run(games)
    for side in ("home", "away"):
        q = pd.DataFrame({"team": out[f"{side}_team"], "season": out["season"], "cutoff": out["cutoff"]})
        out[f"{side}_elo"] = elo.ratings_at(elo_states, q).to_numpy()
    out["elo_home_prob"] = elo.predict(out["home_elo"], out["away_elo"], out["location"])
    out["elo_diff"] = out["home_elo"] - out["away_elo"]

    # Rest / bye / short week from the published schedule (known in advance)
    sched = pd.concat([
        games[["game_id", "season", "kickoff_utc", "home_team"]].rename(columns={"home_team": "team"}),
        games[["game_id", "season", "kickoff_utc", "away_team"]].rename(columns={"away_team": "team"}),
    ])
    sched = sched[sched["game_id"].isin(games.loc[games["game_status"] != "canceled", "game_id"])]
    sched = sched.sort_values(["team", "kickoff_utc"])
    sched["prev_ko"] = sched.groupby("team")["kickoff_utc"].shift(1)
    sched["prev_season"] = sched.groupby("team")["season"].shift(1)
    rest = (sched["kickoff_utc"] - sched["prev_ko"]).dt.total_seconds() / 86400.0
    sched["rest_days"] = np.where(sched["prev_season"] == sched["season"], rest.round(), np.nan)
    rest_map = sched.set_index(["game_id", "team"])["rest_days"]
    for side in ("home", "away"):
        r = pd.Series([rest_map.get((g, t), np.nan) for g, t in zip(out["game_id"], out[f"{side}_team"])],
                      index=out.index)
        out[f"{side}_first_game"] = r.isna().astype(int)
        out[f"{side}_rest_days"] = r.fillna(14.0).clip(upper=14.0)
        out[f"{side}_short_week"] = (r <= fs.short_rest_days).astype(int)
        out[f"{side}_off_bye"] = (r >= fs.bye_rest_days).astype(int)
    out["rest_diff"] = out["home_rest_days"] - out["away_rest_days"]

    # Quarterback: starter listed in the schedule vs. the team's previous starter.
    qb_counts = _qb_start_counts(games)
    for side in ("home", "away"):
        qb = out[f"{side}_qb_id"]
        known = qb.notna() & (qb.astype(str) != "")
        last = out[f"{side}_last_qb"]
        out[f"{side}_qb_changed"] = np.where(known & last.notna(), (qb != last).astype(float), np.nan)
        starts = _lookup_qb_starts(qb_counts, qb, out["cutoff"])
        out[f"{side}_qb_starts"] = np.where(known, starts, np.nan)
        status = np.where(~known, "unknown",
                          np.where(out["game_status"] == "final", "confirmed_starter", "projected_starter"))
        out[f"{side}_quarterback_status"] = status
    out["qb_exp_diff"] = np.log1p(out["home_qb_starts"].clip(upper=100)) - np.log1p(out["away_qb_starts"].clip(upper=100))

    out = out.copy()  # defragment after many column inserts
    # Differentials
    for metric in METRICS:
        for label in ("l4", "l8", "season"):
            out[f"{metric}_{label}_diff"] = out[f"home_{metric}_{label}"] - out[f"away_{metric}_{label}"]
    out["home_field"] = (out["location"].fillna("Home") != "Neutral").astype(int)
    out["is_postseason"] = out["game_type"].isin(POSTSEASON).astype(int)
    out["early_season"] = ((out["week"] <= fs.early_season_weeks) & (out["is_postseason"] == 0)).astype(int)
    out["dome"] = out["roof"].isin(["dome", "closed"]).astype(int)
    out["div_game"] = pd.to_numeric(out["div_game"], errors="coerce").astype(float)
    out["wind"] = np.where(out["dome"] == 1, 0.0, out["wind"])
    out["temp"] = np.where(out["dome"] == 1, 70.0, out["temp"])

    out = out.copy()
    # Market
    mk = market_probabilities(odds, cutoffs[cutoffs.index.isin(out["game_id"])],
                              closing_line_proxy=bool(data_cfg.get("closing_line_proxy", True)),
                              stale_hours=float(data_cfg.get("stale_odds_hours", 24)))
    out = out.merge(mk, on="game_id", how="left")
    out["odds_status"] = out["odds_status"].fillna("missing")

    # Label: 1 home win, 0 away win, 0.5 tie, NaN not played
    hs, as_ = out["home_score"].astype(float), out["away_score"].astype(float)
    final = out["game_status"] == "final"
    out["home_result"] = np.where(final, np.where(hs > as_, 1.0, np.where(hs < as_, 0.0, 0.5)), np.nan)
    return out.sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)


def _qb_start_counts(games: pd.DataFrame) -> pd.DataFrame:
    done = games[games["game_status"] == "final"]
    qb = pd.concat([
        done[["kickoff_utc", "home_qb_id"]].rename(columns={"home_qb_id": "qb_id"}),
        done[["kickoff_utc", "away_qb_id"]].rename(columns={"away_qb_id": "qb_id"}),
    ]).dropna()
    qb = qb[qb["qb_id"].astype(str) != ""].sort_values("kickoff_utc")
    qb["starts"] = qb.groupby("qb_id").cumcount() + 1
    qb["available_at"] = qb["kickoff_utc"] + GAME_DURATION
    return qb


def _lookup_qb_starts(qb_counts: pd.DataFrame, qb: pd.Series, cutoff: pd.Series) -> np.ndarray:
    q = pd.DataFrame({"qb_id": qb.fillna("__none__").astype(str), "cutoff": cutoff, "_ord": np.arange(len(qb))})
    if qb_counts.empty:
        return np.zeros(len(qb))
    m = pd.merge_asof(q.sort_values("cutoff"), qb_counts[["qb_id", "available_at", "starts"]]
                      .assign(qb_id=lambda d: d["qb_id"].astype(str)).sort_values("available_at"),
                      left_on="cutoff", right_on="available_at", by="qb_id",
                      direction="backward", allow_exact_matches=False).sort_values("_ord")
    return m["starts"].fillna(0).to_numpy(dtype=float)


# -------------------------------------------------------------------- validation
def validate_point_in_time(features: pd.DataFrame) -> None:
    """Raise LeakageError if any feature source is not strictly before the cutoff."""
    problems = []
    if (features["cutoff"] > features["kickoff_utc"]).any():
        problems.append("cutoff after kickoff")
    for side in ("home", "away"):
        ts = features[f"{side}_feature_ts"]
        bad = ts.notna() & (ts >= features["cutoff"])
        if bad.any():
            problems.append(f"{side} team state after cutoff in {list(features.loc[bad, 'game_id'][:3])}")
    if "odds_captured_at" in features:
        oc = pd.to_datetime(features["odds_captured_at"])
        bad = oc.notna() & (oc > features["cutoff"])
        if bad.any():
            problems.append(f"odds captured after cutoff in {list(features.loc[bad, 'game_id'][:3])}")
    if problems:
        raise LeakageError("; ".join(problems))


def team_features_long(features: pd.DataFrame, model_version: str = "") -> pd.DataFrame:
    """Long per-team view for the `team_features` table."""
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        rows.append(pd.DataFrame({
            "game_id": features["game_id"], "team": features[f"{side}_team"],
            "opponent": features[f"{opp}_team"], "is_home": int(side == "home"),
            "feature_timestamp": features[f"{side}_feature_ts"], "prediction_cutoff": features["cutoff"],
            "elo_rating": features[f"{side}_elo"],
            "offensive_epa": features[f"{side}_off_epa_season"],
            "defensive_epa": features[f"{side}_def_epa_season"],
            "recent_epa": features[f"{side}_off_epa_l4"] - features[f"{side}_def_epa_l4"],
            "off_epa_l4": features[f"{side}_off_epa_l4"], "def_epa_l4": features[f"{side}_def_epa_l4"],
            "off_epa_l8": features[f"{side}_off_epa_l8"], "def_epa_l8": features[f"{side}_def_epa_l8"],
            "success_l8": features[f"{side}_success_l8"], "explosive_l8": features[f"{side}_explosive_l8"],
            "turnover_l8": features[f"{side}_turnover_l8"], "takeaway_l8": features[f"{side}_takeaway_l8"],
            "rest_days": features[f"{side}_rest_days"], "short_week": features[f"{side}_short_week"],
            "off_bye": features[f"{side}_off_bye"],
            "quarterback_status": features[f"{side}_quarterback_status"],
            "quarterback_changed": features[f"{side}_qb_changed"],
            "quarterback_prior_starts": features[f"{side}_qb_starts"],
            "games_played_season": features[f"{side}_games_played_season"],
            "model_version": model_version,
        }))
    return pd.concat(rows, ignore_index=True)


def save_team_features(con, features: pd.DataFrame, model_version: str = "") -> int:
    tf = team_features_long(features, model_version)
    con.register("_tf", tf)
    con.execute("CREATE TABLE IF NOT EXISTS team_features AS SELECT * FROM _tf WHERE FALSE")
    con.execute("DELETE FROM team_features WHERE game_id IN (SELECT game_id FROM _tf)")
    con.execute("INSERT INTO team_features SELECT * FROM _tf")
    con.unregister("_tf")
    return len(tf)
