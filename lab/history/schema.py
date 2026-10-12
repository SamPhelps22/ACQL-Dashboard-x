"""The dataset's tables.

Times are seconds since 1970, UTC, like the app's own store. A NULL time
means the source does not say - it is never filled in with a guess.

Every margin is from the HOME team's side: +6.5 is the home team by 6.5.
"""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE sources (
    source_id           TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,
    description         TEXT NOT NULL,
    location            TEXT NOT NULL,     -- URL or repo-relative path
    sha256              TEXT,
    bytes               INTEGER,
    retrieved_at        REAL,              -- when this copy was obtained, if known
    retrieved_at_basis  TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT ''
);

-- Game identity. Regular-season games only: the pool plays nothing else.
CREATE TABLE games (
    game_id         TEXT PRIMARY KEY,      -- nflverse game_id, e.g. 2024_01_BAL_KC
    season          INTEGER NOT NULL,
    week            INTEGER NOT NULL,
    gameday         TEXT,
    gametime_et     TEXT,
    away_team       TEXT NOT NULL,         -- as the schedule writes it
    home_team       TEXT NOT NULL,
    away_code       TEXT NOT NULL,         -- the app's team codes (acql.predictions)
    home_code       TEXT NOT NULL,
    neutral         INTEGER NOT NULL,
    kickoff_utc     REAL,
    kickoff_basis   TEXT NOT NULL,
    source_id       TEXT NOT NULL REFERENCES sources(source_id)
);

-- What actually happened. No prediction record is built from this table.
CREATE TABLE outcomes (
    game_id         TEXT PRIMARY KEY REFERENCES games(game_id),
    away_score      INTEGER NOT NULL,
    home_score      INTEGER NOT NULL,
    home_margin     INTEGER NOT NULL,
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    crosscheck      TEXT NOT NULL          -- agree / disagree / absent, against the repo's scores file
);

-- Every line seen, with when it became available to us.
--   as_of         when the number was the market's, if the source says
--   available_at  the latest moment it is certain we had it; NULL = unknown
CREATE TABLE odds_snapshots (
    snapshot_id         TEXT PRIMARY KEY,
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    market              TEXT NOT NULL CHECK (market IN ('spread', 'total', 'moneyline')),
    home_value          REAL,              -- spread: home margin; total: points; moneyline: home price
    away_value          REAL,              -- moneyline: away price
    timing              TEXT NOT NULL,     -- snapshot / file_market / file_opening / typed / unspecified / archive_*
    as_of               REAL,
    available_at        REAL,
    available_at_basis  TEXT NOT NULL,
    orientation         TEXT NOT NULL,     -- as_source / flipped (source had home and away the other way)
    source_id           TEXT NOT NULL REFERENCES sources(source_id),
    raw                 TEXT NOT NULL
);
CREATE INDEX odds_by_game ON odds_snapshots(game_id, market, available_at);

-- One row per computer model per game per source file.
CREATE TABLE model_forecasts (
    forecast_id         TEXT PRIMARY KEY,
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    model               TEXT NOT NULL,     -- the file's column name, e.g. linesag
    home_margin         REAL NOT NULL,
    published_at        REAL,
    published_at_basis  TEXT NOT NULL,
    retrieved_at        REAL,
    retrieved_at_basis  TEXT NOT NULL,
    available_at        REAL,
    orientation         TEXT NOT NULL,
    source_id           TEXT NOT NULL REFERENCES sources(source_id)
);
CREATE INDEX forecasts_by_game ON model_forecasts(game_id, available_at);

-- A pool sheet says which games of its week carried a line; a game on a
-- sheet with no line was straight up.
CREATE TABLE pool_sheets (
    sheet_id        TEXT PRIMARY KEY,
    season          INTEGER NOT NULL,
    week            INTEGER NOT NULL,
    games_on_sheet  INTEGER NOT NULL,
    games_matched   INTEGER NOT NULL,
    season_match    TEXT NOT NULL,         -- unique / partial
    imported_at     REAL,
    source_id       TEXT NOT NULL REFERENCES sources(source_id)
);

-- Every game on every sheet, lined or not. favourite/points/home_line are
-- NULL for a straight-up game; problem says why a note could not be read.
CREATE TABLE pool_lines (
    pool_line_id    TEXT PRIMARY KEY,
    game_id         TEXT NOT NULL REFERENCES games(game_id),
    sheet_id        TEXT NOT NULL REFERENCES pool_sheets(sheet_id),
    raw_note        TEXT NOT NULL,
    favourite_code  TEXT,
    points          REAL,
    home_line       REAL,                  -- +points when the home team is the pool's favourite
    problem         TEXT NOT NULL DEFAULT '',
    posted_at       REAL,
    posted_at_basis TEXT NOT NULL
);

CREATE TABLE pool_rules (
    rule_id             TEXT PRIMARY KEY,
    applies_to          TEXT NOT NULL,
    description         TEXT NOT NULL,
    status              TEXT NOT NULL,     -- verified / unknown
    evidence            TEXT NOT NULL,
    verified_from_season INTEGER,
    verified_from_week   INTEGER
);

-- The share of the models' opinion production priced each week with.
CREATE TABLE production_weights (
    season      INTEGER NOT NULL,
    week        INTEGER NOT NULL,
    weight      REAL NOT NULL,
    fit         TEXT NOT NULL,          -- JSON, as production noted it
    source_id   TEXT NOT NULL REFERENCES sources(source_id),
    basis       TEXT NOT NULL,
    PRIMARY KEY (season, week)
);

-- One record per game per cutoff: only what was available at the cutoff.
-- Deliberately no score, result or margin column.
CREATE TABLE prediction_records (
    record_id               TEXT PRIMARY KEY,   -- game_id|cutoff_kind
    game_id                 TEXT NOT NULL REFERENCES games(game_id),
    season                  INTEGER NOT NULL,
    week                    INTEGER NOT NULL,
    away_code               TEXT NOT NULL,
    home_code               TEXT NOT NULL,
    neutral                 INTEGER NOT NULL,
    cutoff_kind             TEXT NOT NULL,
    cutoff_at               REAL,
    cutoff_basis            TEXT NOT NULL,
    spread_home             REAL,
    spread_snapshot_id      TEXT,
    spread_open_home        REAL,
    spread_open_snapshot_id TEXT,
    total                   REAL,
    total_snapshot_id       TEXT,
    moneyline_home          REAL,
    moneyline_away          REAL,
    moneyline_snapshot_id   TEXT,
    spread_home_unverified      REAL,
    spread_unverified_id        TEXT,
    total_unverified            REAL,
    total_unverified_id         TEXT,
    moneyline_home_unverified   REAL,
    moneyline_away_unverified   REAL,
    moneyline_unverified_id     TEXT,
    n_models                INTEGER NOT NULL,
    forecast_source_id      TEXT,
    forecast_ids            TEXT NOT NULL,      -- JSON list
    pool_line_status        TEXT NOT NULL,      -- lined / straight_up / conflict / unreadable / unknown
    pool_line_home          REAL,
    pool_line_id            TEXT,
    rule_id                 TEXT,
    rules_verified          INTEGER NOT NULL,
    flags                   TEXT NOT NULL,      -- JSON list, sorted
    inputs_hash             TEXT NOT NULL,
    UNIQUE (game_id, cutoff_kind)
);
"""


def create(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
