#!/usr/bin/env python3
"""Tests for the Model Lab's phase 3 backtest (lab/archive_backtest.py).

    python tests/test_lab_archive_backtest.py

Small invented seasons, and the invented archive from test_lab_history; no
network, no Qt, and the app's database is never opened.
"""

from __future__ import annotations

import random
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from acql import predictions  # noqa: E402
from lab import archive_backtest as ab  # noqa: E402

import test_lab_history as fixtures  # noqa: E402

TEAMS = ["ari", "atl", "bal", "buf", "car", "chi", "cin", "cle", "dal", "den", "det", "gb",
         "hou", "ind", "jax", "kc"]


def invented_season(season: int, weeks: int, seed: int) -> tuple[list[ab.ArchiveGame], dict[str, int]]:
    rng = random.Random(seed)
    games, margins = [], {}
    for week in range(1, weeks + 1):
        order = TEAMS[:]
        rng.shuffle(order)
        for i in range(0, len(order), 2):
            home, away = order[i], order[i + 1]
            truth = rng.gauss(0, 6)
            market = round((truth + rng.gauss(0, 2)) * 2) / 2
            models = tuple(round(truth + rng.gauss(1, 3), 2) for _ in range(12))
            gid = f"{season}_{week:02d}_{away}_{home}"
            line = ab.proxy.pool_line(market)
            games.append(ab.ArchiveGame(
                gid, season, week, home, away,
                predictions.Forecast(road=away, home=home, market=market, opening=market, opinions=models),
                "midweek", None if line is None else (line if market > 0 else -line), market))
            margins[gid] = round(truth + rng.gauss(0, 13)) or 1
    return games, margins


class TestWalkForward(unittest.TestCase):
    def setUp(self):
        self.games, self.margins = invented_season(2030, 8, 3)

    def weights(self, margins):
        return {(p.game.season, p.game.week): p.weight for p in ab.walk_forward(self.games, margins)}

    def test_a_week_is_never_weighted_on_its_own_or_later_results(self):
        baseline = self.weights(self.margins)
        for week in range(1, 9):
            tampered = dict(self.margins)
            for g in self.games:
                if g.week >= week:
                    tampered[g.game_id] = -tampered[g.game_id] * 3 + 7
            self.assertEqual(self.weights(tampered)[(2030, week)], baseline[(2030, week)], week)

    def test_each_season_starts_from_the_starting_weight(self):
        other, more = invented_season(2031, 4, 4)
        found = {(p.game.season, p.game.week): p.weight
                 for p in ab.walk_forward(self.games + other, {**self.margins, **more})}
        self.assertEqual(found[(2030, 1)], ab.START)
        self.assertEqual(found[(2031, 1)], ab.START)

    def test_the_fit_is_production_s_own(self):
        # Week 5's weight is whatever predictions.fit_from makes of weeks 1-4.
        by_week = ab.weeks_of(self.games)
        replays = [predictions.replay_week(w, *ab.graded_slate(by_week[(2030, w)], self.margins))
                   for w in range(1, 5)]
        self.assertEqual(self.weights(self.margins)[(2030, 5)], predictions.fit_from(replays).weight)

    def test_weight_zero_is_the_market(self):
        for p in ab.price_week(ab.weeks_of(self.games)[(2030, 1)], 0.0):
            self.assertEqual(p.fitted_margin, p.game.forecast.market)
            self.assertEqual((p.fitted.pick, round(p.fitted.chance, 9)),
                             (p.market.pick, round(p.market.chance, 9)))

    def test_pricing_reads_no_results(self):
        week = ab.weeks_of(self.games)[(2030, 2)]
        once = [(p.fitted.pick, p.fitted.chance) for p in ab.price_week(week, 0.4)]
        again = [(p.fitted.pick, p.fitted.chance) for p in ab.price_week(week, 0.4)]
        self.assertEqual(once, again)


class TestScoring(unittest.TestCase):
    def test_against_the_close(self):
        self.assertEqual(ab.against_close(5.0, 3.0, 7), 1)       # took home, home covered
        self.assertEqual(ab.against_close(5.0, 3.0, 1), 0)
        self.assertEqual(ab.against_close(1.0, 3.0, 1), 1)       # took away, away covered
        self.assertIsNone(ab.against_close(3.0, 3.0, 10))        # no side taken
        self.assertIsNone(ab.against_close(5.0, 3.0, 3))         # landed on the number
        self.assertIsNone(ab.against_close(5.0, None, 3))


class TestLoad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = fixtures.TestSeasonArchive
        cls.case.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.case.tearDownClass()

    def test_archive_games_use_the_midweek_line_and_the_opener_for_the_pool_line(self):
        conn = sqlite3.connect(self.case.with_)
        games = {g.game_id: g for g in ab.load(conn, 2030, 2030)}
        self.assertEqual(sorted(games), ["2030_01_BAL_KC", "2030_01_LA_LAC", "2030_01_SF_SEA"])
        sea = games["2030_01_SF_SEA"]
        self.assertEqual(sea.forecast.market, 3.5)               # midweek, not the later 4.5
        self.assertEqual(sea.forecast.opening, 3.0)
        self.assertEqual(sea.line_used, "midweek")
        self.assertEqual(sea.forecast.opinions, (3.5, 6.0))      # linemidweek and linesag, as production counts
        self.assertEqual(sea.close, -3.5)                        # nflverse's own number

    def test_a_dataset_without_archives_has_nothing_to_load(self):
        conn = sqlite3.connect(self.case.without)
        self.assertEqual(ab.load(conn, 2030, 2030), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
