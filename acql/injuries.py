"""Who is hurt: each team's injury report, from ESPN.

The betting line already has every injury in it - a starting quarterback
ruled out moves a game by a touchdown before anyone here reads about it.
What this adds is the *why*: a line that has swung nine points makes sense
at a glance when the report says the quarterback is out.

ESPN publishes one list for the league: every player with a status. Kept
here are the ones who matter to this week's game - out, doubtful or
questionable - and anyone just put on injured reserve; a player who has
been on it for a month was priced in a month ago. The list doesn't say who
starts, so the pages name the quarterbacks and count the rest by position.

One document in the app's database, refreshed by the scheduled runs and by
Update lines; nothing here knows about Qt.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
TIMEOUT = 40
#: How often the report is looked at...
EVERY = 6 * 3600
#: ...and on the day the cards are due.
EVERY_LOCK_DAY = 3600
#: Someone put on injured reserve longer ago than this is old news.
RESERVE_DAYS = 10
#: Statuses kept, worst first, and how the pages say them.
STATUSES = {"out": "out", "doubtful": "doubtful", "injured reserve": "on injured reserve",
            "questionable": "questionable"}
ORDER = list(STATUSES)
#: "Out" for these reasons isn't an injury: a healthy player left off the
#: game-day roster, which is most third quarterbacks every week.
NOT_HURT = ("coach's decision", "coachs decision", "not injury related - resting")


class InjuryError(Exception):
    """The report couldn't be fetched, in words fit to show."""


@dataclass(frozen=True)
class Injury:
    name: str
    position: str           # "QB", "WR", "CB"
    status: str             # a key of STATUSES
    what: str               # "Ankle", or ""
    at: float               # when the report last changed, seconds since 1970

    @property
    def quarterback(self) -> bool:
        return self.position == "QB"

    @property
    def missing(self) -> bool:
        """Not expected to play: out, doubtful or on injured reserve."""
        return self.status != "questionable"

    def words(self) -> str:
        return f"{self.position} {self.name} {STATUSES.get(self.status, self.status)}" + (
            f" ({self.what.lower()})" if self.what else "")


def _when(text: object) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def parse(data: object, now: float | None = None) -> dict[str, list[dict]]:
    """ESPN's reply as {team code: [injury, ...]} - only the ones worth keeping."""
    from .predictions import team_code
    now = time.time() if now is None else now
    out: dict[str, list[dict]] = {}
    for team in (data.get("injuries") if isinstance(data, dict) else None) or []:
        code = team_code((team or {}).get("displayName"))
        if not code:
            continue
        kept = []
        for item in team.get("injuries") or []:
            status = str((item or {}).get("status", "")).casefold()
            athlete = item.get("athlete") or {}
            name = str(athlete.get("displayName") or "").strip()
            if status not in STATUSES or not name:
                continue
            what = str((item.get("details") or {}).get("type") or "").strip()
            if what.casefold().replace("’", "'") in NOT_HURT:
                continue
            at = _when(item.get("date"))
            if status == "injured reserve" and now - at > RESERVE_DAYS * 86400:
                continue
            kept.append({
                "name": name,
                "position": str((athlete.get("position") or {}).get("abbreviation") or "").upper(),
                "status": status,
                "what": what,
                "at": at,
            })
        kept.sort(key=lambda i: (i["position"] != "QB", ORDER.index(i["status"]), i["name"]))
        out[code] = kept
    return out


def fetch(*, opener=None) -> dict[str, list[dict]]:
    """The league's report, parsed. Raises InjuryError."""
    request = urllib.request.Request(URL, headers={"User-Agent": "ACQL-Dashboard", "Accept": "application/json"})
    open_url = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    try:
        with open_url(request) as reply:
            body = reply.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as exc:
        raise InjuryError(f"Couldn't reach ESPN's injury report ({getattr(exc, 'reason', exc)}).") from exc
    try:
        return parse(json.loads(body))
    except ValueError as exc:
        raise InjuryError("ESPN sent back something that wasn't an injury report.") from exc


# ---- kept ---------------------------------------------------------------------------
def _kept() -> dict:
    try:
        from . import store
        found = store.get("injuries", "latest", {})
        return found if isinstance(found, dict) else {}
    except Exception:  # noqa: BLE001 - no report is no report
        return {}


def fetched_at() -> float:
    return float(_kept().get("at") or 0.0)


def due(lock_in: float | None = None, now: float | None = None) -> bool:
    """Whether the report is worth fetching again - hourly once the cards are due within a day."""
    now = time.time() if now is None else now
    every = EVERY_LOCK_DAY if lock_in is not None and 0 <= lock_in < 86400 else EVERY
    return now - fetched_at() >= every


def refresh(*, opener=None, now: float | None = None) -> int:
    """Fetch and keep the report. Returns how many players are on it."""
    from . import store
    teams = fetch(opener=opener)
    store.put("injuries", "latest", {"at": time.time() if now is None else now, "teams": teams})
    return sum(len(v) for v in teams.values())


def team(code: str) -> list[Injury]:
    """A team's report, quarterbacks first."""
    rows = (_kept().get("teams") or {}).get(str(code or "").lower()) or []
    out = []
    for row in rows:
        try:
            out.append(Injury(str(row["name"]), str(row.get("position", "")), str(row["status"]),
                              str(row.get("what", "")), float(row.get("at") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def summary(code: str, most: int = 2) -> str:
    """"QB Lamar Jackson out (hamstring); 3 more out (WR, CB, S); 2 questionable" - or ""."""
    report = team(code)
    if not report:
        return ""
    parts = [i.words() for i in report if i.quarterback][:most]
    missing = [i for i in report if i.missing and not i.quarterback]
    if missing:
        spots = []
        for i in missing:
            if i.position and i.position not in spots:
                spots.append(i.position)
        parts.append(f"{len(missing)} {'more ' if parts else ''}out"
                     + (f" ({', '.join(spots[:5])}{'…' if len(spots) > 5 else ''})" if spots else ""))
    doubt = sum(1 for i in report if not i.missing and not i.quarterback)
    if doubt:
        parts.append(f"{doubt} questionable")
    return "; ".join(parts)
