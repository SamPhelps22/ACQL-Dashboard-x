"""Everything the lab knows, and the point-in-time view a model is given.

`Store.snapshot(as_of)` is the only way a model sees history. It keeps rows
of games completed by `as_of` and nothing else; the games being predicted
are passed separately with their outcomes removed (games.blind).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .. import config
from . import games as games_mod
from . import pbp


@dataclass
class Snapshot:
    as_of: pd.Timestamp
    games: pd.DataFrame          # completed games, with results
    team_games: pd.DataFrame
    qb_games: pd.DataFrame
    drives: pd.DataFrame
    store: object = None         # for the feature bank only; it serves rows at or before as_of
    scheme: pd.DataFrame | None = None   # Model H coverage / pressure per team-game (2016+)

    @property
    def cutoff(self) -> pd.Timestamp | None:
        return self.games["completed_at"].max() if len(self.games) else None


class Store:
    def __init__(self, games: pd.DataFrame, team_games: pd.DataFrame | None = None,
                 qb_games: pd.DataFrame | None = None, drives: pd.DataFrame | None = None,
                 injuries: pd.DataFrame | None = None, scheme: pd.DataFrame | None = None):
        self.games = games
        done = games[["game_id", "completed_at"]]
        empty = pd.DataFrame(columns=["game_id"])

        def attach(df):
            df = empty if df is None else df
            return df.merge(done, on="game_id", how="inner") if len(df) else df.assign(completed_at=pd.NaT)

        self.team_games = attach(team_games)
        self.qb_games = attach(qb_games)
        self.drives = attach(drives)
        self.scheme = attach(scheme)
        self.injuries = injuries if injuries is not None else pd.DataFrame()
        self._cache: dict = {}

    @classmethod
    def load(cls) -> "Store":
        g = games_mod.load()
        inj = load_injuries()
        from . import scheme
        return cls(g, pbp.load("team_games"), pbp.load("qb_games"), pbp.load("drives"), inj, scheme.load())

    def snapshot(self, as_of: pd.Timestamp) -> Snapshot:
        key = pd.Timestamp(as_of)
        if key in self._cache:
            return self._cache[key]
        g = games_mod.visible(self.games, key)
        ids = set(g["game_id"])

        def keep(df):
            return df[df["game_id"].isin(ids)] if len(df) else df

        snap = Snapshot(key, g, keep(self.team_games), keep(self.qb_games), keep(self.drives), self,
                        keep(self.scheme))
        if len(self._cache) > 8:
            self._cache.clear()
        self._cache[key] = snap
        return snap

    def injuries_before(self, season: int, week: int, ts: pd.Timestamp) -> pd.DataFrame:
        """The week's injury-report rows whose modification time is before `ts`."""
        inj = self.injuries
        if not len(inj):
            return inj
        rows = inj[(inj["season"] == season) & (inj["week"] == week)]
        return rows[rows["date_modified"] < ts]


def load_injuries() -> pd.DataFrame:
    frames = []
    for path in sorted(config.RAW.glob("injuries_*.csv")):
        df = pd.read_csv(path, low_memory=False, usecols=lambda c: c in {
            "season", "game_type", "team", "week", "gsis_id", "position", "full_name", "report_status",
            "practice_status", "date_modified"})
        if "date_modified" not in df.columns:      # 2025+ files carry no timestamp: unusable before kickoff
            df["date_modified"] = pd.NA
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    inj = pd.concat(frames, ignore_index=True)
    inj["team"] = inj["team"].map(config.team)
    inj["date_modified"] = pd.to_datetime(inj["date_modified"], utc=True, errors="coerce")
    return inj
