"""The commissioner's rulings on weeks that don't add up (idea #57).

reconcile.py finds weeks where a coach's official total isn't what their
picks score under the coded rules. Only the commissioner can say which is
right, and until it is written down the question keeps coming back and the
site's replay leaves the week out. This keeps one ruling per week:

    official   the pool's official totals stand (the replay ends on them)
    recount    the recount stands (the official sheet had a slip)

with the date it was ruled and a note. Nothing here changes a score.
"""

from __future__ import annotations

import time

KIND = "rulings"
CHOICES = {"official": "Official totals stand", "recount": "The recount stands"}


def _key(year: int, week: int) -> str:
    return f"{int(year)}-{int(week)}"


def get(year: int, week: int) -> dict | None:
    from .. import store
    try:
        found = store.get(KIND, _key(year, week), None)
    except Exception:  # noqa: BLE001
        return None
    return found if isinstance(found, dict) and found.get("ruling") in CHOICES else None


def put(year: int, week: int, ruling: str, note: str = "", now: float | None = None) -> None:
    """Write a ruling down ("" clears it)."""
    from .. import store
    if not ruling:
        store.put(KIND, _key(year, week), None)
        return
    if ruling not in CHOICES:
        raise ValueError(f"unknown ruling {ruling!r}")
    store.put(KIND, _key(year, week), {"ruling": ruling, "note": str(note or ""),
                                       "at": time.time() if now is None else now})


def words(found: dict | None) -> str:
    if not found:
        return "Not ruled yet"
    day = time.strftime("%Y-%m-%d", time.localtime(float(found.get("at") or 0)))
    return f"{CHOICES[found['ruling']]} (ruled {day})" + (f" - {found['note']}" if found.get("note") else "")
