"""Game-day rules shared by RedZone mode and Cinema mode - no Qt here.

What these decide, both screens draw:

* which game RedZone mode features (spotlight_rank, Spotlight),
* down, distance and field position read from ESPN's situation text,
* the state of one pick (pick_status),
* what a change in the standings means, said once (pool_events),
* how honest the score data is right now (data_label),
* which games a Cinema filter shows (filter_states).

Nothing here invents data: a game with no situation text has no drive shown,
and a feed that has not answered is "unavailable", never "live".
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import gameday as GD

# ---- the spotlight -----------------------------------------------------------------------

#: How much each thing happening counts towards featuring a game. Kept as plain
#: numbers so a preference can switch one off (weight 0) without new code.
WEIGHTS = {
    "red_zone": 50,       # a team inside the 20
    "scored": 45,         # a score in the last two minutes
    "turnover": 40,       # the last play was an interception or fumble
    "close_late": 35,     # 4th quarter or overtime, one score apart
    "mine": 20,           # you picked this game
    "live": 5,            # on at all
}
#: How long a score keeps a game "just scored" (seconds).
SCORED_FOR = 120
#: The featured game is not swapped for a better one more often than this (seconds).
DWELL = 25
#: A game you chose by hand stays featured this long before the automatic choice returns.
MANUAL_HOLD = 180

_TURNOVER = re.compile(r"\b(intercept\w*|fumble\w*|recovered by|turnover on downs|pick[- ]six)\b", re.IGNORECASE)
_QUARTER = re.compile(r"\b(4th|OT)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Rank:
    index: int
    score: int
    reasons: tuple[str, ...]


def reason_words(reasons) -> str:
    words = {"red_zone": "RED ZONE", "scored": "JUST SCORED", "turnover": "TURNOVER", "close_late": "CLOSE LATE",
             "mine": "YOUR PICK", "live": "LIVE"}
    return " · ".join(words[r] for r in reasons if r in words)


def is_close_late(st) -> bool:
    margin = st.margin
    return (st.state == "in" and margin is not None and abs(margin) <= 8
            and bool(_QUARTER.search(st.clock or "")))


def spotlight_rank(states, picks: dict | None = None, *, scored_at: dict | None = None,
                   weights: dict | None = None, now: float | None = None) -> list[Rank]:
    """The live games, most worth featuring first. Only games under way count;
    every reason comes from the scoreboard as kept (red zone flag, last play,
    clock, score), never guessed."""
    now = time.time() if now is None else now
    picks = picks or {}
    scored_at = scored_at or {}
    w = {**WEIGHTS, **(weights or {})}
    out = []
    for st in states:
        if st.state != "in":
            continue
        reasons = []
        if st.red_zone:
            reasons.append("red_zone")
        if now - scored_at.get(st.index, -1e18) <= SCORED_FOR:
            reasons.append("scored")
        if st.last_play and _TURNOVER.search(st.last_play):
            reasons.append("turnover")
        if is_close_late(st):
            reasons.append("close_late")
        if picks.get(st.index, GD.NOBODY) != GD.NOBODY:
            reasons.append("mine")
        reasons.append("live")
        score = sum(w.get(r, 0) for r in reasons)
        out.append(Rank(st.index, score, tuple(r for r in reasons if w.get(r, 0) > 0)))
    out.sort(key=lambda r: (-r.score, r.index))
    return out


@dataclass
class Spotlight:
    """Which game is featured, and why. The automatic choice moves only when a
    better game has been better for a while (DWELL); a game picked by hand is
    held for MANUAL_HOLD, a pinned one until unpinned."""

    current: int | None = None
    since: float = 0.0
    manual_until: float = 0.0
    pinned: int | None = None
    auto: bool = True

    def choose_by_hand(self, index: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.current, self.since, self.manual_until = index, now, now + MANUAL_HOLD

    def pin(self, index: int | None) -> None:
        self.pinned = index
        if index is not None:
            self.current = index

    def update(self, ranked: list[Rank], states, now: float | None = None) -> int | None:
        now = time.time() if now is None else now
        known = {st.index: st for st in states}
        if self.pinned is not None and self.pinned in known:
            self.current = self.pinned
            return self.current
        self.pinned = None if self.pinned not in known else self.pinned
        held = self.current in known and now < self.manual_until
        if held:
            return self.current
        if not self.auto:
            if self.current in known:
                return self.current
        top = ranked[0].index if ranked else None
        if top is None:
            # nothing on: keep a final or upcoming game chosen by hand, else the next kickoff
            if self.current in known:
                return self.current
            upcoming = sorted((s for s in states if s.state == "pre"), key=lambda s: (s.kickoff or 1e18, s.index))
            self.current = upcoming[0].index if upcoming else None
            self.since = now
            return self.current
        if self.current is None or self.current not in known or known[self.current].state != "in":
            self.current, self.since = top, now
            return top
        if top != self.current and now - self.since >= DWELL:
            mine = next((r.score for r in ranked if r.index == self.current), 0)
            best = ranked[0].score
            if best > mine:
                self.current, self.since = top, now
        return self.current


# ---- the drive --------------------------------------------------------------------------

_SITUATION = re.compile(r"(1st|2nd|3rd|4th)\s*&\s*(goal|\d+)\s*(?:at\s+([A-Za-z]{2,4})\s+(\d{1,2})|at\s+50|at\s+midfield)?",
                        re.IGNORECASE)


#: ESPN's spellings that differ from the dashboard's team codes.
_ALIASES = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LAR"}


def _code(text: str) -> str:
    code = str(text or "").strip().upper()
    return _ALIASES.get(code, code)


@dataclass(frozen=True)
class Drive:
    down: int
    distance: str              # "7" or "Goal"
    to_goal: int | None        # yards to the end zone, when the text says where
    team: str                  # who has the ball ("home"/"away")
    text: str

    @property
    def down_text(self) -> str:
        return f"{('1st', '2nd', '3rd', '4th')[self.down - 1]} & {self.distance}"


def drive(st, code_of) -> Drive | None:
    """Down, distance and field position from the scoreboard's situation text
    ("2nd & 7 at ATL 23"). `code_of(team name)` gives the code the text uses.
    None when there is no such text - nothing is drawn rather than guessed."""
    text = (st.situation or "").strip()
    if st.state != "in" or not text or st.possession not in ("home", "away"):
        return None
    m = _SITUATION.search(text)
    if not m:
        return None
    down = ("1st", "2nd", "3rd", "4th").index(m.group(1).lower()) + 1
    distance = "Goal" if m.group(2).lower() == "goal" else m.group(2)
    to_goal = None
    if m.group(3) and m.group(4):
        side, yard = _code(m.group(3)), int(m.group(4))
        holder, other = ((st.game.home, st.game.away) if st.possession == "home" else (st.game.away, st.game.home))
        own, opp = _code(code_of(holder) or ""), _code(code_of(other) or "")
        if side and side == own:
            to_goal = 100 - yard
        elif side and side == opp:
            to_goal = yard
    elif "50" in text or "midfield" in text.lower():
        to_goal = 50
    return Drive(down, distance, to_goal, st.possession, text)


# ---- one pick ---------------------------------------------------------------------------

def pick_status(st, side: int) -> str:
    """'upcoming', 'winning', 'losing', 'level' (no one credited if it ended now),
    'correct', 'incorrect', 'push' (final, no one credited) or 'postponed'."""
    if st.state == "off":
        return "postponed"
    if st.state == "pre" or not st.started:
        return "upcoming"
    final = st.state == "final"
    if st.leader == GD.NOBODY:
        return "push" if final else "level"
    right = st.leader == side
    if final:
        return "correct" if right else "incorrect"
    return "winning" if right else "losing"


# ---- the pool, said once ------------------------------------------------------------------

@dataclass
class PoolWatch:
    """Standings as last said; the next table's real changes as sentences.
    The order and ties are the board's - nothing is ranked here."""

    base: dict | None = None             # key -> (place, points, name)
    said: set = field(default_factory=set)

    def events(self, rows, you_key: str = "") -> list[tuple[str, str]]:
        """`rows`: (key, name, place, points). Returns (kind, text) for genuine
        changes since the last table: a new leader, your place, a coach into
        the top three. A table identical to the last says nothing."""
        now = {k: (p, pts, n) for k, n, p, pts in rows if k and isinstance(p, int)}
        before, self.base = self.base, now
        if before is None:
            return []
        out = []
        leaders_now = sorted(n for k, (p, _pts, n) in now.items() if p == 1)
        leaders_before = sorted(n for k, (p, _pts, n) in before.items() if p == 1)
        if leaders_now and leaders_now != leaders_before:
            text = (f"{leaders_now[0]} takes the lead" if len(leaders_now) == 1
                    else f"{' and '.join(leaders_now[:3])} share the lead")
            out.append(("pool", text))
        if you_key in now and you_key in before and now[you_key][0] != before[you_key][0]:
            was, place = before[you_key][0], now[you_key][0]
            out.append(("you", f"You {'climb' if place < was else 'drop'} to {GD_ordinal(place)} (from {GD_ordinal(was)})"))
        for k, (p, _pts, n) in now.items():
            if k == you_key or k not in before or p > 3 or before[k][0] <= 3 or p == 1:
                continue
            out.append(("pool", f"{n} moves into the top three ({GD_ordinal(p)})"))
        fresh = []
        for kind, text in out:
            key = (kind, text)
            if key in self.said:
                continue
            self.said.add(key)
            fresh.append((kind, text))
        return fresh


def GD_ordinal(n: int) -> str:  # noqa: N802 - kept short where it is used
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---- how honest the data is -----------------------------------------------------------------

#: Within this many seconds a fresh feed counts as live; older but still inside the
#: feed's own limit, "delayed".


def data_label(fresh, live: bool = True) -> tuple[str, str]:
    """(LABEL, words) for the score data on screen - the same words the website
    uses (feedLabel). The scores are polled from ESPN's scoreboard (every 30
    seconds while a game is on), never streamed. Whether they are stale is the
    freshness rule's call (tokens.FRESHNESS), not a second threshold here; LIVE
    only when they are fresh and a game is being played."""
    if fresh is None or fresh.level == "waiting":
        return "LOADING", "No scoreboard answer yet"
    if fresh.level == "error":
        return "UNAVAILABLE", "No good scoreboard answer yet"
    if fresh.level == "failed":
        return "REFRESH FAILED", f"Showing the last good scores, {fresh.age_text()}"
    if fresh.level == "stale":
        return "STALE", f"Last good scores {fresh.age_text()}"
    if not live:
        return "UP TO DATE", f"Scores from {fresh.age_text()}"
    return "LIVE", "Scoreboard polled every 30 s"


# ---- Cinema filters ---------------------------------------------------------------------------

FILTERS = ("all", "live", "upcoming", "final", "mine")


def filter_states(states, which: str, picks: dict | None = None) -> list:
    picks = picks or {}
    if which == "live":
        return [s for s in states if s.state == "in"]
    if which == "upcoming":
        return [s for s in states if s.state in ("pre", "off")]
    if which == "final":
        return [s for s in states if s.state == "final"]
    if which == "mine":
        return [s for s in states if picks.get(s.index, GD.NOBODY) != GD.NOBODY]
    return list(states)
