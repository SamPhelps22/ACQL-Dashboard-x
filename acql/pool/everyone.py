"""Everyone's picks for a week, side by side.

The pick sheet has every coach's side in every game, their three Big Losers
and their suicide pick. This lays the whole pool out as one board - a row a
coach, a column a game - with each pick marked once its game is decided, and
counts how the pool split on every game.

When a week has no pick sheet (an old week typed into the workbook), the
board is built from the graded lines instead, which only know the games
already played.

No Qt here: ui/pages/everyone.py lays it out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model import luck
from . import picks
from ..models import Season, same_team
from ..model.predictions import display_team, team_code


def _plain(name: object) -> str:
    return "".join(c for c in str(name or "").casefold() if c.isalnum())


def short(team: object) -> str:
    """A team as the board writes it: "DAL"."""
    return team_code(team).upper()


@dataclass(frozen=True)
class GameColumn:
    index: int
    away: str               # "TB"
    home: str               # "DAL"
    matchup: str            # "Tampa Bay @ Dallas"
    line: str               # the pool's line: "Dallas by 9", or ""
    winner: str             # the credited side's code once decided, else ""
    on_away: int            # cards on each side
    on_home: int

    @property
    def cards(self) -> int:
        return self.on_away + self.on_home

    @property
    def favourite(self) -> str:
        """The side most cards are on ("" when level or nobody has picked)."""
        if self.on_away == self.on_home:
            return ""
        return self.away if self.on_away > self.on_home else self.home

    @property
    def share(self) -> float:
        """The share of cards on the more popular side, 0.5 to 1."""
        return max(self.on_away, self.on_home) / self.cards if self.cards else 0.0


@dataclass(frozen=True)
class CoachCard:
    key: str                # the coach's key in the season, or "" if only the sheet knows them
    name: str
    picks: dict[int, str] = field(default_factory=dict)     # game number -> team code ("DAL")
    losers: tuple[str, ...] = ()
    suicide: str = ""

    def state(self, game: GameColumn) -> str:
        """"right", "wrong", "open" (picked, not decided) or "" (no pick)."""
        pick = self.picks.get(game.index)
        if not pick:
            return ""
        if not game.winner:
            return "open"
        return "right" if pick == game.winner else "wrong"

    def right(self, games: list[GameColumn]) -> int:
        return sum(1 for g in games if self.state(g) == "right")

    def with_crowd(self, games: list[GameColumn]) -> tuple[int, int]:
        """(games this card is on the more popular side, games with a more popular side that it picked)."""
        both = [g for g in games if g.favourite and self.picks.get(g.index)]
        return sum(1 for g in both if self.picks[g.index] == g.favourite), len(both)


@dataclass(frozen=True)
class Board:
    week: int
    games: list[GameColumn] = field(default_factory=list)
    coaches: list[CoachCard] = field(default_factory=list)
    from_sheet: bool = False

    @property
    def decided(self) -> list[GameColumn]:
        return [g for g in self.games if g.winner]

    def coach(self, key: str) -> CoachCard | None:
        return next((c for c in self.coaches if key and c.key == key), None)

    @property
    def most_popular(self) -> GameColumn | None:
        """The game the pool agrees on most."""
        return max((g for g in self.games if g.cards), key=lambda g: (g.share, g.cards), default=None)

    @property
    def most_split(self) -> GameColumn | None:
        """The game the pool is most divided on."""
        return min((g for g in self.games if g.cards), key=lambda g: (g.share, -g.cards), default=None)


def weeks(season: Season) -> list[int]:
    """Weeks with anyone's picks to show, oldest first."""
    kept = picks.load_all()
    out = []
    for number, week in sorted(season.weeks.items()):
        if not week.games:
            continue
        sheet = kept.get(number)
        if (sheet is not None and sheet.games) or any(line.correct_picks for line in week.lines.values()):
            out.append(number)
    return out


def build(season: Season, number: int) -> Board:
    week = season.weeks.get(number)
    if week is None or not week.games:
        return Board(number)
    games = sorted(week.games, key=lambda g: g.index)
    sheet = picks.load(number)
    by_name = {_plain(p.display): key for key, p in season.players.items()}
    cards: dict[str, CoachCard] = {}

    if sheet is not None and sheet.games:
        taken: dict[str, dict[int, str]] = {name: {} for name in sheet.coaches}
        for game in games:
            row = sheet.game_for(game.away, game.home)
            if row is None:
                continue
            for name, team in row.picks.items():
                code = short(team)
                if code in (short(game.away), short(game.home)):
                    taken.setdefault(name, {})[game.index] = code
        for name, mine in taken.items():
            key = by_name.get(_plain(name), "")
            shown = season.players[key].display if key else name
            cards[name] = CoachCard(
                key=key, name=shown, picks=mine,
                losers=tuple(short(t) for t in sheet.losers.get(name, []) if short(t)),
                suicide=short(sheet.suicide.get(name, "")),
            )
    else:
        for key, mine in luck.picks_of(week).items():
            player = season.players.get(key)
            cards[key] = CoachCard(key=key, name=player.display if player else key,
                                   picks={i: short(team) for i, team in mine.items() if short(team)})

    columns = []
    for game in games:
        away, home = short(game.away), short(game.home)
        winner = ""
        if game.played:
            winner = home if same_team(game.winner, game.home) else away if same_team(game.winner, game.away) else ""
        columns.append(GameColumn(
            index=game.index, away=away, home=home, matchup=game.label,
            line=(f"{display_team(game.line_favourite)} by {game.line:g}"
                  if game.line is not None and game.line_favourite else ""),
            winner=winner,
            on_away=sum(1 for c in cards.values() if c.picks.get(game.index) == away),
            on_home=sum(1 for c in cards.values() if c.picks.get(game.index) == home),
        ))
    coaches = sorted(cards.values(), key=lambda c: c.name.casefold())
    return Board(number, columns, coaches, from_sheet=sheet is not None and bool(sheet.games))
