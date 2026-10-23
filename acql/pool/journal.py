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
