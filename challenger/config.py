"""Challenger's configuration: one frozen dataclass, hashed into every run id.

Every number that shapes a forecast lives here, so a stored prediction can be
traced back to exactly the settings that made it. `config_hash` is written
next to every prediction file; changing any field changes the hash, and a
changed hash means a new model version, never a rewrite of old forecasts.

The values below were chosen BEFORE the development backtest was run, from
general NFL modelling practice, except where a comment says they were tuned -
and every tuned value was tuned on seasons before the development period
(2002-2009) or inside the walk-forward loop on earlier seasons only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent
#: Raw downloads and aggregates (git-ignored: large, and re-fetchable).
CACHE = ROOT / "data" / "challenger"
#: Everything a run produces that is worth keeping (committed).
RESULTS = PACKAGE / "results"
#: The append-only prospective journal (committed).
JOURNAL = PACKAGE / "journal"
#: Saved model artifacts for the shadow model (committed).
ARTIFACTS = PACKAGE / "artifacts"


@dataclass(frozen=True)
class EloConfig:
    # Tuned once on 2002-2009 by log loss at the weekly deadline (python -m challenger tune-elo,
    # table in results/elo_tuning_2002_2009.csv); never touched by the dev or holdout seasons.
    # An online home-advantage update (hfa_step > 0) did not help on 2002-2009, so it is off.
    k: float = 20.0
    home_advantage: float = 55.0      # Elo points
    hfa_step: float = 0.0             # Elo points per unit of (result - expectation) on home games
    season_carry: float = 0.6         # share of a team's distance from the mean kept over the offseason
    mean: float = 1505.0
    mov_multiplier: bool = True


@dataclass(frozen=True)
class RatingConfig:
    """Shrunk exponentially weighted team ratings (features.py)."""

    half_life_long: float = 8.0       # games
    half_life_short: float = 3.0      # games ("recent form")
    prior_games: float = 4.0          # pseudo-games of league average every rating starts from
    season_carry: float = 0.45        # share of last season's evidence weight kept into a new season
    qb_half_life: float = 400.0       # dropbacks
    qb_prior_dropbacks: float = 250.0
    qb_replacement_shift: float = -0.10   # a QB with no history is this far below league EPA/dropback
    qb_season_carry: float = 0.7


@dataclass(frozen=True)
class ModelConfig:
    lr_C_grid: tuple[float, ...] = (0.01, 0.03, 0.1, 0.3, 1.0)
    gbm_grid: tuple[dict, ...] = (
        {"num_leaves": 4, "n_estimators": 150, "learning_rate": 0.03, "min_child_samples": 60},
        {"num_leaves": 4, "n_estimators": 400, "learning_rate": 0.02, "min_child_samples": 60},
        {"num_leaves": 8, "n_estimators": 200, "learning_rate": 0.03, "min_child_samples": 80},
        {"num_leaves": 8, "n_estimators": 400, "learning_rate": 0.015, "min_child_samples": 120},
        {"num_leaves": 15, "n_estimators": 250, "learning_rate": 0.02, "min_child_samples": 150},
        {"num_leaves": 3, "n_estimators": 600, "learning_rate": 0.02, "min_child_samples": 40},
    )
    gbm_common: dict = field(default_factory=lambda: {
        "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.7, "reg_lambda": 5.0,
        "random_state": 7, "n_jobs": 1, "deterministic": True, "force_col_wise": True, "verbose": -1,
    })
    #: Seasons before a test season used as inner validation folds (tuning, calibration, stacking).
    inner_folds: int = 3
    calibration: str = "platt"        # "platt" or "none"
    stack_C: float = 1.0              # L2 strength of the stacker over [elo, lr, gbm] logits


@dataclass(frozen=True)
class Config:
    elo: EloConfig = field(default_factory=EloConfig)
    ratings: RatingConfig = field(default_factory=RatingConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    #: First season whose pbp feeds ratings, and first season used as a training row.
    first_pbp_season: int = 2001
    first_train_season: int = 2003
    #: Pre-registered evaluation split. Development seasons may inform design;
    #: the holdout is run once, with the config frozen, and reported as is.
    dev_seasons: tuple[int, ...] = tuple(range(2010, 2020))
    holdout_seasons: tuple[int, ...] = tuple(range(2020, 2027))
    #: A forecast is made this many minutes before the earliest kickoff of its
    #: week (ACQL cards are due about an hour before Thursday's game).
    deadline_minutes_before_first_kickoff: int = 60
    #: A game counts as finished (its result and pbp usable) this long after kickoff.
    game_duration_hours: float = 4.5
    #: Which QB a forecast assumes starts: "previous_start" (deadline-safe) only.
    qb_source: str = "previous_start"
    #: Include play-by-play EPA features (False runs the no-EPA ablation).
    use_epa: bool = True
    seed: int = 7

    def to_dict(self) -> dict:
        return asdict(self)


def config_hash(cfg: Config) -> str:
    text = json.dumps(cfg.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


DEFAULT = Config()


def small_test_config() -> Config:
    """A fast configuration for the synthetic test league."""
    return replace(
        DEFAULT,
        models=replace(
            DEFAULT.models,
            lr_C_grid=(0.1, 1.0),
            gbm_grid=({"num_leaves": 4, "n_estimators": 40, "learning_rate": 0.05, "min_child_samples": 20},
                      {"num_leaves": 3, "n_estimators": 60, "learning_rate": 0.05, "min_child_samples": 20}),
            inner_folds=2,
        ),
        first_pbp_season=2101, first_train_season=2101,
        dev_seasons=(2104, 2105), holdout_seasons=(2106,),
    )
