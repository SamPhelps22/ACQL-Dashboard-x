"""Opponent-adjusted unit ratings from play-by-play, as of a snapshot.

For each rate statistic (EPA per dropback, sack rate, explosive rate ...) a
weighted ridge fits

    stat(offense o vs defence d, game g) = mean + off[o] + def[d] + home*h

on the snapshot's team-games, weighting each game by its plays and by
recency (half-life `HALF_LIFE` weeks; a season boundary counts as
`OFFSEASON_WEEKS` more). The ridge penalty shrinks thin samples toward
average, which is what keeps week-2 ratings from believing week 1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STATS = {
    # name: (numerator, denominator)
    "epa_play": ("epa", "plays"),
    "pass_epa": ("pass_epa", "dropbacks"),
    "run_epa": ("run_epa", "runs"),
    "succ": ("succ", "plays"),
    "sack_rate": ("sacks", "dropbacks"),
    "hit_rate": ("qb_hits", "dropbacks"),
    "expl_pass": ("expl_pass", "dropbacks"),
    "expl_run": ("expl_run", "runs"),
    "third": ("third_conv", "thirds"),
    "rz_td": ("rz_tds", "rz_drives"),
    "to_rate": ("turnovers", "plays"),
    "ppd": ("drive_points", "n_drives"),
    "early_pass": ("early_down_passes", "early_downs"),
}
HALF_LIFE = 10.0
OFFSEASON_WEEKS = 12.0
LOOKBACK_SEASONS = 2
#: Ridge penalty, in units of "games' worth of plays" (a team with fewer games is pulled harder to 0).
PENALTY_GAMES = 4.0


def _age_weeks(tg: pd.DataFrame, as_of_season: int, as_of_week: float) -> np.ndarray:
    return (as_of_week - tg["week"].values) + (as_of_season - tg["season"].values) * (18 + OFFSEASON_WEEKS)


def unit_ratings(team_games: pd.DataFrame, games: pd.DataFrame, season: int, week: int,
                 stats=STATS) -> pd.DataFrame:
    """One row a team: off_<stat>, def_<stat> (positive def = allows more), and n_games."""
    tg = team_games[team_games["season"] >= season - LOOKBACK_SEASONS]
    if not len(tg):
        return pd.DataFrame()
    home = games.set_index("game_id")["home_team"]
    tg = tg.assign(is_home=(tg["game_id"].map(home) == tg["team"]).astype(float))
    teams = sorted(set(tg["team"]) | set(tg["opp"]))
    idx = {t: i for i, t in enumerate(teams)}
    n, T = len(tg), len(teams)
    X = np.zeros((n, 2 + 2 * T))
    X[:, 0] = 1.0
    X[:, 1] = tg["is_home"].values
    X[np.arange(n), 2 + tg["team"].map(idx).values] = 1.0
    X[np.arange(n), 2 + T + tg["opp"].map(idx).values] = 1.0
    age = _age_weeks(tg, season, week)
    decay = 0.5 ** (age / HALF_LIFE)
    out = {"team": teams}
    counts = tg[tg["season"] == season].groupby("team").size()
    for name, (num, den) in stats.items():
        d = tg[den].astype(float).values
        ok = d > 0
        y = np.where(ok, tg[num].astype(float).values / np.where(ok, d, 1), 0.0)
        w = decay * d * ok
        per_game = np.nanmean(d[ok]) if ok.any() else 1.0
        lam = PENALTY_GAMES * per_game
        XtW = X.T * w
        P = lam * np.eye(X.shape[1])
        P[0, 0] = P[1, 1] = 1e-6
        try:
            beta = np.linalg.solve(XtW @ X + P, XtW @ y)
        except np.linalg.LinAlgError:
            beta = np.zeros(X.shape[1])
        out[f"off_{name}"] = beta[2:2 + T]
        out[f"def_{name}"] = beta[2 + T:]
        out.setdefault("_mean", {})[name] = beta[0]
        out.setdefault("_home", {})[name] = beta[1]
    means = out.pop("_mean")
    homes = out.pop("_home")
    df = pd.DataFrame(out)
    df["games_this_season"] = df["team"].map(counts).fillna(0).astype(int)
    df.attrs["means"] = means
    df.attrs["home"] = homes
    return df


def matchup_frame(week: pd.DataFrame, ratings: pd.DataFrame, stats=STATS) -> pd.DataFrame:
    """Per game, each side's offence rating and the opposing defence rating, for every stat."""
    r = ratings.set_index("team") if len(ratings) else pd.DataFrame()
    rows = []
    for g in week.itertuples():
        row = {"game_id": g.game_id}
        for name in stats:
            for side, team, opp in (("h", g.home_team, g.away_team), ("a", g.away_team, g.home_team)):
                row[f"{side}_off_{name}"] = r[f"off_{name}"].get(team, 0.0) if len(r) else 0.0
                row[f"{side}_def_{name}"] = r[f"def_{name}"].get(team, 0.0) if len(r) else 0.0
        row["h_games"] = r["games_this_season"].get(g.home_team, 0) if len(r) else 0
        row["a_games"] = r["games_this_season"].get(g.away_team, 0) if len(r) else 0
        rows.append(row)
    return pd.DataFrame(rows)


def build(snap, week: pd.DataFrame) -> pd.DataFrame:
    """Feature-bank builder: the week's games with unit ratings as of the snapshot."""
    if not len(week):
        return pd.DataFrame()
    s, w = int(week["season"].iloc[0]), int(week["week"].iloc[0])
    rt = unit_ratings(snap.team_games, snap.games, s, w)
    return matchup_frame(week, rt)
