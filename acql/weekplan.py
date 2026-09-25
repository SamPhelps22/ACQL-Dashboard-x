"""Choosing a whole card to finish first in the week - not just near the top.

Picking each game's likelier side maximises how many you get right, and it
reliably puts you in the top few. It almost never puts you *first*, because
most of the pool is holding nearly the same card: when the favourites come
in you tie with a crowd, and when they don't, so does everyone else. Measured
on a real week-3 slate against 34 simulated coaches:

    card                           wins the week   top five   games right
    likeliest side of every game        1.3%         33.6%       10.7
    this planner                     3.5 - 3.7%       ~22%         9.8

A fair share of 35 is 2.9%. The likely card wins well under half that; this
one wins about a quarter more than a fair share, and nearly three times as
often as the safe card - at the price of fewer top-five finishes, which pay
nothing. (Measured on 200,000 simulated weeks the card was not chosen on.)

    "If you have the best record for the week then you receive $1 per game
     per coach that your record differs from that coach."

Only first is paid, so first is what this aims at: the chance that no other
card scores more than yours, with a tie counted as your share of it.

The method is plain simulation. Play the week thousands of times; in each,
score a freshly drawn field of the other coaches' cards (or their real cards,
once the pick sheet is in) and a candidate card of your own. Start from the
likeliest card and turn over whichever single game most raises the chance of
finishing first, until nothing does. Every game it turns is one it can give a
reason for.

Two details keep the numbers honest:

* The field is drawn afresh in every simulated week. Drawing one imaginary
  field and planning against it - which an earlier version did - tunes the
  card to that one draw's quirks, and it won 3.1% instead of 3.7% when
  checked against fields it had not seen.
* The odds quoted are measured on a separate set of simulated weeks from the
  ones the card was chosen on. Choosing and scoring on the same weeks
  flatters the chosen card, because it was picked partly for luck.

Nothing in here knows about football. It takes a probability per game and a
picture of what everyone else has done, and it is equally happy with a real
pick sheet or with cards drawn from how the pool usually behaves.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

#: Weeks simulated to choose the card, and again to price it. Fewer than
#: about 20,000 and the choice starts to follow the noise: on the week-3
#: slate, 12,000 found cards winning 3.4-3.5%, 20,000 found 3.5-3.7%.
SIMULATIONS = 20_000
SEED = 2026          # fixed, so the same week always plans the same way
#: A flip has to raise the chance of finishing first by at least this much
#: to be kept. Smaller gains are simulation noise, and a card that changes
#: with the noise would change every time the page is opened.
MIN_GAIN = 0.0005


@dataclass(frozen=True)
class Choice:
    """One game as the planner sees it."""

    label: str
    pick: str            # the side the pick logic likes
    other: str           # the side it doesn't
    chance: float        # probability `pick` is the right side, 0..1
    crowd: float         # share of the pool expected on `pick`, 0..1


@dataclass(frozen=True)
class Plan:
    """A whole card, and how often it finishes first."""

    take: list[str]          # the side to take in each game, in order
    flipped: list[int]       # games where that isn't the likelier side
    win_odds: float          # chance of finishing first in the week (ties shared)
    payout: float            # average dollars, counting the weeks you don't win
    expected_hits: float     # how many games it expects to get right
    top_five: float          # chance of finishing in the top five
    plain_win_odds: float    # the same, for the card that just takes the likelier side
    plain_payout: float
    plain_hits: float
    plain_top_five: float
    coaches: int             # other coaches it was played against
    simulations: int
    field_known: bool        # True when the other cards came from the pick sheet
    #: For each game, the chance of finishing first with that one game taken
    #: the other way and the rest of the card unchanged. The gap to
    #: `win_odds` is what the side taken is worth to winning the week.
    flip_odds: tuple[float, ...] = ()

    def worth(self, game: int) -> float | None:
        """Points of week-winning chance this game's side is worth over the other."""
        if not 0 <= game < len(self.flip_odds):
            return None
        return self.win_odds - self.flip_odds[game]

    @property
    def fair_share(self) -> float:
        """What finishing first would be worth if every card were equal."""
        return 1 / (self.coaches + 1)

    @property
    def edge(self) -> float:
        """How many fair shares of the week this card wins (1.0 = average)."""
        return self.win_odds / self.fair_share if self.fair_share else 0.0


class _Week:
    """One batch of simulated weeks, and how a card fares in them."""

    def __init__(
        self,
        chance: np.ndarray,
        crowd: np.ndarray,
        cards: np.ndarray | None,
        coaches: int,
        sims: int,
        rng: np.random.Generator,
    ) -> None:
        games = len(chance)
        # 0 means "the pick side came in", 1 means the other side did, so a
        # card scores a game when its entry equals the result.
        # Single precision is plenty for a coin weighted to two decimals, and
        # half the time of double for the 11 million draws a field takes.
        self.results = (
            rng.random((sims, games), dtype=np.float32) >= chance.astype(np.float32)
        ).astype(np.int8)
        if cards is not None:
            # The real field is what it is: the same cards in every week.
            self.scores = (cards[None, :, :] == self.results[:, None, :]).sum(axis=2)
        else:
            # An imagined field is drawn again every week, so the plan cannot
            # lean on the quirks of any one imaginary set of coaches.
            field = (
                rng.random((sims, coaches, games), dtype=np.float32)
                >= crowd.astype(np.float32)
            ).astype(np.int8)
            self.scores = (field == self.results[:, None, :]).sum(axis=2)
        self.others = self.scores.shape[1]
        self.best_other = self.scores.max(axis=1)
        self.field_total = self.scores.sum(axis=1)
        # How many other coaches landed on each score, and how many beat it,
        # in every simulated week. With these, judging a card is a lookup per
        # week rather than a comparison against all 34 cards - about ten
        # times faster, which is what lets the planner afford 20,000 weeks.
        rows = np.arange(sims)
        self._rows = rows
        at = np.zeros((sims, games + 2), dtype=np.int32)
        for score in range(games + 1):
            at[:, score] = (self.scores == score).sum(axis=1)
        self.at_score = at
        self.beating = at[:, ::-1].cumsum(axis=1)[:, ::-1]   # others scoring >= k

    def _mine(self, card: np.ndarray) -> np.ndarray:
        return (card[None, :] == self.results).sum(axis=1)

    def odds(self, card: np.ndarray) -> tuple[float, float]:
        """(chance of finishing first, average payout) - the search's question."""
        mine = self._mine(card)
        ties = self.at_score[self._rows, mine]
        share = np.where(
            mine > self.best_other, 1.0,
            np.where(mine == self.best_other, 1.0 / (ties + 1), 0.0),
        )
        margin = mine * self.others - self.field_total
        return float(share.mean()), float((share * margin).mean())

    def worth(self, card: np.ndarray) -> tuple[float, float, float, float]:
        """(chance of finishing first, average payout, expected hits, top five)."""
        odds, pay = self.odds(card)
        mine = self._mine(card)
        above = self.beating[self._rows, mine + 1]            # others strictly above
        return odds, pay, float(mine.mean()), float((above < 5).mean())


def plan_week(
    choices: list[Choice],
    *,
    cards: list[list[int]] | None = None,
    coaches: int = 34,
    sims: int = SIMULATIONS,
    seed: int = SEED,
) -> Plan | None:
    """The card most likely to finish first, and what it beats.

    `cards` is the rest of the pool, one row a coach, 0 where they took the
    same side as `choices[i].pick`. Without it the field is simulated from
    each game's `crowd`.

    The same inputs always give the same plan, and it is remembered, so the
    pages that show it can ask as often as they like.
    """
    if not choices:
        return None
    frozen_cards = tuple(tuple(int(v) for v in row) for row in cards) if cards else None
    return _plan(tuple(choices), frozen_cards, coaches, sims, seed)


def card_odds(
    choices: list[Choice],
    take: list[str],
    *,
    cards: list[list[int]] | None = None,
    coaches: int = 34,
    sims: int = SIMULATIONS,
    seed: int = SEED,
) -> tuple[float, tuple[float, ...]] | None:
    """(chance of finishing first, the same with each game flipped) for a given card.

    For a card chosen some other way - the likeliest side of every game, say -
    so the page can show what each of its picks is worth to winning the week
    by the same measure the planner uses.
    """
    if not choices or len(take) != len(choices):
        return None
    bits = tuple(0 if t == c.pick else 1 for t, c in zip(take, choices))
    frozen_cards = tuple(tuple(int(v) for v in row) for row in cards) if cards else None
    return _card_odds(tuple(choices), bits, frozen_cards, coaches, sims, seed)


@lru_cache(maxsize=32)
def _card_odds(choices, bits, cards, coaches, sims, seed):
    chance = np.array([c.chance for c in choices])
    crowd = np.array([c.crowd for c in choices])
    field = np.array(cards, dtype=np.int8) if cards else None
    check = _Week(chance, crowd, field, coaches, sims, np.random.default_rng(seed + 1))
    card = np.array(bits, dtype=np.int8)
    odds = check.odds(card)[0]
    flips = []
    for game in range(len(choices)):
        trial = card.copy()
        trial[game] ^= 1
        flips.append(check.odds(trial)[0])
    return odds, tuple(flips)


@lru_cache(maxsize=32)
def _plan(
    choices: tuple[Choice, ...],
    cards: tuple[tuple[int, ...], ...] | None,
    coaches: int,
    sims: int,
    seed: int,
) -> Plan | None:
    chance = np.array([c.chance for c in choices])
    crowd = np.array([c.crowd for c in choices])
    field = np.array(cards, dtype=np.int8) if cards else None
    if field is not None and field.size == 0:
        return None
    if field is None and coaches < 1:
        return None

    # Choose on one set of weeks, report on another.
    search = _Week(chance, crowd, field, coaches, sims, np.random.default_rng(seed))
    check = _Week(chance, crowd, field, coaches, sims, np.random.default_rng(seed + 1))

    plain = np.zeros(len(choices), dtype=np.int8)       # the likelier side everywhere
    card = plain.copy()
    best = search.odds(card)
    for _ in range(len(choices)):
        trials = []
        for game in range(len(choices)):
            trial = card.copy()
            trial[game] ^= 1
            trials.append((search.odds(trial), game))
        # Most likely to finish first; between equals, the one that pays more.
        (odds, pay), game = max(trials, key=lambda t: t[0])
        if odds < best[0] + MIN_GAIN:
            break
        card[game] ^= 1
        best = (odds, pay)

    odds, pay, hits, top = check.worth(card)
    plain_odds, plain_pay, plain_hits, plain_top = check.worth(plain)
    flip_odds = []
    for game in range(len(choices)):
        trial = card.copy()
        trial[game] ^= 1
        flip_odds.append(check.odds(trial)[0])
    return Plan(
        take=[c.other if card[i] else c.pick for i, c in enumerate(choices)],
        flipped=[i for i in range(len(choices)) if card[i]],
        win_odds=odds, payout=pay, expected_hits=hits, top_five=top,
        plain_win_odds=plain_odds, plain_payout=plain_pay,
        plain_hits=plain_hits, plain_top_five=plain_top,
        coaches=search.others, simulations=sims,
        field_known=field is not None,
        flip_odds=tuple(flip_odds),
    )
