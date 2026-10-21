"""A small real-data store (2009-2012) for tests, and a way to rewrite its future."""

from __future__ import annotations

import functools

import numpy as np
import pandas as pd

from research_lab import config
from research_lab.data import games as games_mod, pbp
from research_lab.data.store import Store, load_injuries

SEASONS = (2009, 2012)


def available() -> bool:
    return (config.RAW / "games.csv").exists() and (config.DERIVED / "team_games.csv.gz").exists()


@functools.lru_cache(maxsize=1)
def _tables():
    g = games_mod.load()
    g = g[g["season"].between(*SEASONS)].reset_index(drop=True)
    ids = set(g["game_id"])
    t = {name: pbp.load(name) for name in ("team_games", "qb_games", "drives")}
    t = {k: v[v["game_id"].isin(ids)].reset_index(drop=True) for k, v in t.items()}
    inj = load_injuries()
    inj = inj[inj["season"].between(*SEASONS)]
    return g, t, inj


def store() -> Store:
    g, t, inj = _tables()
    return Store(g.copy(), t["team_games"].copy(), t["qb_games"].copy(), t["drives"].copy(), inj.copy())


def scrambled_after(cutoff: pd.Timestamp, seed: int = 7, lines_after: pd.Timestamp | None = None) -> Store:
    """The same store with every outcome and stat of games kicking off after `cutoff` rewritten at random.

    Closing lines are rewritten only for games after `lines_after` (default `cutoff`): a closing-line
    benchmark may see its own games' closing lines, but no later ones."""
    g, t, inj = _tables()
    g = g.copy()
    rng = np.random.default_rng(seed)
    late = g["kickoff"] > cutoff
    g.loc[late, "home_score"] = rng.integers(0, 50, late.sum())
    g.loc[late, "away_score"] = rng.integers(0, 50, late.sum())
    g["margin"] = g["home_score"] - g["away_score"]
    g["total_points"] = g["home_score"] + g["away_score"]
    g["home_win"] = np.where(g["margin"] > 0, 1.0, np.where(g["margin"] < 0, 0.0, 0.5))
    later = g["kickoff"] > (lines_after if lines_after is not None else cutoff)
    for c in ("spread_line", "home_moneyline", "away_moneyline", "total_line"):
        g.loc[later, c] = g.loc[later, c].sample(frac=1, random_state=seed).values
    late_ids = set(g.loc[late, "game_id"])
    out = {}
    for k, v in t.items():
        v = v.copy()
        m = v["game_id"].isin(late_ids)
        num = [c for c in v.columns if v[c].dtype.kind in "fi" and c not in ("season", "week", "fixed_drive")]
        v[num] = v[num].astype(float)
        v.loc[m, num] = v.loc[m, num] * rng.uniform(0.2, 3.0, size=(m.sum(), len(num)))
        if "result" in v.columns:
            v.loc[m, "result"] = rng.choice(["TD", "FG", "PUNT", "TO"], m.sum())
        out[k] = v
    return Store(g, out["team_games"], out["qb_games"], out["drives"], inj.copy())
