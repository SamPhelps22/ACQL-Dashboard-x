"""The one forecast format every model produces, and its checks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

FIELDS = [
    "game_id", "season", "week", "home_team", "away_team", "kickoff", "forecast_ts", "info_set",
    "p_home_raw", "p_away_raw", "p_home_cal", "p_away_cal", "exp_margin", "exp_total", "margin_sd",
    "model", "model_version", "train_cutoff", "feature_cutoff", "missing", "provenance", "uses_market",
]


@dataclass
class Forecast:
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    kickoff: str
    forecast_ts: str
    info_set: str
    p_home_raw: float
    model: str
    model_version: str
    train_cutoff: str
    feature_cutoff: str
    exp_margin: float | None = None
    exp_total: float | None = None
    margin_sd: float | None = None
    p_home_cal: float | None = None
    missing: dict = field(default_factory=dict)
    provenance: str = ""
    uses_market: bool = False

    @property
    def p_away_raw(self) -> float:
        return 1.0 - self.p_home_raw

    def record(self) -> dict:
        d = asdict(self)
        d["p_away_raw"] = self.p_away_raw
        d["p_away_cal"] = None if self.p_home_cal is None else 1.0 - self.p_home_cal
        d["missing"] = json.dumps(self.missing, sort_keys=True)
        return {k: d.get(k) for k in FIELDS}


def validate(df: pd.DataFrame) -> list[str]:
    """Problems with a batch of forecast rows; empty when it is sound."""
    problems = []
    missing = [c for c in FIELDS if c not in df.columns]
    if missing:
        return [f"missing columns {missing}"]
    p = df["p_home_raw"].astype(float)
    if ((p <= 0) | (p >= 1) | p.isna()).any():
        problems.append("p_home_raw outside (0,1)")
    if not np.allclose(df["p_home_raw"].astype(float) + df["p_away_raw"].astype(float), 1.0):
        problems.append("home + away raw probabilities do not sum to 1")
    cal = df["p_home_cal"].notna()
    if cal.any() and not np.allclose(df.loc[cal, "p_home_cal"].astype(float) + df.loc[cal, "p_away_cal"].astype(float), 1.0):
        problems.append("home + away calibrated probabilities do not sum to 1")
    late = pd.to_datetime(df["forecast_ts"], utc=True) >= pd.to_datetime(df["kickoff"], utc=True)
    if late.any() and (df.loc[late, "info_set"] != "closing_retrospective").any():
        problems.append("forecast_ts at or after kickoff for a non-retrospective forecast")
    fc = pd.to_datetime(df["feature_cutoff"], utc=True)
    if (fc > pd.to_datetime(df["forecast_ts"], utc=True)).any():
        problems.append("feature_cutoff after forecast_ts")
    if df.duplicated(["game_id", "model", "info_set"]).any():
        problems.append("duplicate forecasts for one game and model")
    return problems
