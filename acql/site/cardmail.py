"""Deadeye's card, emailed to whoever runs the dashboard - and nobody else.

The card is only useful if it is read before the pool's deadline, and the
dashboard is on one computer. So on the days that lead up to the deadline
the scheduled job (headless.py --email) sends it: every pick with its
chance and how the evidence splits, what has changed since the last email,
the Big Losers, and how long is left.

It goes to the dashboard's own Gmail address - the one it sends from - or
to the addresses kept under settings / cardmail. It never uses the recap's
list: that is the pool, and this is the one thing the pool doesn't get.

Nothing here knows about Qt.
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from email.message import EmailMessage

from ..pool import bigloser, briefing
from ..model import evidence
from . import mailer
from ..feeds import odds, oddslock, results
from .. import places
from ..models import Season
from ..version import MODEL_NAME

#: A chance has to move this far between emails to be worth a line.
MOVED = 0.05
#: Strength -> the colour it is written in.
COLOURS = {"Lock": "#0b7a2e", "Strong": "#3d8b3d", "Lean": "#b07a12", "Coin flip": "#6b7280"}


@dataclass(frozen=True)
class CardMail:
    week: int
    subject: str
    text: str
    html: str
    picks: dict[str, list] = field(default_factory=dict)     # game index -> [pick, chance]
    changes: tuple[str, ...] = ()
    losers: tuple[str, ...] = ()                             # its three Big Losers, as shown


# ---- who it goes to ------------------------------------------------------------------
def recipients(settings: mailer.MailSettings | None = None) -> list[str]:
    """The addresses the card goes to: the ones kept, else the sender's own."""
    settings = settings or mailer.MailSettings.load()
    try:
        from .. import store
        kept = store.get("settings", "cardmail", {})
        listed = [str(a).strip() for a in (kept.get("to") or [])] if isinstance(kept, dict) else []
    except Exception:  # noqa: BLE001 - an unreadable setting is the sender's own address
        listed = []
    listed = [a for a in listed if "@" in a]
    return listed or ([settings.sender] if settings.sender else [])


# ---- what was sent last time ------------------------------------------------------------
def _last(week: int) -> dict:
    try:
        from .. import store
        found = store.get("cardmail", str(week), {})
        return found if isinstance(found, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def remember(card: CardMail, now: float | None = None) -> None:
    """Keep what was sent, so the next email can say what has changed."""
    from .. import store
    try:
        store.put("cardmail", str(card.week), {"at": time.time() if now is None else now,
                                              "picks": card.picks, "losers": list(card.losers)})
    except store.StoreError:
        pass


def _changes(picks: dict[str, list], matchups: dict[str, str], before: dict) -> list[str]:
    old = before.get("picks") or {}
    out = []
    for index, (pick, chance) in picks.items():
        was = old.get(index)
        if not was:
            if old:
                out.append(f"New: {matchups[index]} - take {pick} ({chance:.0%})")
            continue
        if was[0] != pick:
            out.append(f"Changed: {matchups[index]} - now {pick} ({chance:.0%}), was {was[0]} ({was[1]:.0%})")
        elif abs(chance - was[1]) >= MOVED:
            out.append(f"Moved: {pick} ({matchups[index]}) {was[1]:.0%} → {chance:.0%}")
    return out


# ---- the email --------------------------------------------------------------------------
def compose(season: Season, week: int, *, now: float | None = None, before: dict | None = None) -> CardMail | None:
    """The card for a week as an email. None when nothing is priced yet."""
    now = time.time() if now is None else now
    brief = briefing.build(season, week)
    if not brief.choices:
        return None
    cases = {c.index: c for c in evidence.build(season, brief)}
    board = bigloser.board(season, week, brief)
    year = results.season_year(season, now)
    picks = {str(c.index): [c.pick, round(c.chance, 3)] for c in brief.choices}
    matchups = {str(c.index): c.matchup for c in brief.choices}
    earlier = _last(week) if before is None else before
    changes = _changes(picks, matchups, earlier)
    from ..model.predictions import display_team
    losers = tuple(display_team(b.team) for b in brief.losers)
    was = tuple(earlier.get("losers") or ())
    if was and set(was) != set(losers):
        changes.append("Big Losers changed: now " + ", ".join(losers) + " (was " + ", ".join(was) + ")")
    mine = ", ".join(f"{display_team(b.team)} ({b.chance:.0%})" for b in brief.losers)
    others = [o for o in board.best_gain if o.team not in losers]

    due = oddslock.coming(season, week, now) or oddslock.note(season, week, now)
    last_day = 0 <= oddslock.lock_time(year, week) - now < 86400
    waiting = [c for c in cases.values() if any(s.name == "Pool line" for s in c.signals)]
    unpriced = brief.games - brief.priced
    lines = odds.stored(week)
    checked = time.strftime("%a %I:%M %p", time.localtime(lines.at)).replace(" 0", " ") if lines else ""

    subject = (f"{'FINAL CHECK - ' if last_day else ''}{places.BRAND} · week {week} briefing: "
               f"{len(brief.choices)} picks"
               + (f", {len([c for c in changes if c.startswith('Changed')])} changed"
                  if any(c.startswith("Changed") for c in changes) else "")
               + (" - due today" if last_day else ""))

    notes = []
    if waiting:
        notes.append(
            f"{len(waiting)} big favourite{'s have' if len(waiting) != 1 else ' has'} no pool line "
            f"entered yet ({', '.join(c.pick for c in waiting)}). Those are priced straight up for "
            f"now and often change once the line is in: enter it on Deadeye Picks > My picks.")
    if unpriced > 0:
        notes.append(f"{unpriced} game{'s have' if unpriced != 1 else ' has'} no betting line posted yet.")
    if checked:
        notes.append(f"Lines last checked {checked}.")

    # ---- plain text
    text = [f"{places.BRAND.upper()} - {MODEL_NAME.upper()}'S CARD, WEEK {week}", f"Powered by {MODEL_NAME}", due, ""]
    if changes:
        text += ["SINCE THE LAST EMAIL"] + [f"  {c}" for c in changes] + [""]
    text.append("THE CARD")
    for c in brief.choices:
        case = cases.get(c.index)
        text.append(
            f"  #{c.index:<2} {c.pick} ({c.chance:.0%}, {evidence.strength(c.chance)})"
            f" - {c.matchup}" + (f" - pool line {c.line}" if c.line else "")
            + (f" - {case.summary()}" if case else ""))
    text += ["", f"  {brief.expected:.1f} of {len(brief.choices)} expected right"]
    if losers:
        text += ["", f"{MODEL_NAME.upper()}'S THREE BIG LOSERS",
                 f"  {mine} - {sum(b.chance for b in brief.losers):.1f} points expected"]
        if others:
            text.append("  To gain on the pool instead, swap in: "
                        + ", ".join(f"{o.team} ({o.chance:.0%})" for o in others))
    if notes:
        text += [""] + notes
    text += ["", f"- {places.BRAND} (only you get this email)"]

    # ---- html
    e = html.escape
    font = "font-family:Segoe UI,Arial,sans-serif"
    rows = []
    for c in brief.choices:
        case = cases.get(c.index)
        label = evidence.strength(c.chance)
        colour = COLOURS.get(label, "#333")
        changed = any(x.startswith("Changed") and c.matchup in x for x in changes)
        rows.append(
            f"<tr style='border-bottom:1px solid #e5e7eb{';background:#fff8e1' if changed else ''}'>"
            f"<td style='padding:7px 8px;color:#6b7280'>{c.index}</td>"
            f"<td style='padding:7px 8px'><b style='font-size:16px'>{e(c.pick)}</b>"
            f"<br><span style='color:#6b7280;font-size:12px'>{e(c.matchup)}"
            + (f" · pool line {e(c.line)}" if c.line else "") + "</span></td>"
            f"<td style='padding:7px 8px;white-space:nowrap'><b style='color:{colour}'>{c.chance:.0%}</b>"
            f"<br><span style='color:{colour};font-size:12px'>{label}</span></td>"
            f"<td style='padding:7px 8px;color:#6b7280;font-size:13px'>{'<br>'.join(e(x) for x in case.lines()) if case else ''}</td>"
            "</tr>")
    body = [
        f"<div style='{font};font-size:15px;color:#111;max-width:640px'>",
        f"<p style='margin:0;font-size:12px;letter-spacing:0.14em;color:#b07a12;font-weight:700'>"
        f"{e(places.BRAND.upper())} · POWERED BY {e(MODEL_NAME.upper())}</p>",
        f"<h2 style='margin:2px 0 4px;font-size:22px'>{e(MODEL_NAME)}'s card · week {week}</h2>",
        f"<p style='margin:0 0 14px;color:{'#b3261e' if last_day else '#374151'};font-weight:600'>{e(due)}</p>",
    ]
    if changes:
        body.append("<div style='background:#fff8e1;border-left:4px solid #f2b83a;padding:10px 12px;margin:0 0 14px'>"
                    "<b>Since the last email</b><br>" + "<br>".join(e(c) for c in changes) + "</div>")
    body.append("<table style='border-collapse:collapse;width:100%'>"
                "<tr style='text-align:left;color:#6b7280;font-size:12px;border-bottom:2px solid #111'>"
                "<th style='padding:4px 8px'>#</th><th style='padding:4px 8px'>Take</th>"
                "<th style='padding:4px 8px'>Chance</th><th style='padding:4px 8px'>Evidence</th></tr>"
                + "".join(rows) + "</table>")
    body.append(f"<p style='color:#374151'>{brief.expected:.1f} of {len(brief.choices)} expected right.</p>")
    if losers:
        body.append(
            f"<p style='margin:16px 0 4px;font-size:17px'><b>{e(MODEL_NAME)}'s three Big Losers</b></p>"
            "<table style='border-collapse:collapse;width:100%'>" + "".join(
                f"<tr style='border-bottom:1px solid #e5e7eb'><td style='padding:6px 8px'>"
                f"<b style='font-size:16px'>{e(display_team(b.team))}</b>"
                f"<br><span style='color:#6b7280;font-size:12px'>against {e(display_team(b.opponent))}</span></td>"
                f"<td style='padding:6px 8px;white-space:nowrap'><b style='color:#b3261e'>{b.chance:.0%}</b>"
                f"<br><span style='color:#6b7280;font-size:12px'>to lose by 15+</span></td></tr>"
                for b in brief.losers) + "</table>"
            f"<p style='color:#374151;margin:6px 0 0'>{sum(b.chance for b in brief.losers):.1f} Big Loser "
            "points expected."
            + (" To gain on the pool instead, swap in "
               + e(", ".join(f"{o.team} ({o.chance:.0%})" for o in others)) + "." if others else "")
            + "</p>")
    for note in notes:
        body.append(f"<p style='color:#6b7280;font-size:13px;margin:10px 0 0'>{e(note)}</p>")
    body.append(f"<p style='color:#9ca3af;font-size:12px;margin-top:18px'>{e(places.BRAND)} · {e(places.TAGLINE)} "
                "Only you get this email; the full case for every pick is on Deadeye Picks.</p></div>")
    return CardMail(week, subject, "\n".join(text), "".join(body), picks, tuple(changes), losers)


def message(card: CardMail, settings: mailer.MailSettings | None = None) -> EmailMessage:
    settings = settings or mailer.MailSettings.load()
    to = recipients(settings)
    if not settings.sender or not settings.sealed_password or not to:
        raise mailer.MailError("Email isn't set up in the dashboard yet (Results > Email settings).")
    msg = EmailMessage()
    msg["From"] = settings.sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = card.subject
    msg.set_content(card.text)
    msg.add_alternative(card.html, subtype="html")
    return msg


def send_note(subject: str, text: str, *, smtp_factory=None, dry_run: bool = False) -> list[str]:
    """A short plain-text alert to the card's own addresses (never the pool's
    recap list). Returns who it went to; with dry_run, who it would go to."""
    settings = mailer.MailSettings.load()
    to = recipients(settings)
    if not settings.sender or not settings.sealed_password or not to:
        raise mailer.MailError("Email isn't set up in the dashboard yet (Results > Email settings).")
    if dry_run:
        return to
    msg = EmailMessage()
    msg["From"] = settings.sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(text + "\n\n- Operation Sunday")
    mailer.send(settings, msg, smtp_factory=smtp_factory)
    return to


def send(card: CardMail, *, smtp_factory=None) -> list[str]:
    """Send the card and remember it. Returns who it went to."""
    settings = mailer.MailSettings.load()
    mailer.send(settings, message(card, settings), smtp_factory=smtp_factory)
    remember(card)
    return recipients(settings)
