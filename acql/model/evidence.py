"""Why Deadeye takes each side: every piece of evidence about one game.

A card says "Buffalo, 74%". This says why, as a short list of signals a
person can check at a glance - each one for the pick, against it, or just
worth knowing:

    Betting line     the market's number, and what it says about the pool's question
    Pool line        a big favourite whose pool line isn't posted yet
    Line move        where the line opened and where it is now
    Computer models  how many of the published models side with the pick
    Form             each team's record and scoring margin this season
    Rest             a short week or a bye, when the two teams differ
    Weather          wind, rain or cold at an outdoor game, when it is worth knowing
    Scoring          the over/under, when it stands out from the slate
    Injuries         who is out on each side, from ESPN's report
    The pool         how much of the pool is expected on the same side
    You              your own record picking these teams this season
    Track record     how Deadeye's picks at this confidence have done
    Big Loser        when the other side is a blowout candidate
    Primetime dog    a night game's underdog, and how night dogs have done this season

The market and the models are what the chance is made of; the rest is the
background the market has already weighed, shown so the pick can be
checked rather than taken on trust.

No Qt here: the page lays it out, and it can be checked without a screen.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .. import analytics
from . import luck, predictions, pricing
from ..feeds import results
from ..models import Game, Season, same_team
from .predictions import display_team, team_code
from ..version import MODEL_NAME

FOR, AGAINST, INFO = "for", "against", "info"
#: Confidence, from the chance the pick is credited.
STRENGTHS = ((0.75, "Lock"), (0.65, "Strong"), (0.55, "Lean"), (0.0, "Coin flip"))
#: A line has to move this far (points) to count either way.
MOVE = 0.5
#: Scoring margins a game apart by this much make one team the better form.
FORM_GAP = 3.0
#: Days of rest apart by this much is worth mentioning.
REST_GAP = 2
#: A Big Loser chance this high on the other side is worth mentioning.
BLOWOUT = 0.15
#: An over/under this far from the slate's middle is worth mentioning.
TOTAL_GAP = 4.0
#: A signal that has disagreed with the betting line this often...
DISTRUST_GAMES = 6
#: ...and been right no more than this share of those times is shown but not
#: counted: its tick or cross has been worth less than nothing.
DISTRUST_RATE = 0.4
#: Sides this far apart in points added a play (attack less defence) is a real gap:
#: over the sixty-odd plays a side runs, about three points.
EFFICIENCY_GAP = 0.05
#: The commissioner usually puts a line on a favourite of about this size or
#: bigger (the same figure the long replay uses, backtest.LINED_FROM).
LINE_LIKELY = 6.5


def strength(chance: float) -> str:
    return next(name for floor, name in STRENGTHS if chance >= floor)


@dataclass(frozen=True)
class Signal:
    name: str
    verdict: str            # FOR, AGAINST or INFO
    headline: str
    detail: str = ""


@dataclass(frozen=True)
class Step:
    """One step in how the pick's number was made, in order."""

    name: str
    words: str                      # what it says
    points: float | None = None     # what it adds to the pick's margin (None: not a number of points)


@dataclass(frozen=True)
class Case:
    index: int
    matchup: str
    pick: str               # as the pages show it: "Buffalo"
    other: str
    chance: float
    line: str               # the pool's line as written, or ""
    turned: bool
    signals: tuple[Signal, ...]
    steps: tuple[Step, ...] = ()    # how the number was made, from the betting line to the chance

    def made(self) -> str:
        """The steps on one line: "Betting line Seattle -2 (+2.0) > Moneyline (-0.6) > ..."."""
        parts = []
        for step in self.steps:
            words = f"{step.name}: {step.words}" if step.words else step.name
            parts.append(words + (f" ({step.points:+.1f})" if step.points is not None else ""))
        return "  \u2192  ".join(parts)

    @property
    def strength(self) -> str:
        return strength(self.chance)

    @property
    def backing(self) -> int:
        return sum(1 for s in self.signals if s.verdict == FOR)

    @property
    def doubts(self) -> int:
        return sum(1 for s in self.signals if s.verdict == AGAINST)

    def summary(self) -> str:
        """"4 for, 1 against" - the signals that take a side."""
        parts = [f"{self.backing} for"]
        if self.doubts:
            parts.append(f"{self.doubts} against")
        return ", ".join(parts)


# ---- what the season so far says about each team ------------------------------------
@dataclass(frozen=True)
class Form:
    wins: int
    losses: int
    ties: int
    scored: int
    allowed: int
    last: str               # "beat Baltimore 31-10"
    last_kickoff: float | None

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def margin(self) -> float:
        return (self.scored - self.allowed) / self.games if self.games else 0.0

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")


def season_form(year: int, before_week: int) -> dict[str, Form]:
    """Team code -> its season before `before_week`, from the scores kept."""
    tally: dict[str, list] = {}
    for week in range(1, before_week):
        for score in results.load(year, week):
            if not score.final or score.away_points is None or score.home_points is None:
                continue
            for team, opp, mine, theirs in (
                (score.away, score.home, score.away_points, score.home_points),
                (score.home, score.away, score.home_points, score.away_points),
            ):
                t = tally.setdefault(team, [0, 0, 0, 0, 0, "", None])
                t[0] += mine > theirs
                t[1] += mine < theirs
                t[2] += mine == theirs
                t[3] += mine
                t[4] += theirs
                when = score.kickoff or 0.0
                if t[6] is None or when >= t[6]:
                    verb = "beat" if mine > theirs else "lost to" if mine < theirs else "tied"
                    t[5] = f"{verb} {display_team(opp)} {mine}-{theirs}"
                    t[6] = when
    return {code: Form(*values) for code, values in tally.items()}


def _kickoff(year: int, week: int, game: Game) -> float | None:
    found, _ = results.find(results.load(year, week), game.away, game.home)
    return getattr(found, "kickoff", None) if found is not None else None


# ---- the signals ----------------------------------------------------------------------
def _spread(home_margin: float, game: Game) -> str:
    """"Buffalo -6.5" from the home side's margin."""
    if abs(home_margin) < 0.25:
        return "Pick'em"
    favourite = game.home if home_margin > 0 else game.away
    return f"{display_team(favourite)} −{abs(round(home_margin * 2) / 2):g}"


def _market(game: Game, pick: str, pick_home: bool, forecast) -> Signal | None:
    margin = pricing.market_margin(game, forecast) if forecast is not None else None
    if margin is None:
        return None
    team = game.home if pick_home else game.away
    outright = luck._home_win(margin) if pick_home else 1 - luck._home_win(margin)
    # the moneyline is the market's own answer to "who wins": used when it is in
    money = pricing.market_win(game, forecast)
    if money is not None:
        outright = money if pick_home else 1 - money
    credited = luck.credited_chance(game, margin, team)
    if credited is None:
        return None
    if game.line is None and money is not None:
        credited = outright
    verdict = FOR if credited > 0.5 else AGAINST if credited < 0.5 else INFO
    if game.line is not None and game.line_favourite:
        favourite = display_team(game.line_favourite)
        detail = (
            f"The pool's line is {favourite} by {game.line:g}. On the market's number "
            f"{pick} is credited {credited:.0%} of the time"
            + (f" ({outright:.0%} to win outright)." if outright != credited else ".")
        )
    elif money is not None:
        detail = f"The moneyline makes {pick} {outright:.0%} to win outright."
    else:
        detail = f"The market makes {pick} {outright:.0%} to win outright."
    return Signal("Betting line", verdict, _spread(margin, game), detail)


def _line_coming(game: Game, forecast, lines_posted: bool) -> Signal | None:
    """A big favourite in a week whose pool lines aren't in yet: the pick is
    priced straight up for now, and usually isn't once the line is posted."""
    if lines_posted or game.line is not None or forecast is None:
        return None
    margin = pricing.market_margin(game, forecast)
    if margin is None or abs(margin) < LINE_LIKELY:
        return None
    favourite = display_team(game.home if margin > 0 else game.away)
    return Signal(
        "Pool line", AGAINST, "not posted yet - expect one",
        f"{favourite} is favoured by {abs(margin):g}, and favourites this big usually get a pool line. "
        f"Priced straight up for now: enter the line with Line games\u2026 when it is posted - the pick often changes.",
    )


def _injuries(pick: str, other: str, pick_code: str, other_code: str) -> Signal | None:
    """Who is out on each side. The line has it already; this is the why."""
    from ..feeds import injuries
    mine, theirs = injuries.team(pick_code), injuries.team(other_code)
    if not mine and not theirs:
        return None

    def short(name: str, report) -> str:
        gone = [i for i in report if i.missing]
        passer = next((i for i in gone if i.quarterback), None)
        if passer is not None:
            return f"{name}: QB {passer.name} {injuries.STATUSES[passer.status]}"
        return f"{name}: {len(gone)} out" if gone else f"{name}: none out"

    detail = " ".join(
        f"{name} - {injuries.summary(code) or 'nothing reported'}."
        for name, code in ((pick, pick_code), (other, other_code))
    )
    return Signal("Injuries", INFO, f"{short(pick, mine)} \u00b7 {short(other, theirs)}",
                  detail + " Already in the line; it is why the line is where it is.")


def _nth(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _efficiency(pick: str, other: str, pick_code: str, other_code: str, year: int, week: int) -> Signal | None:
    """How well each side has actually moved the ball and stopped it, lately."""
    try:
        from ..feeds import nflverse
        found = nflverse.efficiency() if nflverse.available() else None
    except Exception:  # noqa: BLE001 - the case stands without it
        found = None
    if found is None:
        return None
    mine, theirs = found.teams.get(pick_code), found.teams.get(other_code)
    if mine is None or theirs is None:
        return None
    gap = mine.net - theirs.net
    verdict = FOR if gap >= EFFICIENCY_GAP else AGAINST if gap <= -EFFICIENCY_GAP else INFO

    def words(name: str, form) -> str:
        return f"{name} attack {_nth(form.attack_rank)}, defence {_nth(form.defence_rank)}"

    behind = (week - 1) - found.week if found.season == year else None
    stale = ("" if behind is not None and behind <= 0 else
             f" The file stops at week {found.week} of {found.season}, so the latest games are not in it.")
    return Signal(
        "Efficiency", verdict, f"{words(pick, mine)} \u00b7 {words(other, theirs)}",
        f"Expected points added a play over each side's last {found.window} games: {pick} "
        f"{mine.attack:+.2f} with the ball and {mine.defence:+.2f} allowed; {other} {theirs.attack:+.2f} and "
        f"{theirs.defence:+.2f}. The line has weighed this already - it is the football under the number.{stale}")


def _quarterback(pick: str, other: str, pick_code: str, other_code: str,
                 market_at: float = 0.0) -> Signal | None:
    """Whether either side has a quarterback on the injury report - and
    whether that news came in after the newest line the card is priced on."""
    from ..feeds import injuries
    if not injuries.fetched_at():
        return None
    mine = [i for i in injuries.team(pick_code) if i.quarterback]
    theirs = [i for i in injuries.team(other_code) if i.quarterback]

    def words(name: str, listed) -> str:
        if not listed:
            return f"{name}: none listed"
        return f"{name}: " + ", ".join(f"{i.name} {injuries.STATUSES.get(i.status, i.status)}" for i in listed[:2])

    mine_out, theirs_out = any(i.missing for i in mine), any(i.missing for i in theirs)
    verdict = FOR if theirs_out and not mine_out else AGAINST if mine_out and not theirs_out else INFO
    late = injuries.newer_than(mine + theirs, market_at)
    detail = ("No quarterback on either side's injury report." if not mine and not theirs else
              "The report lists every quarterback on a roster, so a name here may be a backup rather than the "
              "starter - check who is starting. " + (
                  "The line already has it in." if not late else
                  "The line may not have it yet: " + ", ".join(
                      f"{i.name} ({injuries.STATUSES.get(i.status, i.status)})" for i in late)
                  + " changed after the newest line the card is priced on. Update lines before the card goes in."
                  + (" Questionable is not out - the line may barely move." if all(not i.missing for i in late)
                     else "")))
    headline = f"{words(pick, mine)} \u00b7 {words(other, theirs)}" + (" \u00b7 newer than the line" if late else "")
    return Signal("Quarterback", verdict, headline, detail)


def _steps(game: Game, choice, pick_home: bool, price, forecast) -> tuple[Step, ...]:
    """How the pick's number was made: the betting line, what was added to it, the pool's rule, the chance."""
    if price is None or price.margin is None or price.base is None:
        return ()
    side = 1.0 if pick_home else -1.0
    out = [Step("Typed spread" if price.typed else "Betting line", _spread(price.base, game), side * price.base)]
    anchor = price.base if price.typed or forecast is None else pricing._anchor(game, forecast, price.base)
    if abs(anchor - price.base) >= 0.05:
        out.append(Step("Moneyline", "the prices to win outright", side * (anchor - price.base)))
    if price.edge is not None:
        count = len(getattr(forecast, "opinions", ()) or ())
        out.append(Step("Computer models", f"{count} of them" if count else "", side * (price.margin - anchor)))
    ahead = side * price.margin
    out.append(Step(MODEL_NAME, f"{choice.pick} by {ahead:.1f}" if ahead >= 0 else f"{choice.other} by {-ahead:.1f}"))
    if game.line is not None and game.line_favourite:
        out.append(Step("Pool's line", f"{display_team(game.line_favourite)} must win by "
                                       f"{analytics.line_need(game.line)}"))
    else:
        out.append(Step("Straight up", "just has to win"))
    out.append(Step("Chance", f"{choice.chance:.0%}"))
    return tuple(out)


def _weather(year: int, week: int, game: Game) -> Signal | None:
    """Wind, rain or cold at kickoff - only when there is some, and no roof."""
    from ..feeds import weather
    found = weather.game(year, week, game.away, game.home)
    if found is None or not found.notable:
        return None
    return Signal("Weather", INFO, found.words() + (f" in {found.city.split(',')[0]}" if found.city else ""),
                  "Wind and rain pull the scoring down and favour the run. The total has it in "
                  "already; it is why a blowout is a little less likely here.")


def _scoring(forecast, typical: float) -> Signal | None:
    """The over/under, when this game stands out from the rest of the slate."""
    total = getattr(forecast, "total", None)
    if not total or not typical or abs(total - typical) < TOTAL_GAP:
        return None
    if total > typical:
        return Signal("Scoring", INFO, f"over/under {total:g} - high for this slate ({typical:g})",
                      "More points means wider margins: an upset and a blowout are both a little likelier.")
    return Signal("Scoring", INFO, f"over/under {total:g} - low for this slate ({typical:g})",
                  "Fewer points means closer games: a big favourite is a little less likely to run away with it.")


def _move(game: Game, pick: str, pick_home: bool, forecast) -> Signal | None:
    if forecast is None or forecast.opening is None or forecast.market is None:
        return None
    from .predictions import home_margin
    opened = home_margin(game, forecast, forecast.opening)
    now = pricing.market_margin(game, forecast)
    if opened is None or now is None:
        return None
    toward = (now - opened) if pick_home else (opened - now)
    # without the books' own opener, the first line seen is all there is
    seen = bool(getattr(forecast, "opening_seen", False))
    headline = f"{'first seen' if seen else 'opened'} {_spread(opened, game)}, now {_spread(now, game)}"
    since = "since first seen" if seen else "since it opened"
    if toward >= MOVE:
        return Signal("Line move", FOR, headline,
                      f"{toward:g} point{'' if toward == 1 else 's'} toward {pick} {since}: the news and the "
                      f"money have come in on this side.")
    if toward <= -MOVE:
        return Signal("Line move", AGAINST, headline,
                      f"{-toward:g} point{'' if toward == -1 else 's'} away from {pick} {since}: the news and "
                      f"the money have gone the other way.")
    return Signal("Line move", INFO, headline, "Hasn't moved enough to say anything.")


def _models(game: Game, pick: str, pick_home: bool, forecast) -> Signal | None:
    opinions = list(getattr(forecast, "opinions", ()) or ())
    if len(opinions) < 3:
        return None
    team = game.home if pick_home else game.away
    votes = [luck.credited_chance(game, o, team) for o in opinions]
    votes = [v for v in votes if v is not None]
    if not votes:
        return None
    agree = sum(1 for v in votes if v > 0.5)
    share = agree / len(votes)
    middle = statistics.median(opinions)
    low, high = min(opinions), max(opinions)
    detail = (
        f"Their middle: {_spread(middle, game)}; from {_spread(low, game)} to "
        f"{_spread(high, game)}."
    )
    verdict = FOR if share >= 0.55 else AGAINST if share <= 0.45 else INFO
    return Signal("Computer models", verdict, f"{agree} of {len(votes)} side with {pick}", detail)


def _form(pick_code: str, other_code: str, pick: str, other: str, form: dict[str, Form]) -> Signal | None:
    mine, theirs = form.get(pick_code), form.get(other_code)
    if mine is None or theirs is None or not mine.games or not theirs.games:
        return None
    gap = mine.margin - theirs.margin
    verdict = FOR if gap >= FORM_GAP else AGAINST if gap <= -FORM_GAP else INFO
    headline = (f"{pick} {mine.record} ({mine.margin:+.1f} a game) · "
                f"{other} {theirs.record} ({theirs.margin:+.1f})")
    detail = f"Last time out, {pick} {mine.last}; {other} {theirs.last}."
    return Signal("Form", verdict, headline, detail)


def _rest(pick: str, other: str, pick_code: str, other_code: str, kickoff: float | None,
          form: dict[str, Form]) -> Signal | None:
    if kickoff is None:
        return None
    mine, theirs = form.get(pick_code), form.get(other_code)
    if mine is None or theirs is None or not mine.last_kickoff or not theirs.last_kickoff:
        return None
    a = round((kickoff - mine.last_kickoff) / 86400)
    b = round((kickoff - theirs.last_kickoff) / 86400)
    if abs(a - b) < REST_GAP:
        return None
    def words(days: int) -> str:
        return f"{days} days" + (" (off a bye)" if days >= 12 else " (short week)" if days <= 5 else "")
    return Signal("Rest", FOR if a > b else AGAINST, f"{pick} {words(a)} · {other} {words(b)}",
                  "Already in the line, but worth knowing.")


def _crowd(choice) -> Signal | None:
    if choice.crowd is None:
        return None
    share = choice.crowd
    if share >= 0.5:
        detail = ("Taking it keeps pace with the pool; the week is won on the games it gets wrong."
                  if share >= 0.75 else "Most of the pool sees it the same way.")
    else:
        detail = "If it comes in you gain on most of the pool."
    return Signal("The pool", INFO, f"about {share:.0%} on {choice.pick}", detail)


def _yours(spots, pick: str, other: str) -> Signal | None:
    if spots is None:
        return None
    found = {s.label: s for s in (*spots.teams, *spots.against)}
    parts = []
    for label in (f"Picking {pick}", f"Against {other}"):
        s = found.get(label)
        if s is not None and s.picks:
            parts.append(f"{s.right}-{s.wrong} {label[0].lower()}{label[1:]}")
    if not parts:
        return None
    return Signal("You", INFO, " · ".join(parts), "Your own picks this season.")


def _track(chance: float, bands: list[analytics.Band]) -> Signal | None:
    band = next((b for b in bands if b.low <= chance < b.high or (b.high >= 1 and chance >= b.low)), None)
    if band is None or band.picks < 3:
        return None
    return Signal(
        "Track record", INFO,
        f"{band.hits} of {band.picks} came in ({band.actual:.0%})",
        f"Deadeye's picks rated {band.low:.0%}-{min(band.high, 1):.0%} this season "
        f"(they claimed {band.claimed:.0%} on average).",
    )


def _primetime(game: Game, pick: str, year: int, week: int, record) -> Signal | None:
    """A night game: the underdog's side, with the season's primetime-dog record."""
    from ..pool import trends
    score, flipped = results.find(results.load(year, week), game.away, game.home)
    night = trends.night(getattr(score, "kickoff", None))
    if not night:
        return None
    dog = trends.underdog(game, score, flipped)
    detail = (f"Primetime underdogs are {record.record()} against the spread this season"
              + (f" and have {record.streak_words()}" if record.streak_words() else "") + "."
              if record is not None and record.games else "No primetime games graded yet this season.")
    if not dog:
        return Signal("Primetime dog", INFO, f"{night} game", detail)
    if same_side(pick, dog):
        return Signal("Primetime dog", FOR, f"{night}: {pick} is the underdog", detail)
    return Signal("Primetime dog", AGAINST, f"{night}: {display_team(dog)} is the underdog", detail)


def _blowout(other: str, other_code: str, loser_chance: dict[str, float], chosen: set[str]) -> Signal | None:
    chance = loser_chance.get(other_code)
    if chance is None or chance < BLOWOUT:
        return None
    on_card = " - one of Deadeye's Big Losers" if other_code in chosen else ""
    return Signal("Big Loser", INFO, f"{other} {chance:.0%} to lose by 15+{on_card}",
                  "A blowout is worth Big Loser points on top of the pick.")


# ---- every game on the card -------------------------------------------------------------
def build(season: Season, brief, me: str | None = None) -> list[Case]:
    """The case for every pick on a briefing's card, in slate order."""
    week = season.weeks.get(brief.week)
    if week is None or not brief.choices:
        return []
    games = sorted(week.games, key=lambda g: g.index)
    by_index = {g.index: g for g in games}
    ctx = pricing.context(season, brief.week, games)
    prices = pricing.price_week(season, brief.week, games, ctx)
    year = results.season_year(season)
    form = season_form(year, brief.week)
    try:
        bands = analytics.calibration(pricing.graded_entries(season))
    except Exception:  # noqa: BLE001 - the case stands without its track record
        bands = []
    spots = None
    if me:
        from ..pool import patterns
        spots = patterns.report(season).spots.get(me)
    loser_chance = {team_code(b.team): b.chance for b in pricing.big_loser_candidates(prices)
                    if team_code(b.team)}
    chosen = {team_code(b.team) for b in brief.losers}
    lines_posted = any(g.line is not None for g in games)
    priced = {p.game.index: p for p in prices}
    doubted = distrusted(season)
    # today's injury report says nothing about a week that has been played
    current = not all(g.played for g in games)
    try:
        from ..pool import trends
        night_record = trends.primetime_record(season, brief.week - 1)
    except Exception:  # noqa: BLE001 - the case stands without it
        night_record = None
    market_at = predictions.market_time(brief.week) if current else 0.0

    out = []
    for choice in brief.choices:
        game = by_index.get(choice.index)
        if game is None:
            continue
        pick_home = team_code(choice.pick) == team_code(game.home)
        pick_code, other_code = team_code(choice.pick), team_code(choice.other)
        forecast = ctx.forecasts.get(game.index)
        signals = [
            _market(game, choice.pick, pick_home, forecast),
            _line_coming(game, forecast, lines_posted),
            _move(game, choice.pick, pick_home, forecast),
            _models(game, choice.pick, pick_home, forecast),
            _efficiency(choice.pick, choice.other, pick_code, other_code, year, brief.week) if current else None,
            _quarterback(choice.pick, choice.other, pick_code, other_code, market_at) if current else None,
            _form(pick_code, other_code, choice.pick, choice.other, form),
            _rest(choice.pick, choice.other, pick_code, other_code,
                  _kickoff(year, brief.week, game), form),
            _injuries(choice.pick, choice.other, pick_code, other_code) if current else None,
            _weather(year, brief.week, game) if current else None,
            _scoring(forecast, ctx.typical_total),
            _crowd(choice),
            _yours(spots, choice.pick, choice.other),
            _track(choice.chance, bands),
            _blowout(choice.other, other_code, loser_chance, chosen),
            _primetime(game, choice.pick, year, brief.week, night_record),
        ]
        signals = [_discounted(s, doubted) for s in signals]
        if choice.turned:
            signals.insert(0, Signal("Against the pool", INFO, f"{choice.pick} is the less likely side",
                                     "Taken on purpose, to finish first rather than near the top."))
        out.append(Case(
            index=choice.index, matchup=choice.matchup, pick=choice.pick, other=choice.other,
            chance=choice.chance, line=choice.line, turned=choice.turned,
            signals=tuple(s for s in signals if s is not None),
            steps=_steps(game, choice, pick_home, priced.get(game.index), forecast),
        ))
    return out


def same_side(a: str, b: str) -> bool:
    return same_team(a, b) or (bool(team_code(a)) and team_code(a) == team_code(b))


def overruled(season: Season, week: int) -> list[str]:
    """Games whose typed-in spread is older than the latest line, so the line was used."""
    found = season.weeks.get(week)
    if found is None:
        return []
    games = sorted(found.games, key=lambda g: g.index)
    return [p.game.label for p in pricing.price_week(season, week, games) if p.overruled]


# ---- how each signal has done ----------------------------------------------------------
@dataclass(frozen=True)
class SignalRecord:
    """One signal as a tipster: every graded game it had a view on."""

    name: str
    games: int = 0              # games it pointed to a side
    right: int = 0              # ...and that side was credited
    split: int = 0              # games it pointed the other way from the betting line
    split_right: int = 0        # ...and was right

    @property
    def rate(self) -> float:
        return self.right / self.games if self.games else 0.0


_BOARD: dict[tuple, list[SignalRecord]] = {}


def distrusted(season: Season) -> dict[str, SignalRecord]:
    """Signals whose own record this season says not to count them."""
    try:
        board = scoreboard(season)
    except Exception:  # noqa: BLE001 - without a record every signal counts
        return {}
    return {r.name: r for r in board
            if r.split >= DISTRUST_GAMES and r.split_right / r.split <= DISTRUST_RATE
            and r.name in ("Line move", "Computer models", "Form", "Rest", "Primetime dog")}


def _discounted(signal: Signal | None, doubted: dict[str, SignalRecord]) -> Signal | None:
    """A signal with a wrong-way record keeps its place and loses its vote."""
    if signal is None or signal.verdict == INFO or signal.name not in doubted:
        return signal
    record = doubted[signal.name]
    return Signal(
        signal.name, INFO, signal.headline,
        f"{signal.detail} Not counted: when it has disagreed with the betting line this season "
        f"it has been right {record.split_right} of {record.split} times.",
    )


#: The rows of the scoreboard, in the order they are read.
SCORED = ("Deadeye", "Betting line", "Computer models", "Line move", "Form", "Rest", "Primetime dog", "The pool")


def scoreboard(season: Season) -> list[SignalRecord]:
    """How often each signal's side has been credited this season.

    Every graded game is asked of every signal: which side does it point
    to? - the same rule the page uses for a tick or a cross. `split` is the
    part worth knowing: the games where a signal disagreed with the betting
    line, and who was right. A signal that only ever agrees with the line
    tells you nothing the line didn't.
    """
    from ..feeds import odds
    from ..pool import patterns, picks
    from . import predictions
    from ..version import MODEL_NAME
    key = (id(season), predictions.store_stamp(), odds.stamp(), picks._store_stamp(),
           sum(1 for w in season.weeks.values() for g in w.games if g.played))
    if key in _BOARD:
        return _BOARD[key]
    year = results.season_year(season)
    tally = {name: [0, 0, 0, 0] for name in SCORED}
    for number in sorted(season.weeks):
        week = season.weeks[number]
        games = [g for g in sorted(week.games, key=lambda g: g.index) if patterns._decided(g)]
        if not games:
            continue
        ctx = pricing.context(season, number, sorted(week.games, key=lambda g: g.index))
        prices = {p.game.index: p for p in pricing.price_week(season, number, sorted(week.games, key=lambda g: g.index), ctx)}
        form = season_form(year, number)
        crowd: dict[int, list[int]] = {}
        for card in patterns.week_cards(season, number).values():
            for pick in card:
                sides = crowd.setdefault(pick.game.index, [0, 0])
                sides[0 if pick.side == "home" else 1] += 1
        for game in games:
            forecast = ctx.forecasts.get(game.index)
            home, away = display_team(game.home), display_team(game.away)
            home_code, away_code = team_code(game.home), team_code(game.away)
            home_credited = team_code(game.winner) == home_code
            views: dict[str, bool | None] = {}

            def side(signal: Signal | None) -> bool | None:
                if signal is None or signal.verdict == INFO:
                    return None
                return signal.verdict == FOR            # for the home side, the one asked about

            views["Betting line"] = side(_market(game, home, True, forecast))
            views["Line move"] = side(_move(game, home, True, forecast))
            views["Computer models"] = side(_models(game, home, True, forecast))
            views["Form"] = side(_form(home_code, away_code, home, away, form))
            views["Rest"] = side(_rest(home, away, home_code, away_code, _kickoff(year, number, game), form))
            views["Primetime dog"] = side(_primetime(game, home, year, number, None))
            took = crowd.get(game.index)
            views["The pool"] = None if not took or took[0] == took[1] else took[0] > took[1]
            guess = prices[game.index].prediction() if game.index in prices else None
            views["Deadeye"] = None if guess is None else team_code(guess.pick) == home_code
            line = views["Betting line"]
            for name, view in views.items():
                if view is None:
                    continue
                row = tally[name]
                row[0] += 1
                row[1] += view == home_credited
                if line is not None and view != line:
                    row[2] += 1
                    row[3] += view == home_credited
    labels = {"Deadeye": MODEL_NAME}
    board = [SignalRecord(labels.get(name, name), *tally[name]) for name in SCORED]
    _BOARD.clear()
    _BOARD[key] = board
    return board
