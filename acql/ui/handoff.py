"""Answers worked out ahead of time, handed to a page once.

The warm-up (workers.py) works out a page's slowest sums off the window's
thread after a load. A sum that keeps no answer of its own is handed over
here: the page takes it on its next refresh - once, and only if it was
worked out from the very season the page is showing - and works everything
out afresh after that, exactly as it always did. So a warm-up can make the
first open quicker but can never leave a page showing an old answer.
"""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_READY: dict[str, tuple[object, object]] = {}


def give(name: str, season, value) -> None:
    """Keep `value`, worked out from `season`, for the page that asks for `name`."""
    with _LOCK:
        _READY[name] = (season, value)


def take(name: str, season, make):
    """The answer kept for `name` if it came from this same season (used once),
    otherwise `make()`."""
    with _LOCK:
        held = _READY.pop(name, None)
    if held is not None and held[0] is season:
        return held[1]
    return make()


def forget() -> None:
    with _LOCK:
        _READY.clear()
