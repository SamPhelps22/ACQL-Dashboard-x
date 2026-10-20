"""Hot trends: how kinds of side have done against the spread this season.

    Primetime underdogs   the dog in a night game (kickoff 7pm Eastern or later)
    Underdogs             every dog
    Home teams            every home side

A game counts when it is finished and has a spread: the pool's own line when
it has one - the result row already credits that side - and otherwise the
scoreboard's spread, judged from the final score (a push counts for neither).
Kickoffs come from the stored scoreboard, so a game the dashboard never
fetched can't be called primetime and is left out of that trend only.

No Qt here: the pages, the pick sheet and the website only lay it out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..feeds import results
from ..models import Game, Season, same_team
from ..model.predictions import display_team, team_code

#: A kickoff at this hour or later, Eastern time, is primetime.
PRIME_HOUR = 19
#: A trend needs this many games before the website shows it.
MIN_GAMES = 4


def eastern(kickoff: float) -> datetime:
    """The kickoff on the clock in New York (without tz data: the US daylight rule)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(kickoff, ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001 - Windows without tzdata
        utc = datetime.fromtimestamp(kickoff, timezone.utc)
        year = utc.year
        # second Sunday in March to first Sunday in November, 2am local
        march = datetime(year, 3, 8, 7, tzinfo=timezone.utc)
        start = march + timedelta(days=(6 - march.weekday()) % 7)
        november = datetime(year, 11, 1, 6, tzinfo=timezone.utc)
        end = november + timedelta(days=(6 - november.weekday()) % 7)
        return utc + timedelta(hours=-4 if start <= utc < end else -5)


def is_primetime(kickoff: float | None) -> bool:
    return kickoff is not None and eastern(kickoff).hour >= PRIME_HOUR


def night(kickoff: float | None) -> str:
    """"Thursday night", "Sunday night", "Monday night" - or "" for a day game."""
    if not is_primetime(kickoff):
        return ""
    return f"{eastern(kickoff).strftime('%A')} night"


@dataclass(frozen=True)
class Graded:
    """One finished game against its spread."""

    kickoff: float | None
    week: int
    index: int
    home: str
    away: str
    dog: str                # the underdog as the slate writes it
    dog_covered: bool | None  # None: a push


def underdog(game: Game, score: results.Score | None, flipped: bool = False) -> str:
    """The game's underdog: by the pool's line, else the scoreboard's spread."""
    if game.line is not None and game.line_favourite:
        return game.line_underdog
    spread = getattr(score, "home_spread", None)
    if spread is None or spread == 0:
        return ""
    if flipped:
        spread = -spread
    return game.away if spread > 0 else game.home


def _covered(game: Game, score, flipped: bool, dog: str) -> bool | None:
    if game.line is not None and game.line_favourite:
        return same_team(game.winner, dog) if game.played else None
    found = results.points(game, score) if score is not None else None
    if found is None:
        if game.home_points is None or game.away_points is None:
            return None
        found = (game.home_points, game.away_points)
    home_points, away_points = found
    spread = score.home_spread if not flipped else -score.home_spread
    margin = home_points - away_points - spread          # home's result against the number
    if margin == 0:
        return None
    return (margin < 0) == same_team(dog, game.away)


def graded(season: Season, upto: int | None = None) -> list[Graded]:
    """Every finished game with a spread, oldest kickoff first."""
    year = results.season_year(season)
    out = []
    for number in sorted(season.weeks):
        if upto is not None and number > upto:
            continue
        try:
            scores = results.load(year, number)
        except Exception:  # noqa: BLE001 - no stored scoreboard: lines only
            scores = []
        for game in season.weeks[number].games:
            if not game.played:
                continue
            score, flipped = results.find(scores, game.away, game.home)
            dog = underdog(game, score, flipped)
            if not dog:
                continue
            if game.line is None and getattr(score, "home_spread", None) is None:
                continue
            covered = _covered(game, score, flipped, dog)
            out.append(Graded(getattr(score, "kickoff", None), number, game.index,
                              game.home, game.away, dog, covered))
    out.sort(key=lambda g: (g.kickoff or 0, g.week, g.index))
    return out


@dataclass(frozen=True)
class Trend:
    key: str
    label: str              # "Primetime underdogs"
    side: str               # what "covered" means: "dogs", "home teams"
    wins: int
    losses: int
    pushes: int = 0
    streak: int = 0         # the current run: +N covered in a row, -N failed
    recent: tuple[str, ...] = field(default=())  # the latest results, newest last: "Bears +3.5 ✓"

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.pushes}" if self.pushes else "")

    def streak_words(self) -> str:
        if abs(self.streak) < 3:
            return ""
        return (f"covered {self.streak} straight" if self.streak > 0
                else f"failed to cover {-self.streak} straight")

    def headline(self) -> str:
        """"Primetime underdogs 12-0 ATS - covered 12 straight"."""
        streak = self.streak_words()
        return f"{self.label} {self.record()} ATS" + (f" - {streak}" if streak else "")


def _trend(key: str, label: str, side: str, rows: list[tuple[Graded, bool | None, str]]) -> Trend:
    wins = sum(1 for _, ok, _ in rows if ok is True)
    losses = sum(1 for _, ok, _ in rows if ok is False)
    pushes = sum(1 for _, ok, _ in rows if ok is None)
    streak = 0
    for _, ok, _ in reversed(rows):
        if ok is None:
            continue
        if streak == 0:
            streak = 1 if ok else -1
        elif (streak > 0) == ok:
            streak += 1 if ok else -1
        else:
            break
    recent = tuple(f"{who} {'✓' if ok else '✗' if ok is False else 'push'}" for _, ok, who in rows[-6:])
    return Trend(key, label, side, wins, losses, pushes, streak, recent)


def season_trends(season: Season, upto: int | None = None) -> list[Trend]:
    """The season's trends against the spread, the primetime underdogs first."""
    found = graded(season, upto)

    def dog_rows(games):
        return [(g, g.dog_covered, display_team(g.dog)) for g in games]

    home_rows = [(g, None if g.dog_covered is None else g.dog_covered == same_team(g.dog, g.home),
                  display_team(g.home)) for g in found]
    return [
        _trend("primetime_dogs", "Primetime underdogs", "dogs",
               dog_rows([g for g in found if is_primetime(g.kickoff)])),
        _trend("dogs", "Underdogs", "dogs", dog_rows(found)),
        _trend("home", "Home teams", "home teams", home_rows),
    ]


def primetime_record(season: Season, upto: int | None = None) -> Trend:
    return season_trends(season, upto)[0]


def week_tags(season: Season, number: int) -> dict[int, dict]:
    """Game index -> {"night": "Sunday night", "dog": "Chicago"} for each
    primetime game on a week's slate (the dog only when there is a spread)."""
    week = season.weeks.get(number)
    if week is None:
        return {}
    try:
        scores = results.load(results.season_year(season), number)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for game in week.games:
        score, flipped = results.find(scores, game.away, game.home)
        kickoff = getattr(score, "kickoff", None)
        if not is_primetime(kickoff):
            continue
        out[game.index] = {"night": night(kickoff), "dog": display_team(underdog(game, score, flipped)),
                           "dog_code": team_code(underdog(game, score, flipped))}
    return out


def words(trend: Trend) -> str:
    """A line for a card or the pick sheet."""
    if not trend.games:
        return f"No {trend.label.lower()} graded yet this season."
    return f"{trend.headline()} this season ({trend.rate:.0%})."

