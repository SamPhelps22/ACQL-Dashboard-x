"""Model C - situational and environmental effects on top of a plain team-strength base.

    C_base            team strength only (net points per drive, EPA per play, success rate) + home field
    C_situational     + rest, short weeks, byes, travel, time zones, early west-coast kickoffs,
                      altitude, roof, surface, division games (all known when the schedule is out)
    C_sit_weather     + observed game weather (temp, wind, cold, windy, dome team in the cold).
                      RETROSPECTIVE: nflverse weather is the game-time observation, not a forecast.

C_situational minus C_base is the ablation the brief asks for; the ridge
penalty (chosen on earlier seasons) is the regularisation that stops a
handful of altitude or London games turning into a story.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from ..features import ratings, situational
from .ridge_margin import RidgeMarginModel

BASE = ["epa_play", "ppd", "succ"]
SIT = ["rest_diff", "h_short", "a_short", "h_bye", "a_bye", "a_km_k", "h_km_k", "a_tz_east", "a_tz_west",
       "early_west_away", "alt_away", "dome", "turf", "div_game"]


def _ratings(snap, week):
    out = ratings.build(snap, week)
    return out[["game_id"] + [c for c in out.columns if any(c.endswith(f"_{b}") for b in BASE)]] if len(out) else out


def base_cols(df):
    X = pd.DataFrame(index=df.index)
    for s in BASE:
        X[f"net_{s}"] = (df[f"h_off_{s}"] + df[f"a_def_{s}"]) - (df[f"a_off_{s}"] + df[f"h_def_{s}"])
    X["home"] = 1.0 - df["neutral"]
    return X


def sit_cols(df):
    X = pd.DataFrame(index=df.index)
    d = df.copy()
    d["a_km_k"] = d["a_km"].fillna(d["a_km"].median() if d["a_km"].notna().any() else 0) / 1000
    d["h_km_k"] = d["h_km"].fillna(0) / 1000
    d["alt_away"] = (d["altitude"].fillna(0) > 1500).astype(float) * (1 - 0 * d["neutral"])
    for c in SIT:
        X[c] = d[c].astype(float)
    return X


def weather_cols(df):
    X = pd.DataFrame(index=df.index)
    X["wind"] = df["wind"]
    X["cold"] = df["cold"]
    X["windy"] = df["windy"]
    X["dome_team_cold"] = df["a_dome_team"] * df["cold"] * (1 - df["dome"])
    X["weather_missing"] = df["weather_missing"]
    return X


def _weather(snap, week):
    if not len(week) or "temp" not in week.columns:
        return pd.DataFrame({"game_id": week["game_id"].values})
    return situational.weather(week)


class SituationalBase(RidgeMarginModel):
    name = "C_base"
    version = "1"
    builders = {"c_ratings": _ratings, "situational": situational.build}

    def columns(self, df):
        return base_cols(df)


class Situational(SituationalBase):
    name = "C_situational"

    def columns(self, df):
        return pd.concat([base_cols(df), sit_cols(df)], axis=1)


class SituationalWeather(SituationalBase):
    name = "C_sit_weather"
    info_set = config.CLOSING_RETRO
    provenance = "nflverse pbp + schedule + OBSERVED game weather (retrospective)"
    builders = {"c_ratings": _ratings, "situational": situational.build, "weather": _weather}

    def columns(self, df):
        return pd.concat([base_cols(df), sit_cols(df), weather_cols(df)], axis=1)
