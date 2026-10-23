"""A past week as it stood at the pick deadline (idea #7, time-travel).

Built only from what was written down before the deadline and never
rewritten: the week's known snapshot (known.py - lines, pool lines, the
scouting report as it stood), Deadeye's card as recorded (cards.model) and
the card you saved (cards.mine). The result is shown beside it, clearly as
what happened afterwards. Anything that was put together after the fact -
a card rebuilt later, a snapshot never frozen - is said so, never passed off
as the record.

No Qt here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Row:
    index: int
    matchup: str
    line: str = ""             # the betting line as known: "Buffalo -6.5"
    pool_line: str = ""
    deadeye: str = ""
    chance: float | None = None
    yours: str = ""
    result: str = ""           # who was credited, filled in afterwards ("" while open)


@dataclass(frozen=True)
class View:
    week: int
    rows: list[Row] = field(default_factory=list)
    snapshot_at: float | None = None      # when the known snapshot was last written
    frozen: bool = False                  # it was sealed at the deadline
    card_at: float | None = None
    rebuilt: bool = False                 # Deadeye's card was made after the fact
    mine_at: float | None = None
    from_sheet: bool = False              # your side came from the commissioner's sheet, not a saved card

    @property
    def empty(self) -> bool:
        return not self.rows

    def caveats(self) -> list[str]:
        out = []
        if self.snapshot_at is None:
            out.append("No snapshot of the lines was written for this week before its deadline.")
        elif not self.frozen:
            out.append("The lines snapshot was never sealed at the deadline; it shows the last one written.")
        if self.card_at is None:
            out.append("No card of the model's was recorded for this week.")
        elif self.rebuilt:
            out.append("The model's card for this week was rebuilt afterwards from replays, not recorded at the time.")
        if self.mine_at is None:
            out.append("Your picks are from the commissioner's sheet (no card was saved in the dashboard)."
                       if self.from_sheet else "No card of yours is on record for this week.")
        return out


def weeks(season) -> list[int]:
    """Weeks with anything recorded at their deadline, newest first."""
    from ..feeds import results
    from ..pool import cards
    from . import known
    year = results.season_year(season)
    found = [n for n in season.weeks if known.kept(year, n) or cards.model(n) or cards.mine(n)]
    return sorted(found, reverse=True)


def view(season, week: int) -> View:
    from ..feeds import results
    from ..pool import cards, journal
    from . import known
    year = results.season_year(season)
    snap = known.kept(year, week) or {}
    games = snap.get("games") or {}
    model, mine = cards.model(week), cards.mine(week)
    slate = season.weeks.get(week)
    by_index = {g.index: g for g in (slate.games if slate else [])}
    indices = sorted({int(i) for i in games} | set(model.take if model else {}) | set(mine.take if mine else {})
                     | set(by_index))
    sheet_side = {} if mine else _sheet(season, week)
    rows = []
    for i in indices:
        report = games.get(str(i)) or {}
        game = by_index.get(i)
        label = (report.get("matchup") or (model.label.get(i) if model else "") or (game.label if game else f"Game {i}"))

        def named(team: str) -> str:
            return journal._name(game, team) if game is not None and team else team
        rows.append(Row(
            index=i, matchup=label, line=str(report.get("line") or ""), pool_line=str(report.get("pool_line") or ""),
            deadeye=named(model.take.get(i, "")) if model else "",
            chance=model.chance.get(i) if model else None,
            yours=named(mine.take.get(i, "")) if mine else named(sheet_side.get(i, "")),
            result=named(game.winner) if game is not None and game.played and game.winner else ""))
    return View(week, rows, float(snap["at"]) if snap.get("at") else None, bool(snap.get("frozen")),
                model.at if model else None, bool(model.rebuilt) if model else False, mine.at if mine else None,
                bool(sheet_side))


def _sheet(season, week: int) -> dict[int, str]:
    """Your row on the commissioner's sheet for the week: game index -> side."""
    try:
        from ..pool import me, picks
        sheet = picks.load(week)
        wk = season.weeks.get(week)
        if sheet is None or wk is None:
            return {}
        wanted = " ".join((me.display(season) or me.NAME).split()).casefold()
        coach = next((c for c in sheet.coaches if " ".join(c.split()).casefold() == wanted), None)
        if coach is None:
            return {}
        out = {}
        for g in wk.games:
            row = sheet.game_for(g.away, g.home)
            side = row.picks.get(coach, "") if row is not None else ""
            if side:
                out[g.index] = side
        return out
    except Exception:  # noqa: BLE001
        return {}


def stamp(at: float | None) -> str:
    if not at:
        return "never"
    return time.strftime("%a %b %d, %I:%M %p", time.localtime(at)).replace(" 0", " ")
