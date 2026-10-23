"""The week's routine, ticking itself (idea #88), and what would have helped (idea #64).

Five steps a week, each read from what the app already sees - nothing to tick
by hand:

    1. lines in        the week has a market number
    2. card saved      you saved a card in the dashboard
    3. card on sheet   your row is on the commissioner's sheet
    4. sheet matches   your row is the card you saved (cardcheck.py)
    5. last week read  last week's autopsy brief went out

And after each week, one honest look back: across every game this season
where your sheet differed from Deadeye's card, would simply following
Deadeye have been better, and by how much - said only once there are 30
such games, because fewer can't tell skill from luck. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Games of disagreement before the look back says anything.
ENOUGH = 30


@dataclass(frozen=True)
class Step:
    name: str
    done: bool
    next_words: str        # what to do while it isn't done


@dataclass(frozen=True)
class Ritual:
    week: int
    steps: list[Step]

    @property
    def done(self) -> int:
        return sum(s.done for s in self.steps)

    @property
    def next_step(self) -> Step | None:
        return next((s for s in self.steps if not s.done), None)

    def words(self) -> str:
        nxt = self.next_step
        return f"Week {self.week}: {self.done}/{len(self.steps)}" + (f" · next: {nxt.next_words}" if nxt else " · all done")


def ritual(season, week: int) -> Ritual:
    from .. import store
    from ..model import predictions
    from . import cardcheck, cards, me, picks
    lines_in = bool(predictions.market_time(week))
    saved = cards.mine(week) is not None
    on_sheet, matches = False, False
    sheet = picks.load(week)
    name = (me.display(season) or me.NAME).casefold()
    if sheet is not None and any(" ".join(c.split()).casefold() == name for c in sheet.coaches):
        on_sheet = True
        try:
            matches = cardcheck.check(season, week).matches
        except Exception:  # noqa: BLE001
            matches = False
    try:
        read = int(store.get("autopsybrief", "sent", 0) or 0) >= week - 1
    except Exception:  # noqa: BLE001
        read = False
    return Ritual(week, [
        Step("Lines in", lines_in, "wait for the week's lines (or Update lines)"),
        Step("Card saved", saved, "save your card on My picks"),
        Step("Card on the sheet", on_sheet, "send your card to the commissioner"),
        Step("Sheet matches", matches and saved, "check the sheet against your saved card"),
        Step("Last week read", read, "read last week's autopsy"),
    ])


@dataclass(frozen=True)
class LookBack:
    games: int             # decided games where you went against Deadeye
    you: int               # you right, Deadeye wrong
    deadeye: int           # Deadeye right, you wrong

    @property
    def enough(self) -> bool:
        return self.games >= ENOUGH

    def words(self) -> str:
        if not self.games:
            return "You haven't gone against Deadeye on a decided game yet this season."
        if not self.enough:
            return (f"Going against Deadeye: you {self.you}, Deadeye {self.deadeye} over {self.games} decided games - "
                    f"too few to say what would have helped ({ENOUGH} needed).")
        net = self.deadeye - self.you
        if net > 0:
            return (f"Following Deadeye on every game you went against it would have won you {net} more point"
                    f"{'s' if net != 1 else ''} ({self.games} games: you {self.you}, Deadeye {self.deadeye}).")
        if net < 0:
            return (f"Your own calls against Deadeye have been worth {-net} point{'s' if net != -1 else ''} over "
                    f"{self.games} games (you {self.you}, Deadeye {self.deadeye}) - keep making them.")
        return f"Going against Deadeye has broken even over {self.games} games."


def look_back(season) -> LookBack:
    from . import journal
    found = [o for o in journal.overrides(season) if o.decided]
    return LookBack(len(found), sum(o.outcome == "you" for o in found),
                    sum(o.outcome not in ("you", "neither") for o in found))
