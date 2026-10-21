"""Play-by-play to one row per team per game (offence and defence) and per QB.

Only scrimmage plays count: `pass == 1 or rush == 1` with an EPA value
(nflfastR's convention - sacks and scrambles are dropbacks, kneels and spikes
are dropped by the EPA filter or by name). Everything here describes a game
that has been played; features.py decides when each row may be seen.

Team-game columns (prefix `off_`, and the same from the opponent's offence as
`def_` - for a defence, a higher number is worse):

    plays, epa (per play), pass_epa (per dropback), rush_epa (per designed run),
    success, explosive (pass >= 20 yards or run >= 10), third (3rd-down
    conversion rate), rz (touchdowns per drive reaching the opponent 20),
    sack (sacks per dropback), pressure (sacks + QB hits per dropback - a
    proxy: true pressure charting only exists from 2018), turnover
    (interceptions + fumbles lost per play), ypp (yards per play)

QB-game columns: the starter (most dropbacks for the team), and for every QB
with a dropback: dropbacks, EPA on dropbacks, sacks, interceptions, CPOE
sum/count, and EPA on his own designed runs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import franchise, pbp_path

COLUMNS = [
    "game_id", "season", "week", "posteam", "defteam", "pass", "rush", "epa", "success",
    "yards_gained", "down", "third_down_converted", "third_down_failed", "qb_dropback",
    "sack", "qb_hit", "interception", "fumble_lost", "fixed_drive", "fixed_drive_result",
    "drive_inside20", "passer_id", "passer", "rusher_id", "qb_epa", "cpoe", "play_type",
]

#: First season with QB hits charted in the play-by-play.
PRESSURE_FROM = 2006

METRICS = ("epa", "pass_epa", "rush_epa", "success", "explosive", "third", "rz",
           "sack", "pressure", "turnover", "ypp")


def read_season(season: int) -> pd.DataFrame:
    import pyarrow.parquet as pq

    path = pbp_path(season)
    names = set(pq.ParquetFile(path).schema.names)
    cols = [c for c in COLUMNS if c in names]
    frame = pq.read_table(path, columns=cols).to_pandas()
    for c in COLUMNS:
        if c not in frame.columns:
            frame[c] = np.nan
    return frame


def _rate(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den.where(den > 0)).astype(float)


def team_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per (game, offence) with offensive rates, then joined to the opponent's as defence."""
    p = pbp[pbp["posteam"].notna() & pbp["defteam"].notna()].copy()
    scrim = p[((p["pass"] == 1) | (p["rush"] == 1)) & p["epa"].notna()
              & ~p["play_type"].isin(["qb_kneel", "qb_spike"])].copy()
    scrim["is_pass"] = (scrim["pass"] == 1).astype(float)
    scrim["is_rush"] = ((scrim["rush"] == 1) & (scrim["pass"] != 1)).astype(float)
    scrim["pass_epa_v"] = scrim["epa"] * scrim["is_pass"]
    scrim["rush_epa_v"] = scrim["epa"] * scrim["is_rush"]
    yards = scrim["yards_gained"].fillna(0)
    scrim["explosive_v"] = (((scrim["is_pass"] == 1) & (yards >= 20)) | ((scrim["is_rush"] == 1) & (yards >= 10))).astype(float)
    scrim["sack_v"] = scrim["sack"].fillna(0)
    scrim["hit_v"] = np.clip(scrim["sack"].fillna(0) + scrim["qb_hit"].fillna(0), 0, 1) * scrim["is_pass"]
    scrim["to_v"] = scrim["interception"].fillna(0) + scrim["fumble_lost"].fillna(0)
    scrim["yards_v"] = yards
    keys = ["game_id", "season", "week", "posteam", "defteam"]
    agg = scrim.groupby(keys, as_index=False).agg(
        plays=("epa", "size"), epa_sum=("epa", "sum"), success_sum=("success", "sum"),
        dropbacks=("is_pass", "sum"), runs=("is_rush", "sum"),
        pass_epa_sum=("pass_epa_v", "sum"), rush_epa_sum=("rush_epa_v", "sum"),
        explosive_sum=("explosive_v", "sum"), sack_sum=("sack_v", "sum"),
        hit_sum=("hit_v", "sum"), to_sum=("to_v", "sum"), yards_sum=("yards_v", "sum"),
    )
    third = p[p["down"] == 3].groupby(["game_id", "posteam"], as_index=False).agg(
        conv=("third_down_converted", "sum"), fail=("third_down_failed", "sum"))
    drives = p[p["fixed_drive"].notna()].groupby(["game_id", "posteam", "fixed_drive"], as_index=False).agg(
        inside20=("drive_inside20", "max"), result=("fixed_drive_result", "first"))
    drives = drives[drives["inside20"] == 1]
    drives["td"] = (drives["result"] == "Touchdown").astype(float)
    rz = drives.groupby(["game_id", "posteam"], as_index=False).agg(rz_trips=("td", "size"), rz_td=("td", "sum"))
    out = agg.merge(third, on=["game_id", "posteam"], how="left").merge(rz, on=["game_id", "posteam"], how="left")
    out["off_plays"] = out["plays"]
    out["off_epa"] = _rate(out["epa_sum"], out["plays"])
    out["off_pass_epa"] = _rate(out["pass_epa_sum"], out["dropbacks"])
    out["off_rush_epa"] = _rate(out["rush_epa_sum"], out["runs"])
    out["off_success"] = _rate(out["success_sum"], out["plays"])
    out["off_explosive"] = _rate(out["explosive_sum"], out["plays"])
    out["off_third"] = _rate(out["conv"].fillna(0), out["conv"].fillna(0) + out["fail"].fillna(0))
    out["off_rz"] = _rate(out["rz_td"].fillna(0), out["rz_trips"].fillna(0))
    out["off_sack"] = _rate(out["sack_sum"], out["dropbacks"])
    out["off_pressure"] = _rate(out["hit_sum"], out["dropbacks"])
    # QB hits are not recorded before 2006, so before then the "pressure" proxy
    # would silently be sacks only: left missing rather than mixed.
    out.loc[out["season"] < PRESSURE_FROM, "off_pressure"] = np.nan
    out["off_turnover"] = _rate(out["to_sum"], out["plays"])
    out["off_ypp"] = _rate(out["yards_sum"], out["plays"])
    off_cols = [f"off_{m}" for m in METRICS]
    out = out[["game_id", "season", "week", "posteam", "defteam", "off_plays"] + off_cols]
    opp = out[["game_id", "posteam", "off_plays"] + off_cols].rename(
        columns={"posteam": "defteam", "off_plays": "def_plays", **{c: "def_" + c[4:] for c in off_cols}})
    both = out.merge(opp, on=["game_id", "defteam"], how="left")
    both = both.rename(columns={"posteam": "team", "defteam": "opp"})
    both["team"] = both["team"].map(franchise)
    both["opp"] = both["opp"].map(franchise)
    return both


def qb_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per (game, team, QB) for every passer with a dropback; `starter` marks the team's main one."""
    p = pbp[pbp["posteam"].notna()].copy()
    drop = p[(p["qb_dropback"] == 1) & p["passer_id"].notna() & p["epa"].notna()].copy()
    drop["cpoe_n"] = drop["cpoe"].notna().astype(float)
    qb = drop.groupby(["game_id", "season", "week", "posteam", "passer_id"], as_index=False).agg(
        name=("passer", "first"), dropbacks=("epa", "size"),
        epa_sum=("qb_epa", "sum"), sacks=("sack", "sum"), ints=("interception", "sum"),
        cpoe_sum=("cpoe", "sum"), cpoe_n=("cpoe_n", "sum"))
    runs = p[(p["rush"] == 1) & (p["pass"] != 1) & p["rusher_id"].notna() & p["epa"].notna()]
    runs = runs.groupby(["game_id", "posteam", "rusher_id"], as_index=False).agg(
        rush_epa_sum=("epa", "sum"), rushes=("epa", "size")).rename(columns={"rusher_id": "passer_id"})
    qb = qb.merge(runs, on=["game_id", "posteam", "passer_id"], how="left")
    qb[["rush_epa_sum", "rushes"]] = qb[["rush_epa_sum", "rushes"]].fillna(0)
    qb = qb.sort_values(["game_id", "posteam", "dropbacks", "passer_id"], ascending=[True, True, False, True])
    qb["starter"] = (~qb.duplicated(["game_id", "posteam"])).astype(int)
    qb = qb.rename(columns={"posteam": "team", "passer_id": "qb_id"})
    qb["team"] = qb["team"].map(franchise)
    return qb.reset_index(drop=True)


def aggregate(seasons) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Team-game and QB-game tables for the given seasons, cached per season as parquet."""
    from .config import CACHE
    from .data import sha256

    teams, qbs = [], []
    folder = CACHE / "agg"
    folder.mkdir(parents=True, exist_ok=True)
    for season in seasons:
        src = pbp_path(season)
        if not src.exists():
            continue
        stamp = sha256(src)[:16]
        tp, qp = folder / f"team_{season}_{stamp}.parquet", folder / f"qb_{season}_{stamp}.parquet"
        if tp.exists() and qp.exists():
            teams.append(pd.read_parquet(tp))
            qbs.append(pd.read_parquet(qp))
            continue
        for old in list(folder.glob(f"team_{season}_*.parquet")) + list(folder.glob(f"qb_{season}_*.parquet")):
            old.unlink()
        raw = read_season(season)
        t, q = team_games(raw), qb_games(raw)
        t.to_parquet(tp, index=False)
        q.to_parquet(qp, index=False)
        teams.append(t)
        qbs.append(q)
    if not teams:
        return pd.DataFrame(), pd.DataFrame()
    return pd.concat(teams, ignore_index=True), pd.concat(qbs, ignore_index=True)
