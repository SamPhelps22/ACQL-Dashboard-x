"""How each game's score got where it did: every scoring play, with the time
it happened, from ESPN's play-by-play.

The scoreboard (results.py) says how a game ended. The website's replay of
the week (replay.py) needs the order things happened in across all sixteen
games - which touchdown put whom in front, and when - so once a game is
final its play-by-play is fetched once and its scoring plays kept: the score
after each, the quarter and game clock, the play as ESPN describes it, and
the moment it happened (ESPN's "wallclock"). A finished game never changes,
so nothing is fetched twice; weeks played before this existed are filled in
the same way, a few games at a time.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import results

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
TIMEOUT = 15
#: The most one round may take; the games left wait for the next round.
BUDGET_S = 20
#: Where they're kept: one document a game, "2026-5-atl-gb" (ESPN's away, home).
KIND = "timeline"
META_KIND, META_KEY = "timeline-meta", "last-try"
#: After a round that couldn't reach ESPN, wait this long before the next.
RETRY_S = 15 * 60
#: A game ESPN had no play-by-play for is asked about again after this...
EMPTY_RETRY_S = 24 * 3600
#: ...this many times at most.
EMPTY_TRIES = 3
#: A conversion this soon after a touchdown, by the same side, is one moment.
CONVERSION_S = 240


class TimelineError(Exception):
    """ESPN's play-by-play couldn't be read; the message says why, in words."""


@dataclass(frozen=True)
class Moment:
    """The score just after one scoring play (ESPN's away and home)."""

    at: float | None        # when it happened, seconds since 1970 (None: ESPN didn't say)
    away: int
    home: int
    period: int             # 1-4, 5 for overtime
    clock: str              # the game clock as ESPN shows it, "2:01"
    text: str               # the play, as ESPN describes it

    def row(self) -> list:
        return [self.at, self.away, self.home, self.period, self.clock, self.text]

    @classmethod
    def from_row(cls, row) -> "Moment | None":
        try:
            at, away, home, period, clock, text = row
            return cls(float(at) if at is not None else None, int(away), int(home),
                       int(period or 0), str(clock or ""), str(text or ""))
        except (TypeError, ValueError):
            return None


# ---- reading the play-by-play ---------------------------------------------------
def _sequence(play: dict, fallback: int) -> tuple[int, int]:
    try:
        return int(str(play.get("sequenceNumber"))), fallback
    except (TypeError, ValueError):
        return 10 ** 12, fallback


def _plays(payload: dict) -> list[dict]:
    drives = payload.get("drives") if isinstance(payload.get("drives"), dict) else {}
    from . import items       # a list sent as anything else is no plays, never an error
    out = []
    for drive in items(drives.get("previous")):
        if isinstance(drive, dict):
            out.extend(p for p in items(drive.get("plays")) if isinstance(p, dict))
    current = drives.get("current")
    if isinstance(current, dict):
        seen = {str(p.get("id")) for p in out}
        out.extend(p for p in items(current.get("plays"))
                   if isinstance(p, dict) and str(p.get("id")) not in seen)
    if not out:
        # no drive chart: the list of scoring plays alone (no wallclock on those)
        out = [p for p in items(payload.get("scoringPlays")) if isinstance(p, dict)]
    indexed = sorted(enumerate(out), key=lambda ip: _sequence(ip[1], ip[0]))
    return [p for _, p in indexed]


def _period(play: dict) -> int:
    value = play.get("period")
    if isinstance(value, dict):
        value = value.get("number")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clock(play: dict) -> str:
    value = play.get("clock")
    if isinstance(value, dict):
        value = value.get("displayValue")
    return str(value or "").strip()


def parse(payload: object) -> list[Moment]:
    """Every change of score in a game's play-by-play, in order. A touchdown
    and the kick or two-point try after it are one moment, described by the
    touchdown."""
    if not isinstance(payload, dict):
        return []
    out: list[Moment] = []
    last = (0, 0)
    last_gain: tuple[str, int] = ("", 0)
    for play in _plays(payload):
        away, home = results._points(play.get("awayScore")), results._points(play.get("homeScore"))
        if away is None or home is None or (away, home) == last:
            continue
        side = "away" if away != last[0] else "home"
        gain = (away - last[0]) if side == "away" else (home - last[1])
        at = results._kickoff(play.get("wallclock"))
        moment = Moment(at, away, home, _period(play), _clock(play),
                        " ".join(str(play.get("text") or "").split())[:180])
        joined = (out and last_gain[0] == side and last_gain[1] >= 6 and gain in (1, 2)
                  and (at is None or out[-1].at is None or 0 <= at - out[-1].at <= CONVERSION_S))
        if joined:
            prev = out[-1]
            out[-1] = Moment(prev.at, away, home, prev.period, prev.clock, prev.text)
            last_gain = ("", 0)
        else:
            out.append(moment)
            last_gain = (side, gain)
        last = (away, home)
    return out


def ended(payload: object) -> float | None:
    """When the game's last play happened (its end, near enough)."""
    if not isinstance(payload, dict):
        return None
    times = [results._kickoff(p.get("wallclock")) for p in _plays(payload)]
    times = [t for t in times if t is not None]
    return max(times) if times else None


def fetch(event: str, opener=None) -> dict:
    """One game's play-by-play from ESPN."""
    request = urllib.request.Request(
        f"{SUMMARY}?event={urllib.parse.quote(str(event))}",
        headers={"User-Agent": "ACQL-Dashboard", "Accept": "application/json"},
    )
    open_url = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    try:
        with open_url(request) as response:
            raw = response.read()
        from .. import rawarchive
        rawarchive.keep("timeline", raw, f"event {event}")
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise TimelineError(f"ESPN's play-by-play answered with an error ({exc.code})") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise TimelineError("ESPN's play-by-play can't be reached - is the internet connected?") from exc
    except ValueError as exc:
        raise TimelineError("ESPN sent back something that isn't a play-by-play") from exc


# ---- keeping them ----------------------------------------------------------------
def _key(year: int, week: int, away: str, home: str) -> str:
    return f"{int(year)}-{int(week)}-{away}-{home}"


def _entry(year: int, week: int, away: str, home: str) -> dict | None:
    from .. import store
    try:
        raw = store.get(KIND, _key(year, week, away, home), None)
    except store.StoreError:
        return None
    return raw if isinstance(raw, dict) else None


@dataclass(frozen=True)
class GameTimeline:
    moments: list[Moment]
    end: float | None       # the last play's time


def load(year: int, week: int, away: str, home: str) -> GameTimeline | None:
    """A game's kept timeline (ESPN's away and home), None when there's none."""
    entry = _entry(year, week, away, home)
    if not entry or not entry.get("moments"):
        return None
    moments = [m for m in (Moment.from_row(r) for r in entry.get("moments") or []) if m is not None]
    end = entry.get("end")
    return GameTimeline(moments, float(end) if isinstance(end, (int, float)) else None) if moments else None


def save(year: int, week: int, away: str, home: str, moments: list[Moment],
         end: float | None, *, event: str = "", now: float | None = None) -> None:
    from .. import store
    before = _entry(year, week, away, home) or {}
    try:
        store.put(KIND, _key(year, week, away, home), {
            "event": event,
            "at": time.time() if now is None else now,
            "tries": int(before.get("tries") or 0) + (0 if moments else 1),
            "end": end,
            "moments": [m.row() for m in moments],
        })
    except store.StoreError:
        pass


def _wanted(entry: dict | None, now: float) -> bool:
    if entry is None:
        return True
    if entry.get("moments"):
        return False
    if int(entry.get("tries") or 0) >= EMPTY_TRIES:
        return False
    return now - float(entry.get("at") or 0) >= EMPTY_RETRY_S


#: Weeks over with every game's timeline kept (or given up on): not looked
#: at again this run - the window asks every minute.
_DONE: set[tuple[int, int]] = set()


def missing(year: int, weeks, *, now: float | None = None) -> list[tuple[int, results.Score]]:
    """The finished games of these weeks with no timeline kept yet, newest week first."""
    now = time.time() if now is None else now
    out = []
    for week in sorted({int(w) for w in weeks}, reverse=True):
        if (year, week) in _DONE:
            continue
        kept = results.load(year, week)
        entries = {(s.away, s.home): _entry(year, week, s.away, s.home) for s in kept if s.final}
        found = [(week, s) for s in kept if s.final and _wanted(entries[(s.away, s.home)], now)]
        waiting = any(e is not None and not e.get("moments") and int(e.get("tries") or 0) < EMPTY_TRIES
                      for e in entries.values())
        if kept and not found and not waiting and all(s.final or s.called_off for s in kept):
            _DONE.add((year, week))
        out.extend(found)
    return out


def _last_try() -> float:
    from .. import store
    try:
        value = store.get(META_KIND, META_KEY, 0)
    except store.StoreError:
        return 0.0
    return float(value) if isinstance(value, (int, float)) else 0.0


def _note_try(at: float | None) -> None:
    from .. import store
    try:
        if at is None:
            store.delete(META_KIND, META_KEY)
        else:
            store.put(META_KIND, META_KEY, at)
    except store.StoreError:
        pass


def due(year: int, weeks, *, now: float | None = None) -> bool:
    """Whether a round is worth starting: a finished game without its
    timeline, and ESPN not found unreachable in the last few minutes."""
    now = time.time() if now is None else now
    if not year or now - _last_try() < RETRY_S:
        return False
    return bool(missing(year, weeks, now=now))


def refresh(year: int, weeks, *, now: float | None = None, board=None, summary=None,
            budget: float = BUDGET_S) -> tuple[int, list[str]]:
    """Fetch the timelines of finished games that haven't one, as many as
    the budget allows. Returns (how many were kept, what went wrong)."""
    moment = time.time() if now is None else now
    get_board = board or results.fetch
    get_summary = summary or fetch
    todo = missing(year, weeks, now=moment)
    kept, problems = 0, []
    started = time.monotonic()
    asked_board: set[int] = set()
    for week, score in todo:
        if kept and time.monotonic() - started > budget:
            break
        event = score.event
        if not event and week not in asked_board:
            # kept before game ids were: the week's scoreboard once, for its ids
            asked_board.add(week)
            try:
                results.save(year, week, get_board(year, week), moment)
            except Exception as exc:  # noqa: BLE001 - said, and tried again later
                problems.append(f"Play-by-play for week {week}: {exc}")
                _note_try(moment)
                break
            found, _ = results.find(results.load(year, week), score.away, score.home)
            event = found.event if found is not None else ""
        if not event:
            continue
        try:
            payload = get_summary(event)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Play-by-play for week {week}: {exc}")
            _note_try(moment)
            break
        save(year, week, score.away, score.home, parse(payload), ended(payload), event=event, now=moment)
        kept += 1
    if kept and not problems:
        _note_try(None)
    return kept, problems


# every call kept as a success or a failure for timeline (sourcehealth.py, #41)
from .. import sourcehealth as _sourcehealth  # noqa: E402
fetch = _sourcehealth.watched("timeline", fetch)
