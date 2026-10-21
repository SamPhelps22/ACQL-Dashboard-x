"""Does the card on the commissioner's sheet match the card you saved?

The pick sheet that goes out after the deadline has every coach's row,
yours included. A slip on the entry form - a click on the wrong team -
costs a game, and it is only noticed, if ever, when the week is graded.
The saved card (cards.mine) is what you meant to hand in, so the two are
compared game by game, and for the Big Losers, as soon
as the sheet is read. A difference is reported, not corrected: you may have
changed your mind on the form on purpose.

No Qt here. Nothing is changed; the result is kept so an alert goes once.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

KIND = "card-check"


@dataclass(frozen=True)
class Diff:
    what: str           # "Game 9" / "Big Losers"
    matchup: str        # "Dallas @ Philadelphia" ("" for Big Losers)
    saved: str
    submitted: str


@dataclass(frozen=True)
class Check:
    week: int
    compared: bool                 # False when there was nothing to compare with
    reason: str = ""               # why not, when not
    games: int = 0                 # games compared
    diffs: list[Diff] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        return self.compared and not self.diffs

    def headline(self) -> str:
        if not self.compared:
            return self.reason
        if not self.diffs:
            return f"Week {self.week}: the sheet matches your saved card ({self.games} games)"
        n = len(self.diffs)
        return f"Week {self.week}: the sheet differs from your saved card in {n} place{'' if n == 1 else 's'}"

    def lines(self) -> list[str]:
        return [f"{d.what}{' (' + d.matchup + ')' if d.matchup else ''}: saved {d.saved or '-'}, "
                f"sheet has {d.submitted or '-'}" for d in self.diffs]


def _plain(text: object) -> str:
    return " ".join(str(text or "").split()).casefold()


def _coach(sheet, name: str) -> str:
    wanted = _plain(name)
    return next((c for c in sheet.coaches if _plain(c) == wanted), "")


def compare(week: int, saved, sheet, name: str) -> Check:
    """Compare a saved card (cards.Snapshot) with a sheet (picks.WeekPicks) for coach `name`."""
    from ..model.predictions import team_code
    if sheet is None:
        return Check(week, False, f"Week {week}: no pick sheet yet")
    if saved is None:
        return Check(week, False, f"Week {week}: no saved card to check the sheet against - "
                                  "save your card on My picks before you enter it")
    coach = _coach(sheet, name)
    if not coach:
        return Check(week, False, f"Week {week}: {name} isn't on the pick sheet")
    diffs: list[Diff] = []
    compared = 0
    for index in sorted(saved.take):
        label = str(saved.label.get(index, ""))
        away, _, home = label.partition(" @ ")
        game = sheet.game_for(away, home) if home else None
        if game is None:
            continue
        compared += 1
        mine, theirs = saved.take[index], game.picks.get(coach, "")
        if team_code(mine) != team_code(theirs):
            diffs.append(Diff(f"Game {index}", label, mine, theirs))
    if saved.losers and sheet.losers.get(coach):
        want = sorted(saved.losers)
        got = sorted(team_code(t) for t in sheet.losers[coach] if team_code(t))
        if want != got:
            diffs.append(Diff("Big Losers", "", ", ".join(c.upper() for c in want), ", ".join(c.upper() for c in got)))
    if compared == 0:
        return Check(week, False, f"Week {week}: none of the saved card's games are on the sheet")
    return Check(week, True, games=compared, diffs=diffs)


def check(season, week: int) -> Check:
    """Your saved card against the week's sheet, as stored now."""
    from . import cards, me, picks
    name = me.display(season) or me.NAME
    return compare(week, cards.mine(week), picks.load(week), name)


def kept(week: int) -> dict | None:
    from .. import store
    try:
        found = store.get(KIND, str(week), None)
    except Exception:  # noqa: BLE001
        return None
    return found if isinstance(found, dict) else None


def keep(result: Check, now: float | None = None) -> bool:
    """Write the result down. True when it is a new difference worth an alert
    (one that was not already reported for this week)."""
    from .. import store
    now = time.time() if now is None else now
    before = kept(result.week) or {}
    fingerprint = sorted(result.lines())
    new = bool(result.diffs) and before.get("fingerprint") != fingerprint
    try:
        store.put(KIND, str(result.week), {
            "at": now, "compared": result.compared, "reason": result.reason, "games": result.games,
            "diffs": [asdict(d) for d in result.diffs], "fingerprint": fingerprint,
            "alerted": before.get("alerted") if not new else None,
        })
    except Exception:  # noqa: BLE001 - the check is never what stops a run
        return False
    return new


def mark_alerted(week: int, now: float | None = None) -> None:
    from .. import store
    found = kept(week)
    if found is not None:
        found["alerted"] = time.time() if now is None else now
        try:
            store.put(KIND, str(week), found)
        except Exception:  # noqa: BLE001
            pass
