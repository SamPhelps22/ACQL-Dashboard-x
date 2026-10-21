"""The experiment registry: one JSON line per experiment, appended, never rewritten.

Failed and not-runnable experiments are recorded too, with the reason.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid

from .. import config


def commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "research_lab"], cwd=config.ROOT, capture_output=True,
                               text=True).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except OSError:
        return "unknown"


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]


def record(kind: str, name: str, cfg: dict, status: str, metrics: dict | None = None, note: str = "",
           test_period: str = "", train_cutoff: str = "", path=config.REGISTRY) -> dict:
    from ..data.fetch import dataset_version
    entry = {"id": uuid.uuid4().hex[:12], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "kind": kind, "name": name, "status": status, "source_commit": commit(),
             "dataset_version": dataset_version(), "lab_version": config.LAB_VERSION, "config": cfg,
             "config_hash": config_hash(cfg), "train_cutoff": train_cutoff, "test_period": test_period,
             "metrics": metrics or {}, "note": note}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def read(path=config.REGISTRY) -> list[dict]:
    try:
        return [json.loads(line) for line in open(path) if line.strip()]
    except OSError:
        return []
