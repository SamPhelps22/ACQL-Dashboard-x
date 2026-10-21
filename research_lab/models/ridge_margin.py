"""A shared engine for the feature models (A, C, F): ridge regression on the home margin.

Taught on point-in-time feature rows of games completed before the forecast.
The penalty is chosen once per season, on earlier seasons only: fit on all but
the latest completed season, score that season, pick the best penalty.
The margin becomes a probability through a normal curve whose spread is the
training residual spread.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from ..features.bank import bank_for, training_rows
from .base import Model, Standardizer, margin_to_p, ridge

PENALTIES = (1.0, 10.0, 100.0, 1000.0, 10000.0)
TRAIN_SEASONS = 10


class RidgeMarginModel(Model):
    #: feature-bank builders: {name: fn}
    builders: dict = {}
    #: training window: the last `train_seasons` seasons, never before `train_from`
    train_seasons = TRAIN_SEASONS
    train_from = config.FIRST_SEASON + 1

    def columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Model inputs from merged builder rows (one row per game)."""
        raise NotImplementedError

    def __init__(self):
        self._lam: dict[int, float] = {}

    def _rows(self, snap, since):
        frames = []
        for name, fn in self.builders.items():
            frames.append(training_rows(snap, name, fn, since, info_set=self.info_set))
        df = frames[0]
        for f in frames[1:]:
            df = df.merge(f.drop(columns=[c for c in ("margin", "home_win", "total_points", "home_score",
                                                      "away_score") if c in f.columns]), on="game_id", how="inner")
        return df

    def _week(self, snap, week):
        bank = bank_for(snap.store)
        s, w = int(week["season"].iloc[0]), int(week["week"].iloc[0])
        frames = [bank.week_rows(name, fn, s, w, self.info_set) for name, fn in self.builders.items()]
        df = frames[0]
        for f in frames[1:]:
            df = df.merge(f, on="game_id", how="left")
        return df.set_index("game_id").reindex(week["game_id"]).reset_index()

    def _design(self, df, scaler=None):
        X = self.columns(df).astype(float)
        names = list(X.columns)
        X = X.values
        if scaler is None:
            scaler = Standardizer().fit(X)
        Z = scaler.transform(X)
        return np.column_stack([np.ones(len(Z)), Z]), scaler, names

    def _choose(self, train: pd.DataFrame, season: int) -> float:
        if season in self._lam:
            return self._lam[season]
        last = train["season"].max()
        fit, val = train[train["season"] < last], train[train["season"] == last]
        best, lam_best = np.inf, PENALTIES[2]
        if len(fit) > 500 and len(val) > 100:
            X, sc, _ = self._design(fit)
            Xv, _, _ = self._design(val, sc)
            for lam in PENALTIES:
                b = ridge(X, fit["margin"].values, lam)
                err = np.mean((Xv @ b - val["margin"].values) ** 2)
                if err < best:
                    best, lam_best = err, lam
        self._lam[season] = lam_best
        return lam_best

    def predict(self, snap, week):
        season = int(week["season"].iloc[0])
        since = max(season - self.train_seasons, self.train_from)
        train = self._rows(snap, since)
        train = train.merge(snap.games[["game_id", "season"]], on="game_id", how="left", suffixes=("_x", ""))
        train = train[train["margin"].notna()]
        lam = self._choose(train, season)
        X, sc, names = self._design(train)
        beta = ridge(X, train["margin"].values, lam)
        resid = train["margin"].values - X @ beta
        sd = float(np.sqrt(np.mean(resid ** 2)))
        cur = self._week(snap, week)
        Xw, _, _ = self._design(cur, sc)
        m = Xw @ beta
        tot_ok = train["total_points"].notna().values
        bt = ridge(X[tot_ok], train["total_points"].values[tot_ok], lam)
        total = Xw @ bt
        self.last_coef = dict(zip(["intercept", *names], beta))
        self.last_lambda = lam
        return pd.DataFrame({"game_id": week["game_id"].values, "p_home": margin_to_p(m, sd), "exp_margin": m,
                             "exp_total": total, "margin_sd": sd, "missing": self.missing(cur)})

    def missing(self, cur: pd.DataFrame) -> list[dict]:
        return [{} for _ in range(len(cur))]
