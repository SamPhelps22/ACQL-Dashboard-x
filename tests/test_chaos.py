#!/usr/bin/env python3
"""Tests for the Chaos Simulator engine (acql/pool/chaos.py).

Run from the project root:

    python tests/test_chaos.py

Made-up slates only, with a fixed seed, so every number is repeatable. No Qt.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql.pool import chaos
from acql.pool.chaos import ChaosGame, Coach


def slate(n: int = 14) -> list[ChaosGame]:
    return [
        ChaosGame(label=f"A{i} @ H{i}", home=f"H{i}", away=f"A{i}",
                  home_margin=(i % 7) - 2.5, home_win=None)
        for i in range(n)
    ]


def field(games, size: int = 35) -> list[Coach]:
    favs = tuple(g.favourite_is_home for g in games)
    coaches = [Coach("Phelpy", chaos.BASIS_SHEET, card=favs)]
    coaches += [Coach(f"C{i}", chaos.BASIS_HISTORY, fav_rate=0.6 + 0.01 * i, picks_seen=40)
                for i in range(size - 2)]
    coaches.append(Coach("Newbie", chaos.BASIS_FAVOURITES))
    return coaches


class Engine(unittest.TestCase):
    def setUp(self):
        self.games = slate()
        self.coaches = field(self.games)

    def test_same_seed_same_answer(self):
        a = chaos.report(chaos.simulate(self.games, self.coaches, sims=3000, seed=7), "Phelpy")
        b = chaos.report(chaos.simulate(self.games, self.coaches, sims=3000, seed=7), "phelpy")
        self.assertEqual(a, b)
        c = chaos.report(chaos.simulate(self.games, self.coaches, sims=3000, seed=8), "Phelpy")
        self.assertNotEqual(a.finishes, c.finishes)

    def test_finishes_are_a_distribution(self):
        r = chaos.report(chaos.simulate(self.games, self.coaches, sims=4000), "Phelpy")
        self.assertEqual(len(r.finishes), 35)
        self.assertAlmostEqual(sum(r.finishes), 1.0, places=9)
        self.assertAlmostEqual(r.first, r.finishes[0])
        self.assertLessEqual(r.first_alone, r.first)
        self.assertLessEqual(r.best_finish, r.typical_range[0])
        self.assertGreaterEqual(r.worst_finish, r.typical_range[1])
        self.assertTrue(0 <= r.expected_score <= len(self.games))

    def test_places_share_ties(self):
        sim = chaos.simulate(self.games, self.coaches, sims=500)
        for s in range(0, 500, 50):
            row, places = sim.scores[s], sim.places[s]
            top = row.max()
            self.assertTrue((places[row == top] == 1).all())
            for i in range(len(row)):
                self.assertEqual(places[i], 1 + (row > row[i]).sum())

    def test_favourite_card_scores_market_expectation(self):
        # The all-favourites card should average the sum of the favourites' chances.
        sim = chaos.simulate(self.games, self.coaches, sims=20000, seed=3)
        want = sum(max(g.home_credited_chance(), 1 - g.home_credited_chance()) for g in self.games)
        self.assertAlmostEqual(chaos.report(sim, "Phelpy").expected_score, want, delta=0.08)

    def test_moneyline_sets_the_chance(self):
        g = ChaosGame("A @ H", "H", "A", home_margin=3.0, home_win=0.70)
        self.assertAlmostEqual(g.home_credited_chance(), 0.70, places=3)
        sim = chaos.simulate([g], [Coach("x", chaos.BASIS_FAVOURITES)], sims=40000, seed=1)
        self.assertAlmostEqual(sim.home[:, 0].mean(), 0.70, delta=0.01)

    def test_lined_game_needs_the_line(self):
        # A 7-point favourite on a 7-point pool line: about a coin flip to cover.
        g = ChaosGame("A @ H", "H", "A", home_margin=7.0, line=7.0, line_fav_home=True)
        self.assertAlmostEqual(g.home_credited_chance(), 0.5 + 0.5 / 13.5 * 0.4, delta=0.03)
        dog = ChaosGame("A @ H", "H", "A", home_margin=7.0, line=7.0, line_fav_home=False)
        straight = ChaosGame("A @ H", "H", "A", home_margin=7.0)
        self.assertLess(g.home_credited_chance(), straight.home_credited_chance())
        # The line given to the market's underdog: home is credited unless the away side wins by 7+.
        self.assertGreater(dog.home_credited_chance(), straight.home_credited_chance())

    def test_leverage_is_the_biggest_swing(self):
        # Phelpy alone fades game 0's favourite: that game must swing his finish most.
        favs = list(g.favourite_is_home for g in self.games)
        favs[0] = not favs[0]
        coaches = [Coach("Phelpy", chaos.BASIS_SHEET, card=tuple(favs))]
        coaches += [Coach(f"C{i}", chaos.BASIS_FAVOURITES) for i in range(34)]
        r = chaos.report(chaos.simulate(self.games, coaches, sims=4000), "Phelpy")
        self.assertEqual(r.leverage.game, self.games[0].label)
        self.assertEqual(r.leverage.size, max(s.size for s in r.swings))

    def test_basis_is_labelled(self):
        texts = [c.basis_text for c in self.coaches]
        self.assertIn("pick sheet", texts[0])
        self.assertIn("history", texts[1])
        self.assertIn("assumed", texts[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
