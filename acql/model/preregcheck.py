"""The pre-registered tests, read off disk for the Model Lab.

The training ground scores plans written down before their games
(acql/training/prereg.py) and leaves data/training/prereg/latest.json. This
reads that file and lays it out as rows, as challengers.py and pfmcheck.py
do - it imports nothing from the training package (the dashboard must not).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from ..store import data_dir

WHERE = ("training", "prereg", "latest.json")
STALE_S = 9 * 86400
HEADERS = ["Plan", "Written", "Rule", "Games so far", "Against Deadeye", "Could be from", "Reading"]


@dataclass
class Plans:
    made: float = 0.0
    rows: list[list] = field(default_factory=list)
    cases: set[int] = field(default_factory=set)

    def stale(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) - self.made > STALE_S


def read(path=None) -> Plans | None:
    try:
        found = json.loads((path or data_dir().joinpath(*WHERE)).read_text(encoding="utf-8"))
        out = Plans(made=float(found.get("made", 0.0)))
        for plan in found.get("plans", []):
            if "better than" in str(plan.get("call", "")):
                out.cases.add(len(out.rows))
            low, high = plan.get("low"), plan.get("high")
            out.rows.append([
                f"{plan['id']} [{plan.get('fingerprint', '')}]", plan.get("registered", ""), plan.get("rule", ""),
                plan.get("games", 0), f"{plan.get('edge', 0.0):+.4f}",
                "-" if low is None else f"{low:+.4f} to {high:+.4f}", plan.get("call", "")])
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
