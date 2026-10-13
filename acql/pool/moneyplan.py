"""The card that makes the most money under this pool's own rule.

The rule, from the workbook's formulas: every coach owes the week's best
card a dollar for every game they finish behind it, and the best card - or
the cards tied for best, sharing it - collects the lot. Big Loser points are
part of the score both ways.

That rule is lopsided. Finishing first collects from all 34 other coaches,
so being a game further ahead of the pack when you win is worth about $34;
finishing behind costs only the dollar a game you are short. A card that is
better than the pool on average - which a card built from the betting lines
is - earns more by being *different* from the pool than by being a little
more likely to score one more game. The Big Loser picks are where that is
cheapest: this pool puts two thirds of its cards on the same two or three
teams, and a team almost as likely to be blown out that nobody holds costs a
few points of chance and buys a lot of difference.

So this plans the whole card - the side in every game and the three Big
Losers - for the most money over thousands of simulated weeks:

    the results   each game's result is drawn from its chance; a Big Loser
                  only happens when that team also lost the game, so the two
                  can never contradict each other
    the field     34 coaches, each taking a side with the share of the pool
                  expected on it and holding each Big Loser with the share
                  expected on that team. Checked on this pool's real sheets:
                  two coaches agree on 70.2% of games, where coaches picking
                  independently at those shares would agree on 71.0% - so
                  independent coaches are a fair picture of it
    the money     given the results, every other coach's score has an exact
                  distribution, so the money a score of mine would make is
                  worked out exactly rather than by drawing 34 cards - that
                  takes the noise of the imaginary field out of the choice

It starts from the likeliest side of every game and the three likeliest Big
Losers, then makes whichever single change - one side turned over, or one
Big Loser swapped - adds the most money, until nothing adds at least
MIN_GAIN. The card is chosen on one set of simulated weeks and priced on
another, so the figures quoted are not flattered by the choosing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

SIMULATIONS = 20_000
SEED = 2026
#: A change has to add at least this many dollars a week to be made. Smaller
#: is simulation noise, and a card that changed with the noise would change
#: every time the page was opened.
MIN_GAIN = 0.02
#: Big Losers considered for a swap: the likeliest this many.
BL_CANDIDATES = 12
BIG_LOSER_PICKS = 3
COACHES = 34


@dataclass(frozen=True)
class Game:
    """One game as the planner sees it."""

    label: str
    pick: str                 # the likelier side
    other: str
    chance: float             # probability `pick` is credited
    crowd: float              # share of the pool expected on `pick`
    #: team -> (chance it loses by 15 or more, share of the pool holding it
    #: as a Big Loser). Either or both sides; missing means "not a candidate".
    losers: tuple[tuple[str, float, float], ...] = ()


@dataclass(frozen=True)
class Card:
    take: tuple[str, ...]             # the side in each game
    losers: tuple[str, ...]           # the three Big Losers
    money: float                      # average dollars a week, owed weeks counted
    first: float                      # chance of the week's best score (ties shared)
    hits: float                       # expected games right
    loser_points: float               # expected Big Loser points

    @property
    def points(self) -> float:
        return self.hits + self.loser_points


@dataclass(frozen=True)
class Plan:
    best: Card                        # the card to play
    plain: Card                       # likeliest side everywhere, likeliest Big Losers
    flipped: tuple[int, ...]          # games where `best` isn't the likelier side
    swapped: tuple[str, ...]          # Big Losers in `best` that aren't the likeliest three
    coaches: int
    simulations: int
    field_known: bool
    #: For each game, the money with that one game turned the other way and
    #: the rest of the best card unchanged.
    flip_money: tuple[float, ...] = ()

    @property
    def gain(self) -> float:
        return self.best.money - self.plain.money


# ---- the field, exactly, given one set of results ---------------------------------
def field_tables(coins: np.ndarray, coaches: int = COACHES) -> tuple[np.ndarray, np.ndarray]:
    """Money and first-place share for each score I might have.

    `coins` is (sims, n): for each simulated week, the chance an ordinary
    coach gains a point from each source - a game (the share of the pool on
    the side that came in) or a Big Loser (the share holding a team that was
    blown out; zero for the rest). A coach's score is the sum of those coins,
    so its distribution is exact, and so is the money for every score of mine.
    Returns two (sims, n + 1) tables indexed by my score.
    """
    sims, n = coins.shape
    dist = np.zeros((sims, n + 1))
    dist[:, 0] = 1.0
    for j in range(n):
        # Only the weeks where this coin can land move, and only the scores
        # reachable so far: a Big Loser's coin is zero in nine weeks in ten,
        # and after j coins nobody has more than j points. The rest would be
        # multiplied by one and have nothing added - so they are left alone.
        q = coins[:, j]
        rows = np.flatnonzero(q)
        if not rows.size:
            continue
        every = rows.size == sims
        part = dist[:, :j + 2] if every else dist[rows, :j + 2]
        q = q[:, None] if every else q[rows, None]
        nxt = part * (1 - q)
        nxt[:, 1:] += part[:, :-1] * q
        if every:
            dist[:, :j + 2] = nxt
        else:
            dist[rows, :j + 2] = nxt
    F = np.cumsum(dist, axis=1)                                   # P(score <= k)
    F = np.minimum(F, 1.0)
    FN = F ** coaches
    # What I owe with score m: the expected gap to the best other card,
    # sum over k >= m of P(best other > k).
    owe = np.zeros((sims, n + 1))
    owe[:, :n] = np.cumsum((1 - FN)[:, :n][:, ::-1], axis=1)[:, ::-1]
    # What I collect with score m, given nobody beats it: every coach below
    # pays their gap, shared with whoever ties. With T ties among N others,
    # T ~ Binomial(N, p), p = P(score = m | score <= m), the other N - T sit
    # below at an average gap mu, and my share is (N - T) mu / (T + 1):
    #   E[(N - T) / (T + 1)] = (1 - (1 - p)^(N + 1)) / p - 1.
    below = np.concatenate([np.zeros((sims, 1)), F[:, :-1]], axis=1)          # P(score <= m-1)
    gap_sum = np.concatenate([np.zeros((sims, 1)), np.cumsum(F[:, :-1], axis=1)], axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        mu = np.where(below > 0, gap_sum / np.maximum(below, 1e-300), 0.0)
        p = np.where(F > 0, dist / np.maximum(F, 1e-300), 0.0)
        tiny = p < 1e-9
        safe = np.where(tiny, 1.0, p)
        some = 1 - (1 - p) ** (coaches + 1)                     # somebody else lands on this score
        share = np.where(tiny, coaches, some / safe - 1)
        first = np.where(tiny, 1.0, some / ((coaches + 1) * safe))
    collect = FN * mu * share
    return collect - owe, FN * first


# ---- simulated weeks ---------------------------------------------------------------
class Weeks:
    """One batch of simulated weeks and the money every score makes in them."""

    def __init__(self, games: tuple[Game, ...], sims: int, seed: int,
                 coaches: int = COACHES, field_cards=None) -> None:
        rng = np.random.default_rng(seed)
        chance = np.array([g.chance for g in games])
        crowd = np.array([g.crowd for g in games])
        n = len(games)
        # 1 where the other side was credited
        self.results = (rng.random((sims, n)) >= chance).astype(np.int8)
        self.teams: list[str] = []
        hits, shares = [], []
        for j, g in enumerate(games):
            for team, blowout, held in g.losers:
                is_pick = team == g.pick
                lost = self.results[:, j] == (1 if is_pick else 0)
                p_lost = (1 - g.chance) if is_pick else g.chance
                given = min(1.0, blowout / p_lost) if p_lost > 1e-9 else 0.0
                hits.append(lost & (rng.random(sims) < given))
                shares.append(held)
                self.teams.append(team)
        self.hits = np.stack(hits, axis=1).astype(np.int8) if hits else np.zeros((sims, 0), np.int8)
        self.index = {t: i for i, t in enumerate(self.teams)}
        self.rows = np.arange(sims)
        self.coaches = coaches
        if field_cards is None:
            game_coins = np.where(self.results == 0, crowd, 1 - crowd)
            loser_coins = self.hits * np.array(shares)[None, :] if shares else np.zeros((sims, 0))
            self.money_table, self.first_table = field_tables(
                np.concatenate([game_coins, loser_coins], axis=1), coaches)
            self.known = None
        else:
            # The real field: every coach's own card, the same in every week.
            sides, losers = field_cards
            self.known = (np.asarray(sides, dtype=np.int8), np.asarray(losers, dtype=np.int8))

    def score(self, bits: np.ndarray, losers: tuple[int, ...]) -> np.ndarray:
        mine = (bits[None, :] == self.results).sum(axis=1)
        for i in losers:
            mine = mine + self.hits[:, i]
        return mine

    def value(self, bits: np.ndarray, losers: tuple[int, ...]) -> tuple[float, float]:
        """(average money, chance of the best score) for one card."""
        mine = self.score(bits, losers)
        if self.known is None:
            return (float(self.money_table[self.rows, mine].mean()),
                    float(self.first_table[self.rows, mine].mean()))
        sides, held = self.known
        others = (sides[None, :, :] == self.results[:, None, :]).sum(axis=2)
        if held.size:
            others = others + (held[None, :, :] * self.hits[:, None, :]).sum(axis=2)
        best = others.max(axis=1)
        ties = (others == mine[:, None]).sum(axis=1)
        pot = np.clip(mine[:, None] - others, 0, None).sum(axis=1)
        collect = np.where(mine > best, pot, np.where(mine == best, pot / (ties + 1), 0.0))
        owe = np.where(mine < best, best - mine, 0)
        share = np.where(mine > best, 1.0, np.where(mine == best, 1.0 / (ties + 1), 0.0))
        return float((collect - owe).mean()), float(share.mean())


def _card(games, weeks: Weeks, bits: np.ndarray, losers: tuple[int, ...]) -> Card:
    money, first = weeks.value(bits, losers)
    hits = float((bits[None, :] == weeks.results).sum(axis=1).mean())
    points = float(sum(weeks.hits[:, i].mean() for i in losers))
    return Card(
        take=tuple(g.other if b else g.pick for g, b in zip(games, bits)),
        losers=tuple(weeks.teams[i] for i in losers),
        money=money, first=first, hits=hits, loser_points=points,
    )


def plan(games: list[Game], *, sims: int = SIMULATIONS, seed: int = SEED,
         coaches: int = COACHES, field_cards=None, allow_flips: bool = True,
         allow_swaps: bool = True) -> Plan | None:
    """The most money a card can expect this week, and the card.

    `field_cards` is (sides, losers) from the real pick sheet: sides is one
    row per coach, 0 where they have `pick`; losers one row per coach over
    the Big Loser teams in the order the games list them, 1 where held.
    """
    if not games:
        return None
    frozen = None
    if field_cards is not None:
        frozen = (tuple(tuple(int(v) for v in row) for row in field_cards[0]),
                  tuple(tuple(int(v) for v in row) for row in field_cards[1]))
    return _plan(tuple(games), sims, seed, coaches, frozen, allow_flips, allow_swaps)


@lru_cache(maxsize=16)
def _plan(games, sims, seed, coaches, frozen, allow_flips, allow_swaps) -> Plan | None:
    search = Weeks(games, sims, seed, coaches, frozen)
    check = Weeks(games, sims, seed + 1, coaches, frozen)
    chances = {t: b for g in games for t, b, _ in g.losers}
    ranked = sorted(search.teams, key=lambda t: (-chances[t], t))
    plain_losers = tuple(search.index[t] for t in ranked[:BIG_LOSER_PICKS])
    pool = [search.index[t] for t in ranked[:BL_CANDIDATES]]

    bits = np.zeros(len(games), dtype=np.int8)
    losers = plain_losers
    best = search.value(bits, losers)[0]
    for _ in range(len(games) + BIG_LOSER_PICKS * 2):
        trials = []
        if allow_flips:
            for j in range(len(games)):
                t = bits.copy()
                t[j] ^= 1
                trials.append((search.value(t, losers)[0], "flip", j))
        if allow_swaps:
            for slot in range(len(losers)):
                for cand in pool:
                    if cand in losers:
                        continue
                    trial = tuple(sorted(losers[:slot] + (cand,) + losers[slot + 1:]))
                    trials.append((search.value(bits, trial)[0], "swap", trial))
        if not trials:
            break
        value, kind, what = max(trials, key=lambda t: t[0])
        if value < best + MIN_GAIN:
            break
        if kind == "flip":
            bits[what] ^= 1
        else:
            losers = what
        best = value

    chosen = _card(games, check, bits, losers)
    plain = _card(games, check, np.zeros(len(games), dtype=np.int8), plain_losers)
    flip_money = []
    for j in range(len(games)):
        t = bits.copy()
        t[j] ^= 1
        flip_money.append(check.value(t, losers)[0])
    return Plan(
        best=chosen, plain=plain,
        flipped=tuple(int(j) for j in np.flatnonzero(bits)),
        swapped=tuple(check.teams[i] for i in losers if i not in plain_losers),
        coaches=coaches if frozen is None else len(frozen[0]),
        simulations=sims, field_known=frozen is not None,
        flip_money=tuple(flip_money),
    )


def card_value(games: list[Game], take: list[str], losers: list[str], *,
               sims: int = SIMULATIONS, seed: int = SEED, coaches: int = COACHES) -> Card | None:
    """Money and chances for a card chosen some other way (the coach's own, say)."""
    if not games or len(take) != len(games):
        return None
    check = Weeks(tuple(games), sims, seed + 1, coaches)
    bits = np.array([0 if t == g.pick else 1 for t, g in zip(take, games)], dtype=np.int8)
    held = tuple(check.index[t] for t in losers if t in check.index)
    return _card(games, check, bits, held)


# ---- how the pool spreads its Big Loser picks -------------------------------------
#: Fitted to this pool's own sheets - 2026 weeks 1 and 2, refitted with 2025
#: week 17 added (327 coaches' picks; the best fit moved from 3.0 to 3.25,
#: which changes nothing that matters): the share of cards holding a team
#: goes with its chance of a blowout, sharpened by this power of the odds,
#: and no team gets past the ceiling - the pool's favourite Big Loser sits on
#: 54-82% of cards, never all of them. Reputation counts too (the Browns,
#: Jets and Titans are held well past their chances), which this leaves out.
#: Fitted again on 2026 weeks 1-5 (518 picks) when a Big Loser's chance
#: became history's number (analytics.rout_chance): 2.5 fits the sheets best
#: on those chances, as 2.75-3.0 did on the margin curve's.
LOSER_SHARPNESS = 2.5
LOSER_CEILING = 0.70


def loser_shares(chances: dict[str, float], picks: int = BIG_LOSER_PICKS,
                 sharpness: float = LOSER_SHARPNESS,
                 ceiling: float = LOSER_CEILING) -> dict[str, float]:
    """Team -> share of the pool expected to hold it as a Big Loser."""
    if not chances:
        return {}
    teams = list(chances)
    x = np.array([math.log(max(1e-6, c) / max(1e-6, 1 - c)) for c in chances.values()])
    w = np.exp(sharpness * (x - x.max()))
    s = picks * w / w.sum()
    for _ in range(30):                      # nobody's favourite is on every card
        over = s > ceiling + 1e-12
        if not over.any():
            break
        extra = float((s[over] - ceiling).sum())
        s[over] = ceiling
        rest = ~over
        if s[rest].sum() > 0:
            s[rest] += extra * s[rest] / s[rest].sum()
    return {t: float(v) for t, v in zip(teams, s)}
