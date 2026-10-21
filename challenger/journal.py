"""The append-only prospective journal.

Four JSON-lines files under challenger/journal/, each a hash chain (every
record carries the SHA-256 of the one before it, so an edit anywhere breaks
`verify`):

    challenger.jsonl   Challenger's forecasts, written before kickoff
    deadeye.jsonl      Deadeye's forecasts, captured on their own
    market.jsonl       market snapshots (lines as fetched, with the time)
    outcomes.jsonl     final scores, written only after a game has finished

Rules enforced on write:
  * a forecast for a game whose kickoff has passed is refused;
  * records are only ever appended - nothing is rewritten or deleted;
  * an outcome is refused before kickoff + game duration; a later, different
    score for the same game is appended as a flagged correction.

A model may forecast a game more than once before kickoff (e.g. after a data
refresh). The one that is scored is the last one made before the game's ACQL
deadline if there is one, otherwise the last before kickoff; every record
stays in the file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import JOURNAL

KINDS = ("challenger", "deadeye", "market", "outcomes")


class JournalError(RuntimeError):
    pass


def _path(kind: str, folder: Path | None = None) -> Path:
    if kind not in KINDS:
        raise ValueError(kind)
    return (folder or JOURNAL) / f"{kind}.jsonl"


def _canonical(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def read(kind: str, folder: Path | None = None) -> list[dict]:
    path = _path(kind, folder)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify(kind: str, folder: Path | None = None) -> tuple[bool, str]:
    prev = "genesis"
    for i, rec in enumerate(read(kind, folder)):
        body = {k: v for k, v in rec.items() if k != "record_hash"}
        if rec.get("prev_hash") != prev:
            return False, f"record {i}: chain broken"
        if hashlib.sha256(_canonical(body).encode()).hexdigest() != rec.get("record_hash"):
            return False, f"record {i}: content changed"
        prev = rec["record_hash"]
    return True, "ok"


def _append(kind: str, records: list[dict], folder: Path | None = None) -> list[dict]:
    ok, why = verify(kind, folder)
    if not ok:
        raise JournalError(f"{kind} journal fails verification ({why}); refusing to append")
    existing = read(kind, folder)
    prev = existing[-1]["record_hash"] if existing else "genesis"
    path = _path(kind, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = []
    with open(path, "a", encoding="utf-8") as handle:
        for rec in records:
            body = {**rec, "prev_hash": prev}
            body["record_hash"] = hashlib.sha256(_canonical(body).encode()).hexdigest()
            handle.write(_canonical(body) + "\n")
            prev = body["record_hash"]
            written.append(body)
    return written


def now_utc() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def append_forecasts(kind: str, records: list[dict], now: pd.Timestamp | None = None,
                     folder: Path | None = None) -> list[dict]:
    """Append forecasts; every one must be for a game that has not kicked off."""
    now = now or now_utc()
    for r in records:
        kick = pd.Timestamp(r["kickoff_utc"])
        if now >= kick:
            raise JournalError(f"{r['game_id']}: kickoff {kick} has passed (now {now}); a forecast cannot be added")
        r["recorded_at_utc"] = now.isoformat()
    return _append(kind, records, folder)


def append_market(records: list[dict], folder: Path | None = None) -> list[dict]:
    return _append("market", records, folder)


def append_outcomes(records: list[dict], now: pd.Timestamp | None = None, duration_hours: float = 4.5,
                    folder: Path | None = None) -> list[dict]:
    """Append final scores for finished games; a changed score is a flagged correction, never an edit."""
    now = now or now_utc()
    known = {r["game_id"]: r for r in read("outcomes", folder)}
    out = []
    for r in records:
        kick = pd.Timestamp(r["kickoff_utc"])
        if now < kick + pd.Timedelta(hours=duration_hours):
            raise JournalError(f"{r['game_id']}: not finished yet")
        old = known.get(r["game_id"])
        if old and (old["home_score"], old["away_score"]) == (r["home_score"], r["away_score"]):
            continue
        out.append({**r, "recorded_at_utc": now.isoformat(), "correction": bool(old)})
    return _append("outcomes", out, folder) if out else []


def scored_forecasts(kind: str, folder: Path | None = None) -> pd.DataFrame:
    """One forecast per (model_version, game): the last made before the ACQL deadline, else before kickoff."""
    recs = pd.DataFrame(read(kind, folder))
    if recs.empty:
        return recs
    for c in ("recorded_at_utc", "kickoff_utc", "deadline_utc"):
        if c in recs:
            recs[c] = pd.to_datetime(recs[c], utc=True, format="ISO8601")
    recs = recs[recs["recorded_at_utc"] < recs["kickoff_utc"]]
    recs["before_deadline"] = recs["recorded_at_utc"] <= recs.get("deadline_utc", recs["kickoff_utc"])
    recs = recs.sort_values(["before_deadline", "recorded_at_utc"])
    keep = []
    for _, grp in recs.groupby(["model_version", "game_id"]):
        pre = grp[grp["before_deadline"]]
        keep.append((pre if len(pre) else grp).iloc[-1])
    return pd.DataFrame(keep).reset_index(drop=True)
