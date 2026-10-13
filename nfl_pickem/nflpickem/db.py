"""DuckDB storage: schema, connections, idempotent upserts and validation."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DDL = [
    """CREATE TABLE IF NOT EXISTS meta (key VARCHAR PRIMARY KEY, value VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS games (
        game_id VARCHAR PRIMARY KEY,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        game_type VARCHAR NOT NULL,          -- REG, WC, DIV, CON, SB
        game_date DATE,
        kickoff_utc TIMESTAMP,
        home_team VARCHAR NOT NULL,
        away_team VARCHAR NOT NULL,
        home_score INTEGER,
        away_score INTEGER,
        game_status VARCHAR NOT NULL,        -- scheduled, final, canceled, postponed
        location VARCHAR,                    -- Home or Neutral
        div_game INTEGER,
        roof VARCHAR,
        temp DOUBLE,
        wind DOUBLE,
        home_qb_id VARCHAR, away_qb_id VARCHAR,
        home_qb_name VARCHAR, away_qb_name VARCHAR,
        data_source VARCHAR NOT NULL,        -- nflverse, synthetic, manual
        updated_at TIMESTAMP NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS odds_snapshots (
        game_id VARCHAR NOT NULL,
        captured_at TIMESTAMP,               -- when we observed it; NULL = unknown (closing line)
        provider VARCHAR NOT NULL,
        home_moneyline DOUBLE,
        away_moneyline DOUBLE,
        home_spread DOUBLE,                  -- sportsbook convention: negative = home favoured
        source_timestamp TIMESTAMP,          -- provider's last-update time when supplied
        is_closing BOOLEAN DEFAULT FALSE,
        snapshot_key VARCHAR PRIMARY KEY     -- game_id|provider|captured_at for idempotency
    )""",
    """CREATE TABLE IF NOT EXISTS team_game_stats (
        game_id VARCHAR NOT NULL,
        team VARCHAR NOT NULL,
        plays INTEGER, off_epa_sum DOUBLE, off_success_sum DOUBLE,
        pass_plays INTEGER, pass_epa_sum DOUBLE,
        explosive_plays INTEGER, turnovers INTEGER,
        def_plays INTEGER, def_epa_sum DOUBLE, def_success_sum DOUBLE,
        def_explosive_plays INTEGER, takeaways INTEGER,
        source VARCHAR,
        PRIMARY KEY (game_id, team)
    )""",
    """CREATE TABLE IF NOT EXISTS team_game_detail (
        game_id VARCHAR NOT NULL,
        team VARCHAR NOT NULL,
        dropbacks INTEGER, dropback_epa_sum DOUBLE, sacks INTEGER, qb_hits INTEGER,
        interceptions INTEGER, cpoe_sum DOUBLE, cpoe_n INTEGER, explosive_passes INTEGER,
        rush_plays INTEGER, rush_epa_sum DOUBLE, rush_success_sum DOUBLE,
        early_plays INTEGER, early_epa_sum DOUBLE, early_success_sum DOUBLE, early_pass INTEGER,
        third_att INTEGER, third_conv INTEGER,
        rz_drives INTEGER, rz_td_drives INTEGER,
        neutral_plays INTEGER, neutral_epa_sum DOUBLE,
        source VARCHAR,
        PRIMARY KEY (game_id, team)
    )""",
    """CREATE TABLE IF NOT EXISTS qb_game_stats (
        game_id VARCHAR NOT NULL,
        team VARCHAR NOT NULL,
        qb_id VARCHAR NOT NULL,
        qb_name VARCHAR,
        dropbacks INTEGER, epa_sum DOUBLE, cpoe_sum DOUBLE, cpoe_n INTEGER,
        sacks INTEGER, interceptions INTEGER, scrambles INTEGER, scramble_epa_sum DOUBLE,
        source VARCHAR,
        PRIMARY KEY (game_id, team, qb_id)
    )""",
    """CREATE TABLE IF NOT EXISTS injuries (
        season INTEGER, week INTEGER, team VARCHAR, player_id VARCHAR,
        player_name VARCHAR, position VARCHAR, report_status VARCHAR,
        practice_status VARCHAR, date_modified TIMESTAMP, source VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS prediction_runs (
        run_id VARCHAR PRIMARY KEY,
        generated_at TIMESTAMP NOT NULL,
        data_cutoff TIMESTAMP NOT NULL,
        season INTEGER, week INTEGER,
        model_version VARCHAR NOT NULL,
        config_json VARCHAR,
        frozen BOOLEAN NOT NULL DEFAULT FALSE,
        frozen_at TIMESTAMP,
        data_source VARCHAR,
        notes VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS predictions (
        run_id VARCHAR NOT NULL,
        game_id VARCHAR NOT NULL,
        generated_at TIMESTAMP NOT NULL,
        model_version VARCHAR NOT NULL,
        season INTEGER, week INTEGER,
        home_team VARCHAR, away_team VARCHAR, kickoff_utc TIMESTAMP,
        market_home_probability DOUBLE,
        elo_home_probability DOUBLE,
        logistic_home_probability DOUBLE,
        gradient_boosting_home_probability DOUBLE,
        blended_home_probability DOUBLE,
        selected_team VARCHAR,
        selected_team_probability DOUBLE,
        confidence_points INTEGER,
        expected_points DOUBLE,
        odds_captured_at TIMESTAMP,
        odds_status VARCHAR,                 -- current, stale, closing_proxy, missing
        injury_status VARCHAR,
        data_flags VARCHAR,
        PRIMARY KEY (run_id, game_id)
    )""",
    """CREATE TABLE IF NOT EXISTS pool_results (
        pool_id VARCHAR NOT NULL,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        game_id VARCHAR NOT NULL,
        run_id VARCHAR,
        selected_team VARCHAR,
        confidence_points INTEGER,
        actual_result VARCHAR,               -- win, loss, tie, void, pending
        points_earned DOUBLE,
        graded_at TIMESTAMP,
        PRIMARY KEY (pool_id, season, week, game_id)
    )""",
    """CREATE TABLE IF NOT EXISTS pool_scores (
        pool_id VARCHAR NOT NULL,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        participant VARCHAR NOT NULL,
        points DOUBLE,
        is_me BOOLEAN DEFAULT FALSE,
        PRIMARY KEY (pool_id, season, week, participant)
    )""",
    """CREATE TABLE IF NOT EXISTS backtest_runs (
        backtest_id VARCHAR PRIMARY KEY,
        created_at TIMESTAMP,
        seasons VARCHAR,
        includes_holdout BOOLEAN,
        config_json VARCHAR,
        data_source VARCHAR,
        summary_json VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS backtest_predictions (
        backtest_id VARCHAR NOT NULL,
        game_id VARCHAR NOT NULL,
        season INTEGER, week INTEGER, game_type VARCHAR,
        kickoff_utc TIMESTAMP, prediction_cutoff TIMESTAMP,
        home_team VARCHAR, away_team VARCHAR,
        market DOUBLE, elo DOUBLE, logistic DOUBLE, gbm DOUBLE, ml_only DOUBLE, blend DOUBLE,
        logistic_raw DOUBLE, gbm_raw DOUBLE, odds_status VARCHAR,
        blend_weights VARCHAR,
        predicted_at TIMESTAMP,
        PRIMARY KEY (backtest_id, game_id)
    )""",
    """CREATE TABLE IF NOT EXISTS ingestion_log (
        logged_at TIMESTAMP, source VARCHAR, item VARCHAR, rows INTEGER, status VARCHAR, message VARCHAR
    )""",
]

GAME_COLUMNS = [
    "game_id", "season", "week", "game_type", "game_date", "kickoff_utc", "home_team",
    "away_team", "home_score", "away_score", "game_status", "location", "div_game", "roof",
    "temp", "wind", "home_qb_id", "away_qb_id", "home_qb_name", "away_qb_name",
    "data_source", "updated_at",
]
ODDS_COLUMNS = [
    "game_id", "captured_at", "provider", "home_moneyline", "away_moneyline", "home_spread",
    "source_timestamp", "is_closing", "snapshot_key",
]
STATS_COLUMNS = [
    "game_id", "team", "plays", "off_epa_sum", "off_success_sum", "pass_plays", "pass_epa_sum",
    "explosive_plays", "turnovers", "def_plays", "def_epa_sum", "def_success_sum",
    "def_explosive_plays", "takeaways", "source",
]


DETAIL_COLUMNS = [
    "game_id", "team", "dropbacks", "dropback_epa_sum", "sacks", "qb_hits", "interceptions", "cpoe_sum",
    "cpoe_n", "explosive_passes", "rush_plays", "rush_epa_sum", "rush_success_sum", "early_plays",
    "early_epa_sum", "early_success_sum", "early_pass", "third_att", "third_conv", "rz_drives",
    "rz_td_drives", "neutral_plays", "neutral_epa_sum", "source",
]
QB_COLUMNS = [
    "game_id", "team", "qb_id", "qb_name", "dropbacks", "epa_sum", "cpoe_sum", "cpoe_n", "sacks",
    "interceptions", "scrambles", "scramble_epa_sum", "source",
]


def connect(path: str | Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        init_db(con)
    return con


MIGRATIONS = [
    "ALTER TABLE backtest_predictions ADD COLUMN IF NOT EXISTS residual DOUBLE",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS residual_home_probability DOUBLE",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pool_line_team VARCHAR",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pool_line DOUBLE",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS line_source VARCHAR",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS credited_home_probability DOUBLE",
    "ALTER TABLE backtest_predictions ADD COLUMN IF NOT EXISTS market_home_spread DOUBLE",
    """CREATE TABLE IF NOT EXISTS pool_lines (
        season INTEGER NOT NULL, week INTEGER NOT NULL, game_id VARCHAR NOT NULL,
        favourite_team VARCHAR NOT NULL, line DOUBLE NOT NULL, entered_at TIMESTAMP,
        PRIMARY KEY (season, week, game_id))""",
]


def init_db(con: duckdb.DuckDBPyConnection) -> None:
    for stmt in DDL:
        con.execute(stmt)
    for stmt in MIGRATIONS:
        con.execute(stmt)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", [str(SCHEMA_VERSION)])


def get_meta(con, key: str, default: str | None = None) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key = ?", [key]).fetchone()
    return row[0] if row else default


def set_meta(con, key: str, value: str) -> None:
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", [key, value])


def upsert(con, table: str, df: pd.DataFrame, columns: list[str]) -> int:
    """Insert or replace rows by primary key. Duplicates inside df keep the last row."""
    if df.empty:
        return 0
    df = df[columns].copy()
    con.register("_upsert_df", df)
    try:
        con.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) "
                    f"SELECT {', '.join(columns)} FROM _upsert_df")
    finally:
        con.unregister("_upsert_df")
    return len(df)


def dedupe_games(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates(subset=["game_id"], keep="last").reset_index(drop=True)


def upsert_games(con, df: pd.DataFrame) -> int:
    df = dedupe_games(df)
    errors = validate_games(df)
    if errors:
        raise ValueError("Invalid games data: " + "; ".join(errors[:10]))
    return upsert(con, "games", df, GAME_COLUMNS)


def upsert_odds(con, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["captured_at"] = pd.to_datetime(df["captured_at"])
    cap = df["captured_at"].dt.strftime("%Y-%m-%dT%H:%M:%S").fillna("closing")
    df["snapshot_key"] = df["game_id"].astype(str) + "|" + df["provider"].astype(str) + "|" + cap
    df = df.drop_duplicates("snapshot_key", keep="last")
    return upsert(con, "odds_snapshots", df, ODDS_COLUMNS)


def upsert_team_stats(con, df: pd.DataFrame) -> int:
    df = df.drop_duplicates(["game_id", "team"], keep="last")
    return upsert(con, "team_game_stats", df, STATS_COLUMNS)


def log_ingestion(con, source: str, item: str, rows: int, status: str, message: str = "") -> None:
    con.execute("INSERT INTO ingestion_log VALUES (now(), ?, ?, ?, ?, ?)",
                [source, item, rows, status, message])


def load_games(con, seasons: list[int] | None = None) -> pd.DataFrame:
    q = "SELECT * FROM games"
    if seasons:
        q += f" WHERE season IN ({', '.join(str(int(s)) for s in seasons)})"
    return con.execute(q + " ORDER BY kickoff_utc, game_id").df()


def validate_games(df: pd.DataFrame) -> list[str]:
    """Return a list of human-readable problems with a games frame."""
    errors: list[str] = []
    missing = [c for c in GAME_COLUMNS if c not in df.columns]
    if missing:
        return [f"missing columns {missing}"]
    if df["game_id"].isna().any():
        errors.append("null game_id")
    if df["game_id"].duplicated().any():
        errors.append("duplicate game_id values")
    same = df[df["home_team"] == df["away_team"]]
    if len(same):
        errors.append(f"home==away in {list(same.game_id[:3])}")
    final = df[df["game_status"] == "final"]
    if final[["home_score", "away_score"]].isna().any().any():
        errors.append("final games missing scores")
    bad_status = set(df["game_status"]) - {"scheduled", "final", "canceled", "postponed"}
    if bad_status:
        errors.append(f"unknown game_status {bad_status}")
    if (df.get("week", pd.Series(dtype=int)) < 1).any():
        errors.append("week < 1")
    return errors


def validate_database(con) -> dict[str, object]:
    """Integrity report used by the CLI `status` command and the dashboard."""
    report: dict[str, object] = {}
    report["games"] = con.execute("SELECT count(*) FROM games").fetchone()[0]
    report["final_games"] = con.execute("SELECT count(*) FROM games WHERE game_status='final'").fetchone()[0]
    report["seasons"] = [r[0] for r in con.execute("SELECT DISTINCT season FROM games ORDER BY 1").fetchall()]
    report["odds_snapshots"] = con.execute("SELECT count(*) FROM odds_snapshots").fetchone()[0]
    report["team_game_stats"] = con.execute("SELECT count(*) FROM team_game_stats").fetchone()[0]
    report["orphan_odds"] = con.execute(
        "SELECT count(*) FROM odds_snapshots o LEFT JOIN games g USING (game_id) WHERE g.game_id IS NULL"
    ).fetchone()[0]
    report["final_without_scores"] = con.execute(
        "SELECT count(*) FROM games WHERE game_status='final' AND (home_score IS NULL OR away_score IS NULL)"
    ).fetchone()[0]
    report["final_without_stats"] = con.execute(
        """SELECT count(*) FROM games g WHERE game_status='final' AND NOT EXISTS
           (SELECT 1 FROM team_game_stats s WHERE s.game_id = g.game_id)"""
    ).fetchone()[0]
    report["data_sources"] = [r[0] for r in con.execute("SELECT DISTINCT data_source FROM games").fetchall()]
    report["prediction_runs"] = con.execute("SELECT count(*) FROM prediction_runs").fetchone()[0]
    report["frozen_runs"] = con.execute("SELECT count(*) FROM prediction_runs WHERE frozen").fetchone()[0]
    return report
