"""Write-once prediction files and the code/data fingerprints that go with them.

A backtest's forecasts are written before any result is joined to them, as a
gzip CSV named by its run id, with a manifest holding its SHA-256, the config
hash, the git commit, and the data files' hashes. A file that already exists
is never overwritten: writing the same run id again must reproduce the same
bytes, or it is refused (`ImmutableError`).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import VERSION
from .config import ROOT, Config, config_hash

#: The columns a forecast file holds - and the only ones (no outcomes, ever).
COLUMNS = ["run_id", "model", "model_version", "game_id", "season", "week", "game_type", "home", "away",
           "kickoff_utc", "deadline_utc", "data_cutoff_utc", "train_seasons", "p_home", "p_away"]
FORBIDDEN = {"home_score", "away_score", "result", "home_win", "total", "margin", "winner"}


class ImmutableError(RuntimeError):
    pass


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        # code only: the run's own outputs (results, journal, artifacts) do not make the code dirty
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "challenger", ":!challenger/results",
                                ":!challenger/journal", ":!challenger/artifacts"], cwd=ROOT, capture_output=True,
                               text=True, timeout=10).stdout.strip()
        return out.stdout.strip() + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def model_version(cfg: Config) -> str:
    return f"challenger-{VERSION}-{config_hash(cfg)}"


def _bytes(frame: pd.DataFrame) -> bytes:
    text = frame.to_csv(index=False, float_format="%.10f", lineterminator="\n")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(text.encode())
    return buf.getvalue()


def write_once(frame: pd.DataFrame, folder: Path, run_id: str, meta: dict) -> Path:
    """Write a forecast file and its manifest; refuse to change one that exists."""
    bad = FORBIDDEN & set(frame.columns)
    if bad:
        raise ValueError(f"a forecast file may not carry outcomes: {sorted(bad)}")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"predictions_{run_id}.csv.gz"
    payload = _bytes(frame[COLUMNS])
    digest = hashlib.sha256(payload).hexdigest()
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ImmutableError(f"{path.name} exists with different content; a new run needs a new run id")
        return path
    path.write_bytes(payload)
    manifest = {**meta, "run_id": run_id, "file": path.name, "sha256": digest, "rows": int(len(frame)),
                "written_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "git_commit": git_commit()}
    (folder / f"predictions_{run_id}.manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    return path


def read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, compression="gzip")
    for c in ("kickoff_utc", "deadline_utc", "data_cutoff_utc"):
        frame[c] = pd.to_datetime(frame[c], utc=True, format="ISO8601")
    return frame


def verify(path: Path) -> bool:
    """True when a stored file still matches the hash in its manifest."""
    manifest = json.loads(path.with_name(path.name.replace(".csv.gz", ".manifest.json")).read_text())
    return hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sha256"]
