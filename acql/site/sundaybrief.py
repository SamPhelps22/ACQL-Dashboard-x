"""The Sunday morning brief: the week's strongest calls, how the lines have
moved since they opened, and how much of the odds budget is left.

By Sunday the cards are in, so this is not a card to hand in: it is what to
watch before the early games. It is built only from what is already kept -
the stored lines, never a fresh fetch - so it costs nothing from the odds
budget it reports on.

It goes to the same place as Deadeye's card (cardmail.recipients): the
dashboard's own address, never the pool's recap list.

Nothing here knows about Qt.
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass
from email.message import EmailMessage

from .. import places
from ..feeds import odds, oddslock, results
from ..models import Season
from ..pool import briefing
from ..version import MODEL_NAME
from . import cardmail, mailer

#: How many of the week's picks count as its top calls.
TOP = 5
#: Requests the app keeps back each month (headless.ODDS_RESERVE).
RESERVE = 40
#: Below this many requests left above the reserve, the brief warns.
LOW = 30
#: How many models of the forecast log's scorecard the brief names.
BOARD = 3


@dataclass(frozen=True)
class Brief:
    week: int
    subject: str
    text: str
    html: str


def week_in_play(season: Season, now: float | None = None) -> int | None:
    """The latest week whose cards have locked - the one being played."""
    now = time.time() if now is None else now
    year = results.season_year(season, now)
    locked = [w for w in results.calendar_weeks(year, now)
              if oddslock.lock_time(year, w) <= now and season.weeks.get(w) is not None]
    return max(locked) if locked else None


def budget_note(left: int | None) -> tuple[str, bool]:
    """(what to say about the odds budget, whether it is a warning)."""
    if left is None:
        return "Odds budget: not known yet (no fetch this month).", False
    spare = left - RESERVE
    fetches = max(spare, 0) // 3
    if spare < LOW:
        return (f"Odds budget LOW: {left} requests left this month, {max(spare, 0)} above the "
                f"reserve of {RESERVE} - about {fetches} more fetches."), True
    return f"Odds budget: {left} requests left this month (about {fetches} fetches above the reserve).", False


def scoreboard(season: Season, now: float) -> list[dict]:
    """The forecast log's leaders this season (model/forecastlog.py); [] when it has none."""
    try:
        from ..model import forecastlog
        conn = forecastlog.connect()
        try:
            card = forecastlog.scorecard(conn, results.season_year(season, now))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - the brief goes out without it
        return []
    return [r for r in card if r.get("beat_line_rate") is not None][:BOARD]


def _score_line(r: dict) -> str:
    hit = f"{r['hit_rate']:.0%} right" if r.get("hit_rate") is not None else "no picks graded"
    return (f"{r['model_name']}: beat the close {r['beat_line']} of {r['line_games']} "
            f"({r['beat_line_rate']:.0%}), {hit}")


def honesty(season: Season) -> list[str]:
    """Calibration (analytics.calibration), a line a band: did its 70% picks win about 70%?"""
    try:
        from .. import analytics
        from ..model import pricing
        bands = analytics.calibration(pricing.graded_entries(season))
    except Exception:  # noqa: BLE001 - the brief goes out without it
        return []
    return [f"Called {b.label}: {b.hits} of {b.picks} came in ({b.hits / b.picks:.0%}, "
            f"it said {b.claimed:.0%})" for b in bands if b.picks >= 5]


def compose(season: Season, week: int | None = None, *, now: float | None = None,
            left: int | None = None, moves: list | None = None,
            board: list[dict] | None = None, honest: list[str] | None = None) -> Brief | None:
    """The brief for the week in play. None when there is nothing to say."""
    now = time.time() if now is None else now
    week = week_in_play(season, now) if week is None else week
    if week is None:
        return None
    brief = briefing.build(season, week)
    if not brief.choices:
        return None
    top = sorted(brief.choices, key=lambda c: -c.chance)[:TOP]
    moves = odds.movements(week) if moves is None else moves
    board = scoreboard(season, now) if board is None else board
    honest = honesty(season) if honest is None else honest
    budget, low = budget_note(odds.remaining() if left is None else left)

    subject = f"{places.BRAND} · Sunday brief, week {week}" + (" - odds budget low" if low else "")

    text = [f"{places.BRAND.upper()} - SUNDAY BRIEF, WEEK {week}", f"Powered by {MODEL_NAME}", "",
            f"{MODEL_NAME.upper()}'S TOP {len(top)} CALLS"]
    text += [f"  {c.pick} ({c.chance:.0%}) - {c.matchup}" for c in top]
    text += ["", "LINE MOVES SINCE OPEN"]
    text += ([f"  {game}: {then:+.1f} -> {nowl:+.1f}" for game, then, nowl in moves]
             or [f"  Nothing has moved {odds.BIG_MOVE:g} points or more."])
    if board:
        text += ["", "FORECAST SCORECARD (BEST AGAINST THE CLOSING LINE)"] + [f"  {_score_line(r)}" for r in board]
    if honest:
        text += ["", "ARE ITS CHANCES HONEST?"] + [f"  {h}" for h in honest]
    text += ["", budget, "", f"- {places.BRAND} (only you get this email)"]

    e = html.escape
    font = "font-family:Segoe UI,Arial,sans-serif"
    row = "<tr style='border-bottom:1px solid #e5e7eb'>"
    cell = "<td style='padding:6px 8px'>"
    body = [
        f"<div style='{font};font-size:15px;color:#111;max-width:640px'>",
        f"<p style='margin:0;font-size:12px;letter-spacing:0.14em;color:#b07a12;font-weight:700'>"
        f"{e(places.BRAND.upper())} · POWERED BY {e(MODEL_NAME.upper())}</p>",
        f"<h2 style='margin:2px 0 12px;font-size:22px'>Sunday brief · week {week}</h2>",
        f"<p style='margin:0 0 4px;font-size:17px'><b>{e(MODEL_NAME)}'s top {len(top)} calls</b></p>",
        "<table style='border-collapse:collapse;width:100%'>"
        + "".join(f"{row}{cell}<b>{e(c.pick)}</b><br><span style='color:#6b7280;font-size:12px'>"
                  f"{e(c.matchup)}</span></td>{cell}<b style='color:#0b7a2e'>{c.chance:.0%}</b></td></tr>"
                  for c in top) + "</table>",
        "<p style='margin:16px 0 4px;font-size:17px'><b>Line moves since open</b></p>",
    ]
    if moves:
        body.append("<table style='border-collapse:collapse;width:100%'>" + "".join(
            f"{row}{cell}{e(game)}</td>{cell}{then:+.1f} &rarr; <b>{nowl:+.1f}</b></td></tr>"
            for game, then, nowl in moves) + "</table>")
    else:
        body.append(f"<p style='color:#374151;margin:0'>Nothing has moved {odds.BIG_MOVE:g} points or more.</p>")
    if board:
        body.append("<p style='margin:16px 0 4px;font-size:17px'><b>Forecast scorecard</b></p>"
                    "<p style='margin:0 0 4px;color:#6b7280;font-size:12px'>Best against the closing line this season</p>"
                    + "".join(f"<p style='margin:2px 0'>{e(_score_line(r))}</p>" for r in board))
    if honest:
        body.append("<p style='margin:16px 0 4px;font-size:17px'><b>Are its chances honest?</b></p>"
                    + "".join(f"<p style='margin:2px 0'>{e(h)}</p>" for h in honest))
    body.append(f"<p style='margin:16px 0 0;color:{'#b3261e' if low else '#374151'}"
                f"{';font-weight:600' if low else ''}'>{e(budget)}</p>")
    body.append(f"<p style='color:#9ca3af;font-size:12px;margin-top:18px'>{e(places.BRAND)} · "
                "Only you get this email.</p></div>")
    return Brief(week, subject, "\n".join(text), "".join(body))


def message(brief: Brief, settings: mailer.MailSettings | None = None) -> EmailMessage:
    return cardmail.message(brief, settings)  # same sender, same only-you recipients


def send(brief: Brief, *, smtp_factory=None) -> list[str]:
    settings = mailer.MailSettings.load()
    mailer.send(settings, message(brief, settings), smtp_factory=smtp_factory)
    return cardmail.recipients(settings)
