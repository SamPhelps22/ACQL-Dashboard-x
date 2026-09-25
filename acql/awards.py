"""Season superlatives - the fun awards from the Dashboard sheet, computed.

Every award returns an Award or None; an award with no meaningful winner is
omitted rather than shown with a blank, which is what the spreadsheet does
today (the Hot Hand cell currently reads "#VALUE!").

Two rules keep the board honest. Ties are broken alphabetically rather than by
whichever player the parser happened to see first, so an award does not jump
between two equal players from one refresh to the next. And an award that
everyone would win - perfect attendance in a pool where nobody has missed a
week - is dropped, because a prize nobody can lose says nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .models import Player, Season

GOOD = "good"
BAD = "bad"

RECENT_WEEKS = 3
SURGE_THRESHOLD = 0.5   # wins per week before a second-half run counts

Key = Callable[[Player], "float | tuple[float, ...]"]


@dataclass(frozen=True)
class Award:
    key: str
    icon: str
    title: str
    winner: str
    value: str
    detail: str
    tone: str = ""      # "good", "bad", or "" - the UI colours the value chip


# ---- shared helpers ---------------------------------------------------
def _money(value: float) -> str:
    """Payouts are usually whole dollars; only show cents when there are some."""
    return f"${value:,.0f}" if float(value).is_integer() else f"${value:,.2f}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _negate(value: float | tuple[float, ...]) -> tuple[float, ...]:
    """Flip a sort key so `sorted` ascending gives the highest first.

    Keys may be tuples (a measure plus a tie-break), and a tuple cannot be
    negated directly, so each element is flipped in turn.
    """
    if isinstance(value, tuple):
        return tuple(-v for v in value)
    return (-value,)


def _with_history(season: Season, minimum: int = 1) -> list[Player]:
    return [p for p in season.players.values() if len(p.weeks_played) >= minimum]


def _top(field: Iterable[Player], key: Key) -> Player | None:
    """Highest scorer, ties alphabetical so the award never flickers."""
    ranked = sorted(field, key=lambda p: (_negate(key(p)), p.display.lower()))
    return ranked[0] if ranked else None


def _bottom(field: Iterable[Player], key: Key) -> Player | None:
    """Lowest scorer, same tie-break."""
    ranked = sorted(field, key=lambda p: (key(p), p.display.lower()))
    return ranked[0] if ranked else None


def _week_averages(season: Season) -> dict[int, float]:
    """Mean score per week across everyone who has one."""
    scores: dict[int, list[int]] = {}
    for p in season.players.values():
        for week, wins in p.weekly_wins.items():
            if wins is not None:
                scores.setdefault(week, []).append(wins)
    return {w: sum(v) / len(v) for w, v in scores.items()}


def _streak(player: Player, averages: dict[int, float], *, above: bool) -> int:
    """Weeks in a row, counting back from the latest, on one side of the average."""
    run = 0
    for week in reversed(player.weeks_played):
        wins, average = player.weekly_wins.get(week), averages.get(week)
        if wins is None or average is None:
            break
        if (wins > average) if above else (wins < average):
            run += 1
        else:
            break
    return run


def _cashed_weeks(player: Player) -> dict[int, float]:
    """Only the weeks this player was actually paid something."""
    return {w: v for w, v in player.weekly_winnings.items() if v and v > 0}


def _rank_count(player: Player, position: int) -> int:
    return sum(1 for r in player.weekly_rank.values() if r == position)


# ---- the money ---------------------------------------------------------
def biggest_payday(season: Season) -> Award | None:
    """The largest single-week payout anyone has collected."""
    payouts = [
        (amount, week, p)
        for p in season.players.values()
        for week, amount in _cashed_weeks(p).items()
    ]
    if not payouts:
        return None
    # Sorted on the key alone - Player is not orderable, so it never compares.
    amount, week, player = min(
        payouts, key=lambda c: (-c[0], c[2].display.lower(), c[1])
    )
    return Award(
        "payday", "\N{MONEY BAG}", "Biggest Payday", player.display,
        _money(amount), f"Collected in week {week}", GOOD,
    )


def most_weeks_cashed(season: Season) -> Award | None:
    """Turns up in the money most often, whatever the amounts."""
    player = _top(season.players.values(), lambda p: len(_cashed_weeks(p)))
    if player is None:
        return None
    weeks = _cashed_weeks(player)
    if len(weeks) < 2:
        return None
    return Award(
        "cashed", "\N{BANKNOTE WITH DOLLAR SIGN}", "Most Weeks Cashed", player.display,
        str(len(weeks)), f"{_money(sum(weeks.values()))} won in all", GOOD,
    )


def still_waiting(season: Season) -> Award | None:
    """Longest run without a payout, while others are collecting."""
    if not any(_cashed_weeks(p) for p in season.players.values()):
        return None
    dry = [
        p for p in _with_history(season, 3)
        if not _cashed_weeks(p) and p.total_winnings <= 0
    ]
    player = _top(dry, lambda p: len(p.weeks_played))
    if player is None:
        return None
    return Award(
        "waiting", "\N{HOURGLASS WITH FLOWING SAND}", "Still Waiting", player.display,
        f"{len(player.weeks_played)} weeks", "Yet to win a single week", BAD,
    )


# ---- form and results ---------------------------------------------------
def best_week_award(season: Season) -> Award | None:
    """Highest single-week score anyone has posted."""
    player = _top(_with_history(season, 1), lambda p: p.best_week)
    if player is None or not player.best_week:
        return None
    week = min(w for w, v in player.weekly_wins.items() if v == player.best_week)
    shared = sum(1 for p in season.players.values() if p.best_week == player.best_week) - 1
    detail = f"Set in week {week}"
    if shared:
        detail += f", matched by {_plural(shared, 'other')}"
    return Award(
        "best", "\N{GLOWING STAR}", "Best Week", player.display,
        str(player.best_week), detail, GOOD,
    )


def hot_hand(season: Season) -> Award | None:
    """Best recent form over the last few weeks played."""
    field = _with_history(season, 2)
    player = _top(field, lambda p: (p.trend(RECENT_WEEKS), float(p.season_wins)))
    if player is None:
        return None
    weeks = player.weeks_played[-RECENT_WEEKS:]
    span = f"week {weeks[0]}" if len(weeks) == 1 else f"weeks {weeks[0]}-{weeks[-1]}"
    return Award(
        "hot", "\N{FIRE}", "Hot Hand", player.display,
        f"{player.trend(RECENT_WEEKS):.1f}/wk", f"Averaged over {span}", GOOD,
    )


def beating_the_pool(season: Season) -> Award | None:
    """Longest current run of weeks above the pool average."""
    averages = _week_averages(season)
    player = _top(_with_history(season, 2), lambda p: _streak(p, averages, above=True))
    if player is None:
        return None
    run = _streak(player, averages, above=True)
    if run < 2:
        return None
    return Award(
        "streak", "\N{HIGH VOLTAGE SIGN}", "On a Run", player.display,
        f"{run} weeks", "Above the pool average, and counting", GOOD,
    )


def ice_cold(season: Season) -> Award | None:
    """The same run, the wrong way round."""
    averages = _week_averages(season)
    player = _top(_with_history(season, 2), lambda p: _streak(p, averages, above=False))
    if player is None:
        return None
    run = _streak(player, averages, above=False)
    if run < 2:
        return None
    return Award(
        "cold", "\N{SNOWFLAKE}", "Ice Cold", player.display,
        f"{run} weeks", "Below the pool average, and counting", BAD,
    )


def week_winner(season: Season) -> Award | None:
    """Most weeks finished top of the pile."""
    player = _top(season.players.values(), lambda p: _rank_count(p, 1))
    if player is None:
        return None
    wins = _rank_count(player, 1)
    if not wins:
        return None
    return Award(
        "weekwinner", "\N{CROWN}", "Most Weeks Won", player.display,
        str(wins), f"Finished first in {_plural(wins, 'week')}", GOOD,
    )


def bridesmaid(season: Season) -> Award | None:
    """Second place over and over, without ever taking a week."""
    field = [p for p in season.players.values() if not _rank_count(p, 1)]
    player = _top(field, lambda p: _rank_count(p, 2))
    if player is None:
        return None
    seconds = _rank_count(player, 2)
    if seconds < 2:
        return None
    return Award(
        "bridesmaid", "\N{SECOND PLACE MEDAL}", "Always the Bridesmaid", player.display,
        str(seconds), "Second-place finishes, no wins", BAD,
    )


def late_bloomer(season: Season) -> Award | None:
    """Biggest step up between the first half of a player's weeks and the second."""
    runs = []
    for p in _with_history(season, 4):
        weeks = p.weeks_played
        half = len(weeks) // 2
        early = [p.weekly_wins[w] for w in weeks[:half]]
        late = [p.weekly_wins[w] for w in weeks[half:]]
        if not early or not late:
            continue
        first = sum(early) / len(early)
        second = sum(late) / len(late)
        runs.append((second - first, p.display.lower(), p, first, second))
    if not runs:
        return None
    gain, _, player, first, second = min(runs, key=lambda r: (-r[0], r[1]))
    if gain < SURGE_THRESHOLD:
        return None
    return Award(
        "bloomer", "\N{SEEDLING}", "Late Bloomer", player.display,
        f"+{gain:.1f}/wk", f"Up from {first:.1f} to {second:.1f} a week", GOOD,
    )


def biggest_choke(season: Season) -> Award | None:
    """Largest single-week drop from a player's own average."""
    drops = [
        (p.average_wins - wins, week, p)
        for p in _with_history(season, 2)
        for week, wins in p.weekly_wins.items()
        if wins is not None
    ]
    if not drops:
        return None
    drop, week, player = min(drops, key=lambda c: (-c[0], c[2].display.lower(), c[1]))
    if drop <= 0:
        return None
    return Award(
        "choke", "\N{SKULL}", "Biggest Choke", player.display,
        f"-{drop:.1f}",
        f"Week {week}: {player.weekly_wins[week]} wins against a "
        f"{player.average_wins:.1f} average",
        BAD,
    )


# ---- standings ---------------------------------------------------------
def biggest_climber(season: Season) -> Award | None:
    """Most positions gained since the previous snapshot."""
    movers = [p for p in season.players.values() if p.rank_movement is not None]
    player = _top(movers, lambda p: float(p.rank_movement or 0))
    if player is None or (player.rank_movement or 0) <= 0:
        return None
    return Award(
        "climber", "\N{CHART WITH UPWARDS TREND}", "Biggest Climber", player.display,
        f"+{player.rank_movement}", f"Up from {player.prev_pos} to {player.pos}", GOOD,
    )


def free_fall(season: Season) -> Award | None:
    """The steepest slide down the table."""
    movers = [p for p in season.players.values() if p.rank_movement is not None]
    player = _bottom(movers, lambda p: float(p.rank_movement or 0))
    if player is None or (player.rank_movement or 0) >= 0:
        return None
    return Award(
        "freefall", "\N{CHART WITH DOWNWARDS TREND}", "Free Fall", player.display,
        str(player.rank_movement), f"Down from {player.prev_pos} to {player.pos}", BAD,
    )


def walking_dead(season: Season) -> Award | None:
    """Furthest back in the standings."""
    order = season.ordered_players()
    if len(order) < 2:
        return None
    player = order[-1]
    return Award(
        "dead", "\N{ZOMBIE}", "Walking Dead", player.display,
        f"{player.games_behind:.0f} back",
        f"{player.wins}-{player.losses} on the season", BAD,
    )


# ---- temperament -------------------------------------------------------
def most_consistent(season: Season) -> Award | None:
    """Lowest week-to-week spread, among players with a real record."""
    player = _bottom(_with_history(season, 3), lambda p: p.consistency)
    if player is None:
        return None
    return Award(
        "consistent", "\N{DIRECT HIT}", "Most Consistent", player.display,
        f"+/-{player.consistency:.2f}",
        f"Averaging {player.average_wins:.1f} wins a week", GOOD,
    )


def boom_or_bust(season: Season) -> Award | None:
    """The opposite: the widest swings."""
    player = _top(_with_history(season, 3), lambda p: p.consistency)
    if player is None or player.consistency <= 0:
        return None
    return Award(
        "boom", "\N{ROCKET}", "Boom or Bust", player.display,
        f"+/-{player.consistency:.2f}",
        f"Between {player.worst_week} and {player.best_week} wins", "",
    )


def mr_reliable(season: Season) -> Award | None:
    """Highest floor - the best worst-week in the pool."""
    player = _top(
        _with_history(season, 2), lambda p: (float(p.worst_week), p.average_wins)
    )
    if player is None:
        return None
    return Award(
        "reliable", "\N{ROBOT FACE}", "Mr. Reliable", player.display,
        str(player.worst_week), "Has never scored below this in a week", GOOD,
    )


def mr_average(season: Season) -> Award | None:
    """The player the whole pool is bunched around."""
    field = _with_history(season, 3)
    if len(field) < 4:
        return None
    pool = sum(p.average_wins for p in field) / len(field)
    player = _bottom(field, lambda p: abs(p.average_wins - pool))
    if player is None:
        return None
    return Award(
        "average", "\N{LEFT-POINTING MAGNIFYING GLASS}", "Mr. Average", player.display,
        f"{player.average_wins:.1f}/wk",
        f"The pool averages {pool:.1f} - nobody is closer", "",
    )


# ---- the side games ----------------------------------------------------
def big_loser_king(season: Season) -> Award | None:
    """Best at picking the week's big loser."""
    player = _top(season.players.values(), lambda p: float(p.big_loser_wins))
    if player is None or not player.big_loser_wins:
        return None
    return Award(
        "bigloser", "\N{DOWN-POINTING RED TRIANGLE}", "Big-Loser Specialist",
        player.display, str(player.big_loser_wins),
        f"{player.big_loser_points:g} point"
        f"{'' if player.big_loser_points == 1 else 's'} from the side game", GOOD,
    )


def last_one_standing(season: Season) -> Award | None:
    """The suicide pool, once it has come down to one."""
    alive = [p for p in season.players.values() if p.suicide_alive]
    if len(alive) != 1 or len(season.players) < 2:
        return None
    player = alive[0]
    return Award(
        "suicide", "\N{SHIELD}", "Last One Standing", player.display,
        "Alive", f"The only one left of {_plural(len(season.players), 'entrant')}", GOOD,
    )


def never_missed(season: Season) -> Award | None:
    """Perfect attendance - dropped when nobody has missed a week."""
    weeks = season.final_weeks()
    if len(weeks) < 3:
        return None
    full = [p for p in season.players.values() if set(weeks) <= set(p.weeks_played)]
    # A prize the whole pool wins is not a prize.
    if not full or len(full) == len(season.players):
        return None
    player = _top(full, lambda p: float(p.season_wins))
    if player is None:
        return None
    return Award(
        "ironman", "\N{ANCHOR}", "Never Missed a Week", player.display,
        f"{len(weeks)}/{len(weeks)}",
        f"One of {_plural(len(full), 'player')} with a full card", GOOD,
    )


# ---- what the raw pick sheets know ------------------------------------
#: Sheets a coach has to appear on before their habits are worth naming. One
#: week of unusual picks is a mood; three is a way of playing.
CHALK_WEEKS = 3


def _chalk_shares(season: Season) -> dict[str, tuple[float, int]]:
    """Each coach's average agreement with the pool, and over how many weeks.

    Only the raw pick sheets carry this - the workbook records which picks
    were right, never which were popular - so it is empty until a sheet has
    been loaded, and the two awards below simply do not appear.
    """
    from . import picks

    gathered: dict[str, list[float]] = {}
    for sheet in picks.load_all().values():
        for coach, share in picks.chalk(sheet).items():
            gathered.setdefault(" ".join(coach.split()).casefold(), []).append(share)
    known = {
        " ".join(p.display.split()).casefold(): p.display
        for p in season.players.values()
    }
    return {
        known[key]: (sum(values) / len(values), len(values))
        for key, values in gathered.items()
        if key in known and len(values) >= CHALK_WEEKS
    }


def the_contrarian(season: Season) -> Award | None:
    """Furthest from the crowd. The only way anyone finishes a week clear."""
    shares = _chalk_shares(season)
    if len(shares) < 3:
        return None
    name, (share, weeks) = min(shares.items(), key=lambda item: item[1][0])
    pool = sum(s for s, _ in shares.values()) / len(shares)
    return Award(
        key="contrarian",
        icon="\N{BLACK CHESS KNIGHT}",
        title="The Contrarian",
        winner=name,
        value=f"{share:.0%}",
        detail=(
            f"takes the popular side {share:.0%} of the time against the pool's "
            f"{pool:.0%}, over {_plural(weeks, 'sheet')}. Being right where "
            f"everyone else is right pays nothing - this is the only way to "
            f"finish a week clear of the field."
        ),
        tone="good",
    )


def the_sheep(season: Season) -> Award | None:
    """Closest to the crowd. Not a criticism - it wins games, just not weeks."""
    shares = _chalk_shares(season)
    if len(shares) < 3:
        return None
    name, (share, weeks) = max(shares.items(), key=lambda item: item[1][0])
    pool = sum(s for s, _ in shares.values()) / len(shares)
    return Award(
        key="sheep",
        icon="\N{SHEEP}",
        title="With The Crowd",
        winner=name,
        value=f"{share:.0%}",
        detail=(
            f"takes the popular side {share:.0%} of the time against the pool's "
            f"{pool:.0%}, over {_plural(weeks, 'sheet')}. The crowd is usually "
            f"right, so this wins games - it just never wins a week, because "
            f"everybody else has the same card."
        ),
    )


ALL_AWARDS = (
    best_week_award,
    hot_hand,
    biggest_payday,
    week_winner,
    biggest_climber,
    beating_the_pool,
    most_weeks_cashed,
    most_consistent,
    late_bloomer,
    mr_reliable,
    big_loser_king,
    last_one_standing,
    never_missed,
    mr_average,
    boom_or_bust,
    bridesmaid,
    ice_cold,
    biggest_choke,
    free_fall,
    still_waiting,
    walking_dead,
    the_contrarian,
    the_sheep,
)


def compute(season: Season, limit: int | None = None) -> list[Award]:
    """Every award that has a genuine winner, in display order."""
    out: list[Award] = []
    for fn in ALL_AWARDS:
        try:
            award = fn(season)
        except (ValueError, ZeroDivisionError, KeyError, TypeError, AttributeError):
            # One bad award never costs the board the rest of them.
            award = None
        if award is not None:
            out.append(award)
        if limit is not None and len(out) >= limit:
            break
    return out