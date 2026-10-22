"""The live week as the screens show it: what changed, what is next, how fresh.

Display only. Nothing here prices a game, credits a pick or ranks a coach -
those stay with gameday.py and the pool's own rules. This module takes what
they already worked out and answers the questions a scoreboard has to answer
honestly:

* the next kickoff, from the kickoff times the scoreboard gave - never a
  guessed one, and never a countdown below zero;
* the slate's counts (games, on now, final, still to play, postponed), each
  game counted once;
* which scores really changed since the last good look - not on the first
  look, not on a look that failed, not twice for the same look;
* which coaches moved in the standings or gained points since the last
  accepted standings;
* how fresh each feed is: the last good look, the last try, and whether the
  data on screen is stale or the last try failed.

The website follows the same rules in its own script (pool_page.html); the
thresholds both read are in tokens.FRESHNESS.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..ui import tokens

# ---- kickoff and the countdown -------------------------------------------------------


@dataclass(frozen=True)
class Kickoff:
    at: float                        # seconds since 1970, UTC, as the scoreboard gave it
    indices: tuple[int, ...]         # every game starting then, in the week's order


def _kick(st) -> float | None:
    at = getattr(st, "kickoff", None)
    return float(at) if isinstance(at, (int, float)) and at > 0 else None


def next_kickoff(states, now: float | None = None) -> Kickoff | None:
    """The next game still to start: a game not yet on (postponed ones are
    left out), with a kickoff time from the scoreboard that is still ahead.

    A game past its kickoff time that the scoreboard still has as not started
    is "kicking off" (see `kicking_off`), not a countdown below zero. Games
    sharing the earliest time are all named."""
    now = time.time() if now is None else now
    ahead = [(at, st.index) for st in states
             if st.state == "pre" and (at := _kick(st)) is not None and at > now]
    if not ahead:
        return None
    first = min(at for at, _ in ahead)
    return Kickoff(first, tuple(sorted(i for at, i in ahead if at == first)))


def kicking_off(states, now: float | None = None) -> list[int]:
    """Games whose kickoff time has come while the scoreboard still has them
    as not started - waiting on the feed, not a time to count down to."""
    now = time.time() if now is None else now
    return sorted(st.index for st in states if st.state == "pre" and (at := _kick(st)) is not None and at <= now)


def countdown_parts(seconds: float) -> tuple[int, int, int, int]:
    """(days, hours, minutes, seconds), never below zero."""
    left = max(0, int(seconds))
    days, left = divmod(left, 86400)
    hours, left = divmod(left, 3600)
    minutes, secs = divmod(left, 60)
    return days, hours, minutes, secs


def countdown_text(seconds: float) -> str:
    """"2d 03:14:05", "03:14:05", "14:05" - zero-padded so the digits hold still."""
    days, hours, minutes, secs = countdown_parts(seconds)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


#: US Eastern: the NFL's own clock, and the one the pool talks in.
def _eastern_offset(utc: datetime) -> timedelta:
    """EDT from the second Sunday of March 2:00 local to the first Sunday of
    November 2:00 local; EST otherwise (the US rule since 2007). Worked out
    here so the answer never depends on the computer's own zone setting."""
    year = utc.year
    march = datetime(year, 3, 8, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7)              # second Sunday of March
    november = datetime(year, 11, 1, tzinfo=timezone.utc)
    end = november + timedelta(days=(6 - november.weekday()) % 7)          # first Sunday of November
    starts = start + timedelta(hours=7)        # 2:00 EST is 07:00 UTC
    ends = end + timedelta(hours=6)            # 2:00 EDT is 06:00 UTC
    return timedelta(hours=-4) if starts <= utc < ends else timedelta(hours=-5)


def eastern(at: float) -> tuple[datetime, str]:
    """A moment as US Eastern wall time, with "EDT" or "EST"."""
    utc = datetime.fromtimestamp(at, tz=timezone.utc)
    offset = _eastern_offset(utc)
    return (utc + offset).replace(tzinfo=None), "EDT" if offset == timedelta(hours=-4) else "EST"


def clock_et(at: float, seconds: bool = False) -> str:
    """"3:42 PM ET" (or "3:42:15 PM ET") - the actual stored moment, Eastern."""
    when, _zone = eastern(at)
    hour = when.hour % 12 or 12
    tail = f":{when.second:02d}" if seconds else ""
    return f"{hour}:{when.minute:02d}{tail} {'AM' if when.hour < 12 else 'PM'} ET"


def kickoff_et(at: float) -> str:
    """"Sun 1:00 PM ET" - the day and the time, Eastern."""
    when, _zone = eastern(at)
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    return f"{days[when.weekday()]} {clock_et(at)}"


# ---- the slate ---------------------------------------------------------------------


@dataclass(frozen=True)
class Slate:
    """A week's games by where they stand. Every game is counted once, by its
    index on the pick sheet; `total` counts the games on the slate, including
    postponed ones, which are in none of the other counts but `postponed`."""

    week: int
    total: int
    live: int
    final: int
    upcoming: int        # not started, not postponed
    postponed: int
    untimed: int         # still to play with no kickoff time from the scoreboard

    @property
    def over(self) -> bool:
        return self.total > 0 and self.live == 0 and self.upcoming == 0

    def text(self) -> str:
        """"16 games · 3 live · 5 final · 8 to play" (postponed when there are any)."""
        if not self.total:
            return "No games"
        bits = [f"{self.total} game{'s' if self.total != 1 else ''}"]
        if self.live:
            bits.append(f"{self.live} live")
        bits.append(f"{self.final} final")
        if self.upcoming:
            bits.append(f"{self.upcoming} to play")
        if self.postponed:
            bits.append(f"{self.postponed} postponed")
        return " · ".join(bits)


def slate(week: int, states) -> Slate:
    seen: dict[int, object] = {}
    for st in states:
        seen.setdefault(st.index, st)          # a game listed twice counts once
    games = list(seen.values())
    count = {k: sum(1 for st in games if st.state == k) for k in ("pre", "in", "final", "off")}
    untimed = sum(1 for st in games if st.state == "pre" and _kick(st) is None)
    return Slate(week, len(games), count["in"], count["final"], count["pre"], count["off"], untimed)


# ---- what really changed --------------------------------------------------------------


def _valid_score(value) -> bool:
    return (isinstance(value, tuple) and len(value) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in value))


class ScoreWatch:
    """Which games' scores changed since the last accepted look.

    The first accepted look sets the baseline and changes nothing. A score
    that is missing or malformed in a look is not a change, and the baseline
    keeps the last good value for it. The same look handed in twice (same
    `token`) changes nothing the second time. Hand in only looks that
    succeeded; a failed look is never handed in."""

    def __init__(self) -> None:
        self._base: dict | None = None
        self._token = None

    @property
    def started(self) -> bool:
        return self._base is not None

    def accept(self, scores: dict, token=None) -> set:
        """`scores` maps a game key to (home points, away points) or None."""
        if token is not None and token == self._token:
            return set()
        self._token = token
        clean = {k: v for k, v in scores.items() if _valid_score(v)}
        if self._base is None:
            self._base = clean
            return set()
        changed = {k for k, v in clean.items() if k in self._base and self._base[k] != v}
        self._base = {**self._base, **clean}
        return changed


class StateWatch:
    """Which keys' values changed since the last accepted look - a card going
    from upcoming to live, live to final, fresh to stale. The first look sets
    the baseline; keys new to a look are not changes."""

    def __init__(self) -> None:
        self._base: dict | None = None

    def accept(self, values: dict) -> dict:
        """{key: (before, now)} for every key whose value changed."""
        if self._base is None:
            self._base = dict(values)
            return {}
        out = {k: (self._base[k], v) for k, v in values.items() if k in self._base and self._base[k] != v}
        self._base.update(values)
        return out


@dataclass(frozen=True)
class Movement:
    moved: dict = field(default_factory=dict)      # key -> (place before, place now)
    points: dict = field(default_factory=dict)     # key -> (points before, points now)

    @property
    def gained(self) -> dict:
        """Only the rises: a correction down is shown as it is, not as a gain."""
        return {k: v for k, v in self.points.items() if v[1] > v[0]}

    def __bool__(self) -> bool:
        return bool(self.moved or self.points)


class StandingsWatch:
    """Places and points that changed since the last accepted standings.

    The standings themselves - the order, the ties - come from the pool's own
    rules (gameday.board); this only compares one accepted table with the
    next. Rows with no key or no points are left out, never ranked here."""

    def __init__(self) -> None:
        self._base: dict | None = None
        self._token = None

    def accept(self, rows, token=None) -> Movement:
        """`rows`: (key, place, points) in the standings' own order."""
        if token is not None and token == self._token:
            return Movement()
        self._token = token
        now = {}
        for key, place, points in rows:
            if key and isinstance(points, int) and isinstance(place, int):
                now[key] = (place, points)
        if self._base is None:
            self._base = now
            return Movement()
        moved = {k: (self._base[k][0], v[0]) for k, v in now.items() if k in self._base and self._base[k][0] != v[0]}
        points = {k: (self._base[k][1], v[1]) for k, v in now.items() if k in self._base and self._base[k][1] != v[1]}
        self._base = {**self._base, **now}
        return Movement(moved, points)


# ---- how fresh it is --------------------------------------------------------------------


@dataclass(frozen=True)
class Freshness:
    """One feed's health, worked out from its timestamps.

    level: "waiting" (never tried), "fresh", "stale" (the last good look is
    older than the feed allows), "failed" (the last try failed; older good
    data is still shown) or "error" (no good look ever, and the last try
    failed)."""

    category: str              # "scores", "standings"
    level: str
    last_success: float | None
    last_attempt: float | None
    error: str
    age: float | None          # seconds since the last good look

    @property
    def warn(self) -> bool:
        return self.level in ("stale", "failed")

    def age_text(self) -> str:
        if self.age is None:
            return ""
        seconds = int(self.age)
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            m = seconds // 60
            return f"{m} minute{'s' if m != 1 else ''} ago"
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"

    def headline(self) -> str:
        """What the screen says, from the stored timestamps only."""
        if self.level == "waiting":
            return "Waiting for the first update"
        if self.level == "error":
            return "No successful data refresh yet"
        when = clock_et(self.last_success, seconds=True)
        if self.level == "failed":
            return f"Refresh failed — showing data from {when}"
        if self.level == "stale":
            return f"Data is {self.age_text().removesuffix(' ago')} old — last successful update {when}"
        return f"Updated {self.age_text()}"

    def detail(self) -> str:
        """The two moments apart: the last good look and the last try."""
        bits = []
        if self.last_success:
            bits.append(f"Last successful update: {clock_et(self.last_success, seconds=True)}")
        if self.last_attempt and self.last_attempt != self.last_success:
            bits.append(f"Last attempt: {clock_et(self.last_attempt, seconds=True)}"
                        + (f" ({self.error})" if self.error else ""))
        return " · ".join(bits)


def freshness(category: str, last_success: float | None, last_attempt: float | None, *,
              failed: bool = False, error: str = "", live: bool = False,
              now: float | None = None) -> Freshness:
    """A feed's freshness from when it last worked and when it was last tried.

    `failed`: the last try did not work. `live`: a game is on, so the feed is
    expected every 30 seconds rather than every few minutes (tokens.FRESHNESS)."""
    now = time.time() if now is None else now
    good = float(last_success) if isinstance(last_success, (int, float)) and last_success > 0 else None
    tried = float(last_attempt) if isinstance(last_attempt, (int, float)) and last_attempt > 0 else None
    if tried is None and good is not None:
        tried = good
    age = max(0.0, now - good) if good is not None else None
    if good is None:
        level = "error" if failed else "waiting"
    elif failed:
        level = "failed"
    else:
        limits = tokens.FRESHNESS
        limit = limits[f"{category}_live_s"] if live and f"{category}_live_s" in limits else limits.get(f"{category}_s", 900)
        level = "stale" if age > limit else "fresh"
    return Freshness(category, level, good, tried, error if failed else "", age)


def scores_freshness(year: int, week: int, *, live: bool = False, now: float | None = None) -> Freshness:
    """The desktop's score feed, from what feeds/results.py keeps: the last
    answer with games in it, the last time it was asked, and the last failure
    (cleared by the next good look)."""
    from ..feeds import results
    good = results.fetched_at(year, week) if year and week else None
    asked = results.checked_at(year, week) if year and week else None
    failure = results.last_failure()
    failed = failure is not None and (good is None or failure[0] > good)
    tried = max((t for t in (asked, failure[0] if failure else None, good) if t), default=None)
    return freshness("scores", good, tried, failed=failed, error=failure[1] if failed else "",
                     live=live, now=now)


# ---- one card ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardState:
    """How one game's card is drawn. The game's status, whether it is the
    chosen card, and a data warning are separate: a final game stays final
    when chosen, and a warning shows whatever else is true."""

    status: str        # "upcoming", "live", "final", "postponed"
    selected: bool
    warn: str          # "", "stale", "error"
    label: str         # "LIVE", "FINAL", "POSTPONED", "UPCOMING"


_STATUS = {"pre": "upcoming", "in": "live", "final": "final", "post": "final", "off": "postponed"}


def card_state(game_state: str, *, selected: bool = False, feed: Freshness | None = None) -> CardState:
    status = _STATUS.get(game_state, "upcoming")
    warn = ""
    if feed is not None and status != "final":       # a final stands whatever the feed does now
        warn = "error" if feed.level == "error" else "stale" if feed.warn else ""
    return CardState(status, bool(selected), warn, status.upper())
