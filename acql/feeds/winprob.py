"""ESPN's own live win chance for each game being played (idea #18 of the upgrade book).

The live board's chances come from the score, the time left and the line
before kickoff. That misses who has the ball and where: 20-17 with three
minutes left is a different game when the trailing side is at the 38. ESPN's
game summary carries its own play-by-play win chance, which knows all of
that, so while a game is on this reads the newest one.

Checked on 2026-10-25 (PIT v NO, London, in play): the summary at
site.api.espn.com/.../summary?event=<id> has `winprobability`, a list with
one entry per play, each `homeWinPercentage` (0..1, ESPN's home team) and
`tiePercentage`. Anyone may read it (Access-Control-Allow-Origin: *) and it
is cached for 5 seconds. The whole answer is large (~560 KB, mostly drives),
so it is only asked for games under way, at most once a minute each.

Only the chance of winning the game outright is given. The pool credits
lined games against its own line, so pool/gameday.py turns ESPN's number into
the expected margin that would give it and carries on with its own rules.

Kept in memory and in the store (kind "winprob"), so a hidden window and the
headless runs see the same numbers. Nothing here knows about Qt.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event}"
TIMEOUT = 15
#: Ask about one game no more often than this.
EVERY = 60.0
#: A number older than this is no longer about the game as it stands.
FRESH = 240.0
KIND = "winprob"
#: Games asked about in one round at most; the rest wait for the next.
MOST = 8


def parse(payload: object) -> float | None:
    """The newest home win chance in a summary answer, or None."""
    if not isinstance(payload, dict):
        return None
    points = payload.get("winprobability")
    if not isinstance(points, list):
        return None
    for point in reversed(points):
        if not isinstance(point, dict):
            continue
        value = point.get("homeWinPercentage")
        if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
            return float(value)
    return None


def fetch(event: str, opener=None) -> float | None:
    """ESPN's home win chance for one game now. None when it has none."""
    url = SUMMARY.format(event=str(event).strip())
    request = urllib.request.Request(url, headers={"User-Agent": "ACQL Dashboard"})
    open_ = opener or urllib.request.urlopen
    with open_(request, timeout=TIMEOUT) as response:
        body = response.read()
    # Not kept in the raw archive: each answer is ~560 KB and changes every
    # play, so a Sunday would add hundreds of megabytes for one number each.
    return parse(json.loads(body))


def _kept() -> dict:
    from .. import store
    try:
        found = store.get(KIND, "latest", {}) or {}
    except Exception:  # noqa: BLE001
        return {}
    return found if isinstance(found, dict) else {}


def latest(event: str, *, now: float | None = None, fresh: float = FRESH) -> float | None:
    """ESPN's home win chance for a game, if one was read recently enough."""
    if not event:
        return None
    row = _kept().get(str(event))
    if not isinstance(row, list) or len(row) != 2:
        return None
    at, value = row
    now = time.time() if now is None else now
    try:
        if now - float(at) > fresh:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def refresh(scores, *, now: float | None = None, fetcher=None) -> int:
    """Read ESPN's chance for every game under way that is due a look. Returns how many were read.

    `scores` are results.Score rows (the week as last fetched). Failures are
    quiet: the board simply goes on with its own estimate.
    """
    from .. import store
    get = fetcher or fetch
    now = time.time() if now is None else now
    kept = _kept()
    asked = dict(kept.get("_asked") or {}) if isinstance(kept.get("_asked"), dict) else {}
    live = [s for s in scores or [] if getattr(s, "state", "") == "in" and getattr(s, "event", "")]
    read = 0
    for score in live[:MOST]:
        event = str(score.event)
        last = asked.get(event)
        if last is not None and now - float(last) < EVERY:
            continue
        asked[event] = now
        try:
            value = get(event)
        except (urllib.error.URLError, OSError, ValueError):
            continue
        except Exception:  # noqa: BLE001 - never stop the scores over this
            continue
        if value is not None:
            kept[event] = [now, round(value, 4)]
            read += 1
    # keep the record small: only games looked at in the last day
    kept = {k: v for k, v in kept.items()
            if k == "_asked" or (isinstance(v, list) and len(v) == 2 and now - float(v[0]) < 86400)}
    kept["_asked"] = {k: v for k, v in asked.items() if now - float(v) < 86400}
    try:
        store.put(KIND, "latest", kept)
    except Exception:  # noqa: BLE001
        pass
    return read
