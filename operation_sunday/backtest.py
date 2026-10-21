"""Walk-forward (expanding window) evaluation.

For every evaluation week, with cutoff C (the week's lock):
  * training rows = finished games whose result was published by C;
  * preprocessing, regularisation choice and calibration are fitted inside
    those rows only (models.Logistic);
  * the week is predicted from features as of C (features.build_features);
  * its outcomes are only read afterwards, by the scorer.

The final holdout seasons are refused unless explicitly unlocked with a
reason, which is logged with the promotion-criteria digest in force.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Settings
from .models import Model
from .tz import iso, utc_now


class HoldoutLocked(RuntimeError):
    pass


class HoldoutGuard:
    def __init__(self, settings: Settings, log_dir: Path | None = None):
        self.settings = settings
        self.log = (log_dir or settings.state_path) / "holdout_access.jsonl"

    def check(self, seasons, unlock_reason: str | None = None):
        touched = sorted(set(int(s) for s in seasons) & set(self.settings.holdout_seasons))
        if not touched:
            return
        if not unlock_reason:
            raise HoldoutLocked(f"seasons {touched} are the final holdout; pass an explicit unlock reason "
                                "once model-selection rules are final")
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": iso(utc_now()), "seasons": touched, "reason": unlock_reason,
                                "criteria": self.settings.promotion.digest()}) + "\n")

    def viewings(self) -> int:
        return sum(1 for _ in open(self.log, encoding="utf-8")) if self.log.exists() else 0


def training_rows(feats: pd.DataFrame, cutoff) -> pd.DataFrame:
    """Everything a model may learn from at `cutoff`: finished and published."""
    cut = pd.Timestamp(cutoff)
    return feats[(feats["status"] == "final") & (feats["published_utc"] <= cut) & (feats["kickoff_utc"] < cut)]


def eval_week_keys(feats: pd.DataFrame, seasons, include_post=False) -> list:
    sel = feats[feats["season"].isin(list(seasons))]
    if not include_post:
        sel = sel[sel["game_type"] == "REG"]
    return list(dict.fromkeys(sel.sort_values("cutoff_utc")["week_key"]))


def walk_forward(feats: pd.DataFrame, models: list[Model], week_keys: list, settings: Settings,
                 guard: HoldoutGuard | None = None, unlock_reason: str | None = None,
                 min_train: int = 200) -> pd.DataFrame:
    seasons = {k[0] for k in week_keys}
    (guard or HoldoutGuard(settings)).check(seasons, unlock_reason)
    rows = []
    for key in week_keys:
        week = feats[feats["week_key"] == key]
        if week.empty:
            continue
        cut = week["cutoff_utc"].iloc[0]
        train = training_rows(feats, cut)
        if len(train) < min_train:
            continue
        assert not train["game_id"].isin(week["game_id"]).any(), "same-week leakage"
        for m in models:
            m.fit(train)
            pred = m.predict(week)
            rows.append(pd.DataFrame({
                "week_key": [key] * len(week), "season": week["season"].to_numpy(),
                "week": week["week"].to_numpy(), "game_id": week["game_id"].to_numpy(),
                "model": m.name, "p_home": pred["p_home"].to_numpy(float),
                "exp_margin": pred["exp_margin"].to_numpy(float), "exp_total": pred["exp_total"].to_numpy(float),
                "train_games": len(train), "train_cutoff": cut,
            }))
    if not rows:
        return pd.DataFrame(columns=["week_key", "game_id", "model", "p_home"])
    return pd.concat(rows, ignore_index=True)


def attach_outcomes(preds: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    cols = ["game_id", "home_win", "margin", "total", "home", "away", "close_spread", "neutral",
            "missing_flags", "home_qb", "away_qb", "cutoff_utc", "published_utc"]
    return preds.merge(feats[cols], on="game_id", how="left")


def matched(scored: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Only games where every compared model has a probability."""
    s = scored[scored["model"].isin(models) & scored["p_home"].notna()]
    n = s.groupby("game_id")["model"].nunique()
    keep = n[n == len(set(models))].index
    return s[s["game_id"].isin(keep)]
