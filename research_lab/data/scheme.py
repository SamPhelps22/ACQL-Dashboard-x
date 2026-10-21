"""Model H data: coverage, pressure and personnel per team-game, from nflverse participation.

nflverse `pbp_participation` (2016-2025) carries, per play, the defence's
man/zone label and coverage shell (from 2018, about 40-50% of plays labelled),
whether the passer was pressured (2016+, partial until 2023), offensive
personnel and formation. It is joined to play-by-play EPA by (game, play).

Per (game, offence) the table holds dropbacks and EPA against man and against
zone, pressured dropbacks, 11-personnel snaps and shotgun snaps; the defence's
side is the same row read from the other team. Only completed games are ever
read by a model (Store.snapshot).

Licensing: nflverse redistributes these fields (participation derived from
NFL Next Gen Stats; FTN charting under CC-BY-SA 4.0). Fine for this research;
redistribution of the raw files is not done here.
"""

from __future__ import annotations

import pandas as pd

from .. import config

FIRST = 2016


def _season(y: int) -> pd.DataFrame | None:
    part = config.RAW / f"participation_{y}.csv"
    pbp = config.RAW / f"pbp_{y}.csv.gz"
    if not part.exists() or not pbp.exists():
        return None
    pa = pd.read_csv(part, low_memory=False, usecols=["nflverse_game_id", "play_id", "possession_team",
                                                     "offense_personnel", "offense_formation", "was_pressure",
                                                     "defense_man_zone_type"])
    pb = pd.read_csv(pbp, low_memory=False, usecols=["game_id", "play_id", "season", "week", "posteam", "defteam",
                                                     "epa", "qb_dropback", "pass", "rush"])
    pb = pb[pb["posteam"].notna() & pb["epa"].notna() & ((pb["pass"] == 1) | (pb["rush"] == 1))]
    d = pb.merge(pa, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="inner")
    d["posteam"] = d["posteam"].map(config.team)
    d["defteam"] = d["defteam"].map(config.team)
    db = d["qb_dropback"] == 1
    man = db & (d["defense_man_zone_type"] == "MAN_COVERAGE")
    zone = db & (d["defense_man_zone_type"] == "ZONE_COVERAGE")
    pres_known = db & d["was_pressure"].notna()
    pres = pres_known & (d["was_pressure"].astype(str).str.lower() == "true")
    d = d.assign(db_man=man.astype(int), epa_man=d["epa"].where(man, 0.0), db_zone=zone.astype(int),
                 epa_zone=d["epa"].where(zone, 0.0), cov_known=(man | zone).astype(int),
                 press_den=pres_known.astype(int), press=pres.astype(int),
                 p11=d["offense_personnel"].astype(str).str.contains("1 RB.*1 TE.*3 WR").astype(int),
                 pers_known=d["offense_personnel"].notna().astype(int),
                 gun=(d["offense_formation"] == "SHOTGUN").astype(int), form_known=d["offense_formation"].notna().astype(int))
    g = d.groupby(["game_id", "posteam", "defteam"]).agg(
        season=("season", "first"), week=("week", "first"), db_man=("db_man", "sum"), epa_man=("epa_man", "sum"),
        db_zone=("db_zone", "sum"), epa_zone=("epa_zone", "sum"), cov_known=("cov_known", "sum"),
        press=("press", "sum"), press_den=("press_den", "sum"), p11=("p11", "sum"), pers_known=("pers_known", "sum"),
        gun=("gun", "sum"), form_known=("form_known", "sum")).reset_index()
    return g.rename(columns={"posteam": "team", "defteam": "opp"})


def build(out=config.DERIVED) -> int:
    frames = [f for y in range(FIRST, config.CURRENT_SEASON + 1) if (f := _season(y)) is not None]
    df = pd.concat(frames, ignore_index=True)
    df.to_csv(out / "scheme_games.csv.gz", index=False)
    return len(df)


def load() -> pd.DataFrame:
    p = config.DERIVED / "scheme_games.csv.gz"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()
