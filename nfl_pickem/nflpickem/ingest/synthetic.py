"""Clearly labelled SYNTHETIC demonstration dataset.

Nothing generated here is real NFL data. Team codes are SYN01..SYNnn, seasons
are 2101+, and every row carries data_source='synthetic' / provider='synthetic'.
It exists so the whole pipeline (features -> models -> backtest -> dashboard)
can run offline and in tests without any network access or credentials.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .. import db

SYNTHETIC_FIRST_SEASON = 2101
SOURCE = "synthetic"


def _american(prob: float) -> float:
    prob = min(max(prob, 0.02), 0.98)
    return round(-100 * prob / (1 - prob)) if prob >= 0.5 else round(100 * (1 - prob) / prob)


def generate(n_teams: int = 16, n_seasons: int = 6, weeks: int = 14, seed: int = 7,
             played_weeks_last_season: int | None = 8) -> dict[str, pd.DataFrame]:
    """Return games, odds and team_game_stats frames for a synthetic league.

    The last season is only partly played (``played_weeks_last_season``) so the
    weekly-picks workflow has an upcoming slate to predict.
    """
    if n_teams % 2:
        raise ValueError("n_teams must be even")
    rng = np.random.default_rng(seed)
    teams = [f"SYN{i + 1:02d}" for i in range(n_teams)]
    off = rng.normal(0, 3.0, n_teams)
    dfn = rng.normal(0, 3.0, n_teams)
    games, odds, stats = [], [], []
    now = datetime(2101 + n_seasons - 1, 9, 1) + timedelta(weeks=(played_weeks_last_season or weeks), days=2)
    for s_idx in range(n_seasons):
        season = SYNTHETIC_FIRST_SEASON + s_idx
        off = 0.6 * off + rng.normal(0, 1.8, n_teams)
        dfn = 0.6 * dfn + rng.normal(0, 1.8, n_teams)
        start = datetime(season, 9, 7, 17, 0)
        for week in range(1, weeks + 1):
            off += rng.normal(0, 0.4, n_teams)
            dfn += rng.normal(0, 0.4, n_teams)
            order = rng.permutation(n_teams)
            played = not (s_idx == n_seasons - 1 and played_weeks_last_season is not None
                          and week > played_weeks_last_season)
            for k in range(0, n_teams, 2):
                h, a = order[k], order[k + 1]
                kickoff = start + timedelta(weeks=week - 1, hours=int(rng.choice([0, 0, 0, 3, 27])))
                backup_h, backup_a = rng.random() < 0.06, rng.random() < 0.06
                exp_margin = (off[h] + dfn[h] - 3.5 * backup_h) - (off[a] + dfn[a] - 3.5 * backup_a) + 2.0
                margin = exp_margin + rng.normal(0, 13.0)
                total = 44 + rng.normal(0, 9)
                hs, as_ = max(0, round((total + margin) / 2)), max(0, round((total - margin) / 2))
                gid = f"SYN_{season}_{week:02d}_{teams[a]}_{teams[h]}"
                games.append({
                    "game_id": gid, "season": season, "week": week, "game_type": "REG",
                    "game_date": kickoff.date(), "kickoff_utc": kickoff,
                    "home_team": teams[h], "away_team": teams[a],
                    "home_score": hs if played else None, "away_score": as_ if played else None,
                    "game_status": "final" if played else "scheduled", "location": "Home",
                    "div_game": int(abs(h - a) < 4), "roof": "outdoors", "temp": None, "wind": None,
                    "home_qb_id": f"{teams[h]}_QB{2 if backup_h else 1}",
                    "away_qb_id": f"{teams[a]}_QB{2 if backup_a else 1}",
                    "home_qb_name": f"{teams[h]} QB{2 if backup_h else 1}",
                    "away_qb_name": f"{teams[a]} QB{2 if backup_a else 1}",
                    "data_source": SOURCE, "updated_at": now,
                })
                # Market: noisy view of the true expected margin plus ~4.5% vig.
                mkt_margin = exp_margin + rng.normal(0, 1.5)
                p_home = float(1 / (1 + np.exp(-mkt_margin / 7.0)))
                vig = 0.0225
                odds.append({
                    "game_id": gid, "captured_at": now - timedelta(hours=2) if not played else pd.NaT,
                    "provider": SOURCE,
                    "home_moneyline": _american(p_home + vig), "away_moneyline": _american(1 - p_home + vig),
                    "home_spread": -round(mkt_margin * 2) / 2, "source_timestamp": pd.NaT,
                    "is_closing": played,
                })
                if played:
                    for t, o, opp_d, sc in ((h, off[h], dfn[a], hs), (a, off[a], dfn[h], as_)):
                        plays = int(rng.integers(55, 70))
                        epa_pp = 0.012 * (o - opp_d) + rng.normal(0, 0.12)
                        stats.append({"game_id": gid, "team": teams[t], "plays": plays,
                                      "off_epa_sum": epa_pp * plays,
                                      "off_success_sum": plays * float(np.clip(0.44 + epa_pp * 0.5, 0.2, 0.7)),
                                      "pass_plays": int(plays * 0.58), "pass_epa_sum": epa_pp * plays * 0.65,
                                      "explosive_plays": int(rng.poisson(5 + 4 * epa_pp)),
                                      "turnovers": int(rng.poisson(max(0.3, 1.3 - 2 * epa_pp)))})
    st = pd.DataFrame(stats)
    st = _attach_defense(st, pd.DataFrame(games))
    st["source"] = SOURCE
    detail, qbs = _detail(st, pd.DataFrame(games), rng)
    return {"games": pd.DataFrame(games), "odds": pd.DataFrame(odds), "team_game_stats": st,
            "team_game_detail": detail, "qb_game_stats": qbs, "now": now}


def _detail(st: pd.DataFrame, games: pd.DataFrame, rng) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthetic unit-level aggregates consistent with the team-game stats."""
    epa_pp = st["off_epa_sum"] / st["plays"]
    db = st["pass_plays"] + 2
    rush = st["plays"] - db
    sacks = rng.poisson(np.clip(2.5 - 6 * epa_pp, 0.3, 6))
    d = pd.DataFrame({
        "game_id": st["game_id"], "team": st["team"], "dropbacks": db,
        "dropback_epa_sum": st["pass_epa_sum"] * db / st["pass_plays"], "sacks": sacks,
        "qb_hits": sacks + rng.poisson(4, len(st)), "interceptions": rng.poisson(0.8, len(st)),
        "cpoe_sum": (epa_pp * 20 + rng.normal(0, 4, len(st))) * (db - 4), "cpoe_n": db - 4,
        "explosive_passes": rng.poisson(np.clip(3 + 8 * epa_pp, 0.5, 9)),
        "rush_plays": rush, "rush_epa_sum": (st["off_epa_sum"] - st["pass_epa_sum"] * db / st["pass_plays"]),
        "rush_success_sum": rush * np.clip(0.4 + epa_pp * 0.5, 0.2, 0.7),
        "early_plays": (st["plays"] * 0.65).astype(int), "early_epa_sum": st["off_epa_sum"] * 0.6,
        "early_success_sum": st["off_success_sum"] * 0.65, "early_pass": (db * 0.55).astype(int),
        "third_att": rng.integers(10, 16, len(st)),
    })
    d["third_conv"] = np.clip(np.round(d["third_att"] * np.clip(0.4 + epa_pp, 0.1, 0.8)), 0, d["third_att"]).astype(int)
    d["rz_drives"] = rng.integers(1, 6, len(st))
    d["rz_td_drives"] = np.minimum(d["rz_drives"], rng.binomial(d["rz_drives"], np.clip(0.55 + epa_pp, 0.1, 0.9)))
    d["neutral_plays"] = (st["plays"] * 0.8).astype(int)
    d["neutral_epa_sum"] = st["off_epa_sum"] * 0.8
    d["source"] = SOURCE
    side = pd.concat([games[["game_id", "home_team", "home_qb_id"]].set_axis(["game_id", "team", "qb_id"], axis=1),
                      games[["game_id", "away_team", "away_qb_id"]].set_axis(["game_id", "team", "qb_id"], axis=1)])
    q = d[["game_id", "team", "dropbacks", "dropback_epa_sum", "cpoe_sum", "cpoe_n", "sacks", "interceptions"]] \
        .merge(side, on=["game_id", "team"]).rename(columns={"dropback_epa_sum": "epa_sum"})
    q["qb_name"] = q["qb_id"]
    q["scrambles"] = 0
    q["scramble_epa_sum"] = 0.0
    q["source"] = SOURCE
    return d, q


def _attach_defense(st: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    opp = pd.concat([
        games[["game_id", "home_team", "away_team"]].rename(columns={"home_team": "team", "away_team": "opp"}),
        games[["game_id", "away_team", "home_team"]].rename(columns={"away_team": "team", "home_team": "opp"}),
    ])
    st = st.merge(opp, on=["game_id", "team"])
    d = st[["game_id", "team", "plays", "off_epa_sum", "off_success_sum", "explosive_plays", "turnovers"]].rename(
        columns={"team": "opp", "plays": "def_plays", "off_epa_sum": "def_epa_sum",
                 "off_success_sum": "def_success_sum", "explosive_plays": "def_explosive_plays",
                 "turnovers": "takeaways"})
    return st.merge(d, on=["game_id", "opp"]).drop(columns="opp")


def load_into(con, **kwargs) -> datetime:
    """Generate the synthetic league and write it to the database. Returns its 'now'."""
    data = generate(**kwargs)
    games = data["games"]
    games["home_score"] = games["home_score"].astype("Int64")
    games["away_score"] = games["away_score"].astype("Int64")
    db.upsert_games(con, games)
    db.upsert_odds(con, data["odds"])
    db.upsert_team_stats(con, data["team_game_stats"])
    db.upsert(con, "team_game_detail", data["team_game_detail"], db.DETAIL_COLUMNS)
    db.upsert(con, "qb_game_stats", data["qb_game_stats"], db.QB_COLUMNS)
    db.set_meta(con, "data_mode", "synthetic")
    db.set_meta(con, "synthetic_now", data["now"].isoformat())
    db.log_ingestion(con, SOURCE, "synthetic league", len(games), "ok", "SYNTHETIC DEMO DATA")
    return data["now"]
