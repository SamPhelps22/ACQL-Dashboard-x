"""The Big Loser pool: which three teams to take, and how every coach has picked.

A Big Loser is a point when the team loses by 15 or more. Two things decide
what a pick is worth:

    the blowout     how likely the team is to lose that badly: how often
                    teams with its line have, in every season since 1999
                    (analytics.rout_chance)
    the pool        how many cards already hold the team - a point everyone
                    banks moves nobody

So every candidate gets both, and what holding it gains on the average
card: its chance times the share of the pool that *doesn't* have it. The
three likeliest are the most points; the three that gain most are the ones
that make ground. The long replay (backtest.py) found the second kind worth
about $3.70 a week more under this pool's payout.

And looking back: every coach's Big Loser record - how many came in, how
many their picks deserved, and how far from the crowd they picked.

No Qt here: the Side Pools page lays it out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import moneyplan, picks, pricing, results
from .config import BIG_LOSER_PICKS
from .models import Season
from .predictions import display_team, team_code

#: A Big Loser has to lose by this many or more.
MARGIN = 15


# ---- the week ahead ------------------------------------------------------------------
@dataclass(frozen=True)
class Option:
    code: str
    team: str               # as the pages show it
    opponent: str
    margin: float           # the team's expected margin (negative: an underdog)
    chance: float           # to lose by 15 or more
    held: float             # share of the pool's cards with it

    @property
    def gain(self) -> float:
        """Points holding it gains on the average card."""
        return self.chance * (1 - self.held)


@dataclass(frozen=True)
class Board:
    week: int
    options: list[Option] = field(default_factory=list)     # likeliest first
    counted: bool = False            # the pool's share is off its real sheet, not estimated
    money: tuple[str, ...] = ()      # the money card's three (briefing), when it was planned

    @property
    def likeliest(self) -> list[Option]:
        return self.options[:BIG_LOSER_PICKS]

    @property
    def best_gain(self) -> list[Option]:
        return sorted(self.options, key=lambda o: (-o.gain, -o.chance, o.team))[:BIG_LOSER_PICKS]


def _chances(season: Season, week: int, *, include_played: bool = False) -> list:
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found else []
    if not games:
        return []
    ctx = pricing.context(season, week, games)
    return pricing.big_loser_candidates(pricing.price_week(season, week, games, ctx),
                                        include_played=include_played)


def _held(sheet, chance: dict[str, float]) -> tuple[dict[str, float], bool]:
    """(team -> share of the pool holding it, whether that was counted off the sheet)."""
    if sheet is not None and getattr(sheet, "losers", None):
        cards = [[team_code(t) for t in teams if team_code(t)] for teams in sheet.losers.values()]
        cards = [c for c in cards if c]
        if cards:
            return {code: sum(1 for c in cards if code in c) / len(cards) for code in chance}, True
    return moneyplan.loser_shares(chance), False


def board(season: Season, week: int, brief=None, *, use_sheet: bool = True) -> Board:
    """Every team as a Big Loser for a week: its chance, the pool's share, the gain."""
    candidates = _chances(season, week)
    chance = {team_code(b.team): b.chance for b in candidates if team_code(b.team)}
    if not chance:
        return Board(week)
    sheet = picks.load(week) if use_sheet else None
    held, counted = _held(sheet, chance)
    options = [
        Option(code=team_code(b.team), team=display_team(b.team), opponent=display_team(b.opponent),
               margin=b.margin, chance=b.chance, held=held.get(team_code(b.team), 0.0))
        for b in candidates if team_code(b.team)
    ]
    money = getattr(getattr(getattr(brief, "money", None), "best", None), "losers", ()) or ()
    return Board(week, options, counted, tuple(money))


# ---- looking back ---------------------------------------------------------------------
def blown(season: Season, week: int) -> set[str] | None:
    """The teams that lost by 15 or more in a week, as codes - None until it is known.

    The standings export names them; without it the final scores say so.
    """
    named = (getattr(season, "big_losers_by_week", {}) or {}).get(week)
    if named:
        return {team_code(t) for t in named if team_code(t)}
    scores = results.load(results.season_year(season), week)
    if not scores or not all(s.final or s.called_off for s in scores):
        return None
    out = set()
    for s in scores:
        if not s.final or s.home_points is None or s.away_points is None:
            continue
        if abs(s.home_points - s.away_points) >= MARGIN:
            out.add(s.home if s.home_points < s.away_points else s.away)
    return out


@dataclass
class Record:
    key: str
    name: str
    weeks: int = 0
    picks: int = 0
    hits: int = 0
    expected: float = 0.0        # hits the picks deserved, by their chances
    priced: int = 0              # picks that had a chance to judge them by
    held: float = 0.0            # summed share of the pool on each pick

    @property
    def rate(self) -> float:
        return self.hits / self.picks if self.picks else 0.0

    @property
    def luck(self) -> float:
        """Hits above what the picks deserved (only over picks that could be priced)."""
        return self.hits - self.expected if self.priced == self.picks else float("nan")

    @property
    def crowd(self) -> float:
        """The average share of the pool holding the same team."""
        return self.held / self.picks if self.picks else 0.0


@dataclass(frozen=True)
class Review:
    weeks: list[int]
    coaches: list[Record]            # most hits first
    model: Record                    # the three likeliest each week - Deadeye's picks
    pool: Record                     # every coach added up

    def record_for(self, key: str) -> Record | None:
        return next((r for r in self.coaches if r.key == key), None)


def _plain(name: object) -> str:
    return "".join(c for c in str(name or "").casefold() if c.isalnum())


def review(season: Season) -> Review:
    """Every coach's Big Loser picks over the finished weeks, off the pick sheets."""
    from .version import MODEL_NAME
    by_name = {_plain(p.display): key for key, p in season.players.items()}
    coaches: dict[str, Record] = {}
    model, pool = Record("", MODEL_NAME), Record("", "The pool")
    weeks = []
    other = picks.other_season_weeks()
    for number in sorted(season.weeks):
        lost = blown(season, number)
        sheet = picks.load(number) if number not in other else None
        if lost is None or sheet is None or not getattr(sheet, "losers", None):
            continue
        chance = {team_code(b.team): b.chance for b in _chances(season, number, include_played=True)
                  if team_code(b.team)}
        held, _ = _held(sheet, chance or {c: 0.0 for teams in sheet.losers.values()
                                          for c in map(team_code, teams) if c})
        counted = False
        for coach, teams in sheet.losers.items():
            codes = [team_code(t) for t in teams if team_code(t)]
            key = by_name.get(_plain(coach))
            if not codes or key is None:
                continue
            counted = True
            for record in (coaches.setdefault(key, Record(key, season.players[key].display)), pool):
                record.weeks += 1
                for code in codes:
                    record.picks += 1
                    record.hits += code in lost
                    record.held += held.get(code, 0.0)
                    if code in chance:
                        record.priced += 1
                        record.expected += chance[code]
        if not counted:
            continue
        weeks.append(number)
        if chance:
            model.weeks += 1
            for code in sorted(chance, key=lambda c: -chance[c])[:BIG_LOSER_PICKS]:
                model.picks += 1
                model.priced += 1
                model.hits += code in lost
                model.expected += chance[code]
                model.held += held.get(code, 0.0)
    ranked = sorted(coaches.values(), key=lambda r: (-r.hits, -r.rate, r.name.casefold()))
    return Review(weeks, ranked, model, pool)
