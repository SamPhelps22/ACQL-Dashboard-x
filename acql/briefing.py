"""What to do this week, in one place.

Everything the dashboard knows about the week ahead is spread across pages:
the picks on Next Week, the crowd on Insights, the money on Winnings. Any one
of them answers a question. None of them answers the question, which is what
card to hand in on Thursday.

So this assembles the answer once, as plain values a page can lay out and a
person can read aloud:

    the card          a side for every game, and how sure it is
    the swings        the few picks that actually decide the week
    the big losers    three teams, and what they are worth
    the suicide pick  if still alive
    the money         what the card is expected to pay, and what wins the week

Nothing here draws anything or knows about Qt, so it can be checked against a
real week without a screen - which is the only way any of it was trusted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace

from . import analytics, lines, picks, predictions, pricing, weekplan
from .models import Game, Season, same_team


#: Picks worth calling out as where the week is won, most valuable first.
SWINGS = 3
#: A pick has to gain at least this much on the average card to be a swing.
SWING_LEVERAGE = 0.08
#: Below this the pick is a coin flip and is reported as one.
CONFIDENT = 0.60


@dataclass(frozen=True)
class Choice:
    """One game, decided."""

    index: int
    matchup: str
    pick: str
    other: str
    chance: float
    crowd: float | None          # share of the pool expected on the same side
    lined: bool                  # played under the pool's line rule
    line: str                    # the pool's line as written, or ""
    why: str
    #: Taken against the likelier side, because the planner found that this
    #: side wins the week more often. `pick`, `chance` and `crowd` then
    #: describe the side actually taken.
    turned: bool = False
    #: Chance of winning the week with this game flipped and the rest of the
    #: card kept - the planner's own measure of what this pick is worth.
    if_flipped: float | None = None
    home_margin: float | None = None     # the market line it was priced on

    @property
    def leverage(self) -> float | None:
        return None if self.crowd is None else self.chance - self.crowd

    @property
    def coin_flip(self) -> bool:
        # A turned game is under 50% on purpose; calling it a coin flip
        # would be describing the choice as an accident.
        return not self.turned and self.chance < 0.55

    def sentence(self) -> str:
        """The row as a line of a message."""
        if self.turned:
            on = f", on {self.crowd:.0%} of cards" if self.crowd is not None else ""
            return (
                f"{self.matchup}: {self.pick} ({self.chance:.0%}{on}) "
                f"- against the pool"
                + (f", {self.line}" if self.line else "")
            )
        gain = ""
        if self.leverage is not None and abs(self.leverage) >= 0.05:
            gain = f", {self.leverage:+.0%} on the field"
        return (
            f"{self.matchup}: {self.pick} ({self.chance:.0%}{gain})"
            + (f" - {self.line}" if self.line else "")
        )


@dataclass(frozen=True)
class Brief:
    """The week, decided."""

    week: int
    style: str = "win"
    choices: list[Choice] = field(default_factory=list)
    plan: weekplan.Plan | None = None
    losers: list[analytics.BigLoser] = field(default_factory=list)
    suicide_note: str = ""
    priced: int = 0
    games: int = 0
    counted_crowd: bool = False      # whether the pool's shares are real or guessed

    @property
    def straight(self) -> bool:
        return self.style == STYLE_STRAIGHT

    @property
    def win_odds(self) -> float | None:
        """Chance the card as shown finishes first."""
        if self.plan is None:
            return None
        return self.plan.plain_win_odds if self.straight else self.plan.win_odds

    @property
    def expected(self) -> float:
        """Games the card is expected to get right - the card as handed in."""
        return sum(c.chance for c in self.choices)

    @property
    def turned(self) -> list[Choice]:
        return [c for c in self.choices if c.turned]

    @property
    def swings(self) -> list[Choice]:
        """The handful of picks that decide the week, best first."""
        worth = [
            c for c in self.choices
            if c.leverage is not None and c.leverage >= SWING_LEVERAGE
        ]
        worth.sort(key=lambda c: -(c.leverage or 0))
        return worth[:SWINGS]

    @property
    def strong(self) -> list[Choice]:
        return [c for c in self.choices if c.chance >= CONFIDENT]

    @property
    def flips(self) -> list[Choice]:
        return [c for c in self.choices if c.coin_flip]

    def as_text(self) -> str:
        """The whole briefing as something that can be pasted into a message."""
        if not self.choices:
            return f"Week {self.week}: nothing priced yet."
        out = [f"ACQL week {self.week}", ""]
        if self.plan is not None and self.straight:
            out.append(
                f"  The likeliest side of every game: {self.plan.plain_win_odds:.1%} "
                f"to finish first of {self.plan.coaches + 1} (a fair share is "
                f"{self.plan.fair_share:.1%}; the card built to win the week "
                f"would be {self.plan.win_odds:.1%})"
            )
            out.append("")
        elif self.plan is not None:
            out.append(
                f"  Built to win the week: {self.plan.win_odds:.1%} to finish "
                f"first of {self.plan.coaches + 1} (a fair share is "
                f"{self.plan.fair_share:.1%}; the likeliest side of every game "
                f"would be {self.plan.plain_win_odds:.1%})"
            )
            out.append("")
        for choice in self.choices:
            out.append("  " + choice.sentence())
        out.append("")
        out.append(
            f"  {self.expected:.1f} of {len(self.choices)} expected"
            + (f", {len(self.strong)} strong" if self.strong else "")
            + (f", {len(self.flips)} coin flips" if self.flips else "")
        )
        if self.swings:
            out.append("")
            out.append("  Where the week is won:")
            for choice in self.swings:
                out.append(
                    f"    {choice.pick} - {choice.leverage:+.0%} on the average card"
                )
        if self.losers:
            out.append("")
            out.append("  Big Losers: " + ", ".join(
                f"{loser.team} ({loser.chance:.0%})" for loser in self.losers
            ))
        if self.suicide_note:
            out.append(f"  Suicide pool: {self.suicide_note}")
        return "\n".join(out)


#: The two cards This Week can hand in.
STYLE_WIN = "win"            # built to finish first (the planner's card)
STYLE_STRAIGHT = "straight"  # the likeliest side of every game


def build(season: Season, week: int, style: str = STYLE_WIN, *, use_sheet: bool = True) -> Brief:
    """Everything worth saying about a week, worked out once.

    `style` picks the card: the planner's, built to finish first, or the
    likeliest side of every game. Both are worked out either way, so the
    page can say what the other would do.

    `use_sheet=False` ignores the week's pick sheet - the card as it would
    have been made before anyone's picks were known, which is the only fair
    one to grade a past week by.

    Priced by pricing.py - the same rules as the Every Game worksheet, so the
    two can never quietly disagree about the same game: a typed spread wins,
    otherwise the market's latest number, nudged by the share of the models'
    opinion this season's results have earned.
    """
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found else []
    ctx = pricing.context(season, week, games)
    prices = pricing.price_week(season, week, games, ctx)
    sheet = picks.load(week) if use_sheet else None
    chalk_rate, _ = analytics.pool_chalk(season)

    choices: list[Choice] = []
    for p in prices:
        guess = p.prediction()
        if guess is None:
            continue
        game = p.game
        other = game.away if same_team(guess.pick, game.home) else game.home
        spread = p.spread or lines.Spread("home" if p.base >= 0 else "away", abs(p.base))
        crowd = pricing.crowd_share(season, week, game, guess.pick, spread, sheet, chalk_rate)
        choices.append(Choice(
            index=game.index,
            matchup=game.label,
            pick=predictions.display_team(guess.pick),
            other=predictions.display_team(other),
            chance=guess.chance,
            crowd=crowd,
            lined=guess.against_line,
            line=_line_text(game),
            why=guess.reason,
            home_margin=p.base,
        ))

    plan = None
    if len(choices) >= weekplan_minimum(choices):
        # The planner decides the card. Every game it turns over is shown
        # as the side it takes, so the table, the tiles and the text to paste
        # are all the card that is trying to win the week - not the safer
        # card that mostly lands in the top five.
        by_index = {g.index: g for g in games}
        cards = pricing.field_cards(
            sheet, [by_index[c.index] for c in choices], [c.pick for c in choices]
        )
        plan = weekplan.plan_week(
            [
                weekplan.Choice(
                    label=c.matchup, pick=c.pick, other=c.other,
                    chance=c.chance, crowd=c.crowd if c.crowd is not None else 0.7,
                )
                for c in choices
            ],
            cards=cards,
            coaches=max(1, len(season.players) - 1),
        )
        if plan is not None and style != STYLE_STRAIGHT:
            choices = [
                replace(
                    _turn(choice) if i in plan.flipped else choice,
                    if_flipped=plan.flip_odds[i] if i < len(plan.flip_odds) else None,
                )
                for i, choice in enumerate(choices)
            ]
        elif plan is not None:
            # The likeliest side everywhere: what each pick is worth to
            # winning the week, measured the same way the planner measures.
            found = weekplan.card_odds(
                [weekplan.Choice(label=c.matchup, pick=c.pick, other=c.other,
                                 chance=c.chance,
                                 crowd=c.crowd if c.crowd is not None else 0.7)
                 for c in choices],
                [c.pick for c in choices], cards=cards,
                coaches=max(1, len(season.players) - 1),
            )
            if found is not None:
                choices = [replace(c, if_flipped=found[1][i]) for i, c in enumerate(choices)]

    return Brief(
        week=week,
        style=style,
        choices=choices,
        plan=plan,
        losers=pricing.big_loser_candidates(prices)[:3],
        suicide_note=_suicide_note(season, week),
        priced=len(choices),
        games=len(games),
        counted_crowd=sheet is not None,
    )


def _turn(choice: Choice) -> Choice:
    """The same game, taking the side the planner chose over the likelier one."""
    crowd = None if choice.crowd is None else 1 - choice.crowd
    on = f" and on only {crowd:.0%} of cards" if crowd is not None else ""
    pack = (
        f", while {choice.pick} is on {choice.crowd:.0%} of them"
        if choice.crowd is not None else ""
    )
    return replace(
        choice,
        pick=choice.other,
        other=choice.pick,
        chance=1 - choice.chance,
        crowd=crowd,
        turned=True,
        why=(
            f"Against the pool: {1 - choice.chance:.0%} to land{on}. "
            f"{choice.pick} is likelier ({choice.chance:.0%}){pack} - right "
            f"there, you only keep pace with the pack. Right here, you pass it."
        ),
    )


def weekplan_minimum(choices: list[Choice]) -> int:
    """Planning a whole card is only worth it with most of the week priced."""
    return 6


def _line_text(game: Game) -> str:
    line = getattr(game, "line", None)
    favourite = getattr(game, "line_favourite", "") or ""
    if line is None or not favourite:
        return ""
    return f"{favourite} by {line:g}"


def _suicide_note(season: Season, week: int) -> str:
    """Where the suicide pool stands. Not a suggestion.

    Picking a survivor team needs to know which ones a coach has already
    spent, and the pick sheet records this week's choice rather than the
    history - so this says how the pool stands and leaves the choice alone
    rather than recommending a team that may already be used.
    """
    alive = [p for p in season.players.values() if p.suicide_alive]
    if not alive:
        return ""
    sheet = picks.load(week)
    if sheet is not None and sheet.suicide:
        # The sheet marks an eliminated coach's cell "DEAD" (or leaves it
        # blank); only real teams are counted, or "DEAD" is the most popular
        # pick in the pool from about week 3 on.
        tally = Counter(
            predictions.team_code(team) for team in sheet.suicide.values()
            if predictions.team_code(team)
        )
        if tally:
            code, count = tally.most_common(1)[0]
            return (
                f"{len(alive)} still alive \u00b7 most taken this week: "
                f"{predictions.display_team(code)} ({count})"
            )
    return f"{len(alive)} still alive in the suicide pool"
