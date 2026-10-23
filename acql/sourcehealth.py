"""How each data source has behaved lately (idea #41).

Readiness says how fresh each source is now. This keeps the history behind
it: every fetch from each source - ESPN's scores and play-by-play, the Odds
API, the injury report, the predictions file, PFM, the weather, GitHub
(publishing) and email - as a success or a failure with how long it took,
for the last 30 days. A source that has been failing on and off shows it
before it fails on the day that matters.

`watched(name, fn)` wraps a fetch function; recording never raises. No Qt.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass

KIND = "source-health"
DAYS = 30
#: Names as Readiness shows them.
NAMES = {"espn-scores": "ESPN scores", "timeline": "ESPN play-by-play", "odds": "The Odds API", "oddspapi": "OddsPapi (backup lines)",
         "injuries": "Injury report", "predictions": "Predictions file", "pfm": "PFM ratings",
         "weather": "Weather", "github": "GitHub (website)", "email": "Email"}


def record(source: str, ok: bool, seconds: float, note: str = "", now: float | None = None) -> None:
    from . import store
    now = time.time() if now is None else now
    try:
        kept = store.get(KIND, source, []) or []
        kept = [r for r in (kept if isinstance(kept, list) else []) if now - float(r[0]) < DAYS * 86400]
        kept.append([round(now, 1), bool(ok), round(float(seconds), 2), str(note)[:120]])
        store.put(KIND, source, kept[-2000:])
    except Exception:  # noqa: BLE001 - keeping the record never breaks a fetch
        pass


def watched(source: str, fn):
    """`fn`, with each call recorded as a success or a failure for `source`."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        if kwargs.get("opener") is not None or kwargs.get("smtp_factory") is not None:
            return fn(*args, **kwargs)      # a test's stand-in connection: not the source's record
        started = time.perf_counter()
        try:
            out = fn(*args, **kwargs)
        except Exception as exc:
            record(source, False, time.perf_counter() - started, f"{type(exc).__name__}: {exc}")
            raise
        record(source, True, time.perf_counter() - started)
        return out
    run.__wrapped_source__ = source
    return run


@dataclass(frozen=True)
class Health:
    source: str
    calls: int
    good: int
    last_good: float | None
    last_bad: float | None
    last_note: str
    median_s: float | None
    days: str                  # one mark a day, oldest first: ✓ all good, ✕ any failure, · no call

    @property
    def name(self) -> str:
        return NAMES.get(self.source, self.source)


def health(source: str, now: float | None = None, days: int = 14) -> Health | None:
    from . import store
    now = time.time() if now is None else now
    try:
        kept = store.get(KIND, source, []) or []
    except Exception:  # noqa: BLE001
        return None
    rows = [r for r in kept if isinstance(r, list) and len(r) >= 3 and now - float(r[0]) < DAYS * 86400]
    if not rows:
        return None
    good = [r for r in rows if r[1]]
    bad = [r for r in rows if not r[1]]
    times = sorted(float(r[2]) for r in good)
    marks = []
    for d in range(days - 1, -1, -1):
        day = [r for r in rows if d * 86400 <= now - float(r[0]) < (d + 1) * 86400]
        marks.append("·" if not day else "✕" if any(not r[1] for r in day) else "✓")
    return Health(source, len(rows), len(good), float(good[-1][0]) if good else None,
                  float(bad[-1][0]) if bad else None, str(bad[-1][3]) if bad and len(bad[-1]) > 3 else "",
                  times[len(times) // 2] if times else None, "".join(marks))


def every(now: float | None = None) -> list[Health]:
    return [h for h in (health(s, now) for s in NAMES) if h is not None]
