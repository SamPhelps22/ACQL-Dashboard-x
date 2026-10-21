"""Download the public nflverse files the lab uses, with a provenance manifest.

Every file is recorded with its URL, when it was fetched, its size and SHA-256,
so a backtest can name exactly which data it ran on (`dataset_version`).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path

from .. import config

RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
SOURCES = {
    "games.csv": "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
    **{f"pbp_{y}.csv.gz": f"{RELEASE}/pbp/play_by_play_{y}.csv.gz" for y in range(config.FIRST_SEASON, config.CURRENT_SEASON + 1)},
    **{f"injuries_{y}.csv": f"{RELEASE}/injuries/injuries_{y}.csv" for y in range(2009, config.CURRENT_SEASON + 1)},
    **{f"ftn_{y}.csv": f"{RELEASE}/ftn_charting/ftn_charting_{y}.csv" for y in range(2022, config.CURRENT_SEASON + 1)},
    **{f"participation_{y}.csv": f"{RELEASE}/pbp_participation/pbp_participation_{y}.csv" for y in range(2016, config.CURRENT_SEASON)},
}
MANIFEST = "manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(raw: Path = config.RAW) -> dict:
    try:
        return json.loads((raw / MANIFEST).read_text())
    except (OSError, ValueError):
        return {}


def record(name: str, url: str, raw: Path = config.RAW, fetched_at: str | None = None) -> dict:
    path = raw / name
    entry = {"url": url, "bytes": path.stat().st_size, "sha256": sha256(path),
             "fetched_at": fetched_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))}
    manifest = read_manifest(raw)
    manifest[name] = entry
    (raw / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return entry


def fetch(names: list[str] | None = None, refresh: bool = False, raw: Path = config.RAW) -> dict:
    raw.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in names or list(SOURCES):
        url = SOURCES[name]
        path = raw / name
        if path.exists() and not refresh:
            if name not in read_manifest(raw):
                record(name, url, raw)
            out[name] = "kept"
            continue
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                path.write_bytes(r.read())
            record(name, url, raw, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            out[name] = "fetched"
        except Exception as exc:  # noqa: BLE001 - reported, never hidden
            out[name] = f"failed: {exc}"
    return out


def dataset_version(raw: Path = config.RAW) -> str:
    """One hash over every file's hash: the data a run used."""
    manifest = read_manifest(raw)
    text = json.dumps({k: v["sha256"] for k, v in sorted(manifest.items())})
    return hashlib.sha256(text.encode()).hexdigest()[:16]
