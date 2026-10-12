"""Market power rankings: how good the betting market thinks each team is.

A team's record says what has happened to it; the line says what the market
expects next, and the two part company all the time - a 4-0 team that has
been a slim favourite every week, a 1-3 team still favoured on the road.
Every line this season is one statement: this home team is that many points
better than that visitor, here. Solving all of them together gives each
team a rating in points against an average team (survivor.ratings - the
same sums the suicide helper plans later weeks with).

Set beside the record and the scoring margin, the gap is the interesting
part: a team the market rates well above its results is one the pool will
underrate, and the other way round.

No Qt here: the Teams page lays it out.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import evidence, predictions, results, survivor
from .models import Season
from .predictions import display_team


@dataclass(frozen=True)
class TeamRank:
    code: str
    team: str
    rating: float            # points better than an average team, by the market
    priced: int              # games the rating rests on
    rank: int                # by the market
    record: str              # "3-1"
    games: int
    margin: float            # points a game, scored minus allowed
    results_rank: int        # by that margin
    next: str = ""           # "vs Denver, by 3.5" / "at Dallas, +2"
    own: float | None = None     # the dashboard's own rating, from results alone (teamstrength.py)

    @property
    def gap(self) -> int:
        """Places the market has the team above (+) or below (-) its results."""
        return self.results_rank - self.rank


@dataclass(frozen=True)
class Rankings:
    teams: list[TeamRank]
    games: int               # lines the ratings were solved from
    weeks: tuple[int, ...]
    through: int             # results counted through this week

    def team(self, code: str) -> TeamRank | None:
        return next((t for t in self.teams if t.code == code), None)


def _next_games(season: Season, week: int) -> dict[str, str]:
    """Team code -> its game in `week`, with the market's number when there is one."""
    found = season.weeks.get(week)
    if found is None:
        return {}
    games = sorted(found.games, key=lambda g: g.index)
    from . import pricing
    margins = pricing.market_margins(week, games)
    out = {}
    for game in games:
        home, away = predictions.team_code(game.home), predictions.team_code(game.away)
        margin = margins.get(game.index)

        def line(team_margin):
            if team_margin is None:
                return ""
            if abs(team_margin) < 0.25:
                return ", pick'em"
            return f", by {abs(team_margin):g}" if team_margin > 0 else f", +{abs(team_margin):g}"

        if home:
            out[home] = f"vs {display_team(game.away)}{line(margin)}"
        if away:
            out[away] = f"at {display_team(game.home)}{line(None if margin is None else -margin)}"
    return out


def rankings(season: Season, upto: int | None = None) -> Rankings:
    """Every team by the market's rating, beside what it has actually done."""
    from . import analytics
    ahead = analytics.upcoming_week(season)
    upto = ahead if upto is None else upto
    lines = survivor._lines_so_far(upto)
    rated = survivor.ratings(lines)
    if not rated:
        return Rankings([], 0, (), 0)
    priced: dict[str, int] = {}
    for home, away, _ in lines:
        priced[home] = priced.get(home, 0) + 1
        priced[away] = priced.get(away, 0) + 1
    year = results.season_year(season)
    form = evidence.season_form(year, upto + 1)
    through = max((w for w in range(1, upto + 1) if results.over(year, w)), default=0)
    by_market = sorted(rated, key=lambda c: (-rated[c], c))
    by_results = sorted(rated, key=lambda c: (-(form[c].margin if c in form else -99), c))
    coming = _next_games(season, ahead)
    weeks = tuple(w for w in range(1, upto + 1) if predictions.load(w)[0])
    try:
        from . import teamstrength
        own = dict(teamstrength.table(season, ahead))
    except Exception:  # noqa: BLE001 - the market's ratings stand without the dashboard's own
        own = {}
    teams = []
    for code in by_market:
        played = form.get(code)
        teams.append(TeamRank(
            code=code, team=display_team(code), rating=rated[code], priced=priced.get(code, 0),
            rank=by_market.index(code) + 1,
            record=played.record if played else "0-0", games=played.games if played else 0,
            margin=played.margin if played else 0.0,
            results_rank=by_results.index(code) + 1,
            next=coming.get(code, ""), own=own.get(code),
        ))
    return Rankings(teams, len(lines), weeks, through)
