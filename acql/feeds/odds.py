"""Betting lines, fetched instead of typed.

Every number the dashboard gives - the card, the chance of winning the week,
the suicide helper, the luck meter - starts from the betting line. Typing
sixteen spreads a week is a chore, and a line typed on Tuesday is stale by
Sunday: the market moves on injury news, and a quarterback ruled out on
Friday can move a game four or five points.

This fetches the current NFL lines from The Odds API (the-odds-api.com) -
the spread, the moneyline and the total for every game. Its free plan is 500
requests a month and each of those three counts as one, so a press of
"Update lines" is three: about five a day all season.

What is kept, per week, in the app's database (store.py):

    opening    the first number seen for each game
    latest     the most recent one, the median over every bookmaker quoted
    win        the home side's chance of winning outright, from the moneylines
               (each book's two prices with its margin taken out, then the median)
    total      the points the books expect the two teams to score between them
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
import math
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace

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
def _read() -> dict:
    """A private copy of everything kept here, safe to change before `_write`."""
    from .. import store
    return json.loads(json.dumps(store.items("odds")))


def _write(mapping: dict) -> None:
    from .. import store
    try:
        store.replace("odds", mapping)
    except store.StoreError:
        pass


def stamp() -> tuple:
    """Changes whenever the lines do - for caches that depend on them."""
    from .. import store
    return store.stamp("odds")


# ---- the API key ------------------------------------------------------------
def api_key() -> str:
    from ..site import mailer
    env_key = os.environ.get("ACQL_ODDS_API_KEY", "").strip()   # GitHub's cloud job
    if env_key:
        return env_key
    sealed = _read().get("key", "")
    try:
        return mailer.unseal(sealed) if sealed else ""
    except Exception:  # noqa: BLE001 - a key sealed on another machine
        return ""


def set_api_key(key: str) -> None:
    from ..site import mailer
    store = _read()
    key = "".join(key.split())
    store["key"] = mailer.seal(key) if key else ""
    _write(store)


def remaining() -> int | None:
    """Requests left this month, as the last reply said."""
    value = _read().get("remaining")
    return int(value) if isinstance(value, (int, float)) else None


def budget_forecast(now: float | None = None, log: list | None = None) -> tuple[int, float, int] | None:
    """(projected requests left at month's end, the month's end, requests used a day)
    at this month's pace (#42) - None until the month has two readings a day or more apart.
    The allowance is taken to start again on the 1st."""
    import calendar
    import datetime as _dt
    now = time.time() if now is None else now
    log = _read().get("left_log") if log is None else log
    today = _dt.datetime.fromtimestamp(now)
    start = _dt.datetime(today.year, today.month, 1).timestamp()
    end = _dt.datetime(today.year, today.month, calendar.monthrange(today.year, today.month)[1], 23, 59).timestamp()
    month = [(float(t), int(n)) for t, n in (log or []) if start <= float(t) <= now]
    if len(month) < 2 or month[-1][0] - month[0][0] < 86400:
        return None
    used = max(0, month[0][1] - month[-1][1])
    per_day = used / ((month[-1][0] - month[0][0]) / 86400)
    projected = month[-1][1] - per_day * max(0.0, (end - now) / 86400)
    return int(round(projected)), end, int(round(per_day))


# ---- fetching ---------------------------------------------------------------
@dataclass(frozen=True)
class Quote:
    """One game's line across the books."""

    away: str            # team codes
    home: str
    kickoff: str         # ISO time, UTC
    home_margin: float   # median over the books, home team's side
    books: int
    home_win: float | None = None    # the moneylines' chance the home side wins outright
    total: float | None = None       # the over/under
    source: str = ""                  # set when the backup (OddsPapi) gave it

    @property
    def key(self) -> str:
        return f"{self.away}@{self.home}"


def _moment(iso: object) -> float | None:
    """Seconds since 1970 from the API's ISO time, or None if it isn't one."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def parse(events: object) -> list[Quote]:
    """The API's reply as one Quote per game.

    Each bookmaker lists both sides of the spread; the home side's "point"
    is minus its margin (-6.5 = favoured by 6.5). Books are combined by the
    median, so one stale or odd number cannot move the line.
    """
    from ..model.predictions import team_code

    out = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        home, away = team_code(event.get("home_team")), team_code(event.get("away_team"))
        if not home or not away:
            continue
        margins, wins, totals = [], [], []
        for book in event.get("bookmakers") or []:
            for market in (book or {}).get("markets") or []:
                kind, outcomes = (market or {}).get("key"), (market or {}).get("outcomes") or []
                if kind == "spreads":
                    for outcome in outcomes:
                        point = outcome.get("point")
                        if team_code(outcome.get("name")) == home and isinstance(point, (int, float)):
                            margins.append(-float(point))
                elif kind == "h2h":
                    # a book's two prices add up to more than 100%: its margin
                    # comes out before its opinion is counted
                    implied = {team_code(o.get("name")): _implied(o.get("price")) for o in outcomes}
                    ours, theirs = implied.get(home), implied.get(away)
                    if ours and theirs:
                        wins.append(ours / (ours + theirs))
                elif kind == "totals":
                    for outcome in outcomes:
                        point = outcome.get("point")
                        if str(outcome.get("name", "")).casefold() == "over" and isinstance(point, (int, float)):
                            totals.append(float(point))
        if margins:
            out.append(Quote(
                away=away, home=home, kickoff=str(event.get("commence_time", "")),
                home_margin=round(statistics.median(margins), 2), books=len(margins),
                home_win=round(statistics.median(wins), 4) if wins else None,
                total=round(statistics.median(totals), 1) if totals else None,
            ))
    return out


def _implied(price: object) -> float | None:
    """The chance an American price implies: -150 is 60%, +130 is 43.5%.

    None for anything that is not a real American price - a number, finite,
    and at least 100 either way (+100 and -100 are both even money). A +50
    or -50 is a decimal or a typo, and read as American it would pass for a
    plausible 67% or 33%; dropped here, that book simply isn't counted.
    """
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    if not math.isfinite(price) or abs(price) < 100:
        return None
    return -price / (-price + 100) if price < 0 else 100 / (price + 100)


def fetch(key: str, *, opener=None) -> tuple[list[Quote], int | None]:
    """(every game on the board, requests left this month). Raises OddsError."""
    if not key:
        raise OddsError("No Odds API key yet - add one under the ⚙ button.")
    query = urllib.parse.urlencode({
        "apiKey": key, "regions": "us", "markets": "spreads,h2h,totals",
        "oddsFormat": "american", "dateFormat": "iso",
    })
    request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": "ACQL-Dashboard"})
    open_url = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    try:
        with open_url(request) as reply:
            body = reply.read().decode("utf-8")
            from .. import rawarchive
            rawarchive.keep("odds", body)
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


def fetch_any(key: str, *, opener=None, backup_opener=None, skip_main: str = "") -> tuple[list[Quote], int | None]:
    """`fetch`, with OddsPapi (oddspapi.py) as the backup.

    When The Odds API can't answer - or `skip_main` gives a reason not to ask it,
    such as the month's reserve - the lines come from OddsPapi instead, once a
    side-by-side check has shown the two agree. Those quotes carry `source`, and
    the requests-left figure returned is None so the main feed's count is untouched.
    When the main feed answers and the backup has a key but no check yet, the
    check runs then (one OddsPapi request).
    """
    from . import oddspapi
    reason = skip_main
    if not reason:
        try:
            quotes, left = fetch(key, opener=opener)
        except OddsError as exc:
            reason = str(exc)
        else:
            if oddspapi.api_key() and not oddspapi.confirmed():
                try:
                    oddspapi.confirm(quotes, opener=backup_opener)
                except OddsError:
                    pass
            return quotes, left
    if not oddspapi.ready():
        raise OddsError(reason)
    quotes, _ = oddspapi.fetch(oddspapi.api_key(), opener=backup_opener)
    note = f"from OddsPapi (Pinnacle) - {reason.rstrip('.')}"
    return [replace(q, source=note) for q in quotes], None


# ---- which games belong to a week -------------------------------------------
def week_pairs(season, week: int) -> list[tuple[str, str]]:
    """(away code, home code) for the week: the workbook's slate, else the schedule."""
    from . import schedule
    from ..model.predictions import team_code

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
    source: str = ""

    def summary(self) -> str:
        if not self.matched:
            return (f"No week {self.week} lines on the board yet - books usually "
                    "post the next week's games on Sunday night.")
        text = f"Updated {self.matched} week {self.week} line{'s' if self.matched != 1 else ''}"
        if self.moved:
            text += f"; {len(self.moved)} moved since the last update"
        if self.missing:
            text += f"; {len(self.missing)} not posted yet"
        return text + (f" ({self.source})" if self.source else "") + "."


def update(week: int, quotes: list[Quote], pairs: list[tuple[str, str]],
           remaining_requests: int | None = None, now: float | None = None) -> Update:
    """Store this week's lines from a fetch. Only games on the week's slate count.

    A pair that meets twice in a season (division games) is matched to the
    earliest kickoff on the board, which is the one this week.

    A game already under way is left out: the API quotes it live, and a
    line taken from the score at half-time (Green Bay -17.5 while trailing)
    is not a line anyone picked against.
    """
    from ..model.predictions import display_matchup

    now = time.time() if now is None else now
    wanted = {f"{a}@{h}" for a, h in pairs}
    best: dict[str, Quote] = {}
    for q in quotes:
        if q.key in wanted and (q.key not in best or q.kickoff < best[q.key].kickoff):
            best[q.key] = q
    started = {k for k, q in best.items() if (_moment(q.kickoff) or now + 1) <= now}
    for key in started:
        del best[key]

    store = _read()
    weeks = store.setdefault("weeks", {})
    entry = weeks.setdefault(str(week), {"opening": {}, "latest": {}, "history": []})
    result = Update(week=week, at=now, remaining=remaining_requests,
                    source=next((q.source for q in best.values() if q.source), ""))
    lines = {}
    for key, q in best.items():
        before = entry["latest"].get(key)
        # "opening" is the first line this app fetched, not the books' opener
        # (the key keeps its old name so stored weeks still read)
        entry["opening"].setdefault(key, q.home_margin)
        entry["latest"][key] = q.home_margin
        lines[key] = q.home_margin
        if q.home_win is not None:
            entry.setdefault("win", {})[key] = q.home_win
        if q.total is not None:
            entry.setdefault("total", {})[key] = q.total
        away, home = key.split("@")
        if before is not None and abs(before - q.home_margin) >= 0.5:
            result.moved.append((display_matchup(away, home), float(before), q.home_margin))
    result.matched = len(best)
    result.missing = [display_matchup(*k.split("@")) for k in sorted(wanted - set(best) - started)]
    if lines:
        entry["at"] = now
        entry.setdefault("kickoff", {}).update({k: q.kickoff for k, q in best.items()})
        entry["history"] = (entry.get("history") or [])[-(KEEP_HISTORY - 1):] + [
            {"at": now, "lines": lines}
        ]
    if remaining_requests is not None:
        store["remaining"] = remaining_requests
        # each reading of the allowance, for the month's pace (budget_forecast)
        store["left_log"] = (store.get("left_log") or [])[-199:] + [[now, int(remaining_requests)]]
    store["checked"] = now
    _write(store)
    return result


# ---- reading it back ----------------------------------------------------------
@dataclass(frozen=True)
class Stored:
    at: float
    opening: dict[str, float]       # the first line FETCHED for each game - see first_seen
    latest: dict[str, float]
    history: list[tuple[float, dict[str, float]]]
    win: dict[str, float] = field(default_factory=dict)      # home side's chance to win outright
    total: dict[str, float] = field(default_factory=dict)    # the over/under

    @property
    def first_seen(self) -> dict[str, float]:
        """Each game's first fetched line. Only a sportsbook opener when the
        first fetch happened to come before any move - which nothing here can
        tell - so it is never shown as "opened"."""
        return self.opening


def stored(week: int) -> Stored | None:
    """The week's lines as kept - without any taken after a game kicked off.

    Before `update` left started games out, an update pressed during
    Thursday night's game kept that game's live line as both its opening
    and its latest. Those are dropped here, so a game's latest is the last
    line seen before its kickoff, and a game only ever seen live has none
    (the predictions file's own number stands).
    """
    entry = (_read().get("weeks") or {}).get(str(week))
    if not isinstance(entry, dict) or not entry.get("latest"):
        return None
    kickoffs = {k: _moment(v) for k, v in (entry.get("kickoff") or {}).items()}
    pregame = lambda key, at: kickoffs.get(key) is None or at < kickoffs[key]
    history = [
        (at, {k: float(v) for k, v in (h.get("lines") or {}).items() if pregame(k, at)})
        for h in entry.get("history") or [] if isinstance(h, dict)
        for at in [float(h.get("at", 0))]
    ]
    opening = {k: float(v) for k, v in entry.get("opening", {}).items()}
    latest = {k: float(v) for k, v in entry.get("latest", {}).items()}
    for key, kickoff in kickoffs.items():
        seen = [at for at, _ in _entry_lines(entry, key)]
        if kickoff is None or not seen or max(seen) < kickoff:
            continue                    # never fetched after it started
        before = [lines[key] for _, lines in history if key in lines]
        if before:
            latest[key] = before[-1]
        else:
            latest.pop(key, None)
            opening.pop(key, None)
    if not latest:
        return None
    return Stored(
        at=float(entry.get("at", 0)), opening=opening, latest=latest, history=history,
        win={k: float(v) for k, v in (entry.get("win") or {}).items() if k in latest},
        total={k: float(v) for k, v in (entry.get("total") or {}).items() if k in latest},
    )


def _entry_lines(entry: dict, key: str) -> list[tuple[float, float]]:
    """(when, line) for every update of the week that quoted this game."""
    return [
        (float(h.get("at", 0)), float(h["lines"][key]))
        for h in entry.get("history") or []
        if isinstance(h, dict) and key in (h.get("lines") or {})
    ]


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

    from ..model.predictions import DISPLAY, Forecast, team_code

    found = stored(week)
    if found is None:
        return forecasts
    newer = found.at > float(imported or 0)
    out, seen = [], set()
    for f in forecasts:
        key = f"{team_code(f.road)}@{team_code(f.home)}"
        seen.add(key)
        if key in found.latest and newer:
            no_opener = f.opening is None
            opening = f.opening if not no_opener else (
                f.market if f.market is not None else found.first_seen.get(key)
            )
            f = replace(f, market=found.latest[key], opening=opening, opening_seen=f.opening_seen or no_opener)
        if key in found.latest:
            # the moneyline and the total only ever come from here
            f = replace(f, market_win=found.win.get(key), total=found.total.get(key))
        out.append(f)
    for key, margin in found.latest.items():
        if key in seen:
            continue
        away, home = key.split("@")
        out.append(Forecast(
            road=DISPLAY.get(away, away), home=DISPLAY.get(home, home),
            market=margin, opening=found.first_seen.get(key, margin), opening_seen=True,
            market_win=found.win.get(key), total=found.total.get(key),
        ))
    return out


def movements(week: int, since: float | None = None) -> list[tuple[str, float, float]]:
    """(game, then, now) for every line that has moved BIG_MOVE or more.

    `since` compares with the lines as they stood then; otherwise with the
    first line fetched (not necessarily the books' opener).
    """
    from ..model.predictions import display_matchup

    found = stored(week)
    if found is None:
        return []
    then = lines_at(week, since) if since is not None else found.first_seen
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


# every call kept as a success or a failure for odds (sourcehealth.py, #41)
from .. import sourcehealth as _sourcehealth  # noqa: E402
fetch = _sourcehealth.watched("odds", fetch)
