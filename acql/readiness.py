"""System readiness: is everything the dashboard runs on up to date?

A pick is only as good as what it was made from. Lines go stale, an injury
report from yesterday is yesterday's, a scheduled job can quietly stop - and
none of that shows on a page of confident percentages. This gathers the
state of every input into one checklist, each line saying when it was last
updated and whether that is recent enough for where the week stands:

    Data sources      scores, betting lines (and the requests left to fetch
                      them), the computer models, injuries, weather, the team
                      efficiency file, the pool's own files
    This week's card  whether every game has what pricing it needs, whether
                      Deadeye's card was kept before the first kickoff, whether
                      your own card is saved
    Automation        the scheduled jobs, the website, the card email

"Recent enough" depends on the clock: a line twelve hours old is fine on a
Monday and stale two hours before the deadline, so each check is judged
against how close the cards are to being due (the same cadence the scheduled
job fetches on, headless.py). A check that cannot be made says so rather
than passing.

Nothing here fetches anything or changes anything. No Qt here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .models import Season
from .version import MODEL_NAME

OK, NOTE, WARN, BAD = "ok", "note", "warn", "bad"
#: Worst first, for sorting and for the overall word.
ORDER = (BAD, WARN, NOTE, OK)
SOURCES, CARD, AUTOMATION = "Data sources", "This week's card", "Automation"
#: The scheduled jobs schedule.ps1 registers, and how long each may go without running.
TASKS = (("ACQL Daily", "the nightly run", 27 * 3600),
         ("ACQL Game-day poll", "the game-day check", 8 * 86400),
         ("ACQL Deadeye email", "the card email job", 8 * 86400),
         ("ACQL Training", "the weekly training run", 8 * 86400),
         ("ACQL Sunday brief", "the Sunday brief", 8 * 86400))
#: Task Scheduler's "all is well" results: done, still running, not yet run.
TASK_FINE = {0, 267009, 267011}
#: A line may be this much older than the cadence it is fetched on before it is called stale.
SLACK = 1.5
DAY = 86400.0
#: Task Scheduler and git take over a second between them to answer, and the
#: Readiness page asks on the window's thread each time it is drawn. Neither
#: answer changes from one minute to the next, so each is reused this long.
SLOW_ANSWER_S = 60.0
_REMEMBERED: dict[str, tuple[float, object]] = {}


def _remembered(key: str, make):
    """`make()`, or its answer from under SLOW_ANSWER_S ago."""
    moment = time.monotonic()
    hit = _REMEMBERED.get(key)
    if hit is not None and moment - hit[0] < SLOW_ANSWER_S:
        return hit[1]
    value = make()
    _REMEMBERED[key] = (moment, value)
    return value


def ago(seconds: float | None) -> str:
    """"just now", "12 min ago", "5 h ago", "3 days ago"."""
    if seconds is None:
        return "never"
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 36 * 3600:
        return f"{seconds / 3600:.0f} h ago"
    return f"{seconds / DAY:.0f} days ago"


def until(seconds: float) -> str:
    """"in 40 min", "in 5 h", "in 3 days" - or how long ago, once it has passed."""
    if seconds < 0:
        return ago(-seconds)
    if seconds < 90 * 60:
        return f"in {max(1.0, seconds / 60):.0f} min"
    if seconds < 36 * 3600:
        return f"in {seconds / 3600:.0f} h"
    return f"in {seconds / DAY:.0f} days"


@dataclass(frozen=True)
class Check:
    group: str
    name: str
    state: str              # OK, NOTE, WARN or BAD
    headline: str
    detail: str = ""
    at: float | None = None     # when what it describes was last updated
    fix: str = ""               # a fix the page can offer with one click (FIXES)


@dataclass(frozen=True)
class Readiness:
    checks: list[Check] = field(default_factory=list)
    week: int = 0               # the week the next card is for
    lock: float | None = None   # when that card is due
    now: float = 0.0

    def of(self, state: str) -> list[Check]:
        return [c for c in self.checks if c.state == state]

    @property
    def worst(self) -> str:
        return next((s for s in ORDER if self.of(s)), OK)

    @property
    def ready(self) -> bool:
        return not self.of(BAD) and not self.of(WARN)

    @property
    def verdict(self) -> str:
        bad, warn = len(self.of(BAD)), len(self.of(WARN))
        if bad:
            return f"{bad} thing{'' if bad == 1 else 's'} broken" + (f", {warn} to look at" if warn else "")
        if warn:
            return f"{warn} thing{'' if warn == 1 else 's'} to look at"
        return "Ready"

    def grouped(self) -> list[tuple[str, list[Check]]]:
        out = []
        for group in (SOURCES, CARD, AUTOMATION):
            rows = sorted((c for c in self.checks if c.group == group), key=lambda c: ORDER.index(c.state))
            if rows:
                out.append((group, rows))
        return out


def line_cadence(to_lock: float) -> float:
    """How often the lines are fetched, given how long until the cards are due (headless.py's rule)."""
    from . import headless
    if to_lock <= headless.LAST_HOURS:
        return float(headless.LINES_EVERY_LAST_HOURS)
    return float(headless.LINES_EVERY_LOCK_DAY if to_lock < DAY else headless.LINES_EVERY)


def freshness(age: float | None, limit: float, *, matters: bool = True) -> str:
    """OK inside the limit, WARN past it (NOTE when it doesn't matter yet), BAD if never."""
    if age is None:
        return BAD if matters else NOTE
    if age <= limit:
        return OK
    return WARN if matters else NOTE


# ---- the checks -----------------------------------------------------------------------------------
def _scores(year: int, week: int, now: float) -> Check:
    from .feeds import results
    scores = results.load(year, week)
    # the last answer with games in it - an empty or unreadable answer was
    # asked for but brought nothing, so it never makes old scores look fresh
    at = results.fetched_at(year, week)
    age = None if at is None else now - at
    live = sum(1 for s in scores if s.state == "in")
    final = sum(1 for s in scores if s.final)
    over = bool(scores) and results.over(year, week)
    down = results.unreachable_since(now)
    words = f"week {week}: {final} of {len(scores)} final" + (f", {live} being played" if live else "")
    if down is not None and (at is None or down > at):
        return Check(SOURCES, "Scores", WARN, f"ESPN couldn't be reached {ago(now - down)}",
                     f"Last read {ago(age)} - {words}. It is tried again by itself.", at)
    if over:
        return Check(SOURCES, "Scores", OK, f"Week {week} is finished - every game final", f"Read {ago(age)}.", at)
    limit = 20 * 60 if live else 13 * 3600
    state = freshness(age, limit, matters=bool(live) or not scores)
    return Check(SOURCES, "Scores", state, f"Read {ago(age)} - {words}",
                 "While games are on the scoreboard is read every few minutes, with the dashboard open or by "
                 "the game-day job." if live else "Read again by the nightly run and whenever the dashboard opens.", at)


def _slate(season: Season, week: int):
    """(the week's unplayed games, each one's price) - priced from what is stored."""
    from .model import pricing
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found is not None else []
    ctx = pricing.context(season, week, games) if games else None
    prices = {p.game.index: p for p in pricing.price_week(season, week, games, ctx)} if games else {}
    return [g for g in games if not g.played], prices, ctx


def _lines(season: Season, week: int, to_lock: float, now: float) -> list[Check]:
    from . import headless
    from .feeds import odds
    from .model import predictions
    games, prices, _ctx = _slate(season, week)
    at = predictions.market_time(week) or None
    age = None if at is None else now - at
    priced = [g for g in games if prices.get(g.index) is not None and prices[g.index].base is not None]
    missing = [g.label for g in games if g not in priced]
    out = []
    if not games:
        out.append(Check(SOURCES, "Betting lines", NOTE, f"Week {week} has no games set up yet",
                         "The slate comes from the pool's pick sheet or the NFL's schedule."))
    elif to_lock <= 0:
        out.append(Check(SOURCES, "Betting lines", OK if priced else BAD,
                         f"Locked at the deadline - {len(priced)} of {len(games)} games had a line",
                         f"Last taken {ago(age)}; nothing is fetched for a week once its cards are in.", at))
    else:
        limit = line_cadence(to_lock) * SLACK
        soon = to_lock < 3 * DAY
        state = BAD if not priced and soon else freshness(age, limit, matters=soon) if priced else NOTE
        words = (f"{len(priced)} of {len(games)} games priced, lines {ago(age)}" if priced
                 else "No lines for the week yet")
        detail = (f"Cards are due {until(to_lock)}; this close, lines are fetched every "
                  f"{line_cadence(to_lock) / 3600:g} h. ")
        if missing:
            detail += ("No line yet for " + ", ".join(missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
                       + " - books post some games late. ")
            if soon and state == OK:
                state = WARN if to_lock < 2 * DAY else NOTE
        out.append(Check(SOURCES, "Betting lines", state, words, detail.strip(), at))
    left = odds.remaining()
    if not odds.api_key():
        out.append(Check(SOURCES, "Odds requests", BAD, "No Odds API key is set",
                         "Without one the lines can only be typed in by hand (Deadeye Picks > My picks, the "
                         "button beside Update lines)."))
    elif left is None:
        out.append(Check(SOURCES, "Odds requests", NOTE, "Requests left this month: not known until the next fetch"))
    else:
        low = left <= headless.ODDS_RESERVE
        ahead = odds.budget_forecast()
        pace, short = "", False
        if ahead is not None:
            projected, end, per_day = ahead
            day = time.strftime("%b %d", time.localtime(end)).replace(" 0", " ")
            short = projected < headless.ODDS_RESERVE
            pace = (f" · at this pace (about {per_day} a day), {max(projected, 0)} left on {day}"
                    + (" - below the reserve" if short else ""))
        out.append(Check(SOURCES, "Odds requests", WARN if low or short else OK,
                         f"{left} requests left this month{pace}",
                         f"A fetch costs 3. The scheduled job stops at {headless.ODDS_RESERVE} left, keeping "
                         "those for fetching by hand." + (" It has stopped." if low else "")
                         + (" At this pace it will stop before the month ends." if short and not low else "")))
    return out


def _models(season: Season, week: int, to_lock: float, now: float) -> Check:
    games, _prices, ctx = _slate(season, week)
    forecasts = ctx.forecasts if ctx is not None else {}
    with_models = [g for g in games if len(getattr(forecasts.get(g.index), "opinions", ()) or ()) >= 3]
    if not games:
        return Check(SOURCES, "Computer models", NOTE, f"Nothing to price for week {week} yet")
    if with_models:
        state = OK if len(with_models) == len(games) or to_lock <= 0 else NOTE
        return Check(SOURCES, "Computer models", state,
                     f"The published models are in for {len(with_models)} of {len(games)} games",
                     f"From the Prediction Tracker's file; {MODEL_NAME} nudges the line by them.")
    soon = 0 < to_lock < 2 * DAY
    return Check(SOURCES, "Computer models", WARN if soon else NOTE,
                 f"No computer models for week {week} yet - {MODEL_NAME} is running on the line alone",
                 "The Prediction Tracker posts each week's file midweek; the scheduled job reads it hourly "
                 "once it is up." + (" It is usually in by now." if soon else ""))


def _injuries(to_lock: float, now: float) -> Check:
    from .feeds import injuries
    at = injuries.fetched_at() or None
    age = None if at is None else now - at
    limit = (injuries.EVERY_LOCK_DAY if 0 <= to_lock < DAY else injuries.EVERY) * 2.5
    return Check(SOURCES, "Injury report", freshness(age, limit, matters=to_lock > 0),
                 f"Read {ago(age)}" if at else "Never read",
                 "ESPN's report, read every few hours and hourly on the day the cards are due. It is where "
                 "the quarterback and injury lines under each pick come from.", at)


def _weather(year: int, week: int, to_lock: float, now: float) -> Check:
    from . import store
    kept = store.get("weather", f"{year}-{week}", {}) or {}
    at = float(kept.get("at") or 0) or None
    age = None if at is None else now - at
    outdoors = sum(1 for g in (kept.get("games") or {}).values() if not g.get("indoor"))
    near = 0 < to_lock < 5 * DAY
    return Check(SOURCES, "Weather", freshness(age, 13 * 3600, matters=near) if at or near else NOTE,
                 f"Forecast read {ago(age)} for {outdoors} outdoor game{'' if outdoors == 1 else 's'}" if at
                 else f"No forecast for week {week} yet",
                 "Forecasts only reach two weeks ahead and firm up near the game; read a few times a day.", at)


def _efficiency(year: int, week: int) -> Check:
    from .feeds import nflverse
    found = nflverse.efficiency() if nflverse.available() else None
    if found is None:
        return Check(SOURCES, "Team efficiency", NOTE, "The nflverse files are not installed",
                     "Without them the efficiency line under each pick is left out; nothing else changes.")
    behind = (week - 1) - found.week if found.season == year else 99
    words = f"Through week {found.week} of {found.season}, {len(found.teams)} teams"
    if behind <= 0:
        return Check(SOURCES, "Team efficiency", OK, words, "Each team's last eight games, from nflverse's team files.")
    return Check(SOURCES, "Team efficiency", WARN,
                 f"{words} - {'a week' if behind == 1 else f'{behind} weeks'} behind",
                 "These are files fetched by hand (data/nflverse), not read automatically: the efficiency line "
                 "under each pick is missing the latest games until this season's file is fetched again.")


def _pool_files(season: Season) -> Check:
    notes = list(getattr(season, "warnings", None) or [])
    conflicts = len(getattr(season, "conflicts", None) or [])
    words = f"{len(season.players)} coaches, standings through week {season.current_week}"
    if conflicts:
        return Check(SOURCES, "The pool's files", WARN, f"{words} - {conflicts} disagreement{'' if conflicts == 1 else 's'} between files",
                     "Two files say different things about the same result; Data & Update > Data lists each one. "
                     + " ".join(notes[:2]))
    if notes:
        return Check(SOURCES, "The pool's files", NOTE, f"{words} - {len(notes)} note{'' if len(notes) == 1 else 's'} from the last load",
                     " ".join(notes[:3]))
    return Check(SOURCES, "The pool's files", OK, words, "Loaded with nothing to report.")


def _turned_away(now: float) -> Check | None:
    """Files refused as a week's predictions in the last week (predictions.refusal)."""
    from .model import predictions
    recent = predictions.turned_away(since=now - 7 * DAY)
    if not recent:
        return None
    names = "; ".join(f"{r.get('name') or r['path']}: {r.get('reason', '')}" for r in recent[:4])
    more = f"; and {len(recent) - 4} more" if len(recent) > 4 else ""
    return Check(SOURCES, "Files turned away", NOTE,
                 f"{len(recent)} file{'' if len(recent) == 1 else 's'} not taken as a week's predictions",
                 names + more + ". Nothing was loaded from them.", recent[0].get("at"))


def _consistency(season: Season, week: int) -> Check | None:
    """Do the sources agree with each other (consistency.py)?"""
    from . import consistency
    found = consistency.week(season, week)
    if season.weeks.get(week) is None:
        return None
    if not found:
        return Check(SOURCES, "Sources agree", OK, f"Week {week}: line, moneyline, total, pool lines and the record agree")
    serious = [p for p in found if p.kind in ("moneyline", "source", "pool line")]
    detail = "; ".join(f"{p.game + ': ' if p.game else ''}{p.text}" for p in found[:5])
    if len(found) > 5:
        detail += f"; and {len(found) - 5} more"
    return Check(SOURCES, "Sources agree", WARN if serious else NOTE,
                 f"Week {week}: {len(found)} disagreement{'' if len(found) == 1 else 's'} between sources",
                 detail + ". Two numbers that describe the same game can't both be right - check where each came from.")


def _backups(now: float) -> Check:
    """The daily copy kept outside the synced folder, and whether it opens sound (store.mirror_backup)."""
    from . import store
    status = store.mirror_status()
    if status is None:
        return Check(AUTOMATION, "Backup outside OneDrive", NOTE, "Not made yet",
                     "Each day's database copy is also put in %LOCALAPPDATA%\\ACQL\\backups, where a OneDrive "
                     "sync problem can't reach it. The first one is made the next time the app opens.")
    at = float(status.get("at") or 0) or None
    age = now - at if at else None
    if not status.get("ok"):
        return Check(AUTOMATION, "Backup outside OneDrive", BAD, f"The latest copy failed its check ({status.get('word')})",
                     f"{status.get('file')} - the copies in data/backups are still there.", at)
    return Check(AUTOMATION, "Backup outside OneDrive", OK if age is not None and age < 2 * DAY else WARN,
                 f"{status.get('file')} checked sound {ago(age)} ({status.get('documents')} records)",
                 "Kept in %LOCALAPPDATA%\\ACQL\\backups: the last 14 days and 8 Sundays.", at)


#: Fixes a check can offer: key -> button words.
FIXES = {"old_sheets": "Clear them"}
#: The start of the note the load leaves while other seasons' sheets are stored.
OLD_SHEETS = "Stored pick sheets from another season"


def standing(now: float | None = None) -> list[tuple[float, str]]:
    """(first seen, note) for each note the nightly run has repeated for a day or more,
    oldest first (headless._new_notes keeps them)."""
    from . import store
    now = time.time() if now is None else now
    kept = store.get("headless", "notes", {}) or {}
    if not isinstance(kept, dict):
        return []
    out = [(float(v.get("first", now)), str(text)) for text, v in kept.items()
           if isinstance(v, dict) and now - float(v.get("first", now)) >= DAY]
    return sorted(out)


def forget_standing(start: str) -> None:
    """Drop the standing notes that begin with `start` (after their fix ran),
    so the page doesn't show them again before the next run."""
    from . import store
    kept = store.get("headless", "notes", {}) or {}
    if isinstance(kept, dict):
        store.put("headless", "notes", {t: v for t, v in kept.items() if not str(t).startswith(start)})


def _standing(now: float) -> Check | None:
    from html import escape
    found = standing(now)
    if not found:
        return None
    lines = [f"Since {time.strftime('%b %d', time.localtime(first)).replace(' 0', ' ')}: {escape(text)}"
             for first, text in found]
    fix = "old_sheets" if any(text.startswith(OLD_SHEETS) for _f, text in found) else ""
    many = len(found) != 1
    return Check(AUTOMATION, "Standing issues", NOTE,
                 f"{len(found)} note{'s' if many else ''} the nightly run keep{'' if many else 's'} repeating",
                 "<br>".join(lines), found[0][0], fix)


def _corrections(year: int, now: float) -> Check | None:
    """Final scores ESPN changed after the game, in the last week (feeds/recheck.py)."""
    from .feeds import recheck, results
    weeks = range(1, 23)
    found = [c for c in recheck.corrections(year, weeks) if now - c.at < 7 * DAY]
    if not found:
        return None
    return Check(SOURCES, "Score corrections", WARN,
                 f"{len(found)} final score{'s' if len(found) != 1 else ''} changed after the game",
                 "<br>".join(c.text() for c in found) + "<br>Graded with the corrected score; the commissioner's "
                 "sheet may still have the old one.", found[-1].at)


def _publish_windows(year: int) -> Check | None:
    """When each source has usually had the week (publishtimes.py, #100)."""
    from . import publishtimes
    found = [w for w in (publishtimes.window(s, year) for s in publishtimes.NAMES) if w is not None]
    if not found:
        return None
    return Check(SOURCES, "When sources publish", OK,
                 "; ".join(f"{publishtimes.NAMES[w.source]} {w.words()}" for w in found),
                 "Written down each week the first time a source had it. Next week's lines are fetched as soon "
                 "as ESPN's free scoreboard shows them, not on a fixed clock.")


def _second_source(year: int) -> Check | None:
    """ESPN's finals against the nflverse games file on disk (feeds/crosscheck.py, #46)."""
    from .feeds import crosscheck
    found = crosscheck.check(year, range(1, 23))
    if not found:
        return None
    agree = sum(c.agree for c in found)
    differ = [d for c in found for d in c.differ]
    behind = [c.week for c in found if c.missing and not c.agree]
    checked = [c.week for c in found if c.agree or c.differ]
    if differ:
        return Check(SOURCES, "Second results source", WARN,
                     f"ESPN and nflverse disagree on {len(differ)} final score{'s' if len(differ) != 1 else ''}",
                     "<br>".join(differ))
    span = f"weeks {min(checked)}-{max(checked)}" if checked else "no week yet"
    return Check(SOURCES, "Second results source", OK if checked else NOTE,
                 f"ESPN and nflverse agree on all {agree} finals ({span})",
                 (f"The nflverse copy on this computer doesn't have week{'s' if len(behind) != 1 else ''} "
                  f"{', '.join(map(str, behind))} yet; refreshing it is a download, asked for each time."
                  if behind else ""))


def _source_history(now: float) -> Check | None:
    """Each source's last 30 days of fetches (sourcehealth.py, #41): one mark a day for the last two weeks."""
    from html import escape
    from . import sourcehealth
    found = sourcehealth.every(now)
    if not found:
        return None
    lines, worst = [], OK
    for h in found:
        rate = h.good / h.calls if h.calls else 1.0
        recent_bad = h.last_bad is not None and now - h.last_bad < 3 * DAY
        if recent_bad and (h.last_good is None or h.last_bad > h.last_good):
            worst = WARN                      # failing now
        elif recent_bad and worst == OK:
            worst = NOTE
        lines.append(f"<span style='font-family:monospace'>{h.days}</span> {escape(h.name)}: "
                     f"{h.good} of {h.calls} good ({rate:.0%})"
                     + (f", usually {h.median_s:.1f}s" if h.median_s is not None else "")
                     + (f"; last failure {ago(now - h.last_bad)}: {escape(h.last_note[:80])}" if h.last_bad else ""))
    failing = [h.name for h in found if h.last_bad and (h.last_good is None or h.last_bad > h.last_good)]
    headline = (f"Failing at the last try: {', '.join(failing)}" if failing else
                f"{len(found)} sources, the last two weeks a mark a day (✓ all good, ✕ a failure, · no call)")
    return Check(AUTOMATION, "Source history", worst, headline, "<br>".join(lines))


def _skipped(now: float) -> Check | None:
    """Items a source sent in a shape that couldn't be read, lately (feeds.keep_readable).
    The rest of each answer was used; this says what wasn't."""
    from .feeds import skipped_lately
    found = skipped_lately(2 * DAY, now)
    if not found:
        return None
    parts = [f"{where}: {v.get('count', 0)} left out {ago(now - float(v.get('at', 0)))}"
             + (f" ({v['why']})" if v.get("why") else "") for where, v in found[:4]]
    total = sum(int(v.get("count", 0)) for _, v in found)
    return Check(SOURCES, "Unreadable items", NOTE,
                 f"{total} item{'' if total == 1 else 's'} from {len(found)} source"
                 f"{'' if len(found) == 1 else 's'} couldn't be read in the last two days",
                 "; ".join(parts) + ". Everything else in those answers was used. The raw data keeps what came.",
                 max(float(v.get("at", 0)) for _, v in found))


def _updates() -> Check | None:
    """Would an automatic update overwrite work here (updater.work_at_risk)? Only said for a git checkout."""
    from . import store, updater
    root = store.project_root()
    if not (root / ".git").exists():
        return None
    risk = _remembered(f"work at risk {root}", lambda: updater.work_at_risk(root))
    if not risk:
        return Check(AUTOMATION, "Updates", OK, "Everything here is on GitHub - an update can install safely")
    return Check(AUTOMATION, "Updates", NOTE, "Held back: this folder has work that isn't on GitHub",
                 risk.replace("The update wasn't installed: ", "No update installs while "))


def _training(now: float) -> Check:
    """Is the training ground's weekly answer current?"""
    from .model import challengers
    answer = challengers.read()
    if answer is None:
        return Check(AUTOMATION, "Training verdict", NOTE, "No training answer on disk yet",
                     "The ACQL Training job writes it, Tue-Thu; the nightly run starts it when it is overdue.")
    age = now - answer.made
    return Check(AUTOMATION, "Training verdict", WARN if answer.stale(now) else OK,
                 f"Made {ago(age)}" + (" - stale" if answer.stale(now) else ""),
                 answer.call if not answer.stale(now) else
                 "The weekly training job hasn't run since; the nightly run starts it when it is this late. "
                 "If it stays stale, check the ACQL Training task.", answer.made)


def _inputs(season: Season, week: int, to_lock: float) -> Check:
    from .feeds import oddslock, results
    games, prices, ctx = _slate(season, week)
    if not games:
        return Check(CARD, "Every game's inputs", NOTE, f"Week {week} has no unplayed games set up")
    year = results.season_year(season)
    scores = results.load(year, week)
    forecasts = ctx.forecasts if ctx is not None else {}
    lacking = []
    for g in games:
        price = prices.get(g.index)
        missing = []
        if price is None or price.base is None:
            missing.append("no betting line")
        elif getattr(forecasts.get(g.index), "market_win", None) is None and g.line is None:
            missing.append("no moneyline")
        found, _flip = results.find(scores, g.away, g.home)
        if found is None or not found.kickoff:
            missing.append("no kickoff time")
        if missing:
            lacking.append((g.label, missing))
    unpriced = [label for label, missing in lacking if "no betting line" in missing]
    posted = any(g.line is not None for g in games)
    line_note = ("" if posted or to_lock <= 0 else
                 " The pool's lines aren't in yet: big favourites are priced straight up until they are entered "
                 "on Deadeye Picks > My picks.")
    if not lacking:
        return Check(CARD, "Every game's inputs", OK, f"All {len(games)} games have a line and a kickoff time",
                     ("" + line_note).strip())
    state = BAD if unpriced and 0 < to_lock < DAY else WARN if unpriced and to_lock < 2 * DAY else NOTE
    if to_lock <= 0 and unpriced:
        state = WARN
    detail = "; ".join(f"{label}: {', '.join(missing)}" for label, missing in lacking[:6])
    if len(lacking) > 6:
        detail += f"; and {len(lacking) - 6} more"
    return Check(CARD, "Every game's inputs", state,
                 f"{len(lacking)} of {len(games)} games are missing something - {len(unpriced)} can't be priced",
                 detail + "." + line_note)


def _kept_card(season: Season, year: int, week: int, now: float) -> Check:
    """Was Deadeye's card written down before the games began?"""
    from .pool import cards
    from .feeds import oddslock
    snap = cards.model(week)
    kickoff = oddslock.kickoff_time(year, week)
    started = cards.week_started(season, week)
    name = f"{MODEL_NAME}'s card, week {week}"
    if snap is None:
        if started:
            return Check(CARD, name, BAD, "No card was kept before the first kickoff",
                         "Its record for this week will have to be re-made from the stored lines afterwards, "
                         "which is a little kind to it. The nightly run and opening Deadeye Picks both keep it.")
        return Check(CARD, name, WARN if kickoff - now < 2 * DAY else NOTE, "Not kept yet",
                     "It is written down whenever Deadeye Picks is opened or the scheduled job prices the week, "
                     "and for the last time before the first kickoff.")
    if getattr(snap, "rebuilt", False):
        return Check(CARD, name, WARN, "Re-made after the fact, not kept at the time",
                     "Scored on the lines as stored, which is a little kind to it.", snap.at)
    if started and snap.at > kickoff + 15 * 60:
        return Check(CARD, name, WARN, f"Kept {ago(now - snap.at)} - after the first kickoff",
                     "A card written down once games have started is not a prediction of them.", snap.at)
    return Check(CARD, name, OK,
                 f"Kept before the first kickoff ({ago(now - snap.at)})" if started
                 else f"Kept as it stands, {ago(now - snap.at)} - frozen at the first kickoff",
                 "This is the card it is scored on: it is never rewritten once the games begin.", snap.at)


def _known(year: int, week: int, to_lock: float, now: float) -> Check:
    from .model import known
    found = known.kept(year, week)
    if found is None:
        return Check(CARD, "What was known", NOTE if to_lock > 0 else WARN,
                     "Nothing written down for this week yet" if to_lock > 0
                     else "The week closed with nothing written down",
                     "Each game's injuries, rest, weather and ratings are written down while the week is open "
                     "and frozen at the deadline, so later models are tested on what was known then.")
    at = float(found.get("at") or 0) or None
    frozen = bool(found.get("frozen"))
    return Check(CARD, "What was known", OK,
                 f"{len(found.get('games') or {})} games written down {ago(now - at) if at else ''}"
                 + (" - frozen at the deadline" if frozen else " - still open"), "", at)


def _my_card(week: int, to_lock: float, now: float) -> Check:
    from .pool import cards
    mine = cards.mine(week)
    if mine is not None:
        return Check(CARD, "Your own card", OK, f"Saved {ago(now - mine.at)}",
                     "Any change before the deadline is pointed out on Deadeye Picks.", mine.at)
    if to_lock <= 0:
        return Check(CARD, "Your own card", NOTE, "No card was saved for this week")
    return Check(CARD, "Your own card", WARN if to_lock < DAY else NOTE,
                 f"Not saved yet - cards are due {until(to_lock)}",
                 "Save card on Deadeye Picks remembers the one you are handing in.")


def _submitted(season: Season, week: int) -> Check | None:
    """Your row on the commissioner's sheet against the card you saved (pool/cardcheck.py)."""
    from .pool import cardcheck, picks
    if picks.load(week) is None:
        return None
    found = cardcheck.check(season, week)
    if not found.compared:
        return Check(CARD, "Card as submitted", NOTE, found.reason,
                     "The sheet is compared with the card saved on My picks, to catch a slip on the entry form.")
    if found.diffs:
        return Check(CARD, "Card as submitted", WARN, found.headline(), "; ".join(found.lines()) + ".")
    return Check(CARD, "Card as submitted", OK, found.headline())


def _autopsy(season: Season, year: int) -> Check:
    from .model import autopsy
    done = [n for n in sorted(season.weeks) if season.weeks[n].games and all(g.played for g in season.weeks[n].games)]
    kept = [n for n in done if autopsy.kept(year, n) is not None]
    if not done:
        return Check(CARD, "Hits and misses", NOTE, "No finished week yet")
    if len(kept) == len(done):
        return Check(CARD, "Hits and misses", OK, f"Every finished week is written down (through week {done[-1]})",
                     "Each game as it was picked and how it came out, kept so nothing learned later rewrites it.")
    missing = [n for n in done if n not in kept]
    return Check(CARD, "Hits and misses", NOTE,
                 f"Week{'s' if len(missing) != 1 else ''} {', '.join(map(str, missing))} not written down yet",
                 "The nightly run does it, and so does opening Deadeye > Hits & misses.")


def task_states() -> dict[str, dict] | None:
    """{task name: {"last": seconds since 1970 or None, "next": the same, "result": int or None,
    "found": bool}} from Windows' Task Scheduler - or None where that can't be asked."""
    import csv
    import io
    import os
    import subprocess
    if os.name != "nt":
        return None
    out: dict[str, dict] = {}
    for name, _what, _limit in TASKS:
        try:
            done = subprocess.run(
                ["schtasks", "/Query", "/TN", name, "/FO", "CSV", "/V"], capture_output=True, text=True,
                timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0:
            out[name] = {"found": False, "last": None, "next": None, "result": None}
            continue
        rows = list(csv.DictReader(io.StringIO(done.stdout)))
        row = rows[0] if rows else {}

        def moment(text: str) -> float | None:
            text = (text or "").strip()
            for pattern in ("%m/%d/%Y %I:%M:%S %p", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
                try:
                    stamp = time.mktime(time.strptime(text, pattern))
                except (ValueError, OverflowError):
                    continue
                return stamp if stamp > 946684800 else None       # "never" comes back as a date in 1999
            return None

        try:
            result = int(str(row.get("Last Result", "")).strip())
        except ValueError:
            result = None
        out[name] = {"found": True, "last": moment(row.get("Last Run Time", "")),
                     "next": moment(row.get("Next Run Time", "")), "result": result}
    return out


def _tasks(states: dict[str, dict] | None, now: float) -> list[Check]:
    if states is None:
        return [Check(AUTOMATION, "Scheduled jobs", NOTE, "Couldn't ask Windows about the scheduled jobs",
                      "They are registered by schedule.ps1 in the project folder.")]
    out = []
    for name, what, limit in TASKS:
        found = states.get(name) or {"found": False}
        title = what[0].upper() + what[1:]
        if not found.get("found"):
            out.append(Check(AUTOMATION, title, BAD, f"“{name}” is not set up on this computer",
                             "Run schedule.ps1 in the project folder once to register it."))
            continue
        last, result, coming = found.get("last"), found.get("result"), found.get("next")
        when = f"last ran {ago(now - last)}" if last else "has not run yet"
        after = f", next {until(coming - now)}" if coming else ""
        if result is not None and result not in TASK_FINE:
            out.append(Check(AUTOMATION, title, WARN, f"Its last run ended with an error ({result}) - {when}",
                             "The log on Data & Update says what it was doing." + after, last))
        elif last is not None and now - last > limit:
            out.append(Check(AUTOMATION, title, WARN, f"Overdue - {when}{after}",
                             "The computer may have been off, or the job switched off.", last))
        else:
            # set up but never yet run is worth knowing, not a pass
            out.append(Check(AUTOMATION, title, OK if last else NOTE, (when[0].upper() + when[1:]) + after, "", last))
    return out


def _last_run(now: float) -> Check | None:
    from . import store
    found = store.get("headless", "last_run", None)
    if not isinstance(found, dict) or not found.get("at"):
        return None
    at = float(found["at"])
    fine = bool(found.get("ok", True))
    return Check(AUTOMATION, "Last automatic run", OK if fine else WARN,
                 f"Finished {ago(now - at)}" + ("" if fine else " - with a problem"),
                 str(found.get("note") or ""), at)


def _website(now: float) -> Check:
    from .site import siteextras, webpublish
    if not webpublish.WebSettings.load().ready:
        return Check(AUTOMATION, "Pool website", NOTE, "Not set up", "Results > Pool page walks through it.")
    last = siteextras.last_published() or {}
    auto = siteextras.Extras.load().auto_publish
    when = str(last.get("at") or "")
    words = f"Last published {when} (after week {last.get('week')})" if when else "Never published"
    if not auto:
        return Check(AUTOMATION, "Pool website", WARN, f"{words} - updating by itself is switched off",
                     "It only changes when Pool page is pressed on Results.")
    return Check(AUTOMATION, "Pool website", OK if when else WARN, words,
                 "Updates by itself whenever what it shows has changed.")


def _email(week: int, now: float) -> Check:
    from .site import mailer
    from . import store
    settings = mailer.MailSettings.load()
    if not (settings.sender and settings.sealed_password):
        return Check(AUTOMATION, f"{MODEL_NAME}'s card email", NOTE, "Email isn't set up",
                     "Results > Email settings: the Gmail it sends from.")
    sent = store.get("cardmail", str(week), {}) or {}
    at = float(sent.get("at") or 0) or None
    return Check(AUTOMATION, f"{MODEL_NAME}'s card email", OK,
                 f"Week {week}'s card last emailed {ago(now - at)}" if at else f"Week {week}'s card not emailed yet",
                 "Goes to you alone, Tuesday, Wednesday and Thursday at noon.", at)


def build(season: Season, now: float | None = None, tasks: dict[str, dict] | None | bool = True) -> Readiness:
    """Every check. `tasks` is Task Scheduler's answer when it is already to
    hand (or False to leave the scheduled jobs out); True asks Windows."""
    from . import analytics
    from .feeds import oddslock, results
    now = time.time() if now is None else now
    year = results.season_year(season)
    ahead = analytics.upcoming_week(season)
    calendar = results.calendar_weeks(year, now)
    playing = calendar[0] if calendar else ahead
    lock = oddslock.lock_time(year, ahead)
    to_lock = lock - now
    checks: list[Check] = []

    def add(make, *args) -> None:
        try:
            found = make(*args)
        except Exception as exc:  # noqa: BLE001 - one check failing is itself worth saying
            label = getattr(make, "__name__", "check").strip("_").replace("_", " ")
            found = Check(SOURCES, label.capitalize(), NOTE, "Couldn't be checked", f"{type(exc).__name__}: {exc}")
        if found is None:
            return
        checks.extend(found if isinstance(found, list) else [found])

    add(_scores, year, playing, now)
    add(_lines, season, ahead, to_lock, now)
    add(_models, season, ahead, to_lock, now)
    add(_injuries, to_lock, now)
    add(_weather, year, ahead, to_lock, now)
    add(_efficiency, year, ahead)
    add(_pool_files, season)
    add(_turned_away, now)
    add(_corrections, year, now)
    add(_second_source, year)
    add(_publish_windows, year)
    add(_consistency, season, ahead)
    add(_inputs, season, ahead, to_lock)
    if playing != ahead and season.weeks.get(playing) is not None:
        add(_kept_card, season, year, playing, now)
    add(_kept_card, season, year, ahead, now)
    add(_my_card, ahead, to_lock, now)
    add(_submitted, season, playing if season.weeks.get(playing) is not None else ahead)
    add(_known, year, ahead, to_lock, now)
    add(_autopsy, season, year)
    if tasks is not False:
        add(_tasks, _remembered("task states", task_states) if tasks is True else tasks, now)
    add(_last_run, now)
    add(_standing, now)
    add(_source_history, now)
    add(_skipped, now)
    add(_training, now)
    add(_backups, now)
    add(_updates)
    add(_website, now)
    add(_email, ahead, now)
    return Readiness(checks, ahead, lock, now)
