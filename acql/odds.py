"""Betting lines, fetched instead of typed.

Every number the dashboard gives - the card, the chance of winning the week,
the suicide helper, the luck meter - starts from the betting line. Typing
sixteen spreads a week is a chore, and a line typed on Tuesday is stale by
Sunday: the market moves on injury news, and a quarterback ruled out on
Friday can move a game four or five points.

This fetches the current NFL spreads from The Odds API (the-odds-api.com),
which has a free plan of 500 requests a month - one press of "Update lines"
is one request, so that is several a day all season.

What is kept, per week, in acql-odds.json beside the pool's data:

    opening    the first number seen for each game
    latest     the most recent one, the median over every bookmaker quoted
    history    each update's numbers, so a card can be compared with the
               lines it was made on

and `overlay` lays those onto the week's stored predictions, so every page
that reads predictions - Next Week, This Week, the suicide helper - picks up
the latest line without knowing where it came from. A Prediction Tracker
file downloaded *after* an update wins for its games; one downloaded before
is overruled by the fresher line.

Every margin here is from the HOME team's side, like the predictions file:
+6.5 means the home team is favoured by 6.5.
"""

from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
SIGNUP_PAGE = "https://the-odds-api.com/"
STORE_NAME = "acql-odds.json"
TIMEOUT = 20
#: Updates kept per week. A few a day for a week is plenty.
KEEP_HISTORY = 40
#: A move this big (points) is worth pointing out.
BIG_MOVE = 1.5


class OddsError(Exception):
    """A fetch that failed, with a reason fit to show the person."""


# ---- where it lives ---------------------------------------------------------
def _store_path() -> Path:
    try:
        from .config import DATA_DIR  # lazy: config never imports this
        return Path(DATA_DIR) / STORE_NAME
    except Exception:  # noqa: BLE001
        from .config import ROOT
        return Path(ROOT) / STORE_NAME


def _read() -> dict:
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(store: dict) -> None:
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, indent=1), encoding="utf-8")
    except OSError:
        pass


def stamp() -> tuple[float, int] | None:
    """Changes whenever the store does - for caches that depend on the lines."""
    try:
        info = _store_path().stat()
    except OSError:
        return None
    return (info.st_mtime, info.st_size)


# ---- the API key ------------------------------------------------------------
def api_key() -> str:
    from . import mailer
    sealed = _read().get("key", "")
    try:
        return mailer.unseal(sealed) if sealed else ""
    except Exception:  # noqa: BLE001 - a key sealed on another machine
        return ""


def set_api_key(key: str) -> None:
    from . import mailer
    store = _read()
    key = "".join(key.split())
    store["key"] = mailer.seal(key) if key else ""
    _write(store)


def remaining() -> int | None:
    """Requests left this month, as the last reply said."""
    value = _read().get("remaining")
    return int(value) if isinstance(value, (int, float)) else None


# ---- fetching ---------------------------------------------------------------
@dataclass(frozen=True)
class Quote:
    """One game's line across the books."""

    away: str            # team codes
    home: str
    kickoff: str         # ISO time, UTC
    home_margin: float   # median over the books, home team's side
    books: int

    @property
    def key(self) -> str:
        return f"{self.away}@{self.home}"


def parse(events: object) -> list[Quote]:
    """The API's reply as one Quote per game.

    Each bookmaker lists both sides of the spread; the home side's "point"
    is minus its margin (-6.5 = favoured by 6.5). Books are combined by the
    median, so one stale or odd number cannot move the line.
    """
    from .predictions import team_code

    out = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        home, away = team_code(event.get("home_team")), team_code(event.get("away_team"))
        if not home or not away:
            continue
        margins = []
        for book in event.get("bookmakers") or []:
            for market in (book or {}).get("markets") or []:
                if (market or {}).get("key") != "spreads":
                    continue
                for outcome in market.get("outcomes") or []:
                    point = outcome.get("point")
                    if team_code(outcome.get("name")) == home and isinstance(point, (int, float)):
                        margins.append(-float(point))
        if margins:
            out.append(Quote(
                away=away, home=home, kickoff=str(event.get("commence_time", "")),
                home_margin=round(statistics.median(margins), 2), books=len(margins),
            ))
    return out


def fetch(key: str, *, opener=None) -> tuple[list[Quote], int | None]:
    """(every game on the board, requests left this month). Raises OddsError."""
    if not key:
        raise OddsError("No Odds API key yet - add one under the ⚙ button.")
    query = urllib.parse.urlencode({
        "apiKey": key, "regions": "us", "markets": "spreads",
        "oddsFormat": "american", "dateFormat": "iso",
    })
    request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": "ACQL-Dashboard"})
    open_url = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    try:
        with open_url(request) as reply:
            body = reply.read().decode("utf-8")
            left = reply.headers.get("x-requests-remaining") if reply.headers else None
    except urllib.error.HTTPError as exc:
        try:
            said = exc.read().decode("utf-8", "replace").casefold()
        except Exception:  # noqa: BLE001
            said = ""
        if any(word in said for word in ("quota", "credit", "usage")):
            raise OddsError(
                "Out of Odds API requests for this month - the free plan allows "
                "500. The lines already stored are still used."
            ) from exc
        if exc.code == 401:
            raise OddsError("The Odds API didn't accept the key. Check it under ⚙.") from exc
        if exc.code == 429:
            raise OddsError("The Odds API asked to slow down. Try again in a minute.") from exc
        raise OddsError(f"The Odds API said no ({exc.code}). Try again in a minute.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise OddsError(f"Couldn't reach The Odds API ({getattr(exc, 'reason', exc)}). "
                        "Check the connection and try again.") from exc
    try:
        events = json.loads(body)
    except ValueError as exc:
        raise OddsError("The Odds API sent back something that wasn't odds.") from exc
    try:
        left_n = int(float(left)) if left is not None else None
    except ValueError:
        left_n = None
    return parse(events), left_n


# ---- which games belong to a week -------------------------------------------
def week_pairs(season, week: int) -> list[tuple[str, str]]:
    """(away code, home code) for the week: the workbook's slate, else the schedule."""
    from . import schedule
    from .predictions import team_code

    found = season.weeks.get(week) if season is not None else None
    if found is not None and found.games:
        pairs = [(team_code(g.away), team_code(g.home)) for g in found.games]
        pairs = [p for p in pairs if all(p)]
        if pairs:
            return pairs
    return [(a.lower(), h.lower()) for a, h in schedule.pairings(week)]


@dataclass
class Update:
    week: int
    at: float
    matched: int = 0
    missing: list[str] = field(default_factory=list)      # games with no line yet
    moved: list[tuple[str, float, float]] = field(default_factory=list)   # (game, before, now)
    remaining: int | None = None

    def summary(self) -> str:
        from .predictions import display_team
        if not self.matched:
            return (f"No week {self.week} lines on the board yet - books usually "
                    "post the next week's games on Sunday night.")
        text = f"Updated {self.matched} week {self.week} line{'s' if self.matched != 1 else ''}"
        if self.moved:
            text += f"; {len(self.moved)} moved since the last update"
        if self.missing:
            text += f"; {len(self.missing)} not posted yet"
        return text + "."


def update(week: int, quotes: list[Quote], pairs: list[tuple[str, str]],
           remaining_requests: int | None = None, now: float | None = None) -> Update:
    """Store this week's lines from a fetch. Only games on the week's slate count.

    A pair that meets twice in a season (division games) is matched to the
    earliest kickoff on the board, which is the one this week.
    """
    from .predictions import display_matchup

    now = time.time() if now is None else now
    wanted = {f"{a}@{h}" for a, h in pairs}
    best: dict[str, Quote] = {}
    for q in quotes:
        if q.key in wanted and (q.key not in best or q.kickoff < best[q.key].kickoff):
            best[q.key] = q

    store = _read()
    weeks = store.setdefault("weeks", {})
    entry = weeks.setdefault(str(week), {"opening": {}, "latest": {}, "history": []})
    result = Update(week=week, at=now, remaining=remaining_requests)
    lines = {}
    for key, q in best.items():
        before = entry["latest"].get(key)
        entry["opening"].setdefault(key, q.home_margin)
        entry["latest"][key] = q.home_margin
        lines[key] = q.home_margin
        away, home = key.split("@")
        if before is not None and abs(before - q.home_margin) >= 0.5:
            result.moved.append((display_matchup(away, home), float(before), q.home_margin))
    result.matched = len(best)
    result.missing = [display_matchup(*k.split("@")) for k in sorted(wanted - set(best))]
    if lines:
        entry["at"] = now
        entry.setdefault("kickoff", {}).update({k: q.kickoff for k, q in best.items()})
        entry["history"] = (entry.get("history") or [])[-(KEEP_HISTORY - 1):] + [
            {"at": now, "lines": lines}
        ]
    if remaining_requests is not None:
        store["remaining"] = remaining_requests
    store["checked"] = now
    _write(store)
    return result


# ---- reading it back ----------------------------------------------------------
@dataclass(frozen=True)
class Stored:
    at: float
    opening: dict[str, float]
    latest: dict[str, float]
    history: list[tuple[float, dict[str, float]]]


def stored(week: int) -> Stored | None:
    entry = (_read().get("weeks") or {}).get(str(week))
    if not isinstance(entry, dict) or not entry.get("latest"):
        return None
    history = [
        (float(h.get("at", 0)), {k: float(v) for k, v in (h.get("lines") or {}).items()})
        for h in entry.get("history") or [] if isinstance(h, dict)
    ]
    return Stored(
        at=float(entry.get("at", 0)),
        opening={k: float(v) for k, v in entry.get("opening", {}).items()},
        latest={k: float(v) for k, v in entry.get("latest", {}).items()},
        history=history,
    )


def lines_at(week: int, when: float) -> dict[str, float]:
    """The latest line for each game as of a moment (for "since you saved")."""
    found = stored(week)
    if found is None:
        return {}
    out: dict[str, float] = {}
    for at, lines in found.history:
        if at <= when:
            out.update(lines)
    return out


def overlay(week: int, forecasts: list, imported: float) -> list:
    """The week's predictions with the fetched lines laid on top.

    A fetched line newer than the predictions file replaces its market
    number; the file's opening line stays if it has one. Games the file
    doesn't have (or every game, with no file) come in on the line alone.
    """
    from dataclasses import replace

    from .predictions import DISPLAY, Forecast, team_code

    found = stored(week)
    if found is None:
        return forecasts
    newer = found.at > float(imported or 0)
    out, seen = [], set()
    for f in forecasts:
        key = f"{team_code(f.road)}@{team_code(f.home)}"
        seen.add(key)
        if key in found.latest and newer:
            opening = f.opening if f.opening is not None else (
                f.market if f.market is not None else found.opening.get(key)
            )
            f = replace(f, market=found.latest[key], opening=opening)
        out.append(f)
    for key, margin in found.latest.items():
        if key in seen:
            continue
        away, home = key.split("@")
        out.append(Forecast(
            road=DISPLAY.get(away, away), home=DISPLAY.get(home, home),
            market=margin, opening=found.opening.get(key, margin),
        ))
    return out


def movements(week: int, since: float | None = None) -> list[tuple[str, float, float]]:
    """(game, then, now) for every line that has moved BIG_MOVE or more.

    `since` compares with the lines as they stood then; otherwise with the
    opening number.
    """
    from .predictions import display_matchup

    found = stored(week)
    if found is None:
        return []
    then = lines_at(week, since) if since is not None else found.opening
    out = []
    for key, now in found.latest.items():
        before = then.get(key)
        if before is not None and abs(now - before) >= BIG_MOVE:
            out.append((display_matchup(*key.split("@")), before, now))
    out.sort(key=lambda m: -abs(m[2] - m[1]))
    return out


def describe_margin(game_label: str, home_margin: float) -> str:
    """"Kansas City -6.5" style, from the home side's margin."""
    away, _, home = game_label.partition(" @ ")
    if abs(home_margin) < 0.25:
        return "pick'em"
    team = home if home_margin > 0 else away
    return f"{team} -{abs(home_margin):g}"
