"""Confidence-point allocation, grading and strategy interface.

Default strategy (``ExpectedPointsStrategy``): pick the team with the higher
blended probability and give the largest points to the most likely picks.
By the rearrangement inequality, pairing the sorted probabilities with the
sorted point values maximises the sum of p_i * points_i, i.e. expected points.

Tie-breaking is deterministic: higher probability, then earlier kickoff, then
game_id (alphabetical). An exact 50/50 game picks the home team.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd


@dataclass
class ScoringRules:
    points_mode: str = "1_to_n"                 # "1_to_n", "flat" (1 point per correct pick) or "custom"
    custom_points: list[int] = field(default_factory=list)
    tie_rule: str = "half"                      # zero | half | full
    postponed_rule: str = "void"                # void | loss
    include_postseason: bool = False

    @classmethod
    def from_config(cls, pool_cfg: dict) -> "ScoringRules":
        return cls(**{k: pool_cfg[k] for k in cls.__dataclass_fields__ if k in pool_cfg})

    def point_values(self, n_games: int) -> list[int]:
        """Point values, highest first, for an n-game slate (distinct unless flat)."""
        if self.points_mode == "flat":
            return [1] * n_games
        if self.points_mode == "1_to_n":
            return list(range(n_games, 0, -1))
        pts = sorted(self.custom_points, reverse=True)
        if len(pts) < n_games:
            raise ValueError(f"custom_points has {len(pts)} values but the slate has {n_games} games")
        if len(set(pts)) != len(pts):
            raise ValueError("custom_points must be unique")
        return pts[:n_games]


def select_teams(slate: pd.DataFrame, prob_col: str = "blended_home_probability") -> pd.DataFrame:
    """Add selected_team and selected_team_probability. NaN probability -> home at 0.5."""
    s = slate.copy()
    p = s[prob_col].astype(float).fillna(0.5)
    home = p >= 0.5
    s["selected_team"] = np.where(home, s["home_team"], s["away_team"])
    s["selected_is_home"] = home
    s["selected_team_probability"] = np.where(home, p, 1 - p)
    return s


def rank_games(slate: pd.DataFrame) -> pd.DataFrame:
    keys = ["selected_team_probability", "kickoff_utc", "game_id"]
    s = slate.copy()
    if "kickoff_utc" not in s:
        s["kickoff_utc"] = pd.NaT
    return s.sort_values(keys, ascending=[False, True, True], kind="mergesort")


class ConfidenceStrategy(Protocol):
    name: str

    def allocate(self, slate: pd.DataFrame, rules: ScoringRules,
                 prob_col: str = "blended_home_probability") -> pd.DataFrame: ...


class ExpectedPointsStrategy:
    """Maximise expected confidence points (the default)."""

    name = "expected_points"

    def allocate(self, slate: pd.DataFrame, rules: ScoringRules,
                 prob_col: str = "blended_home_probability") -> pd.DataFrame:
        return allocate(slate, rules, prob_col)


class OpponentAwareStrategy:
    """Placeholder for future opponent-aware optimisation.

    Maximising the probability of *winning the pool* requires opponents' picks
    or a defensible model of how they pick. Until such data is supplied this
    strategy refuses to run rather than pretending to optimise. Use
    ``simulate_pool_win_probability`` to *evaluate* a sheet against known
    opponent sheets.
    """

    name = "opponent_aware"

    def __init__(self, opponent_sheets: list[pd.DataFrame] | None = None):
        self.opponent_sheets = opponent_sheets

    def allocate(self, slate, rules, prob_col="blended_home_probability"):
        if not self.opponent_sheets:
            raise NotImplementedError(
                "Opponent-aware allocation needs opponent picks (or an opponent model); none supplied. "
                "Use ExpectedPointsStrategy.")
        raise NotImplementedError("Opponent-aware optimisation is not implemented yet.")


def allocate(slate: pd.DataFrame, rules: ScoringRules | None = None,
             prob_col: str = "blended_home_probability", exclude: set[str] | None = None) -> pd.DataFrame:
    """Assign unique confidence points to eligible games.

    Excluded games (canceled, removed from the pool, or in ``exclude``) get no
    points and are kept in the output with confidence_points = 0.
    """
    rules = rules or ScoringRules()
    exclude = set(exclude or ())
    s = select_teams(slate, prob_col)
    eligible = ~s["game_id"].isin(exclude)
    if "game_status" in s:
        eligible &= s["game_status"] != "canceled"
    elig = rank_games(s[eligible])
    pts = rules.point_values(len(elig))
    elig = elig.assign(confidence_points=pts)
    rest = s[~eligible].assign(confidence_points=0)
    out = pd.concat([elig, rest])
    out["confidence_points"] = out["confidence_points"].astype(int)
    out["expected_points"] = out["selected_team_probability"] * out["confidence_points"]
    out["confidence_rank"] = out["confidence_points"].rank(ascending=False, method="first").astype(int)
    return out.sort_values(["confidence_points", "game_id"], ascending=[False, True]).reset_index(drop=True)


def validate_allocation(alloc: pd.DataFrame, rules: ScoringRules | None = None) -> None:
    rules = rules or ScoringRules()
    used = alloc.loc[alloc["confidence_points"] > 0, "confidence_points"]
    if rules.points_mode == "flat":
        if not (used == 1).all() or len(used) != int((alloc["confidence_points"] > 0).sum()):
            raise ValueError("Flat scoring must give every eligible game exactly 1 point")
        return
    if used.duplicated().any():
        raise ValueError("Confidence points are not unique")
    expected = sorted(rules.point_values(len(used)))
    if sorted(used.tolist()) != expected:
        raise ValueError(f"Confidence points {sorted(used.tolist())} != expected {expected}")
    ordered = alloc[alloc["confidence_points"] > 0].sort_values("confidence_points", ascending=False)
    if (ordered["selected_team_probability"].diff().dropna() > 1e-12).any():
        raise ValueError("Confidence points are not ordered by win probability")


def grade_pick(selected_team: str, home_team: str, away_team: str, home_score, away_score,
               points: int, rules: ScoringRules, game_status: str = "final") -> tuple[str, float]:
    """Return (actual_result, points_earned) for one pick."""
    if game_status in ("canceled", "postponed"):
        return ("void", 0.0) if rules.postponed_rule == "void" else ("loss", 0.0)
    if game_status != "final" or pd.isna(home_score) or pd.isna(away_score):
        return "pending", 0.0
    if home_score == away_score:
        frac = {"zero": 0.0, "half": 0.5, "full": 1.0}[rules.tie_rule]
        return "tie", frac * points
    winner = home_team if home_score > away_score else away_team
    return ("win", float(points)) if selected_team == winner else ("loss", 0.0)


def grade_sheet(alloc: pd.DataFrame, results: pd.DataFrame, rules: ScoringRules) -> pd.DataFrame:
    """Grade an allocation against a results frame (game_id, home_score, away_score, game_status)."""
    cols = ["game_id", "home_score", "away_score", "game_status"]
    m = alloc.drop(columns=[c for c in cols[1:] if c in alloc.columns]).merge(results[cols], on="game_id", how="left")
    graded = [grade_pick(r.selected_team, r.home_team, r.away_team, r.home_score, r.away_score,
                         r.confidence_points, rules, r.game_status if isinstance(r.game_status, str) else "scheduled")
              for r in m.itertuples(index=False)]
    m["actual_result"] = [g[0] for g in graded]
    m["points_earned"] = [g[1] for g in graded]
    return m


def simulate_pool_win_probability(my_sheet: pd.DataFrame, opponent_sheets: list[pd.DataFrame],
                                  home_probs: pd.Series, n_sims: int = 5000, seed: int = 42) -> float:
    """Monte Carlo P(my score > all opponents) given supplied opponent sheets.

    Sheets need game_id, selected_team, home_team, confidence_points. Ties for
    first count as half a win. ``home_probs`` is indexed by game_id.
    """
    rng = np.random.default_rng(seed)
    games = list(home_probs.index)
    home_wins = rng.random((n_sims, len(games))) < home_probs.to_numpy()[None, :]

    def scores(sheet):
        s = sheet.set_index("game_id").reindex(games)
        picked_home = (s["selected_team"] == s["home_team"]).to_numpy()
        pts = s["confidence_points"].fillna(0).to_numpy()
        return ((home_wins == picked_home[None, :]) * pts[None, :]).sum(axis=1)

    mine = scores(my_sheet)
    best_opp = np.max(np.vstack([scores(o) for o in opponent_sheets]), axis=0)
    return float(np.mean((mine > best_opp) + 0.5 * (mine == best_opp)))
