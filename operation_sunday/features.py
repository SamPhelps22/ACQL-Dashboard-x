"""Point-in-time features: each forecast sees only what was known at its cutoff.

One chronological pass over the games. Before the features for a week are
written, every game whose result was published by that week's cutoff
(kickoff + settings.result_delay_hours <= cutoff) has updated the team states;
nothing else has. A Thursday game of the same week is therefore never in its
own week's features, and nor is anything later.

Feature families (FAMILIES) and their point-in-time status:

  team_strength  Elo and a Kalman team-strength filter (margin and total),
                 from published results only.                   eligible
  rest           days since each team's previous game, from the schedule
                 (published before the season).                 eligible
  travel         time zones crossed by the visitor, from team home zones.
                                                                eligible
  situational    division game, neutral site, dome, postseason, week number.
                                                                eligible
  market         a market snapshot timestamped at or before the cutoff.
                 Historical Thursday snapshots are NOT archived, so in the
                 backtest this family is empty; the closing line exists but
                 is benchmark-only (CLOSING_BENCHMARK).        eligible when snapshot exists
  qb             nflverse lists the ACTUAL starter, known only at kickoff.
                 Excluded from leakage-sensitive evaluation.   not testable
  injuries       no timestamped historical injury reports here. not testable
  weather        historical values are observations, not forecasts. excluded
  tactical, drive_sim
                 need play-by-play with point-in-time aggregation; not built
                 in this release.                              not available
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .config import Settings
from .schedule import deadline_for

FEATURE_VERSION = "fv-1.0"

FAMILIES = {
    "team_strength": ["elo_diff", "kal_margin", "kal_unc"],
    "rest": ["rest_diff", "short_week_diff", "off_bye_diff"],
    "travel": ["tz_shift"],
    "situational": ["div_game", "neutral", "dome", "postseason", "early_season"],
    "market": ["mkt_logit"],
}
UNAVAILABLE_FAMILIES = {
    "qb": "Starting QB is only known for sure at kickoff in this data (nflverse lists actual starters); "
          "no timestamped Thursday starter evidence exists, so it is excluded from leakage-sensitive evaluation.",
    "injuries": "No timestamped historical injury reports are stored; post-cutoff injury news cannot be separated.",
    "weather": "Historical temperature/wind are game-time observations, not forecasts available Thursday.",
    "tactical": "Needs point-in-time play-by-play matchup aggregates; not built in this release.",
    "drive_sim": "Needs point-in-time drive-level play-by-play; not built in this release.",
}
CLOSING_BENCHMARK = "close_spread"

# team home time zone (hours from UTC, standard time) - for travel only
TEAM_TZ = {
    **{t: -5 for t in "ATL BAL BUF CAR CIN CLE DET IND JAX MIA NE NYG NYJ PHI PIT TB WAS".split()},
    **{t: -6 for t in "CHI DAL GB HOU KC MIN NO TEN".split()},
    **{t: -7 for t in "ARI DEN".split()},
    **{t: -8 for t in "LA LAC LV SEA SF".split()},
}
DOMES = {"dome"}


@dataclass
class MarketSnapshot:
    """A market price available at a known time. Used only if taken_at <= cutoff."""
    game_id: str
    taken_at: datetime
    home_prob: float | None = None
    home_spread: float | None = None   # + = home favoured by this many points
    source: str = ""


# ---- team-state models ------------------------------------------------------------
class Elo:
    """FiveThirtyEight-style Elo. Literature defaults, NOT tuned on evaluation data."""
    K, HFA, REVERT = 20.0, 48.0, 1 / 3

    def __init__(self):
        self.r: dict[str, float] = {}
        self.season: dict[str, int] = {}

    def get(self, team, season):
        if team in self.season and self.season[team] != season:
            self.r[team] = 1505 + (self.r[team] - 1505) * (1 - self.REVERT)
            self.season[team] = season
        self.season.setdefault(team, season)
        return self.r.setdefault(team, 1505.0)

    def update(self, home, away, season, margin, neutral):
        rh, ra = self.get(home, season), self.get(away, season)
        diff = rh - ra + (0 if neutral else self.HFA)
        exp = 1 / (1 + 10 ** (-diff / 400))
        actual = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        mult = math.log(abs(margin) + 1) * 2.2 / ((diff if margin > 0 else -diff) * 0.001 + 2.2)
        delta = self.K * mult * (actual - exp)
        self.r[home], self.r[away] = rh + delta, ra - delta


class KalmanStrength:
    """Bayesian team strength: margin = s_home - s_away + hfa + noise.

    Each team's strength has a Gaussian posterior; a result updates both teams
    exactly (two-team Kalman step). Weekly drift adds variance; a new season
    shrinks every team 1/3 toward zero and widens it. A second filter does the
    same for scoring level, giving an expected total. Parameters are fixed
    priors, not tuned on evaluation data."""
    SIGMA, PRIOR_VAR, WEEK_DRIFT, SEASON_KEEP, SEASON_VAR = 13.5, 36.0, 0.25, 2 / 3, 16.0
    HFA = 2.0
    T_SIGMA, T_PRIOR_VAR, T_MEAN = 13.0, 9.0, 44.0

    def __init__(self):
        self.m: dict[str, float] = {}
        self.v: dict[str, float] = {}
        self.t: dict[str, float] = {}
        self.tv: dict[str, float] = {}
        self.season: dict[str, int] = {}
        self.last: dict[str, datetime] = {}
        self.hfa = self.HFA
        self.total_mean = self.T_MEAN

    def _touch(self, team, season, when):
        if team not in self.m:
            self.m[team], self.v[team], self.t[team], self.tv[team] = 0.0, self.PRIOR_VAR, 0.0, self.T_PRIOR_VAR
            self.season[team], self.last[team] = season, when
            return
        if self.season[team] != season:
            self.m[team] *= self.SEASON_KEEP
            self.v[team] = self.v[team] * self.SEASON_KEEP ** 2 + self.SEASON_VAR
            self.t[team] *= 0.5
            self.tv[team] = self.tv[team] * 0.25 + self.T_PRIOR_VAR / 2
            self.season[team] = season
        weeks = max(0.0, (when - self.last[team]).days / 7)
        self.v[team] += self.WEEK_DRIFT * weeks
        self.last[team] = max(self.last[team], when)

    def predict(self, home, away, season, when, neutral):
        self._touch(home, season, when)
        self._touch(away, season, when)
        mu = self.m[home] - self.m[away] + (0 if neutral else self.hfa)
        var = self.v[home] + self.v[away]
        total = self.total_mean + self.t[home] + self.t[away]
        return mu, math.sqrt(var), total

    def update(self, home, away, season, when, neutral, margin, total):
        mu, _, tmu = self.predict(home, away, season, when, neutral)
        s = self.v[home] + self.v[away] + self.SIGMA ** 2
        err = max(-28.0, min(28.0, margin - mu))
        kh, ka = self.v[home] / s, self.v[away] / s
        self.m[home] += kh * err
        self.m[away] -= ka * err
        self.v[home] *= (1 - kh)
        self.v[away] *= (1 - ka)
        if not neutral:
            self.hfa += 0.002 * err
        ts = self.tv[home] + self.tv[away] + self.T_SIGMA ** 2
        terr = max(-30.0, min(30.0, total - tmu))
        for team in (home, away):
            k = self.tv[team] / ts
            self.t[team] += k * terr
            self.tv[team] *= (1 - k)
        self.total_mean += 0.002 * terr


# ---- the pass ----------------------------------------------------------------------
def _week_groups(games: pd.DataFrame):
    gt = np.where(games["game_type"].eq("REG"), "REG", "POST")
    return games.assign(_gt=gt).groupby(["season", "_gt", "week"], sort=False)


def build_features(games: pd.DataFrame, settings: Settings,
                   snapshots: list[MarketSnapshot] | None = None,
                   cutoffs: dict | None = None) -> pd.DataFrame:
    """One row per non-canceled game, with features as of its week's lock.

    cutoffs may map (season, "REG"/"POST", week) -> UTC datetime to override
    the calendar (used by tests). Returns the games with feature columns, the
    cutoff used, and missing-data flags."""
    g = games[games["status"] != "canceled"].copy()
    g = g[g["season"] >= settings.first_training_season]
    delay = timedelta(hours=settings.result_delay_hours)
    by_game: dict[str, list] = {}
    for s in snapshots or []:
        by_game.setdefault(s.game_id, []).append(s)

    weeks = []
    for (season, gt, week), sub in _week_groups(g):
        key = (int(season), gt, int(week))
        if cutoffs and key in cutoffs:
            cut = cutoffs[key]
        else:
            cut = deadline_for(g, int(season), int(week), settings, gt).lock_utc
        weeks.append((pd.Timestamp(cut), key, sub.index))
    weeks.sort(key=lambda w: w[0])

    final = g[g["status"] == "final"].copy()
    final["published"] = final["kickoff_utc"] + delay
    final = final.sort_values(["published", "game_id"])
    fi = 0
    fin_rows = final.to_dict("records")

    elo, kal = Elo(), KalmanStrength()
    last_game: dict[str, pd.Timestamp] = {}
    g["neutral"] = g["neutral"].astype(float)
    g["div_game"] = g["div_game"].astype(float)
    # days since each team's previous scheduled game (schedule-known)
    long = pd.concat([g[["game_id", "kickoff_utc"]].assign(team=g["home"], side="h"),
                      g[["game_id", "kickoff_utc"]].assign(team=g["away"], side="a")]).sort_values(["team", "kickoff_utc"])
    long["rest"] = long.groupby("team")["kickoff_utc"].diff().dt.days
    rest_h = long[long["side"] == "h"].set_index("game_id")["rest"]
    rest_a = long[long["side"] == "a"].set_index("game_id")["rest"]
    seen_teams: set[str] = set()

    out = {}
    for cut, key, idx in weeks:
        while fi < len(fin_rows) and fin_rows[fi]["published"] <= cut:
            r = fin_rows[fi]
            m = r["home_score"] - r["away_score"]
            elo.update(r["home"], r["away"], r["season"], m, r["neutral"])
            kal.update(r["home"], r["away"], r["season"], r["kickoff_utc"].to_pydatetime(), r["neutral"],
                       m, r["home_score"] + r["away_score"])
            seen_teams.update((r["home"], r["away"]))
            fi += 1
        for i, r in zip(idx, g.loc[idx].itertuples()):
            flags = []
            eh, ea = elo.get(r.home, r.season), elo.get(r.away, r.season)
            mu, unc, tot = kal.predict(r.home, r.away, r.season, r.kickoff_utc.to_pydatetime(), r.neutral)
            if r.home not in seen_teams or r.away not in seen_teams:
                flags.append("no_team_history")
            rest = [rest_h.get(r.game_id, np.nan), rest_a.get(r.game_id, np.nan)]
            rest = [np.nan if (x is None or pd.isna(x) or x > 60) else float(x) for x in rest]  # >60 days = new season
            if any(np.isnan(x) for x in rest):
                flags.append("rest_unknown")
            rh, ra = (min(max(x, 4), 14) if not np.isnan(x) else 7 for x in rest)
            tz_h, tz_a = TEAM_TZ.get(r.home), TEAM_TZ.get(r.away)
            if tz_h is None or tz_a is None:
                flags.append("team_zone_unknown")
                shift = 0.0
            else:
                shift = 0.0 if r.neutral else float(tz_a - tz_h)  # + = visitor travelled west->east
            mkt = np.nan
            mkt_ts = None
            cands = [s for s in by_game.get(r.game_id, []) if pd.Timestamp(s.taken_at) <= cut]
            late = [s for s in by_game.get(r.game_id, []) if pd.Timestamp(s.taken_at) > cut]
            if late:
                flags.append("market_after_cutoff_ignored")
            if cands:
                s = max(cands, key=lambda s: s.taken_at)
                p = s.home_prob
                if p is None and s.home_spread is not None:
                    p = 0.5 * (1 + math.erf(s.home_spread / 13.45 / math.sqrt(2)))
                if p is not None:
                    p = min(max(p, 1e-4), 1 - 1e-4)
                    mkt, mkt_ts = math.log(p / (1 - p)), s.taken_at
            else:
                flags.append("no_market_snapshot")
            if r.roof == "unknown":
                flags.append("roof_unknown")
            out[i] = {
                "cutoff_utc": cut, "feature_cutoff_utc": cut,
                "elo_diff": eh - ea, "kal_margin": mu, "kal_unc": unc, "kal_total": tot,
                "rest_diff": rh - ra, "short_week_diff": float(rh <= 5) - float(ra <= 5),
                "off_bye_diff": float(rh >= 12) - float(ra >= 12), "tz_shift": shift,
                "dome": float(r.roof in DOMES),
                "postseason": float(key[1] == "POST"), "early_season": float(key[1] == "REG" and key[2] <= 3),
                "mkt_logit": mkt, "market_ts": mkt_ts, "missing_flags": flags,
            }
    feats = pd.DataFrame.from_dict(out, orient="index")
    res = g.join(feats, how="inner")
    res["home_win"] = np.where(res["status"] == "final",
                               np.where(res["home_score"] > res["away_score"], 1.0,
                                        np.where(res["home_score"] < res["away_score"], 0.0, 0.5)), np.nan)
    res["margin"] = res["home_score"] - res["away_score"]
    res["total"] = res["home_score"] + res["away_score"]
    res["published_utc"] = res["kickoff_utc"] + delay
    res["week_key"] = list(zip(res["season"], np.where(res["game_type"].eq("REG"), "REG", "POST"), res["week"]))
    return res.sort_values(["cutoff_utc", "kickoff_utc", "game_id"])
