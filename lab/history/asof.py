"""What a game's prediction may see at a cutoff - the one rule, in one place.

A record is built from rows whose `available_at` is at or before the cutoff,
and from nothing else:

  * the market fields take the latest such snapshot (ties: a fetched
    snapshot before a file's own line, then the id, so the choice never
    depends on insertion order);
  * the models are the latest source file of them available by then;
  * the pool line comes from the commissioner's sheets for that week.

A row with no `available_at` was never certainly in hand before anything, so
it can't fill a verified field. The undated market lines (nflverse) are kept
in separate `*_unverified` fields, and every record that carries one says
so in its flags - a backtest has to opt in to them on purpose.

The `outcomes` table is never read here. The tests hold that with an SQLite
authorizer that refuses every read of it while records are built.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

CUTOFF_KINDS = ("week_lock", "kickoff")

WEEK_LOCK_BASIS = ("the week's first kickoff by the schedule - production's odds-lock "
                   "rule (acql/oddslock.py)")
KICKOFF_BASIS = "this game's own kickoff by the schedule"

# Preference among snapshots that became available at the same moment.
_TIMING_RANK = ("CASE timing WHEN 'snapshot' THEN 0 WHEN 'file_market' THEN 1 "
                "WHEN 'typed' THEN 2 WHEN 'unspecified' THEN 3 ELSE 4 END")
# Among undated lines, the one source that covers every season leads, so the
# quarantined fields mean the same thing from season to season.
_UNDATED_RANK = ("CASE timing WHEN 'unspecified' THEN 0 WHEN 'file_market' THEN 1 "
                 "WHEN 'typed' THEN 2 ELSE 3 END")

# The rules are recorded in pool_rules; these are their ids.
LINED_RULE = "pool_line_v1"
STRAIGHT_RULE = "straight_up_v1"


# ---- cutoffs ----------------------------------------------------------------------
def cutoffs(conn: sqlite3.Connection) -> dict[str, dict[str, tuple[float | None, str]]]:
    """game_id -> {cutoff kind: (cutoff time or None, basis)}.

    The week lock is the first kickoff of the week's games; if any game of
    the week has no kickoff time, the first one is not known and the cutoff
    is left empty rather than taken from the games that do have one.
    """
    weeks: dict[tuple[int, int], list[float | None]] = {}
    rows = conn.execute("SELECT game_id, season, week, kickoff_utc FROM games").fetchall()
    for _, season, week, kickoff in rows:
        weeks.setdefault((season, week), []).append(kickoff)
    out = {}
    for game_id, season, week, kickoff in rows:
        times = weeks[(season, week)]
        lock = min(times) if all(t is not None for t in times) else None
        out[game_id] = {
            "week_lock": (lock, WEEK_LOCK_BASIS if lock is not None
                          else "unknown: a game of this week has no kickoff time"),
            "kickoff": (kickoff, KICKOFF_BASIS if kickoff is not None
                        else "unknown: the schedule has no kickoff time"),
        }
    return out


# ---- choosing rows ----------------------------------------------------------------
def _dict(cursor: sqlite3.Cursor, row: tuple | None) -> dict | None:
    if row is None:
        return None
    return {d[0]: v for d, v in zip(cursor.description, row)}


def latest_snapshot(conn, game_id: str, market: str, cutoff: float | None,
                    timings: tuple[str, ...] = ("snapshot", "file_market", "typed", "unspecified")) -> dict | None:
    """The latest dated snapshot available at or before the cutoff, or None."""
    if cutoff is None:
        return None
    marks = ",".join("?" * len(timings))
    cur = conn.execute(
        f"SELECT * FROM odds_snapshots WHERE game_id = ? AND market = ? "
        f"AND available_at IS NOT NULL AND available_at <= ? AND timing IN ({marks}) "
        f"ORDER BY available_at DESC, {_TIMING_RANK}, snapshot_id LIMIT 1",
        (game_id, market, cutoff, *timings),
    )
    return _dict(cur, cur.fetchone())


def opening_snapshot(conn, game_id: str, cutoff: float | None) -> dict | None:
    """The opening spread as known at the cutoff.

    A file that states its opener (Prediction Tracker `lineopen`) is believed
    for it; failing that, the earliest dated spread we hold.
    """
    if cutoff is None:
        return None
    cur = conn.execute(
        "SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'spread' "
        "AND timing = 'file_opening' AND available_at IS NOT NULL AND available_at <= ? "
        "ORDER BY available_at DESC, snapshot_id LIMIT 1", (game_id, cutoff))
    found = _dict(cur, cur.fetchone())
    if found:
        return found
    cur = conn.execute(
        "SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'spread' "
        "AND timing IN ('snapshot', 'file_market') AND available_at IS NOT NULL "
        "AND available_at <= ? ORDER BY available_at ASC, snapshot_id LIMIT 1", (game_id, cutoff))
    return _dict(cur, cur.fetchone())


def undated_snapshot(conn, game_id: str, market: str) -> dict | None:
    """The quarantined undated line for a market, or None."""
    cur = conn.execute(
        f"SELECT * FROM odds_snapshots WHERE game_id = ? AND market = ? "
        f"AND available_at IS NULL AND timing != 'file_opening' "
        f"ORDER BY {_UNDATED_RANK}, snapshot_id LIMIT 1", (game_id, market))
    return _dict(cur, cur.fetchone())


def forecasts_at(conn, game_id: str, cutoff: float | None) -> tuple[str | None, list[dict]]:
    """(source, its rows) - the latest forecast file available by the cutoff."""
    if cutoff is None:
        return None, []
    row = conn.execute(
        "SELECT source_id FROM model_forecasts WHERE game_id = ? AND available_at IS NOT NULL "
        "AND available_at <= ? ORDER BY available_at DESC, source_id DESC LIMIT 1",
        (game_id, cutoff)).fetchone()
    if row is None:
        return None, []
    cur = conn.execute(
        "SELECT * FROM model_forecasts WHERE game_id = ? AND source_id = ? "
        "AND available_at <= ? ORDER BY model, forecast_id", (game_id, row[0], cutoff))
    return row[0], [_dict(cur, r) for r in cur.fetchall()]


def pool_line(conn, game_id: str) -> tuple[str, dict | None, list[str]]:
    """(status, the agreed line row if lined, flags) from the week's sheets."""
    rows = conn.execute(
        "SELECT pool_line_id, favourite_code, points, home_line, problem, s.season_match "
        "FROM pool_lines l JOIN pool_sheets s USING (sheet_id) WHERE game_id = ? "
        "ORDER BY pool_line_id", (game_id,)).fetchall()
    if not rows:
        return "unknown", None, ["POOL_LINE_UNKNOWN"]
    flags = ["POOL_LINE_TIME_UNVERIFIED"]
    if any(r[5] != "unique" for r in rows):
        flags.append("POOL_SHEET_SEASON_PARTIAL")
    if any(r[4] for r in rows):
        return "unreadable", None, flags + ["POOL_NOTE_UNREADABLE"]
    lines = {(r[1], r[2], r[3]) for r in rows}
    if len(lines) > 1:
        return "conflict", None, flags + ["POOL_LINE_CONFLICT"]
    favourite, points, home_line = next(iter(lines))
    if points is None:
        return "straight_up", None, flags
    return "lined", {"pool_line_id": rows[0][0], "home_line": home_line}, flags


def rule_for(conn, status: str, season: int, week: int) -> tuple[str | None, bool, list[str]]:
    """(rule id, whether that rule is evidenced by this week, flags)."""
    rule_id = {"lined": LINED_RULE, "straight_up": STRAIGHT_RULE}.get(status)
    if rule_id is None:
        return None, False, []
    row = conn.execute(
        "SELECT status, verified_from_season, verified_from_week FROM pool_rules WHERE rule_id = ?",
        (rule_id,)).fetchone()
    verified = bool(row and row[0] == "verified" and row[1] is not None
                    and (season, week) >= (row[1], row[2]))
    return rule_id, verified, ([] if verified else ["RULES_NOT_VERIFIED_FOR_PERIOD"])


# ---- one record -------------------------------------------------------------------
def build_record(conn: sqlite3.Connection, game: dict, kind: str,
                 cutoff_at: float | None, basis: str) -> dict:
    """The prediction record for one game at one cutoff."""
    gid = game["game_id"]
    flags: set[str] = set()
    if cutoff_at is None:
        flags.add("CUTOFF_UNKNOWN")

    spread = latest_snapshot(conn, gid, "spread", cutoff_at)
    total = latest_snapshot(conn, gid, "total", cutoff_at)
    money = latest_snapshot(conn, gid, "moneyline", cutoff_at)
    opening = opening_snapshot(conn, gid, cutoff_at)
    for name, found in (("SPREAD", spread), ("TOTAL", total), ("MONEYLINE", money)):
        if found is None:
            flags.add(f"NO_VERIFIED_{name}_AT_CUTOFF")
        elif found["orientation"] == "flipped":
            flags.add("SOURCE_HOME_AWAY_FLIPPED")

    loose = {m: undated_snapshot(conn, gid, m) for m in ("spread", "total", "moneyline")}
    for market, found in loose.items():
        if found is not None:
            flags.add(f"{market.upper()}_TIME_UNVERIFIED")

    source, forecasts = forecasts_at(conn, gid, cutoff_at)
    if not forecasts:
        flags.add("NO_MODEL_FORECASTS_AT_CUTOFF")
    elif any(f["published_at"] is None for f in forecasts):
        flags.add("MODEL_PUBLICATION_TIME_UNKNOWN")
    undated_models = conn.execute(
        "SELECT COUNT(*) FROM model_forecasts WHERE game_id = ? AND available_at IS NULL",
        (gid,)).fetchone()[0]
    if undated_models:
        flags.add("MODEL_FORECAST_TIME_UNVERIFIED")

    status, line, pool_flags = pool_line(conn, gid)
    flags.update(pool_flags)
    rule_id, verified, rule_flags = rule_for(conn, status, game["season"], game["week"])
    flags.update(rule_flags)

    def value(row, key="home_value"):
        return None if row is None else row[key]

    def ident(row):
        return None if row is None else row["snapshot_id"]

    record = {
        "record_id": f"{gid}|{kind}",
        "game_id": gid,
        "season": game["season"],
        "week": game["week"],
        "away_code": game["away_code"],
        "home_code": game["home_code"],
        "neutral": game["neutral"],
        "cutoff_kind": kind,
        "cutoff_at": cutoff_at,
        "cutoff_basis": basis,
        "spread_home": value(spread),
        "spread_snapshot_id": ident(spread),
        "spread_open_home": value(opening),
        "spread_open_snapshot_id": ident(opening),
        "total": value(total),
        "total_snapshot_id": ident(total),
        "moneyline_home": value(money),
        "moneyline_away": value(money, "away_value"),
        "moneyline_snapshot_id": ident(money),
        "spread_home_unverified": value(loose["spread"]),
        "spread_unverified_id": ident(loose["spread"]),
        "total_unverified": value(loose["total"]),
        "total_unverified_id": ident(loose["total"]),
        "moneyline_home_unverified": value(loose["moneyline"]),
        "moneyline_away_unverified": value(loose["moneyline"], "away_value"),
        "moneyline_unverified_id": ident(loose["moneyline"]),
        "n_models": len(forecasts),
        "forecast_source_id": source,
        "forecast_ids": json.dumps([f["forecast_id"] for f in forecasts]),
        "pool_line_status": status,
        "pool_line_home": None if line is None else line["home_line"],
        "pool_line_id": None if line is None else line["pool_line_id"],
        "rule_id": rule_id,
        "rules_verified": int(verified),
        "flags": json.dumps(sorted(flags)),
    }
    # The fingerprint covers the values behind the ids too, so a changed
    # forecast number changes it even when the ids stay the same.
    record["inputs_hash"] = hashlib.sha256(json.dumps(
        {"record": record, "models": [(f["model"], f["home_margin"]) for f in forecasts]},
        sort_keys=True).encode()).hexdigest()
    return record


def games(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute("SELECT * FROM games ORDER BY season, week, game_id")
    return [_dict(cur, row) for row in cur.fetchall()]


def all_records(conn: sqlite3.Connection) -> list[dict]:
    """Every record the tables call for, in a fixed order."""
    times = cutoffs(conn)
    out = []
    for game in games(conn):
        for kind in CUTOFF_KINDS:
            at, basis = times[game["game_id"]][kind]
            out.append(build_record(conn, game, kind, at, basis))
    return out


# ---- handing a record to the production engine (read-only) ----------------------------
def production_forecast(conn: sqlite3.Connection, record_id: str, *, allow_unverified: bool = False):
    """The record as an `acql.predictions.Forecast`, so the app's own pricing can
    be run on it without changing anything in the app.

    Refuses a record with no verified line unless the caller opts in to the
    undated one - which is then the caller's stated choice, not a default.
    """
    from acql.predictions import Forecast  # lazy: production is only read from

    cur = conn.execute("SELECT * FROM prediction_records WHERE record_id = ?", (record_id,))
    rec = _dict(cur, cur.fetchone())
    if rec is None:
        raise KeyError(record_id)
    market = rec["spread_home"]
    if market is None:
        if not allow_unverified:
            raise ValueError(f"{record_id} has no verified line at its cutoff")
        market = rec["spread_home_unverified"]
    ids = json.loads(rec["forecast_ids"])
    opinions = ()
    if ids:
        marks = ",".join("?" * len(ids))
        opinions = tuple(r[0] for r in conn.execute(
            f"SELECT home_margin FROM model_forecasts WHERE forecast_id IN ({marks}) "
            f"ORDER BY model, forecast_id", ids))
    return Forecast(road=rec["away_code"], home=rec["home_code"], market=market,
                    opening=rec["spread_open_home"], opinions=opinions,
                    neutral=bool(rec["neutral"]))
