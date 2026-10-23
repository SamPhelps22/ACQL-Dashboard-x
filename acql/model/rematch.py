"""Division rematches (idea #39): how the first meeting went.

Pool coaches anchor on the first meeting between division rivals. For a
rematch this finds the earlier game this season - its line, its score and
who the pool's rule credited - so the scouting report can show it beside
this week's number. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FirstMeeting:
    week: int
    label: str                 # "Green Bay at Detroit"
    line: str                  # "Detroit −3" or ""
    score: str                 # "Green Bay 17, Detroit 24" or ""
    winner: str


def first_meeting(season, number: int, game) -> FirstMeeting | None:
    """The earlier game this season between the same two teams, or None."""
    from ..models import same_team
    from . import pricing, scouting
    from .predictions import display_team
    for w in sorted(n for n in season.weeks if n < number):
        for g in season.weeks[w].games:
            if not ((same_team(g.home, game.home) and same_team(g.away, game.away))
                    or (same_team(g.home, game.away) and same_team(g.away, game.home))):
                continue
            line = ""
            try:
                ctx = pricing.context(season, w, sorted(season.weeks[w].games, key=lambda x: x.index))
                line = scouting._line_text(g, pricing.market_margin(g, ctx.forecasts.get(g.index)))
            except Exception:  # noqa: BLE001 - the meeting without its line
                pass
            away, home = display_team(g.away), display_team(g.home)
            score = ""
            if g.away_points is not None and g.home_points is not None:
                score = f"{away} {g.away_points}, {home} {g.home_points}"
            return FirstMeeting(w, f"{away} at {home}", line, score, display_team(g.winner) if g.winner else "")
    return None
