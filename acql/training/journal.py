"""The lab notebook: every run written down once, and what to try next.

Each training run adds one line to data/training/journal.jsonl - never edits
or removes one. A line says what was run (the training rules' version, the
code's git commit, a fingerprint of the data it was run on), what each
challenger scored on its three cards, and the status it was given. Two runs
on the same fingerprint and commit should say the same thing; if they do not,
something is not reproducible, and the queue says so.

From the whole notebook - not just the newest run - comes the queue of what
to look at next (hypotheses.json). The rules are deliberately few, and they
look at evidence across runs so one noisy week does not start a hunt:

  * retired in the last RETIRE_RUNS runs in a row  -> stop spending runs on it
  * ahead on probability but not clear of zero     -> wait for more weeks; do not retune
                                                      on the held-back seasons
  * better chances, fewer pool picks (or the reverse) -> look at the games where it
                                                      and the rule in use took different sides
  * less honest chances than the rule in use       -> try recalibrating its chance curve
  * eligible                                        -> owner review; a switch is theirs

A hypothesis already settled ("stop") is not raised again. Nothing here
changes a pick. No Qt here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import pandas as pd

from . import VERSION, scorecards

FILE = "journal.jsonl"
QUEUE = "hypotheses.json"
RETIRE_RUNS = 2


def code_version() -> str:
    """The git commit the run was made from, '-dirty' if files were changed; '' outside git."""
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True,
                             timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "acql"], cwd=root, capture_output=True,
                               text=True, timeout=10).stdout.strip()
        return f"{sha}-dirty" if sha and dirty else sha
    except (OSError, subprocess.SubprocessError):
        return ""


def fingerprint(games: pd.DataFrame) -> str:
    """A short hash of which games were scored and how they came out."""
    if games is None or games.empty:
        return ""
    cols = [c for c in ("game", "order", "actual", "credited") if c in games.columns]
    body = games[cols].to_csv(index=False).encode()
    return hashlib.sha1(body).hexdigest()[:12]


def entry(cards: dict, games: pd.DataFrame | None, now: float | None = None) -> dict:
    def brief(card: dict) -> dict:
        return {"status": card["status"], "prob_edge": card["probability"]["edge"],
                "prob_low": card["probability"]["low"], "prob_high": card["probability"]["high"],
                "market_edge": (card.get("market") or {}).get("edge"),
                "pool_diff_per_week": card["pool"].get("diff_per_week"),
                "pool_low": card["pool"].get("low"), "pool_high": card["pool"].get("high"),
                "calibration": card["calibration"], "in_use_calibration": card["in_use_calibration"],
                "failed_gates": [g for g, ok in card["gates"].items() if not ok]}
    return {"made": time.time() if now is None else now, "training": VERSION, "code": code_version(),
            "data": fingerprint(games), "setting": cards.get("setting"), "games": cards.get("games", 0),
            "weeks": cards.get("weeks", 0), "sealed": cards.get("sealed"), "champion": cards.get("champion"),
            "recommendation": cards.get("recommendation"),
            "challengers": {n: brief(c) for n, c in cards.get("challengers", {}).items()}}


def read(path: Path) -> list[dict]:
    """Every line of the notebook that can be read; a damaged line is skipped, never fatal."""
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                found = json.loads(line)
                if isinstance(found, dict):
                    out.append(found)
            except ValueError:
                continue
    except OSError:
        pass
    return out


def append(path: Path, line: dict) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, default=float) + "\n")


def hypotheses(runs: list[dict]) -> list[dict]:
    """What to look at next, from the whole notebook."""
    if not runs:
        return []
    out = []
    last = runs[-1]
    for name, now in last.get("challengers", {}).items():
        history = [r["challengers"][name]["status"] for r in runs if name in r.get("challengers", {})]
        if len(history) >= RETIRE_RUNS and all(s == scorecards.RETIRED for s in history[-RETIRE_RUNS:]):
            out.append({"model": name, "kind": "stop", "says": f"clearly worse in the last {RETIRE_RUNS} runs: "
                        "stop spending runs on it unless its recipe changes"})
            continue
        if now["status"] == scorecards.ELIGIBLE:
            out.append({"model": name, "kind": "review", "says": "passed every gate - worth the owner's review; "
                        "the switch is theirs"})
        edge, low = now.get("prob_edge") or 0.0, now.get("prob_low")
        if edge > 0 and (low is None or low <= 0):
            out.append({"model": name, "kind": "wait", "says": "ahead on probability but not clear of zero: "
                        "let more weeks come in; do not retune it on the held-back seasons"})
        pool = now.get("pool_diff_per_week")
        if pool is not None and edge and (pool < 0 < edge or edge < 0 < pool) and abs(pool) >= 0.1:
            out.append({"model": name, "kind": "disagree", "says": "its chances and its pool picks point "
                        "different ways: look at the games it took a different side of"})
        if now.get("calibration", 0) > now.get("in_use_calibration", 0) + scorecards.CALIBRATION_SLACK \
                and now["status"] != scorecards.RETIRED:
            out.append({"model": name, "kind": "recalibrate", "says": "its chances are less honest than the "
                        "rule in use: try its margins through a recalibrated chance curve"})
    same = [r for r in runs[:-1] if r.get("data") and r.get("data") == last.get("data")
            and r.get("code") == last.get("code") and r.get("training") == last.get("training")]
    if same:
        before = same[-1].get("challengers", {})
        moved = [n for n, c in last.get("challengers", {}).items()
                 if n in before and before[n].get("status") != c.get("status")]
        if moved:
            out.append({"model": ", ".join(moved), "kind": "reproducibility",
                        "says": "same data and code as an earlier run, different status: something is not "
                                "reproducible - find it before trusting either run"})
    return out


def record(cards: dict, games: pd.DataFrame | None, folder: Path, root: Path, now: float | None = None) -> list[dict]:
    """Add this run to the notebook (root/journal.jsonl) and write the queue into the run's folder."""
    path = Path(root) / FILE
    append(path, entry(cards, games, now))
    queue = hypotheses(read(path))
    (Path(folder) / QUEUE).write_text(json.dumps(queue, indent=1), encoding="utf-8")
    return queue
