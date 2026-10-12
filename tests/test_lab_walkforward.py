#!/usr/bin/env python3
"""Tests for the Model Lab's walk-forward backtest (lab/walkforward.py).

    python tests/test_lab_walkforward.py

Uses the invented season from test_lab_history and small invented histories;
no network, no Qt, and the app's database is never opened.
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

from acql import analytics  # noqa: E402
from lab import walkforward as wf  # noqa: E402
from lab.history import build  # noqa: E402

import test_lab_history as fixtures  # noqa: E402


class TestVerifiedComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix="lab-wf-"))
        cls.db = cls.folder / "history.db"
        build.build(fixtures.write_fixtures(cls.folder), cls.db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_picks_are_made_without_reading_outcomes(self):
        conn = sqlite3.connect(f"{self.db.resolve().as_uri()}?mode=ro", uri=True)
        conn.set_authorizer(lambda action, table, *_: sqlite3.SQLITE_DENY
                            if action == sqlite3.SQLITE_READ and table == "outcomes" else sqlite3.SQLITE_OK)
        picks, notes = wf.verified_picks(conn)
        conn.close()
        self.assertEqual(notes, [])
        # BAL-KC, ATL-PIT, NE-MIA, SF-SEA and DAL-NYG have a dated line, models and a sheet.
        self.assertEqual(sorted(p.game_id for p in picks), sorted(
            ["2030_01_BAL_KC", "2030_01_ATL_PIT", "2030_01_NE_MIA", "2030_01_SF_SEA", "2030_01_DAL_NYG"]))

    def test_deadeye_at_weight_zero_is_the_market(self):
        copy = self.folder / "zero.db"
        shutil.copyfile(self.db, copy)
        conn = sqlite3.connect(copy)
        conn.execute("UPDATE production_weights SET weight = 0")
        picks, _ = wf.verified_picks(conn)
        conn.close()
        for p in picks:
            self.assertEqual((p.deadeye.pick, round(p.deadeye.chance, 9)),
                             (p.market.pick, round(p.market.chance, 9)), p.game_id)

    def test_a_week_with_no_held_weight_is_left_out_and_said_so(self):
        copy = self.folder / "noweight.db"
        shutil.copyfile(self.db, copy)
        conn = sqlite3.connect(copy)
        conn.execute("DELETE FROM production_weights")
        picks, notes = wf.verified_picks(conn)
        conn.close()
        self.assertEqual(picks, [])
        self.assertTrue(any("no production weight" in n for n in notes))

    def test_scoring_uses_the_sheet_line(self):
        conn = sqlite3.connect(self.db)
        picks, _ = wf.verified_picks(conn)
        result = wf.score_verified(picks, wf.outcomes(conn))
        conn.close()
        winners = {r["pick"].game_id: r["winner"] for r in result["rows"]}
        self.assertEqual(winners["2030_01_BAL_KC"], "kc")     # KC by 7 on a "(kc by 7)" line: exactly the line
        self.assertEqual(winners["2030_01_NE_MIA"], "mia")    # MIA by 10 clears "(mia by 8)"
        self.assertEqual(winners["2030_01_SF_SEA"], "sea")    # SF won by 3 but needed 7
        self.assertNotIn("2030_01_DAL_NYG", winners)          # a straight-up tie: grading unknown
        self.assertEqual(result["ties"], 1)


class TestRules(unittest.TestCase):
    def test_credit_follows_the_pool_rule(self):
        self.assertEqual(wf.credited("h", "a", 7.0, 7), "h")       # exactly the line goes to the favourite
        self.assertEqual(wf.credited("h", "a", 7.0, 6), "a")
        self.assertEqual(wf.credited("h", "a", 6.5, 7), "h")       # half point: the next whole number
        self.assertEqual(wf.credited("h", "a", -8.0, -8), "a")     # road favourite by exactly 8
        self.assertEqual(wf.credited("h", "a", -8.0, -7), "h")
        self.assertEqual(wf.credited("h", "a", None, 1), "h")
        self.assertIsNone(wf.credited("h", "a", None, 0))

    def test_the_current_width_flips_nothing(self):
        self.assertEqual(wf.flips(wf.CURRENT_SD), [])

    def test_bootstrap_is_repeatable_and_brackets_the_mean(self):
        diffs = [random.Random(1).gauss(0, 1) for _ in range(200)]
        one, two = wf.bootstrap(diffs, n=400), wf.bootstrap(diffs, n=400)
        self.assertEqual(one, two)
        self.assertLessEqual(one[1], one[0])
        self.assertLessEqual(one[0], one[2])
        grouped = wf.bootstrap(diffs, [i % 10 for i in range(200)], n=400)
        self.assertAlmostEqual(grouped[0], one[0])


class TestWalkForward(unittest.TestCase):
    def setUp(self):
        rng = random.Random(7)
        self.games = []
        self.margins = {}
        for season in range(2000, 2006):
            for i in range(40):
                spread = rng.choice([-7.5, -3.0, -1.5, 2.5, 3.0, 6.5, 9.5, 13.0])
                line = None if abs(spread) < 6.5 else (abs(spread) // 1 + 1) * (1 if spread > 0 else -1)
                gid = f"{season}_{i}"
                self.games.append(wf.HistGame(gid, season, 1, "h", "a", spread, line))
                self.margins[gid] = round(spread + rng.gauss(0, 13))
        self.priced = wf.price_history(self.games, sds=(8.7, 10.2, 12.0))

    def choose(self, margins):
        seasons = wf.walk_forward(self.games, self.priced, margins, 2002, 2005, sds=(8.7, 10.2, 12.0))
        return {s["season"]: (s["sd"], s["trained_on"]) for s in seasons}

    def test_a_season_is_never_tuned_on_itself_or_later(self):
        baseline = self.choose(self.margins)
        for season in (2002, 2003, 2004, 2005):
            tampered = dict(self.margins)
            for g in self.games:
                if g.season >= season:
                    tampered[g.game_id] = -tampered[g.game_id] + 40     # anything at all
            self.assertEqual(self.choose(tampered)[season], baseline[season], season)

    def test_training_grows_one_season_at_a_time(self):
        trained = [n for _, n in (self.choose(self.margins)[s] for s in (2002, 2003, 2004, 2005))]
        self.assertEqual(trained, sorted(trained))
        self.assertTrue(all(b > a for a, b in zip(trained, trained[1:])))

    def test_pricing_reads_no_results(self):
        # price_history takes no outcomes at all: same prices whatever happened.
        again = wf.price_history(self.games, sds=(8.7, 10.2, 12.0))
        self.assertEqual({k: (v.pick, v.chance) for k, v in again.items()},
                         {k: (v.pick, v.chance) for k, v in self.priced.items()})
        self.assertIsInstance(next(iter(again.values())), analytics.Prediction)


if __name__ == "__main__":
    unittest.main(verbosity=2)
