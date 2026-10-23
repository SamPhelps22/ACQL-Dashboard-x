"""The autopsy brief: a short look back at the week just finished (idea #62).

The Sunday brief looks forward. This closes the loop once the week's last
game is final: your hits and misses, Deadeye's, how lucky the week was,
where you and Deadeye split and who was right, the game that caught the
most of the pool out, Big Loser and the suicide pick, and the spots in
Deadeye's record worth watching next week.

Sent once a week by the nightly run, to the card's own addresses
(cardmail.recipients) - only Sam, never the pool. Built only from what is
kept: no fetch, nothing from the odds budget.

Nothing here knows about Qt.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from email.message import EmailMessage

from .. import places
from ..models import Season
from ..version import MODEL_NAME
from . import cardmail, mailer

#: How many blind spots the brief names.
SPOTS = 3


@dataclass(frozen=True)
class Brief:
    week: int
    subject: str
    text: str
    html: str


@dataclass
class Facts:
    """What the brief says, worked out before it is written."""

    week: int
    you: str = ""
    hits: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)
    rank: int | None = None
    model_right: int | None = None
    model_games: int = 0
    luck: tuple[int, float] | None = None        # (wins, expected)
    splits: list[tuple[str, str, str, str]] = field(default_factory=list)  # matchup, yours, Deadeye's, who
    swing: tuple[str, str, int, int] | None = None   # matchup, winner, coaches right, coaches picking
    big_loser: list[tuple[str, bool]] = field(default_factory=list)
    suicide: tuple[str, bool] | None = None      # team, survived
    spots: list[str] = field(default_factory=list)
    helped: str = ""            # what would have helped, across the season (ritual.look_back, #64)


def finished(season: Season) -> int | None:
    """The latest week with every game played."""
    done = [n for n, w in season.weeks.items() if w.games and all(g.played for g in w.games)]
    return max(done) if done else None


def facts(season: Season, week: int, *, graded=None) -> Facts | None:
    from ..model import luck as luckmod
    from ..model.predictions import team_code
    from ..pool import bigloser, cards, journal, me
    wk = season.weeks.get(week)
    if wk is None or not wk.games:
        return None
    out = Facts(week)
    key = me.key(season)
    out.you = me.display(season) or me.NAME
    played = sorted((g for g in wk.games if g.played), key=lambda g: g.index)
    every = luckmod.picks_of(wk)
    mine = every.get(key, {})
    for g in played:
        pick = mine.get(g.index)
        if pick:
            (out.hits if team_code(pick) == team_code(g.winner) else out.misses).append(
                f"{journal._name(g, pick)} ({g.label})")
    line = wk.lines.get(key)
    if line is not None:
        out.rank = line.rank
        if line.suicide_pick:
            out.suicide = (line.suicide_pick, not line.suicide_out)
    model = cards.model(week)
    if model is not None:
        took = [(g, model.take.get(g.index)) for g in played if model.take.get(g.index)]
        out.model_games = len(took)
        out.model_right = sum(1 for g, t in took if team_code(t) == team_code(g.winner))
    try:
        found = luckmod.week_luck(season, week).get(key)
        if found:
            out.luck = (found[0], found[1])
    except Exception:  # noqa: BLE001 - the brief goes out without it
        pass
    try:
        out.splits = [(o.matchup, o.yours, o.deadeye, o.outcome)
                      for o in journal.overrides(season) if o.week == week and o.decided]
    except Exception:  # noqa: BLE001
        pass
    worst = None
    for g in played:
        sides = [c[g.index] for c in every.values() if c.get(g.index)]
        if len(sides) < 2:
            continue
        right = sum(1 for s in sides if team_code(s) == team_code(g.winner))
        if worst is None or right / len(sides) < worst[2] / worst[3]:
            worst = (g.label, journal._name(g, g.winner), right, len(sides))
    out.swing = worst
    if line is not None and line.big_loser_picks:
        blown = bigloser.blown(season, week)
        if blown is not None:
            out.big_loser = [(t, team_code(t) in blown) for t in line.big_loser_picks if t]
    try:
        from ..pool import ritual
        out.helped = ritual.look_back(season).words()
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..model import autopsy
        games = autopsy.graded(season) if graded is None else graded
        out.spots = [f"{r.name}: {r.right} of {r.picks} came in, it expected {r.expected:.1f} ({r.verdict})"
                     for r in autopsy.blind_spots(games, SPOTS)]
    except Exception:  # noqa: BLE001
        pass
    return out


def compose(season: Season, week: int | None = None, *, found: Facts | None = None) -> Brief | None:
    """The brief for the latest finished week. None when no week is finished."""
    week = finished(season) if week is None else week
    if week is None:
        return None
    f = facts(season, week) if found is None else found
    if f is None:
        return None
    n = len(f.hits) + len(f.misses)
    you_line = f"{len(f.hits)} of {n}" + (f", week rank {f.rank}" if f.rank else "")
    model_line = (f"{f.model_right} of {f.model_games}" if f.model_right is not None
                  else "no card kept for this week")
    sections: list[tuple[str, list[str]]] = []
    sections.append(("Your week", [f"{f.you}: {you_line}", f"{MODEL_NAME}: {model_line}"]
                     + ([f"Missed: {', '.join(f.misses)}"] if f.misses else [])))
    if f.luck:
        wins, expected = f.luck
        diff = wins - expected
        word = "lucky" if diff >= 0.5 else "unlucky" if diff <= -0.5 else "about par"
        sections.append(("Luck", [f"Your picks deserved {expected:.1f} wins and got {wins} "
                                  f"({diff:+.1f}, {word})."]))
    if f.splits:
        won = sum(1 for s in f.splits if s[3] == "you")
        lost = sum(1 for s in f.splits if s[3] == MODEL_NAME)
        sections.append((f"Where you went against {MODEL_NAME} (you {won}, {MODEL_NAME} {lost})",
                         [f"{m}: you {y}, {MODEL_NAME} {d} - {'you were right' if w == 'you' else MODEL_NAME + ' was right' if w == MODEL_NAME else 'neither'}"
                          for m, y, d, w in f.splits]))
    if f.swing:
        m, winner, right, total = f.swing
        sections.append(("The game that caught the pool out",
                         [f"{m}: {winner} won; only {right} of {total} coaches had them."]))
    extra = []
    if f.big_loser:
        extra.append("Big Loser: " + ", ".join(f"{t} {'hit' if hit else 'missed'}" for t, hit in f.big_loser))
    if f.suicide:
        extra.append(f"Suicide: {f.suicide[0]} - {'still alive' if f.suicide[1] else 'out'}")
    if extra:
        sections.append(("Side pools", extra))
    if f.helped:
        sections.append(("What would have helped", [f.helped]))
    if f.spots:
        sections.append((f"Worth watching next week ({MODEL_NAME}'s weakest spots so far)", f.spots))

    subject = f"{places.BRAND} · Week {week} autopsy: you {len(f.hits)}-{len(f.misses)}"
    text = [f"{places.BRAND.upper()} - WEEK {week} AUTOPSY", ""]
    for title, lines in sections:
        text += [title.upper()] + [f"  {x}" for x in lines] + [""]
    text.append(f"- {places.BRAND} (only you get this email)")

    e = html.escape
    font = "font-family:Segoe UI,Arial,sans-serif"
    body = [f"<div style='{font};font-size:15px;color:#111;max-width:640px'>",
            f"<p style='margin:0;font-size:12px;letter-spacing:0.14em;color:#b07a12;font-weight:700'>"
            f"{e(places.BRAND.upper())} · POWERED BY {e(MODEL_NAME.upper())}</p>",
            f"<h2 style='margin:2px 0 12px;font-size:22px'>Week {week} autopsy</h2>"]
    for title, lines in sections:
        body.append(f"<p style='margin:16px 0 4px;font-size:17px'><b>{e(title)}</b></p>")
        body += [f"<p style='margin:2px 0'>{e(x)}</p>" for x in lines]
    body.append(f"<p style='color:#9ca3af;font-size:12px;margin-top:18px'>{e(places.BRAND)} · "
                "Only you get this email.</p></div>")
    return Brief(week, subject, "\n".join(text), "".join(body))


def message(brief: Brief, settings: mailer.MailSettings | None = None) -> EmailMessage:
    return cardmail.message(brief, settings)  # same sender, same only-you recipients


def send(brief: Brief, *, smtp_factory=None) -> list[str]:
    settings = mailer.MailSettings.load()
    mailer.send(settings, message(brief, settings), smtp_factory=smtp_factory)
    return cardmail.recipients(settings)
