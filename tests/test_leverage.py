#!/usr/bin/env python3
"""Tests for the season-race leverage (acql/pool/leverage.py).

Run from the project root:

    python tests/test_leverage.py

Made-up pools with a fixed seed, so every number is repeatable; one check
against the real season when its data is here. No Qt.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql.pool import leverage


def pool(gap: int, rival_cards: list[list[int]], chances: list[float], *, weeks_after: int = 0,
         known: bool = True, sims: int = 4000) -> leverage.Report:
    """Me (row 0) `gap` wins behind one rival (row 1), with these chances this week."""
    games = len(chances)
    players = [SimpleNamespace(display="Me"), SimpleNamespace(display="Rival")]
    choices = [SimpleNamespace(matchup=f"A{i} @ H{i}", pick=f"H{i}", other=f"A{i}") for i in range(games)]
    cards = np.array([[0] * games] + rival_cards, dtype=np.int8)
    known_a = np.full(cards.shape, known)
    known_a[0] = False
    base = np.array([10.0, 10.0 + gap], dtype=np.float32)
    flat = np.arange(4.0, 11.0, dtype=np.float32)      # a coach's weeks: 4 to 10 right
    weekly = ([(flat, flat), (flat, flat)], weeks_after)
    zero = np.array([0.0], dtype=np.float32)
    bl = [(zero, zero), (zero, zero)]
    return leverage._report(None, 1, tuple(chances), tuple([0.7] * games), tuple([False] * games), choices,
                            players, 0, cards, known_a, base, weekly, bl, weeks_after + 1, sims, 7)


class TestLeverage(unittest.TestCase):

    def test_same_card_as_the_leader_cannot_catch_them(self):
        found = pool(2, [[0, 0, 0, 0]], [0.6] * 4)
        self.assertEqual(found.title, 0.0)          # every game moves you both alike

    def test_chase_card_turns_games_when_behind_at_the_end(self):
        found = pool(2, [[0, 0, 0, 0]], [0.6] * 4)
        self.assertGreaterEqual(len(found.flips), 2)  # two turned games are needed just to draw level
        self.assertGreater(found.chase_title, 0.0)
        self.assertLess(found.chase_hits, found.card_hits)   # and it costs expected wins

    def test_leader_keeps_the_card(self):
        found = pool(-3, [[1, 0, 0, 0]], [0.6] * 4)
        self.assertEqual(found.flips, [])
        self.assertGreater(found.title, 0.9)

    def test_game_the_rival_is_already_against_is_worth_less_to_turn(self):
        # The rival is on the other side of game 0 only: turning game 0 puts
        # you level with them there, so it can't gain; turning game 1 can.
        found = pool(1, [[1, 0, 0]], [0.55, 0.55, 0.55], sims=8000)
        self.assertLess(found.picks[0].worth(leverage.TITLE), found.picks[1].worth(leverage.TITLE))

    def test_rival_split_reads_the_real_card(self):
        found = pool(1, [[1, 0]], [0.6, 0.6])
        self.assertEqual(found.picks[0].split["Rival"], 1.0)
        self.assertEqual(found.picks[1].split["Rival"], 0.0)
        self.assertEqual(found.rivals[0].differ, 1.0)

    def test_estimated_split_without_a_sheet(self):
        found = pool(1, [[0, 0]], [0.6, 0.6], known=False)
        self.assertAlmostEqual(found.picks[0].split["Rival"], 0.3)
        self.assertFalse(found.field_known)

    def test_long_season_flattens_single_picks(self):
        late = pool(1, [[0, 0, 0, 0]], [0.6] * 4)
        early = pool(1, [[0, 0, 0, 0]], [0.6] * 4, weeks_after=10)
        self.assertLess(abs(early.picks[0].worth(leverage.TITLE)), 0.2)
        self.assertGreater(abs(late.picks[0].worth(leverage.TITLE)), abs(early.picks[0].worth(leverage.TITLE)))

    def test_real_season(self):
        try:
            from acql.config import Settings
            from acql.names import AliasTable
            from acql.repository import load_season
            season = load_season(Settings.load(), AliasTable.load(), online=False)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"no season here: {exc}")
        found = leverage.report(season, sims=3000)
        if found is None:
            self.skipTest("no owner or no priced week")
        self.assertTrue(0 <= found.title <= 1 and 0 <= found.top3 <= 1)
        self.assertGreaterEqual(found.top3, found.title)
        self.assertIs(leverage.report(season, sims=3000), found)       # remembered


if __name__ == "__main__":
    unittest.main(verbosity=2)
