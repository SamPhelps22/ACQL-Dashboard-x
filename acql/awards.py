"""Season superlatives - the fun awards from the Dashboard sheet, computed.

Every award returns an Award or None; an award with no meaningful winner is
omitted rather than shown with a blank, which is what the spreadsheet does
today (the Hot Hand cell currently reads "#VALUE!").
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Player, Season


@dataclass
class Award:
    key: str
    icon: str
    title: str
    winner: str
    value: str
    detail: str


def _with_history(season: Season, minimum: int = 1) -> list[Player]:
    return [p for p in season.players.values() if len(p.weeks_played) >= minimum]


def biggest_choke(season: Season) -> Award | None:
    """Largest single-week drop from a player's own average."""
    best: tuple[float, Player, int] | None = None
    for p in _with_history(season, 2):
        avg = p.average_wins
        for week, wins in p.weekly_wins.items():
            drop = avg - wins
            if best is None or drop > best[0]:
                best = (drop, p, week)
    if best is None or best[0] <= 0:
        return None
    drop, player, week = best
    return Award(
        "choke", "\N{SKULL}", "Biggest Choke", player.display,
        f"-{drop:.1f}", f"Week {week}: {player.weekly_wins[week]} wins vs a {player.average_wins:.1f} average",
    )


def biggest_climber(season: Season) -> Award | None:
    """Most positions gained since the previous snapshot."""
    movers = [p for p in season.players.values() if p.rank_movement is not None]
    if not movers:
        return None
    player = max(movers, key=lambda p: p.rank_movement or 0)
    if (player.rank_movement or 0) <= 0:
        return None
    return Award(
        "climber", "\N{CHART WITH UPWARDS TREND}", "Biggest Climber", player.display,
        f"+{player.rank_movement}", f"Moved from {player.prev_pos} to {player.pos}",
    )


def most_consistent(season: Season) -> Award | None:
    """Lowest week-to-week spread, among players with a real record."""
    field = _with_history(season, 3)
    if not field:
        return None
    player = min(field, key=lambda p: p.consistency)
    return Award(
        "consistent", "\N{DIRECT HIT}", "Most Consistent", player.display,
        f"+/-{player.consistency:.2f}", f"Averaging {player.average_wins:.1f} wins a week",
    )


def boom_or_bust(season: Season) -> Award | None:
    """The opposite: the widest swings."""
    field = _with_history(season, 3)
    if not field:
        return None
    player = max(field, key=lambda p: p.consistency)
    if player.consistency <= 0:
        return None
    return Award(
        "boom", "\N{ROCKET}", "Boom or Bust", player.display,
        f"+/-{player.consistency:.2f}", f"Between {player.worst_week} and {player.best_week} wins",
    )


def mr_reliable(season: Season) -> Award | None:
    """Highest floor - the best worst-week in the pool."""
    field = _with_history(season, 2)
    if not field:
        return None
    player = max(field, key=lambda p: (p.worst_week, p.average_wins))
    return Award(
        "reliable", "\N{ROBOT FACE}", "Mr. Reliable", player.display,
        str(player.worst_week), "Has never scored below this in a week",
    )


def walking_dead(season: Season) -> Award | None:
    """Furthest back in the standings."""
    order = season.ordered_players()
    if len(order) < 2:
        return None
    player = order[-1]
    return Award(
        "dead", "\N{ZOMBIE}", "Walking Dead", player.display,
        f"{player.games_behind:.0f} back", f"{player.wins}-{player.losses} on the season",
    )


def hot_hand(season: Season) -> Award | None:
    """Best recent form over the last three weeks played."""
    field = _with_history(season, 1)
    if not field:
        return None
    player = max(field, key=lambda p: (p.trend(3), p.season_wins))
    weeks = player.weeks_played[-3:]
    if not weeks:
        return None
    span = f"week {weeks[0]}" if len(weeks) == 1 else f"weeks {weeks[0]}-{weeks[-1]}"
    return Award(
        "hot", "\N{FIRE}", "Hot Hand", player.display,
        f"{player.trend(3):.1f}/wk", f"Averaged over {span}",
    )


def best_week_award(season: Season) -> Award | None:
    """Highest single-week score anyone has posted."""
    field = _with_history(season, 1)
    if not field:
        return None
    player = max(field, key=lambda p: p.best_week)
    if not player.best_week:
        return None
    week = max(player.weekly_wins, key=lambda w: player.weekly_wins[w])
    return Award(
        "best", "\N{GLOWING STAR}", "Best Week", player.display,
        str(player.best_week), f"Set in week {week}",
    )


ALL_AWARDS = (
    best_week_award,
    hot_hand,
    biggest_climber,
    most_consistent,
    boom_or_bust,
    mr_reliable,
    biggest_choke,
    walking_dead,
)


def compute(season: Season) -> list[Award]:
    """Every award that has a genuine winner, in display order."""
    out = []
    for fn in ALL_AWARDS:
        try:
            award = fn(season)
        except (ValueError, ZeroDivisionError, KeyError):
            award = None
        if award is not None:
            out.append(award)
    return out
