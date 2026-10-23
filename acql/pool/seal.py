"""The lock ceremony (idea #10): each week's card sealed at the deadline with a fingerprint.

Once the week locks, Deadeye's recorded card and the week's frozen snapshot
of what was known are fixed. This takes a short fingerprint of the two -
"W7 · 3f9a" - the first time it is asked for after the deadline and keeps it,
so it can be quoted later and checked: if either record were ever rewritten,
the fingerprint worked out again would no longer match the one kept.

No Qt.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

KIND = "seals"


@dataclass(frozen=True)
class Seal:
    week: int
    code: str          # four hex characters
    at: float          # when it was sealed
    matches: bool      # the records still give the same fingerprint

    @property
    def label(self) -> str:
        return f"W{self.week} · {self.code}"


def fingerprint(year: int, week: int) -> str | None:
    """Four hex characters over Deadeye's recorded card and the frozen snapshot, or None."""
    from ..model import known
    from . import cards
    card = cards.model(week)
    snap = known.kept(year, week)
    if card is None and snap is None:
        return None
    body = {
        "card": None if card is None else {"take": {str(k): v for k, v in sorted(card.take.items())},
                                           "chance": {str(k): v for k, v in sorted(card.chance.items())},
                                           "losers": list(card.losers)},
        "known": None if snap is None else {"frozen": bool(snap.get("frozen")), "games": snap.get("games")},
    }
    text = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:4]


def seal(year: int, week: int, lock: float, now: float | None = None) -> Seal | None:
    """The week's seal once its deadline has passed (made and kept the first time). None before."""
    from .. import store
    now = time.time() if now is None else now
    if now < lock:
        return None
    current = fingerprint(year, week)
    if current is None:
        return None
    key = f"{int(year)}-{int(week)}"
    try:
        kept = store.get(KIND, key, None)
    except Exception:  # noqa: BLE001
        kept = None
    if not isinstance(kept, dict) or not kept.get("code"):
        kept = {"code": current, "at": now}
        try:
            store.put(KIND, key, kept)
        except Exception:  # noqa: BLE001
            pass
    return Seal(week, str(kept["code"]), float(kept.get("at") or now), str(kept["code"]) == current)
