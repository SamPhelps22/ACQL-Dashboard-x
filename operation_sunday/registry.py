"""Experiment records, model artifacts and the approved-model pointer.

    <state>/experiments/<experiment_id>.json   one per training/selection run
    <state>/artifacts/<model>/<version>.json   fitted parameters (never production code)
    <state>/approved.json                      current approved model + full history

Promotion appends to the history; rollback appends a rollback event that
points back at the previous approved entry. Nothing is ever deleted, so the
history of what was official, and why, is always complete.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

from .config import REPO_DIR
from .tz import iso, utc_now


def code_revision() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_DIR, capture_output=True, text=True,
                             timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "operation_sunday"], cwd=REPO_DIR,
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return (rev or "unknown") + ("+dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def _write_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


class Registry:
    def __init__(self, state: Path):
        self.state = Path(state)
        self.approved_path = self.state / "approved.json"

    # ---- artifacts ------------------------------------------------------
    def save_artifact(self, model_name: str, config: dict, state: dict, training_cutoff: str,
                      dataset_version: str) -> str:
        body = {"model": model_name, "config": config, "state": state, "training_cutoff": training_cutoff,
                "dataset_version": dataset_version}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:12]
        version = f"{model_name}@{digest}"
        path = self.state / "artifacts" / model_name / f"{digest}.json"
        if not path.exists():
            _write_atomic(path, {**body, "version": version, "saved_at": iso(utc_now())})
        return version

    def load_artifact(self, version: str) -> dict | None:
        name, digest = version.split("@", 1)
        p = self.state / "artifacts" / name / f"{digest}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    # ---- experiments ----------------------------------------------------
    def record_experiment(self, record: dict) -> str:
        exp_id = record.get("experiment_id") or f"exp-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        record = {**record, "experiment_id": exp_id, "code_revision": record.get("code_revision") or code_revision(),
                  "recorded_at": iso(utc_now())}
        _write_atomic(self.state / "experiments" / f"{exp_id}.json", record)
        return exp_id

    def experiments(self) -> list[dict]:
        d = self.state / "experiments"
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []

    # ---- approval -------------------------------------------------------
    def _approved(self) -> dict:
        if self.approved_path.exists():
            return json.loads(self.approved_path.read_text(encoding="utf-8"))
        return {"current": None, "history": []}

    def approved(self) -> dict | None:
        return self._approved()["current"]

    def history(self) -> list[dict]:
        return self._approved()["history"]

    def promote(self, model_name: str, experiment_id: str, reason: str) -> dict:
        data = self._approved()
        entry = {"model": model_name, "experiment_id": experiment_id, "reason": reason,
                 "approved_at": iso(utc_now()), "event": "promote"}
        data["history"].append(entry)
        data["current"] = entry
        _write_atomic(self.approved_path, data)
        return entry

    def rollback(self, reason: str) -> dict | None:
        """Back to the approved model before the current one."""
        data = self._approved()
        promos = [h for h in data["history"] if h["event"] == "promote"]
        cur = data["current"]
        if cur is None:
            return None
        idx = max(i for i, h in enumerate(promos) if h["experiment_id"] == cur.get("experiment_id")
                  and h["model"] == cur["model"]) if cur.get("event") == "promote" else None
        if cur.get("event") == "rollback":
            idx = cur["restored_index"]
        if idx is None or idx == 0:
            target = None
        else:
            target = promos[idx - 1]
        entry = {"event": "rollback", "reason": reason, "at": iso(utc_now()),
                 "from": cur["model"], "model": target["model"] if target else None,
                 "experiment_id": target["experiment_id"] if target else None,
                 "restored_index": (idx - 1) if target else None}
        data["history"].append(entry)
        data["current"] = entry if target else None
        _write_atomic(self.approved_path, data)
        return entry
