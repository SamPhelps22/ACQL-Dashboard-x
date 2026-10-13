"""The week's inputs, archived as they were - so Deadeye can be judged later.

Deadeye leans on two things that are gone once the week is over: the
Prediction Tracker file it read (every computer model's number, and the
market line at the time), and the card it made from them. Without both, its
blend of the models with the market (predictions.CONSENSUS_WEIGHT) can never
be checked against a plain betting-line card - the files are not kept
anywhere else.

So, every week:

  * each new predictions file that is read is kept: a byte-for-byte copy in
    the data folder's ``archive/<season>/`` and its rows in the database,
    with when it was read and a fingerprint (the same file read twice is
    kept once);
  * once the week kicks off, the record is closed: Deadeye's card as it
    stood at the lock (cards.py), the lines it used and the file it read.

Nothing is ever overwritten or deleted here. ``python -m acql.archive``
lists what is kept.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import asdict
from pathlib import Path

#: The database kind: one document a week, "2026-06".
KIND = "archive"
FOLDER = "archive"


def _key(year: int, week: int) -> str:
    return f"{int(year)}-{int(week):02d}"


def _store():
    from . import store
    return store


def folder(year: int) -> Path:
    """Copies sit next to the database in use (a scratch one in tests)."""
    return _store().db_path().parent / FOLDER / str(int(year))


def record(year: int, week: int) -> dict:
    """What is kept for a week: {"files": [...], "final": {...} or None}."""
    got = _store().get(KIND, _key(year, week), None)
    return got if isinstance(got, dict) else {"files": [], "final": None}


def _put(year: int, week: int, entry: dict) -> None:
    store = _store()
    try:
        store.put(KIND, _key(year, week), entry)
    except store.StoreError:
        pass


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def keep_file(year: int, week: int, path: str | Path, forecasts: list, *, now: float | None = None) -> bool:
    """Archive a predictions file just read for `week`. False if it was already kept."""
    path = Path(path)
    try:
        sha = fingerprint(path)
    except OSError:
        return False
    entry = record(year, week)
    if any(f.get("sha256") == sha for f in entry.get("files", [])):
        return False
    at = time.time() if now is None else now
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(at))
    target = folder(year) / f"week{int(week):02d}_{stamp}_{path.name}"
    copied = ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied = str(target)
    except OSError:
        pass
    entry.setdefault("files", []).append({
        "read_at": at,
        "source": str(path),
        "copy": copied,
        "sha256": sha,
        "games": [asdict(f) for f in forecasts],
    })
    _put(year, week, entry)
    return True


def close_week(year: int, week: int, card, forecasts: list, *, now: float | None = None) -> bool:
    """Record the week as it stood at the lock: Deadeye's card and the lines. Once only."""
    entry = record(year, week)
    if entry.get("final"):
        return False
    if card is None and not forecasts:
        return False
    entry["final"] = {
        "closed_at": time.time() if now is None else now,
        "card": asdict(card) if card is not None else None,
        "lines": [{"road": f.road, "home": f.home, "market": f.market, "opening": f.opening,
                   "models": len(getattr(f, "opinions", ()) or ()), "consensus": f.consensus}
                  for f in forecasts],
    }
    _put(year, week, entry)
    return True


def weeks() -> dict[str, dict]:
    """Every archived week, "2026-06" -> its record."""
    return {k: v for k, v in _store().items(KIND).items() if isinstance(v, dict)}


def describe() -> str:
    lines = []
    for key in sorted(weeks()):
        entry = weeks()[key]
        files = entry.get("files", [])
        final = entry.get("final")
        lines.append(f"{key}: {len(files)} predictions file(s) kept"
                     + ("; closed at kickoff with Deadeye's card" if final and final.get("card")
                        else "; closed at kickoff (no card)" if final else "; still open"))
    return "\n".join(lines) or "Nothing archived yet."


if __name__ == "__main__":
    print(describe())
