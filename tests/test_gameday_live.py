"""The live week as the screens show it - countdown, slate, score flashes,
freshness, card states, standings movement - and Cinema mode in a hidden
window. Made-up games only; nothing fetched, nothing published.

    python -m unittest tests.test_gameday_live
"""

import os
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acql.pool import livestate as LS  # noqa: E402
from acql.ui import tokens  # noqa: E402


@dataclass(frozen=True)
class G:
    """What livestate reads from a gameday.GameNow."""

    index: int
    state: str = "pre"
    kickoff: float | None = None
    home_points: int | None = None
    away_points: int | None = None


NOW = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc).timestamp()     # Sun 12:00 PM EDT


class TestNextKickoff(unittest.TestCase):
    def test_the_earliest_game_still_to_start(self):
        games = [G(1, kickoff=NOW + 3600), G(2, kickoff=NOW + 600), G(3, "in", NOW - 900)]
        nxt = LS.next_kickoff(games, NOW)
        self.assertEqual((nxt.at, nxt.indices), (NOW + 600, (2,)))

    def test_games_sharing_a_kickoff_are_all_named(self):
        games = [G(4, kickoff=NOW + 3600), G(2, kickoff=NOW + 3600), G(9, kickoff=NOW + 7200)]
        self.assertEqual(LS.next_kickoff(games, NOW).indices, (2, 4))

    def test_no_countdown_below_zero_once_kickoff_comes(self):
        games = [G(1, kickoff=NOW - 30)]          # the feed has not caught up yet
        self.assertIsNone(LS.next_kickoff(games, NOW))
        self.assertEqual(LS.kicking_off(games, NOW), [1])
        self.assertEqual(LS.countdown_parts(-45), (0, 0, 0, 0))
        self.assertEqual(LS.countdown_text(-45), "00:00")

    def test_postponed_missing_and_invalid_times_are_never_counted_down_to(self):
        games = [G(1, "off", NOW + 600), G(2, kickoff=None), G(3, kickoff=0), G(4, kickoff=-5)]
        self.assertIsNone(LS.next_kickoff(games, NOW))

    def test_no_games_no_kickoff(self):
        self.assertIsNone(LS.next_kickoff([], NOW))

    def test_countdown_text(self):
        self.assertEqual(LS.countdown_text(2 * 86400 + 3 * 3600 + 14 * 60 + 5), "2d 03:14:05")
        self.assertEqual(LS.countdown_text(3 * 3600 + 5), "03:00:05")
        self.assertEqual(LS.countdown_text(65), "01:05")


class TestEastern(unittest.TestCase):
    def test_daylight_and_standard_time(self):
        summer = datetime(2026, 10, 18, 17, 0, tzinfo=timezone.utc).timestamp()   # 1:00 PM EDT
        winter = datetime(2026, 12, 6, 18, 0, tzinfo=timezone.utc).timestamp()    # 1:00 PM EST
        self.assertEqual(LS.eastern(summer)[1], "EDT")
        self.assertEqual(LS.clock_et(summer), "1:00 PM ET")
        self.assertEqual(LS.eastern(winter)[1], "EST")
        self.assertEqual(LS.clock_et(winter), "1:00 PM ET")

    def test_the_changeover_mornings(self):
        # 2026: EDT ends Sun Nov 1 at 2:00 EDT (06:00 UTC); starts Sun Mar 8 at 2:00 EST (07:00 UTC)
        before = datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc).timestamp()
        after = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual((LS.eastern(before)[1], LS.eastern(after)[1]), ("EDT", "EST"))
        self.assertEqual(LS.eastern(datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc).timestamp())[1], "EST")
        self.assertEqual(LS.eastern(datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc).timestamp())[1], "EDT")

    def test_seconds_and_the_day(self):
        at = datetime(2026, 10, 18, 19, 42, 15, tzinfo=timezone.utc).timestamp()
        self.assertEqual(LS.clock_et(at, seconds=True), "3:42:15 PM ET")
        self.assertEqual(LS.kickoff_et(at), "Sun 3:42 PM ET")


class TestSlate(unittest.TestCase):
    def test_counts_by_state_each_game_once(self):
        games = [G(1, "in"), G(2, "final"), G(3, "final"), G(4, "pre", NOW + 60), G(5, "off"), G(6, "pre"),
                 G(2, "final")]                     # game 2 listed twice
        sl = LS.slate(6, games)
        self.assertEqual((sl.total, sl.live, sl.final, sl.upcoming, sl.postponed, sl.untimed), (6, 1, 2, 2, 1, 1))
        self.assertEqual(sl.text(), "6 games · 1 live · 2 final · 2 to play · 1 postponed")
        self.assertFalse(sl.over)

    def test_over_and_empty(self):
        self.assertTrue(LS.slate(6, [G(1, "final"), G(2, "off")]).over)
        self.assertEqual(LS.slate(6, []).text(), "No games")


class TestScoreWatch(unittest.TestCase):
    def test_the_first_look_flashes_nothing(self):
        w = LS.ScoreWatch()
        self.assertEqual(w.accept({1: (7, 3), 2: (0, 0)}, token=1), set())

    def test_a_real_change_flashes_that_game_once(self):
        w = LS.ScoreWatch()
        w.accept({1: (7, 3), 2: (0, 0)}, token=1)
        self.assertEqual(w.accept({1: (7, 10), 2: (0, 0)}, token=2), {1})
        self.assertEqual(w.accept({1: (7, 10), 2: (0, 0)}, token=2), set())    # the same look again
        self.assertEqual(w.accept({1: (7, 10), 2: (0, 0)}, token=3), set())    # a new look, nothing new

    def test_missing_or_malformed_scores_are_not_changes(self):
        w = LS.ScoreWatch()
        w.accept({1: (7, 3)}, token=1)
        self.assertEqual(w.accept({1: None}, token=2), set())
        self.assertEqual(w.accept({1: ("7", 3)}, token=3), set())
        self.assertEqual(w.accept({1: (-1, 3)}, token=4), set())
        self.assertEqual(w.accept({1: (True, 3)}, token=5), set())
        # the baseline kept the last good value through all that
        self.assertEqual(w.accept({1: (7, 3)}, token=6), set())
        self.assertEqual(w.accept({1: (14, 3)}, token=7), {1})

    def test_a_kickoff_is_not_a_score_change(self):
        w = LS.ScoreWatch()
        w.accept({1: None}, token=1)               # not started
        self.assertEqual(w.accept({1: (0, 0)}, token=2), set())

    def test_a_correction_down_is_still_a_change_shown_as_it_is(self):
        w = LS.ScoreWatch()
        w.accept({1: (14, 3)}, token=1)
        self.assertEqual(w.accept({1: (7, 3)}, token=2), {1})


class TestStateWatch(unittest.TestCase):
    def test_transitions_only_on_a_real_change(self):
        w = LS.StateWatch()
        self.assertEqual(w.accept({1: "pre", 2: "in"}), {})
        self.assertEqual(w.accept({1: "pre", 2: "in"}), {})
        self.assertEqual(w.accept({1: "in", 2: "final"}), {1: ("pre", "in"), 2: ("in", "final")})
        self.assertEqual(w.accept({1: "in", 2: "final"}), {})


class TestFreshness(unittest.TestCase):
    def test_fresh_then_stale_by_the_clock_alone(self):
        f = LS.freshness("scores", NOW - 60, NOW - 60, live=True, now=NOW)
        self.assertEqual(f.level, "fresh")
        self.assertEqual(f.headline(), "Updated 1 minute ago")
        f = LS.freshness("scores", NOW - tokens.FRESHNESS["scores_live_s"] - 1, None, live=True, now=NOW)
        self.assertEqual(f.level, "stale")
        self.assertTrue(f.warn)
        # the same age is fine between games, when the feed is looked at every five minutes
        self.assertEqual(LS.freshness("scores", NOW - 200, None, live=False, now=NOW).level, "fresh")

    def test_a_failed_refresh_keeps_the_last_good_time(self):
        good = NOW - 120
        f = LS.freshness("scores", good, NOW, failed=True, error="no connection", now=NOW)
        self.assertEqual(f.level, "failed")
        self.assertEqual(f.last_success, good)
        self.assertEqual(f.last_attempt, NOW)
        self.assertIn("Refresh failed", f.headline())
        self.assertIn(LS.clock_et(good, seconds=True), f.headline())
        self.assertIn("Last attempt", f.detail())
        self.assertIn("no connection", f.detail())

    def test_no_good_look_ever(self):
        self.assertEqual(LS.freshness("scores", None, NOW, failed=True, now=NOW).headline(),
                         "No successful data refresh yet")
        self.assertEqual(LS.freshness("scores", None, None, now=NOW).level, "waiting")

    def test_recovery(self):
        f = LS.freshness("scores", NOW, NOW, failed=False, now=NOW)
        self.assertEqual((f.level, f.error), ("fresh", ""))


class TestCardState(unittest.TestCase):
    def test_status_selection_and_warning_are_separate(self):
        stale = LS.freshness("scores", NOW - 3600, None, live=True, now=NOW)
        cs = LS.card_state("in", selected=True, feed=stale)
        self.assertEqual((cs.status, cs.selected, cs.warn), ("live", True, "stale"))
        cs = LS.card_state("final", selected=True, feed=stale)
        self.assertEqual((cs.status, cs.selected, cs.warn, cs.label), ("final", True, "", "FINAL"))
        error = LS.freshness("scores", None, NOW, failed=True, now=NOW)
        self.assertEqual(LS.card_state("pre", feed=error).warn, "error")
        self.assertEqual(LS.card_state("off").status, "postponed")
        self.assertEqual(LS.card_state("pre").warn, "")


class TestStandingsWatch(unittest.TestCase):
    def test_moves_and_gains_only_after_the_first_table(self):
        w = LS.StandingsWatch()
        self.assertFalse(w.accept([("Ann", 1, 5), ("Bob", 2, 4), ("Cy", 2, 4)]))
        m = w.accept([("Bob", 1, 6), ("Ann", 2, 5), ("Cy", 3, 4)])
        self.assertEqual(m.moved, {"Bob": (2, 1), "Ann": (1, 2), "Cy": (2, 3)})
        self.assertEqual(m.gained, {"Bob": (4, 6)})
        self.assertFalse(w.accept([("Bob", 1, 6), ("Ann", 2, 5), ("Cy", 3, 4)]))     # the same table again

    def test_a_correction_is_not_a_gain(self):
        w = LS.StandingsWatch()
        w.accept([("Ann", 1, 5)])
        m = w.accept([("Ann", 1, 4)])
        self.assertEqual(m.points, {"Ann": (5, 4)})
        self.assertEqual(m.gained, {})

    def test_partial_rows_are_left_out_not_ranked(self):
        w = LS.StandingsWatch()
        w.accept([("Ann", 1, 5), ("", 2, 3), ("Bob", None, 2)])
        self.assertFalse(w.accept([("Ann", 1, 5)]))


class TestKeptScores(unittest.TestCase):
    """feeds/results.py: an empty answer is asked-at, never updated-at."""

    def setUp(self):
        from acql import store
        self.dir = tempfile.TemporaryDirectory()
        self.store = store
        store.use(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.store.use(None)
        self.dir.cleanup()

    def test_an_empty_answer_keeps_the_last_good_time_and_scores(self):
        from acql.feeds import results
        s = results.Score("mia", "buf", 10, 24, state="in", kickoff=NOW - 3600)
        results.save(2026, 7, [s], at=NOW - 300)
        results.save(2026, 7, [], at=NOW)
        self.assertEqual(results.checked_at(2026, 7), NOW)
        self.assertEqual(results.fetched_at(2026, 7), NOW - 300)
        self.assertEqual([(x.away_points, x.home_points) for x in results.load(2026, 7)], [(10, 24)])
        f = LS.scores_freshness(2026, 7, live=True, now=NOW)
        self.assertEqual(f.last_success, NOW - 300)
        self.assertEqual(f.level, "stale")          # 5 minutes with a game on

    def test_a_failure_after_a_good_look_then_recovery(self):
        from acql.feeds import results

        def boom(year, week):
            raise results.ResultsError("ESPN's scoreboard can't be reached")
        s = results.Score("mia", "buf", 10, 24, state="in", kickoff=NOW - 3600)
        results.save(2026, 7, [s], at=NOW - 60)
        results.refresh(2026, [7], now=NOW, force=True, fetcher=boom)
        f = LS.scores_freshness(2026, 7, live=True, now=NOW)
        self.assertEqual((f.level, f.last_success), ("failed", NOW - 60))
        self.assertIn("can't be reached", f.detail())
        self.assertEqual(len(results.load(2026, 7)), 1)              # the scores survived
        results.refresh(2026, [7], now=NOW + 60, force=True,
                        fetcher=lambda y, w: [replace(s, home_points=31)])
        f = LS.scores_freshness(2026, 7, live=True, now=NOW + 60)
        self.assertEqual((f.level, f.last_success, f.error), ("fresh", NOW + 60, ""))

    def test_a_watched_live_game_is_asked_about_every_30_seconds(self):
        from acql.feeds import results
        s = results.Score("mia", "buf", 10, 24, state="in", kickoff=NOW - 3600)
        results.save(2026, 7, [s], at=NOW)
        every = results.LIVE_RECHECK_S
        self.assertEqual(every, 30)
        self.assertEqual(results.due(2026, [7], now=NOW + 20, every=every), [])
        # a window tick landing a moment short of 30 s still looks (the stamp came after the answer)
        self.assertEqual(results.due(2026, [7], now=NOW + 29, every=every), [7])
        # unwatched, it waits the usual five minutes
        self.assertEqual(results.due(2026, [7], now=NOW + 60), [])

    def test_never_a_good_look(self):
        from acql.feeds import results

        def boom(year, week):
            raise results.ResultsError("no connection")
        results.refresh(2026, [8], now=NOW, force=True, fetcher=boom)
        self.assertEqual(LS.scores_freshness(2026, 8, now=NOW).level, "error")


@unittest.skipIf(os.environ.get("ACQL_SKIP_QT") == "1", "Qt tests skipped")
class TestCinemaWindow(unittest.TestCase):
    """Cinema mode in a hidden window: in, out, the same feed, nothing replayed."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _feed(self, states, fresh):
        from acql.ui.cinema import LiveFeed
        feed = LiveFeed()
        feed.week, feed.states, feed.fresh = 7, states, fresh
        return feed

    def test_enter_leave_and_escape(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QWidget
        from acql.ui import cinema, theme

        class Host(QWidget):
            season = None
        host = Host()
        feed = self._feed([], None)
        feed.week = 0                                   # between weeks: an honest empty screen
        win = cinema.CinemaWindow(host, feed, theme.DARK)
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        closed = []
        win.closed.connect(lambda: closed.append(1))
        win.enter()
        self.assertTrue(win.isVisible())
        self.assertTrue(win._tick.isActive())
        self.assertIn("NO WEEK", win.week_label.text())
        self.assertFalse(win.empty.isHidden())
        win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(win.isVisible())
        self.assertFalse(win._tick.isActive())         # nothing ticks once it is gone
        self.assertEqual(closed, [1])
        win.enter()                                     # and back in again
        self.assertTrue(win.isVisible())
        win.leave()

    def test_leaderboard_moves_and_counts_once(self):
        from unittest import mock
        from acql.ui import cinema, motion
        # Animations on, whatever the computer says (GitHub's Windows machines have them off).
        patcher = mock.patch.object(motion, "reduced", lambda: False)
        patcher.start()
        self.addCleanup(patcher.stop)
        board = cinema.Leaderboard()
        board.resize(300, 200)
        board.show_rows([("Ann", 1, 5, False), ("Bob", 2, 4, True)], LS.Movement())
        self.assertEqual(board.rows["Bob"].pos().y(), cinema.ROW_HEIGHT)
        self.assertEqual(board.rows["Bob"].property("you"), "true")
        move = LS.Movement(moved={"Bob": (2, 1), "Ann": (1, 2)}, points={"Bob": (4, 6)})
        board.show_rows([("Bob", 1, 6, True), ("Ann", 2, 5, False)], move)
        self.assertEqual(board.order, ["Bob", "Ann"])
        self.assertIsNotNone(board.rows["Bob"].counter)
        board.rows["Bob"].counter.stop()
        board.show_rows([("Bob", 1, 6, True), ("Ann", 2, 5, False)], LS.Movement())    # a plain redraw
        self.assertEqual(board.rows["Bob"].points.text(), "6")
        self.assertEqual(board.rows["Bob"].pos().y(), 0)


if __name__ == "__main__":
    unittest.main()
