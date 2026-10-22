"""The dashboard's background work with no window: for Task Scheduler.

The window keeps the season current by itself while it is open - it asks
ESPN for results, reloads, fetches the replay's scoring plays and brings the
website up to date. This does the same rounds from a scheduled task, so the
website stays current whether or not anyone has the dashboard open:

    python -m acql.headless --daily     every step, asked of ESPN whatever the time
    python -m acql.headless --poll      only when a look is due (a game under way,
                                        a finished game without its replay) -
                                        otherwise it leaves in a second
    python -m acql.headless --email     Deadeye's card for the week ahead, on the
                                        freshest lines, emailed to the dashboard's
                                        own address (cardmail.py)
    python -m acql.headless --brief     the Sunday morning brief: top calls, line
                                        moves since open, odds budget - from
                                        stored lines only (sundaybrief.py)

schedule.ps1 registers all three: --daily at 3am, --poll every ten minutes
on game days, --email at noon on Tuesday, Wednesday and Thursday. Everything it does goes in the dashboard's log (acql-log.txt),
each line starting "headless:".

Both also keep the week ahead's numbers fresh until its odds lock: the
computer models' predictions file and the betting lines (with an Odds API
key), twice a day and every two hours on the day of the lock - so Deadeye's
card is always priced on the latest line, and kept as it stood at the lock
even when nobody opens the dashboard that week.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

from . import analytics
from .feeds import oddslock, results
from .model import predictions
from .config import DATA_DIR, Settings
from .names import AliasTable
from .repository import load_season
from .version import MODEL_NAME

#: Held while a run is going, so a poll can't start on top of the 3am run.
LOCK_FILE = Path(DATA_DIR) / "headless.lock"

#: The week ahead's lines are refreshed this often...
LINES_EVERY = 12 * 3600
#: ...this often on the day its odds lock...
LINES_EVERY_LOCK_DAY = 2 * 3600
#: ...and this often in the last two hours before the pool's deadline, when
#: the late injury news lands.
LINES_EVERY_LAST_HOURS = 20 * 60
LAST_HOURS = 2 * 3600
#: The predictions file is looked for no more often than this.
PREDICTIONS_EVERY = 3600
#: Before the card is emailed the lines are fetched again unless they are this fresh.
EMAIL_LINES_FRESH = 45 * 60
#: The email waits this long for a run already going (the poll starts at noon too).
EMAIL_WAIT = 240
#: Where --email --dry-run leaves the card to look at, instead of sending it.
EMAIL_PREVIEW = Path(DATA_DIR) / "deadeye-email-preview.html"
#: Where --brief --dry-run leaves the Sunday brief.
BRIEF_PREVIEW = Path(DATA_DIR) / "sunday-brief-preview.html"
#: Lines aren't posted much further ahead than this.
LINES_AHEAD = 6 * 86400
#: A refresh that failed isn't tried again for this long.
LINES_RETRY = 15 * 60
#: The computer models' predictions, as The Prediction Tracker publishes them.
PREDICTIONS_URL = "https://www.thepredictiontracker.com/nflpredictions.csv"
#: The Odds API's free plan is 500 requests a month, and a fetch of spreads,
#: moneylines and totals is three: this many are left for pressing Update
#: lines by hand.
ODDS_RESERVE = 40


def _log(text: str) -> None:
    from .ui.pages.base import write_log
    write_log(f"headless: {text}")
    print(text, flush=True)


class _RunLock:
    """An OS lock on a file: released by Windows even if the run is killed."""

    def __init__(self, path: Path) -> None:
        self.path, self.handle = path, None

    def __enter__(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        return True

    def __exit__(self, *_exc) -> None:
        if self.handle is not None:
            self.handle.close()


def _poll_due() -> bool:
    """Cheap look, without reading a spreadsheet: is ESPN worth asking now?
    This week, next week and last week (a Monday night final lands on Tuesday)."""
    from .feeds import timeline
    year = results.season_year()
    weeks = set(results.calendar_weeks(year))
    weeks |= {w - 1 for w in weeks if w > 1}
    if results.due(year, weeks):
        return True
    finished = [w for w in sorted(weeks) if results.over(year, w)]
    if (bool(finished) and timeline.due(year, finished)) or _lines_due() is not None:
        return True
    from .model import ledger
    return ledger.due(year)             # a week's cards are in and its numbers aren't written down yet


# ---- the week ahead's lines -----------------------------------------------------------
def _week_ahead(year: int, now: float) -> int | None:
    """The next week whose odds haven't locked yet."""
    return next((w for w in results.calendar_weeks(year, now) if oddslock.lock_time(year, w) > now), None)


def _lines_due(now: float | None = None) -> int | None:
    """The week ahead, when its predictions and lines are due a refresh."""
    from . import store
    now = time.time() if now is None else now
    year = results.season_year()
    week = _week_ahead(year, now)
    if week is None:
        return None
    to_lock = oddslock.lock_time(year, week) - now
    if to_lock > LINES_AHEAD:
        return None
    try:
        tried = float(store.get("headless", "lines_tried", 0) or 0)
    except store.StoreError:
        tried = 0.0
    if now - tried < LINES_RETRY:
        return None
    every = (LINES_EVERY_LAST_HOURS if to_lock <= LAST_HOURS
             else LINES_EVERY_LOCK_DAY if to_lock < 86400 else LINES_EVERY)
    return week if now - predictions.market_time(week) >= every else None


def _download_predictions(season, week: int) -> None:
    """The Prediction Tracker's file, kept only when it is this week's games."""
    import tempfile
    import urllib.request
    from . import store
    try:
        if time.time() - float(store.get("headless", "predictions_tried", 0) or 0) < PREDICTIONS_EVERY:
            return
        store.put("headless", "predictions_tried", time.time())
    except store.StoreError:
        pass
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found else []
    if not games:
        _log(f"week {week} has no games set up yet - predictions not fetched")
        return
    request = urllib.request.Request(PREDICTIONS_URL, headers={"User-Agent": "ACQL-Dashboard"})
    with urllib.request.urlopen(request, timeout=30) as reply:
        body = reply.read()
    with tempfile.TemporaryDirectory() as scratch:
        trial = Path(scratch) / "nflpredictions.csv"
        trial.write_bytes(body)
        refused = predictions.refusal(trial, games)
        if refused:
            _log(f"the published predictions file was not kept: {refused}")
            return
        if not predictions.covers_slate(trial, games):
            _log(f"the published predictions aren't week {week}'s games yet - not kept")
            return
        folder = predictions.ROOT / "predictions"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"nflpredictions week {week}.csv"
        if target.exists() and target.read_bytes() == body:
            return                                  # nothing new published
        target.write_bytes(body)
    got, where, fresh = predictions.refresh_from_disk(
        week, getattr(season, "workbook_path", None), games, locked=False)
    _log(f"week {week} predictions downloaded: {len(got)} games" + ("" if fresh else " (unchanged)"))


def _fetch_lines(season, week: int) -> None:
    """The latest betting lines, the way Update lines on This Week fetches them."""
    from .pool import briefing, cards
    from .feeds import odds
    key = odds.api_key()
    if not key:
        return
    left = odds.remaining()
    if left is not None and left <= ODDS_RESERVE:
        _log(f"betting lines not fetched: {left} Odds API requests left this month, kept for by hand")
        return
    cards.remember_before_update(week, briefing.build(season, week))
    quotes, left = odds.fetch(key)
    update = odds.update(week, quotes, odds.week_pairs(season, week), left)
    _log(update.summary() + (f" {left} requests left this month." if left is not None else ""))


def _injuries() -> None:
    """ESPN's injury report, a few times a day - hourly on the day the cards are due."""
    from .feeds import injuries
    try:
        now = time.time()
        year = results.season_year()
        week = _week_ahead(year, now)
        lock_in = oddslock.lock_time(year, week) - now if week else None
        if injuries.due(lock_in, now):
            _log(f"injury report read: {injuries.refresh()} players listed")
    except Exception as exc:  # noqa: BLE001 - the picks don't wait on it
        _log(f"injury report not read: {exc}")


def _known(season) -> None:
    """Everything known about the week ahead's games, written down while it is
    open and frozen at the deadline - so nothing learned later can get into it."""
    try:
        from .model import known
        now = time.time()
        year = results.season_year(season)
        for week in results.calendar_weeks(year, now):
            if season.weeks.get(week) is None:
                continue
            done = known.keep(season, year, week, oddslock.lock_time(year, week), now)
            if done in ("kept", "frozen"):
                _log(f"week {week}: what is known before kickoff {done}")
    except Exception as exc:  # noqa: BLE001 - the picks don't wait on it
        _log(f"what is known before kickoff not kept: {exc}")


def _computers() -> None:
    """Each computer model's number, kept by name while the week's file is still on disk."""
    try:
        from .model import computers
        computers.keep()
    except Exception as exc:  # noqa: BLE001 - the picks do not wait on it
        _log(f"computer models' names not kept: {exc}")


def _seasons() -> None:
    """The Model Lab's season-by-season record - several seconds' work, done here
    so the page never waits for it. It only changes when a season ends."""
    try:
        from .model import contenders
        year = results.season_year()
        if contenders.seasons(year) is None:
            made = contenders.seasons(year, compute=True)
            _log(f"model lab: the contenders' season-by-season record worked out ({len(made or [])} seasons)")
        from .feeds import nflverse
        if nflverse.available() and nflverse.families() is None:
            found = nflverse.families(compute=True)
            _log(f"model lab: market, football and hybrid worked out over {len(found.seasons)} seasons")
    except Exception as exc:  # noqa: BLE001 - the page says it isn't there yet
        _log(f"model lab: season-by-season record not worked out: {exc}")


def _ledger(season) -> None:
    """Every recipe's number for a week, written down once its cards are in (the Model Lab's record)."""
    try:
        from .model import ledger
        done = ledger.keep(season)
        ledger.tried()
        if done:
            _log(f"model lab: every recipe's numbers written down for week{'s' if len(done) != 1 else ''} "
                 f"{', '.join(str(w) for w in done)}")
    except Exception as exc:  # noqa: BLE001 - the lab replays the week instead
        _log(f"model lab: the week's numbers not written down: {exc}")


def _autopsy(season) -> None:
    """Each finished week's games, written down as they were picked and how they came out."""
    try:
        from .model import autopsy
        from .version import MODEL_NAME
        done = autopsy.keep(season)
        if done:
            _log(f"{MODEL_NAME}'s hits and misses kept for week{'s' if len(done) != 1 else ''} "
                 f"{', '.join(str(w) for w in done)}")
    except Exception as exc:  # noqa: BLE001 - the page works it out afresh instead
        _log(f"hits and misses not kept: {exc}")


def _weather() -> None:
    """The forecast for the outdoor games still to kick off, a few times a day."""
    from .feeds import weather
    try:
        now = time.time()
        year = results.season_year()
        for week in results.calendar_weeks(year, now):
            if weather.due(year, week, now):
                count = weather.refresh(year, week, now=now)
                if count:
                    _log(f"weather read for {count} outdoor game(s) of week {week}")
    except Exception as exc:  # noqa: BLE001 - the picks don't wait on it
        _log(f"weather not read: {exc}")


def _refresh_lines(season) -> None:
    """The week ahead's numbers brought up to date, then Deadeye's card kept."""
    from .pool import briefing, cards
    from . import store
    week = _lines_due()
    if week is None or oddslock.locked_for(season, week):
        return
    try:
        store.put("headless", "lines_tried", time.time())
    except store.StoreError:
        pass
    for step in (_download_predictions, _fetch_lines):
        try:
            step(season, week)
        except Exception as exc:  # noqa: BLE001 - the other source may still come through
            _log(f"week {week} {step.__name__.strip('_').replace('_', ' ')} failed: {exc}")
    # The card as it stands on the newest numbers, made before anyone's
    # picks are known, kept to grade Deadeye by (cards.record_model).
    try:
        if cards.record_model(season, week, briefing.build(season, week, use_sheet=False)):
            _log(f"Deadeye's week {week} card kept on the latest lines")
    except Exception as exc:  # noqa: BLE001
        _log(f"Deadeye's week {week} card couldn't be kept: {exc}")


def _predictions(season) -> None:
    """The week ahead's predictions file, picked up as the window's Loader does."""
    try:
        ahead = analytics.upcoming_week(season)
        week = season.weeks.get(ahead)
        got, where, fresh = predictions.refresh_from_disk(
            ahead, getattr(season, "workbook_path", None),
            sorted(week.games, key=lambda g: g.index) if week else [],
            locked=oddslock.locked_for(season, ahead),
        )
        if fresh and got:
            _log(f"week {ahead} predictions read from {Path(where).name}: {len(got)} games")
    except Exception as exc:  # noqa: BLE001
        _log(f"couldn't read the predictions file: {exc}")


def _timelines(season) -> int:
    """Finished games' scoring plays, for the website's replay of each week."""
    from .feeds import timeline
    year = getattr(season, "results_year", 0) or 0
    weeks = sorted(n for n, w in season.weeks.items() if w.games and all(g.played for g in w.games))
    if not year or not weeks or not timeline.due(year, weeks):
        return 0
    kept, problems = timeline.refresh(year, weeks)
    for problem in problems:
        _log(f"replay: {problem}")
    if kept:
        _log(f"replay: kept {kept} game timeline(s)")
    return kept


def _retrying(call, error: type, *, tries: int = 3, pause: float = 60, sleep=time.sleep):
    """`call()`, tried again after `pause` seconds when it raises `error` (a connection
    that dropped or timed out), up to `tries` times; the last failure is raised."""
    for attempt in range(1, tries + 1):
        try:
            return call()
        except error as exc:
            if attempt == tries:
                raise
            _log(f"try {attempt} of {tries} failed ({exc}); trying again in {pause:.0f}s")
            sleep(pause)


def _publish(season) -> str | None:
    """The website, brought up to date when something it shows has changed -
    the same steps as the window's AutoPublisher, on this thread."""
    from .site import pushalerts, siteextras, webpublish
    from .ui import poolpage
    from .ui.webpage import published

    settings = webpublish.WebSettings.load()
    if not settings.ready:
        _log("website not set up (Results > Pool page in the dashboard) - not published")
        return None
    if not siteextras.Extras.load().auto_publish:
        _log("the website's automatic updates are switched off - not published")
        return None
    weeks = poolpage.finished_weeks(season)
    if not weeks:
        return None
    page, files, data = poolpage.site(season)
    fingerprint = poolpage.site_fingerprint(data)
    if not siteextras.needs_publish(fingerprint):
        _log("website already up to date")
        return None
    from .ui import previewcard
    try:
        files[poolpage.PREVIEW] = previewcard.render(data)
    except Exception as exc:  # noqa: BLE001 - the page goes up without its preview
        _log(f"preview card failed: {exc!r}")
    try:
        files.update(poolpage.app_files())
    except Exception as exc:  # noqa: BLE001
        _log(f"home-screen icon failed: {exc!r}")
    week = max(weeks)
    url = _retrying(lambda: webpublish.publish(settings, page, message=f"After week {week} (scheduled)",
                                               files=files), webpublish.WebPublishError)
    published(data, week, url)
    _log(f"website updated: {url}")
    _alert("results", lambda: pushalerts.results_in(week, url))
    return url


def _alert(what: str, send) -> None:
    """One phone alert (pushalerts.py) - a failure is logged, never fatal."""
    try:
        if send():
            _log(f"{what} alert sent")
    except Exception as exc:  # noqa: BLE001
        _log(f"{what} alert failed: {exc!r}")


def email_card(*, dry_run: bool = False) -> int:
    """Deadeye's card for the week ahead, on the freshest numbers, emailed to
    the dashboard's own address. `dry_run` writes it to a file instead."""
    from .pool import briefing, cards
    from .site import cardmail, mailer
    now = time.time()
    settings = Settings.load()
    season = load_season(settings, AliasTable.load())
    year = results.season_year(season)
    week = _week_ahead(year, now)
    if week is None or season.weeks.get(week) is None:
        _log("card email: no week open to pick - not sent")
        return 0
    # the newest numbers first: the file, the lines (unless just fetched), the injuries, the weather
    for step in (_download_predictions, None):
        try:
            if step is not None:
                step(season, week)
            elif now - predictions.market_time(week) >= EMAIL_LINES_FRESH:
                _fetch_lines(season, week)
        except Exception as exc:  # noqa: BLE001 - the card goes out on what there is
            _log(f"card email: the latest numbers couldn't be fetched ({exc})")
    _injuries()
    _weather()
    card = cardmail.compose(season, week)
    if card is None:
        _log(f"card email: week {week} has no lines yet - not sent")
        return 0
    try:
        cards.record_model(season, week, briefing.build(season, week, use_sheet=False))
    except Exception:  # noqa: BLE001
        pass
    if dry_run:
        EMAIL_PREVIEW.write_text(
            f"<!doctype html><meta charset='utf-8'><title>{card.subject}</title>"
            f"<p style='font-family:Segoe UI,Arial;color:#666'>Subject: {card.subject}</p>{card.html}",
            encoding="utf-8")
        _log(f"card email (dry run): \"{card.subject}\" written to {EMAIL_PREVIEW.name}, "
             f"would go to {len(cardmail.recipients())} address(es); nothing sent")
        return 0
    _private_page(card.html, season)
    try:
        to = cardmail.send(card)
    except mailer.MailError as exc:
        _log(f"card email not sent: {exc}")
        return 1
    _log(f"card email sent: \"{card.subject}\" to {len(to)} address(es)"
         + (f"; {len(card.changes)} change(s) since the last one" if card.changes else ""))
    return 0


def email_brief(*, dry_run: bool = False) -> int:
    """The Sunday brief for the week in play, from what is kept (no odds fetch)."""
    from .site import mailer, sundaybrief
    season = load_season(Settings.load(), AliasTable.load())
    brief = sundaybrief.compose(season)
    if brief is None:
        _log("sunday brief: no week in play - not sent")
        return 0
    if dry_run:
        BRIEF_PREVIEW.write_text(
            f"<!doctype html><meta charset='utf-8'><title>{brief.subject}</title>"
            f"<p style='font-family:Segoe UI,Arial;color:#666'>Subject: {brief.subject}</p>{brief.html}",
            encoding="utf-8")
        _log(f"sunday brief (dry run): written to {BRIEF_PREVIEW.name}; nothing sent")
        return 0
    try:
        to = sundaybrief.send(brief)
    except mailer.MailError as exc:
        _log(f"sunday brief not sent: {exc}")
        return 1
    _log(f"sunday brief sent: \"{brief.subject}\" to {len(to)} address(es)")
    return 0


def _private_page(inside: str | None = None, season=None) -> None:
    """The locked page on the website (site/lockedpage.py): the card, encrypted
    before it leaves. Only when a passphrase has been set; never the cause of a failed run."""
    try:
        from .site import lockedpage
        done = lockedpage.put(inside, season=season) if inside is not None else lockedpage.refresh(season)
        if done:
            _log("private page updated")
    except Exception as exc:  # noqa: BLE001 - reported, and the run goes on
        _log(f"private page not updated: {exc}")


def run(*, force: bool, dry_run: bool = False) -> int:
    started = time.monotonic()
    settings = Settings.load()
    season = load_season(settings, AliasTable.load(), force=force)
    for warning in _new_notes(season.warnings):
        _log(f"note: {warning}")
    if season.is_empty:
        _log(f"no data found in {', '.join(map(str, settings.search_paths()))} - nothing to do")
        return 1
    fetched = getattr(season, "results_fetched", None) or []
    _log(f"loaded {len(season.players)} players, week {season.current_week}; "
         f"ESPN results for week(s) {fetched or 'none due'}")
    _predictions(season)
    _refresh_lines(season)
    _injuries()
    _weather()
    _autopsy(season)
    _ledger(season)
    _seasons()
    _known(season)
    _card_check(season, dry_run=dry_run)
    _sentinel(season, dry_run=dry_run)
    _watch(season, dry_run=dry_run)
    _record_live(season)
    _heal_training(dry_run=dry_run)
    _computers()
    if _timelines(season):
        season = load_season(settings, AliasTable.load(), online=False)
    if dry_run:
        _log(f"dry run: website not touched ({time.monotonic() - started:.0f}s)")
        return 0
    try:
        _publish(season)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        _log(f"website update failed: {exc}\n{traceback.format_exc()}")
        _ran(False, f"the website update failed: {exc}")
        return 1
    _private_page(season=season)
    _log(f"done in {time.monotonic() - started:.0f}s")
    _ran(True, f"took {time.monotonic() - started:.0f}s")
    return 0


#: A note the load repeats is written to the log again only this often.
NOTE_AGAIN = 24 * 3600


def _new_notes(warnings, now: float | None = None) -> list[str]:
    """The load's notes worth writing down this run: new ones, and standing
    ones once a day (with how long they have stood) - not the same lines every
    ten minutes, which taught the log to be skimmed."""
    from . import store
    now = time.time() if now is None else now
    try:
        kept = store.get("headless", "notes", {}) or {}
    except Exception:  # noqa: BLE001
        kept = {}
    out, seen = [], {}
    for text in warnings:
        entry = kept.get(text) if isinstance(kept, dict) else None
        first = float(entry.get("first", now)) if isinstance(entry, dict) else now
        last = float(entry.get("logged", 0)) if isinstance(entry, dict) else 0.0
        logged = last
        if now - last >= NOTE_AGAIN:
            days = (now - first) / 86400
            out.append(text if days < 1 else f"{text} (standing for {days:.0f} day{'' if round(days) == 1 else 's'})")
            logged = now
        seen[text] = {"first": first, "logged": logged}
    try:
        store.put("headless", "notes", seen)
    except Exception:  # noqa: BLE001
        pass
    return out


def _card_check(season, *, dry_run: bool = False) -> None:
    """Your row on the commissioner's sheet against the card you saved (cardcheck.py):
    written down every run, and one email the first time a difference shows."""
    try:
        from .pool import cardcheck
        from .site import cardmail
        year = results.season_year(season)
        for week in results.calendar_weeks(year, time.time()):
            found = cardcheck.check(season, week)
            if not found.compared:
                continue
            new = cardcheck.keep(found)
            if found.diffs:
                _log(f"card check: {found.headline()}")
            if new and not dry_run:
                try:
                    cardmail.send_note(f"Check your week {week} card - the sheet differs from what you saved",
                                       found.headline() + ":\n\n" + "\n".join(found.lines())
                                       + "\n\nIf that wasn't on purpose, tell the commissioner before kickoff.")
                    cardcheck.mark_alerted(week)
                    _log(f"card check: alert emailed for week {week}")
                except Exception as exc:  # noqa: BLE001
                    _log(f"card check: alert not sent: {exc}")
    except Exception as exc:  # noqa: BLE001 - never the cause of a failed run
        _log(f"card check failed: {exc!r}")


def _sentinel(season, *, dry_run: bool = False) -> None:
    """Sources against each other (consistency.py) for the week ahead: logged
    each run, and one email the first time a serious disagreement shows."""
    try:
        from . import consistency, store
        from .site import cardmail
        week = analytics.upcoming_week(season)
        found = consistency.week(season, week)
        for problem in found:
            _log(f"sources disagree, week {week}: {problem.game + ': ' if problem.game else ''}{problem.text}")
        serious = sorted(f"{p.kind}|{p.game}|{p.text}" for p in found if p.kind in ("moneyline", "source", "pool line"))
        told = store.get("consistency", str(week), {}) or {}
        new = [s for s in serious if s not in (told.get("sent") or [])]
        if new and not dry_run:
            try:
                cardmail.send_note(f"Week {week}: two sources disagree",
                                   "\n".join(s.split("|", 1)[1].replace("|", ": ") for s in new)
                                   + "\n\nTwo numbers that describe the same game can't both be right. "
                                     "Readiness lists it until they agree.")
                store.put("consistency", str(week), {"sent": sorted(set(serious) | set(told.get("sent") or [])),
                                                     "at": time.time()})
                _log(f"sources disagree: alert emailed for week {week}")
            except Exception as exc:  # noqa: BLE001
                _log(f"sources disagree: alert not sent: {exc}")
    except Exception as exc:  # noqa: BLE001 - never the cause of a failed run
        _log(f"consistency check failed: {exc!r}")


def _record_live(season) -> None:
    """A point for the game-day flight recorder (pool/recorder.py) when games are on."""
    try:
        from .pool import me, recorder
        weeks = results.calendar_weeks(results.season_year(season), time.time())
        if weeks and season.weeks.get(weeks[0]) is not None:
            if recorder.record(season, weeks[0], me.key(season)):
                _log(f"week {weeks[0]}: live point recorded")
    except Exception as exc:  # noqa: BLE001
        _log(f"flight recorder: {exc!r}")


#: The training ground's answer is redone weekly (Tue-Thu); older than this it is overdue.
TRAINING_OVERDUE = 8 * 86400
#: A started catch-up run is not started again for this long.
TRAINING_RETRY = 12 * 3600


def _heal_training(*, dry_run: bool = False, now: float | None = None, start=None) -> bool:
    """Start the training package's weekly command on its own when its weekly answer
    is overdue - the ACQL Training job had never run by 2026-10-20 and the
    answer was 8 days old. A separate process, so nothing here imports the
    training package (the dashboard must not). True when one was started."""
    import subprocess
    from . import store
    from .model import challengers
    now = time.time() if now is None else now
    answer = challengers.read()
    if answer is not None and now - answer.made < TRAINING_OVERDUE:
        return False
    try:
        tried = float(store.get("headless", "training_started", 0) or 0)
    except Exception:  # noqa: BLE001
        tried = 0.0
    if now - tried < TRAINING_RETRY or dry_run:
        return False
    try:
        store.put("headless", "training_started", now)
    except Exception:  # noqa: BLE001
        pass
    # its own process: the name is put together here so it is plainly a command to run,
    # not an import (the dashboard never imports the training package)
    args = [sys.executable, "-m", ".".join(("acql", "training")), "weekly"]
    try:
        if start is not None:
            start(args)
        else:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(args, cwd=str(Path(__file__).resolve().parent.parent), creationflags=flags,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        _log(f"training catch-up not started: {exc}")
        return False
    age = "none on disk" if answer is None else f"{(now - answer.made) / 86400:.0f} days old"
    _log(f"training answer overdue ({age}) - weekly training started in the background")
    return True


def _watch(season, *, dry_run: bool = False) -> None:
    """Deadeye's picks that changed side, and the deadline guardian (pool/alerts.py):
    an email only when one of those happens, to the card's own addresses."""
    try:
        from .pool import alerts
        from .site import cardmail
        year = results.season_year(season)
        week = analytics.upcoming_week(season)
        if season.weeks.get(week) is None:
            return
        notes = []
        turned = alerts.turned_picks(season, week, year)
        if turned:
            notes.append(f"{len(turned)} of {MODEL_NAME}'s week {week} picks changed side:\n"
                         + "\n".join("  " + t.text() for t in turned))
            for t in turned:
                _log(f"pick changed side: {t.text()}")
        guard = alerts.deadline_due(year, week)
        if guard:
            notes.append(guard)
            _log(f"deadline guardian: {guard}")
        if notes and not dry_run:
            subject = (f"Week {week}: {len(turned)} pick{'' if len(turned) == 1 else 's'} changed side"
                       if turned else f"Week {week}: cards due soon")
            try:
                cardmail.send_note(subject, "\n\n".join(notes))
                _log("alert emailed: " + subject)
            except Exception as exc:  # noqa: BLE001
                _log(f"alert not sent: {exc}")
    except Exception as exc:  # noqa: BLE001 - never the cause of a failed run
        _log(f"pick watch failed: {exc!r}")


def _ran(ok: bool, note: str = "") -> None:
    """When the last run finished and how - for the readiness page (readiness.py)."""
    try:
        from . import store
        store.put("headless", "last_run", {"at": time.time(), "ok": bool(ok), "note": note[:200]})
    except Exception:  # noqa: BLE001 - bookkeeping only
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acql.headless", description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--daily", action="store_true", help="every step, whatever the time")
    mode.add_argument("--poll", action="store_true", help="only when a look at ESPN is due")
    mode.add_argument("--email", action="store_true", help="email Deadeye's card for the week ahead")
    mode.add_argument("--brief", action="store_true", help="email the Sunday morning brief")
    mode.add_argument("--alerts", action="store_true",
                      help="only the deadline reminder (GitHub's cloud job runs this)")
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything but publish the website, or send the email")
    args = parser.parse_args(argv)

    # GitHub can send the emails and texts instead (site/snapshot.py): one sender, never two
    from .site import snapshot
    sending = args.email or args.brief or args.alerts
    if sending and snapshot.in_cloud() and not args.dry_run and not snapshot.cloud_sends():
        _log("cloud: sending is switched off on the PC (snapshot.py --cloud-on) - nothing sent")
        return 0
    if (args.email or args.brief) and snapshot.pc_should_skip("the card email" if args.email else "the Sunday brief"):
        return 0

    if args.alerts:
        from .site import pushalerts
        if not args.dry_run:
            _alert("deadline", pushalerts.remind_deadline)
        return 0

    if args.brief:
        try:
            return email_brief(dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001
            _log(f"sunday brief failed: {exc!r}\n{traceback.format_exc()}")
            return 1

    if args.email:
        # The poll starts on the same minute: wait for it rather than give up.
        waited = time.monotonic()
        while True:
            with _RunLock(LOCK_FILE) as mine:
                if mine:
                    try:
                        return email_card(dry_run=args.dry_run)
                    except Exception as exc:  # noqa: BLE001
                        _log(f"card email failed: {exc!r}\n{traceback.format_exc()}")
                        return 1
            if time.monotonic() - waited > EMAIL_WAIT:
                _log("card email: another run was still going after four minutes - not sent")
                return 1
            time.sleep(5)

    with _RunLock(LOCK_FILE) as mine:
        if not mine:
            _log("another run is still going - skipped")
            return 0
        try:
            from .site import pushalerts
            if not snapshot.cloud_sends():
                _alert("deadline", pushalerts.remind_deadline)
            if args.poll and not _poll_due():
                return 0
            _log("daily run" if args.daily else "game-day poll")
            return run(force=args.daily, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001
            _log(f"run failed: {exc!r}\n{traceback.format_exc()}")
            return 1
        finally:
            # the locked copy GitHub sends from, at most hourly (nothing until a key is made)
            if not args.dry_run and not snapshot.in_cloud():
                snapshot.upload_quietly()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
