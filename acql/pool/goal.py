"""What you're playing for this season, and the card it suggests (idea #90, with a little of #55).

The picks page offers three cards (briefing.STYLE_NAMES). Which one is right
depends on what you want from the season, which the dashboard has never
been told. This keeps that one choice and turns it into a suggestion with
its reason. It never changes the card by itself: the page shows the
suggestion and a button, and the card you hand in stays your choice.

Unset by default, so nothing changes until a goal is chosen. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import briefing

GOALS = {"": "Not set", "money": "Weekly money", "title": "The season title", "top3": "A top-3 finish",
         "loser": "Big Loser points"}
#: Regular-season weeks.
SEASON_WEEKS = 18
#: Chasing the title from this far back (games behind per week left) calls for more risk.
CHASE = 0.6
#: ...but only once the end is this close; earlier, steady points still close the gap.
CHASE_WEEKS = 6
#: With the season's own title (or top-3) odds known (#55): below this, and with this
#: few weeks left, the card that takes more risk is the one that can still get there.
LONG_ODDS, LONG_WEEKS = 0.05, 8


@dataclass(frozen=True)
class Suggestion:
    goal: str
    style: str
    reason: str


def suggest(goal: str, games_behind: float | None, weeks_left: int, *,
            title: float | None = None, top3: float | None = None) -> Suggestion | None:
    """The card for a goal, given where you stand - and, when known, your title and
    top-3 odds from the season simulation (analytics.race). None when no goal is set."""
    if goal not in GOALS or not goal:
        return None
    if goal == "money":
        return Suggestion(goal, briefing.STYLE_MONEY,
                          "Weekly money is won by finishing first in a week; this card takes the likelier side "
                          "of every game and Big Losers the pool isn't on.")
    if goal == "loser":
        return Suggestion(goal, briefing.STYLE_MONEY,
                          "This card chooses Big Losers for what they pay, not just how likely they are.")
    if goal == "top3" and top3 is not None and top3 < LONG_ODDS and 0 < weeks_left <= LONG_WEEKS:
        return Suggestion(goal, briefing.STYLE_WIN,
                          f"Top-3 odds {top3:.0%} with {weeks_left} weeks left: steady points won't get there, so "
                          "the card that turns a game or two against the pool. It costs points on average.")
    if goal == "top3":
        return Suggestion(goal, briefing.STYLE_STRAIGHT,
                          "A top-3 finish is about steady points: the likelier side of every game and the three "
                          "likeliest Big Losers.")
    behind = games_behind or 0.0
    odds = f"Title odds {title:.0%}, " if title is not None else ""
    if title is not None and title < LONG_ODDS and 0 < weeks_left <= LONG_WEEKS:
        return Suggestion(goal, briefing.STYLE_WIN,
                          f"{odds}{weeks_left} week{'s' if weeks_left != 1 else ''} left: the title needs more than "
                          "steady points now, so the card that turns a game or two against the pool. It costs "
                          "points on average.")
    if weeks_left and weeks_left <= CHASE_WEEKS and behind >= CHASE * weeks_left:
        return Suggestion(goal, briefing.STYLE_WIN,
                          f"{behind:g} games back with {weeks_left} week{'s' if weeks_left != 1 else ''} left: "
                          "steady points won't close that, so the card that turns a game or two against the pool "
                          "is the one that can. It costs points on average.")
    return Suggestion(goal, briefing.STYLE_STRAIGHT,
                      f"{odds}{behind:g} games back with {weeks_left} weeks left: the title is won on points, so the "
                      "card with the most expected points.")


def odds(season) -> tuple[float | None, float | None]:
    """(your title odds, your top-3 odds) from the season simulation, or Nones."""
    from .. import analytics
    from . import me
    key = me.key(season)
    try:
        found = analytics.race(season)
    except Exception:  # noqa: BLE001
        return None, None
    mine = next((o for o in found.outlooks if getattr(o.player, "key", None) == key), None)
    return (mine.title_odds, mine.top3_odds) if mine is not None else (None, None)


def standing(season) -> tuple[float | None, int]:
    """(your games behind the leader, regular-season weeks left)."""
    from . import me
    key = me.key(season)
    player = season.players.get(key) if key else None
    done = max((n for n, w in season.weeks.items() if w.games and all(g.played for g in w.games)), default=0)
    return (player.games_behind if player is not None else None), max(0, SEASON_WEEKS - done)
