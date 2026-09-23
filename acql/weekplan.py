"""Choosing a whole card, to win the week rather than to be right most often.

Picking each game's likelier side maximises how many you get right. It does
not maximise what you are paid, and in this pool those are different things:

    "If you have the best record for the week then you receive $1 per game
     per coach that your record differs from that coach."

So the money is your margin over the field, collected only when you finish
top. Being right on a game 33 of 35 coaches also got right moves you and the
field together and pays nothing; being right where they are wrong is the
whole of it. The sums bear that out - a 55% pick a quarter of the pool holds
is worth more than a 74% pick that 33 of them share.

The method is plain simulation. Play the week ten thousand times, score
every coach's real card each time, score a candidate card of your own, and
average what it would have paid. Then walk from the obvious card - the
likelier side of everything - flipping whichever single game improves the
average most, until nothing does. Sixteen games is few enough that this
finds the best card or something very near it, and it explains itself: every
flip it keeps is a game it can say the reason for.

Nothing in here knows about football. It takes a probability per game and a
picture of what everyone else has done, and it is equally happy with a real
pick sheet or with cards drawn from how the pool usually behaves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SIMULATIONS = 10_000
SEED = 2026          # fixed, so the same week always plans the same way


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
    """A whole card, and what it is worth."""

    take: list[str]          # the side to take in each game, in order
    flipped: list[int]       # games where that isn't the likelier side
    win_odds: float          # chance of finishing top of the week
    payout: float            # average dollars, counting the weeks you don't win
    expected_hits: float     # how many games it expects to get right
    plain_win_odds: float    # the same, for the card that just takes the likelier side
    plain_payout: float
    plain_hits: float
    coaches: int
    simulations: int


def _field(
    choices: list[Choice],
    cards: list[list[int]] | None,
    coaches: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """The other coaches' cards as rows of 0 (took `pick`) and 1 (took `other`).

    A real pick sheet is used as it stands. Without one, the field is drawn
    from how often the pool takes each side, which is the same information
    the leverage column uses.
    """
    if cards:
        return np.array(cards, dtype=np.int8)
    crowd = np.array([c.crowd for c in choices])
    draws = rng.random((coaches, len(choices)))
    return (draws >= crowd).astype(np.int8)


def plan_week(
    choices: list[Choice],
    *,
    cards: list[list[int]] | None = None,
    coaches: int = 34,
    sims: int = SIMULATIONS,
    seed: int = SEED,
) -> Plan | None:
    """The card that pays most, and what it beats.

    `cards` is the rest of the pool, one row a coach, 0 where they took the
    same side as `choices[i].pick`. Without it the field is simulated.
    """
    if not choices:
        return None
    rng = np.random.default_rng(seed)
    chance = np.array([c.chance for c in choices])

    # 0 means "the pick side came in", 1 means the other side did, so a card
    # scores a game when its entry equals the result.
    results = (rng.random((sims, len(choices))) >= chance).astype(np.int8)
    field = _field(choices, cards, coaches, rng)
    if field.size == 0:
        return None
    others = field.shape[0]
    field_scores = (field[None, :, :] == results[:, None, :]).sum(axis=2)
    best_other = field_scores.max(axis=1)
    field_total = field_scores.sum(axis=1)

    def worth(card: np.ndarray) -> tuple[float, float, float]:
        """(chance of winning the week, average payout, expected hits)."""
        mine = (card[None, :] == results).sum(axis=1)
        ties = (field_scores == mine[:, None]).sum(axis=1)
        won = mine > best_other
        tied = mine == best_other
        share = np.where(won, 1.0, np.where(tied, 1.0 / (ties + 1), 0.0))
        margin = mine * others - field_total
        return float(share.mean()), float((share * margin).mean()), float(mine.mean())

    plain = np.zeros(len(choices), dtype=np.int8)       # the likelier side everywhere
    plain_odds, plain_pay, plain_hits = worth(plain)

    card = plain.copy()
    best = plain_pay
    for _ in range(len(choices)):
        gains = []
        for game in range(len(choices)):
            trial = card.copy()
            trial[game] ^= 1
            gains.append((worth(trial)[1], game))
        gain, game = max(gains)
        if gain <= best + 1e-9:
            break
        card[game] ^= 1
        best = gain

    odds, pay, hits = worth(card)
    return Plan(
        take=[c.other if card[i] else c.pick for i, c in enumerate(choices)],
        flipped=[i for i in range(len(choices)) if card[i]],
        win_odds=odds, payout=pay, expected_hits=hits,
        plain_win_odds=plain_odds, plain_payout=plain_pay, plain_hits=plain_hits,
        coaches=others, simulations=sims,
    )