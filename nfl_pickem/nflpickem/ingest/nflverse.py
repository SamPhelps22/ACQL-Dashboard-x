"""nflverse ingestion: schedules/results, closing lines, play-by-play aggregates, injuries.

Sources (all free, no credentials):
  * Schedules, scores, closing lines, starting QBs, rest, roof, weather:
    https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv
    (updated several times per week in season).
  * Play-by-play (EPA per play):
    https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet
    (updated nightly in season).
  * Injury reports:
    https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from .. import db
from ..teams import normalize_team

log = logging.getLogger(__name__)

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet"
INJURY_URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"
EASTERN = ZoneInfo("America/New_York")
PROVIDER = "nflverse"


def _download(url: str, timeout: int = 180) -> bytes:
    log.info("Downloading %s", url)
    resp = requests.get(url, timeout=timeout)
    if resp.status_code == 404:
        raise FileNotFoundError(url)
    resp.raise_for_status()
    return resp.content


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def kickoff_to_utc(gameday: pd.Series, gametime: pd.Series) -> pd.Series:
    """nflverse gameday/gametime are US/Eastern local; return naive UTC timestamps."""
    gt = gametime.fillna("13:00").astype(str)
    local = pd.to_datetime(gameday.astype(str) + " " + gt, errors="coerce")
    return local.dt.tz_localize(EASTERN, ambiguous="NaT", nonexistent="shift_forward") \
        .dt.tz_convert("UTC").dt.tz_localize(None)


def parse_schedule(raw: pd.DataFrame, now: datetime | None = None,
                   first_season: int | None = None) -> pd.DataFrame:
    """Convert nflverse games.csv into the `games` table layout."""
    now = now or _utcnow()
    df = raw.copy()
    if first_season:
        df = df[df["season"] >= first_season]
    out = pd.DataFrame({
        "game_id": df["game_id"].astype(str),
        "season": df["season"].astype(int),
        "week": df["week"].astype(int),
        "game_type": df["game_type"].astype(str),
        "game_date": pd.to_datetime(df["gameday"], errors="coerce").dt.date,
        "kickoff_utc": kickoff_to_utc(df["gameday"], df["gametime"]),
        "home_team": df["home_team"].map(normalize_team),
        "away_team": df["away_team"].map(normalize_team),
        "home_score": pd.to_numeric(df["home_score"], errors="coerce").astype("Int64"),
        "away_score": pd.to_numeric(df["away_score"], errors="coerce").astype("Int64"),
        "location": df.get("location", "Home"),
        "div_game": pd.to_numeric(df.get("div_game"), errors="coerce").astype("Int64"),
        "roof": df.get("roof"),
        "temp": pd.to_numeric(df.get("temp"), errors="coerce"),
        "wind": pd.to_numeric(df.get("wind"), errors="coerce"),
        "home_qb_id": df.get("home_qb_id"), "away_qb_id": df.get("away_qb_id"),
        "home_qb_name": df.get("home_qb_name"), "away_qb_name": df.get("away_qb_name"),
    })
    out["game_status"] = derive_status(out, now)
    out["data_source"] = PROVIDER
    out["updated_at"] = now
    return db.dedupe_games(out.reset_index(drop=True))


def derive_status(games: pd.DataFrame, now: datetime) -> pd.Series:
    """final if scored; canceled if >7 days past kickoff without a score; else scheduled.

    A game moved to a later date simply gets a new kickoff_utc under the same
    stable game_id, so it stays `scheduled` until it is played.
    """
    scored = games["home_score"].notna() & games["away_score"].notna()
    stale = games["kickoff_utc"] < (pd.Timestamp(now) - pd.Timedelta(days=7))
    status = np.where(scored, "final", np.where(stale, "canceled", "scheduled"))
    return pd.Series(status, index=games.index)


def parse_odds(raw: pd.DataFrame, games: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Lines from games.csv. For finished games these are closing lines with no
    capture time (captured_at NULL, is_closing TRUE). For upcoming games they are
    the current line as observed at download time (captured_at = now)."""
    now = now or _utcnow()
    df = raw[raw["game_id"].isin(games["game_id"])].copy()
    df = df.merge(games[["game_id", "kickoff_utc", "game_status"]], on="game_id")
    df = df[df["home_moneyline"].notna() | df["spread_line"].notna()]
    upcoming = (df["game_status"] == "scheduled") & (df["kickoff_utc"] > pd.Timestamp(now))
    out = pd.DataFrame({
        "game_id": df["game_id"],
        "captured_at": np.where(upcoming, pd.Timestamp(now), pd.NaT),
        "provider": PROVIDER,
        "home_moneyline": pd.to_numeric(df["home_moneyline"], errors="coerce"),
        "away_moneyline": pd.to_numeric(df["away_moneyline"], errors="coerce"),
        # nflverse spread_line is the expected home margin (positive = home favoured).
        "home_spread": -pd.to_numeric(df["spread_line"], errors="coerce"),
        "source_timestamp": pd.NaT,
        "is_closing": ~upcoming,
    })
    out["captured_at"] = pd.to_datetime(out["captured_at"])
    return out.reset_index(drop=True)


def ingest_schedule(con, first_season: int, raw: pd.DataFrame | None = None,
                    now: datetime | None = None) -> pd.DataFrame:
    """Download (or accept) games.csv and upsert games + nflverse odds snapshots."""
    if raw is None:
        raw = pd.read_csv(io.BytesIO(_download(GAMES_URL)), low_memory=False)
    games = parse_schedule(raw, now=now, first_season=first_season)
    n = db.upsert_games(con, games)
    odds = parse_odds(raw, games, now=now)
    # Closing lines replace any earlier closing row; observed current lines accumulate.
    m = db.upsert_odds(con, odds)
    db.log_ingestion(con, PROVIDER, "games.csv", n, "ok", f"{m} odds rows")
    log.info("Upserted %d games and %d odds snapshots", n, m)
    return games


# --------------------------------------------------------------------------- pbp
def aggregate_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    """Aggregate play-by-play to per-team-per-game offensive/defensive sums.

    Plays counted: pass or run plays with a defined EPA, excluding kneels/spikes
    and two-point attempts. Explosive = rush >= 10 yards or pass >= 20 yards.
    """
    p = pbp.copy()
    mask = p["play_type"].isin(["pass", "run"]) & p["epa"].notna() & p["posteam"].notna()
    for col in ("qb_kneel", "qb_spike", "two_point_attempt"):
        if col in p.columns:
            mask &= p[col].fillna(0) == 0
    p = p[mask].copy()
    p["posteam"] = p["posteam"].map(normalize_team)
    p["defteam"] = p["defteam"].map(normalize_team)
    is_pass = p["play_type"] == "pass"
    p["explosive"] = ((is_pass & (p["yards_gained"] >= 20)) | (~is_pass & (p["yards_gained"] >= 10))).astype(int)
    p["turnover"] = (p.get("interception", 0).fillna(0) + p.get("fumble_lost", 0).fillna(0)).clip(0, 1)
    p["is_pass"] = is_pass.astype(int)
    p["pass_epa"] = np.where(is_pass, p["epa"], 0.0)
    p["success"] = p.get("success", (p["epa"] > 0).astype(int)).fillna(0)
    off = p.groupby(["game_id", "posteam"]).agg(
        plays=("epa", "size"), off_epa_sum=("epa", "sum"), off_success_sum=("success", "sum"),
        pass_plays=("is_pass", "sum"), pass_epa_sum=("pass_epa", "sum"),
        explosive_plays=("explosive", "sum"), turnovers=("turnover", "sum"),
    ).reset_index().rename(columns={"posteam": "team"})
    dfn = p.groupby(["game_id", "defteam"]).agg(
        def_plays=("epa", "size"), def_epa_sum=("epa", "sum"), def_success_sum=("success", "sum"),
        def_explosive_plays=("explosive", "sum"), takeaways=("turnover", "sum"),
    ).reset_index().rename(columns={"defteam": "team"})
    out = off.merge(dfn, on=["game_id", "team"], how="outer")
    out["source"] = PROVIDER
    for c in ("plays", "pass_plays", "explosive_plays", "turnovers", "def_plays",
              "def_explosive_plays", "takeaways"):
        out[c] = out[c].fillna(0).astype(int)
    return out


def ingest_pbp(con, seasons: list[int], cache_dir: Path | None = None,
               keep_cache: bool = False, force: bool = False) -> int:
    """Download each season's play-by-play, aggregate, upsert. Skips seasons that
    are complete in the DB unless force=True (incremental updates)."""
    total = 0
    for season in seasons:
        if not force:
            missing = con.execute(
                """SELECT count(*) FROM games g WHERE season=? AND game_status='final'
                   AND (NOT EXISTS (SELECT 1 FROM team_game_stats s WHERE s.game_id=g.game_id)
                        OR NOT EXISTS (SELECT 1 FROM team_game_detail d WHERE d.game_id=g.game_id))""",
                [season]).fetchone()[0]
            if missing == 0:
                log.info("Season %s play-by-play already complete; skipping", season)
                continue
        cache = Path(cache_dir) / f"pbp_{season}.parquet" if cache_dir else None
        try:
            if cache and cache.exists() and not force:
                pbp = pd.read_parquet(cache)
            else:
                content = _download(PBP_URL.format(season=season), timeout=600)
                if cache and keep_cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(content)
                import pyarrow.parquet as pq
                avail = set(pq.ParquetFile(io.BytesIO(content)).schema.names)
                pbp = pd.read_parquet(io.BytesIO(content), columns=[c for c in DETAIL_PBP_COLUMNS if c in avail])
        except FileNotFoundError:
            log.warning("No play-by-play published for %s", season)
            db.log_ingestion(con, PROVIDER, f"pbp_{season}", 0, "missing", "404")
            continue
        agg = aggregate_pbp(pbp)
        n = db.upsert_team_stats(con, agg)
        if {"qb_dropback", "down", "wp"}.issubset(pbp.columns):
            detail, qb = aggregate_pbp_detail(pbp)
            db.upsert(con, "team_game_detail", detail, db.DETAIL_COLUMNS)
            db.upsert(con, "qb_game_stats", qb, db.QB_COLUMNS)
        db.log_ingestion(con, PROVIDER, f"pbp_{season}", n, "ok")
        total += n
        log.info("Season %s: %d team-game rows", season, n)
    return total


DETAIL_PBP_COLUMNS = [
    "game_id", "posteam", "defteam", "play_type", "epa", "success", "yards_gained", "interception",
    "fumble_lost", "qb_kneel", "qb_spike", "two_point_attempt", "qb_dropback", "sack", "qb_hit", "cpoe",
    "down", "yardline_100", "drive", "fixed_drive_result", "wp", "passer_player_id", "passer_player_name",
    "qb_scramble", "third_down_converted", "third_down_failed", "rusher_player_id",
]


def aggregate_pbp_detail(pbp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Unit-level offensive aggregates per team-game and per-QB aggregates.

    Definitions (offence; defensive versions are the opponent's offence):
      dropbacks: qb_dropback == 1 (passes, sacks, scrambles); dropback EPA includes sacks.
      rush plays: designed runs (play_type run, not a QB scramble).
      early downs: 1st and 2nd down pass/run plays; early_pass counts dropbacks among them.
      third downs: attempts = converted + failed; red-zone drives: drives with a snap inside the 20,
      TD drives: those with fixed_drive_result == 'Touchdown'.
      neutral plays: win probability between 0.10 and 0.90 (removes garbage time).
    """
    p = pbp.copy()
    p = p[p["posteam"].notna() & p["epa"].notna()]
    for col in ("qb_kneel", "qb_spike", "two_point_attempt"):
        if col in p:
            p = p[p[col].fillna(0) == 0]
    p = p[p["play_type"].isin(["pass", "run"])].copy()
    p["posteam"] = p["posteam"].map(normalize_team)
    db_ = p["qb_dropback"].fillna(0) == 1
    scr = p["qb_scramble"].fillna(0) == 1
    rush = (p["play_type"] == "run") & ~scr & ~db_
    early = p["down"].isin([1, 2])
    neutral = p["wp"].between(0.10, 0.90)
    p["_db"] = db_.astype(int)
    p["_db_epa"] = np.where(db_, p["epa"], 0.0)
    p["_sack"] = p["sack"].fillna(0).astype(int)
    p["_hit"] = (p["qb_hit"].fillna(0).astype(int) | p["_sack"]).clip(0, 1)
    p["_int"] = p["interception"].fillna(0).astype(int)
    p["_cpoe"] = p["cpoe"].fillna(0.0)
    p["_cpoe_n"] = p["cpoe"].notna().astype(int)
    p["_xpass"] = (db_ & (p["yards_gained"] >= 20)).astype(int)
    p["_rush"] = rush.astype(int)
    p["_rush_epa"] = np.where(rush, p["epa"], 0.0)
    p["_rush_succ"] = np.where(rush, p["success"].fillna(0), 0.0)
    p["_early"] = early.astype(int)
    p["_early_epa"] = np.where(early, p["epa"], 0.0)
    p["_early_succ"] = np.where(early, p["success"].fillna(0), 0.0)
    p["_early_pass"] = (early & db_).astype(int)
    p["_3c"] = p["third_down_converted"].fillna(0).astype(int)
    p["_3a"] = p["_3c"] + p["third_down_failed"].fillna(0).astype(int)
    p["_neu"] = neutral.astype(int)
    p["_neu_epa"] = np.where(neutral, p["epa"], 0.0)
    g = p.groupby(["game_id", "posteam"])
    out = g.agg(dropbacks=("_db", "sum"), dropback_epa_sum=("_db_epa", "sum"), sacks=("_sack", "sum"),
                qb_hits=("_hit", "sum"), interceptions=("_int", "sum"), cpoe_sum=("_cpoe", "sum"),
                cpoe_n=("_cpoe_n", "sum"), explosive_passes=("_xpass", "sum"), rush_plays=("_rush", "sum"),
                rush_epa_sum=("_rush_epa", "sum"), rush_success_sum=("_rush_succ", "sum"),
                early_plays=("_early", "sum"), early_epa_sum=("_early_epa", "sum"),
                early_success_sum=("_early_succ", "sum"), early_pass=("_early_pass", "sum"),
                third_att=("_3a", "sum"), third_conv=("_3c", "sum"), neutral_plays=("_neu", "sum"),
                neutral_epa_sum=("_neu_epa", "sum")).reset_index()
    rz = p[p["yardline_100"] <= 20].groupby(["game_id", "posteam", "drive"])["fixed_drive_result"].first().reset_index()
    rz["td"] = (rz["fixed_drive_result"] == "Touchdown").astype(int)
    rz = rz.groupby(["game_id", "posteam"]).agg(rz_drives=("td", "size"), rz_td_drives=("td", "sum")).reset_index()
    out = out.merge(rz, on=["game_id", "posteam"], how="left").rename(columns={"posteam": "team"})
    out[["rz_drives", "rz_td_drives"]] = out[["rz_drives", "rz_td_drives"]].fillna(0).astype(int)
    out["source"] = PROVIDER
    # Per quarterback: dropbacks attributed to the passer (sacks/scrambles included when id present).
    q = p[db_].copy()
    q["qb_id"] = q["passer_player_id"].fillna(q["rusher_player_id"])
    q = q[q["qb_id"].notna()]
    q["_scr"] = (q["qb_scramble"].fillna(0) == 1).astype(int)
    q["_scr_epa"] = np.where(q["_scr"] == 1, q["epa"], 0.0)
    qb = q.groupby(["game_id", "posteam", "qb_id"]).agg(
        qb_name=("passer_player_name", "first"), dropbacks=("_db", "sum"), epa_sum=("epa", "sum"),
        cpoe_sum=("_cpoe", "sum"), cpoe_n=("_cpoe_n", "sum"), sacks=("_sack", "sum"),
        interceptions=("_int", "sum"), scrambles=("_scr", "sum"), scramble_epa_sum=("_scr_epa", "sum"),
    ).reset_index().rename(columns={"posteam": "team"})
    qb["source"] = PROVIDER
    return out, qb


# ---------------------------------------------------------------------- injuries
def ingest_injuries(con, season: int) -> int:
    """Load nflverse weekly injury reports for a season (QB rows are used for status)."""
    try:
        raw = pd.read_csv(io.BytesIO(_download(INJURY_URL.format(season=season))), low_memory=False)
    except (FileNotFoundError, requests.RequestException) as exc:
        log.warning("Injury data unavailable for %s: %s", season, exc)
        db.log_ingestion(con, PROVIDER, f"injuries_{season}", 0, "missing", str(exc))
        return 0
    df = pd.DataFrame({
        "season": raw["season"], "week": raw["week"], "team": raw["team"].map(normalize_team),
        "player_id": raw.get("gsis_id"), "player_name": raw.get("full_name"),
        "position": raw.get("position"), "report_status": raw.get("report_status"),
        "practice_status": raw.get("practice_status"),
        "date_modified": (pd.to_datetime(raw["date_modified"], errors="coerce", utc=True).dt.tz_localize(None)
                          if "date_modified" in raw else pd.Series(pd.NaT, index=raw.index)),
        "source": PROVIDER,
    })
    con.execute("DELETE FROM injuries WHERE season = ? AND source = ?", [season, PROVIDER])
    con.register("_inj", df)
    con.execute("INSERT INTO injuries SELECT * FROM _inj")
    con.unregister("_inj")
    db.log_ingestion(con, PROVIDER, f"injuries_{season}", len(df), "ok")
    return len(df)
