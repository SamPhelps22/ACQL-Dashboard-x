"""The Model Lab: every way of pricing a game, on the same games, side by side.

Deadeye is one recipe - the betting line, nudged by the published computer
models. There are others: the line alone, the models alone, the dashboard's
own ratings (teamstrength.py), blends of them. This runs each one over every
graded game of the season the way it would have been run at the time - each
week priced with only what was known going into it - and scores them the
same way: how often the side it favoured was credited under the pool's
rules, and how good its chances were (Brier score and log loss, where lower
is better and a coin flip scores 0.250 and 0.693).

A challenger replaces Deadeye only when it has earned it on games it had not
seen: enough of them, and clearly better. One good month is not that - the
NFL is noisy enough that the best recipe loses to a worse one over sixty
games about as often as not. So the lab shows the table and says, plainly,
whether anything has earned the switch. Nothing here changes Deadeye.

No Qt here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import contenders, luck, predictions, pricing, results, teamstrength
from .models import Season
from .predictions import team_code
from .version import MODEL_NAME

#: Games a challenger and Deadeye must both have priced before a switch is considered.
ENOUGH_GAMES = 150
#: ...and how much lower its log loss has to be on them.
CLEARLY_BETTER = 0.010
#: How much of the gap between the line and the dashboard's own ratings a blend takes.
RATINGS_SHARE = 0.25
#: "Line + line movement" follows a move this much further than the line already has.
MOVE_SHARE = 0.5
#: Games two recipes must have split - one right, the other wrong - before
#: the split is tested against luck at all.
SPLITS_NEEDED = 6
#: The chance of a split at least this lopsided by luck alone, under which it is called real.
REAL = 0.05
#: Calibration: the chance each recipe gave its own side, in these bands.
BANDS = ((0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.80), (0.80, 1.01))
LINE, MOVES = "Betting line only", "Line + line movement"
#: What a recipe goes on: the betting market, football of its own, or both.
MARKET, FOOTBALL, HYBRID = "Market", "Football", "Hybrid"

#: What has changed in Deadeye, newest first - the record a version is judged against.
VERSIONS = (
    ("2.16", "Oct 2026",
     "The newest number wins (a typed spread no longer overrules a fresher line); odds fetched "
     "during a game are ignored; the card locks at the pool's Thursday deadline; straight-up games "
     "are priced off the moneyline; a game's over/under widens or narrows its spread of results; "
     "the three Big Losers are kept with the card."),
    ("2.15", "Oct 2026",
     "The betting line, nudged by the published computer models - by a share fitted on the weeks "
     "before, smaller when the models disagree among themselves."),
)


@dataclass(frozen=True)
class Play:
    """One game as one recipe had it."""

    week: int
    index: int
    chance: float           # it gave the home side of being credited
    hit: bool               # its side was credited
    loss: float             # log loss
    winner: bool | None     # it had the game's winner outright (None: no score kept, a tie, or no lean)
    lined: bool             # the pool put a line on the game


@dataclass
class Entry:
    name: str
    about: str
    games: int = 0
    right: int = 0
    brier: float = 0.0
    logloss: float = 0.0
    #: against Deadeye, on the games both priced
    shared: int = 0
    shared_right: int = 0
    deadeye_right: int = 0
    shared_logloss: float = 0.0
    deadeye_logloss: float = 0.0
    #: how far the final margins landed from the ones it expected (points), over `scored` games
    miss: float = 0.0
    scored: int = 0
    incumbent: bool = False
    kind: str = ""                  # MARKET, FOOTBALL or HYBRID
    by_week: dict[int, list[int]] = field(default_factory=dict)
    #: every game it priced, by (week, game) - what any two recipes are compared on
    log: dict[tuple[int, int], Play] = field(default_factory=dict)
    #: the games it could not price, by why
    missing: dict[str, int] = field(default_factory=dict)

    # ---- picking the winner, and covering the pool's line: two different questions
    @property
    def winners(self) -> tuple[int, int]:
        """(games it had the outright winner of, games that can be said of)."""
        known = [play for play in self.log.values() if play.winner is not None]
        return sum(play.winner for play in known), len(known)

    @property
    def lined(self) -> tuple[int, int]:
        """(pool-line games its side was credited in, pool-line games it priced)."""
        on = [play for play in self.log.values() if play.lined]
        return sum(play.hit for play in on), len(on)

    def on(self, keys) -> tuple[int, int]:
        """(right, games) over a given set of games."""
        plays = [self.log[k] for k in keys if k in self.log]
        return sum(play.hit for play in plays), len(plays)

    @property
    def rate(self) -> float:
        return self.right / self.games if self.games else 0.0

    @property
    def mean_brier(self) -> float:
        return self.brier / self.games if self.games else 0.0

    @property
    def mean_logloss(self) -> float:
        return self.logloss / self.games if self.games else 0.0

    @property
    def mean_miss(self) -> float | None:
        return self.miss / self.scored if self.scored else None

    @property
    def edge(self) -> float | None:
        """Log loss a game better (+) or worse (-) than Deadeye on the same games."""
        if self.incumbent or not self.shared:
            return None
        return (self.deadeye_logloss - self.shared_logloss) / self.shared

    @property
    def verdict(self) -> str:
        if self.incumbent:
            return "in service"
        if not self.shared:
            return "no games in common yet"
        edge = self.edge or 0.0
        if self.shared < ENOUGH_GAMES:
            lean = "ahead" if edge > 0 else "behind" if edge < 0 else "level"
            return f"{lean}, {self.shared} of {ENOUGH_GAMES} games"
        if edge >= CLEARLY_BETTER and self.shared_right >= self.deadeye_right:
            return "has earned the switch"
        return "not better than Deadeye"


@dataclass(frozen=True)
class Pair:
    """Two recipes on the games both priced."""

    games: int = 0
    both: int = 0           # both right
    neither: int = 0
    first: int = 0          # only the first was right
    second: int = 0         # only the second
    edge: float = 0.0       # log loss a game the first is better by (negative: worse)

    @property
    def split(self) -> int:
        """Games they disagreed about the result of - the only ones that tell them apart."""
        return self.first + self.second

    @property
    def net(self) -> int:
        return self.first - self.second

    @property
    def luck(self) -> float | None:
        """The chance of a split at least this lopsided if the two were equally
        good (McNemar's exact test). None with too few split games to ask."""
        if self.split < SPLITS_NEEDED:
            return None
        low = min(self.first, self.second)
        tail = sum(math.comb(self.split, k) for k in range(low + 1)) / 2 ** self.split
        return min(1.0, 2 * tail)

    @property
    def reading(self) -> str:
        if not self.games:
            return "no games in common"
        if not self.split:
            return "never split"
        if self.luck is None:
            return f"too few split games ({self.split})"
        if self.luck < REAL and self.net:
            return f"a real gap - {self.luck:.0%} by chance"
        return f"within luck - {self.luck:.0%} by chance"


def pair(first: Entry, second: Entry) -> Pair:
    """`first` against `second`, game for game, on the games both priced."""
    keys = [k for k in first.log if k in second.log]
    if not keys:
        return Pair()
    a, b = [first.log[k] for k in keys], [second.log[k] for k in keys]
    return Pair(
        games=len(keys),
        both=sum(x.hit and y.hit for x, y in zip(a, b)),
        neither=sum(not x.hit and not y.hit for x, y in zip(a, b)),
        first=sum(x.hit and not y.hit for x, y in zip(a, b)),
        second=sum(y.hit and not x.hit for x, y in zip(a, b)),
        edge=(sum(y.loss for y in b) - sum(x.loss for x in a)) / len(keys),
    )


@dataclass(frozen=True)
class Band:
    """The picks a recipe gave a chance in one band, and how they came out."""

    low: float
    high: float
    picks: int = 0
    said: float = 0.0       # the average chance it gave them
    came: float = 0.0       # the share that came in

    @property
    def label(self) -> str:
        return f"{self.low:.0%} and up" if self.high > 1 else f"{self.low:.0%}-{self.high:.0%}"


def calibration(entry: Entry) -> list[Band]:
    """A recipe's picks by how sure it was of its own side, against how often they came in."""
    out = []
    for low, high in BANDS:
        sure = [(max(play.chance, 1 - play.chance), play.hit) for play in entry.log.values()]
        inside = [(chance, hit) for chance, hit in sure if low <= chance < high]
        out.append(Band(low, high, len(inside),
                        sum(c for c, _ in inside) / len(inside) if inside else 0.0,
                        sum(h for _, h in inside) / len(inside) if inside else 0.0))
    return out


@dataclass(frozen=True)
class Lab:
    entries: list[Entry]
    games: int
    weeks: tuple[int, ...]
    ratings_games: int = 0          # results the dashboard's own ratings rest on
    long_run: dict | None = None    # the ratings' record over 2011-2025 (backtest)
    decided: int = 0                # graded games in all, priced or not

    def entry(self, name: str) -> Entry | None:
        return next((e for e in self.entries if e.name == name), None)

    @property
    def service(self) -> Entry | None:
        return next((e for e in self.entries if e.incumbent), None)

    def best_of_each_kind(self) -> list[tuple[str, Entry, int, int]]:
        """(kind, its best recipe, right, games) on the games every recipe priced -
        the market, football alone and the two together, like for like."""
        common = self.common
        out = []
        for kind in (MARKET, FOOTBALL, HYBRID):
            rivals = [e for e in self.entries if e.kind == kind]
            if not rivals or not common:
                continue
            best = min(rivals, key=lambda e: (sum(e.log[k].loss for k in common), e.name))
            out.append((kind, best, *best.on(common)))
        return out

    @property
    def front_runner(self) -> Entry | None:
        """The challenger furthest ahead of the one in service on log loss -
        among those that priced nearly all the same games, so that a good run
        over half the season is not set against a whole one. Falls back to
        any with thirty games in common. None when nothing is ahead."""
        service = self.service
        if service is None:
            return None
        rivals = [e for e in self.entries if not e.incumbent and e.edge is not None]
        full = [e for e in rivals if e.shared >= 0.8 * service.games]
        pool = [e for e in (full or [e for e in rivals if e.shared >= 30]) if (e.edge or 0) > 0]
        return max(pool, key=lambda e: e.edge, default=None)

    @property
    def common(self) -> list[tuple[int, int]]:
        """The games every recipe priced - the only ones all of them can be compared on."""
        if not self.entries:
            return []
        keys = set(self.entries[0].log)
        for e in self.entries[1:]:
            keys &= set(e.log)
        return sorted(keys)

    def ablation(self) -> list[tuple[str, str, str, Pair]]:
        """What each ingredient adds: (the ingredient, the recipe with it, the
        recipe without, the two set side by side on the games both priced)."""
        steps = (
            ("The computer models", MODEL_NAME, LINE),
            ("The dashboard's own ratings", "Line + own ratings", LINE),
            ("Which way the line moved", MOVES, LINE),
            ("Own ratings, on top of the models", f"{MODEL_NAME} + own ratings", MODEL_NAME),
            ("The week's news since the line opened", LINE, "Opening line only"),
        )
        out = []
        for what, with_it, without in steps:
            a, b = self.entry(with_it), self.entry(without)
            if a is not None and b is not None:
                out.append((what, with_it, without, pair(a, b)))
        return out

    @property
    def challenger(self) -> Entry | None:
        """A recipe that has earned Deadeye's place, if any has."""
        return next((e for e in self.entries if e.verdict == "has earned the switch"), None)


def _blend(a: float | None, b: float | None, share: float) -> float | None:
    if a is None or b is None:
        return None
    return a + share * (b - a)


def run(season: Season) -> Lab:
    """Every recipe over every graded game of the season, each week priced
    with what was known going into it."""
    year = results.season_year(season)
    recipes = [
        (MODEL_NAME, "The card you are given. It starts from the betting line and nudges it toward the middle of "
                     "the published computer models - less when those models disagree with each other."),
        (LINE, "The sportsbooks' number and nothing else. It is the bar every other recipe has to clear."),
        ("Computer models only", "The middle of the published computer models, ignoring the betting line. "
                                 "Only for weeks whose models file was kept."),
        ("Own ratings only", "The dashboard's own team ratings, built from every final score since 2011. "
                             "It never sees a betting line or anyone else's model."),
        ("Line + own ratings", f"The betting line, moved {RATINGS_SHARE:.0%} of the way toward what the own ratings expect."),
        (f"{MODEL_NAME} + own ratings", f"{MODEL_NAME}'s number with the same {RATINGS_SHARE:.0%} step toward the own "
                                        "ratings added on top. Closest to what a next version would be."),
        ("Opening line only", "Where the betting line first opened, before the week's injuries and money moved it."),
        (MOVES, f"The betting line, pushed {MOVE_SHARE:.0%} further in the direction it has already moved since it "
                "opened - a bet that a move keeps going."),
        (contenders.ANALYST, "A regression: a straight-line weighting of the own ratings and each team's last four "
                             "results. Taught on 2011 to last season; it has never seen a betting line."),
        (contenders.MACHINE, "Gradient-boosted trees: a few hundred small yes-or-no rules over the same inputs as "
                             "the Analyst. Taught on 2011 to last season; it has never seen a betting line."),
    ]
    kinds = {
        MODEL_NAME: HYBRID, LINE: MARKET, "Computer models only": FOOTBALL, "Own ratings only": FOOTBALL,
        "Line + own ratings": HYBRID, f"{MODEL_NAME} + own ratings": HYBRID, "Opening line only": MARKET,
        MOVES: MARKET, contenders.ANALYST: FOOTBALL, contenders.MACHINE: FOOTBALL,
    }
    entries = {name: Entry(name, about, incumbent=(name == MODEL_NAME), kind=kinds.get(name, ""))
               for name, about in recipes}
    weeks, total, decided_in_all = set(), 0, 0
    for number in sorted(season.weeks):
        week = season.weeks[number]
        games = sorted(week.games, key=lambda g: g.index)
        decided = [g for g in games if g.played and team_code(g.winner) in (team_code(g.home), team_code(g.away))]
        if not decided:
            continue
        ctx = pricing.context(season, number, games)
        prices = {p.game.index: p for p in pricing.price_week(season, number, games, ctx)}
        strength = teamstrength.before(season, number, year)
        decided_in_all += len(decided)
        for game in decided:
            f = ctx.forecasts.get(game.index)
            line = pricing.market_margin(game, f) if f is not None else None
            opening = (predictions.home_margin(game, f, f.opening)
                       if f is not None and f.opening is not None and f.market is not None else None)
            models = (predictions.home_margin(game, f, f.consensus)
                      if f is not None and f.consensus is not None and len(f.opinions) >= 3 else None)
            own = strength.margin(game.home, game.away)
            deadeye = prices[game.index].margin if game.index in prices else None
            try:
                analyst, machine = contenders.margins(season, number, game, year)
            except Exception:  # noqa: BLE001 - the lab stands without them
                analyst = machine = None
            actual = (float(game.home_points - game.away_points)
                      if game.home_points is not None and game.away_points is not None else None)
            margins = {
                MODEL_NAME: deadeye,
                "Betting line only": line,
                "Computer models only": models,
                "Own ratings only": own,
                "Line + own ratings": _blend(line, own, RATINGS_SHARE),
                f"{MODEL_NAME} + own ratings": (None if deadeye is None or line is None or own is None
                                                else deadeye + RATINGS_SHARE * (own - line)),
                "Opening line only": opening,
                MOVES: None if line is None or opening is None else line + MOVE_SHARE * (line - opening),
                contenders.ANALYST: analyst,
                contenders.MACHINE: machine,
            }
            # why a recipe has nothing to say about a game - the coverage audit
            no_file = "no predictions file was kept for the week"
            no_line = no_file if f is None else "no betting line was kept for the game"
            no_open = no_file if f is None else "no opening line was kept for the game"
            no_rate = "a team the ratings have not seen"
            why = {
                MODEL_NAME: no_line, LINE: no_line,
                "Computer models only": (
                    no_file if f is None else
                    "the computer models' file was not kept for the week - only the betting line"
                    if not f.opinions else "fewer than three computer models priced it"),
                "Own ratings only": no_rate, contenders.ANALYST: no_rate, contenders.MACHINE: no_rate,
                "Line + own ratings": no_line if line is None else no_rate,
                f"{MODEL_NAME} + own ratings": no_line if line is None or deadeye is None else no_rate,
                "Opening line only": no_open, MOVES: no_line if line is None else no_open,
            }
            for name, margin in margins.items():
                if margin is None:
                    entries[name].missing[why[name]] = entries[name].missing.get(why[name], 0) + 1
            home_credited = team_code(game.winner) == team_code(game.home)
            chances = {}
            for name, margin in margins.items():
                if margin is None:
                    continue
                p = luck.credited_chance(game, margin, game.home)
                if p is not None:
                    chances[name] = min(max(p, 0.01), 0.99)
            if chances:
                weeks.add(number)
                total += 1
            base = chances.get(MODEL_NAME)
            y = 1.0 if home_credited else 0.0
            for name, p in chances.items():
                e = entries[name]
                hit = (p > 0.5) == home_credited and p != 0.5
                loss = -(y * math.log(p) + (1 - y) * math.log(1 - p))
                e.games += 1
                e.right += hit
                e.brier += (p - y) ** 2
                e.logloss += loss
                if actual is not None:
                    e.miss += abs(actual - margins[name])
                    e.scored += 1
                had_winner = (None if actual is None or not actual or not margins[name]
                              else (margins[name] > 0) == (actual > 0))
                e.log[(number, game.index)] = Play(number, game.index, p, bool(hit), loss, had_winner,
                                                   game.line is not None and bool(game.line_favourite))
                tally = e.by_week.setdefault(number, [0, 0])
                tally[0] += hit
                tally[1] += 1
                if base is not None:
                    e.shared += 1
                    e.shared_right += hit
                    e.shared_logloss += loss
                    e.deadeye_right += (base > 0.5) == home_credited and base != 0.5
                    e.deadeye_logloss += -(y * math.log(base) + (1 - y) * math.log(1 - base))
    long_run = None
    try:
        from . import backtest
        kept = backtest.stored_results()
        proxy = getattr(kept, "raw", {}).get("proxy") if kept is not None else None
        if isinstance(proxy, dict):
            long_run = proxy
    except Exception:  # noqa: BLE001 - the lab stands without the long record
        long_run = None
    ratings_games = teamstrength.before(season, max(season.weeks, default=1), year).games if season.weeks else 0
    return Lab([e for e in entries.values() if e.games], total, tuple(sorted(weeks)), ratings_games, long_run,
               decided_in_all)
