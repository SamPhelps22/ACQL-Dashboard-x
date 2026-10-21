"""Alerts worth an email: a pick that changed side, a deadline about to pass.

The card email already goes out Tuesday to Thursday with every change since
the last one counted ("11 changes since the last one") - most of them a
chance moving a point or two. The ones that matter are few: a pick that
changed side, and a card not saved with the deadline close. These are
worked out here and sent by the scheduled run (headless.py) to the card's
own addresses only (cardmail.send_note).

Each alert is remembered, so it goes once. No Qt here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

KIND = "alerts-sent"
#: The deadline guardian speaks this long before the cards are due.
GUARD_BEFORE = 3 * 3600


@dataclass(frozen=True)
class Turned:
    index: int
    matchup: str
    was: str
    now: str
    line_was: float | None
    line_now: float | None

    def text(self) -> str:
        moved = ""
        if self.line_was is not None and self.line_now is not None and self.line_was != self.line_now:
            moved = f" (the market moved from {self.line_was:+g} to {self.line_now:+g}, home side)"
        return f"Game {self.index}, {self.matchup}: now {self.now}, was {self.was}{moved}"


def _sent(week_key: str) -> dict:
    from .. import store
    try:
        found = store.get(KIND, week_key, {})
    except Exception:  # noqa: BLE001
        return {}
    return found if isinstance(found, dict) else {}


def _keep(week_key: str, value: dict) -> None:
    from .. import store
    try:
        store.put(KIND, week_key, value)
    except Exception:  # noqa: BLE001 - bookkeeping only
        pass


def compare_picks(before: dict, now: dict) -> list[Turned]:
    """Picks that changed side: `before`/`now` are {game index (str): [pick, market]}."""
    from ..model.predictions import team_code
    out = []
    for key, (pick, market) in sorted(now.items(), key=lambda kv: int(kv[0])):
        old = before.get(key)
        if not old or team_code(old[0]) == team_code(pick):
            continue
        out.append(Turned(int(key), "", old[0], pick, old[1], market))
    return out


def picks_now(season, week: int) -> tuple[dict, dict[int, str]]:
    """({game index: [Deadeye's side, the market's home margin]}, {index: matchup})."""
    from ..model import flips
    found = flips.week_flips(season, week)
    return ({str(f.index): [f.pick, f.market] for f in found}, {f.index: f.matchup for f in found})


def turned_picks(season, week: int, year: int, now: float | None = None) -> list[Turned]:
    """Picks that changed side since the last look, remembered so each is told once.
    The first look of a week only writes the baseline."""
    from ..feeds import oddslock
    now = time.time() if now is None else now
    if now >= oddslock.lock_time(year, week):
        return []
    key = f"{year}-{week}"
    sent = _sent(key)
    current, matchups = picks_now(season, week)
    if not current:
        return []
    before = sent.get("picks")
    sent["picks"] = current
    _keep(key, sent)
    if not isinstance(before, dict):
        return []
    return [Turned(t.index, matchups.get(t.index, ""), t.was, t.now, t.line_was, t.line_now)
            for t in compare_picks(before, current)]


def deadline_due(year: int, week: int, now: float | None = None) -> str | None:
    """The deadline guardian: a message when the cards are due within
    GUARD_BEFORE and no card is saved - once a week, and only for someone
    who saves cards (a saved card in any earlier week)."""
    from ..feeds import oddslock
    from . import cards
    now = time.time() if now is None else now
    lock = oddslock.lock_time(year, week)
    if not 0 < lock - now <= GUARD_BEFORE or cards.mine(week) is not None:
        return None
    if not any(cards.mine(w) is not None for w in range(1, week)):
        return None
    key = f"{year}-{week}"
    sent = _sent(key)
    if sent.get("guard"):
        return None
    sent["guard"] = now
    _keep(key, sent)
    hours = (lock - now) / 3600
    return (f"Week {week}'s cards are due in about {hours:.0f} hour{'' if round(hours) == 1 else 's'} "
            f"and no card is saved on My picks yet.")
