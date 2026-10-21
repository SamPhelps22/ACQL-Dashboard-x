"""The immutable forecast journal (SQLite).

* A week's official package is revision 0. Until it is locked it is a draft
  and may be regenerated (the draft is replaced atomically, never duplicated -
  this is how an interrupted run recovers).
* Locking verifies the package, stores its content hash and marks it locked.
  From then on database triggers refuse any UPDATE or DELETE of the package or
  its forecasts - not just this module, any client.
* A legitimate operational rerun after the lock is a NEW revision with an
  explicit reason, created already locked. The original stays official and is
  evaluated separately.
* Timestamps are the real wall-clock times; nothing is backdated. A lock after
  the deadline is stored with on_time = 0 and a late alert.
* A REPLAY (re-running a past Thursday, e.g. for testing or research) stores
  the simulated time in created_at/locked_at, the real time in recorded_at,
  and mode = 'replay'. Replays are never on-time live forecasts: on_time is
  NULL for them and reports keep them apart.
* Results are insert-only; a correction is a new row in result_corrections.
* Post-lock information goes to post_lock_notes for monitoring only.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .tz import iso, parse_utc, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS packages (
    package_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL, week INTEGER NOT NULL, game_type TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','locked')),
    created_at TEXT NOT NULL, locked_at TEXT,
    deadline_utc TEXT NOT NULL,
    on_time INTEGER, late_alert TEXT,
    model_name TEXT NOT NULL, model_version TEXT NOT NULL,
    selection_json TEXT NOT NULL, fallback TEXT,
    market_snapshot_json TEXT NOT NULL,
    reason TEXT, supersedes TEXT,
    content_hash TEXT,
    mode TEXT NOT NULL DEFAULT 'live' CHECK (mode IN ('live','replay')),
    recorded_at TEXT NOT NULL,
    UNIQUE (season, week, game_type, revision)
);
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES packages(package_id),
    season INTEGER NOT NULL, week INTEGER NOT NULL, game_id TEXT NOT NULL,
    home TEXT NOT NULL, away TEXT NOT NULL, kickoff_utc TEXT NOT NULL,
    created_at TEXT NOT NULL, cutoff_utc TEXT NOT NULL,
    model_name TEXT NOT NULL, model_version TEXT NOT NULL,
    training_cutoff TEXT NOT NULL, feature_cutoff TEXT NOT NULL, market_ts TEXT,
    p_home REAL NOT NULL, p_away REAL NOT NULL,
    exp_margin REAL, exp_total REAL,
    provenance_json TEXT NOT NULL, missing_flags_json TEXT NOT NULL,
    selection_decision TEXT NOT NULL,
    pick TEXT, p_pick_credited REAL, pool_line REAL,
    content_hash TEXT NOT NULL,
    UNIQUE (package_id, game_id)
);
CREATE TABLE IF NOT EXISTS results (
    game_id TEXT PRIMARY KEY, season INTEGER, week INTEGER,
    home_score REAL NOT NULL, away_score REAL NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS result_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL,
    home_score REAL NOT NULL, away_score REAL NOT NULL, reason TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_lock_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, package_id TEXT NOT NULL, game_id TEXT,
    kind TEXT NOT NULL, detail TEXT NOT NULL, observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT NOT NULL, season INTEGER, week INTEGER, stage TEXT NOT NULL,
    status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, detail TEXT,
    PRIMARY KEY (run_id, stage)
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, season INTEGER, week INTEGER,
    level TEXT NOT NULL, message TEXT NOT NULL, raised_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS packages_locked_no_update BEFORE UPDATE ON packages
WHEN OLD.status = 'locked' BEGIN SELECT RAISE(ABORT, 'locked package is immutable'); END;
CREATE TRIGGER IF NOT EXISTS packages_locked_no_delete BEFORE DELETE ON packages
WHEN OLD.status = 'locked' BEGIN SELECT RAISE(ABORT, 'locked package is immutable'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_locked_no_update BEFORE UPDATE ON forecasts
WHEN (SELECT status FROM packages WHERE package_id = OLD.package_id) = 'locked'
BEGIN SELECT RAISE(ABORT, 'locked forecast is immutable'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_locked_no_delete BEFORE DELETE ON forecasts
WHEN (SELECT status FROM packages WHERE package_id = OLD.package_id) = 'locked'
BEGIN SELECT RAISE(ABORT, 'locked forecast is immutable'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_locked_no_insert BEFORE INSERT ON forecasts
WHEN (SELECT status FROM packages WHERE package_id = NEW.package_id) = 'locked'
BEGIN SELECT RAISE(ABORT, 'cannot add forecasts to a locked package'); END;
CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON results
BEGIN SELECT RAISE(ABORT, 'results are insert-only; use result_corrections'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results
BEGIN SELECT RAISE(ABORT, 'results are insert-only'); END;
"""

HASH_FIELDS = ("game_id", "home", "away", "kickoff_utc", "created_at", "cutoff_utc", "model_name",
               "model_version", "training_cutoff", "feature_cutoff", "market_ts", "p_home", "p_away",
               "exp_margin", "exp_total", "provenance_json", "missing_flags_json", "selection_decision",
               "pick", "p_pick_credited", "pool_line")


class LockError(RuntimeError):
    pass


def _canon(v):
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 10)
    return v


def forecast_hash(f: dict) -> str:
    return hashlib.sha256(json.dumps({k: _canon(f.get(k)) for k in HASH_FIELDS},
                                     sort_keys=True, default=str).encode()).hexdigest()


def package_hash(forecasts: list[dict], header: dict) -> str:
    body = {"header": header, "forecasts": sorted(f["content_hash"] for f in forecasts)}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class Journal:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # ---- runs and alerts ----------------------------------------------------
    def alert(self, season, week, level, message):
        self.conn.execute("INSERT INTO alerts (season, week, level, message, raised_at) VALUES (?,?,?,?,?)",
                          (season, week, level, message, iso(utc_now())))

    def alerts(self, season=None, week=None):
        q, a = "SELECT * FROM alerts", []
        if season is not None:
            q, a = q + " WHERE season=? AND week=?", [season, week]
        return [dict(r) for r in self.conn.execute(q + " ORDER BY id", a)]

    def stage(self, run_id, season, week, stage, status, detail=None):
        now = iso(utc_now())
        if status == "running":
            self.conn.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?)",
                              (run_id, season, week, stage, status, now, None, detail))
        else:
            self.conn.execute("UPDATE runs SET status=?, finished_at=?, detail=? WHERE run_id=? AND stage=?",
                              (status, now, detail, run_id, stage))

    def interrupted_runs(self, season, week):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM runs WHERE season=? AND week=? AND status='running'", (season, week))]

    def mark_interrupted(self, season, week):
        n = 0
        for r in self.interrupted_runs(season, week):
            self.conn.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE run_id=? AND stage=?",
                              (iso(utc_now()), r["run_id"], r["stage"]))
            n += 1
        return n

    # ---- packages -----------------------------------------------------------
    def package(self, season, week, game_type="REG", revision=0):
        r = self.conn.execute("SELECT * FROM packages WHERE season=? AND week=? AND game_type=? AND revision=?",
                              (season, week, game_type, revision)).fetchone()
        return dict(r) if r else None

    def packages(self, season=None, week=None):
        q, a = "SELECT * FROM packages", []
        if season is not None:
            q, a = q + " WHERE season=? AND week=?", [season, week]
        return [dict(r) for r in self.conn.execute(q + " ORDER BY season, week, revision", a)]

    def forecasts(self, package_id):
        return [dict(r) for r in self.conn.execute("SELECT * FROM forecasts WHERE package_id=? ORDER BY kickoff_utc, game_id",
                                                   (package_id,))]

    def official(self, season, week, game_type="REG"):
        p = self.package(season, week, game_type, 0)
        return (p, self.forecasts(p["package_id"])) if p else (None, [])

    def save_draft(self, season, week, game_type, deadline_utc, header: dict, forecasts: list[dict],
                   mode: str = "live", now: datetime | None = None) -> str:
        """Write (or replace) the week's draft. Refuses once the week is locked."""
        existing = self.package(season, week, game_type, 0)
        if existing and existing["status"] == "locked":
            raise LockError(f"{season} week {week} is locked; create a revision with a reason instead")
        pid = f"{season}-{game_type}-{week:02d}-r0"
        with self.conn:
            self.conn.execute("BEGIN")
            if existing:
                self.conn.execute("DELETE FROM forecasts WHERE package_id=?", (pid,))
                self.conn.execute("DELETE FROM packages WHERE package_id=?", (pid,))
            self._insert(pid, season, week, game_type, 0, "draft", deadline_utc, header, forecasts, mode=mode, now=now)
        return pid

    def _insert(self, pid, season, week, game_type, revision, status, deadline_utc, header, forecasts,
                mode="live", now=None):
        real = iso(utc_now())
        if mode == "live" and now is not None and abs((now - utc_now()).total_seconds()) > 300:
            raise LockError("a live package must use the real clock; use mode='replay' for a past moment")
        now = iso(now) if now is not None else real
        self.conn.execute(
            "INSERT INTO packages (package_id, season, week, game_type, revision, status, created_at, locked_at, "
            "deadline_utc, on_time, late_alert, model_name, model_version, selection_json, fallback, "
            "market_snapshot_json, reason, supersedes, content_hash, mode, recorded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, season, week, game_type, revision, "draft", now, None, iso(deadline_utc), None, None,
             header["model_name"], header["model_version"], json.dumps(header.get("selection", {}), default=str),
             header.get("fallback"), json.dumps(header.get("market_snapshot", {}), default=str),
             header.get("reason"), header.get("supersedes"), None, mode, real))
        for f in forecasts:
            f = dict(f)
            f.setdefault("forecast_id", str(uuid.uuid4()))
            f["package_id"] = pid
            f["content_hash"] = forecast_hash(f)
            cols = ["forecast_id", "package_id", "season", "week", "game_id", "home", "away", "kickoff_utc",
                    "created_at", "cutoff_utc", "model_name", "model_version", "training_cutoff", "feature_cutoff",
                    "market_ts", "p_home", "p_away", "exp_margin", "exp_total", "provenance_json",
                    "missing_flags_json", "selection_decision", "pick", "p_pick_credited", "pool_line", "content_hash"]
            self.conn.execute(f"INSERT INTO forecasts ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                              [None if isinstance(f.get(c), float) and math.isnan(f.get(c)) else f.get(c) for c in cols])

    # ---- verification and lock ----------------------------------------------
    def verify(self, package_id, scheduled_game_ids: list[str]) -> list[str]:
        problems = []
        pkg = dict(self.conn.execute("SELECT * FROM packages WHERE package_id=?", (package_id,)).fetchone())
        fc = self.forecasts(package_id)
        have = {f["game_id"] for f in fc}
        missing = sorted(set(scheduled_game_ids) - have)
        if missing:
            problems.append(f"missing forecasts for {missing}")
        extra = sorted(have - set(scheduled_game_ids))
        if extra:
            problems.append(f"forecasts for games not on the slate: {extra}")
        for f in fc:
            p, q = f["p_home"], f["p_away"]
            if p is None or not (0 < p < 1) or not (0 < q < 1) or abs(p + q - 1) > 1e-9:
                problems.append(f"{f['game_id']}: invalid probabilities {p}, {q}")
            if not f["model_version"] or "@" not in f["model_version"]:
                problems.append(f"{f['game_id']}: no immutable model version")
            cut = parse_utc(f["cutoff_utc"])
            for col in ("feature_cutoff", "training_cutoff", "market_ts"):
                if f[col] and parse_utc(f[col]) > cut:
                    problems.append(f"{f['game_id']}: {col} {f[col]} is after the cutoff {f['cutoff_utc']}")
            if parse_utc(f["created_at"]) > parse_utc(f["kickoff_utc"]):
                problems.append(f"{f['game_id']}: forecast created after kickoff")
            if forecast_hash(f) != f["content_hash"]:
                problems.append(f"{f['game_id']}: content hash mismatch")
        if pkg["status"] == "locked":
            problems.append("package already locked")
        return problems

    def lock(self, package_id, scheduled_game_ids, now: datetime | None = None) -> dict:
        problems = self.verify(package_id, scheduled_game_ids)
        if problems:
            raise LockError("; ".join(problems))
        pkg = dict(self.conn.execute("SELECT * FROM packages WHERE package_id=?", (package_id,)).fetchone())
        if pkg["mode"] == "live":
            if now is not None and abs((now - utc_now()).total_seconds()) > 300:
                raise LockError("a live package is locked on the real clock")
            now = utc_now()
        elif now is None:
            raise LockError("a replay lock needs its simulated time")
        fc = self.forecasts(package_id)
        header = {k: pkg[k] for k in ("season", "week", "game_type", "revision", "model_name", "model_version",
                                      "selection_json", "market_snapshot_json", "deadline_utc", "reason")}
        h = package_hash(fc, header)
        in_time = now <= parse_utc(pkg["deadline_utc"])
        on_time = (int(in_time) if pkg["mode"] == "live" else None)
        alert = None if in_time else (f"LATE LOCK: locked {iso(now)} after deadline {pkg['deadline_utc']}; "
                                      "not an on-time forecast" + (" (replay)" if pkg["mode"] == "replay" else ""))
        self.conn.execute("UPDATE packages SET status='locked', locked_at=?, content_hash=?, on_time=?, late_alert=? "
                          "WHERE package_id=?", (iso(now), h, on_time, alert, package_id))
        if alert:
            self.alert(pkg["season"], pkg["week"], "late", alert)
        return {"package_id": package_id, "content_hash": h, "on_time": bool(on_time) if on_time is not None else None,
                "in_time": in_time, "mode": pkg["mode"], "late_alert": alert}

    def check_integrity(self, package_id) -> bool:
        pkg = dict(self.conn.execute("SELECT * FROM packages WHERE package_id=?", (package_id,)).fetchone())
        fc = self.forecasts(package_id)
        if any(forecast_hash(f) != f["content_hash"] for f in fc):
            return False
        header = {k: pkg[k] for k in ("season", "week", "game_type", "revision", "model_name", "model_version",
                                      "selection_json", "market_snapshot_json", "deadline_utc", "reason")}
        return package_hash(fc, header) == pkg["content_hash"]

    def create_revision(self, season, week, game_type, reason: str, header: dict, forecasts: list[dict],
                        scheduled_game_ids, now: datetime | None = None) -> dict:
        if not reason or not reason.strip():
            raise LockError("a revision needs an explicit reason")
        orig = self.package(season, week, game_type, 0)
        if not orig or orig["status"] != "locked":
            raise LockError("revisions are only for weeks whose official package is locked")
        rev = 1 + max(p["revision"] for p in self.packages(season, week))
        pid = f"{season}-{game_type}-{week:02d}-r{rev}"
        header = {**header, "reason": reason, "supersedes": orig["package_id"]}
        with self.conn:
            self.conn.execute("BEGIN")
            self._insert(pid, season, week, game_type, rev, "draft", parse_utc(orig["deadline_utc"]), header, forecasts,
                         mode=orig["mode"], now=now if orig["mode"] == "replay" else None)
        out = self.lock(pid, scheduled_game_ids, now if orig["mode"] == "replay" else None)
        out["revision"] = rev
        return out

    # ---- after the games ----------------------------------------------------
    def record_result(self, game_id, season, week, home_score, away_score) -> bool:
        row = self.conn.execute("SELECT home_score, away_score FROM results WHERE game_id=?", (game_id,)).fetchone()
        if row:
            if (row["home_score"], row["away_score"]) != (home_score, away_score):
                self.conn.execute("INSERT INTO result_corrections (game_id, home_score, away_score, reason, recorded_at) "
                                  "VALUES (?,?,?,?,?)", (game_id, home_score, away_score,
                                                          "source changed after first recording", iso(utc_now())))
            return False
        self.conn.execute("INSERT INTO results VALUES (?,?,?,?,?,?)",
                          (game_id, season, week, home_score, away_score, iso(utc_now())))
        return True

    def note(self, package_id, game_id, kind, detail):
        self.conn.execute("INSERT INTO post_lock_notes (package_id, game_id, kind, detail, observed_at) VALUES (?,?,?,?,?)",
                          (package_id, game_id, kind, detail, iso(utc_now())))
