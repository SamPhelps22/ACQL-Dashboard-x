"""The raw payload archive (idea #44): every answer a source gave, kept as it came.

When a number is doubted - a week's totals, a line that looked wrong - this
is how to prove what the source actually said, and when. Each fetched body is
gzipped and named by its content's fingerprint, so a payload that hasn't
changed since the last look costs one index line and no new file.

It lives outside the synced project folder (%LOCALAPPDATA%\\ACQL\\raw) so it
can never be committed or published. Only what came back is kept, never the
request - the odds request carries the API key.

Keeping is never the thing that breaks a fetch: every function here swallows
its own errors.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from pathlib import Path

#: The sources, by the names the index uses.
SOURCES = ("espn-scores", "odds", "injuries", "predictions", "pfm", "weather", "timeline")
INDEX = "index.jsonl"

_OVERRIDE: Path | None = None


def folder() -> Path | None:
    if _OVERRIDE is not None:
        return _OVERRIDE
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "ACQL" / "raw" if base else None


def use(path: Path | None) -> None:
    """Point the archive somewhere else (tests)."""
    global _OVERRIDE
    _OVERRIDE = path


def keep(source: str, body: bytes | str, label: str = "", now: float | None = None) -> str | None:
    """Keep one payload. Returns its fingerprint, or None when it couldn't be kept."""
    try:
        root = folder()
        if root is None:
            return None
        now = time.time() if now is None else now
        data = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        digest = hashlib.sha256(data).hexdigest()[:20]
        month = time.strftime("%Y-%m", time.localtime(now))
        name = f"{month}/{source}-{digest}.gz"
        target = root / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_suffix(".part")
            part.write_bytes(gzip.compress(data))
            part.replace(target)
        row = {"at": round(now, 1), "source": source, "label": str(label), "hash": digest,
               "size": len(data), "file": name}
        with open(root / INDEX, "a", encoding="utf-8") as out:
            out.write(json.dumps(row) + "\n")
        return digest
    except Exception:  # noqa: BLE001 - never the cause of a failed fetch
        return None


def index(source: str | None = None) -> list[dict]:
    """Every kept fetch, oldest first (optionally one source's)."""
    root = folder()
    if root is None or not (root / INDEX).exists():
        return []
    out = []
    try:
        with open(root / INDEX, encoding="utf-8") as found:
            for line in found:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if source is None or row.get("source") == source:
                    out.append(row)
    except OSError:
        return []
    return out


def latest(source: str, before: float | None = None) -> dict | None:
    """The last fetch of a source (at or before a time, if given)."""
    rows = [r for r in index(source) if before is None or float(r.get("at", 0)) <= before]
    return rows[-1] if rows else None


def read(row: dict) -> bytes | None:
    """A kept payload's bytes, as they came."""
    root = folder()
    try:
        return gzip.decompress((root / row["file"]).read_bytes()) if root else None
    except (OSError, KeyError, EOFError, gzip.BadGzipFile):
        return None


def open_copy(row: dict) -> Path | None:
    """Write a readable copy of a kept payload to a temporary file and return its path."""
    import tempfile
    data = read(row)
    if data is None:
        return None
    try:
        text = json.dumps(json.loads(data), indent=2).encode("utf-8")
        suffix = ".json"
    except ValueError:
        text, suffix = data, ".txt"
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(float(row.get("at", 0))))
    path = Path(tempfile.gettempdir()) / f"acql-raw-{row.get('source')}-{stamp}{suffix}"
    try:
        path.write_bytes(text)
    except OSError:
        return None
    return path
