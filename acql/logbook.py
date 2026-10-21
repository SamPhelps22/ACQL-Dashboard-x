"""Leave a line in the dashboard's log when something that is allowed to fail did.

Several steps (saving a pick sheet, keeping a forecast file) must not stop the
run when the database refuses them. They used to say nothing at all, so a pick
that quietly failed to save left no trace. `trouble` records it once per kind
per run, in acql-log.txt, and never raises.
"""

from __future__ import annotations

_SEEN: set[tuple[str, str]] = set()


def trouble(where: str, exc: BaseException) -> None:
    """Log `where` failed with `exc`, the first time that exact thing happens in this run."""
    key = (where, f"{type(exc).__name__}: {exc}")
    if key in _SEEN:
        return
    _SEEN.add(key)
    try:
        from .ui.pages.base import write_log
        write_log(f"{where}: {key[1]}")
    except Exception:  # noqa: BLE001 - the log is never the thing that breaks the app
        pass
