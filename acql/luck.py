"""The luck meter: wins against what the picks deserved.

Every pick had a chance of landing before the game was played - the betting
line says how likely each side was to win, and on a lined game the pool's
rule decides what "landing" means. Add those chances up over a coach's picks
and you get the wins their picks deserved. The difference is luck:

    luck           = wins - expected wins
    pick quality   = expected wins - the pool's average expected wins

A coach on +3 luck won three more games than their picks deserved; a coach
with high pick quality made good picks whatever happened. The two are
different things, and over a season the second is the one that lasts.

Only games with a betting line count, on both sides of the sum, so a week
with half its lines missing still compares like with like.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import analytics
from .models import Game, Season, same_team


def _home_win(margin: float) -> float:
    """Chance the home side wins outright, given the market's home margin."""
    if margin >= 0:
        return analytics.win_chance(margin)
    return 1 - analytics.win_chance(-margin)


def favourite_covers(fav_margin: float, line: float) -> float:
    """Chance the pool's favourite wins by more than the pool's line.

    `fav_margin` is the market's margin for that favourite (negative when
    the market has it as the underdog). A win by exactly the line goes to
    the underdog, so the favourite needs floor(line) + 1.
    """
    need = math.floor(line) + 1
    if fav_margin >= 0:
        return analytics.cover_chance(fav_margin, need)
    # The pool's favourite is the market's underdog: it must win by `need`
    # from behind, which is the other side failing to lose by that much.
    return 1 - analytics.cover_chance(-fav_margin, -need + 1)


def credited_chance(game: Game, home_margin: float, team: str) -> float | None:
    """Chance this team is credited with the game under the pool's rules."""
    line = getattr(game, "line", None)
    favourite = getattr(game, "line_favourite", "")
    if line is not None and favourite:
        fav_home = same_team(favourite, game.home)
        fav_margin = home_margin if fav_home else -home_margin
        p_fav = favourite_covers(fav_margin, line)
        return p_fav if same_team(team, favourite) else 1 - p_fav
    p_home = _home_win(home_margin)
    if same_team(team, game.home):
        return p_home
    if same_team(team, game.away):
        return 1 - p_home
    return None


def picks_of(week) -> dict[str, dict[int, str]]:
    """Every coach's side in every played game, as far as it can be known.

    A graded sheet keeps only the right picks. If everything left on a
    coach's line is right and some games are blank, the blanks were the other
    side; a line with a wrong pick still on it was never cleared, so its
    blanks really are games the coach skipped.
    """
    played = [g for g in week.games if g.played]
    winners = {g.index: g.winner for g in played}
    out: dict[str, dict[int, str]] = {}
    for key, line in week.lines.items():
        shown = {g.index: line.correct_picks.get(g.index) for g in played
                 if line.correct_picks.get(g.index)}
        graded = bool(shown) and len(shown) < len(played) and all(
            same_team(p, winners[i]) for i, p in shown.items()
        )
        card = dict(shown)
        if graded:
            for game in played:
                if game.index not in card:
                    card[game.index] = game.away if same_team(game.winner, game.home) else game.home
        out[key] = card
    return out


def crowd_record(week) -> tuple[int, int]:
    """(games the pool's majority got right, games decided)."""
    cards = picks_of(week)
    right = decided = 0
    for game in (g for g in week.games if g.played):
        sides = [c[game.index] for c in cards.values() if c.get(game.index)]
        if not sides:
            continue
        on_winner = sum(1 for p in sides if same_team(p, game.winner))
        if on_winner * 2 == len(sides):
            continue                    # a dead heat has no majority
        decided += 1
        right += 1 if on_winner * 2 > len(sides) else 0
    return right, decided


@dataclass(frozen=True)
class Luck:
    key: str
    name: str
    picks: int          # priced picks counted
    wins: int
    expected: float
    weeks: int

    @property
    def luck(self) -> float:
        return self.wins - self.expected

    @property
    def per_week(self) -> float:
        return self.luck / self.weeks if self.weeks else 0.0


def _market(week: int, games: list[Game]) -> dict[int, float]:
    from . import pricing                # the stored predictions, read one way
    return pricing.market_margins(week, games)


def week_luck(season: Season, week_number: int, market=None) -> dict[str, tuple[int, float, int]]:
    """Player key -> (wins, expected wins, priced picks) for one week."""
    week = season.weeks.get(week_number)
    if week is None or not week.lines:
        return {}
    played = [g for g in week.games if g.played]
    margins = (market or _market)(week_number, sorted(week.games, key=lambda g: g.index))
    out: dict[str, tuple[int, float, int]] = {}
    cards = picks_of(week)
    for key, card in cards.items():
        wins, expected, counted = 0, 0.0, 0
        for game in played:
            margin = margins.get(game.index)
            pick = card.get(game.index)
            if margin is None or not pick:
                continue
            chance = credited_chance(game, margin, pick)
            if chance is None:
                continue
            counted += 1
            expected += chance
            wins += 1 if same_team(pick, game.winner) else 0
        if counted:
            out[key] = (wins, expected, counted)
    return out


def season_luck(season: Season, market=None, through: int | None = None) -> list[Luck]:
    """Every coach's luck over the season so far, luckiest first."""
    totals: dict[str, list[float]] = {}
    for number in sorted(season.weeks):
        if through is not None and number > through:
            continue
        for key, (wins, expected, counted) in week_luck(season, number, market).items():
            t = totals.setdefault(key, [0, 0.0, 0, 0])
            t[0] += wins
            t[1] += expected
            t[2] += counted
            t[3] += 1
    out = []
    for key, (wins, expected, counted, weeks) in totals.items():
        player = season.players.get(key)
        out.append(Luck(key, player.display if player else key, counted, int(wins), expected, weeks))
    out.sort(key=lambda l: (-l.luck, l.name.casefold()))
    return out


def pool_expected(lines: list[Luck]) -> float:
    """The average coach's expected wins, for measuring pick quality against."""
    return sum(l.expected for l in lines) / len(lines) if lines else 0.0
