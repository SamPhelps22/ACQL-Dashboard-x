"""Starting quarterbacks, checked before kickoff.

Quarterback was the one football signal that measurably moved results in the
pick'em backtests (nfl_pickem/docs/MODEL_CARD.md). The betting line usually
moves for a quarterback change, but only once the news is out - so before
locking a card it is worth seeing, game by game:

  * who is expected to start, and whether that is the team's usual starter
    (the one who started most of its last three games);
  * any quarterback on the team's injury report as Out, Doubtful or
    Questionable that week.

Sources (free, no key): nflverse's schedule, which carries projected starters
for upcoming games and actual starters for played ones, and nflverse's weekly
injury reports. Both are fetched at most every few hours and kept in the
database; with no connection the check says so and nothing else changes.
Projections can be wrong - this is a prompt to look, not a verdict.
"""

from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
INJURY_URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{year}.csv"
KIND = "qbcheck"
TIMEOUT = 15
REFRESH_S = 3 * 3600
USUAL_GAMES = 3
WORRY = ("Out", "Doubtful", "Questionable")
#: nflverse abbreviations that aren't the pool's.
CODES = {"la": "lar", "jac": "jax", "wsh": "was", "oak": "lv", "sd": "lac", "stl": "lar"}


def pool_code(code: str) -> str:
    c = str(code or "").strip().lower()
    return CODES.get(c, c)


@dataclass(frozen=True)
class TeamQB:
    team: str                       # pool code
    starter: str                    # projected/actual starter, "" if not listed
    usual: str                      # most starts in the team's last few games
    injured: tuple[str, ...] = ()   # "Josh Allen: Questionable"
    last_week: str = ""             # the starter's status on last week's report, when this week's isn't out

    @property
    def changed(self) -> bool:
        return bool(self.starter and self.usual and self.starter != self.usual)

    @property
    def flags(self) -> list[str]:
        out = []
        if not self.starter:
            out.append(f"{self.team.upper()}: no starter listed yet")
        elif self.changed:
            out.append(f"{self.team.upper()}: {self.starter} expected to start, not {self.usual}")
        out += [f"{self.team.upper()} injury report: {x}" for x in self.injured]
        if self.last_week:
            out.append(f"{self.team.upper()}: {self.starter} was {self.last_week} on last week's report")
        return out


@dataclass(frozen=True)
class GameQB:
    index: int
    away: TeamQB
    home: TeamQB
    checked_at: float = 0.0

    @property
    def flags(self) -> list[str]:
        return self.away.flags + self.home.flags

    @property
    def worrying(self) -> bool:
        """A starter change, or a QB listed Out/Doubtful - worth a look before locking."""
        return any(t.changed or t.last_week or any(("Out" in i or "Doubtful" in i) for i in t.injured)
                   for t in (self.away, self.home))

    def note(self) -> str:
        return "; ".join(self.flags)

    def summary(self) -> str:
        return (f"QBs: {self.away.starter or '?'} ({self.away.team.upper()}) vs "
                f"{self.home.starter or '?'} ({self.home.team.upper()})")


@dataclass
class Check:
    games: dict[int, GameQB] = field(default_factory=dict)
    available: bool = True
    problem: str = ""
    checked_at: float = 0.0


# ---- fetching -------------------------------------------------------------------
def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ACQL-Dashboard"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _cached(name: str, url: str, now: float, fetch=_fetch) -> tuple[str | None, float]:
    """The kept copy, refreshed when older than REFRESH_S. ``fetch=None`` never touches
    the network (the UI thread reads this way; the loader thread refreshes)."""
    from . import store
    kept = store.get(KIND, name, None)
    if isinstance(kept, dict) and (fetch is None or now - float(kept.get("at", 0)) < REFRESH_S):
        return kept.get("text"), float(kept.get("at", 0))
    if fetch is None:
        return None, 0.0
    try:
        text = fetch(url)
    except (urllib.error.URLError, OSError, ValueError):
        if isinstance(kept, dict):
            return kept.get("text"), float(kept.get("at", 0))     # stale beats nothing
        return None, 0.0
    try:
        store.put(KIND, name, {"at": now, "text": text})
    except store.StoreError:
        pass
    return text, now


# ---- reading --------------------------------------------------------------------
def schedule_rows(text: str, year: int) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("season") == str(year) and r.get("game_type") == "REG":
            rows.append(r)
    return rows


def usual_starter(rows: list[dict], team: str, before_week: int, n: int = USUAL_GAMES) -> str:
    """The quarterback who started most of `team`'s last `n` played games before the week."""
    played = []
    for r in rows:
        try:
            wk = int(r["week"])
        except (KeyError, ValueError):
            continue
        if wk >= before_week or not (r.get("home_score") or "").strip():
            continue
        for side in ("home", "away"):
            if pool_code(r.get(f"{side}_team")) == team and r.get(f"{side}_qb_name"):
                played.append((wk, r[f"{side}_qb_name"]))
    played.sort()
    recent = [name for _, name in played[-n:]]
    if not recent:
        return ""
    counts = Counter(recent)
    best = max(counts.values())
    # most starts; ties go to the most recent of them
    return next(name for name in reversed(recent) if counts[name] == best)


def injured_qbs(text: str | None, week: int) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not text:
        return out
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("position") != "QB" or str(r.get("week")) != str(week):
            continue
        status = (r.get("report_status") or "").strip()
        if status in WORRY:
            out.setdefault(pool_code(r.get("team")), []).append(f"{r.get('full_name', '?')}: {status}")
    return out


def refresh(year: int, *, now: float | None = None, fetch=_fetch) -> bool:
    """Bring the kept schedule and injury report up to date (call off the UI thread)."""
    now = time.time() if now is None else now
    text, _ = _cached("games", GAMES_URL, now, fetch)
    _cached(f"injuries-{year}", INJURY_URL.format(year=year), now, fetch)
    return bool(text)


def _teams_reported(text: str | None, week: int) -> set[str]:
    """Teams with any row (any position) on the given week's injury report."""
    if not text:
        return set()
    return {pool_code(r.get("team")) for r in csv.DictReader(io.StringIO(text)) if str(r.get("week")) == str(week)}


def check(year: int, week: int, slate: list[tuple[int, str, str]], *, now: float | None = None,
          fetch=None) -> Check:
    """QB notes for a week's games. `slate` is (game index, away code, home code) in pool codes."""
    now = time.time() if now is None else now
    games_text, at = _cached("games", GAMES_URL, now, fetch)
    if not games_text:
        return Check(available=False, problem="Starting quarterbacks not checked yet (needs a connection; "
                                              "Refresh fetches them).")
    injury_text, _ = _cached(f"injuries-{year}", INJURY_URL.format(year=year), now, fetch)
    rows = schedule_rows(games_text, year)
    hurt = injured_qbs(injury_text, week)
    reported_now = _teams_reported(injury_text, week)
    before = injured_qbs(injury_text, week - 1) if week > 1 else {}
    this_week = {(pool_code(r["away_team"]), pool_code(r["home_team"])): r
                 for r in rows if r.get("week") == str(week)}
    out = Check(checked_at=at)
    for index, away, home in slate:
        away, home = pool_code(away), pool_code(home)
        r = this_week.get((away, home)) or {}
        teams = []
        for side, team in (("away", away), ("home", home)):
            starter = (r.get(f"{side}_qb_name") or "").strip()
            last = ""
            if starter and team not in reported_now:      # this week's report not out for the team yet
                for item in before.get(team, []):
                    name, _, status = item.partition(": ")
                    if name == starter and status in ("Out", "Doubtful"):
                        last = status
            teams.append(TeamQB(team=team, starter=starter, usual=usual_starter(rows, team, week),
                                injured=tuple(hurt.get(team, [])), last_week=last))
        out.games[index] = GameQB(index, teams[0], teams[1], at)
    return out
