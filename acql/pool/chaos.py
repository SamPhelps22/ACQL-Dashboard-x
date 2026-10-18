"""The Chaos Simulator: play the coming Sunday 10,000 times and see where you land.

Every game's result is drawn from the MARKET - the betting line and, where
the fetched moneylines have it, their chance of an outright win. Deadeye's
own opinion never decides a simulated result: a simulator that grades the
model's card with the model's own odds would only tell you the model agrees
with itself.

Each simulated Sunday draws a final margin for every game, so a lined game
and a straight-up game are graded from the same kind of number: the
favourite is credited on a lined game when it wins by at least the line
(analytics.line_need). The other coaches' cards come from, in order of
preference:

    pick sheet   the card they actually handed in this week
    history      how often their past cards took the market favourite,
                 drawn afresh every simulated Sunday
    favourites   nobody has seen a card of theirs: assumed to take the
                 favourite in every game

Every coach's report says which of those it used. Big Losers are not
simulated - this is the regular picks only.

The engine (`simulate`, `report`) knows nothing about the season or files;
`build` gathers the week's inputs from what is already stored and makes no
network calls, so it costs nothing from the odds API budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

SIMULATIONS = 10_000
SEED = 1717
#: Spread of an NFL final margin around the line, in points.
MARGIN_SD = 13.5
#: Picks a coach needs on record before their own favourite habit is used.
MIN_HISTORY = 12
#: Their habit is pulled toward this pool's usual rate by this many picks.
SHRINK = 8
POOL_USUAL = 0.72

BASIS_SHEET = "pick sheet"
BASIS_HISTORY = "history"
BASIS_FAVOURITES = "favourites"


@dataclass(frozen=True)
class ChaosGame:
    """One game, from the market's side. Margins are the home team's."""

    label: str
    home: str
    away: str
    home_margin: float              # the market's expected home margin
    home_win: float | None = None   # the moneylines' outright chance, if fetched
    line: float | None = None       # the pool's line, when the game is lined
    line_fav_home: bool = True      # which side the pool's line favours

    @property
    def mean(self) -> float:
        """The margin the draw centres on: the moneyline's view where there is one."""
        if self.home_win is not None and 0.0 < self.home_win < 1.0:
            return MARGIN_SD * _ppf(self.home_win)
        return self.home_margin

    def home_credited_chance(self) -> float:
        """The market's chance the home side is the one credited."""
        if self.line is None:
            return _cdf(self.mean / MARGIN_SD)
        need = _need(self.line)
        fav_mean = self.mean if self.line_fav_home else -self.mean
        fav = 1.0 - _cdf((need - 0.5 - fav_mean) / MARGIN_SD)
        return fav if self.line_fav_home else 1.0 - fav

    @property
    def favourite_is_home(self) -> bool:
        return self.home_credited_chance() >= 0.5


@dataclass(frozen=True)
class Coach:
    """A coach and how their card is drawn.

    `card` is a fixed side per game (True home, False away, None no pick) when
    their sheet is in; otherwise `fav_rate` is how often they take the
    favourite, game by game.
    """

    name: str
    basis: str
    card: tuple[bool | None, ...] | None = None
    fav_rate: float = 1.0
    picks_seen: int = 0

    @property
    def basis_text(self) -> str:
        if self.basis == BASIS_SHEET:
            return "their pick sheet for this week"
        if self.basis == BASIS_HISTORY:
            return (f"their history: took the favourite {self.fav_rate:.0%} of the time "
                    f"over {self.picks_seen} picks")
        return "assumed: picks every favourite (no cards on record)"


@dataclass(frozen=True)
class Swing:
    game: str
    if_home: str            # the side credited, and the average finish then
    if_away: str
    finish_if_home: float
    finish_if_away: float

    @property
    def size(self) -> float:
        return abs(self.finish_if_home - self.finish_if_away)


@dataclass(frozen=True)
class Report:
    coach: str
    basis: str
    sims: int
    field_size: int
    expected_score: float
    expected_finish: float
    first: float                    # finished first, ties included
    first_alone: float
    finishes: tuple[float, ...]     # chance of each place, 1st first
    best_finish: int
    best_score: int
    best_chance: float              # how often the best finish happened
    worst_finish: int
    worst_score: int
    worst_chance: float
    typical_range: tuple[int, int]  # 10th to 90th percentile finish
    leverage: Swing | None
    swings: tuple[Swing, ...] = field(default_factory=tuple)


@dataclass
class Simulation:
    games: list[ChaosGame]
    coaches: list[Coach]
    home: np.ndarray        # (sims, games) True when home is credited
    scores: np.ndarray      # (sims, coaches)
    places: np.ndarray      # (sims, coaches) 1 = first; ties share the best place

    @property
    def sims(self) -> int:
        return int(self.home.shape[0])

    def index_of(self, name: str) -> int:
        wanted = _plain(name)
        for i, c in enumerate(self.coaches):
            if _plain(c.name) == wanted:
                return i
        raise KeyError(name)


# ---- the engine ---------------------------------------------------------------
def simulate(games: list[ChaosGame], coaches: list[Coach], sims: int = SIMULATIONS,
             seed: int = SEED) -> Simulation:
    """Play the week `sims` times. The same seed always plays the same weeks."""
    rng = np.random.default_rng(seed)
    n = len(games)
    means = np.array([g.mean for g in games], dtype=float)
    margins = rng.normal(means, MARGIN_SD, size=(sims, n))
    home = np.empty((sims, n), dtype=bool)
    for j, g in enumerate(games):
        if g.line is None:
            home[:, j] = margins[:, j] > 0
        else:
            fav = margins[:, j] if g.line_fav_home else -margins[:, j]
            covered = fav >= _need(g.line) - 0.5
            home[:, j] = covered if g.line_fav_home else ~covered
    fav_home = np.array([g.favourite_is_home for g in games], dtype=bool)

    scores = np.zeros((sims, len(coaches)), dtype=np.int16)
    for i, coach in enumerate(coaches):
        if coach.card is not None:
            card = list(coach.card)[:n] + [None] * max(0, n - len(coach.card))
            picked = np.array([c is not None for c in card], dtype=bool)
            side = np.array([bool(c) for c in card], dtype=bool)
            right = (home == side) & picked
        else:
            on_fav = rng.random((sims, n)) < coach.fav_rate
            right = home == np.where(on_fav, fav_home, ~fav_home)
        scores[:, i] = right.sum(axis=1)

    # place = 1 + coaches strictly ahead
    places = (1 + (scores[:, :, None] < scores[:, None, :]).sum(axis=2)).astype(np.int16)
    return Simulation(list(games), list(coaches), home, scores, places)


def report(sim: Simulation, name: str) -> Report:
    """Everything the panel says about one coach."""
    i = sim.index_of(name)
    score, place = sim.scores[:, i].astype(int), sim.places[:, i].astype(int)
    field_size = len(sim.coaches)
    finishes = np.bincount(place, minlength=field_size + 1)[1:field_size + 1] / sim.sims
    others = np.delete(sim.scores, i, axis=1)
    alone = float(np.mean(score > others.max(axis=1))) if others.size else 1.0

    best, worst = int(place.min()), int(place.max())
    swings = []
    for j, g in enumerate(sim.games):
        h = sim.home[:, j]
        if h.all() or (~h).all():
            continue
        on_home, on_away = float(place[h].mean()), float(place[~h].mean())
        swings.append(Swing(
            game=g.label, if_home=g.home, if_away=g.away,
            finish_if_home=on_home, finish_if_away=on_away,
        ))
    swings.sort(key=lambda s: -s.size)
    return Report(
        coach=sim.coaches[i].name,
        basis=sim.coaches[i].basis_text,
        sims=sim.sims,
        field_size=field_size,
        expected_score=float(score.mean()),
        expected_finish=float(place.mean()),
        first=float(finishes[0]),
        first_alone=alone,
        finishes=tuple(float(f) for f in finishes),
        best_finish=best,
        best_score=int(score[place == best].max()),
        best_chance=float(np.mean(place == best)),
        worst_finish=worst,
        worst_score=int(score[place == worst].min()),
        worst_chance=float(np.mean(place == worst)),
        typical_range=(int(np.percentile(place, 10)), int(np.percentile(place, 90))),
        leverage=swings[0] if swings else None,
        swings=tuple(swings),
    )


# ---- gathering the week -------------------------------------------------------
def build(season, week: int) -> tuple[list[ChaosGame], list[Coach], list[str]]:
    """The week's games (market odds only) and every coach, plus notes on gaps.

    Reads the stored predictions file and fetched lines (no network), this
    week's pick sheet if it is in, and every earlier sheet for the habits.
    """
    from ..model import predictions
    from ..models import same_team
    from . import picks

    notes: list[str] = []
    forecasts, _ = predictions.load(week)
    found = season.weeks.get(week) if season is not None else None
    slate = sorted(found.games, key=lambda g: g.index) if found and found.games else \
        predictions.slate_from(forecasts)
    match = predictions.match_games(slate, forecasts)

    games: list[ChaosGame] = []
    for g in slate:
        f = match.by_game.get(g.index)
        margin = predictions.home_margin(g, f, f.market) if f is not None else None
        if margin is None:
            notes.append(f"{g.label}: no market line stored - left out")
            continue
        win = None
        if f.market_win is not None:
            win = f.market_win if predictions.team_code(g.home) == f.home_code else 1 - f.market_win
        games.append(ChaosGame(
            label=g.label, home=predictions.display_team(g.home),
            away=predictions.display_team(g.away), home_margin=float(margin),
            home_win=win, line=g.line,
            line_fav_home=same_team(g.line_favourite, g.home) if g.line is not None else True,
        ))

    try:
        sheets = picks.load_all()
    except Exception:  # a damaged store must not stop the simulator
        sheets = {}
    this = sheets.get(week)
    habits = _habits({w: s for w, s in sheets.items() if w < week})

    names = [p.display for p in (getattr(season, "players", None) or {}).values()]
    if this is not None:
        known = {_plain(n) for n in names}
        names += [c for c in this.coaches if _plain(c) not in known]
    if not names:
        names = ["Phelpy"]

    coaches = []
    for name in names:
        card = _sheet_card(this, name, slate, games) if this is not None else None
        fav, seen = habits.get(_plain(name), (0, 0))
        if card is not None:
            coaches.append(Coach(name, BASIS_SHEET, card=card))
        elif seen >= MIN_HISTORY:
            rate = (fav + POOL_USUAL * SHRINK) / (seen + SHRINK)
            coaches.append(Coach(name, BASIS_HISTORY, fav_rate=rate, picks_seen=seen))
        else:
            coaches.append(Coach(name, BASIS_FAVOURITES, fav_rate=1.0, picks_seen=seen))
    return games, coaches, notes


def _sheet_card(sheet, name: str, slate, games: list[ChaosGame]):
    from ..model import predictions

    wanted = _plain(name)
    by_label = {g.label: g for g in slate}
    card, any_pick = [], False
    for cg in games:
        g = by_label.get(cg.label)
        row = sheet.game_for(g.away, g.home) if g is not None else None
        pick = None
        if row is not None:
            for coach, team in row.picks.items():
                if _plain(coach) == wanted:
                    code = predictions.team_code(team)
                    if code == predictions.team_code(g.home):
                        pick = True
                    elif code == predictions.team_code(g.away):
                        pick = False
        any_pick = any_pick or pick is not None
        card.append(pick)
    return tuple(card) if any_pick else None


def _habits(sheets: dict) -> dict[str, tuple[int, int]]:
    """coach -> (picks on the market favourite, picks counted) over past sheets.

    The favourite is the market's where that week's line is stored, else the
    side most of the pool took.
    """
    from ..model import predictions

    out: dict[str, list[int]] = {}
    for week, sheet in sheets.items():
        try:
            forecasts, _ = predictions.load(week)
        except Exception:
            forecasts = []
        by_pair = {frozenset((f.home_code, f.road_code)): f for f in forecasts if f.market is not None}
        for row in sheet.games:
            home, away = predictions.team_code(row.home), predictions.team_code(row.away)
            f = by_pair.get(frozenset((home, away)))
            if f is not None and f.market:
                fav = f.home_code if f.market > 0 else f.road_code
            else:
                h, a = row.share_on(row.home) or 0, row.share_on(row.away) or 0
                if h == a:
                    continue
                fav = home if h > a else away
            for coach, team in row.picks.items():
                code = predictions.team_code(team)
                if code not in (home, away):
                    continue
                tally = out.setdefault(_plain(coach), [0, 0])
                tally[0] += code == fav
                tally[1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


# ---- small helpers ------------------------------------------------------------
def _need(line: float) -> int:
    return math.ceil(line - 1e-9)


def _cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _ppf(p: float) -> float:
    """Inverse normal CDF by bisection - accurate enough and dependency-free."""
    lo, hi = -8.0, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _plain(text: object) -> str:
    return " ".join(str(text or "").split()).casefold()


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
