"""Model A - quarterback availability and performance.

Ridge on the home margin from, for each side: the expected starter's rating
and its parts (sacks, interceptions, CPOE, EPA when hit, rushing), his
experience, whether he is a change from last week's starter, the team's pass
and run offence (to keep the passer apart from his supporting cast) and the
opposing defence (pass, run, pressure). Three timing variants:

    A_qb_weekstart   last game's main passer - Tuesday information only
    A_qb_injury      + the final injury report, if timestamped before the forecast (pre-kickoff)
    A_qb_confirmed   the actual starter, ~90 min before kickoff (pre-kickoff)
"""

from __future__ import annotations

import pandas as pd

from .. import config
from ..features import qb
from .ridge_margin import RidgeMarginModel

SIDE_FEATS = ["qb_rating", "qb_sack", "qb_int", "qb_cpoe", "qb_hit_epa", "qb_rush", "qb_exp", "qb_changed",
              "qb_unknown", "team_pass", "team_run", "qb_vs_team", "opp_def_pass", "opp_def_run", "opp_rush",
              "def_pass"]


def columns(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for f in SIDE_FEATS:
        X[f"d_{f}"] = df[f"h_{f}"] - df[f"a_{f}"]
    # pressure matchup: a sack-prone passer against a rush that gets home
    X["x_pressure"] = df["h_qb_sack"] * df["h_opp_rush"] - df["a_qb_sack"] * df["a_opp_rush"]
    X["home"] = 1.0 - df["neutral"]
    return X


class _QB(RidgeMarginModel):
    version = "1"
    mode = "last"

    def __init__(self):
        super().__init__()
        self.builders = {f"qb_{self.mode}": qb.builder(self.mode)}

    def columns(self, df):
        return columns(df)

    def missing(self, cur):
        return [{"home_qb_unknown": bool(r.h_qb_unknown), "away_qb_unknown": bool(r.a_qb_unknown)}
                for r in cur.itertuples()]


class QBWeekStart(_QB):
    name = "A_qb_weekstart"
    mode = "last"


class QBInjury(_QB):
    name = "A_qb_injury"
    mode = "injury"
    info_set = config.PRE_KICKOFF
    provenance = "nflverse pbp + final injury report (timestamped 2010-2024 only)"


class QBConfirmed(_QB):
    name = "A_qb_confirmed"
    mode = "confirmed"
    info_set = config.PRE_KICKOFF
    provenance = "nflverse pbp + actual starting QB (known ~90 min before kickoff)"
