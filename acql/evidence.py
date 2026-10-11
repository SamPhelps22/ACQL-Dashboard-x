"""Why Deadeye takes each side: every piece of evidence about one game.

A card says "Buffalo, 74%". This says why, as a short list of signals a
person can check at a glance - each one for the pick, against it, or just
worth knowing:

    Betting line     the market's number, and what it says about the pool's question
    Line move        where the line opened and where it is now
    Computer models  how many of the published models side with the pick
    Form             each team's record and scoring margin this season
    Rest             a short week or a bye, when the two teams differ
    The pool         how much of the pool is expected on the same side
    You              your own record picking these teams this season
    Track record     how Deadeye's picks at this confidence have done
    Big Loser        when the other side is a blowout candidate

The market and the models are what the chance is made of; the rest is the
background the market has already weighed, shown so the pick can be
checked rather than taken on trust.

No Qt here: the page lays it out, and it can be checked without a screen.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from . import analytics, luck, pricing, results
from .models import Game, Season, same_team
from .predictions import display_team, team_code

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


def strength(chance: float) -> str:
    return next(name for floor, name in STRENGTHS if chance >= floor)


@dataclass(frozen=True)
class Signal:
    name: str
    verdict: str            # FOR, AGAINST or INFO
    headline: str
    detail: str = ""


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
    credited = luck.credited_chance(game, margin, team)
    if credited is None:
        return None
    verdict = FOR if credited > 0.5 else AGAINST if credited < 0.5 else INFO
    if game.line is not None and game.line_favourite:
        favourite = display_team(game.line_favourite)
        detail = (
            f"The pool's line is {favourite} by {game.line:g}. On the market's number "
            f"{pick} is credited {credited:.0%} of the time"
            + (f" ({outright:.0%} to win outright)." if outright != credited else ".")
        )
    else:
        detail = f"The market makes {pick} {outright:.0%} to win outright."
    return Signal("Betting line", verdict, _spread(margin, game), detail)


def _move(game: Game, pick: str, pick_home: bool, forecast) -> Signal | None:
    if forecast is None or forecast.opening is None or forecast.market is None:
        return None
    from .predictions import home_margin
    opened = home_margin(game, forecast, forecast.opening)
    now = pricing.market_margin(game, forecast)
    if opened is None or now is None:
        return None
    toward = (now - opened) if pick_home else (opened - now)
    headline = f"opened {_spread(opened, game)}, now {_spread(now, game)}"
    if toward >= MOVE:
        return Signal("Line move", FOR, headline,
                      f"{toward:g} point{'' if toward == 1 else 's'} toward {pick} since it opened: the news and the "
                      f"money have come in on this side.")
    if toward <= -MOVE:
        return Signal("Line move", AGAINST, headline,
                      f"{-toward:g} point{'' if toward == -1 else 's'} away from {pick} since it opened: the news and "
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
        from . import patterns
        spots = patterns.report(season).spots.get(me)
    loser_chance = {team_code(b.team): b.chance for b in pricing.big_loser_candidates(prices)
                    if team_code(b.team)}
    chosen = {team_code(b.team) for b in brief.losers}

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
            _move(game, choice.pick, pick_home, forecast),
            _models(game, choice.pick, pick_home, forecast),
            _form(pick_code, other_code, choice.pick, choice.other, form),
            _rest(choice.pick, choice.other, pick_code, other_code,
                  _kickoff(year, brief.week, game), form),
            _crowd(choice),
            _yours(spots, choice.pick, choice.other),
            _track(choice.chance, bands),
            _blowout(choice.other, other_code, loser_chance, chosen),
        ]
        if choice.turned:
            signals.insert(0, Signal("Against the pool", INFO, f"{choice.pick} is the less likely side",
                                     "Taken on purpose, to finish first rather than near the top."))
        out.append(Case(
            index=choice.index, matchup=choice.matchup, pick=choice.pick, other=choice.other,
            chance=choice.chance, line=choice.line, turned=choice.turned,
            signals=tuple(s for s in signals if s is not None),
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
