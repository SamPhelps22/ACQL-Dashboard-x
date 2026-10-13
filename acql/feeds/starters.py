"""Starting quarterbacks, checked before kickoff.

Quarterback was the one football signal that measurably moved results in the
pick'em backtests (nfl_pickem/docs/MODEL_CARD.md). The betting line usually
moves for a quarterback change, but only once the news is out - so before
locking a card it is worth seeing, game by game:

  * who is expected to start, and whether that is the team's usual starter
    (the one who started most of its last three games);
  * any quarterback on the team's injury report as Out, Doubtful or
    Questionable that week.

Sources: nflverse's schedule (free, no key), which carries projected starters
for upcoming games and actual starters for played ones - fetched at most every
few hours and kept in the database - and the ESPN injury report the dashboard
already keeps (injuries.py). With no connection the check says so and nothing
else changes. Projections can be wrong - this is a prompt to look, not a
verdict. The scouting window has the full injury report; this is the part of
it that most often changes a pick, put on Game Day before kickoff.
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
KIND = "starters"
TIMEOUT = 15
REFRESH_S = 3 * 3600
USUAL_GAMES = 3
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
    injured: tuple[str, ...] = ()   # "QB Josh Allen questionable (ankle)", from the ESPN report
    starter_hurt: bool = False      # the expected starter is on the report as out/doubtful/IR

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
        return any(t.changed or t.starter_hurt for t in (self.away, self.home))

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
    from .. import store
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


def _same_name(a: str, b: str) -> bool:
    norm = lambda x: " ".join(str(x or "").lower().replace(".", "").split())  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


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


def refresh(year: int, *, now: float | None = None, fetch=_fetch) -> bool:
    """Bring the kept schedule up to date (call off the UI thread; injuries.py keeps the injury report)."""
    now = time.time() if now is None else now
    text, _ = _cached("games", GAMES_URL, now, fetch)
    return bool(text)


def _espn_quarterbacks(team: str) -> list:
    from . import injuries
    try:
        return [i for i in injuries.team(team) if i.quarterback]
    except Exception:  # noqa: BLE001 - the report is optional
        return []


def check(year: int, week: int, slate: list[tuple[int, str, str]], *, now: float | None = None,
          fetch=None, report=_espn_quarterbacks) -> Check:
    """QB notes for a week's games. `slate` is (game index, away code, home code) in pool codes."""
    now = time.time() if now is None else now
    games_text, at = _cached("games", GAMES_URL, now, fetch)
    if not games_text:
        return Check(available=False, problem="Starting quarterbacks not checked yet (needs a connection; "
                                              "Refresh fetches them).")
    rows = schedule_rows(games_text, year)
    this_week = {(pool_code(r["away_team"]), pool_code(r["home_team"])): r
                 for r in rows if r.get("week") == str(week)}
    out = Check(checked_at=at)
    for index, away, home in slate:
        away, home = pool_code(away), pool_code(home)
        r = this_week.get((away, home)) or {}
        teams = []
        for side, team in (("away", away), ("home", home)):
            starter = (r.get(f"{side}_qb_name") or "").strip()
            listed = report(team)
            hurt = any(i.missing and _same_name(i.name, starter) for i in listed)
            teams.append(TeamQB(team=team, starter=starter, usual=usual_starter(rows, team, week),
                                injured=tuple(i.words() for i in listed), starter_hurt=hurt))
        out.games[index] = GameQB(index, teams[0], teams[1], at)
    return out
