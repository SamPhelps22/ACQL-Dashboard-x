"""Point-in-time feature tables, built week by week from snapshots.

A feature builder is `fn(snap, week_games_blind) -> DataFrame[game_id, ...]`.
The bank runs it once per week of history, each time with the snapshot as of
*that* week's start, so every row only reflects games completed before its
own week. A model asking for history at `as_of` gets rows for weeks starting
at or before `as_of` only - never later ones.
"""

from __future__ import annotations

import pandas as pd

from .. import config
from ..data import games as games_mod

INFO_FOR_BUILDERS = config.WEEK_START


class Bank:
    def __init__(self, store):
        self.store = store
        self._weeks = (store.games.groupby(["season", "week"])["ts_week_start"].first()
                       .reset_index().sort_values("ts_week_start"))
        self._memo: dict = {}

    def week_rows(self, name: str, fn, season: int, week: int, info_set=INFO_FOR_BUILDERS) -> pd.DataFrame:
        key = (name, season, week, info_set)
        if key not in self._memo:
            g = self.store.games
            wk = g[(g["season"] == season) & (g["week"] == week)]
            snap = self.store.snapshot(wk["ts_week_start"].iloc[0])
            out = fn(snap, games_mod.blind(wk, info_set))
            self._memo[key] = out
        return self._memo[key]

    def history(self, name: str, fn, as_of: pd.Timestamp, since_season: int | None = None,
                info_set=INFO_FOR_BUILDERS) -> pd.DataFrame:
        """Feature rows for every week whose start is at or before `as_of` (results not attached)."""
        w = self._weeks[self._weeks["ts_week_start"] <= as_of]
        if since_season is not None:
            w = w[w["season"] >= since_season]
        frames = [self.week_rows(name, fn, s, k, info_set) for s, k in zip(w["season"], w["week"])]
        frames = [f for f in frames if len(f)]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def bank_for(store) -> Bank:
    if not hasattr(store, "_bank"):
        store._bank = Bank(store)
    return store._bank


def training_rows(snap, name: str, fn, since_season: int | None = None,
                  info_set=INFO_FOR_BUILDERS) -> pd.DataFrame:
    """Historical feature rows with outcomes, for games completed by the snapshot's time."""
    hist = bank_for(snap.store).history(name, fn, snap.as_of, since_season, info_set)
    if not len(hist):
        return hist
    res = snap.games[["game_id", "margin", "home_win", "total_points", "home_score", "away_score"]]
    return hist.merge(res, on="game_id", how="inner")
