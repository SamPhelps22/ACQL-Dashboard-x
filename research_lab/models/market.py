"""Model D - market information beyond the single consensus price.

What the data allows: nflverse keeps ONE number per market per game - the
closing spread, its two prices, the closing moneylines and the closing total.
There are no opening lines, no timestamps, no movement and no second book, so
the movement and cross-book questions cannot be tested historically here
(registered as not-run experiments; the shadow journal starts collecting
timestamped snapshots so they can be tested prospectively).

What can be tested is whether the parts of the closing market disagree in a
useful way:

    logit_ml       de-vigged moneyline probability (the consensus price)
    spread         closing spread
    disagree       moneyline-implied margin minus the spread
    spread_tilt    the spread's own two prices: which side the book shades
    total_x        spread x total: the same spread is surer in a low-scoring game

D_market_full is a logistic regression on those, taught on earlier seasons;
it is judged against market_ml_close (the consensus alone). All closing ->
`closing_retrospective`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from .base import Model, Standardizer, expit, logistic, logit, norm_ppf
from .baselines import american_to_prob, devig

TRAIN_SEASONS = 10


def market_features(df: pd.DataFrame) -> pd.DataFrame:
    p_ml = devig(df["home_moneyline"], df["away_moneyline"])
    spread = df["spread_line"].astype(float).values
    has_ml = ~np.isnan(p_ml)
    ml_margin = norm_ppf(np.where(has_ml, p_ml, 0.5)) * config.MARGIN_SD
    ph = american_to_prob(df["home_spread_odds"].fillna(-110))
    pa = american_to_prob(df["away_spread_odds"].fillna(-110))
    X = pd.DataFrame({
        "logit_ml": np.where(has_ml, logit(np.where(has_ml, p_ml, 0.5)), spread * 0.145),
        "spread": spread,
        "disagree": np.where(has_ml, ml_margin - spread, 0.0),
        "spread_tilt": ph / (ph + pa) - 0.5,
        "total_x": spread * (df["total_line"].astype(float).fillna(44.0).values - 44.0) / 10.0,
        "ml_missing": (~has_ml).astype(float),
    }, index=df.index)
    return X


class MarketFull(Model):
    name = "D_market_full"
    version = "1"
    info_set = config.CLOSING_RETRO
    uses_market = True
    provenance = "nflverse closing spread, spread prices, moneylines, total (retrospective)"
    columns = ["logit_ml", "spread", "disagree", "spread_tilt", "total_x", "ml_missing"]

    def predict(self, snap, week):
        s = int(week["season"].iloc[0])
        g = snap.games
        g = g[(g["season"] >= s - TRAIN_SEASONS) & g["spread_line"].notna() & g["home_win"].isin([0.0, 1.0])]
        Xh = market_features(g)[self.columns].values
        sc = Standardizer().fit(Xh)
        X = np.column_stack([np.ones(len(Xh)), sc.transform(Xh)])
        beta = logistic(X, g["home_win"].values, lam=5.0)
        Xw = np.column_stack([np.ones(len(week)), sc.transform(market_features(week)[self.columns].values)])
        p = expit(Xw @ beta)
        self.last_coef = dict(zip(["intercept", *self.columns], beta))
        return pd.DataFrame({"game_id": week["game_id"].values, "p_home": p,
                             "exp_margin": week["spread_line"].values, "exp_total": week["total_line"].values,
                             "margin_sd": config.MARGIN_SD})
