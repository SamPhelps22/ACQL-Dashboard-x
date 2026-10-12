"""The report card's grades: Deadeye marked subject by subject, like a school report.

One letter answers "is it any good?" faster than a page of figures - as long
as the letter means something. So each subject is one plain measurement set
against one yardstick, on a scale written down here:

    Picking games       where its season total would stand among the pool's coaches
    Against the line    its picks against the betting line's own side, same games
    Honest chances      whether picks it called 60% came in about 60% of the time
    Margins             how close its expected margins landed, against the line's
    Against you         its card against yours, week for week
    Winning the week    where its card would have finished each week
    Big Losers          its three likeliest a week against the pool's average coach
    Line movement       whether the betting line moved toward its picks afterwards

The betting line is the hard yardstick: level with it is a B, because level
with the market is good and beating it is rare. A subject with too little to
go on is not marked at all, and the overall grade - the average of the marks
given - is called provisional until MATURE_WEEKS weeks are in: five weeks of
football is mostly luck, and the card says so rather than bragging.

No Qt here.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .models import Season
from .version import MODEL_NAME

#: Letters and what each is worth, best first.
SCALE = (("A+", 4.3), ("A", 4.0), ("A-", 3.7), ("B+", 3.3), ("B", 3.0), ("B-", 2.7),
         ("C+", 2.3), ("C", 2.0), ("C-", 1.7), ("D", 1.0), ("F", 0.0))
POINTS = dict(SCALE)
#: Weeks before the overall grade stops being called provisional.
MATURE_WEEKS = 8
#: Picks the betting line must have moved on before "line movement" is marked.
MOVES_NEEDED = 12
#: Graded picks before "honest chances" and "margins" are marked.
PICKS_NEEDED = 40


def letter(points: float) -> str:
    """The letter nearest a number of grade points."""
    return min(SCALE, key=lambda pair: abs(pair[1] - points))[0]


def by_steps(value: float, steps) -> str:
    """The first grade whose bar `value` clears. `steps` is ((bar, grade), ...), highest bar first."""
    for bar, grade in steps:
        if value >= bar:
            return grade
    return steps[-1][1]


def tone(grade: str) -> str:
    """The colour a grade is shown in."""
    if not grade:
        return "muted"
    return "good" if grade[0] == "A" else "" if grade[0] == "B" else "warning" if grade[0] == "C" else "bad"


@dataclass(frozen=True)
class Subject:
    name: str
    grade: str              # "" when there is too little to mark
    figure: str             # the measurement, as a reader would say it
    against: str            # the yardstick it is held to
    meaning: str            # what the mark means, in a sentence
    scale: str = ""         # how the letter was arrived at, for the hover
    better: str = ""        # what would raise it

    @property
    def points(self) -> float | None:
        return POINTS.get(self.grade)


@dataclass(frozen=True)
class Standing:
    """Where the card's season total would put it among the pool's coaches."""

    rank: int
    of: int                                 # coaches, the card included
    total: int
    tied: int = 0
    leader: tuple[str, int] = ("", 0)       # the best real coach over the same weeks
    mine: tuple[int, int] | None = None     # (your rank, your total)
    table: tuple[tuple[int, str, int], ...] = ()    # (rank, name, total): the top of it, the card and you

    @property
    def share(self) -> float:
        """0 for last, 1 for first."""
        return (self.of - self.rank) / (self.of - 1) if self.of > 1 else 1.0


@dataclass(frozen=True)
class Card:
    subjects: list[Subject] = field(default_factory=list)
    weeks: int = 0
    standing: Standing | None = None
    hits: object | None = None          # the hits-and-misses report the marks were taken from

    def by_week(self) -> dict[int, tuple[int, int, float]]:
        """Week -> (picks, the betting line's hits, the hits its own chances called for)."""
        out: dict[int, list] = {}
        for g in (getattr(self.hits, "games", None) or []):
            tally = out.setdefault(g.week, [0, 0, 0.0])
            tally[0] += 1
            tally[1] += bool(g.line_right)
            tally[2] += g.chance
        return {week: (n, line, said) for week, (n, line, said) in out.items()}

    @property
    def marked(self) -> list[Subject]:
        return [s for s in self.subjects if s.grade]

    @property
    def points(self) -> float | None:
        marks = [s.points for s in self.marked]
        return statistics.fmean(marks) if marks else None

    @property
    def overall(self) -> str:
        return letter(self.points) if self.points is not None else ""

    @property
    def provisional(self) -> bool:
        return self.weeks < MATURE_WEEKS

    @property
    def best(self) -> Subject | None:
        return max(self.marked, key=lambda s: s.points, default=None)

    @property
    def worst(self) -> Subject | None:
        return min(self.marked, key=lambda s: s.points, default=None)


def standing(season: Season, weeks: list[int], model_total: int, coach_key: str | None) -> Standing | None:
    """The card's regular-game total over `weeks`, ranked among every coach's over the same weeks."""
    totals: dict[str, int] = {}
    for number in weeks:
        week = season.weeks.get(number)
        for key, line in (week.lines.items() if week is not None else ()):
            totals[key] = totals.get(key, 0) + int(line.regular_wins or 0)
    if not totals:
        return None
    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))

    def name(key: str) -> str:
        player = season.players.get(key)
        return player.display if player is not None else key

    everyone = [total for _key, total in ordered] + [model_total]

    def place(total: int) -> int:
        """A place in the field with the card in it."""
        return 1 + sum(1 for other in everyone if other > total)

    rank = place(model_total)
    mine = (place(totals[coach_key]), totals[coach_key]) if coach_key in totals else None
    rows = [(place(total), name(key), total) for key, total in ordered[:5]]
    rows.append((rank, f"{MODEL_NAME}'s card", model_total))
    if mine is not None and coach_key not in dict(ordered[:5]):
        rows.append((mine[0], name(coach_key), mine[1]))
    rows.sort(key=lambda row: (row[0], row[1] != f"{MODEL_NAME}'s card"))
    return Standing(rank=rank, of=len(ordered) + 1, total=model_total,
                    tied=sum(1 for _key, total in ordered if total == model_total),
                    leader=(name(ordered[0][0]), ordered[0][1]), mine=mine, table=tuple(rows))


# ---- the scales -------------------------------------------------------------------------------
#: Picking games and winning the week: the share of the pool finished ahead of (1 = everyone).
BY_SHARE = ((0.95, "A+"), (0.85, "A"), (0.75, "A-"), (0.65, "B+"), (0.55, "B"), (0.45, "B-"),
            (0.35, "C+"), (0.25, "C"), (0.15, "C-"), (0.05, "D"), (-1.0, "F"))
#: Against the line: games ahead of it in every hundred.
BY_LINE = ((3.0, "A"), (1.75, "A-"), (0.75, "B+"), (-0.75, "B"), (-1.75, "B-"), (-3.0, "C+"),
           (-4.5, "C"), (-6.0, "D"), (-99.0, "F"))
#: Honest chances: how far the record sits from its own chances, in spreads of luck (smaller is better).
BY_LUCK = ((-0.75, "A"), (-1.25, "A-"), (-1.75, "B"), (-2.25, "C"), (-2.75, "D"), (-99.0, "F"))
#: Margins: points closer than the betting line, on average.
BY_MARGIN = ((0.4, "A"), (0.2, "A-"), (0.08, "B+"), (-0.08, "B"), (-0.2, "B-"), (-0.4, "C+"),
             (-0.7, "C"), (-1.0, "D"), (-99.0, "F"))
#: Against you, and Big Losers: games (points) ahead a week.
BY_WEEK = ((1.0, "A"), (0.5, "A-"), (0.2, "B+"), (-0.2, "B"), (-0.5, "B-"), (-1.0, "C"),
           (-1.5, "D"), (-99.0, "F"))
BY_LOSERS = ((0.4, "A"), (0.2, "A-"), (0.08, "B+"), (-0.08, "B"), (-0.2, "B-"), (-0.4, "C"),
             (-0.6, "D"), (-99.0, "F"))
#: Line movement: points the line moved toward its picks, on average.
BY_MOVE = ((0.5, "A"), (0.25, "A-"), (0.1, "B+"), (-0.1, "B"), (-0.25, "C+"), (-0.5, "C"), (-99.0, "D"))


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def mark(report, hits=None, value=None, stand: Standing | None = None, pool_losers: float | None = None) -> Card:
    """The grades, from the report card's own numbers (reportcard.Report), the
    hits-and-misses report (autopsy.Report), the closing line value
    (closing.Value) and the card's standing in the pool. Any of the last
    four may be missing; its subjects are then left unmarked.

    Each subject says three things: the figure and its yardstick, what the
    mark means in a sentence, and what would raise it."""
    coach = report.coach
    weeks = len(report.weeks)
    out: list[Subject] = []
    top = "Already the top mark."

    # ---- picking games
    if weeks and stand is not None:
        rate, pool = report.model_rate or 0.0, report.pool_rate or 0.0
        grade = by_steps(stand.share, BY_SHARE)
        behind = stand.leader[1] - stand.total
        if stand.rank == 1 and not stand.tied:
            meaning = f"It has more games right than any coach in the pool over these {_plural(weeks, 'week')}."
            better = f"{top} It holds while it stays ahead of {stand.leader[0]} ({stand.leader[1]})."
        elif stand.rank == 1:
            meaning = (f"Level with {stand.leader[0]} at the top of the pool over these {_plural(weeks, 'week')}: "
                       f"nobody has more right.")
            better = f"{top} One more game right would put it clear of {stand.leader[0]}."
        else:
            meaning = (f"Only {stand.leader[0]} has more right over these {_plural(weeks, 'week')}." if stand.rank == 2 else
                       f"{stand.rank - 1} coaches have more right over these {_plural(weeks, 'week')}; "
                       f"the best is {stand.leader[0]} with {stand.leader[1]}.")
            better = ((f"{top} " if grade == "A+" else "")
                      + f"{_plural(max(behind, 0), 'more game')} right would draw level with {stand.leader[0]} at the top.")
        out.append(Subject(
            "Picking games", grade,
            f"{report.model_total} of {report.games} right ({rate:.0%})",
            f"would stand {'tied ' if stand.tied else ''}{_ordinal(stand.rank)} of {stand.of} in the pool; "
            f"the average coach has {pool:.0%}",
            meaning,
            "By the share of the pool it would finish ahead of: 95% is an A+, 85% an A, 55% a B, 25% a C.",
            better,
        ))
    else:
        out.append(Subject("Picking games", "", "no graded week yet", "the pool's coaches", "Marked once a week is graded."))

    # ---- against the line
    overall = hits.overall if hits is not None else None
    if overall is not None and overall.line_games >= PICKS_NEEDED and overall.line_games == overall.picks:
        ahead = overall.right - overall.line_right
        per_hundred = 100.0 * ahead / overall.picks
        grade = by_steps(per_hundred, BY_LINE)
        need = math.ceil(1.75 * overall.picks / 100)        # games ahead for an A-
        if not ahead:
            meaning = "Dead level with the betting line. That is a B on purpose: the line is the hardest test there is."
        else:
            meaning = (f"{_plural(abs(ahead), 'game')} {'ahead of' if ahead > 0 else 'behind'} the betting line. "
                       + ("A game or two either way is luck." if abs(ahead) <= 2 else
                          "More than luck usually gives - worth watching."))
        better = (f"{top} Holding it over a full season is the test." if grade in ("A", "A-") else
                  f"An A\u2212 takes being {_plural(need, 'game')} ahead of the line over these {overall.picks}: "
                  f"{need - ahead} more than now. Only knowing something the market doesn't gets there.")
        out.append(Subject(
            "Against the line", grade,
            f"{overall.right} right to the line's {overall.line_right}",
            f"the betting line's own side on the same {overall.picks} games",
            meaning,
            "By games ahead of the line in every hundred: level is a B, 2 ahead an A-, 3 an A; 2 behind a B-.",
            better,
        ))
    else:
        out.append(Subject("Against the line", "", "too few games with a betting line kept",
                           "the betting line's own side", f"Marked from {PICKS_NEEDED} graded picks."))

    # ---- honest chances
    if report.expected is not None and report.graded_picks >= PICKS_NEEDED and report.luck > 0:
        gap = report.graded_hits - report.expected
        spreads = abs(gap) / report.luck
        grade = by_steps(-spreads, BY_LUCK)
        if spreads < 0.75:
            meaning = "When it says 60%, about 60% come in. Its percentages can be taken at face value."
            better = top
        else:
            meaning = (f"Its picks have come in {abs(gap):.0f} {'more' if gap > 0 else 'fewer'} times than its "
                       f"percentages said - they run a little {'low' if gap > 0 else 'high'}, or it has been "
                       f"{'lucky' if gap > 0 else 'unlucky'}.")
            better = (f"An A takes the gap coming back inside {0.75 * report.luck:.0f} games. If it is still this "
                      f"wide after about 150 picks, its percentages should be nudged {'up' if gap > 0 else 'down'}.")
        out.append(Subject(
            "Honest chances", grade,
            f"{report.graded_hits} right where it said {report.expected:.1f}",
            f"its own chances over {_plural(report.graded_picks, 'pick')}; luck alone moves that about {report.luck:.1f}",
            meaning,
            "By how far the record sits from its own chances, in spreads of luck: within 0.75 is an A, 1.75 a B, 2.25 a C.",
            better,
        ))
    else:
        out.append(Subject("Honest chances", "", "too few graded picks", "its own chances",
                           f"Marked from {PICKS_NEEDED} graded picks."))

    # ---- margins
    error = hits.error if hits is not None else None
    if error is not None and error.games >= PICKS_NEEDED:
        closer = error.line - error.deadeye
        grade = by_steps(closer, BY_MARGIN)
        meaning = ("Its expected margins land as close to the final score as the betting line's - no better, no worse."
                   if abs(closer) < 0.08 else
                   f"On average {abs(closer):.1f} points {'closer to' if closer > 0 else 'further from'} the final "
                   f"score than the betting line.")
        better = (top if grade in ("A", "A-") else
                  f"An A\u2212 takes being 0.2 points closer than the line on average. Final margins are mostly "
                  f"noise - both miss by about {error.line:.0f} points - so this is the hardest mark to move.")
        out.append(Subject(
            "Margins", grade,
            f"{error.deadeye:.1f} points off, on average",
            f"the betting line alone: {error.line:.1f} points off over the same {error.games} games",
            meaning,
            "By points closer than the line: level is a B, 0.2 closer an A-, 0.4 an A.",
            better,
        ))
    else:
        out.append(Subject("Margins", "", "too few final scores kept", "the betting line's margin",
                           f"Marked from {PICKS_NEEDED} games with a final score."))

    # ---- against you
    lead = report.lead
    both = sum(1 for w in report.weeks if w.mine is not None)
    if lead is not None and both:
        calls = getattr(report, "calls", None)
        if lead > 0:
            meaning = f"Its card has {_plural(lead, 'more game')} right than yours - about {lead / both:.1f} a week."
            better = ("This is the gap you can close" + (
                f": on the {_plural(calls.calls, 'game')} where you went against its card you came out "
                f"{'level' if not calls.net else f'{calls.net:+d}'}." if calls is not None and calls.calls else
                " - it comes from the games where your card differed from its."))
        elif lead < 0:
            meaning = f"Your card has {_plural(-lead, 'more game')} right than its - you are out-picking it."
            better = "Nothing for you to fix: a low mark here is your card beating its."
        else:
            meaning = "Its card and yours are level."
            better = "It moves with the games where your card differs from its."
        out.append(Subject(
            "Against you", by_steps(lead / both, BY_WEEK),
            f"{report.model_total if both == weeks else sum(w.model for w in report.weeks if w.mine is not None)} "
            f"to {coach}'s {report.mine_total}",
            f"{coach}'s own card over the same {_plural(both, 'week')}",
            meaning,
            "By games ahead a week: 1 or more is an A, half a game an A-, level a B, a game behind a C.",
            better,
        ))
    else:
        out.append(Subject("Against you", "", f"no graded week for {coach}", "your own card", "Choose who you are above."))

    # ---- winning the week
    if weeks and report.average_place is not None:
        field_size = report.weeks[0].entrants + 1
        share = (field_size - report.average_place) / (field_size - 1) if field_size > 1 else 1.0
        grade = by_steps(share, BY_SHARE)
        target = max(1, math.floor(field_size - 0.85 * (field_size - 1)))       # the average finish an A takes
        out.append(Subject(
            "Winning the week", grade,
            f"best score {report.weeks_best} of {_plural(weeks, 'week')}",
            f"would have averaged {_ordinal(round(report.average_place))} of {field_size} each week",
            "The pool pays the week's best card. This is how near the top its card would have finished, week by "
            "week (ties for best count).",
            "By its average finish in the week: ahead of 85% of the pool is an A, 55% a B, 25% a C.",
            (f"{top} More outright best weeks would take the coin-flip games falling its way."
             if grade in ("A+", "A") else
             f"An A takes averaging {_ordinal(target)} or better each week; it averages "
             f"{_ordinal(round(report.average_place))}."),
        ))
    else:
        out.append(Subject("Winning the week", "", "no graded week yet", "each week's field", "Marked once a week is graded."))

    # ---- big losers
    if report.losers and pool_losers is not None:
        played = len(report.losers)
        points = sum(x.model_points for x in report.losers)
        grade = by_steps(points / played - pool_losers, BY_LOSERS)
        more = math.ceil((pool_losers + 0.2) * played - points)
        out.append(Subject(
            "Big Losers", grade,
            f"{_plural(points, 'point')} in {_plural(played, 'week')}",
            f"the pool's average coach: {pool_losers * played:.1f} over the same weeks; {coach}: "
            f"{sum(x.mine for x in report.losers)}",
            "A point each time one of its three teams loses by 15 or more. Its three are simply the likeliest.",
            "By points a week ahead of the pool's average coach: 0.2 ahead is an A-, level a B, 0.4 behind a C.",
            ((top if grade in ("A", "A-") else f"{_plural(max(more, 1), 'more point')} over these weeks would make it an A\u2212.")
             + " Blowouts come in about one time in four, so this mark swings week to week; Side Pools shows "
               "the picks that gain most on the pool."),
        ))
    else:
        out.append(Subject("Big Losers", "", "not graded yet", "the pool's average coach",
                           "Marked once a week's blowouts are known."))

    # ---- line movement
    if value is not None and len(value.picks) >= MOVES_NEEDED:
        grade = by_steps(value.points, BY_MOVE)
        out.append(Subject(
            "Line movement", grade,
            f"{value.points:+.1f} points a pick",
            f"where each line closed, over {_plural(len(value.picks), 'pick')}: "
            f"{value.toward} moved its way, {value.away} away",
            "After its picks were in, did the betting line move toward them? Over a season that is the surest "
            "sign of a real edge.",
            "By points the line moved toward its picks: 0.25 is an A-, level a B, 0.25 away a C+.",
            top if grade in ("A", "A-") else "An A\u2212 takes the line moving a quarter of a point toward its picks on average.",
        ))
    else:
        have = len(value.picks) if value is not None else 0
        out.append(Subject(
            "Line movement", "", f"{_plural(have, 'pick')} measured so far", "where each line closed",
            "After its picks are in, does the betting line move toward them? Over a season that is the surest "
            "sign of a real edge.",
            better=f"Not marked yet: it takes {MOVES_NEEDED} picks with a closing line, and {MOVES_NEEDED - have} "
                   f"are still to come - a week or two.",
        ))

    return Card(out, weeks, stand, hits)


def build(season: Season, report, coach_key: str | None) -> Card:
    """Everything `mark` needs, gathered from the season. Any part that fails is left unmarked."""
    hits = value = stand = pool_losers = None
    try:
        from . import autopsy
        hits = autopsy.report(season)
    except Exception:  # noqa: BLE001
        hits = None
    try:
        from . import closing
        value = closing.value(season)
    except Exception:  # noqa: BLE001
        value = None
    try:
        stand = standing(season, [w.week for w in report.weeks], report.model_total, coach_key)
    except Exception:  # noqa: BLE001
        stand = None
    try:
        per_week = []
        for line in report.losers:
            week = season.weeks.get(line.week)
            marks = [int(l.big_loser_wins or 0) for l in week.lines.values()] if week is not None else []
            if marks:
                per_week.append(statistics.fmean(marks))
        pool_losers = statistics.fmean(per_week) if per_week else None
    except Exception:  # noqa: BLE001
        pool_losers = None
    card = mark(report, hits, value, stand, pool_losers)
    return card
