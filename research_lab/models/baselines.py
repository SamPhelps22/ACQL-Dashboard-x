"""Benchmarks: the market, Challenger's Elo, and a plain logistic regression.

* Market (closing, de-vigged moneyline) and Market (closing spread) see the
  closing numbers, so they are labelled `closing_retrospective`: they are the
  best available market benchmark, not something a pre-deadline card could use.
* Challenger Elo re-implements nfl_pickem/nflpickem/models/elo.py with the
  parameters in nfl_pickem/config.toml (initial 1505, K 20, home 48, season
  regression 1/3, 538 margin-of-victory multiplier). nfl_pickem itself needs
  DuckDB, which this environment lacks, so it is not imported; the
  re-implementation is checked against the published formula in tests.
* Logistic: home win on season-to-date point differential per game, fitted
  on every earlier game.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .. import config
from .base import Model, expit, logistic, logit, margin_to_p, norm_ppf


def american_to_prob(odds):
    o = np.asarray(odds, float)
    return np.where(o < 0, -o / (-o + 100.0), 100.0 / (o + 100.0))


def devig(home_ml, away_ml):
    """Two-way moneylines to the home side's fair probability (proportional margin removal)."""
    ph, pa = american_to_prob(home_ml), american_to_prob(away_ml)
    return ph / (ph + pa)


def spread_p_curve(snap_games: pd.DataFrame) -> tuple[float, float]:
    """Logistic fit of home win on the closing spread, on completed earlier games."""
    g = snap_games[snap_games["spread_line"].notna() & snap_games["home_win"].isin([0.0, 1.0])]
    g = g[g["season"] >= g["season"].max() - 9] if len(g) else g
    if len(g) < 300:
        return 0.0, 0.145
    X = np.column_stack([np.ones(len(g)), g["spread_line"].values])
    b = logistic(X, g["home_win"].values, lam=0.1)
    return float(b[0]), float(b[1])


class MarketMoneyline(Model):
    name = "market_ml_close"
    version = "1"
    info_set = config.CLOSING_RETRO
    uses_market = True
    provenance = "nflverse closing moneylines (retrospective)"

    def predict(self, snap, week):
        p = devig(week["home_moneyline"], week["away_moneyline"])
        a, b = spread_p_curve(snap.games)
        fallback = expit(a + b * week["spread_line"].values)
        miss = np.isnan(p)
        p = np.where(miss, fallback, p)
        return pd.DataFrame({"game_id": week["game_id"].values, "p_home": p, "exp_margin": week["spread_line"].values,
                             "exp_total": week["total_line"].values, "margin_sd": config.MARGIN_SD,
                             "missing": [{"moneyline": bool(m)} for m in miss]})


class MarketSpread(Model):
    name = "market_spread_close"
    version = "1"
    info_set = config.CLOSING_RETRO
    uses_market = True
    provenance = "nflverse closing spread (retrospective), win curve fitted on earlier seasons"

    def predict(self, snap, week):
        a, b = spread_p_curve(snap.games)
        p = expit(a + b * week["spread_line"].values)
        return pd.DataFrame({"game_id": week["game_id"].values, "p_home": p, "exp_margin": week["spread_line"].values,
                             "exp_total": week["total_line"].values, "margin_sd": config.MARGIN_SD})


# ---- Challenger's Elo ---------------------------------------------------------------------
ELO = dict(initial=1505.0, k=20.0, hfa=48.0, regress=0.333)


def elo_expected(diff: float) -> float:
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))


def mov_mult(margin: float, elo_diff_winner: float) -> float:
    return math.log(abs(margin) + 1.0) * 2.2 / (0.001 * elo_diff_winner + 2.2)


class ChallengerElo(Model):
    name = "challenger_elo"
    version = "nfl_pickem-elo-defaults"
    provenance = "re-implementation of nfl_pickem Elo with its config.toml parameters"

    def __init__(self):
        self.reset()

    def reset(self):
        self.r: dict[str, float] = {}
        self.done: list[str] = []
        self.season = None

    def _rating(self, t):
        return self.r.setdefault(t, ELO["initial"])

    def _update(self, games: pd.DataFrame):
        for _, g in games.iterrows():
            if g["season"] != self.season:
                if self.season is not None:
                    for t in self.r:
                        self.r[t] += (ELO["initial"] - self.r[t]) * ELO["regress"]
                self.season = g["season"]
            rh, ra = self._rating(g["home_team"]), self._rating(g["away_team"])
            hfa = 0.0 if g["neutral"] else ELO["hfa"]
            exp = elo_expected(rh - ra + hfa)
            res = g["home_win"]
            m = g["margin"]
            if m != 0:
                wd = (rh + hfa - ra) if m > 0 else (ra - rh - hfa)
                mult = mov_mult(m, wd)
            else:
                mult = 1.0
            delta = ELO["k"] * mult * (res - exp)
            self.r[g["home_team"]] = rh + delta
            self.r[g["away_team"]] = ra - delta

    def sync(self, snap):
        ids = list(snap.games["game_id"])
        if self.done != ids[:len(self.done)]:
            self.reset()
        new = snap.games.iloc[len(self.done):]
        self._update(new)
        self.done = ids

    def predict(self, snap, week):
        self.sync(snap)
        rows = []
        for _, g in week.iterrows():
            # a new season's ratings regress before its first game
            rh, ra = self._rating(g["home_team"]), self._rating(g["away_team"])
            if self.season is not None and g["season"] != self.season:
                rh += (ELO["initial"] - rh) * ELO["regress"]
                ra += (ELO["initial"] - ra) * ELO["regress"]
            hfa = 0.0 if g["neutral"] else ELO["hfa"]
            d = rh - ra + hfa
            rows.append({"game_id": g["game_id"], "p_home": elo_expected(d), "exp_margin": d / 25.0,
                         "margin_sd": config.MARGIN_SD})
        return pd.DataFrame(rows)

    def ratings(self) -> dict:
        return dict(self.r)


class SimpleLogistic(Model):
    """Home win on (season-to-date point differential per game, home minus away), plus home field."""
    name = "logistic_pointdiff"
    version = "1"

    def predict(self, snap, week):
        g = snap.games[snap.games["game_type"].notna()]
        feats = _season_pd(g)
        hist = g[g["home_win"].isin([0.0, 1.0])].copy()
        hist = hist[hist["season"] >= hist["season"].max() - 9]
        x_hist = _diff(hist, feats)
        keep = ~np.isnan(x_hist)
        X = np.column_stack([np.ones(keep.sum()), x_hist[keep], 1 - hist["neutral"].values[keep]])
        beta = logistic(X, hist["home_win"].values[keep], lam=1.0)
        cur = _current_pd(g, week)
        Xw = np.column_stack([np.ones(len(week)), cur, 1 - week["neutral"].values])
        p = expit(Xw @ beta)
        return pd.DataFrame({"game_id": week["game_id"].values, "p_home": p,
                             "exp_margin": norm_ppf(p) * config.MARGIN_SD})


def long_form(g: pd.DataFrame) -> pd.DataFrame:
    """Two rows a game, one per team, with that team's margin."""
    h = g[["game_id", "season", "kickoff", "home_team", "margin"]].rename(columns={"home_team": "team"})
    a = g[["game_id", "season", "kickoff", "away_team", "margin"]].rename(columns={"away_team": "team"})
    a = a.assign(margin=-a["margin"])
    return pd.concat([h.assign(side="home"), a.assign(side="away")]).sort_values(["kickoff", "game_id"])


def _season_pd(g: pd.DataFrame) -> dict:
    """game_id -> (home pre-game pd/g, away pre-game pd/g) within the season, from earlier games only."""
    lf = long_form(g)
    grp = lf.groupby(["season", "team"])["margin"]
    lf["pre"] = (grp.cumsum() - lf["margin"]) / grp.cumcount().replace(0, np.nan)
    piv = lf.pivot_table(index="game_id", columns="side", values="pre", aggfunc="first")
    return {i: (r.get("home", np.nan), r.get("away", np.nan)) for i, r in piv.iterrows()}


def _diff(hist, feats):
    return np.array([feats[i][0] - feats[i][1] if i in feats else np.nan for i in hist["game_id"]], float)


def _current_pd(g, week):
    lf = long_form(g)
    means = lf.groupby(["season", "team"])["margin"].mean().to_dict()
    return np.array([means.get((r.season, r.home_team), 0.0) - means.get((r.season, r.away_team), 0.0)
                     for r in week.itertuples()], float)
