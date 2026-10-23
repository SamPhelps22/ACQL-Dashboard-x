"""What changed between two copies of a week's pick sheet (idea #43).

The commissioner sometimes sends a sheet again: a late card added, a pick
corrected, a name fixed. The new copy silently replaced the old one, so a
changed pick could go unnoticed. Now, whenever a sheet for the same week
replaces one that already had picks, the differences are written down -
coach by coach - and Data & Update lists them.

No Qt.
"""

from __future__ import annotations

import time

KIND = "pick-changes"
#: Change records kept per week.
KEEP = 20


def _plain(name: str) -> str:
    return " ".join(str(name or "").split()).casefold()


def diff(old, new) -> list[str]:
    """Each difference between two WeekPicks for the same week, in words."""
    from ..model.predictions import team_code
    out = []
    old_names = {_plain(n): n for n in old.coaches}
    new_names = {_plain(n): n for n in new.coaches}
    for key in sorted(set(new_names) - set(old_names)):
        out.append(f"{new_names[key]}: card added")
    for key in sorted(set(old_names) - set(new_names)):
        out.append(f"{old_names[key]}: card removed")
    by_pair = {frozenset((team_code(g.away), team_code(g.home))): g for g in old.games}
    for g in new.games:
        before = by_pair.get(frozenset((team_code(g.away), team_code(g.home))))
        if before is None:
            out.append(f"{g.away} @ {g.home}: game added")
            continue
        was = {_plain(n): p for n, p in before.picks.items()}
        for name, pick in sorted(g.picks.items()):
            key = _plain(name)
            if key in old_names and key in was and team_code(was[key]) != team_code(pick):
                out.append(f"{name}: {g.away} @ {g.home} changed from {was[key] or 'blank'} to {pick or 'blank'}")
    for kind, before, after in (("Big Losers", old.losers, new.losers), ("suicide pick", old.suicide, new.suicide)):
        was = {_plain(n): v for n, v in (before or {}).items()}
        for name, value in sorted((after or {}).items()):
            key = _plain(name)
            if key in old_names and key in was and was[key] != value:
                out.append(f"{name}: {kind} changed from {_words(was[key])} to {_words(value)}")
    return out


def _words(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v) or "none"
    return str(value or "none")


def note(week: int, old, new, source: str = "", now: float | None = None) -> list[str]:
    """Write down what changed when `new` replaces `old` (both WeekPicks). The changes."""
    from .. import store
    if old is None or not old.coaches:
        return []
    found = diff(old, new)
    if not found:
        return []
    try:
        kept = store.get(KIND, str(week), []) or []
        kept = (kept if isinstance(kept, list) else [])[-(KEEP - 1):]
        kept.append({"at": time.time() if now is None else now, "source": source, "changes": found})
        store.put(KIND, str(week), kept)
    except Exception:  # noqa: BLE001 - the sheet is kept either way
        pass
    return found


def recent(weeks, days: float = 14, now: float | None = None) -> list[tuple[int, float, str, list[str]]]:
    """(week, when, source, changes) for change records in the last few days, newest first."""
    from .. import store
    now = time.time() if now is None else now
    out = []
    for week in weeks:
        try:
            kept = store.get(KIND, str(week), []) or []
        except Exception:  # noqa: BLE001
            kept = []
        for row in kept if isinstance(kept, list) else []:
            at = float(row.get("at") or 0)
            if now - at <= days * 86400:
                out.append((int(week), at, str(row.get("source") or ""), list(row.get("changes") or [])))
    return sorted(out, key=lambda r: -r[1])
