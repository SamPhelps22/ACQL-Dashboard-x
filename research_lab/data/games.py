"""The schedule: one row a game, with kickoff and forecast timestamps.

Columns kept from nflverse games.csv are split by when they are known:

    known in advance   season, week, teams, kickoff, roof, surface, rest, div_game, neutral
    known at kickoff   home_qb_id / away_qb_id (actual starters, ~90 min before)
    closing (retro)    spread_line, total_line, moneylines   (closing numbers only)
    observed (retro)   temp, wind                              (game-time observations)
    after the game     home_score, away_score, margin
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config

ET = "America/New_York"
#: A game counts as completed (its stats visible) this long after kickoff.
GAME_LENGTH = pd.Timedelta(hours=5)
PRE_KICKOFF_LEAD = pd.Timedelta(minutes=90)

RESULT_COLUMNS = ("home_score", "away_score", "margin", "total_points", "home_win", "overtime")


def _kickoff(df: pd.DataFrame) -> pd.Series:
    t = df["gametime"].fillna("13:00")
    local = pd.to_datetime(df["gameday"] + " " + t, errors="coerce")
    return local.dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")


def week_start(kickoffs: pd.Series) -> pd.Timestamp:
    """Tuesday 09:00 ET on or before the week's first kickoff."""
    first = kickoffs.min().tz_convert(ET)
    day = first.normalize()
    back = (day.weekday() - 1) % 7           # Tuesday = 1
    if back == 0 and first.hour < 9:
        back = 7
    return (day - pd.Timedelta(days=back) + pd.Timedelta(hours=9)).tz_convert("UTC")


def load(path=None, regular_only: bool = False) -> pd.DataFrame:
    path = path or config.RAW / "games.csv"
    df = pd.read_csv(path, low_memory=False)
    df = df[df["season"] >= config.FIRST_SEASON].copy()
    if regular_only:
        df = df[df["game_type"] == "REG"]
    for side in ("home_team", "away_team"):
        df[side] = df[side].map(config.team)
    df["kickoff"] = _kickoff(df)
    df["neutral"] = (df["location"] == "Neutral").astype(int)
    df["playoff"] = (df["game_type"] != "REG").astype(int)
    df["margin"] = df["home_score"] - df["away_score"]
    df["total_points"] = df["home_score"] + df["away_score"]
    df["home_win"] = np.where(df["margin"].isna(), np.nan, np.where(df["margin"] > 0, 1.0, np.where(df["margin"] < 0, 0.0, 0.5)))
    df["completed"] = df["home_score"].notna()
    # one sequential week index across playoffs too (playoff 'week' numbers already continue)
    ws = df.groupby(["season", "week"])["kickoff"].transform(lambda k: week_start(k))
    df["ts_week_start"] = ws
    df["ts_pre_kickoff"] = df["kickoff"] - PRE_KICKOFF_LEAD
    df["completed_at"] = df["kickoff"] + GAME_LENGTH
    df = df.sort_values(["kickoff", "game_id"]).reset_index(drop=True)
    return df


def visible(history: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Games whose results were known at `as_of`."""
    return history[(history["completed"]) & (history["completed_at"] <= as_of)]


#: What a forecast may see about the games it predicts, by information set.
ADVANCE_COLUMNS = ["game_id", "season", "game_type", "week", "gameday", "weekday", "gametime", "away_team",
                   "home_team", "location", "neutral", "playoff", "kickoff", "ts_week_start", "ts_pre_kickoff",
                   "div_game", "roof", "surface", "away_rest", "home_rest", "stadium_id", "stadium",
                   "away_coach", "home_coach"]
KICKOFF_COLUMNS = ["away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name"]
CLOSING_COLUMNS = ["spread_line", "total_line", "away_moneyline", "home_moneyline", "away_spread_odds",
                   "home_spread_odds", "under_odds", "over_odds", "temp", "wind"]


def blind(games: pd.DataFrame, info_set: str = config.WEEK_START) -> pd.DataFrame:
    """The games as a forecast at `info_set` may see them: no outcomes, nothing learned later."""
    cols = list(ADVANCE_COLUMNS)
    if info_set in (config.PRE_KICKOFF, config.CLOSING_RETRO):
        cols += KICKOFF_COLUMNS
    if info_set == config.CLOSING_RETRO:
        cols += CLOSING_COLUMNS
    return games[[c for c in cols if c in games.columns]].copy()
