"""Settings, with every number the system decides by written down in one place.

Defaults match the pool as the dashboard runs it today:

  * deadline: Thursday 18:00 (acql/feeds/oddslock.py DEADLINE = (3, 18, 0)),
    or the week's first kickoff when that comes sooner. The dashboard reads
    "this computer's clock"; here the zone is explicit (America/New_York by
    default) so the deadline never depends on which machine runs the job.
  * scoring: one point per credited pick, pool line on favourites of 6.5+
    (acql/model/backtest.py LINED_FROM, pool_line).

Overrides live in a JSON file (operation_sunday/settings.json by default, or
the path in OPERATION_SUNDAY_SETTINGS). The promotion criteria are hashed into
every experiment record so a later edit can't be passed off as the rule a
decision was made under.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent


@dataclass(frozen=True)
class PromotionCriteria:
    min_games: int = 500
    min_weeks: int = 30
    #: mean per-game log-loss improvement required over the incumbent AND the baseline
    min_logloss_gain: float = 0.002
    #: the paired week-block bootstrap interval's upper bound must be below zero
    ci_level: float = 0.95
    bootstrap_samples: int = 2000
    max_ece: float = 0.035
    calibration_slope_range: tuple = (0.75, 1.25)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Settings:
    timezone: str = "America/New_York"
    deadline_weekday: int = 3          # Monday 0 ... Thursday 3
    deadline_hour: int = 18
    deadline_minute: int = 0
    #: forecasts must be locked this long before the earliest counted kickoff
    kickoff_margin_minutes: int = 0
    #: the weekly job is due this many hours before the lock
    run_lead_hours: float = 3.0
    #: how long after kickoff a final score is assumed published (for eligibility)
    result_delay_hours: float = 4.0
    first_training_season: int = 2006
    dev_eval_seasons: tuple = tuple(range(2012, 2025))
    holdout_seasons: tuple = (2025,)
    designated_baseline: str = "elo"
    seed: int = 20261022
    promotion: PromotionCriteria = field(default_factory=PromotionCriteria)
    state_dir: str = ""
    games_csv_url: str = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
    #: read Thursday market snapshots and pool lines from the dashboard's own store
    market_from_dashboard: bool = True
    #: with lock="auto", a run locks only within this many minutes of the lock
    #: time (earlier runs refresh the draft, so the freshest lines are used)
    lock_window_minutes: int = 180
    #: data older than this many hours at run time raises a freshness warning
    stale_after_hours: float = 36.0

    @property
    def state_path(self) -> Path:
        return Path(self.state_dir or os.environ.get("OPERATION_SUNDAY_STATE", REPO_DIR / "data" / "operation_sunday"))


def load_settings(path: str | os.PathLike | None = None, **overrides) -> Settings:
    path = path or os.environ.get("OPERATION_SUNDAY_SETTINGS") or PACKAGE_DIR / "settings.json"
    values: dict = {}
    p = Path(path)
    if p.exists():
        values.update(json.loads(p.read_text(encoding="utf-8")))
    values.update(overrides)
    names = {f.name for f in fields(Settings)}
    unknown = set(values) - names
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    if "promotion" in values and isinstance(values["promotion"], dict):
        values["promotion"] = PromotionCriteria(**{
            k: tuple(v) if isinstance(v, list) else v for k, v in values["promotion"].items()})
    for key in ("dev_eval_seasons", "holdout_seasons"):
        if key in values:
            values[key] = tuple(values[key])
    s = Settings(**values)
    if not 0 <= s.deadline_weekday <= 6 or not 0 <= s.deadline_hour <= 23 or not 0 <= s.deadline_minute <= 59:
        raise ValueError("deadline weekday/hour/minute out of range")
    if set(s.dev_eval_seasons) & set(s.holdout_seasons):
        raise ValueError("a season cannot be both a development and a holdout season")
    return s
