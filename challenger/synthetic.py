"""A made-up league for tests: schedules, results and pbp-style aggregates.

SYNTHETIC - NOT REAL NFL. Seasons are 2101+, teams are named after real
stadium ids only so the venue code has coordinates to work with. Each week
has one Thursday game and the rest on Sunday, so same-week leakage can be
tested. Team strength drifts, and every pbp metric is a noisy function of
it, so the models have something real (if invented) to find.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .pbp import METRICS

TEAMS = {"KC": "KAN00", "BUF": "BUF00", "MIA": "MIA00", "SEA": "SEA00", "DEN": "DEN00", "CHI": "CHI98",
         "DAL": "DAL00", "GB": "GNB00", "NE": "BOS00", "PIT": "PIT00", "TB": "TAM00", "LV": "VEG00"}


def league(seasons=range(2101, 2107), weeks: int = 12, seed: int = 3):
    """(raw schedule frame, team_games, qb_games) for the synthetic league."""
    rng = np.random.default_rng(seed)
    teams = list(TEAMS)
    off = dict(zip(teams, rng.normal(0, 1, len(teams))))
    deff = dict(zip(teams, rng.normal(0, 1, len(teams))))
    qb_of = {t: f"QB-{t}-0" for t in teams}
    rows, team_rows, qb_rows = [], [], []
    for season in seasons:
        start = pd.Timestamp(f"{season - 100}-09-10")   # dates in a real calendar; ids say 21xx
        for t in teams:
            off[t] = 0.6 * off[t] + rng.normal(0, 0.8)
            deff[t] = 0.6 * deff[t] + rng.normal(0, 0.8)
        for week in range(1, weeks + 1):
            order = rng.permutation(teams)
            thursday = start + pd.Timedelta(days=7 * (week - 1))
            for i in range(0, len(order), 2):
                home, away = order[i], order[i + 1]
                day = thursday if i == 0 else thursday + pd.Timedelta(days=3)
                for t in (home, away):
                    off[t] += rng.normal(0, 0.15)
                    deff[t] += rng.normal(0, 0.15)
                    if rng.random() < 0.02:
                        qb_of[t] = f"QB-{t}-{season}-{week}"
                net_h, net_a = off[home] - deff[away], off[away] - deff[home]
                margin = 3.0 * (net_h - net_a) + 2.0 + rng.normal(0, 12)
                hs = max(0, int(round(21 + margin / 2 + rng.normal(0, 3))))
                aws = max(0, int(round(hs - margin)))
                if hs == aws:
                    hs += 1
                gid = f"{season}_{week:02d}_{away}_{home}"
                rows.append({
                    "game_id": gid, "season": season, "game_type": "REG", "week": week,
                    "gameday": day.strftime("%Y-%m-%d"), "gametime": "20:15" if i == 0 else "13:00",
                    "away_team": away, "home_team": home, "away_score": aws, "home_score": hs,
                    "location": "Home", "result": hs - aws, "total": hs + aws, "div_game": 0,
                    "roof": "outdoors", "surface": "grass", "stadium_id": TEAMS[home],
                    "spread_line": round(3.0 * (net_h - net_a) + 2.0, 1),
                    "home_moneyline": -150, "away_moneyline": 130,
                })
                for team, opp, net in ((home, away, net_h), (away, home, net_a)):
                    r = {"game_id": gid, "season": season, "week": week, "team": team, "opp": opp,
                         "off_plays": 62, "def_plays": 62}
                    for m in METRICS:
                        r[f"off_{m}"] = 0.08 * net + rng.normal(0, 0.12)
                    team_rows.append(r)
                    db = int(rng.integers(28, 45))
                    qb_rows.append({"game_id": gid, "season": season, "week": week, "team": team,
                                    "qb_id": qb_of[team], "name": qb_of[team], "dropbacks": db,
                                    "epa_sum": db * (0.05 * off[team] + rng.normal(0, 0.15)),
                                    "sacks": float(rng.integers(0, 5)), "ints": float(rng.integers(0, 3)),
                                    "cpoe_sum": db * rng.normal(0, 3), "cpoe_n": float(db),
                                    "rush_epa_sum": rng.normal(0, 2), "rushes": 3.0, "starter": 1})
    tg = pd.DataFrame(team_rows)
    # defence = the opponent's offence, as pbp.team_games builds it
    off_cols = [f"off_{m}" for m in METRICS]
    opp = tg[["game_id", "team"] + off_cols].rename(columns={"team": "opp", **{c: "def_" + c[4:] for c in off_cols}})
    tg = tg.merge(opp, on=["game_id", "opp"], how="left")
    return pd.DataFrame(rows), tg, pd.DataFrame(qb_rows)
