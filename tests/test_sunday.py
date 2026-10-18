"""The Sunday brief and the week score check - on made-up seasons, nothing real read or sent.

    python -m unittest tests.test_sunday
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acql.feeds.results import Score  # noqa: E402
from acql.models import Game, PlayerWeek, Season, Week  # noqa: E402


def _season():
    games = [Game(1, home="Buffalo", away="Miami", winner="Buffalo"),
             Game(2, home="Dallas", away="New York Giants", winner="Dallas",
                  line=7.0, line_favourite="Dallas")]
    week = Week(3, games=games)
    week.lines["ann"] = PlayerWeek("Ann", 3, correct_picks={1: "Buffalo", 2: "Dallas"}, total_wins=2)
    week.lines["bob"] = PlayerWeek("Bob", 3, correct_picks={1: "Buffalo"}, total_wins=3)
    season = Season()
    season.weeks[3] = week
    return season


SCORES = [Score("mia", "buf", 10, 24, state="post", final=True),
          Score("nyg", "dal", 17, 20, state="post", final=True)]     # Dallas by 3: not the 7


class TestReconcile(unittest.TestCase):
    def check(self):
        from acql.pool import reconcile
        with mock.patch("acql.pool.picks.load", return_value=None):
            return reconcile.check(_season(), 3, scores=SCORES, year=2026)

    def test_a_line_game_on_file_for_the_favourite_who_did_not_cover_is_flagged(self):
        report = self.check()
        self.assertEqual(report.checked_games, 2)
        self.assertEqual([g.index for g in report.games], [2])
        self.assertIn("by 7 needed", report.games[0].why)

    def test_an_official_total_above_the_recount_is_listed(self):
        report = self.check()
        names = {c.name: c.off_by for c in report.coaches}
        self.assertIn("Bob", names)
        self.assertGreater(names["Bob"], 0)
        self.assertFalse(report.clean)
        self.assertIn("Bob", report.text())

    def test_a_week_that_adds_up_says_so(self):
        from acql.pool import reconcile
        season = _season()
        season.weeks[3].games[1].winner = "New York Giants"
        season.weeks[3].lines["ann"].correct_picks = {1: "Buffalo"}
        season.weeks[3].lines["ann"].total_wins = 1
        season.weeks[3].lines["bob"].total_wins = 1
        with mock.patch("acql.pool.picks.load", return_value=None):
            report = reconcile.check(season, 3, scores=SCORES, year=2026)
        self.assertTrue(report.clean, report.text())
        self.assertIn("Everything adds up", report.text())


class TestSundayBrief(unittest.TestCase):
    def test_budget_warns_near_the_reserve(self):
        from acql.site import sundaybrief
        note, low = sundaybrief.budget_note(sundaybrief.RESERVE + 10)
        self.assertTrue(low)
        self.assertIn("LOW", note)
        note, low = sundaybrief.budget_note(400)
        self.assertFalse(low)
        self.assertFalse(sundaybrief.budget_note(None)[1])

    def test_the_brief_carries_calls_moves_scorecard_and_honesty(self):
        from types import SimpleNamespace
        from acql.site import sundaybrief
        choice = SimpleNamespace(pick="Buffalo", chance=0.71, matchup="Miami @ Buffalo")
        board = [{"model_name": "Sagarin", "beat_line": 30, "line_games": 50, "beat_line_rate": 0.6,
                  "hit_rate": 0.66}]
        with mock.patch("acql.pool.briefing.build", return_value=SimpleNamespace(choices=[choice])):
            brief = sundaybrief.compose(Season(), 6, left=300, moves=[("Miami @ Buffalo", -3.0, -6.5)],
                                        board=board, honest=["Called 66%-75%: 7 of 8 came in"])
        for want in ("Buffalo (71%)", "-3.0 -> -6.5", "Sagarin: beat the close 30 of 50", "7 of 8", "300 requests"):
            self.assertIn(want, brief.text)
        self.assertIn("Sagarin", brief.html)
        self.assertNotIn("low", brief.subject)

    def test_nothing_priced_means_no_brief(self):
        from types import SimpleNamespace
        from acql.site import sundaybrief
        with mock.patch("acql.pool.briefing.build", return_value=SimpleNamespace(choices=[])):
            self.assertIsNone(sundaybrief.compose(Season(), 6, left=300, moves=[], board=[], honest=[]))


if __name__ == "__main__":
    unittest.main()
