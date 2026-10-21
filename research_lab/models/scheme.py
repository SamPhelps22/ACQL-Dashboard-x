"""Model H - scheme matchups from charted coverage and pressure (2018+ only).

Opponent-adjusted, recency-weighted unit ratings (features/ratings.py) on the
participation table:

    epa_man / epa_zone   offence: EPA per dropback against man / zone;
                         defence: the same allowed
    man_rate             defence: share of labelled dropbacks in man (offence side: how often it sees man)
    press_rate           pressure allowed (offence) / generated (defence)
    p11_rate, gun_rate   offensive personnel / formation tendencies

Matchup features, per side, are the coverage-weighted expected pass EPA -
the offence's EPA against man x the opponent's man rate + its EPA against zone
x (1 - man rate) - and pressure allowed x pressure generated.

    H_base     the C_base team-strength inputs, trained on the same 2019+ games
    H_scheme   + the scheme matchup features

Coverage labels exist from 2018, so the first season with a full prior season
of ratings is 2019 and the first scored season (two training seasons) is
2021. 2026 participation data is not published yet: no shadow forecasts.
"""

from __future__ import annotations

import pandas as pd

from .. import config
from ..features import ratings, situational
from .ridge_margin import RidgeMarginModel
from .situational import _ratings, base_cols

FIRST_TRAIN = 2019
STATS = {
    "epa_man": ("epa_man", "db_man"), "epa_zone": ("epa_zone", "db_zone"), "man_rate": ("db_man", "cov_known"),
    "press_rate": ("press", "press_den"), "p11_rate": ("p11", "pers_known"), "gun_rate": ("gun", "form_known"),
}


def build(snap, week: pd.DataFrame) -> pd.DataFrame:
    if not len(week) or snap.scheme is None or not len(snap.scheme):
        return pd.DataFrame({"game_id": week["game_id"].values}) if len(week) else pd.DataFrame()
    s, w = int(week["season"].iloc[0]), int(week["week"].iloc[0])
    sc = snap.scheme[snap.scheme["season"] >= 2018]
    rt = ratings.unit_ratings(sc, snap.games, s, w, stats=STATS)
    out = ratings.matchup_frame(week, rt, stats=STATS)
    out["man_mean"] = rt.attrs["means"]["man_rate"] if len(rt) else 0.4
    return out


def scheme_cols(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for side, opp in (("h", "a"), ("a", "h")):
        man = df[f"{opp}_def_man_rate"] + df["man_mean"]      # opponent's man share: league mean + its deviation
        X[f"{side}_cov_pass"] = (df[f"{side}_off_epa_man"] + df[f"{opp}_def_epa_man"]) * man + \
                                (df[f"{side}_off_epa_zone"] + df[f"{opp}_def_epa_zone"]) * (1 - man)
        X[f"{side}_press"] = df[f"{side}_off_press_rate"] + df[f"{opp}_def_press_rate"]
    X["d_cov_pass"] = X["h_cov_pass"] - X["a_cov_pass"]
    X["d_press"] = X["h_press"] - X["a_press"]
    X["d_p11"] = df["h_off_p11_rate"] - df["a_off_p11_rate"]
    X["d_gun"] = df["h_off_gun_rate"] - df["a_off_gun_rate"]
    return X[["d_cov_pass", "d_press", "d_p11", "d_gun"]]


class _H(RidgeMarginModel):
    version = "1"
    provenance = "nflverse play-by-play + pbp_participation coverage/pressure (2018+)"
    builders = {"c_ratings": _ratings, "situational": situational.build, "scheme": build}

    train_from = FIRST_TRAIN


class SchemeBase(_H):
    name = "H_base"

    def columns(self, df):
        return base_cols(df)


class Scheme(_H):
    name = "H_scheme"

    def columns(self, df):
        return pd.concat([base_cols(df), scheme_cols(df)], axis=1)
