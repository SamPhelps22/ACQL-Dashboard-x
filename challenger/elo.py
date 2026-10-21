"""Challenger's own Elo: a team-strength rating that only ever sees finished games.

Standard football Elo with a margin-of-victory multiplier, an offseason pull
toward the mean, and a home advantage that can be learned online (`hfa_step`;
off by default, because it did not help on the 2002-2009 tuning seasons).
Neutral-site games get no home advantage. Ties count as half a win.

Ratings are read as of each week's forecast deadline (`asof_deadline`, and
the same rule inside features.py): a game moves the ratings only once it has
finished, so a forecast never contains its own result or any game that kicks
off after its deadline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import EloConfig


def expected(diff: float) -> float:
    """Win chance for a side `diff` Elo points better (home advantage included)."""
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))


@dataclass
class EloState:
    cfg: EloConfig
    ratings: dict[str, float] = field(default_factory=dict)
    home_advantage: float = 0.0
    season: int | None = None

    def __post_init__(self) -> None:
        if not self.home_advantage:
            self.home_advantage = self.cfg.home_advantage

    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.cfg.mean)

    def new_season(self, season: int) -> None:
        if self.season is not None and season != self.season:
            c = self.cfg
            self.ratings = {t: c.mean + c.season_carry * (r - c.mean) for t, r in self.ratings.items()}
        self.season = season

    def pregame(self, home: str, away: str, neutral: bool) -> tuple[float, float, float, float]:
        """(home rating, away rating, home advantage applied, home win chance)."""
        hfa = 0.0 if neutral else self.home_advantage
        rh, ra = self.rating(home), self.rating(away)
        return rh, ra, hfa, expected(rh - ra + hfa)

    def update(self, home: str, away: str, neutral: bool, margin: float) -> None:
        rh, ra, hfa, p = self.pregame(home, away, neutral)
        actual = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        mult = 1.0
        if self.cfg.mov_multiplier and margin != 0:
            winner_diff = (rh - ra + hfa) if margin > 0 else (ra - rh - hfa)
            mult = math.log(abs(margin) + 1) * 2.2 / (winner_diff * 0.001 + 2.2)
        shift = self.cfg.k * mult * (actual - p)
        self.ratings[home] = rh + shift
        self.ratings[away] = ra - shift
        if not neutral:
            self.home_advantage += self.cfg.hfa_step * (actual - p)


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def asof_deadline(games: pd.DataFrame, cfg: EloConfig, deadline: pd.Series, finish: pd.Series) -> np.ndarray:
    """Pregame Elo win chances as of each game's deadline (the same rule features.py uses).

    `games` in kickoff order; `deadline` and `finish` aligned with it.
    """
    order = np.argsort(finish.to_numpy(), kind="stable")
    state = EloState(cfg)
    probs = np.full(len(games), np.nan)
    rows = list(games.itertuples(index=False))
    done = 0
    by_deadline = pd.Series(range(len(games))).groupby(deadline.to_numpy()).apply(list)
    for when, idx in by_deadline.items():
        while done < len(order) and finish.iloc[order[done]] <= when:
            g = rows[order[done]]
            if bool(g.completed):
                state.new_season(int(g.season))
                state.update(g.home, g.away, bool(g.neutral), float(g.home_score - g.away_score))
            done += 1
        for i in idx:
            g = rows[i]
            state.new_season(int(g.season))
            probs[i] = state.pregame(g.home, g.away, bool(g.neutral))[3]
    return probs


def tune(games: pd.DataFrame, seasons: tuple[int, int], deadline: pd.Series, finish: pd.Series,
         grid: dict | None = None) -> tuple[EloConfig, pd.DataFrame]:
    """Grid-search the Elo constants on `seasons` (inclusive) by log loss on decided games."""
    import itertools

    grid = grid or {"k": (15.0, 20.0, 25.0, 30.0), "home_advantage": (40.0, 55.0, 65.0),
                    "season_carry": (0.6, 0.67, 0.75), "hfa_step": (0.0, 0.6, 1.5)}
    mask = games["season"].between(*seasons).to_numpy() & games["home_win"].notna().to_numpy()
    y = games["home_win"].to_numpy()[mask]
    rows = []
    keys = list(grid)
    for values in itertools.product(*(grid[k] for k in keys)):
        cfg = EloConfig(**dict(zip(keys, values)))
        p = asof_deadline(games, cfg, deadline, finish)[mask]
        rows.append({**dict(zip(keys, values)), "log_loss": log_loss(p, y), "games": int(mask.sum())})
    table = pd.DataFrame(rows).sort_values("log_loss").reset_index(drop=True)
    best = EloConfig(**{k: table.loc[0, k] for k in keys})
    return best, table
