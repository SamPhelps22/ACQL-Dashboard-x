"""What comes from outside: lines, results, schedules, injuries and weather."""

#: What reading one part of an answer raises when a source writes it in a shape
#: nobody expected: a string where a record should be, a number for a list.
SHAPE_ERRORS = (AttributeError, IndexError, KeyError, TypeError, ValueError)


def items(value: object) -> list:
    """A list a source sent, or no items when it sent something else in its place."""
    return value if isinstance(value, list) else []


def keep_readable(items: object, read, where: str = "") -> list:
    """`read` applied to each item of a list a source sent, keeping what it returns
    (None: not one to keep). An item in a shape nobody expected is left out on its
    own - its error is written to the log once, under `where` - instead of failing
    every other item in the same answer. Anything but a list is no items at all."""
    out, skipped, first = [], 0, None
    for item in items if isinstance(items, list) else []:
        try:
            got = read(item)
        except SHAPE_ERRORS as exc:
            skipped += 1
            first = first or exc
            if where:
                from .. import logbook
                logbook.trouble(f"{where}: an item in an unexpected shape was left out", exc)
            continue
        if got is not None:
            out.append(got)
    if skipped and where:
        note_skipped(where, skipped, first)
    return out


#: Where the last items each source sent in a shape nobody expected are kept, for Readiness.
SKIPS_KIND = "feed-skips"


def note_skipped(where: str, count: int, exc: BaseException | None, now: float | None = None) -> None:
    """Keep that `count` items from `where` were left out; never raises."""
    import time
    try:
        from .. import store
        now = time.time() if now is None else now
        kept = store.get(SKIPS_KIND, where, {}) or {}
        if isinstance(kept, dict) and now - float(kept.get("at", 0)) < 60:
            count += int(kept.get("count", 0))      # the same answer, read in parts (a team, then its players)
        why = f"{type(exc).__name__}: {exc}" if exc is not None else ""
        store.put(SKIPS_KIND, where, {"at": now, "count": int(count), "why": why[:160]})
    except Exception:  # noqa: BLE001 - keeping the note never breaks a fetch
        pass


def skipped_lately(within: float, now: float | None = None) -> list[tuple[str, dict]]:
    """[(source, {"at", "count", "why"})] for skips in the last `within` seconds, newest first."""
    import time
    try:
        from .. import store
        found = store.items(SKIPS_KIND) or {}
    except Exception:  # noqa: BLE001
        return []
    now = time.time() if now is None else now
    out = [(k, v) for k, v in found.items()
           if isinstance(v, dict) and now - float(v.get("at", 0) or 0) <= within]
    return sorted(out, key=lambda kv: -float(kv[1].get("at", 0)))
