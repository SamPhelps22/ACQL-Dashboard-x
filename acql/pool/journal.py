"""The decision journal: every game you took against Deadeye, why, and who was right.

The report card says how your card did against the model's overall. It
cannot say which of your own reasons for going against it are worth
keeping - a hunch about an injury, a read on the weather, fading the crowd.
So each game where your row on the commissioner's sheet differs from
Deadeye's card is listed here, you can give it a reason (a tag and a line),
and once the game is graded the reasons are scored: how often you were right
when you overrode it for that reason, against how often Deadeye would have
been.

Your side comes from the pick sheet (what you actually handed in), Deadeye's
from its card as kept at the deadline (cards.model) - marked when that card
was rebuilt after the fact. Reasons are kept in the app's database under
"journal". No Qt here; nothing here changes a pick.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..version import MODEL_NAME

KIND = "journal"
TAGS = ("injury", "weather", "line move", "matchup", "crowd", "gut", "other")
UNTAGGED = "no reason given"


@dataclass(frozen=True)
class Override:
    week: int
    index: int
    matchup: str
    yours: str
    deadeye: str
    credited: str          # the side the pool credited, "" while open
    rebuilt: bool          # Deadeye's card for that week was made after the fact
    tag: str = ""
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.week}-{self.index}"

    @property
    def decided(self) -> bool:
        return bool(self.credited)

    @property
    def you_right(self) -> bool:
        from ..model.predictions import team_code
        return self.decided and team_code(self.yours) == team_code(self.credited)

    @property
    def deadeye_right(self) -> bool:
        from ..model.predictions import team_code
        return self.decided and team_code(self.deadeye) == team_code(self.credited)

    @property
    def outcome(self) -> str:
        if not self.decided:
            return "to play"
        if self.you_right and not self.deadeye_right:
            return "you"
        if self.deadeye_right and not self.you_right:
            return MODEL_NAME
        return "neither"


@dataclass(frozen=True)
class Tally:
    tag: str
    games: int
    decided: int
    you: int               # you right, Deadeye wrong
    deadeye: int           # Deadeye right, you wrong

    @property
    def net(self) -> int:
        return self.you - self.deadeye


def reasons() -> dict:
    from .. import store
    try:
        found = store.items(KIND)
    except Exception:  # noqa: BLE001
        return {}
    return found if isinstance(found, dict) else {}


def give_reason(week: int, index: int, tag: str, note: str = "", now: float | None = None) -> None:
    """Keep (or with no tag and no note, forget) the reason for one override."""
    from .. import store
    key = f"{int(week)}-{int(index)}"
    tag = tag if tag in TAGS else ""
    note = " ".join(str(note or "").split())[:200]
    if not tag and not note:
        store.delete(KIND, key)
        return
    store.put(KIND, key, {"tag": tag, "note": note, "at": time.time() if now is None else now})


def overrides(season, name: str | None = None) -> list[Override]:
    """Every game, week by week, where your sheet row differs from Deadeye's kept card."""
    from ..model.predictions import team_code
    from . import cards, me, picks
    name = name or me.display(season) or me.NAME
    wanted = " ".join(name.split()).casefold()
    given = reasons()
    out = []
    for number in sorted(season.weeks):
        week = season.weeks[number]
        model, sheet = cards.model(number), picks.load(number)
        if model is None or sheet is None or not week.games:
            continue
        model = cards.aligned(model, cards._slate(week.games))   # the slate may have been renumbered
        coach = next((c for c in sheet.coaches if " ".join(c.split()).casefold() == wanted), None)
        if coach is None:
            continue
        for game in sorted(week.games, key=lambda g: g.index):
            row = sheet.game_for(game.away, game.home)
            mine = row.picks.get(coach, "") if row is not None else ""
            theirs = model.take.get(game.index, "")
            if not mine or not theirs or team_code(mine) == team_code(theirs):
                continue
            reason = given.get(f"{number}-{game.index}") or {}
            out.append(Override(number, game.index, game.label, _name(game, mine), _name(game, theirs),
                                _name(game, game.winner) if game.played and game.winner else "",
                                bool(model.rebuilt), str(reason.get("tag") or ""), str(reason.get("note") or "")))
    return out


def _name(game, team: str) -> str:
    """The slate's own spelling of a team ("new york jets" -> "New York Jets")."""
    from ..model.predictions import team_code
    found = next((side for side in (game.home, game.away) if team_code(side) == team_code(team)), str(team))
    return found.title() if found.isupper() or found.islower() else found


@dataclass(frozen=True)
class Fragility:
    """How much a head-to-head record can be read into (sprint 2026-10-25).

    Only the games one side got right and the other wrong decide it. `flips` is
    how many of those would have to have gone the other way for the side behind
    to be ahead; `p` is the exact two-sided sign test - how often a fair coin,
    settling the same number of games, comes out at least this lopsided.
    """

    you: int
    deadeye: int

    @property
    def decisive(self) -> int:
        return self.you + self.deadeye

    @property
    def lead(self) -> int:
        return abs(self.you - self.deadeye)

    @property
    def flips(self) -> int:
        return self.lead // 2 + 1 if self.lead else 0

    @property
    def p(self) -> float:
        from math import comb
        n, low = self.decisive, min(self.you, self.deadeye)
        if not n or not self.lead:
            return 1.0
        tail = sum(comb(n, k) for k in range(low + 1)) / 2 ** n
        return min(1.0, 2 * tail)

    def words(self, you: str = "you") -> str:
        """One plain sentence, "" when nothing has been decided yet."""
        n = self.decisive
        if not n:
            return ""
        both = f"{you} and {MODEL_NAME}"
        if not self.lead:
            return f"Level on the {_count(n, 'game')} that split {both} - nothing to read into yet."
        behind = MODEL_NAME if self.you > self.deadeye else you
        p = self.p
        odds = f"about 1 time in {round(1 / p)}" if p < 0.5 else f"{p:.0%} of the time"
        verdict = ("luck alone rarely does that" if p <= 0.05
                   else "so it is still within what luck alone does")
        return (f"{self.flips} of the {_count(n, 'result')} that split {both} going the other way would put "
                f"{behind} ahead; a coin settling {n} games comes out at least this one-sided {odds} - "
                f"{verdict}.")


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def tallies(found: list[Override]) -> list[Tally]:
    """Per reason, then all together: how the overrides came out."""
    groups: dict[str, list[Override]] = {}
    for o in found:
        groups.setdefault(o.tag or UNTAGGED, []).append(o)
    out = []
    for tag in [t for t in TAGS if t in groups] + ([UNTAGGED] if UNTAGGED in groups else []):
        rows = groups[tag]
        out.append(Tally(tag, len(rows), sum(o.decided for o in rows),
                         sum(o.outcome == "you" for o in rows), sum(o.outcome == MODEL_NAME for o in rows)))
    if found:
        out.append(Tally("all", len(found), sum(o.decided for o in found),
                         sum(o.outcome == "you" for o in found), sum(o.outcome == MODEL_NAME for o in found)))
    return out
