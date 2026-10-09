"""One way to price a game, used by every page that shows a chance.

Before this, the Next Week worksheet and This Week's card each worked out a
game's chance in their own words, and they drifted apart in two places:

  * a spread typed in by hand won on Next Week but was ignored on This Week,
    which went on using the market's number;
  * Next Week believed the share of the models' opinion that the season's
    results had fitted, This Week the fixed starting figure.

So the same game could read 61% on one page and 58% on the other. Now both
call this module, and so do the suicide helper, the luck meter, the crowd
model and the Insights record - one set of rules, in one place:

    the base     a spread typed in by hand, when there is one: it is a
                 statement about the line. Otherwise the market's latest
                 number (fetched lines, or the predictions file), otherwise
                 the file's opening number.
    the models   a share of their disagreement with the market is added -
                 the slate's shared home lean taken out first, and anything
                 the line has already moved against discounted (see
                 predictions.Forecast.live_edge). How big a share is fitted
                 to this season's results once there are enough of them -
                 the results of the weeks before the one being priced.
    the spread   the usual 8.7 points, widened by how far apart the models
                 are on this game.

Every margin is from the HOME team's side: +6.5 is the home team by 6.5.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from . import analytics, lines, predictions
from .models import Game, Season, same_team


# ---- how much of the models to believe --------------------------------------------
#: The stored data the replays were made from -> each week's replay, and the
#: fits already worked out from them (keyed by the week they were for).
_WEIGHT_CACHE: dict[tuple, tuple[list, dict]] = {}


def model_weight(season: Season | None, before: int | None = None) -> tuple[float, predictions.WeightFit | None]:
    """(weight to use, the fit behind it) - fitted to this season once it can be.

    `before` fits on the weeks before that one only, and that is how every
    week is priced (context): with what was known going into it. So a week's
    chances don't move when its own games are played - its odds stay locked
    from the first kickoff (oddslock.py) - and the record grades each week
    without hindsight: week 5's picks are judged with the weight week 5 had,
    not one fitted on week 5's own results.

    Replaying every stored week at every weight is the slow part of pricing,
    so each week's replay is remembered until the stored predictions, the
    fetched lines or the results change; fitting from them is quick.
    """
    if season is None:
        return predictions.CONSENSUS_WEIGHT, None
    from . import odds
    results = tuple(sorted(
        (n, sum(1 for g in w.games if g.played)) for n, w in season.weeks.items()
    ))
    key = (id(season), results, predictions.store_stamp(), odds.stamp())
    kept = _WEIGHT_CACHE.get(key)
    if kept is None:
        replays = []
        for number, stored in predictions.stored_weeks().items():
            week = season.weeks.get(number)
            if week is None or not stored:
                continue
            if any(g.played for g in week.games):
                replays.append(predictions.replay_week(number, list(week.games), stored))
        kept = (replays, {})
        _WEIGHT_CACHE.clear()
        _WEIGHT_CACHE[key] = kept
    replays, fits = kept
    if before not in fits:
        used = [r for r in replays if before is None or r.number < before]
        fit = predictions.fit_from(used) if used else None
        fits[before] = (fit.weight if fit else predictions.CONSENSUS_WEIGHT, fit)
    return fits[before]


#: The weight each week was priced with, kept by "YEAR-WEEK" (store kind).
HELD_KIND = "weights"


def week_weight(season: Season | None, week: int) -> tuple[float, predictions.WeightFit | None]:
    """The weight a week is priced with (context).

    While the week is open it is fitted on the weeks before it, and noted
    down whenever it changes. From the week's first kickoff (oddslock.py) the
    last one noted stands, so nothing that comes in afterwards - not even a
    result for an earlier week from a pick sheet loaded late - moves the
    week's chances. A week first priced after its kickoff is held at what it
    is priced with then.
    """
    if season is None or not week:
        return model_weight(season, before=week or None)
    from . import oddslock, results, store
    key = f"{results.season_year(season)}-{week}"
    try:
        held = store.get(HELD_KIND, key)
    except Exception:  # noqa: BLE001 - pricing never fails over the note
        held = None
    if oddslock.locked_for(season, week):
        found = _held(held)
        if found is not None:
            return found
    weight, fit = model_weight(season, before=week)
    noted = {"weight": weight, "fit": None}
    if fit is not None:
        noted["fit"] = {**asdict(fit), "weeks": list(fit.weeks)}
    if noted != held:
        try:
            store.put(HELD_KIND, key, noted)
        except Exception:  # noqa: BLE001 - priced all the same; held next time
            pass
    return weight, fit


def _held(raw: object) -> tuple[float, predictions.WeightFit | None] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("weight"), (int, float)):
        return None
    fit = raw.get("fit")
    if isinstance(fit, dict):
        try:
            fit = predictions.WeightFit(**{**fit, "weeks": tuple(fit.get("weeks") or ())})
        except TypeError:
            fit = None
    else:
        fit = None
    return float(raw["weight"]), fit


# ---- a week's context ------------------------------------------------------------------
@dataclass(frozen=True)
class Context:
    """Everything about a week that pricing one of its games needs."""

    week: int
    forecasts: dict[int, predictions.Forecast] = field(default_factory=dict)
    lean: float = 0.0            # the slate's shared home lean, in points
    typical: float = 0.0         # how strung out the models normally are this week
    weight: float = predictions.CONSENSUS_WEIGHT
    fitted: predictions.WeightFit | None = None
    missing: tuple[str, ...] = ()
    flipped: tuple[int, ...] = ()


def context(
    season: Season | None,
    week: int,
    games: list[Game],
    forecasts: list[predictions.Forecast] | None = None,
) -> Context:
    """The week's stored predictions, matched to its slate."""
    if forecasts is None:
        forecasts, _ = predictions.load(week)
    # priced on the weeks before it, and held from its first kickoff
    weight, fit = week_weight(season, week)
    if not forecasts:
        return Context(week, {}, 0.0, 0.0, weight, fit)
    found = predictions.match_games(sorted(games, key=lambda g: g.index), forecasts)
    return Context(
        week=week,
        forecasts=dict(found.by_game),
        lean=predictions.home_lean(forecasts),
        typical=predictions.typical_disagreement(forecasts),
        weight=weight,
        fitted=fit,
        missing=tuple(getattr(found, "missing", ()) or ()),
        flipped=tuple(getattr(found, "flipped", ()) or ()),
    )


# ---- the numbers for one game --------------------------------------------------------
def opening_spread(game: Game, forecast: predictions.Forecast | None) -> lines.Spread | None:
    """The file's opening line as a Spread: the number the pool's own is set against."""
    if forecast is None:
        return None
    opening = forecast.opening if forecast.opening is not None else forecast.market
    margin = predictions.home_margin(game, forecast, opening)
    if margin is None:
        return None
    return lines.Spread("home" if margin >= 0 else "away", abs(margin))


def market_margin(game: Game, forecast: predictions.Forecast | None) -> float | None:
    """The market's latest number for the home side (the opener if that's all there is)."""
    if forecast is None:
        return None
    value = forecast.market if forecast.market is not None else forecast.opening
    return predictions.home_margin(game, forecast, value)


def model_edge(game: Game, ctx: Context) -> float | None:
    """What the models say about this game alone, home side, stale parts removed."""
    forecast = ctx.forecasts.get(game.index)
    if forecast is None:
        return None
    return predictions.home_margin(game, forecast, forecast.live_edge(ctx.lean))


@dataclass(frozen=True)
class Price:
    """One game, priced."""

    game: Game
    margin: float | None         # the expected home margin
    sd: float                    # how widely results scatter around it
    source: str                  # "Vegas" or "market + models"
    base: float | None           # the home margin the models were added to
    edge: float | None           # the models' own disagreement, home side
    typed: bool                  # the base was typed in by hand
    spread: lines.Spread | None  # the number shown in the Spread box

    @property
    def priced(self) -> bool:
        return self.margin is not None

    def prediction(self) -> analytics.Prediction | None:
        if self.margin is None:
            return None
        return analytics.predict_margin(self.game, self.margin, sd=self.sd, source=self.source)


def price(game: Game, ctx: Context, spread: lines.Spread | None = None,
          typed: bool = False) -> Price:
    """The one rule for a game's expected margin and spread of results.

    `spread` is what the page shows in the Spread box - the number typed in
    when `typed`, otherwise the file's opening line (see opening_spread).
    """
    forecast = ctx.forecasts.get(game.index)
    if spread is None and not typed:
        spread = opening_spread(game, forecast)

    base: float | None = None
    if typed and spread is not None and spread.favourite in ("home", "away"):
        base = spread.points if spread.favourite == "home" else -spread.points
    else:
        base = market_margin(game, forecast)
        if base is None and spread is not None and spread.favourite in ("home", "away"):
            base = spread.points if spread.favourite == "home" else -spread.points
    if base is None:
        return Price(game, None, analytics.SPREAD_SD, "Vegas", None, None, typed, spread)

    edge = model_edge(game, ctx)
    if edge is None or forecast is None:
        return Price(game, base, analytics.SPREAD_SD, "Vegas", base, None, typed, spread)
    # Not a flat share: a game the models can't agree on gets less of their
    # opinion, judged against how much they disagree this week.
    share = forecast.model_weight(ctx.weight, ctx.typical)
    sd = math.hypot(analytics.SPREAD_SD, forecast.extra_spread(ctx.weight, ctx.typical))
    return Price(game, base + share * edge, sd, "market + models", base, edge, typed, spread)


def stored_spread(week: int, game: Game) -> lines.Spread | None:
    """A spread typed in on the worksheet for this game, if any."""
    return lines.load_spreads(week, [game]).get(game.index)


def price_week(season: Season | None, week: int, games: list[Game] | None = None,
               ctx: Context | None = None) -> list[Price]:
    """Every game on the slate, priced from what is stored (typed spreads included)."""
    if games is None:
        found = season.weeks.get(week) if season is not None else None
        games = sorted(found.games, key=lambda g: g.index) if found else []
    ctx = ctx or context(season, week, games)
    typed = lines.load_spreads(week, games)
    return [
        price(g, ctx, typed.get(g.index), typed=g.index in typed)
        for g in games
    ]


def market_margins(week: int, games: list[Game]) -> dict[int, float]:
    """Game index -> the market's home margin, from the stored predictions."""
    forecasts, _ = predictions.load(week)
    if not forecasts:
        return {}
    out = {}
    for index, forecast in predictions.match_games(games, forecasts).by_game.items():
        game = next((g for g in games if g.index == index), None)
        if game is None:
            continue
        margin = market_margin(game, forecast)
        if margin is not None:
            out[index] = margin
    return out


# ---- what the rest of the pool will do ------------------------------------------------
def crowd_share(
    season: Season | None,
    week: int,
    game: Game,
    pick: str,
    spread: lines.Spread | None,
    sheet=None,
    chalk: float | None = None,
) -> float | None:
    """The share of the pool expected on `pick`.

    Counted off the pool's own pick sheet when it is loaded; otherwise this
    pool's learned habits once there is enough to learn from; otherwise the
    usual curve - on a lined game the pool's own rate of taking the
    favourite, and on a straight game how pools take favourites of that size.
    """
    from . import crowd

    if sheet is not None:
        row = sheet.game_for(game.away, game.home)
        if row is not None:
            share = row.share_on(pick)
            if share is not None:
                return share
    if spread is None or spread.favourite not in ("home", "away"):
        return None
    home_margin = spread.points if spread.favourite == "home" else -spread.points
    if season is not None:
        learned = crowd.guess(season, week, game, home_margin, pick)
        if learned is not None:
            return learned
    favourite = game.home if spread.favourite == "home" else game.away
    if getattr(game, "line", None) is not None:
        if chalk is None:
            chalk = analytics.pool_chalk(season)[0] if season is not None else analytics.CHALK_PRIOR
        on_favourite = chalk
        favourite = getattr(game, "line_favourite", "") or favourite
    else:
        on_favourite = analytics.crowd_on_favourite(spread.points)
    return on_favourite if same_team(pick, favourite) else 1 - on_favourite


def field_cards(sheet, games: list[Game], picks_taken: list[str]) -> list[list[int]] | None:
    """Every other coach's card from the pick sheet: 0 where they have our side.

    None unless the sheet covers every game being planned.
    """
    if sheet is None or not games:
        return None
    columns = []
    for game, pick in zip(games, picks_taken):
        found = sheet.game_for(game.away, game.home)
        if found is None:
            return None
        wanted = predictions.team_code(pick)
        column = [
            0 if predictions.team_code(team) == wanted else 1
            for team in found.picks.values() if predictions.team_code(team)
        ]
        if not column:
            return None
        columns.append(column)
    if len({len(c) for c in columns}) != 1:
        return None                      # sheets with gaps can't be laid side by side
    return [list(card) for card in zip(*columns)]


# ---- the Big Loser side pool -------------------------------------------------------------
def big_loser_candidates(prices: list[Price], *, include_played: bool = False) -> list[analytics.BigLoser]:
    """Both sides of every priced game as a big loser, likeliest first.

    Each game carries its own spread of results, so a game the models can't
    agree on is judged with the wider range - the same numbers the picks use.
    """
    out = []
    for p in prices:
        if p.margin is None or (p.game.played and not include_played):
            continue
        g = p.game
        out.append(analytics.BigLoser(g.away, g.home, -p.margin, analytics.big_loser_chance(-p.margin, p.sd)))
        out.append(analytics.BigLoser(g.home, g.away, p.margin, analytics.big_loser_chance(p.margin, p.sd)))
    out.sort(key=lambda b: -b.chance)
    return out


# ---- the record: every past pick, graded -----------------------------------------------
def graded_entries(season: Season) -> list[tuple[int, analytics.Prediction, str]]:
    """(week, the pick as it would be priced, the result) for every graded game.

    Replayed rather than remembered: the stored forecasts and the results are
    both on disk, so the record is rebuilt from them and can't drift away from
    what the app would say today. Only weeks with stored numbers count.
    """
    entries = []
    for number, stored in sorted(predictions.stored_weeks().items()):
        week = season.weeks.get(number)
        if week is None or not stored:
            continue
        games = sorted(week.games, key=lambda g: g.index)
        ctx = context(season, number, games, stored)
        for p in price_week(season, number, games, ctx):
            if not p.game.played or p.margin is None:
                continue
            if ctx.forecasts.get(p.game.index) is None and not p.typed:
                continue
            guess = p.prediction()
            if guess is not None:
                entries.append((number, guess, p.game.winner))
    return entries


def team_margins(season: Season | None, week: int) -> dict[str, float]:
    """Team code -> this week's expected margin for that team (for the suicide helper)."""
    out: dict[str, float] = {}
    for p in price_week(season, week):
        if p.margin is None:
            continue
        home, away = predictions.team_code(p.game.home), predictions.team_code(p.game.away)
        if home and away:
            out[home], out[away] = p.margin, -p.margin
    return out
