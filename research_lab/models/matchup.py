"""Model F - tactical matchups from play-by-play.

Two versions on the same opponent-adjusted unit ratings (features/ratings.py):

    matchup_additive     each unit's net edge, offence vs the defence it faces,
                         summed by stat: (home off + away def) - (away off + home def)
    matchup_interaction  the same, plus centred products of a unit and the unit
                         it meets (pass offence x pass defence, pressure allowed x
                         pressure generated, run x run, explosives x explosives,
                         turnovers x takeaways, third down, red zone)

The interaction terms are what "matchup" means; whether they add anything out
of sample is the test (`interaction` minus `additive`). Formation, personnel
and coverage are not here: see Model H for what charting data exists.
"""

from __future__ import annotations

import pandas as pd

from ..features import ratings
from .ridge_margin import RidgeMarginModel

PAIRS = ["pass_epa", "sack_rate", "hit_rate", "run_epa", "expl_pass", "expl_run", "to_rate", "third", "rz_td"]


def additive(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for s in ratings.STATS:
        X[f"net_{s}"] = (df[f"h_off_{s}"] + df[f"a_def_{s}"]) - (df[f"a_off_{s}"] + df[f"h_def_{s}"])
    X["home"] = 1.0 - df.get("neutral", 0.0)
    return X


def interactions(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for s in PAIRS:
        X[f"x_{s}"] = df[f"h_off_{s}"] * df[f"a_def_{s}"] - df[f"a_off_{s}"] * df[f"h_def_{s}"]
    # cross-unit pressure: a sack-prone offence against a pass rush that gets home
    X["x_pressure_pass"] = (df["h_off_sack_rate"] * df["a_def_hit_rate"]) - (df["a_off_sack_rate"] * df["h_def_hit_rate"])
    return X


def _with_site(snap, week):
    out = ratings.build(snap, week)
    if len(out):
        out = out.merge(week[["game_id", "neutral"]], on="game_id", how="left")
    return out


class MatchupAdditive(RidgeMarginModel):
    name = "F_matchup_additive"
    version = "1"
    builders = {"ratings": _with_site}

    def columns(self, df):
        return additive(df)


class MatchupInteraction(RidgeMarginModel):
    name = "F_matchup_interaction"
    version = "1"
    builders = {"ratings": _with_site}

    def columns(self, df):
        return pd.concat([additive(df), interactions(df)], axis=1)
