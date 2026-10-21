"""Model E - Bayesian dynamic team strength (a Kalman filter on points).

State, per team: offence o and defence d, in points against an average team,
with a 2x2 covariance; one shared home-field edge h with its own variance.
Each completed game is two observations:

    home points = mu + h/2 + o_home - d_away + e        e ~ N(0, OBS_SD^2)
    away points = mu - h/2 + o_away - d_home + e

The filter updates the five states involved jointly (cross-team covariances
are not carried: an assumed-density approximation). Between weeks every
team's variance grows by DRIFT per week; between seasons means shrink by
REGRESS toward 0 and variance grows by OFFSEASON_VAR (roster turnover).
A team whose expected quarterback has changed gets QB_CHANGE_VAR more
offensive variance at prediction time (uncertainty, not a guessed penalty).

The forecast is the posterior predictive: margin ~ N(mean, state var + 2*OBS_SD^2),
so a team with few games behind it gets a wider, more modest probability.
`bayes_plugin` is the identical filter forecasting with a fixed spread - the
comparison isolates what the explicit uncertainty is worth.

Hyper-parameters were chosen on 2007-2011 only (see tune()), before any
development season is scored.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from .base import Model, margin_to_p, norm_cdf

#: Chosen by tune() on 2008-2011 (log loss 0.6167 there); obs_sd sat at the low end of its grid.
PARAMS = dict(obs_sd=9.0, drift=0.25, regress=0.30, offseason_var=6.0, prior_var=16.0, h0=2.5, h_var=1.0,
              h_drift=0.003, mu0=21.5, qb_change_var=4.0)


class BayesTeams(Model):
    name = "E_bayes"
    version = "1"

    def __init__(self, params: dict | None = None, plugin: bool = False):
        self.p = dict(PARAMS, **(params or {}))
        self.plugin = plugin
        if plugin:
            self.name = "E_bayes_plugin"
        self.reset()

    def reset(self):
        self.m: dict[str, np.ndarray] = {}
        self.P: dict[str, np.ndarray] = {}
        self.h, self.hv = self.p["h0"], self.p["h_var"]
        self.mu = self.p["mu0"]
        self.season = None
        self.last_ts = None
        self.done: list[str] = []

    def _team(self, t):
        if t not in self.m:
            self.m[t] = np.zeros(2)
            self.P[t] = np.eye(2) * self.p["prior_var"]
        return self.m[t], self.P[t]

    def _advance(self, season, ts):
        if self.season is not None and season != self.season:
            k = 1 - self.p["regress"]
            for t in self.m:
                self.m[t] = self.m[t] * k
                self.P[t] = self.P[t] * k * k + np.eye(2) * self.p["offseason_var"]
            self.last_ts = None
        self.season = season
        if self.last_ts is not None:
            weeks = max(0.0, (ts - self.last_ts).total_seconds() / (7 * 86400))
            if weeks > 0:
                for t in self.P:
                    self.P[t] = self.P[t] + np.eye(2) * self.p["drift"] * weeks
                self.hv += self.p["h_drift"] * weeks
        self.last_ts = ts

    def _update(self, g):
        self._advance(g["season"], g["kickoff"])
        H, A = g["home_team"], g["away_team"]
        mh, Ph = self._team(H)
        ma, Pa = self._team(A)
        x = np.array([mh[0], mh[1], ma[0], ma[1], self.h])
        P = np.zeros((5, 5))
        P[:2, :2], P[2:4, 2:4], P[4, 4] = Ph, Pa, self.hv
        hf = 0.0 if g["neutral"] else 0.5
        Hm = np.array([[1, 0, 0, -1, hf], [0, -1, 1, 0, -hf]], float)
        y = np.array([g["home_score"], g["away_score"]], float) - self.mu
        R = np.eye(2) * self.p["obs_sd"] ** 2
        S = Hm @ P @ Hm.T + R
        K = P @ Hm.T @ np.linalg.inv(S)
        x = x + K @ (y - Hm @ x)
        P = (np.eye(5) - K @ Hm) @ P
        self.m[H], self.P[H] = x[:2], P[:2, :2]
        self.m[A], self.P[A] = x[2:4], P[2:4, 2:4]
        self.h, self.hv = x[4], P[4, 4]
        # league scoring level: slow running mean
        self.mu += 0.002 * ((g["home_score"] + g["away_score"]) / 2 - self.mu)

    def sync(self, snap):
        ids = list(snap.games["game_id"])
        if self.done != ids[:len(self.done)]:
            self.reset()
        for _, g in snap.games.iloc[len(self.done):].iterrows():
            self._update(g)
        self.done = ids

    def qb_changed(self, snap, team) -> bool:
        """Did the team's latest main passer differ from its usual one over its previous 6 games?"""
        q = snap.qb_games
        if not len(q):
            return False
        mine = q[(q["team"] == team) & (q["main"] == True)].merge(  # noqa: E712
            snap.games[["game_id", "kickoff"]], on="game_id").sort_values("kickoff")
        if len(mine) < 3:
            return False
        last = mine["passer_id"].iloc[-1]
        usual = mine["passer_id"].iloc[-7:-1].mode()
        return bool(len(usual) and usual.iloc[0] != last)

    def predict(self, snap, week):
        self.sync(snap)
        rows = []
        new_season = self.season is not None and int(week["season"].iloc[0]) != self.season
        for _, g in week.iterrows():
            out = {}
            for side in ("home_team", "away_team"):
                m, P = self._team(g[side])
                m, P = m.copy(), P.copy()
                if new_season:
                    k = 1 - self.p["regress"]
                    m, P = m * k, P * k * k + np.eye(2) * self.p["offseason_var"]
                if not new_season and self.qb_changed(snap, g[side]):
                    P[0, 0] += self.p["qb_change_var"]
                out[side] = (m, P)
            (mh, Ph), (ma, Pa) = out["home_team"], out["away_team"]
            hf = 0.0 if g["neutral"] else 1.0
            mean = hf * self.h + (mh[0] - ma[1]) - (ma[0] - mh[1])
            var_state = Ph[0, 0] + Ph[1, 1] + Pa[0, 0] + Pa[1, 1] - 2 * Ph[0, 1] - 2 * Pa[0, 1] + hf * self.hv
            sd = np.sqrt(var_state + 2 * self.p["obs_sd"] ** 2)
            total = 2 * self.mu + mh[0] + ma[0] - ma[1] - mh[1]
            if self.plugin:
                sd = config.MARGIN_SD
            rows.append({"game_id": g["game_id"], "p_home": float(np.clip(norm_cdf(mean / sd), 1e-4, 1 - 1e-4)),
                         "exp_margin": mean, "exp_total": total, "margin_sd": sd,
                         "missing": {"state_sd": float(np.sqrt(var_state))}})
        return pd.DataFrame(rows)

    def ratings(self) -> pd.DataFrame:
        return pd.DataFrame([{"team": t, "off": m[0], "def": m[1], "off_sd": np.sqrt(self.P[t][0, 0]),
                              "def_sd": np.sqrt(self.P[t][1, 1])} for t, m in self.m.items()])


GRID = {"obs_sd": (9.0, 10.0, 11.0), "drift": (0.1, 0.25, 0.5), "regress": (0.2, 0.3, 0.45),
        "offseason_var": (2.0, 6.0, 12.0)}


def tune(store, seasons=range(2008, 2012), log=print) -> dict:
    """Coordinate search on 2008-2011 log loss (the filter warms up from 2006). Never touches 2012+."""
    from ..backtest import engine
    best = dict(PARAMS)

    def score(params):
        m = BayesTeams(params)
        df = pd.concat([engine.predict_week(m, store, s, w) for s, w in engine.weeks(store, seasons)])
        r = df.merge(store.games[["game_id", "home_win"]], on="game_id")
        r = r[r["home_win"].isin([0.0, 1.0])]
        p = r["p_home_raw"].astype(float).values
        y = r["home_win"].values
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))

    cur = score(best)
    for _ in range(2):
        for k, vals in GRID.items():
            for v in vals:
                trial = dict(best, **{k: v})
                s = score(trial)
                if s < cur - 1e-5:
                    cur, best = s, trial
        log(f"  tune pass: {cur:.4f} {best}")
    return best
