"""Model A: Elo ratings.

* Expected home score: 1 / (1 + 10^(-(R_home - R_away + HFA) / 400)).
* Update: R += K * MOV_mult * (actual - expected), actual in {1, 0.5, 0}.
* MOV multiplier (FiveThirtyEight NFL Elo): ln(|margin| + 1) * 2.2 / (0.001 * dElo_winner + 2.2),
  which damps rating inflation for heavy favourites.
* Between seasons each rating regresses ``season_regression`` of the way to the mean.

Ratings only ever use results of games that kicked off earlier, so the
pre-game rating of a game is point-in-time by construction. The parameters are
literature defaults (not tuned on the evaluation data).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

GAME_DURATION = pd.Timedelta(hours=4)


@dataclass
class EloParams:
    initial_rating: float = 1505.0
    k_factor: float = 20.0
    home_field_advantage: float = 48.0
    season_regression: float = 0.333
    mov_multiplier: bool = True
    neutral_site_hfa: float = 0.0

    @classmethod
    def from_config(cls, cfg: dict) -> "EloParams":
        return cls(**{k: cfg[k] for k in cls.__dataclass_fields__ if k in cfg})


def expected_home(r_home: float, r_away: float, hfa: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(r_home - r_away + hfa) / 400.0))


def mov_mult(margin: float, elo_diff_winner: float) -> float:
    return math.log(max(abs(margin), 1) + 1) * 2.2 / (0.001 * elo_diff_winner + 2.2)


class EloModel:
    def __init__(self, params: EloParams | None = None):
        self.p = params or EloParams()

    def _hfa(self, location: str | None) -> float:
        return self.p.neutral_site_hfa if location == "Neutral" else self.p.home_field_advantage

    def regress(self, rating: float) -> float:
        return rating + self.p.season_regression * (self.p.initial_rating - rating)

    def run(self, games: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Process completed games chronologically.

        Returns (game_ratings, team_states):
          game_ratings: game_id, home_elo_pre, away_elo_pre, elo_home_prob
          team_states: team, season, game_id, available_at, rating_post — one row per
          team per completed game, usable with merge_asof for any later cutoff.
        """
        done = games[games["game_status"] == "final"].sort_values(["kickoff_utc", "game_id"])
        ratings: dict[str, float] = {}
        last_season: dict[str, int] = {}
        g_rows, s_rows = [], []
        for g in done.itertuples(index=False):
            pre = {}
            for team in (g.home_team, g.away_team):
                r = ratings.get(team, self.p.initial_rating)
                if team in last_season and last_season[team] != g.season:
                    r = self.regress(r)
                pre[team] = r
            rh, ra = pre[g.home_team], pre[g.away_team]
            hfa = self._hfa(g.location)
            exp_h = expected_home(rh, ra, hfa)
            margin = float(g.home_score) - float(g.away_score)
            actual = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
            mult = 1.0
            if self.p.mov_multiplier:
                diff_w = (rh + hfa - ra) if margin > 0 else (ra - rh - hfa) if margin < 0 else 0.0
                mult = mov_mult(margin, diff_w)
            delta = self.p.k_factor * mult * (actual - exp_h)
            ratings[g.home_team], ratings[g.away_team] = rh + delta, ra - delta
            last_season[g.home_team] = last_season[g.away_team] = g.season
            g_rows.append((g.game_id, rh, ra, exp_h))
            avail = g.kickoff_utc + GAME_DURATION
            s_rows.append((g.home_team, g.season, g.game_id, avail, rh + delta))
            s_rows.append((g.away_team, g.season, g.game_id, avail, ra - delta))
        game_ratings = pd.DataFrame(g_rows, columns=["game_id", "home_elo_pre", "away_elo_pre", "elo_home_prob"])
        states = pd.DataFrame(s_rows, columns=["team", "season", "game_id", "available_at", "rating_post"])
        return game_ratings, states

    def ratings_at(self, states: pd.DataFrame, queries: pd.DataFrame) -> pd.Series:
        """Rating for each (team, season, cutoff) query using only states available
        strictly before the cutoff; regressed if the last state is from an earlier season."""
        q = queries[["team", "season", "cutoff"]].copy()
        q["_ord"] = np.arange(len(q))
        if states.empty:
            return pd.Series(self.p.initial_rating, index=queries.index)
        st = states.sort_values("available_at")
        m = pd.merge_asof(q.sort_values("cutoff"), st[["team", "available_at", "season", "rating_post"]]
                          .rename(columns={"season": "state_season"}),
                          left_on="cutoff", right_on="available_at", by="team",
                          direction="backward", allow_exact_matches=False).sort_values("_ord")
        r = m["rating_post"].fillna(self.p.initial_rating).to_numpy()
        crossed = m["state_season"].notna().to_numpy() & (m["state_season"].to_numpy() != m["season"].to_numpy())
        r = np.where(crossed, r + self.p.season_regression * (self.p.initial_rating - r), r)
        return pd.Series(r, index=queries.index)

    def predict(self, home_rating: np.ndarray, away_rating: np.ndarray, location: pd.Series) -> np.ndarray:
        hfa = np.where(location.fillna("Home").to_numpy() == "Neutral",
                       self.p.neutral_site_hfa, self.p.home_field_advantage)
        return 1.0 / (1.0 + 10 ** (-(np.asarray(home_rating) - np.asarray(away_rating) + hfa) / 400.0))
