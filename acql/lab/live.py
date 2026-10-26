"""Live scores for the Lab: one shared poller, pushed to every open page.

ESPN's scoreboard has no streaming feed, so this is controlled polling, said
as such on the page: one reader on this computer asks ESPN, however many
pages are open, and each page is sent only what changed over Server-Sent
Events (the browser reconnects by itself).

    every 30 s    while a game is being played
    every 2 min   when one kicks off within 15 minutes
    every 10 min  otherwise
    on a failure  30 s, 60 s, 120 s ... up to 10 min, and the last good
                  scores stay on screen, marked stale

Every change gets one increasing version number, so a page that reconnects
asks for "since version N" and never sees the same event twice. Nothing is
saved: the app's own refresh keeps the stored scores; this only reads.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict

LIVE_S, SOON_S, IDLE_S, MAX_BACKOFF_S = 30, 120, 600, 600
SOON_WINDOW_S = 15 * 60


def _row(s) -> dict:
    d = asdict(s)
    return {k: d.get(k) for k in ("away", "home", "away_points", "home_points", "state", "final", "kickoff",
                                  "detail", "period", "clock", "possession", "situation", "red_zone",
                                  "last_play", "called_off")}


def phase(g: dict) -> str:
    """The card state the page draws: upcoming, live, halftime, final, called-off."""
    if g.get("called_off"):
        return "called-off"
    if g.get("state") == "post" or g.get("final"):
        return "final"
    if g.get("state") == "in":
        return "halftime" if "half" in str(g.get("detail", "")).casefold() else "live"
    return "upcoming"


class LiveHub:
    def __init__(self, year: int, week: int, *, fetch=None, load=None, clock=time.time):
        from ..feeds import results
        self.year, self.week = year, week
        self._fetch = fetch or (lambda y, w: results.fetch(y, w))
        self._clock = clock
        self._lock = threading.Condition()
        self.version = 0
        self.events: list[dict] = []        # the last 200, each with its version
        self.games: dict[str, dict] = {}
        self.ok_at: float | None = None     # when ESPN last answered
        self.tried_at: float | None = None
        self.error = ""
        self.failures = 0
        self.source = "stored"
        initial = (load or results.load)(year, week)
        for s in initial:
            row = _row(s)
            row["phase"] = phase(row)
            self.games[f"{row['away']}@{row['home']}"] = row
        self.ok_at = results.fetched_at(year, week) if load is None else None
        self._stop = threading.Event()

    # ---- what a page reads -------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            now = self._clock()
            return {"version": self.version, "year": self.year, "week": self.week,
                    "games": list(self.games.values()), "ok_at": self.ok_at, "tried_at": self.tried_at,
                    "error": self.error, "failures": self.failures, "source": self.source,
                    "next_in": self.interval(), "now": now,
                    "stale": self.ok_at is None or now - self.ok_at > max(3 * self.interval(), 90),
                    "mode": "polling ESPN's scoreboard (not a streaming feed)"}

    def since(self, version: int) -> list[dict]:
        with self._lock:
            return [e for e in self.events if e["version"] > version]

    def wait(self, version: int, timeout: float) -> bool:
        """Block until something newer than `version` exists (True) or time runs out."""
        with self._lock:
            return self._lock.wait_for(lambda: self.version > version, timeout=timeout)

    # ---- how often ---------------------------------------------------------------
    def interval(self) -> int:
        if self.failures:
            return min(MAX_BACKOFF_S, LIVE_S * 2 ** (self.failures - 1))
        if any(g["state"] == "in" for g in self.games.values()):
            return LIVE_S
        now = self._clock()
        if any(g["state"] == "pre" and g.get("kickoff") and 0 <= g["kickoff"] - now <= SOON_WINDOW_S
               for g in self.games.values()):
            return SOON_S
        return IDLE_S

    # ---- one look ------------------------------------------------------------------
    def poll(self) -> list[dict]:
        """Ask ESPN once; record what changed. Returns the new events."""
        self.tried_at = self._clock()
        try:
            scores = self._fetch(self.year, self.week)
        except Exception as exc:  # noqa: BLE001 - shown on the page; last good scores stay
            with self._lock:
                self.failures += 1
                self.error = str(exc) or exc.__class__.__name__
                self.version += 1
                self._push({"kind": "error", "text": self.error})
            return []
        made = []
        with self._lock:
            self.failures, self.error, self.source = 0, "", "espn"
            self.ok_at = self._clock()
            for s in scores:
                row = _row(s)
                row["phase"] = phase(row)
                key = f"{row['away']}@{row['home']}"
                old = self.games.get(key)
                if old == row:
                    continue
                kind = "new"
                if old:
                    if (old["away_points"], old["home_points"]) != (row["away_points"], row["home_points"]):
                        kind = "score"
                    elif old["phase"] != row["phase"]:
                        kind = "phase"
                    else:
                        kind = "clock"
                self.games[key] = row
                self.version += 1
                made.append(self._push({"kind": kind, "game": key, "row": row,
                                        "before": None if not old else {"away_points": old["away_points"],
                                                                        "home_points": old["home_points"],
                                                                        "phase": old["phase"]}}))
            self.version += 1
            self._push({"kind": "heartbeat", "ok_at": self.ok_at})
        return made

    def _push(self, event: dict) -> dict:
        event["version"] = self.version
        event["at"] = self._clock()
        self.events.append(event)
        del self.events[:-200]
        self._lock.notify_all()
        return event

    def run(self) -> None:
        while not self._stop.is_set():
            self.poll()
            self._stop.wait(self.interval())

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, name="lab-live", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()


def current_week(year: int) -> int:
    """The week to watch: the first with a game not yet over, else the last with games."""
    from ..feeds import results
    last = 1
    for week in range(1, 19):
        games = results.load(year, week)
        if games:
            last = week
            if any(not g.final and not g.called_off for g in games):
                return week
    return last
