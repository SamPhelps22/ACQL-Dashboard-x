"""Play-by-play reduced to three tables the models read.

    team_games   one row per (game, offense): efficiency, explosives, pressure
                 proxies, third downs, red zone, turnovers, drives, points
    qb_games     one row per (game, team): the main passer and his numbers
    drives       one row per drive: start field position, result, points

These hold only what happened in each game. A model may read a row only when
the game it describes was completed before the forecast (games.visible) -
that rule is enforced by the feature builders, not here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config

COLUMNS = [
    "game_id", "season", "season_type", "week", "posteam", "defteam", "play_type", "epa", "success",
    "qb_dropback", "qb_scramble", "pass", "rush", "sack", "interception", "fumble_lost", "qb_hit",
    "yards_gained", "down", "third_down_converted", "third_down_failed", "fourth_down_converted",
    "fourth_down_failed", "passer_id", "rusher_id", "cpoe", "qb_epa", "fixed_drive", "fixed_drive_result",
    "drive_inside20", "yardline_100", "touchdown", "td_team", "special", "game_half", "drive_play_count",
    "air_yards", "shotgun", "no_huddle", "pass_oe", "xpass",
]

DRIVE_RESULTS = {"Touchdown": "TD", "Field goal": "FG", "Punt": "PUNT", "Turnover": "TO",
                 "Turnover on downs": "DOWNS", "Missed field goal": "MISS", "End of half": "END",
                 "Safety": "SAFETY", "Opp touchdown": "TO"}


def _read(season: int) -> pd.DataFrame:
    path = config.RAW / f"pbp_{season}.csv.gz"
    cols = pd.read_csv(path, nrows=0).columns
    df = pd.read_csv(path, usecols=[c for c in COLUMNS if c in cols], low_memory=False)
    for c in ("posteam", "defteam", "td_team"):
        df[c] = df[c].map(lambda x: config.team(x) if isinstance(x, str) else x)
    return df


def team_games(p: pd.DataFrame) -> pd.DataFrame:
    plays = p[p["posteam"].notna() & p["epa"].notna() & ((p["pass"] == 1) | (p["rush"] == 1))].copy()
    plays["db"] = (plays["qb_dropback"] == 1).astype(int)
    plays["run"] = 1 - plays["db"]
    plays["pass_epa"] = plays["epa"] * plays["db"]
    plays["run_epa"] = plays["epa"] * plays["run"]
    plays["run_succ"] = plays["success"] * plays["run"]
    plays["pass_succ"] = plays["success"] * plays["db"]
    plays["expl_pass"] = ((plays["db"] == 1) & (plays["yards_gained"] >= 20)).astype(int)
    plays["expl_run"] = ((plays["run"] == 1) & (plays["yards_gained"] >= 10)).astype(int)
    plays["third"] = ((plays["down"] == 3)).astype(int)
    plays["third_conv"] = plays["third_down_converted"].fillna(0) * plays["third"]
    plays["to"] = plays["interception"].fillna(0) + plays["fumble_lost"].fillna(0)
    plays["early_down_pass"] = ((plays["down"] <= 2) & (plays["db"] == 1)).astype(int)
    plays["early_down"] = (plays["down"] <= 2).astype(int)
    g = plays.groupby(["game_id", "posteam", "defteam"])
    out = g.agg(season=("season", "first"), week=("week", "first"), plays=("epa", "size"), epa=("epa", "sum"),
                succ=("success", "sum"), dropbacks=("db", "sum"), pass_epa=("pass_epa", "sum"),
                pass_succ=("pass_succ", "sum"), runs=("run", "sum"), run_epa=("run_epa", "sum"),
                run_succ=("run_succ", "sum"), sacks=("sack", "sum"), ints=("interception", "sum"),
                fumbles_lost=("fumble_lost", "sum"), qb_hits=("qb_hit", "sum"), expl_pass=("expl_pass", "sum"),
                expl_run=("expl_run", "sum"), thirds=("third", "sum"), third_conv=("third_conv", "sum"),
                turnovers=("to", "sum"), early_downs=("early_down", "sum"),
                early_down_passes=("early_down_pass", "sum")).reset_index()
    # red zone: drives that reached the 20, and how many ended in a touchdown
    d = drives(p)
    rz = d.groupby(["game_id", "posteam"]).agg(rz_drives=("inside20", "sum"), rz_tds=("rz_td", "sum"),
                                               n_drives=("result", "size"), drive_points=("points", "sum"),
                                               start_yd=("start_yardline_100", "mean")).reset_index()
    out = out.merge(rz, on=["game_id", "posteam"], how="left")
    return out.rename(columns={"posteam": "team", "defteam": "opp"})


def drives(p: pd.DataFrame) -> pd.DataFrame:
    x = p[p["posteam"].notna() & p["fixed_drive"].notna() & p["fixed_drive_result"].notna()
          & (p["play_type"] != "kickoff")]          # a drive starts where its first scrimmage play is
    first = x.groupby(["game_id", "fixed_drive"]).agg(
        season=("season", "first"), week=("week", "first"), posteam=("posteam", "first"), defteam=("defteam", "first"),
        start_yardline_100=("yardline_100", "first"), result_raw=("fixed_drive_result", "first"),
        inside20=("drive_inside20", "max"), half=("game_half", "first"), n_plays=("drive_play_count", "first")).reset_index()
    first["result"] = first["result_raw"].map(DRIVE_RESULTS).fillna("OTHER")
    first["points"] = first["result"].map({"TD": 7, "FG": 3}).fillna(0)   # conversions handled in the simulator
    first["inside20"] = first["inside20"].fillna(0)
    first["rz_td"] = ((first["inside20"] == 1) & (first["result"] == "TD")).astype(int)
    first = first.sort_values(["game_id", "fixed_drive"])
    prev = first.groupby("game_id")["result"].shift(1)
    prev_half = first.groupby("game_id")["half"].shift(1)
    first["prev_result"] = np.where(prev.isna() | (prev_half != first["half"]), "KICKOFF_HALF", prev)
    return first


def qb_games(p: pd.DataFrame) -> pd.DataFrame:
    db = p[(p["qb_dropback"] == 1) & p["passer_id"].notna() & p["posteam"].notna()].copy()
    db["hit"] = db["qb_hit"].fillna(0)
    db["epa_hit"] = db["qb_epa"].where(db["hit"] == 1)
    db["epa_clean"] = db["qb_epa"].where(db["hit"] == 0)
    g = db.groupby(["game_id", "posteam", "defteam", "passer_id"]).agg(
        season=("season", "first"), week=("week", "first"), dropbacks=("qb_epa", "size"), qb_epa=("qb_epa", "sum"),
        cpoe_sum=("cpoe", "sum"), cpoe_n=("cpoe", "count"), sacks=("sack", "sum"), ints=("interception", "sum"),
        hits=("hit", "sum"), epa_hit=("epa_hit", "sum"), epa_clean=("epa_clean", "sum"),
        scrambles=("qb_scramble", "sum")).reset_index()
    # designed runs by the same player
    runs = p[(p["rush"] == 1) & (p["qb_dropback"] != 1) & p["rusher_id"].notna()]
    r = runs.groupby(["game_id", "rusher_id"]).agg(qb_runs=("epa", "size"), qb_run_epa=("epa", "sum")).reset_index()
    g = g.merge(r, left_on=["game_id", "passer_id"], right_on=["game_id", "rusher_id"], how="left").drop(columns="rusher_id")
    g[["qb_runs", "qb_run_epa"]] = g[["qb_runs", "qb_run_epa"]].fillna(0)
    total = g.groupby(["game_id", "posteam"])["dropbacks"].transform("sum")
    g["share"] = g["dropbacks"] / total
    g["main"] = g.groupby(["game_id", "posteam"])["dropbacks"].rank(ascending=False, method="first") == 1
    return g.rename(columns={"posteam": "team", "defteam": "opp"})


def build(seasons=None, out=config.DERIVED) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    seasons = seasons or range(config.FIRST_SEASON, config.CURRENT_SEASON + 1)
    tg, qb, dr = [], [], []
    for s in seasons:
        path = config.RAW / f"pbp_{s}.csv.gz"
        if not path.exists():
            continue
        p = _read(s)
        tg.append(team_games(p))
        qb.append(qb_games(p))
        dr.append(drives(p).drop(columns=["result_raw"]))
    tables = {"team_games": pd.concat(tg), "qb_games": pd.concat(qb), "drives": pd.concat(dr)}
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv.gz", index=False)
    return {k: len(v) for k, v in tables.items()}


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(config.DERIVED / f"{name}.csv.gz", low_memory=False)
