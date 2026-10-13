"""The recipe, taken apart: what each ingredient of Deadeye does, and whether it earns its place.

Deadeye is a short recipe (pricing.py): the betting line; on a straight-up
game the moneyline's say on it; a share of what the published models think
on top; then the pool's own rule. Three questions follow, and this answers
each from what is stored:

    The nudge       What if the models were given a different share of their
                    say? Every game of a week is priced again at every share
                    from none to all, so the picks that would flip can be
                    seen - and, for a week already played, whether flipping
                    them would have been right. Beside it, the season's
                    picks replayed at every share: the reason the share in
                    use is the one in use.
    The ingredients Over every graded game, how many picks did each step of
                    the recipe actually change from the step before it, and
                    how many of those changes came in?
    The lines       For each game, every reading of the betting line from
                    its opening to the deadline, with where the models sat -
                    what the pick was made on, and how it had moved.

A step that changes two picks in eighty games has not been tested by them:
every count here is small and is shown as a count, never as a rate, and the
Model Lab's rule (enough games, clearly better) is what decides anything.

No Qt here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .. import analytics
from ..feeds import lines, odds, oddslock, results
from . import predictions, pricing
from ..models import Game, Season, same_team
from .predictions import display_team, team_code
from ..version import MODEL_NAME

#: The shares the simulator can be set to: every twentieth, and the one in use.
STEP = 0.05
#: Shares worth naming when listing what flips.
MARKS = (0.0, 0.5, 0.85, 1.0)
#: Fewer published models than this and their middle is hardly a consensus.
FEW_MODELS = 8


def shares(in_use: float) -> tuple[float, ...]:
    return tuple(sorted({round(i * STEP, 2) for i in range(int(1 / STEP) + 1)} | {round(in_use, 2)}))


# ---- the nudge -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Nudge:
    """One game, priced at every share of the models' say."""

    index: int
    matchup: str
    line: float | None                  # the betting line, home side
    models: int                         # how many published models priced it
    apart: float | None                 # how far apart the ones that count are (points)
    view: float | None                  # how far the models sit from the line, home side, stale parts removed
    picks: dict[float, tuple[str, float]] = field(default_factory=dict)     # share -> (pick, chance)
    credited: str = ""                  # the side that was credited, once the game is graded

    def at(self, share: float) -> tuple[str, float] | None:
        return self.picks.get(round(share, 2))

    def flips(self, in_use: float, share: float) -> bool:
        """Whether this share takes the other side from the one in use."""
        now, then = self.at(in_use), self.at(share)
        return now is not None and then is not None and not same_team(now[0], then[0])

    @property
    def thin(self) -> bool:
        return 0 < self.models < FEW_MODELS

    def right(self, share: float) -> bool | None:
        """Whether the pick at this share was credited (None: not graded, or not priced)."""
        found = self.at(share)
        if not self.credited or found is None:
            return None
        return same_team(found[0], self.credited)


@dataclass(frozen=True)
class Simulation:
    week: int
    in_use: float
    shares: tuple[float, ...]
    games: list[Nudge] = field(default_factory=list)

    @property
    def with_models(self) -> int:
        return sum(1 for g in self.games if g.models)

    @property
    def graded(self) -> bool:
        return any(g.credited for g in self.games)

    def flipped(self, share: float) -> list[Nudge]:
        return [g for g in self.games if g.flips(self.in_use, share)]

    def record(self, share: float) -> tuple[int, int]:
        """(picks right, picks graded) for the whole card at a share."""
        marks = [g.right(share) for g in self.games]
        return sum(1 for m in marks if m), sum(1 for m in marks if m is not None)

    def first_flip(self) -> float | None:
        """The share nearest the one in use at which any pick changes side."""
        changing = [s for s in self.shares if self.flipped(s)]
        return min(changing, key=lambda s: abs(s - self.in_use)) if changing else None


def simulate(season: Season, week: int) -> Simulation:
    """Every game of a week priced at every share, on what is stored for it."""
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found is not None else []
    ctx = pricing.context(season, week, games)
    in_use = round(ctx.weight, 2)
    steps = shares(in_use)
    typed = lines.load_spreads(week, games) if games else {}
    out = []
    for game in games:
        forecast = ctx.forecasts.get(game.index)
        picks = {}
        for share in steps:
            price = pricing.price(game, replace(ctx, weight=share), typed.get(game.index), typed=game.index in typed)
            said = price.prediction()
            if said is not None:
                picks[share] = (display_team(said.pick), said.chance)
        if not picks:
            continue
        credited = ""
        if game.played and team_code(game.winner) in (team_code(game.home), team_code(game.away)):
            credited = display_team(game.winner)
        out.append(Nudge(
            index=game.index, matchup=game.label, line=pricing.market_margin(game, forecast),
            models=len(getattr(forecast, "opinions", ()) or ()),
            apart=getattr(forecast, "disagreement", None) if forecast is not None else None,
            view=pricing.model_edge(game, ctx) if forecast is not None else None,
            picks=picks, credited=credited,
        ))
    return Simulation(week, in_use, steps, out)


def weeks_with_lines(season: Season) -> list[int]:
    """The weeks there is anything to simulate: a slate, and stored numbers for it."""
    stored = predictions.stored_weeks()
    return [n for n in sorted(season.weeks) if season.weeks[n].games and (stored.get(n) or odds.stored(n) is not None)]


@dataclass(frozen=True)
class ShareLine:
    share: float
    right: int
    games: int
    surprise: float             # average surprise a pick (log loss): lower is better

    @property
    def rate(self) -> float:
        return self.right / self.games if self.games else 0.0


def season_by_share(season: Season) -> list[ShareLine]:
    """The season's graded picks replayed at every share (the same replay the share is fitted on)."""
    replays = []
    for number, stored in predictions.stored_weeks().items():
        week = season.weeks.get(number)
        if week is None or not stored or not any(g.played for g in week.games):
            continue
        replays.append(predictions.replay_week(number, list(week.games), stored))
    counted = sum(r.games for r in replays)
    if not counted:
        return []
    steps = predictions.fit_steps(predictions.CONSENSUS_WEIGHT)
    return [ShareLine(w, sum(r.hits.get(w, 0) for r in replays), counted,
                      sum(r.surprise.get(w, 0.0) for r in replays) / counted) for w in steps]


# ---- what each ingredient changed --------------------------------------------------------------
LINE, MONEYLINE, MODELS, POOL = "The betting line", "The moneyline", "The computer models", "The pool's line"
ABOUT = {
    LINE: "the spread alone, played under the pool's rules - where every pick starts",
    MONEYLINE: "on a straight-up game, the margin the prices to win outright imply, in place of the spread",
    MODELS: "a share of where the published models sit from the line, added on top",
    POOL: "the commissioner's line: the favourite has to win by it, so the likelier winner is not always the pick",
}


@dataclass(frozen=True)
class Ingredient:
    name: str
    games: int                  # games it had a say in
    changed: int = 0            # picks it changed from the step before
    helped: int = 0             # of those, the new pick was credited
    examples: tuple[str, ...] = ()

    @property
    def hurt(self) -> int:
        return self.changed - self.helped

    @property
    def net(self) -> int:
        return self.helped - self.hurt


def _side(game: Game, margin: float | None, sd: float = analytics.SPREAD_SD) -> str:
    said = analytics.predict_margin(game, margin, sd=sd) if margin is not None else None
    return said.pick if said is not None and said.chance > 0.5 else ""


def ingredients(season: Season) -> list[Ingredient]:
    """Over every graded game: the picks each step of the recipe changed, and how they came out."""
    tally = {name: [0, 0, 0, []] for name in (LINE, MONEYLINE, MODELS, POOL)}     # games, changed, helped, examples

    def note(name: str, week: int, game: Game, before: str, after: str, credited: str) -> None:
        row = tally[name]
        row[1] += 1
        won = same_team(after, credited)
        row[2] += won
        row[3].append(f"week {week}, {game.label}: {display_team(before)} became {display_team(after)} - "
                      + ("right" if won else "wrong"))

    for number in sorted(season.weeks):
        games = sorted(season.weeks[number].games, key=lambda g: g.index)
        decided = [g for g in games if g.played and team_code(g.winner) in (team_code(g.home), team_code(g.away))]
        if not decided:
            continue
        ctx = pricing.context(season, number, games)
        prices = {p.game.index: p for p in pricing.price_week(season, number, games, ctx)}
        for game in decided:
            price = prices.get(game.index)
            if price is None or price.margin is None or price.base is None:
                continue
            forecast = ctx.forecasts.get(game.index)
            anchor = price.base if price.typed or forecast is None else pricing._anchor(game, forecast, price.base)
            on_line, on_money = _side(game, price.base), _side(game, anchor)
            final = price.prediction()
            final_side = final.pick if final is not None and final.chance > 0.5 else ""
            if not on_line or not final_side:
                continue
            tally[LINE][0] += 1
            tally[LINE][2] += same_team(on_line, game.winner)
            if game.line is None and abs(anchor - price.base) >= 0.05:
                tally[MONEYLINE][0] += 1
                if on_money and not same_team(on_money, on_line):
                    note(MONEYLINE, number, game, on_line, on_money, game.winner)
            if price.edge is not None:
                tally[MODELS][0] += 1
                if on_money and not same_team(final_side, on_money):
                    note(MODELS, number, game, on_money, final_side, game.winner)
            if game.line is not None and game.line_favourite:
                tally[POOL][0] += 1
                likelier = game.home if price.margin >= 0 else game.away      # the side likelier to win the game
                if not same_team(final_side, likelier):
                    note(POOL, number, game, likelier, final_side, game.winner)
    out = []
    for name, (games, changed, helped, examples) in tally.items():
        if name == LINE:
            out.append(Ingredient(name, games, 0, helped, ()))       # nothing before it to change: `helped` is its record
        else:
            out.append(Ingredient(name, games, changed, helped, tuple(examples[:3])))
    return out


# ---- the line, reading by reading ----------------------------------------------------------------
@dataclass(frozen=True)
class Flight:
    """One game's betting line from its first reading to its last, from the pick's side."""

    index: int
    matchup: str
    pick: str
    readings: list[tuple[float, float]]     # (when, the line for the pick: + favoured, - getting points)
    models: float | None = None             # where the published models' middle sits, the same way round
    typed: tuple[float, float] | None = None    # a spread typed in by hand: (when, the line for the pick)
    lock: float = 0.0                       # when the card was due
    kickoff: float | None = None

    @property
    def opened(self) -> float | None:
        return self.readings[0][1] if self.readings else None

    @property
    def latest(self) -> float | None:
        return self.readings[-1][1] if self.readings else None

    @property
    def moved(self) -> float:
        """Points the line has moved toward the pick since its first reading (negative: away)."""
        return (self.latest - self.opened) if self.readings else 0.0

    @property
    def toward_models(self) -> bool | None:
        """Whether the line has moved toward where the models sat (None: no models, or no move)."""
        if self.models is None or not self.readings or abs(self.moved) < 0.25:
            return None
        return abs(self.latest - self.models) < abs(self.opened - self.models)


def flights(season: Season, week: int) -> list[Flight]:
    """Every priced game of a week with its line's readings, in slate order."""
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found is not None else []
    if not games:
        return []
    year = results.season_year(season)
    ctx = pricing.context(season, week, games)
    prices = {p.game.index: p for p in pricing.price_week(season, week, games, ctx)}
    stored = odds.stored(week)
    history = stored.history if stored is not None else []
    typed = lines.load_spreads(week, games)
    lock = oddslock.lock_time(year, week)
    scores = results.load(year, week)
    out = []
    for game in games:
        price = prices.get(game.index)
        said = price.prediction() if price is not None else None
        if said is None:
            continue
        side = 1.0 if same_team(said.pick, game.home) else -1.0
        home, away = team_code(game.home), team_code(game.away)
        readings = []
        for at, quoted in history:
            if f"{away}@{home}" in quoted:
                readings.append((at, side * quoted[f"{away}@{home}"]))
            elif f"{home}@{away}" in quoted:                # the books have it the other way round
                readings.append((at, -side * quoted[f"{home}@{away}"]))
        forecast = ctx.forecasts.get(game.index)
        if not readings and forecast is not None:
            # no fetched readings: the predictions file's opening and latest numbers are all there is
            when = predictions.market_time(week) or lock
            for value in (forecast.opening, forecast.market):
                margin = predictions.home_margin(game, forecast, value) if value is not None else None
                if margin is not None:
                    readings.append((when, side * margin))
        consensus = getattr(forecast, "consensus", None) if forecast is not None else None
        middle = predictions.home_margin(game, forecast, consensus) if consensus is not None and len(
            getattr(forecast, "opinions", ()) or ()) >= 3 else None
        spread = typed.get(game.index)
        typed_at = None
        if spread is not None and spread.favourite in ("home", "away") and spread.at:
            typed_at = (float(spread.at), side * (spread.points if spread.favourite == "home" else -spread.points))
        score, _flip = results.find(scores, game.away, game.home)
        out.append(Flight(
            index=game.index, matchup=game.label, pick=display_team(said.pick), readings=readings,
            models=None if middle is None else side * middle, typed=typed_at, lock=lock,
            kickoff=getattr(score, "kickoff", None) if score is not None else None,
        ))
    return out


def summary(found: Simulation) -> str:
    """What the simulator shows, in a sentence or two."""
    if not found.games:
        return f"Week {found.week} has nothing priced yet."
    if not found.with_models:
        return (f"No published models are in for week {found.week} yet, so the share changes nothing: "
                f"every pick is the line's until the Prediction Tracker's file is read.")
    parts = []
    for share in MARKS:
        changed = found.flipped(share)
        if not changed:
            continue
        names = ", ".join(f"{g.at(found.in_use)[0]} → {g.at(share)[0]}" for g in changed[:3])
        parts.append(f"at {share:.0%}, {len(changed)} ({names}{'…' if len(changed) > 3 else ''})")
    if not parts:
        return (f"Nothing flips: from none of the models' say to all of it, {MODEL_NAME} takes the same side "
                f"of every week-{found.week} game. The share only moves how sure it is.")
    return f"Picks that change side from the {found.in_use:.0%} in use: " + "; ".join(parts) + "."
