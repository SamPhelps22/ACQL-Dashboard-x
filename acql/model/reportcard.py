"""The model's report card: how accurate it is, and whether to follow it.

Everything here is worked out from what is already stored - the model's card
as it stood before each week's first kickoff (cards.py), the graded sheets,
the stored lines, and the long-run replay (backtest.py) - and nothing here
knows about Qt, so it can be checked against a real season without a screen.

"The model's card" is the one This Week recommends by default: the likeliest
side of every game and the three likeliest Big Losers. It is graded on the
same regular games as every coach, so the comparison is like for like.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .. import analytics
from ..pool import cards
from ..models import Season
from ..version import MODEL_NAME

#: The model's card against this pool's real cards in weeks before this
#: season's were kept - written from the pool's own past sheets.
POOL_WEEKS_FILE = Path(__file__).resolve().parent.parent / "data" / "pool_weeks.json"

#: Weeks before this season's own record is allowed to lead the verdict.
#: Four weeks is 64 games - still mostly luck, but enough that a gap of a few
#: games is no longer just one bad Sunday.
JUDGE_FROM_WEEKS = 4
#: Games ahead over the season before either side is said to be winning.
CLEAR_LEAD = 2
#: Its chances are only called shy or bold past this many spreads of luck,
#: and with at least this many graded picks.
HONESTY_SPREADS = 2.5
HONESTY_PICKS = 64


@dataclass(frozen=True)
class WeekLine:
    week: int
    games: int
    model: int                   # the model's card, regular games right
    mine: int | None             # the coach's regular games right
    pool_average: float
    best: int                    # the best regular score in the pool
    model_place: int             # where the model's card would have finished
    model_tied: int
    my_place: int | None
    entrants: int
    rebuilt: bool


@dataclass(frozen=True)
class LoserLine:
    week: int
    model: tuple[str, ...]       # the model's three likeliest Big Losers
    model_points: int
    mine: int                    # the coach's Big Loser points that week


@dataclass
class Report:
    coach: str
    weeks: list[WeekLine] = field(default_factory=list)
    calls: cards.CallRecord | None = None
    losers: list[LoserLine] = field(default_factory=list)
    expected: float | None = None        # games the model said it would get right
    luck: float = 0.0                    # how far luck alone moves that, one spread
    graded_picks: int = 0
    graded_hits: int = 0
    long_run: dict | None = None
    pool_weeks: list[dict] = field(default_factory=list)
    headline: str = ""
    reasons: list[str] = field(default_factory=list)
    tone: str = ""                       # "good" when the answer is to follow it

    @property
    def honesty(self) -> str:
        """Whether its chances have come in as promised, said only when it can be.

        A few games either way is luck: with 32 picks at about 60%, one
        spread of luck is nearly three games. So nothing is claimed until the
        gap is well past what luck does and there are enough picks to see it.
        """
        if self.expected is None or not self.graded_picks:
            return ""
        gap = self.graded_hits - self.expected
        if self.graded_picks < HONESTY_PICKS or abs(gap) < HONESTY_SPREADS * max(self.luck, 1.0):
            return "about as promised - the gap is within luck"
        return ("better than promised - its chances are shy" if gap > 0
                else "worse than promised - its chances are bold")

    # ---- the numbers the page shows ----------------------------------
    @property
    def games(self) -> int:
        return sum(w.games for w in self.weeks)

    @property
    def model_total(self) -> int:
        return sum(w.model for w in self.weeks)

    @property
    def mine_total(self) -> int | None:
        mine = [w.mine for w in self.weeks if w.mine is not None]
        return sum(mine) if mine else None

    @property
    def model_rate(self) -> float | None:
        return self.model_total / self.games if self.games else None

    @property
    def mine_rate(self) -> float | None:
        games = sum(w.games for w in self.weeks if w.mine is not None)
        return (self.mine_total or 0) / games if games and self.mine_total is not None else None

    @property
    def pool_rate(self) -> float | None:
        return (sum(w.pool_average for w in self.weeks) / self.games) if self.games else None

    @property
    def lead(self) -> int | None:
        """Games the model's card is ahead of the coach, over the weeks both played."""
        both = [w for w in self.weeks if w.mine is not None]
        if not both:
            return None
        return sum(w.model for w in both) - sum(w.mine for w in both)

    @property
    def weeks_best(self) -> int:
        return sum(1 for w in self.weeks if w.model_place == 1)

    @property
    def average_place(self) -> float | None:
        return statistics.fmean(w.model_place for w in self.weeks) if self.weeks else None

    @property
    def my_average_place(self) -> float | None:
        places = [w.my_place for w in self.weeks if w.my_place is not None]
        return statistics.fmean(places) if places else None


def _places(week, score: int) -> tuple[int, int]:
    regular = [line.regular_wins or 0 for line in week.lines.values()]
    return 1 + sum(1 for r in regular if r > score), sum(1 for r in regular if r == score)


def week_lines(season: Season, coach_key: str | None) -> list[WeekLine]:
    out = []
    for sc in cards.history(season, coach_key):
        week = season.weeks[sc.week]
        regular = [line.regular_wins or 0 for line in week.lines.values()]
        mine_place = None
        if sc.mine is not None:
            mine_place = _places(week, sc.mine)[0]
        out.append(WeekLine(
            week=sc.week, games=sc.games, model=sc.model, mine=sc.mine,
            pool_average=statistics.fmean(regular) if regular else 0.0,
            best=sc.best, model_place=_places(week, sc.model)[0],
            model_tied=_places(week, sc.model)[1], my_place=mine_place,
            entrants=sc.entrants, rebuilt=sc.rebuilt,
        ))
    return out


# ---- which teams were blown out -----------------------------------------------
def blowouts(season: Season, week_number: int) -> tuple[set[str], set[str]]:
    """(teams that lost by 15 or more, teams that didn't), as team codes.

    The standings export names the week's big losers outright. Without it, the
    graded workbook still says it for every team someone held: a correct Big
    Loser pick is written over with "1", so the teams a coach held on the pick
    sheet but no longer shows are the ones that came in. Teams nobody held
    stay unknown.
    """
    from ..pool import picks
    from .predictions import team_code
    hit: set[str] = set()
    missed: set[str] = set()
    named = (getattr(season, "big_losers_by_week", {}) or {}).get(week_number)
    if named:
        hit = {team_code(t) for t in named if team_code(t)}
    week = season.weeks.get(week_number)
    sheet = picks.load(week_number)
    if week is None or sheet is None or not getattr(sheet, "losers", None):
        return hit, missed
    by_name = {" ".join(p.display.split()).casefold(): key for key, p in season.players.items()}
    for coach, teams in sheet.losers.items():
        key = by_name.get(" ".join(str(coach).split()).casefold())
        line = week.lines.get(key) if key else None
        if line is None:
            continue
        held = {team_code(t) for t in teams if team_code(t)}
        raw = [str(v or "").strip() for v in (getattr(line, "big_loser_raw", None) or [])]
        still = {team_code(v) for v in raw if team_code(v)}
        marked = sum(1 for v in raw if v == "1")
        if not raw or len(still) + marked != len(held):
            continue                    # the two don't line up; say nothing
        missed |= still
        hit |= held - still
    return hit, missed - hit


def loser_lines(season: Season, coach_key: str | None) -> list[LoserLine]:
    """The model's three likeliest Big Losers against the coach's, where it can tell."""
    from . import pricing, predictions
    out = []
    if not coach_key:
        return out
    for number in sorted(predictions.stored_weeks()):
        week = season.weeks.get(number)
        line = week.lines.get(coach_key) if week is not None else None
        if week is None or line is None or not week.scored:
            continue
        hit, missed = blowouts(season, number)
        if not hit and not missed:
            continue
        prices = pricing.price_week(season, number)
        three = pricing.big_loser_candidates(prices, include_played=True)[:3]
        codes = tuple(predictions.team_code(b.team) for b in three)
        if len(codes) < 3 or not all(c in hit or c in missed for c in codes):
            continue
        out.append(LoserLine(number, codes, sum(1 for c in codes if c in hit),
                             int(line.big_loser_wins or 0)))
    return out


# ---- putting it together ------------------------------------------------------
def build(season: Season, coach_key: str | None, coach: str = "you") -> Report:
    from . import backtest, pricing
    report = Report(coach=coach or "you")
    report.weeks = week_lines(season, coach_key)
    report.calls = cards.call_record(cards.my_calls(season, coach_key)) if coach_key else None
    try:
        report.losers = loser_lines(season, coach_key)
    except Exception:  # noqa: BLE001 - the rest of the card stands without it
        report.losers = []
    entries = pricing.graded_entries(season)
    if entries:
        graded = analytics.grade(entries)
        report.expected = graded.expected
        report.graded_picks = graded.picks
        report.graded_hits = graded.hits
        report.luck = sum(p.chance * (1 - p.chance) for _, p, _ in entries) ** 0.5
    stored = backtest.stored_results()
    report.long_run = stored.raw if stored is not None else None
    report.pool_weeks = pool_weeks()
    _verdict(report)
    return report


def pool_weeks(path: Path = POOL_WEEKS_FILE) -> list[dict]:
    """Real weeks of this pool the model's card has been scored against."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    needed = ("season", "week", "games", "model", "pool_average", "place")
    return [w for w in raw.get("weeks", []) if isinstance(w, dict) and all(k in w for k in needed)]


def _span(weeks: list[dict]) -> str:
    """"2025 weeks 15-17 and 2026 weeks 1-2" - the weeks, season by season."""
    parts = []
    for season in sorted({w["season"] for w in weeks}):
        numbers = sorted(w["week"] for w in weeks if w["season"] == season)
        label = (f"week {numbers[0]}" if len(numbers) == 1 else
                 f"weeks {numbers[0]}-{numbers[-1]}" if numbers == list(range(numbers[0], numbers[-1] + 1))
                 else "weeks " + ", ".join(map(str, numbers)))
        parts.append(f"{season} {label}")
    return " and ".join(parts)


def pool_weeks_line(weeks: list[dict]) -> str:
    if not weeks:
        return ""
    games = sum(w["games"] for w in weeks)
    model = sum(w["model"] for w in weeks)
    average = sum(w["pool_average"] for w in weeks)
    firsts = sum(1 for w in weeks if w["place"] == 1)
    return (f"Against this pool's real cards ({_span(weeks)}) its card got {model} of {games} "
            f"right, where the pool's average coach got {average:.1f}"
            + (f", and it had the week's best score {firsts} of {len(weeks)} weeks." if firsts else "."))


def _long_run_line(report: Report) -> str:
    raw = report.long_run or {}
    week = raw.get("week") or {}
    money = raw.get("money") or {}
    right, pool = week.get("plain_right"), money.get("pool_right")
    if right is None or pool is None:
        return ""
    lo, hi = (raw.get("seasons") or ["2011", "2025"])[:2]
    return (f"Over {lo}-{hi} under this pool's rules its card got {right:.0%} of games right; "
            f"a typical coach gets {pool:.0%} - about {(right - pool) * 16:.1f} more games "
            f"a week.")


def _verdict(report: Report) -> None:
    coach = report.coach
    long_run = _long_run_line(report)
    weeks = len(report.weeks)
    lead = report.lead
    calls = report.calls
    reasons: list[str] = []
    if weeks:
        rate = report.model_rate or 0.0
        pool = report.pool_rate or 0.0
        reasons.append(
            f"This season its card has {report.model_total} of {report.games} right "
            f"({rate:.0%}), where the pool's average coach has {pool:.0%}"
            + (f", and it would have had the week's best score {report.weeks_best} of "
               f"{weeks} weeks." if report.weeks_best else ".")
        )
    if lead is not None and report.mine_total is not None:
        ahead = ("level with" if lead == 0 else
                 f"{abs(lead)} {'game' if abs(lead) == 1 else 'games'} "
                 + ("ahead of" if lead > 0 else "behind"))
        reasons.append(f"Its card is {ahead} {coach}'s over the same {weeks} "
                       f"{'week' if weeks == 1 else 'weeks'}.")
    if calls is not None and calls.calls:
        net = calls.net
        reasons.append(
            f"{coach}'s own calls - {calls.calls} {'game' if calls.calls == 1 else 'games'} "
            f"against its card - came in {calls.paid} times: "
            + (f"+{net} wins." if net > 0 else f"{net} wins." if net < 0 else "even.")
        )
    real = pool_weeks_line(report.pool_weeks)
    if real:
        reasons.append(real)
    if long_run:
        reasons.append(long_run)

    if weeks < JUDGE_FROM_WEEKS:
        report.headline = f"Follow {MODEL_NAME}'s card."
        report.tone = "good"
        reasons.append(
            f"{weeks} {'week is' if weeks == 1 else 'weeks are'} too few to judge by: "
            f"that much football is mostly luck, so the long run carries the verdict "
            f"until week {JUDGE_FROM_WEEKS} is graded."
            if weeks else "No graded weeks yet this season, so the long run carries the verdict."
        )
    elif lead is not None and lead >= CLEAR_LEAD:
        report.headline = f"Follow {MODEL_NAME}'s card."
        report.tone = "good"
    elif lead is not None and lead <= -(CLEAR_LEAD + 1):
        report.headline = f"{coach}'s own calls are working - keep them, but pick your spots."
        report.tone = ""
        reasons.append("Over a whole season the lines usually win, so go against them only "
                       "where you know something they don't.")
    else:
        report.headline = f"Follow {MODEL_NAME}'s card - it's close this season."
        report.tone = "good"
        reasons.append("When it's this close, the long run is the better guide.")
    report.reasons = reasons
