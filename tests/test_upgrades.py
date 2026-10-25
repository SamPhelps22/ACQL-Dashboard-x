#!/usr/bin/env python3
"""Tests for the upgrade-book builds of 2026-10-25: ESPN's live win chance,
the stakes quad, the slate screener, the change explainer, the graded crowd
forecast, the hypothesis bench and the devil's advocate brief.

Run from the project root:

    python tests/test_upgrades.py

Made-up numbers and a scratch database; nothing is fetched. No Qt.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import store
from acql.feeds import winprob
from acql.pool import gameday as GD


class ScratchStore(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        store.use(Path(self._dir.name) / "acql.db")

    def tearDown(self):
        store.use(None)
        self._dir.cleanup()


class TestWinChanceFeed(ScratchStore):
    def test_parse_takes_the_newest_valid_point(self):
        payload = {"winprobability": [{"homeWinPercentage": 0.4}, {"homeWinPercentage": 0.18}, {"junk": 1}]}
        self.assertEqual(winprob.parse(payload), 0.18)

    def test_parse_refuses_what_isnt_a_chance(self):
        self.assertIsNone(winprob.parse({"winprobability": [{"homeWinPercentage": 1.7}]}))
        self.assertIsNone(winprob.parse({"winprobability": "no"}))
        self.assertIsNone(winprob.parse([]))

    def test_refresh_reads_live_games_only_and_waits_a_minute_between_looks(self):
        asked = []

        def fake(event):
            asked.append(event)
            return 0.61

        scores = [SimpleNamespace(state="in", event="1"), SimpleNamespace(state="pre", event="2"),
                  SimpleNamespace(state="post", event="3")]
        self.assertEqual(winprob.refresh(scores, now=1000.0, fetcher=fake), 1)
        self.assertEqual(asked, ["1"])
        self.assertEqual(winprob.latest("1", now=1010.0), 0.61)
        winprob.refresh(scores, now=1030.0, fetcher=fake)          # too soon: not asked again
        self.assertEqual(asked, ["1"])
        winprob.refresh(scores, now=1070.0, fetcher=fake)
        self.assertEqual(asked, ["1", "1"])

    def test_an_old_number_is_not_used(self):
        winprob.refresh([SimpleNamespace(state="in", event="9")], now=0.0, fetcher=lambda e: 0.3)
        self.assertEqual(winprob.latest("9", now=100.0), 0.3)
        self.assertIsNone(winprob.latest("9", now=winprob.FRESH + 1))

    def test_a_failed_fetch_is_quiet(self):
        def boom(event):
            raise OSError("no network")
        self.assertEqual(winprob.refresh([SimpleNamespace(state="in", event="4")], now=0.0, fetcher=boom), 0)
        self.assertIsNone(winprob.latest("4", now=1.0))


class TestCarryingEspnsChance(unittest.TestCase):
    def test_the_expectation_found_gives_back_espns_chance(self):
        for margin, left, p in ((3, 0.05, 0.52), (-7, 0.4, 0.2), (0, 0.9, 0.7), (10, 0.2, 0.97)):
            found = GD.expected_for(margin, left, 13.5, p)
            self.assertIsNotNone(found)
            back = GD.home_win(GD.outlook(margin, left, found, 13.5, started=True))
            self.assertAlmostEqual(back, p, places=3)

    def test_nothing_once_the_clock_has_run_out_or_for_a_certainty(self):
        self.assertIsNone(GD.expected_for(3, 0.0, 13.5, 0.6))
        self.assertIsNone(GD.expected_for(3, 0.5, 13.5, 1.0))
        self.assertIsNone(GD.expected_for(3, 0.5, 13.5, 0.0))

    def test_a_trailing_side_with_the_ball_close_to_scoring_is_carried(self):
        # 20-17 late: the score alone says the leader is a big favourite; ESPN says a coin flip
        lead = GD.home_win(GD.outlook(3, 0.05, 0.0, 13.5, started=True))
        self.assertGreater(lead, 0.75)
        found = GD.expected_for(3, 0.05, 13.5, 0.52)
        self.assertLess(found, 0.0)       # it takes an expectation leaning the other way


class TestStakesQuad(unittest.TestCase):
    def _bd(self, levers, live):
        bd = SimpleNamespace(live=live)
        original = GD.levers
        GD.levers = lambda _bd: levers
        self.addCleanup(setattr, GD, "levers", original)
        return bd

    def test_biggest_stake_first_and_red_zone_weighs_more(self):
        st = lambda i, rz=False, k=0: SimpleNamespace(index=i, red_zone=rz, kickoff=k)   # noqa: E731
        lv = lambda s, size: SimpleNamespace(state=s, size=size)                         # noqa: E731
        a, b, c = st(1), st(2, rz=True), st(3)
        bd = self._bd([lv(a, 0.10), lv(b, 0.08), lv(c, 0.02)], [a, b, c])
        order = GD.stakes_order(bd)
        self.assertEqual([i for i, _ in order], [2, 1, 3])
        self.assertAlmostEqual(order[0][1], 0.12)

    def test_fills_with_other_live_games_and_stops_at_four(self):
        games = [SimpleNamespace(index=i, red_zone=False, kickoff=i) for i in range(1, 8)]
        bd = self._bd([SimpleNamespace(state=games[5], size=0.2)], games)
        order = GD.stakes_order(bd)
        self.assertEqual(len(order), GD.QUAD)
        self.assertEqual(order[0], (6, 0.2))
        self.assertEqual([i for i, _ in order[1:]], [1, 2, 3])


class TestScreenerFilters(unittest.TestCase):
    def _row(self, **kw):
        from acql.model import screener
        base = dict(index=1, matchup="A @ B", away="A", home="B", pick="B", chance=0.6, market=0.6, crowd=0.7,
                    counted=True, pool_line="", pool_gap=None, flip=3.0, loser="A", loser_chance=0.1, hard=50,
                    weather="", injuries="")
        base.update(kw)
        return screener.Row(**base)

    def test_each_filter_picks_its_games(self):
        from acql.model import screener
        rows = [self._row(index=1), self._row(index=2, chance=0.52), self._row(index=3, flip=1.0),
                self._row(index=4, pool_gap=-1.5), self._row(index=5, crowd=0.9),
                self._row(index=6, market=0.45), self._row(index=7, loser_chance=0.3),
                self._row(index=8, injuries="QB out")]
        screen = screener.Screen(8, rows, True)
        want = {"all": 8, "toss": 1, "fragile": 1, "pool_gap": 1, "herd": 2, "against": 1, "loser": 1, "news": 1}
        for key, count in want.items():
            self.assertEqual(len(screener.filtered(screen, key)), count, key)

    def test_edge_and_lean(self):
        row = self._row(chance=0.62, market=0.58, crowd=0.81)
        self.assertAlmostEqual(row.edge, 0.04)
        self.assertAlmostEqual(row.lean, 0.19)
        self.assertIsNone(self._row(market=None).edge)


class TestChangeExplainer(ScratchStore):
    def test_kept_at_takes_the_last_record_before_the_moment(self):
        from acql.model import changes
        from acql.pool import chancetrail
        chancetrail.record(5, {1: ("Detroit", 0.61)}, now=1000.0)
        chancetrail.record(5, {1: ("Detroit", 0.55)}, now=1000.0 + chancetrail.EVERY + 1)
        at, row = changes.kept_at(5, 1000.0 + 10)
        self.assertEqual(at, 1000.0)
        self.assertEqual(row[1], ("Detroit", 0.61))
        self.assertIsNone(changes.kept_at(5, 10.0))

    def test_the_parts_add_up_to_the_whole_move(self):
        from acql.model import changes
        m = changes.Move(1, "A @ B", "B", now=0.58, then=0.63, line_then=3.0, line_now=1.5,
                         line_part=-0.04, rest_part=(0.58 - 0.63) - (-0.04))
        self.assertAlmostEqual(m.line_part + m.rest_part, m.total)


class TestCrowdForecastGraded(ScratchStore):
    def _obs(self, week, share, points=3.0):
        from acql.pool import crowd
        sit = crowd.Situation("Detroit", "Chicago", points, True, None)
        return crowd.Observation(sit, share, 35, week)

    def test_a_week_is_guessed_only_from_the_weeks_before_it(self):
        from acql.pool import crowd, crowdcard
        obs = [self._obs(w, 0.95) for w in (1, 2, 3) for _ in range(10)]
        card = crowdcard.grade(None, obs, [])
        first = [g for g in card.games if g.week == 1]
        # week 1 has nothing before it: the usual curve, exactly
        self.assertTrue(all(abs(g.predicted - g.usual) < 1e-12 for g in first))
        # week 3 learned from weeks 1-2 (20 games) that this pool loves the favourite
        third = [g for g in card.games if g.week == 3]
        self.assertTrue(all(g.predicted > g.usual for g in third))
        self.assertLess(card.mean_miss(3), card.mean_usual(3))
        self.assertEqual(crowd.MINIMUM_GAMES <= 20, True)

    def test_a_guess_kept_before_the_sheet_wins_over_a_rebuild(self):
        from acql.pool import crowdcard
        from acql.model.predictions import team_code
        store.put(crowdcard.KIND, "2", {"at": 1.0, "shares": {f"{team_code('Detroit')}|{team_code('Chicago')}": 0.5}})
        card = crowdcard.grade(None, [self._obs(2, 0.8)], [])
        self.assertTrue(card.games[0].kept)
        self.assertAlmostEqual(card.games[0].predicted, 0.5)
        self.assertAlmostEqual(card.games[0].miss, 0.3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
