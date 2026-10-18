"""Deadeye as a ghost coach: its card scored each finished week the way
everyone's is, so the pages can show where it would stand - never counted,
never placed, never paid.

Its picks are the card This Week recommends, kept as it stood when the
pool's cards were due (cards.model); weeks from before that was kept are
rebuilt from the stored lines, and say so. Its Big Losers are the three on
that kept card - the three likeliest by the same lines, for a card kept
before they were - scored by the pool's rule: a point when the team loses by
15 or more. The money is the pool's rule too, had it played:
the best card takes a dollar a game from every card behind it, level cards
split it.

Nothing here touches the website: Deadeye stays off it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .. import analytics
from ..pool import cards
from ..feeds import results
from ..models import Season, Week, same_team
from ..version import MODEL_NAME

#: How the ghost is named on the pages.
LABEL = f"{MODEL_NAME} (ghost)"
BLOWOUT = analytics.BIG_LOSER_MARGIN + 1
BIG_LOSERS = 3


@dataclass(frozen=True)
class GhostWeek:
    week: int
    regular: int                # picks credited
    losers: int                 # Big Loser points
    losers_known: bool          # every one of its Big Loser games had a final score to go by
    games: int                  # games on the week's slate
    place: int                  # where its total would have finished (1 = the week's best)
    tied: int                   # coaches level with it
    entrants: int
    best: int                   # the field's best total
    payout: float               # what it would have collected (0 unless it had the best card)
    money: float                # collected, or minus what it would have paid
    rebuilt: bool               # its card was made after the fact, from the stored lines

    @property
    def total(self) -> int:
        return self.regular + self.losers


@dataclass(frozen=True)
class GhostSeason:
    weeks: list[GhostWeek]
    scored_weeks: int           # weeks the pool has scored, card or not
    field_chances: int = 0      # what the pool's sheet has every coach's record out of (0: it doesn't say)

    @property
    def complete(self) -> bool:
        """A card for every scored week: only then is its season comparable."""
        return len(self.weeks) == self.scored_weeks

    @property
    def wins(self) -> int:
        return sum(w.total for w in self.weeks)

    @property
    def chances(self) -> int:
        """What its record is out of. Its wins count Big Loser points, as a
        coach's do, so its Big Loser picks are chances too: the pool's own
        count when it has a card for every week the coaches' records cover,
        else its own weeks' games and Big Losers."""
        if self.complete and self.field_chances and self.field_chances >= self.wins:
            return self.field_chances
        return sum(w.games + BIG_LOSERS for w in self.weeks)

    @property
    def losses(self) -> int:
        return max(0, self.chances - self.wins)

    @property
    def pct(self) -> float:
        return self.wins / self.chances if self.chances else 0.0

    @property
    def won(self) -> float:
        return round(sum(w.payout for w in self.weeks), 2)

    @property
    def paid(self) -> float:
        return round(sum(-w.money for w in self.weeks if w.money < 0), 2)

    @property
    def net(self) -> float:
        return round(sum(w.money for w in self.weeks), 2)

    @property
    def best_week(self) -> int:
        return max((w.total for w in self.weeks), default=0)

    @property
    def average(self) -> float:
        return self.wins / len(self.weeks) if self.weeks else 0.0

    @property
    def latest(self) -> GhostWeek | None:
        return max(self.weeks, key=lambda w: w.week) if self.weeks else None

    def last(self, n: int) -> int:
        return sum(w.total for w in sorted(self.weeks, key=lambda w: w.week)[-n:])

    def place_among(self, wins: list[int]) -> int:
        """Where its season would stand among the coaches' win totals."""
        return 1 + sum(1 for v in wins if v > self.wins)


def _margins(season: Season, number: int, week: Week) -> dict[int, int]:
    """Each finished game's home margin (the slate's home side), from the
    score kept with the game or the scoreboard's kept finals."""
    out: dict[int, int] = {}
    kept = []
    try:
        kept = [s for s in results.load(results.season_year(season), number) if s.final]
    except Exception:  # noqa: BLE001 - without them, the games' own scores
        kept = []
    for game in week.games:
        if game.home_points is not None and game.away_points is not None:
            out[game.index] = int(game.home_points) - int(game.away_points)
            continue
        for s in kept:
            if s.home_points is None or s.away_points is None:
                continue
            if same_team(s.home, game.home) and same_team(s.away, game.away):
                out[game.index] = int(s.home_points) - int(s.away_points)
            elif same_team(s.home, game.away) and same_team(s.away, game.home):
                out[game.index] = int(s.away_points) - int(s.home_points)
    return out


def _losers(season: Season, number: int, week: Week, snap=None) -> list[str]:
    """Its three Big Losers, as team codes: the ones kept with its card, or -
    for a card kept before they were - the likeliest by the week's lines."""
    from . import pricing
    from .predictions import team_code
    kept = [code for code in (getattr(snap, "losers", None) or []) if code]
    if kept:
        return kept[:BIG_LOSERS]
    try:
        prices = pricing.price_week(season, number, sorted(week.games, key=lambda g: g.index))
        found = [team_code(b.team) for b in pricing.big_loser_candidates(prices, include_played=True)]
        return [code for code in found if code][:BIG_LOSERS]
    except Exception:  # noqa: BLE001 - its card without Big Losers
        return []


def week_score(season: Season, number: int, *, rebuild: bool = True) -> GhostWeek | None:
    """Its week, scored - None when the week isn't scored or it has no card."""
    week = season.weeks.get(number)
    if week is None or not week.scored:
        return None
    snap = cards.model(number)
    if snap is None and rebuild:
        snap = cards._rebuild(season, number)
    if snap is None:
        return None
    snap = cards.aligned(snap, cards._slate(week.games))
    regular, graded = cards._hits(snap.plain or snap.take, week)
    if not graded:
        return None
    margins = _margins(season, number, week)
    losers, known = 0, True
    from .predictions import team_code
    for team in _losers(season, number, week, snap):
        game = next((g for g in week.games if team in (team_code(g.home), team_code(g.away))), None)
        if game is None:
            continue
        margin = margins.get(game.index)
        if margin is None:
            known = False
            continue
        lost_by = -margin if team == team_code(game.home) else margin
        losers += lost_by >= BLOWOUT
    total = regular + losers
    field = [int(line.total_wins or 0) for line in week.lines.values()]
    best = max(field, default=0)
    top = max(best, total)
    level = sum(1 for v in field if v == top) + (total == top)
    pot = sum(top - v for v in field) + (top - total)
    payout = round(pot / level, 2) if total == top and pot else 0.0
    return GhostWeek(
        week=number, regular=regular, losers=losers, losers_known=known,
        games=len(week.games), place=1 + sum(1 for v in field if v > total),
        tied=sum(1 for v in field if v == total), entrants=len(field), best=best,
        payout=payout, money=payout if total == top else float(total - top),
        rebuilt=snap.rebuilt,
    )


def field_chances(season: Season) -> int:
    """What the pool's sheet has a coach's record out of: wins and losses
    together, which it keeps the same for every coach (the commonest, should
    they differ; 0 when it gives no records)."""
    totals = Counter(int(round(p.wins + p.losses)) for p in season.players.values() if p.wins and p.losses)
    return totals.most_common(1)[0][0] if totals else 0


def season_record(season: Season, *, rebuild: bool = True) -> GhostSeason | None:
    """Its whole season so far; None before any week with a card is scored.
    Worked out once per loaded season - three pages ask."""
    cached = getattr(season, "_ghost_season", None)
    if cached is not None and cached[0] == rebuild:
        return cached[1]
    weeks = []
    # The same weeks the coaches' season totals cover: a week still in progress
    # (stats.xls not yet through it) stays out, as it does for them.
    final = set(season.final_weeks()) if hasattr(season, "final_weeks") else None
    scored = [n for n in sorted(season.weeks) if season.weeks[n].scored and (final is None or n in final)]
    for number in scored:
        found = week_score(season, number, rebuild=rebuild)
        if found is not None:
            weeks.append(found)
    out = GhostSeason(weeks, len(scored), field_chances(season)) if weeks else None
    try:
        season._ghost_season = (rebuild, out)
    except Exception:  # noqa: BLE001 - a season that takes no attributes: worked out again
        pass
    return out


def tooltip(record: GhostSeason) -> str:
    """What the ghost row is, for a hover."""
    rebuilt = [w.week for w in record.weeks if w.rebuilt]
    missing = record.scored_weeks - len(record.weeks)
    lines = [
        f"{MODEL_NAME}, the dashboard's own card, scored like a coach's: shown for "
        "comparison, never placed or paid.",
        "Its picks and its three Big Losers: the card Deadeye Picks recommended when the "
        "pool's cards were due.",
    ]
    lines.append(f"Its record is out of {record.chances}: every game and every Big Loser pick, "
                 "the same as a coach's.")
    if rebuilt:
        lines.append(f"Rebuilt afterwards from the stored lines: week{'s' if len(rebuilt) > 1 else ''} "
                     + ", ".join(str(w) for w in rebuilt) + ".")
    if missing:
        lines.append(f"No card for {missing} scored week{'s' if missing != 1 else ''}, "
                     "so its totals aren't comparable with the coaches'.")
    return "\n".join(lines)
