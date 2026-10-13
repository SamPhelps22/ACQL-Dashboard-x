"""Game results, fetched by the dashboard itself.

Everything the workbook used to be typed up from is on the commissioner's
pick sheet - the games, the pool's lines, every coach's picks, their Big
Losers and suicide picks - except how each game came out. That went into
the workbook's Result row by hand, a team at a time, with the pool's line
worked out in your head.

ESPN publishes every NFL score on an open scoreboard (the one the pool
website's live view reads), so the dashboard asks it. A final score and the
pool's line settle the credited side by the pool's own rule - the favourite
must win by at least the line, a win by exactly the line counting - and the
margin settles each Big Loser (beaten by 15 or more).

A finished game never changes, so each one is kept once it has been seen
and the scoreboard is only asked about weeks with games still to finish. A
graded pick sheet, when there is one, is the commissioner's own word and
outranks all of this (picks.attach): a difference between the two is
reported rather than settled here.
"""

from __future__ import annotations

import calendar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta

from ..models import Game, same_team
from ..model.predictions import team_code

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
TIMEOUT = 10
#: The most one round of asking may take; the weeks left wait for the next.
BUDGET_S = 25
#: Where fetched scores are kept: one document a week, "2026-4".
KIND = "results"
#: Never ask about the same week more often than this, however often the
#: dashboard reloads (it reloads whenever a file in the folder changes).
RECHECK_S = 5 * 60
#: ...except while the Game Day page is open and a game is on: the score is
#: what is being watched, so it is asked for every minute.
LIVE_RECHECK_S = 60
#: A week whose games are all still to kick off is looked at this often -
#: only to keep its fixtures and betting lines current.
FIXTURES_RECHECK_S = 6 * 3600
#: A Big Loser has to lose by this many or more.
BLOWOUT = 15
#: What a finished game nobody was credited with is recorded as: an unlined
#: game that ended level. Every pick on it is wrong, and it still counts as
#: played, so the week can finish.
TIE = "Tie"
#: ESPN's own abbreviations that aren't the pool's.
ESPN_CODES = {"wsh": "was", "la": "lar", "jac": "jax", "lvr": "lv", "oak": "lv",
              "sd": "lac", "stl": "lar"}


class ResultsError(Exception):
    """The scoreboard couldn't be read; the message says why, in words."""


@dataclass(frozen=True)
class Score:
    """One game as the scoreboard has it. Teams are the pool's codes, and home
    is ESPN's home team - which a neutral-site game may have the other way
    round from the pick sheet (`find` sorts that out)."""

    away: str
    home: str
    away_points: int | None = None
    home_points: int | None = None
    state: str = "pre"              # "pre", "in" or "post"
    final: bool = False             # over, with a result that stands
    kickoff: float | None = None    # seconds since 1970, UTC
    detail: str = ""                # "Final", "Final/OT", "Q3 4:12", "Postponed"
    #: The betting line as ESPN's home team's expected margin, when it shows one.
    home_spread: float | None = None
    #: Postponed or cancelled: over without a result.
    called_off: bool = False
    # ---- while a game is on (Game Day) - kept as last seen, blank otherwise ----
    period: int = 0                 # 1-4, 5 for overtime
    clock: float | None = None      # seconds left in the period
    possession: str = ""            # the pool's code for the team with the ball
    situation: str = ""             # "2nd & 7 at ATL 23"
    red_zone: bool = False
    last_play: str = ""
    broadcast: str = ""             # "CBS", "Prime Video"
    away_record: str = ""           # "3-2"
    home_record: str = ""
    away_color: str = ""            # "#002244"
    home_color: str = ""
    #: ESPN's id for the game, which its play-by-play is asked for by (timeline.py).
    event: str = ""
    #: Where it is played, for the forecast (weather.py): the stadium, its
    #: "City, State", and whether there is a roof over it (None: not said).
    venue: str = ""
    city: str = ""
    indoor: bool | None = None


# ---- reading the scoreboard ------------------------------------------------------
def _code(abbr: object) -> str:
    text = str(abbr or "").strip().casefold()
    text = ESPN_CODES.get(text, text)
    return team_code(text)


def _points(value: object) -> int | None:
    """A score as the scoreboard writes it: "24", 24, or {"value": 24.0}."""
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return None


STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?")


def _kickoff(text: object) -> float | None:
    """"2026-09-13T17:00Z" as seconds since 1970 (the scoreboard writes UTC)."""
    found = STAMP.match(str(text or ""))
    if not found:
        return None
    y, mo, d, h, mi, s = (int(v) if v else 0 for v in found.groups())
    try:
        return float(calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0)))
    except (OverflowError, ValueError):
        return None


ODDS = re.compile(r"^\s*([A-Za-z]{2,4})\s+(-?\d+(?:\.\d+)?)")


def _home_spread(odds: object, home: str, away: str) -> float | None:
    """"BUF -8.5" as the home side's expected margin (+8.5 when Buffalo is at home)."""
    first = (odds or [{}])[0] if isinstance(odds, list) else {}
    details = str((first or {}).get("details") or "")
    if re.match(r"^\s*even", details, re.IGNORECASE):
        return 0.0
    found = ODDS.match(details)
    if not found:
        return None
    favourite, points = _code(found.group(1)), abs(float(found.group(2)))
    if favourite == home:
        return points
    if favourite == away:
        return -points
    return None


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _color(team: object) -> str:
    """ESPN's colour for a team ("002244") as "#002244", or "" if it has none."""
    raw = str((team or {}).get("color") or "").strip().lstrip("#") if isinstance(team, dict) else ""
    return f"#{raw.lower()}" if re.fullmatch(r"[0-9A-Fa-f]{6}", raw) else ""


def _record(side: object) -> str:
    """A team's overall record, "3-2", from a competitor."""
    for entry in (side or {}).get("records") or [] if isinstance(side, dict) else []:
        if isinstance(entry, dict) and str(entry.get("type") or entry.get("name") or "") in ("total", "overall"):
            return _text(entry.get("summary"))
    return ""


def _broadcast(comp: dict) -> str:
    """The TV network(s) showing a game: "CBS", "FOX / NFLN"."""
    names: list[str] = []
    for entry in comp.get("broadcasts") or []:
        if isinstance(entry, dict):
            names += [_text(n) for n in entry.get("names") or [] if _text(n)]
    if not names:
        for entry in comp.get("geoBroadcasts") or []:
            media = (entry or {}).get("media") or {} if isinstance(entry, dict) else {}
            name = _text(media.get("shortName"))
            if name:
                names.append(name)
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return " / ".join(seen[:2])


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse(payload: object) -> list[Score]:
    """Every game on a scoreboard page. Anything it can't make sense of is
    left out rather than guessed at."""
    out: list[Score] = []
    events = payload.get("events") if isinstance(payload, dict) else None
    for event in events or []:
        if not isinstance(event, dict):
            continue
        comps = event.get("competitions") or [{}]
        comp = comps[0] if isinstance(comps[0], dict) else {}
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, dict)}
        if "home" not in sides or "away" not in sides:
            continue
        home = _code((sides["home"].get("team") or {}).get("abbreviation"))
        away = _code((sides["away"].get("team") or {}).get("abbreviation"))
        if not home or not away or home == away:
            continue
        status = comp.get("status") or event.get("status") or {}
        kind = status.get("type") or {}
        state = str(kind.get("state") or "pre")
        home_points = _points(sides["home"].get("score"))
        away_points = _points(sides["away"].get("score"))
        # Postponed or cancelled: the scoreboard calls it over, but nothing
        # was decided, so it is a game still to be played.
        called_off = state == "post" and kind.get("completed") is False
        final = state == "post" and not called_off and home_points is not None and away_points is not None
        detail = str(kind.get("shortDetail") or kind.get("detail") or "")
        if called_off:
            state = "pre"
            detail = detail or "Postponed"
        # Who has the ball, where, and what just happened - only while it's on.
        situation = comp.get("situation") if state == "in" else None
        situation = situation if isinstance(situation, dict) else {}
        holder = str(situation.get("possession") or "")
        possession = next((code for code, side in ((home, sides["home"]), (away, sides["away"]))
                           if holder and holder in (str(side.get("id") or ""),
                                                    str((side.get("team") or {}).get("id") or ""))), "")
        last_play = situation.get("lastPlay") if isinstance(situation.get("lastPlay"), dict) else {}
        period = _number(status.get("period")) if state == "in" else None
        clock = _number(status.get("clock")) if state == "in" else None
        out.append(Score(
            away=away, home=home,
            away_points=away_points if state != "pre" else None,
            home_points=home_points if state != "pre" else None,
            state=state, final=final,
            kickoff=_kickoff(comp.get("date") or event.get("date")),
            detail=detail,
            home_spread=_home_spread(comp.get("odds"), home, away),
            called_off=called_off,
            period=int(period) if period else 0,
            clock=clock,
            possession=possession,
            situation=_text(situation.get("downDistanceText") or situation.get("shortDownDistanceText")),
            red_zone=bool(situation.get("isRedZone")),
            last_play=_text(last_play.get("text"))[:160],
            broadcast=_broadcast(comp),
            away_record=_record(sides["away"]),
            home_record=_record(sides["home"]),
            away_color=_color(sides["away"].get("team")),
            home_color=_color(sides["home"].get("team")),
            event=str(event.get("id") or comp.get("id") or ""),
            **_venue(comp),
        ))
    return out


def _venue(comp: dict) -> dict:
    """The stadium, its city and its roof, as the scoreboard gives them."""
    venue = comp.get("venue") if isinstance(comp.get("venue"), dict) else {}
    address = venue.get("address") if isinstance(venue.get("address"), dict) else {}
    place = ", ".join(_text(address.get(k)) for k in ("city", "state", "country") if _text(address.get(k)))
    indoor = venue.get("indoor")
    return {"venue": _text(venue.get("fullName")), "city": place,
            "indoor": indoor if isinstance(indoor, bool) else None}


def fetch(year: int, week: int, opener=None) -> list[Score]:
    """One week of the regular season from ESPN's scoreboard."""
    query = urllib.parse.urlencode({"seasontype": 2, "week": int(week), "dates": int(year)})
    request = urllib.request.Request(
        f"{SCOREBOARD}?{query}",
        headers={"User-Agent": "ACQL-Dashboard", "Accept": "application/json"},
    )
    open_url = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    try:
        with open_url(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ResultsError(f"ESPN's scoreboard answered with an error ({exc.code})") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ResultsError("ESPN's scoreboard can't be reached - is the internet connected?") from exc
    except ValueError as exc:
        raise ResultsError("ESPN's scoreboard sent back something that isn't a scoreboard") from exc
    return parse(payload)


# ---- keeping them ------------------------------------------------------------------
def _key(year: int, week: int) -> str:
    return f"{int(year)}-{int(week)}"


def _stored(year: int, week: int) -> dict:
    from .. import store
    try:
        raw = store.get(KIND, _key(year, week), {})
    except store.StoreError:
        return {}
    return raw if isinstance(raw, dict) else {}


def load(year: int, week: int) -> list[Score]:
    """The scores kept for a week (nothing fetched)."""
    out = []
    for row in _stored(year, week).get("scores") or []:
        if not isinstance(row, dict):
            continue
        try:
            out.append(Score(**{k: row.get(k) for k in Score.__dataclass_fields__ if k in row}))
        except TypeError:
            continue
    return out


def checked_at(year: int, week: int) -> float | None:
    """When the scoreboard was last asked about a week (None: never)."""
    at = _stored(year, week).get("at")
    return float(at) if isinstance(at, (int, float)) else None


def save(year: int, week: int, scores: list[Score], at: float | None = None) -> None:
    """Keep a week's scores. A game already final stays as it was kept - a
    later look that leaves it out, or has it in a worse state, never loses it."""
    from .. import store
    before = {frozenset((s.away, s.home)): s for s in load(year, week)}
    if scores:
        # the scoreboard's word on the week's games, but a final never goes back
        merged = {frozenset((s.away, s.home)): s for s in scores}
        for pair, score in before.items():
            if score.final:
                fresh = merged.get(pair)
                if fresh is not None and fresh.event and not score.event:
                    score = replace(score, event=fresh.event)   # kept as it was, now with its id
                merged[pair] = score
    else:
        merged = before         # an answer with nothing in it says nothing
    try:
        store.put(KIND, _key(year, week), {
            "at": time.time() if at is None else at,
            "scores": [asdict(s) for s in merged.values()],
        })
    except store.StoreError:
        pass
    # Each game's line as the scoreboard has it, for as long as it shows one:
    # the closing line every pick is measured against afterwards (closing.py).
    if scores:
        try:
            from ..model import closing
            closing.capture(year, week, scores, at)
        except Exception:  # noqa: BLE001 - the scores are kept either way
            pass


def find(scores: list[Score], away: str, home: str) -> tuple[Score | None, bool]:
    """The scoreboard's game for a matchup, and whether the scoreboard has it
    the other way round (a neutral site)."""
    a, h = team_code(away), team_code(home)
    if not a or not h:
        return None, False
    for score in scores:
        if {score.away, score.home} == {a, h}:
            return score, score.home != h
    return None, False


# ---- what a result means in this pool ---------------------------------------------
def points(game: Game, score: Score) -> tuple[int, int] | None:
    """(home points, away points) with home being the pick sheet's home team."""
    if score.home_points is None or score.away_points is None:
        return None
    flipped = score.home != team_code(game.home)
    return ((score.away_points, score.home_points) if flipped
            else (score.home_points, score.away_points))


def credited(game: Game, home_points: int, away_points: int) -> str:
    """The side the pool credits with a finished game, as the slate writes it.

    A lined game always has one: the favourite if it won by at least the line
    (a win by exactly the line counts), the underdog otherwise. An unlined
    game goes to the winner, and a tie to nobody (TIE).
    """
    from ..analytics import line_need
    margin = home_points - away_points
    if game.line is not None and game.line_favourite:
        favourite_home = same_team(game.line_favourite, game.home)
        favourite_by = margin if favourite_home else -margin
        favourite = game.home if favourite_home else game.away
        underdog = game.away if favourite_home else game.home
        return favourite if favourite_by >= line_need(game.line) else underdog
    if margin > 0:
        return game.home
    if margin < 0:
        return game.away
    return TIE


def lost_by(game: Game, team: str) -> int | None:
    """How many points a team lost its game by (negative: it won), once the
    game has its scores on it. None when it hasn't or the team isn't in it."""
    if game.home_points is None or game.away_points is None:
        return None
    if same_team(team, game.home) or team_code(team) == team_code(game.home):
        return game.away_points - game.home_points
    if same_team(team, game.away) or team_code(team) == team_code(game.away):
        return game.home_points - game.away_points
    return None


def apply(game: Game, scores: list[Score]) -> str:
    """Put a finished game's score on it, and its result if it has none.

    Returns the credited side the score gives ("" when the game isn't
    finished), so a caller holding another source can compare.
    """
    score, _ = find(scores, game.away, game.home)
    if score is None or not score.final:
        return ""
    both = points(game, score)
    if both is None:
        return ""
    game.home_points, game.away_points = both
    side = credited(game, *both)
    if not str(game.winner or "").strip():
        game.winner = side
        game.result_from = "ESPN"
    return side


# ---- which weeks are worth asking about ---------------------------------------------
def season_year(season=None, now: float | None = None) -> int:
    """The NFL season being played: the one the load settled on, else the
    year in the season's title ("ACQL 2026"), else the calendar's - January's
    games belong to the autumn before."""
    settled = getattr(season, "results_year", 0)
    if isinstance(settled, int) and settled > 2000:
        return settled
    title = str(getattr(season, "title", "") or "")
    found = re.search(r"(?<!\d)(20\d{2})(?!\d)", title)
    if found:
        return int(found.group(1))
    moment = time.localtime(time.time() if now is None else now)
    return moment.tm_year - 1 if moment.tm_mon < 6 else moment.tm_year


def wednesday(year: int, week: int) -> date:
    """The Wednesday a week of the season begins: the one after Labor Day
    (the first Monday of September), a week further on for each week."""
    day = date(int(year), 9, 1)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day + timedelta(days=2) + timedelta(weeks=int(week) - 1)


def week_starts(year: int, week: int) -> float:
    """Early enough for a week's first game: its Wednesday, at midnight UTC."""
    return float(calendar.timegm(wednesday(year, week).timetuple()))


def calendar_weeks(year: int, now: float | None = None) -> list[int]:
    """The week the calendar is in and the one after it - the weeks whose
    fixtures are worth having now, sheet or no sheet: the next first kickoff
    is when that week's odds lock (oddslock.py). Week 1 before the season."""
    now = time.time() if now is None else now
    current = max((w for w in range(1, 19) if week_starts(year, w) <= now), default=0)
    return [w for w in (current, current + 1) if 1 <= w <= 18]


def unfinished(year: int, week: int, pairs: list[tuple[str, str]]) -> int:
    """How many of these games aren't final in what is kept for the week."""
    kept = load(year, week)
    left = 0
    for away, home in pairs:
        score, _ = find(kept, away, home)
        if score is None or not score.final:
            left += 1
    return left


#: How long after a week starts a postponed game is still looked out for.
POSTPONED_WATCH_S = 14 * 86400


def over(year: int, week: int) -> bool:
    """Whether every game the scoreboard listed for a week is final - the
    week is done and never needs asking about again. A postponed game keeps
    it open: it may yet be played (on a Tuesday, say) in the same week."""
    kept = load(year, week)
    return bool(kept) and all(s.final for s in kept)


def due(year: int, weeks, *, now: float | None = None, force: bool = False,
        every: float | None = None) -> list[int]:
    """Weeks worth asking the scoreboard about now.

    * A week that's over isn't asked about again.
    * A week with a game kicked off and not yet final: every few minutes -
      every `every` seconds instead while the Game Day page is watching.
    * A week with nothing kicked off yet: every few hours, to keep its
      fixtures and lines current - and once its first game is due.
    * A week whose only open games were postponed: every few hours, for a
      new date, for two weeks.
    """
    now = time.time() if now is None else now
    out = []
    for week in sorted(set(int(w) for w in weeks)):
        if not 1 <= week <= 18 or over(year, week):
            continue
        kept = load(year, week)
        last = checked_at(year, week)
        if force or last is None:
            out.append(week)
            continue
        open_games = [s for s in kept if not (s.final or s.called_off)]
        started = [s for s in open_games if s.kickoff is None or s.kickoff <= now]
        live = every or RECHECK_S
        if not kept:
            under_way = now >= week_starts(year, week) - 86400
            wait = RECHECK_S if under_way else FIXTURES_RECHECK_S
        elif started:
            wait = live
        elif not open_games:
            # only postponed games left: a new date, now and then, for a while
            if now > week_starts(year, week) + POSTPONED_WATCH_S:
                continue
            wait = FIXTURES_RECHECK_S
        else:
            # nothing left has kicked off: ask again at the next kickoff, or
            # in a few hours for the fixtures, whichever comes first
            first = min((s.kickoff for s in open_games if s.kickoff), default=None)
            if first is not None and last < first <= now:
                out.append(week)
                continue
            wait = FIXTURES_RECHECK_S
        if now - last >= wait:
            out.append(week)
    return out


def refresh(year: int, weeks, *, now: float | None = None,
            force: bool = False, fetcher=None, every: float | None = None) -> tuple[list[int], list[str]]:
    """Ask the scoreboard about every week that's due; keep what it says.

    Returns (the weeks it got, what went wrong in words). One failure ends
    the round - a missing connection fails every week the same way, and one
    line saying so is enough.
    """
    get = fetcher or fetch
    got, problems = [], []
    moment = time.time() if now is None else now
    # The week being played first, then the ones before it, newest first;
    # weeks still to come (only their fixtures) last.
    wanted = sorted(due(year, weeks, now=now, force=force, every=every),
                    key=lambda w: (moment < week_starts(year, w) - 86400, -w))
    started = time.monotonic()
    for week in wanted:
        if got and time.monotonic() - started > BUDGET_S:
            break               # ESPN is slow today: the rest next time
        try:
            scores = get(year, week)
        except ResultsError as exc:
            problems.append(f"Results for week {week}: {exc}")
            _note_failure(moment, str(exc))
            break
        except Exception as exc:  # noqa: BLE001 - never stop a load over this
            problems.append(f"Results for week {week} couldn't be read ({exc})")
            _note_failure(moment, str(exc))
            break
        save(year, week, scores, now)
        got.append(week)
    if got:
        _note_failure(None)
    return got, problems


#: Where the last failed look at the scoreboard is kept, cleared by the next good one.
FAILURE_KIND, FAILURE_KEY = "results-meta", "failure"


def _note_failure(at: float | None, why: str = "") -> None:
    try:
        from .. import store
        if at is None:
            if store.get(FAILURE_KIND, FAILURE_KEY):
                store.delete(FAILURE_KIND, FAILURE_KEY)
        else:
            store.put(FAILURE_KIND, FAILURE_KEY, {"at": float(at), "why": why[:200]})
    except Exception:  # noqa: BLE001 - bookkeeping only
        pass


def unreachable_since(now: float | None = None, within: float = 6 * 3600) -> float | None:
    """When the scoreboard last couldn't be reached, if that's the latest word
    on it and recent (None otherwise)."""
    try:
        from .. import store
        kept = store.get(FAILURE_KIND, FAILURE_KEY)
    except Exception:  # noqa: BLE001
        return None
    at = kept.get("at") if isinstance(kept, dict) else None
    if not isinstance(at, (int, float)):
        return None
    now = time.time() if now is None else now
    return float(at) if now - at <= within else None


def summary(year: int, week: int, pairs: list[tuple[str, str]]) -> str:
    """"14 of 16 final · checked 9:42 PM" for a week's slate."""
    if not pairs:
        return ""
    left = unfinished(year, week, pairs)
    done = len(pairs) - left
    at = checked_at(year, week)
    when = ""
    if at:
        moment = time.localtime(at)
        hour = moment.tm_hour % 12 or 12
        today = time.localtime()
        day = "" if moment.tm_yday == today.tm_yday and moment.tm_year == today.tm_year else time.strftime("%a ", moment)
        when = f" · checked {day}{hour}:{moment.tm_min:02d} {'AM' if moment.tm_hour < 12 else 'PM'}"
    return f"{done} of {len(pairs)} final{when}"
