"""The forecast log: outside forecasts beside Deadeye's, scored on the same games.

The rest of the Model Lab replays every recipe it can compute itself. This is
for the forecasts it cannot - another site's numbers, a friend's spreadsheet,
a model run somewhere else - and for keeping every forecast, ours included,
with the time it was made, so a score never rests on a number that could
have been written after the game.

It began as the "acql_model_lab_starter" module and keeps its rules:

  * forecasts are only ever added, never changed (`add_prediction`);
  * every one carries when it was published and when it was taken, both with
    a timezone, and is eligible to be scored only if both are before the
    week's common cutoff before its own kickoff (`determine_eligibility`) -
    a missing publication time is flagged, never assumed;
  * a model with two eligible forecasts for one game has that game left out
    of its score and counted, not one of them quietly chosen.

Changes from the starter, to fit the app: the tables live in acql.db (so the
daily backup keeps them) under a `lab_` prefix; a CSV's own eligibility
column is kept as a claim but the status is worked out again from the game's
kickoff; a CSV may name models not yet registered; a tied game is left out
of the win-chance scores rather than counted as a home loss; and
`bring_in` copies across what the app already holds with a provable time -
the ledger (model/ledger.py) and fetched betting lines (feeds/odds.py).
Nothing is reconstructed: a ledger week written after its games is brought
in marked "postgame" and never scored.

Nothing here changes how Deadeye prices a game. No Qt here.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

#: Minutes before its own kickoff a forecast must have been published and taken by.
CUTOFF_MINUTES = 60
STATUSES = ("unreviewed", "eligible", "late", "postgame", "invalid", "missing_timestamp")

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_models (
    model_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model_version TEXT NOT NULL DEFAULT '',
    model_type TEXT NOT NULL DEFAULT 'independent',
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_games (
    game_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    kickoff_utc TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_score INTEGER,
    home_score INTEGER,
    status TEXT NOT NULL DEFAULT 'scheduled',
    result_updated_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS lab_predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL REFERENCES lab_games(game_id),
    model_id TEXT NOT NULL REFERENCES lab_models(model_id),
    model_version TEXT NOT NULL DEFAULT '',
    home_win_probability REAL,
    predicted_winner TEXT,
    projected_home_score REAL,
    projected_away_score REAL,
    source_name TEXT NOT NULL DEFAULT '',
    source_published_at_utc TEXT,
    retrieved_at_utc TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    source_reference TEXT NOT NULL DEFAULT '',
    eligibility_status TEXT NOT NULL DEFAULT 'unreviewed',
    data_quality_note TEXT NOT NULL DEFAULT '',
    snapshot_key TEXT,
    raw_payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS lab_idx_predictions_game_model
ON lab_predictions(game_id, model_id);

CREATE INDEX IF NOT EXISTS lab_idx_predictions_snapshot
ON lab_predictions(snapshot_key, game_id, model_id);

CREATE TABLE IF NOT EXISTS lab_snapshots (
    snapshot_key TEXT PRIMARY KEY,
    season INTEGER NOT NULL,
    cutoff_minutes_before_kickoff INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS lab_import_log (
    import_id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    imported_at_utc TEXT NOT NULL,
    rows_seen INTEGER NOT NULL,
    rows_imported INTEGER NOT NULL,
    rows_rejected INTEGER NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
"""


# ---- times ---------------------------------------------------------------------------------------
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_utc(value: str) -> datetime:
    """Parse an ISO timestamp and require an explicit timezone."""
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must include timezone: {value!r}")
    return dt.astimezone(timezone.utc)


def iso(seconds: float) -> str:
    """Seconds since 1970 as an ISO UTC timestamp."""
    return datetime.fromtimestamp(float(seconds), timezone.utc).isoformat(timespec="seconds")


# ---- the database ----------------------------------------------------------------------------------
def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """The log's tables, in acql.db (or `db_path`), made if they are not there yet."""
    if db_path is None:
        from .. import store
        db_path = store.db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def register_model(
    conn: sqlite3.Connection,
    model_id: str,
    display_name: str,
    provider: str = "",
    model_version: str = "",
    model_type: str = "independent",
    notes: str = "",
) -> None:
    if not model_id.strip() or not display_name.strip():
        raise ValueError("model_id and display_name are required")
    conn.execute(
        """INSERT INTO lab_models
        (model_id, display_name, provider, model_version, model_type, active, notes, created_at_utc)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(model_id) DO UPDATE SET
        display_name=excluded.display_name, provider=excluded.provider,
        model_version=excluded.model_version, model_type=excluded.model_type,
        notes=excluded.notes""",
        (model_id, display_name, provider, model_version, model_type, notes, utc_now()),
    )
    conn.commit()


def upsert_game(
    conn: sqlite3.Connection,
    game_id: str,
    season: int,
    week: int,
    kickoff_utc: str,
    away_team: str,
    home_team: str,
    away_score: Optional[int] = None,
    home_score: Optional[int] = None,
    status: str = "scheduled",
    commit: bool = True,
) -> None:
    parse_utc(kickoff_utc)
    if not game_id or not away_team or not home_team or away_team == home_team:
        raise ValueError("Valid game_id and distinct home/away teams are required")
    conn.execute(
        """INSERT INTO lab_games
        (game_id, season, week, kickoff_utc, away_team, home_team, away_score,
         home_score, status, result_updated_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id) DO UPDATE SET
        season=excluded.season, week=excluded.week, kickoff_utc=excluded.kickoff_utc,
        away_team=excluded.away_team, home_team=excluded.home_team,
        away_score=COALESCE(excluded.away_score, lab_games.away_score),
        home_score=COALESCE(excluded.home_score, lab_games.home_score),
        status=excluded.status,
        result_updated_at_utc=CASE WHEN excluded.home_score IS NOT NULL
          AND excluded.away_score IS NOT NULL THEN excluded.result_updated_at_utc
          ELSE lab_games.result_updated_at_utc END""",
        (game_id, season, week, kickoff_utc, away_team, home_team, away_score,
         home_score, status, utc_now() if home_score is not None and away_score is not None else None),
    )
    if commit:
        conn.commit()


def game_id_for(season: int, week: int, away: str, home: str) -> str:
    """The log's name for a game: "2026-W07-SEA@DEN"."""
    return f"{int(season)}-W{int(week):02d}-{away.upper()}@{home.upper()}"


def snapshot_for(season: int, week: int, cutoff: int = CUTOFF_MINUTES) -> str:
    """The common snapshot a week's forecasts are compared in: "2026-W07-T60"."""
    return f"{int(season)}-W{int(week):02d}-T{int(cutoff)}"


def add_prediction(
    conn: sqlite3.Connection,
    *,
    game_id: str,
    model_id: str,
    home_win_probability: Optional[float],
    predicted_winner: Optional[str],
    retrieved_at_utc: str,
    source_published_at_utc: Optional[str] = None,
    model_version: str = "",
    projected_home_score: Optional[float] = None,
    projected_away_score: Optional[float] = None,
    source_name: str = "",
    source_reference: str = "",
    eligibility_status: str = "unreviewed",
    data_quality_note: str = "",
    snapshot_key: Optional[str] = None,
    raw_payload: Optional[dict] = None,
    commit: bool = True,
) -> int:
    """Append-only prediction write. It never updates an existing prediction."""
    parse_utc(retrieved_at_utc)
    if source_published_at_utc:
        parse_utc(source_published_at_utc)
    if home_win_probability is not None:
        if not math.isfinite(home_win_probability) or not 0 <= home_win_probability <= 1:
            raise ValueError("home_win_probability must be between 0 and 1")
    if eligibility_status not in STATUSES:
        raise ValueError("Unknown eligibility_status")
    cur = conn.execute(
        """INSERT INTO lab_predictions
        (game_id, model_id, model_version, home_win_probability, predicted_winner,
         projected_home_score, projected_away_score, source_name, source_published_at_utc,
         retrieved_at_utc, recorded_at_utc, source_reference, eligibility_status,
         data_quality_note, snapshot_key, raw_payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (game_id, model_id, model_version, home_win_probability, predicted_winner,
         projected_home_score, projected_away_score, source_name, source_published_at_utc,
         retrieved_at_utc, utc_now(), source_reference, eligibility_status,
         data_quality_note, snapshot_key, json.dumps(raw_payload or {}, sort_keys=True)),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def already_logged(conn: sqlite3.Connection, model_id: str, game_id: str, source_reference: str) -> bool:
    """Whether this exact source record is already in the log (so bringing it in twice adds nothing)."""
    return conn.execute(
        "SELECT 1 FROM lab_predictions WHERE model_id = ? AND game_id = ? AND source_reference = ? LIMIT 1",
        (model_id, game_id, source_reference)).fetchone() is not None


# ---- odds and scores ------------------------------------------------------------------------------
def american_odds_to_implied(odds: int | float) -> float:
    odds = float(odds)
    if odds == 0:
        raise ValueError("American odds cannot be zero")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


def no_vig_two_way(home_odds: int | float, away_odds: int | float) -> tuple[float, float]:
    """Proportional no-vig normalization for a two-outcome market."""
    h = american_odds_to_implied(home_odds)
    a = american_odds_to_implied(away_odds)
    total = h + a
    return h / total, a / total


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> Optional[float]:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have equal lengths")
    if not probabilities:
        return None
    for p in probabilities:
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("probabilities must be finite and in [0, 1]")
    if any(y not in (0, 1) for y in outcomes):
        raise ValueError("outcomes must be binary 0/1")
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(outcomes)


def log_loss(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    epsilon: float = 1e-15,
) -> Optional[float]:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have equal lengths")
    if not probabilities:
        return None
    if not 0 < epsilon < 0.5:
        raise ValueError("epsilon must be between 0 and 0.5")
    terms = []
    for p, y in zip(probabilities, outcomes):
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("probabilities must be finite and in [0, 1]")
        if y not in (0, 1):
            raise ValueError("outcomes must be binary 0/1")
        p = min(max(p, epsilon), 1 - epsilon)
        terms.append(-(y * math.log(p) + (1 - y) * math.log(1 - p)))
    return sum(terms) / len(terms)


def _scored_rows(conn, season, week, snapshot_key, eligible_only):
    where = ["g.home_score IS NOT NULL", "g.away_score IS NOT NULL",
             "g.home_score != g.away_score",          # a tie is neither side's win: left out
             "p.home_win_probability IS NOT NULL"]
    params: list = []
    if season is not None:
        where.append("g.season = ?"); params.append(season)
    if week is not None:
        where.append("g.week = ?"); params.append(week)
    if snapshot_key is not None:
        where.append("p.snapshot_key = ?"); params.append(snapshot_key)
    if eligible_only:
        where.append("p.eligibility_status = 'eligible'")
    sql = f"""
        SELECT p.model_id, m.display_name, g.game_id, g.season, g.week,
               g.home_team, g.away_team, g.home_score, g.away_score,
               p.home_win_probability, p.predicted_winner,
               p.projected_home_score, p.projected_away_score
        FROM lab_predictions p
        JOIN lab_games g ON g.game_id = p.game_id
        JOIN lab_models m ON m.model_id = p.model_id
        WHERE {' AND '.join(where)}
        ORDER BY p.model_id, g.kickoff_utc
    """
    rows = conn.execute(sql, params).fetchall()
    # If a model has multiple eligible records for one game, do not silently
    # choose one. Exclude that model/game from the score and flag it.
    counts: dict = {}
    for r in rows:
        key = (r["model_id"], r["game_id"])
        counts[key] = counts.get(key, 0) + 1
    grouped: dict[str, list] = {}
    duplicates: dict[str, int] = {}
    for r in rows:
        mid = r["model_id"]
        if counts[(mid, r["game_id"])] != 1:
            duplicates[mid] = duplicates.get(mid, 0) + 1
            continue
        grouped.setdefault(mid, []).append(r)
    return grouped, duplicates


def evaluate_models(
    conn: sqlite3.Connection,
    season: Optional[int] = None,
    week: Optional[int] = None,
    snapshot_key: Optional[str] = None,
    eligible_only: bool = True,
    common_only: bool = False,
) -> list[dict]:
    """
    Score only completed games and eligible predictions. Returns per-model
    metrics and sample counts. `common_only` keeps only the games every
    scored model priced, for a like-for-like comparison.
    """
    grouped, duplicate_counts = _scored_rows(conn, season, week, snapshot_key, eligible_only)
    if common_only and grouped:
        shared = set.intersection(*({r["game_id"] for r in items} for items in grouped.values()))
        grouped = {mid: [r for r in items if r["game_id"] in shared] for mid, items in grouped.items()}
        grouped = {mid: items for mid, items in grouped.items() if items}

    results = []
    for mid, items in grouped.items():
        probs, outcomes = [], []
        correct = 0
        margin_errors, total_errors = [], []
        for r in items:
            y = int(r["home_score"] > r["away_score"])
            probs.append(float(r["home_win_probability"]))
            outcomes.append(y)
            actual_winner = r["home_team"] if y else r["away_team"]
            predicted = r["predicted_winner"]
            if predicted:
                correct += int(predicted.casefold() == actual_winner.casefold())
            if r["projected_home_score"] is not None and r["projected_away_score"] is not None:
                predicted_margin = r["projected_home_score"] - r["projected_away_score"]
                actual_margin = r["home_score"] - r["away_score"]
                margin_errors.append(abs(predicted_margin - actual_margin))
                predicted_total = r["projected_home_score"] + r["projected_away_score"]
                actual_total = r["home_score"] + r["away_score"]
                total_errors.append(abs(predicted_total - actual_total))
        scored = sum(1 for r in items if r["predicted_winner"])
        results.append({
            "model_id": mid,
            "model_name": items[0]["display_name"],
            "games": len(items),
            "brier_score": brier_score(probs, outcomes),
            "log_loss": log_loss(probs, outcomes),
            # only over the forecasts that named a winner (the starter divided by every game)
            "winner_accuracy": (correct / scored) if scored else None,
            "winner_predictions_scored": scored,
            "margin_mae": sum(margin_errors) / len(margin_errors) if margin_errors else None,
            "margin_games": len(margin_errors),
            "total_mae": sum(total_errors) / len(total_errors) if total_errors else None,
            "total_games": len(total_errors),
            "duplicate_game_records_excluded": duplicate_counts.get(mid, 0),
        })
    return sorted(results, key=lambda x: (x["brier_score"] is None, x["brier_score"] or float("inf")))


def weekly_brier(conn: sqlite3.Connection, season: int) -> dict[str, dict[int, float]]:
    """Each model's Brier score week by week, on its eligible forecasts: {model name: {week: score}}."""
    out: dict[str, dict[int, float]] = {}
    weeks = [r[0] for r in conn.execute("SELECT DISTINCT week FROM lab_games WHERE season = ? ORDER BY week",
                                         (season,))]
    for week in weeks:
        for row in evaluate_models(conn, season=season, week=week):
            out.setdefault(row["model_name"], {})[week] = row["brier_score"]
    return out


# ---- what the user looks at -------------------------------------------------------------------------
def seasons(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT DISTINCT season FROM lab_games ORDER BY season DESC")]


def weeks(conn: sqlite3.Connection, season: int) -> list[int]:
    return [r[0] for r in conn.execute("SELECT DISTINCT week FROM lab_games WHERE season = ? ORDER BY week",
                                       (season,))]


def models(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM lab_models ORDER BY display_name").fetchall()


def matchups(conn: sqlite3.Connection, season: int, week: int) -> tuple[list[sqlite3.Row], dict]:
    """A week's games, and each model's latest forecast of each: (games, {(game_id, model_id): row})."""
    games = conn.execute("SELECT * FROM lab_games WHERE season = ? AND week = ? ORDER BY kickoff_utc, game_id",
                         (season, week)).fetchall()
    found: dict = {}
    for row in conn.execute(
            """SELECT p.*, m.display_name FROM lab_predictions p
               JOIN lab_games g ON g.game_id = p.game_id JOIN lab_models m ON m.model_id = p.model_id
               WHERE g.season = ? AND g.week = ? ORDER BY p.prediction_id""", (season, week)):
        key = (row["game_id"], row["model_id"])
        before = found.get(key)
        # an eligible forecast is the one shown; among equals, the newest
        if before is None or not (before["eligibility_status"] == "eligible" and row["eligibility_status"] != "eligible"):
            found[key] = row
    return games, found


def history(conn: sqlite3.Connection, model_id: str | None = None, limit: int = 500) -> list[sqlite3.Row]:
    """The log, newest first."""
    sql = """SELECT p.*, m.display_name, g.season, g.week, g.away_team, g.home_team, g.kickoff_utc,
                    g.away_score, g.home_score
             FROM lab_predictions p JOIN lab_models m ON m.model_id = p.model_id
             JOIN lab_games g ON g.game_id = p.game_id"""
    args: list = []
    if model_id:
        sql += " WHERE p.model_id = ?"
        args.append(model_id)
    sql += " ORDER BY p.prediction_id DESC LIMIT ?"
    args.append(int(limit))
    return conn.execute(sql, args).fetchall()


def imports(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM lab_import_log ORDER BY import_id DESC LIMIT ?", (limit,)).fetchall()


# ---- CSV in and out ---------------------------------------------------------------------------------
CSV_REQUIRED = ("game_id", "model_id", "home_win_probability", "retrieved_at_utc")
CSV_OPTIONAL = ("source_published_at_utc", "predicted_winner", "model_name", "model_version",
                "projected_home_score", "projected_away_score", "source_name", "source_reference",
                "eligibility_status", "data_quality_note", "snapshot_key")


def _number(row: dict, name: str) -> Optional[float]:
    text = (row.get(name) or "").strip()
    return float(text) if text else None


#: Columns that make a file nflverse's games.csv (schedule and results), not forecasts.
GAMES_REQUIRED = ("season", "game_type", "week", "gameday", "gametime", "away_team", "home_team",
                  "away_score", "home_score")
#: nflverse's kickoff times are US Eastern, local.
NFLVERSE_ZONE = "America/New_York"
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def csv_kind(csv_path: str | Path) -> str:
    """"games" for an nflverse games.csv, "predictions" for a forecasts file, "" for neither."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        fields = set(csv.DictReader(f).fieldnames or [])
    if set(CSV_REQUIRED) <= fields:
        return "predictions"
    if set(GAMES_REQUIRED) <= fields:
        return "games"
    return ""


def _nflverse_kickoff(day: str, clock: str) -> str:
    """"2026-10-18" and "13:00" (Eastern) as UTC. Raises without both: a time is never made up."""
    from zoneinfo import ZoneInfo
    if not day or not clock:
        raise ValueError("no kickoff time in the file - left out rather than given a made-up one")
    local = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(NFLVERSE_ZONE))
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def import_games_csv(conn: sqlite3.Connection, csv_path: str | Path, seasons: Iterable[int] | None = None) -> dict:
    """
    nflverse's games.csv: each game's season, week, teams, kickoff and - once
    played - final score, into lab_games. No forecasts are made from it: the
    betting columns in the file carry no time they were taken, so they are
    left alone. A game with no kickoff time is turned away, and one not yet
    played goes in without a score. A neutral-site game the log already has
    the other way round (from the scoreboard) is updated in that orientation.
    `seasons` keeps only those seasons.
    """
    from ..feeds.results import _code
    wanted = {int(s) for s in seasons} if seasons is not None else None
    seen = imported = rejected = finals = skipped = 0
    errors = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = set(GAMES_REQUIRED) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Games CSV missing required columns: " + ", ".join(sorted(missing)))
        for line_no, row in enumerate(reader, start=2):
            try:
                season, week = int(row["season"]), int(row["week"])
            except (TypeError, ValueError):
                seen += 1
                rejected += 1
                errors.append({"line": line_no, "error": "season and week must be whole numbers"})
                continue
            if wanted is not None and season not in wanted:
                skipped += 1
                continue
            seen += 1
            try:
                away, home = _code(row["away_team"]), _code(row["home_team"])
                if not away or not home:
                    raise ValueError("a team is missing")
                kickoff = _nflverse_kickoff((row["gameday"] or "").strip(), (row["gametime"] or "").strip())
                a_text, h_text = (row["away_score"] or "").strip(), (row["home_score"] or "").strip()
                if bool(a_text) != bool(h_text):
                    raise ValueError("only one side has a score")
                a_pts, h_pts = (int(float(a_text)), int(float(h_text))) if a_text else (None, None)
                if a_pts is not None and (a_pts < 0 or h_pts < 0):
                    raise ValueError("a score is negative")
                game_id = game_id_for(season, week, away, home)
                flipped = game_id_for(season, week, home, away)
                if (conn.execute("SELECT 1 FROM lab_games WHERE game_id = ?", (game_id,)).fetchone() is None
                        and conn.execute("SELECT 1 FROM lab_games WHERE game_id = ?", (flipped,)).fetchone()):
                    game_id, away, home, a_pts, h_pts = flipped, home, away, h_pts, a_pts
                upsert_game(conn, game_id, season, week, kickoff, away.upper(), home.upper(), a_pts, h_pts,
                            "final" if a_pts is not None else "scheduled", commit=False)
                imported += 1
                finals += a_pts is not None
            except Exception as exc:  # noqa: BLE001 - a bad row is reported, the rest go in
                rejected += 1
                errors.append({"line": line_no, "error": str(exc)})
    conn.execute(
        """INSERT INTO lab_import_log(filename, imported_at_utc, rows_seen, rows_imported,
           rows_rejected, details_json) VALUES (?, ?, ?, ?, ?, ?)""",
        (Path(csv_path).name, utc_now(), seen, imported, rejected,
         json.dumps({"kind": "games", "finals": finals, "errors": errors[:200]})),
    )
    conn.commit()
    return {"rows_seen": seen, "rows_imported": imported, "rows_rejected": rejected, "finals": finals,
            "other_seasons": skipped, "errors": errors}


def import_predictions_csv(conn: sqlite3.Connection, csv_path: str | Path,
                           cutoff: int = CUTOFF_MINUTES) -> dict:
    """
    CSV required columns: game_id, model_id, home_win_probability, retrieved_at_utc.
    Optional: see CSV_OPTIONAL. Games must already be in the log (export the
    template for their ids); a model not registered yet is registered, named
    from model_name. A row's eligibility_status is kept as what the file
    claimed - the status stored is worked out again from the game's kickoff.
    Every row needs a probability from 0 to 1, a model id of letters, digits,
    "-", "_" or ".", and timestamps with a timezone. A row the log already
    has (same model, game, times and probability) is turned away as a duplicate.
    """
    seen = imported = rejected = 0
    errors = []
    kickoffs = {r["game_id"]: r["kickoff_utc"] for r in conn.execute("SELECT game_id, kickoff_utc FROM lab_games")}
    known = {r["model_id"] for r in conn.execute("SELECT model_id FROM lab_models")}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        missing = set(CSV_REQUIRED) - fields
        if missing:
            if set(GAMES_REQUIRED) <= fields:
                raise ValueError("This is a games/results file (nflverse games.csv), not forecasts - "
                                 "import it with 'Import games CSV'.")
            raise ValueError("CSV missing required columns: " + ", ".join(sorted(missing)))
        for line_no, row in enumerate(reader, start=2):
            seen += 1
            try:
                game_id = (row["game_id"] or "").strip()
                model_id = (row["model_id"] or "").strip()
                if game_id not in kickoffs:
                    raise ValueError(f"unknown game_id {game_id!r} - export the template for the ids in use")
                if not model_id:
                    raise ValueError("model_id is empty")
                if not MODEL_ID.match(model_id):
                    raise ValueError(f"model_id {model_id!r} may use only letters, digits, '-', '_' and '.'")
                if _number(row, "home_win_probability") is None:
                    raise ValueError("home_win_probability is empty")
                published_text = (row.get("source_published_at_utc") or "").strip() or None
                if conn.execute(
                        """SELECT 1 FROM lab_predictions WHERE model_id = ? AND game_id = ? AND retrieved_at_utc = ?
                           AND source_published_at_utc IS ? AND home_win_probability = ? LIMIT 1""",
                        (model_id, game_id, (row["retrieved_at_utc"] or "").strip(), published_text,
                         _number(row, "home_win_probability"))).fetchone():
                    raise ValueError("duplicate: this forecast is already in the log")
                if model_id not in known:
                    register_model(conn, model_id, (row.get("model_name") or "").strip() or model_id,
                                   provider="CSV import", model_type="imported")
                    known.add(model_id)
                published = (row.get("source_published_at_utc") or "").strip() or None
                retrieved = (row["retrieved_at_utc"] or "").strip()
                status, note = determine_eligibility(kickoffs[game_id], retrieved, cutoff, published)
                claimed = (row.get("eligibility_status") or "").strip()
                if claimed and claimed != status:
                    note = (note + "; " if note else "") + f"file said {claimed!r}"
                extra = (row.get("data_quality_note") or "").strip()
                add_prediction(
                    conn,
                    game_id=game_id,
                    model_id=model_id,
                    home_win_probability=_number(row, "home_win_probability"),
                    predicted_winner=(row.get("predicted_winner") or "").strip() or None,
                    retrieved_at_utc=retrieved,
                    source_published_at_utc=published,
                    model_version=(row.get("model_version") or "").strip(),
                    projected_home_score=_number(row, "projected_home_score"),
                    projected_away_score=_number(row, "projected_away_score"),
                    source_name=(row.get("source_name") or "").strip(),
                    source_reference=(row.get("source_reference") or "").strip() or f"{Path(csv_path).name}:{line_no}",
                    eligibility_status=status,
                    data_quality_note="; ".join(x for x in (note, extra) if x),
                    snapshot_key=(row.get("snapshot_key") or "").strip() or None,
                    raw_payload=row,
                    commit=False,
                )
                imported += 1
            except Exception as exc:  # noqa: BLE001 - a bad row is reported, the rest go in
                rejected += 1
                errors.append({"line": line_no, "error": str(exc)})
    conn.execute(
        """INSERT INTO lab_import_log(filename, imported_at_utc, rows_seen, rows_imported,
           rows_rejected, details_json) VALUES (?, ?, ?, ?, ?, ?)""",
        (Path(csv_path).name, utc_now(), seen, imported, rejected, json.dumps(errors)),
    )
    conn.commit()
    return {"rows_seen": seen, "rows_imported": imported, "rows_rejected": rejected, "errors": errors}


LEADERBOARD_FIELDS = [
    "model_id", "model_name", "games", "brier_score", "log_loss",
    "winner_accuracy", "winner_predictions_scored", "margin_mae",
    "margin_games", "total_mae", "total_games", "duplicate_game_records_excluded",
]


def export_evaluation_csv(results: Iterable[dict], output_path: str | Path) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEADERBOARD_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(list(results))


HISTORY_FIELDS = ["prediction_id", "game_id", "season", "week", "away_team", "home_team", "kickoff_utc",
                  "model_id", "display_name", "model_version", "home_win_probability", "predicted_winner",
                  "projected_home_score", "projected_away_score", "source_name", "source_published_at_utc",
                  "retrieved_at_utc", "recorded_at_utc", "source_reference", "eligibility_status",
                  "data_quality_note", "snapshot_key", "away_score", "home_score"]


def export_history_csv(conn: sqlite3.Connection, output_path: str | Path, model_id: str | None = None) -> int:
    rows = history(conn, model_id, limit=10**9)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HISTORY_FIELDS)
        for r in rows:
            writer.writerow([r[name] for name in HISTORY_FIELDS])
    return len(rows)


def export_template_csv(conn: sqlite3.Connection, output_path: str | Path, season: int, week: int) -> int:
    """A blank CSV with a week's game ids filled in, ready for an outside model's numbers."""
    games = conn.execute("SELECT game_id, away_team, home_team FROM lab_games WHERE season = ? AND week = ? "
                         "ORDER BY kickoff_utc", (season, week)).fetchall()
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(list(CSV_REQUIRED) + list(CSV_OPTIONAL))
        for g in games:
            writer.writerow([g["game_id"]] + [""] * (len(CSV_REQUIRED) + len(CSV_OPTIONAL) - 1))
    return len(games)


def create_snapshot(
    conn: sqlite3.Connection,
    snapshot_key: str,
    season: int,
    cutoff_minutes_before_kickoff: int,
    description: str = "",
) -> None:
    if cutoff_minutes_before_kickoff < 0:
        raise ValueError("cutoff_minutes_before_kickoff cannot be negative")
    conn.execute(
        """INSERT OR IGNORE INTO lab_snapshots
        (snapshot_key, season, cutoff_minutes_before_kickoff, created_at_utc, description)
        VALUES (?, ?, ?, ?, ?)""",
        (snapshot_key, season, cutoff_minutes_before_kickoff, utc_now(), description),
    )
    conn.commit()


def determine_eligibility(
    kickoff_utc: str,
    retrieved_at_utc: str,
    cutoff_minutes_before_kickoff: int = CUTOFF_MINUTES,
    source_published_at_utc: Optional[str] = None,
) -> tuple[str, str]:
    """
    Conservative helper. A forecast is eligible only when both its retrieval and,
    if supplied, source publication time are at/before the common cutoff.
    Missing source publication time is explicitly flagged rather than assumed valid.
    """
    kickoff = parse_utc(kickoff_utc)
    retrieved = parse_utc(retrieved_at_utc)
    cutoff = kickoff.timestamp() - cutoff_minutes_before_kickoff * 60
    if retrieved >= kickoff:
        return "postgame", "Retrieved at or after kickoff"
    if source_published_at_utc is None:
        return "missing_timestamp", "Source publication timestamp unavailable"
    published = parse_utc(source_published_at_utc)
    if published >= kickoff:
        return "postgame", "Source publication time is at or after kickoff"
    if published.timestamp() > cutoff or retrieved.timestamp() > cutoff:
        return "late", "Forecast was not available by the common cutoff"
    return "eligible", ""


def results_json(results: Sequence[dict]) -> str:
    return json.dumps(list(results), indent=2, sort_keys=True)


# ---- bringing in what the app already holds ------------------------------------------------------------
def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "model"


MARKET_SPREAD, MARKET_MONEYLINE = "market-spread", "market-moneyline"


def _sync_games(conn, year: int, week: int, odds_kickoffs: dict) -> dict:
    """The week's games from the scoreboard kept on file, by the pool's "away@home" key: {key: (game_id, Score)}."""
    from ..feeds import results
    out = {}
    for score in results.load(year, week):
        kickoff = score.kickoff
        if kickoff is None:
            text = odds_kickoffs.get(f"{score.away}@{score.home}")
            try:
                kickoff = parse_utc(text).timestamp() if text else None
            except ValueError:
                kickoff = None
        if kickoff is None:
            continue                      # no kickoff on file: nothing can be shown to be before it
        game_id = game_id_for(year, week, score.away, score.home)
        played = score.final and score.home_points is not None and score.away_points is not None
        upsert_game(conn, game_id, year, week, iso(kickoff), score.away.upper(), score.home.upper(),
                    score.away_points if played else None, score.home_points if played else None,
                    "final" if played else ("in progress" if score.state == "in" else "scheduled"))
        out[f"{score.away}@{score.home}"] = (game_id, score, kickoff)
    return out


def _find(games: dict, away: str, home: str):
    """A game by the pool's teams, and whether the scoreboard has them the other way round (neutral site)."""
    if f"{away}@{home}" in games:
        return games[f"{away}@{home}"], False
    if f"{home}@{away}" in games:
        return games[f"{home}@{away}"], True
    return None, False


def bring_in(conn: sqlite3.Connection, year: int | None = None, cutoff: int = CUTOFF_MINUTES,
             now: float | None = None) -> dict:
    """Copy into the log what the app already holds with a provable time. Safe to run again: a
    source record already logged is skipped. Returns counts by source.

      * the ledger: every recipe's number for a locked week, with the time it
        was written (its home margin read as a home win chance the way the
        rest of the app reads one, luck._home_win). A week written after its
        games goes in as "postgame" and is never scored.
      * fetched betting lines: for each game, the last line fetched before its
        cutoff, once the cutoff has passed (so it is final), dated from its
        fetch. The moneyline's win chance is kept only at the latest fetch, so
        it goes in with that fetch's time.
    """
    from .. import store
    from ..feeds import results
    from .luck import _home_win
    now = time.time() if now is None else now
    year = results.season_year(None, now) if year is None else int(year)
    counts = {"games": 0, "ledger": 0, "lines": 0, "moneylines": 0, "skipped": 0}
    try:
        odds_weeks = store.get("odds", "weeks", {}) or {}
    except Exception:  # noqa: BLE001
        odds_weeks = {}
    ledger_weeks = {}
    for key, value in (store.items("ledger") or {}).items():
        try:
            y, w = (int(x) for x in str(key).split("-"))
        except ValueError:
            continue
        if y == year and isinstance(value, dict):
            ledger_weeks[w] = value
    weeks_on_file = sorted(set(ledger_weeks) | {int(w) for w in odds_weeks if str(w).isdigit()})

    register_model(conn, MARKET_SPREAD, "Betting line (fetched)", provider="Odds feed",
                   model_type="market", notes="Spread as fetched, read as a home win chance by the app's own sums")
    register_model(conn, MARKET_MONEYLINE, "Moneyline (fetched)", provider="Odds feed",
                   model_type="market", notes="Moneyline win chance as fetched, at the latest fetch")
    for week in weeks_on_file:
        entry = odds_weeks.get(str(week)) or {}
        games = _sync_games(conn, year, week, entry.get("kickoff") or {})
        counts["games"] += len(games)
        snap = snapshot_for(year, week, cutoff)
        create_snapshot(conn, snap, year, cutoff, f"Week {week}: forecasts in by {cutoff} minutes before each kickoff")

        def log(model_id, game_id, p, at, ref, source, version="", note="", payload=None):
            if already_logged(conn, model_id, game_id, ref):
                counts["skipped"] += 1
                return False
            kickoff = conn.execute("SELECT kickoff_utc FROM lab_games WHERE game_id = ?", (game_id,)).fetchone()[0]
            status, why = determine_eligibility(kickoff, iso(at), cutoff, iso(at))
            g = conn.execute("SELECT away_team, home_team FROM lab_games WHERE game_id = ?", (game_id,)).fetchone()
            winner = None if p == 0.5 else (g["home_team"] if p > 0.5 else g["away_team"])
            add_prediction(conn, game_id=game_id, model_id=model_id, home_win_probability=p,
                           predicted_winner=winner, retrieved_at_utc=iso(at), source_published_at_utc=iso(at),
                           model_version=version, source_name=source, source_reference=ref,
                           eligibility_status=status, data_quality_note="; ".join(x for x in (why, note) if x),
                           snapshot_key=snap, raw_payload=payload, commit=False)
            return True

        # the ledger
        kept = ledger_weeks.get(week) or {}
        for row in kept.get("games") or ():
            found, flipped = _find(games, str(row.get("road", "")), str(row.get("home", "")))
            at = row.get("at")
            if found is None or not isinstance(at, (int, float)):
                continue
            game_id = found[0]
            for name, margin in (row.get("margins") or {}).items():
                if not isinstance(margin, (int, float)):
                    continue
                model_id = slug(name)
                register_model(conn, model_id, name, provider="ACQL ledger", model_type="recipe",
                               notes="Numbers as written down in the ledger (model/ledger.py)")
                p = _home_win(float(margin))
                p = 1 - p if flipped else p
                if log(model_id, game_id, round(p, 4), at, f"ledger:{year}-{week}#{row.get('index')}",
                       "ACQL ledger", str(kept.get("version") or ""),
                       "home margin %+.2f read as a win chance" % margin,
                       {"margin": margin, "ledger_at": at, "before": row.get("before")}):
                    counts["ledger"] += 1

        # fetched lines: the last before each game's cutoff, once that cutoff has passed
        for key, (game_id, score, kickoff) in games.items():
            due = kickoff - cutoff * 60
            if now < due:
                continue
            fetched = [h for h in entry.get("history") or () if isinstance(h, dict)
                       and isinstance(h.get("at"), (int, float)) and h["at"] <= due]
            for flipped_key, flipped in ((key, False), ("@".join(reversed(key.split("@"))), True)):
                lines = [(h["at"], h["lines"][flipped_key]) for h in fetched
                         if isinstance(h.get("lines"), dict) and isinstance(h["lines"].get(flipped_key), (int, float))]
                if lines:
                    at, margin = lines[-1]
                    p = _home_win(float(margin))
                    p = 1 - p if flipped else p
                    if log(MARKET_SPREAD, game_id, round(p, 4), at, f"odds:{week}:{flipped_key}@{at:.0f}",
                           "Odds feed (spread)", note="home margin %+.1f; dated from its fetch" % margin,
                           payload={"home_margin": margin, "fetched_at": at}):
                        counts["lines"] += 1
                    break
            # the moneyline's chance is kept only as at the latest fetch
            at = entry.get("at")
            for flipped_key, flipped in ((key, False), ("@".join(reversed(key.split("@"))), True)):
                win = (entry.get("win") or {}).get(flipped_key)
                if isinstance(win, (int, float)) and isinstance(at, (int, float)) and at < kickoff:
                    p = 1 - float(win) if flipped else float(win)
                    if log(MARKET_MONEYLINE, game_id, round(p, 4), at, f"odds-win:{week}:{flipped_key}@{at:.0f}",
                           "Odds feed (moneyline)", note="dated from its fetch",
                           payload={"home_win": win, "fetched_at": at}):
                        counts["moneylines"] += 1
                    break
        conn.commit()
    return counts


# ---- the scorecard: every past forecast graded against the result ------------------------------------------
def _home_margin(row) -> Optional[float]:
    """A forecast's home margin: from its projected scores, else the margin it was brought in with.

    A brought-in margin was written in the pool's orientation, which a neutral-site game can have the other
    way round from the log's; its win chance was turned with it, so the chance's side settles which way."""
    if row["projected_home_score"] is not None and row["projected_away_score"] is not None:
        return float(row["projected_home_score"]) - float(row["projected_away_score"])
    try:
        payload = json.loads(row["raw_payload_json"] or "{}")
    except ValueError:
        return None
    margin = payload.get("margin", payload.get("home_margin")) if isinstance(payload, dict) else None
    if not isinstance(margin, (int, float)) or not math.isfinite(margin):
        return None
    p = row["home_win_probability"]
    if p is not None and margin and p != 0.5 and (margin > 0) != (p > 0.5):
        margin = -margin
    return float(margin)


def _picked(row) -> Optional[str]:
    """The side a forecast picked: the winner it named, else the side its win chance favoured."""
    if row["predicted_winner"]:
        return str(row["predicted_winner"]).casefold()
    p = row["home_win_probability"]
    if p is None or p == 0.5:
        return None
    return (row["home_team"] if p > 0.5 else row["away_team"]).casefold()


def grade_forecasts(conn: sqlite3.Connection, season: Optional[int] = None) -> list[dict]:
    """Every eligible forecast on a finished game, graded: did it have the winner, how far its margin missed,
    and whether that miss beat the closing line's (the last fetched spread before the cutoff).

    The same rules as the leaderboard: eligible forecasts only, and a model with two eligible forecasts for
    one game has that game left out rather than one of them chosen. A tie has no winner to have, so it is
    graded on its margin only."""
    where, params = ["g.home_score IS NOT NULL", "g.away_score IS NOT NULL",
                     "p.eligibility_status = 'eligible'"], []
    if season is not None:
        where.append("g.season = ?")
        params.append(season)
    rows = conn.execute(
        f"""SELECT p.prediction_id, p.model_id, m.display_name, m.model_type, p.game_id, p.retrieved_at_utc,
                   p.home_win_probability, p.predicted_winner, p.projected_home_score, p.projected_away_score,
                   p.raw_payload_json, g.season, g.week, g.kickoff_utc, g.home_team, g.away_team,
                   g.home_score, g.away_score
            FROM lab_predictions p JOIN lab_games g ON g.game_id = p.game_id
            JOIN lab_models m ON m.model_id = p.model_id
            WHERE {' AND '.join(where)} ORDER BY g.kickoff_utc, g.game_id, p.model_id""", params).fetchall()

    # the closing line: the latest eligible fetched spread on each game
    closing: dict[str, tuple[str, float]] = {}
    for r in rows:
        if r["model_id"] == MARKET_SPREAD:
            margin = _home_margin(r)
            before = closing.get(r["game_id"])
            if margin is not None and (before is None or r["retrieved_at_utc"] >= before[0]):
                closing[r["game_id"]] = (r["retrieved_at_utc"], margin)

    counts: dict = {}
    for r in rows:
        counts[(r["model_id"], r["game_id"])] = counts.get((r["model_id"], r["game_id"]), 0) + 1
    graded = []
    for r in rows:
        if counts[(r["model_id"], r["game_id"])] != 1:
            continue
        actual = r["home_score"] - r["away_score"]
        winner = None if actual == 0 else (r["home_team"] if actual > 0 else r["away_team"]).casefold()
        picked = _picked(r)
        margin = _home_margin(r)
        miss = None if margin is None else abs(margin - actual)
        line = closing.get(r["game_id"])
        line_miss = None if line is None else abs(line[1] - actual)
        versus = None
        if miss is not None and line_miss is not None and r["model_id"] != MARKET_SPREAD:
            versus = "beat" if miss < line_miss else ("lost" if miss > line_miss else "even")
        graded.append({
            "prediction_id": r["prediction_id"], "model_id": r["model_id"], "model_name": r["display_name"],
            "game_id": r["game_id"], "season": r["season"], "week": r["week"],
            "away_team": r["away_team"], "home_team": r["home_team"],
            "away_score": r["away_score"], "home_score": r["home_score"],
            "picked": picked.upper() if picked else None,
            "hit": None if winner is None or picked is None else picked == winner,
            "home_margin": margin, "miss": miss,
            "closing_line": None if line is None else line[1], "line_miss": line_miss, "versus_line": versus,
        })
    return graded


def _tally(items: Sequence[dict]) -> dict:
    picks = [g for g in items if g["hit"] is not None]
    misses = [g["miss"] for g in items if g["miss"] is not None]
    against = [g for g in items if g["versus_line"] is not None]
    beat = sum(g["versus_line"] == "beat" for g in against)
    lost = sum(g["versus_line"] == "lost" for g in against)
    return {
        "games": len(items),
        "hits": sum(g["hit"] for g in picks), "picks": len(picks),
        "hit_rate": sum(g["hit"] for g in picks) / len(picks) if picks else None,
        "avg_miss": sum(misses) / len(misses) if misses else None, "margin_games": len(misses),
        "line_games": len(against), "beat_line": beat, "lost_to_line": lost,
        # of the games that weren't dead even with the line
        "beat_line_rate": beat / (beat + lost) if beat + lost else None,
        # how much closer than the closing line, on average (positive: the model was closer)
        "line_edge": (sum(g["line_miss"] - g["miss"] for g in against) / len(against)) if against else None,
    }


def scorecard(conn: sqlite3.Connection, season: Optional[int] = None) -> list[dict]:
    """Each model's record on every graded forecast, with a running tally week by week.

    Per model: hit rate (had the winner), average miss (points between its margin and the result), and
    against the closing line - games it was closer, games it was further, and its average edge in points.
    `weeks` holds the same tally as it stood after each week. The betting line itself is listed for its hit
    rate and miss, with nothing to beat. Sorted with the models that beat the close most often first."""
    by_model: dict[str, list[dict]] = {}
    for g in grade_forecasts(conn, season):
        by_model.setdefault(g["model_id"], []).append(g)
    out = []
    for model_id, items in by_model.items():
        running = []
        for week in sorted({(g["season"], g["week"]) for g in items}):
            so_far = [g for g in items if (g["season"], g["week"]) <= week]
            running.append({"season": week[0], "week": week[1], **_tally(so_far)})
        out.append({"model_id": model_id, "model_name": items[0]["model_name"], **_tally(items), "weeks": running})
    return sorted(out, key=lambda r: (r["beat_line_rate"] is None, -(r["beat_line_rate"] or 0),
                                      r["avg_miss"] if r["avg_miss"] is not None else float("inf")))


SCORECARD_FIELDS = ["model_id", "model_name", "games", "hits", "picks", "hit_rate", "avg_miss", "margin_games",
                    "line_games", "beat_line", "lost_to_line", "beat_line_rate", "line_edge"]


def export_scorecard_csv(card: Iterable[dict], output_path: str | Path) -> None:
    """The scorecard, one row per model per week as the tally stood then, and a season row (week blank)."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "week"] + SCORECARD_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for model in card:
            for week in model["weeks"]:
                writer.writerow({**model, **week})
            writer.writerow({**model, "season": "", "week": ""})
