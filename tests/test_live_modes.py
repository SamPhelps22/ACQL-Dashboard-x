"""RedZone mode and Cinema mode: the shared rules (pool/liveplus.py, worst
places) and both screens in hidden windows - spotlight, filters, hand-overs
between the modes, spoiler-free, standings said once."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acql.pool import gameday as GD  # noqa: E402
from acql.pool import liveplus as LP  # noqa: E402
from acql.pool import livestate as LS  # noqa: E402


def game(i, state="in", *, home=3, away=0, clock="Q2 5:00", red_zone=False, last_play="", possession="",
         situation="", leader=None, home_name="Dallas", away_name="Philadelphia", kickoff=1000.0):
    started = state in ("in", "final")
    margin = (home - away) if started else None
    if leader is None:
        leader = GD.NOBODY if not started or margin == 0 else (GD.HOME if margin > 0 else GD.AWAY)
    g = NS(home=home_name, away=away_name, label=f"{away_name} at {home_name}")
    return NS(index=i, state=state, game=g, home_points=home if started else None, away_points=away if started else None,
              clock=clock if state == "in" else ("Final" if state == "final" else ""), red_zone=red_zone,
              last_play=last_play, possession=possession, situation=situation, started=started, margin=margin,
              leader=leader, kickoff=kickoff)


def real(ns):
    """The same game as a real gameday.GameNow, for the screens."""
    from acql.models import Game
    g = Game(index=ns.index, home=ns.game.home, away=ns.game.away, line=3.0, line_favourite=ns.game.home)
    started = ns.state in ("in", "final")
    return GD.GameNow(game=g, state=ns.state, home_points=ns.home_points, away_points=ns.away_points,
                      left=0.5 if ns.state == "in" else (0.0 if ns.state == "final" else 1.0), kickoff=ns.kickoff,
                      clock=ns.clock, possession=ns.possession, situation=ns.situation, red_zone=ns.red_zone,
                      last_play=ns.last_play, broadcast="FOX", home_record="5-2", away_record="4-3",
                      home_color="", away_color="", expected=3.0, sd=13.0,
                      outlook=GD.Outlook((ns.margin or 0,), (1.0,)), p_home=0.6, p_away=0.4,
                      leader=ns.leader if started else GD.NOBODY, blowout_home=0.05, blowout_away=0.05)


class TestSpotlight(unittest.TestCase):
    def test_red_zone_and_a_fresh_score_lead(self):
        states = [game(0), game(1, red_zone=True), game(2), game(3, state="pre")]
        ranked = LP.spotlight_rank(states, {}, scored_at={2: 990.0}, now=1000.0)
        self.assertEqual([r.index for r in ranked], [1, 2, 0])          # upcoming games are not ranked
        self.assertIn("red_zone", ranked[0].reasons)

    def test_turnover_close_late_and_your_pick(self):
        states = [game(0, last_play="Pass intercepted by J. Smith"), game(1, clock="4th 1:12", home=20, away=17),
                  game(2)]
        ranked = LP.spotlight_rank(states, {2: GD.HOME}, now=0.0)
        reasons = {r.index: r.reasons for r in ranked}
        self.assertIn("turnover", reasons[0])
        self.assertIn("close_late", reasons[1])
        self.assertIn("mine", reasons[2])

    def test_a_priority_switched_off_counts_for_nothing(self):
        states = [game(0, red_zone=True), game(1, last_play="Fumble recovered by DAL")]
        ranked = LP.spotlight_rank(states, {}, weights={"red_zone": 0}, now=0.0)
        self.assertEqual(ranked[0].index, 1)
        self.assertNotIn("red_zone", ranked[1].reasons)

    def test_switching_waits_holds_by_hand_and_pins(self):
        a, b = game(0), game(1, red_zone=True)
        spot = LP.Spotlight()
        self.assertEqual(spot.update(LP.spotlight_rank([a], {}, now=0), [a], now=0), 0)
        both = [a, b]
        ranked = LP.spotlight_rank(both, {}, now=5)
        self.assertEqual(spot.update(ranked, both, now=5), 0)            # not before DWELL
        self.assertEqual(spot.update(ranked, both, now=0 + LP.DWELL), 1)  # then the better game
        spot.choose_by_hand(0, now=100)
        self.assertEqual(spot.update(ranked, both, now=100 + LP.MANUAL_HOLD - 1), 0)
        self.assertEqual(spot.update(ranked, both, now=100 + LP.MANUAL_HOLD + LP.DWELL + 1), 1)
        spot.pin(0)
        self.assertEqual(spot.update(ranked, both, now=10_000), 0)
        spot.pin(None)
        spot.auto = False
        self.assertEqual(spot.update(ranked, both, now=20_000), 0)       # auto off: stays put

    def test_nothing_on_offers_the_next_kickoff(self):
        states = [game(0, state="final"), game(1, state="pre", kickoff=500), game(2, state="pre", kickoff=300)]
        self.assertEqual(LP.Spotlight().update([], states, now=0), 2)


class TestDrive(unittest.TestCase):
    def code(self, name):
        return {"Dallas": "dal", "Washington": "was", "Philadelphia": "phi"}.get(name, "")

    def test_field_position_both_halves_and_aliases(self):
        own = game(0, possession="home", situation="2nd & 7 at DAL 23")
        self.assertEqual(LP.drive(own, self.code).to_goal, 77)
        theirs = game(0, possession="home", situation="1st & Goal at PHI 4")
        d = LP.drive(theirs, self.code)
        self.assertEqual((d.to_goal, d.distance, d.down_text), (4, "Goal", "1st & Goal"))
        wsh = game(0, possession="away", situation="3rd & 2 at WSH 40", away_name="Washington")
        self.assertEqual(LP.drive(wsh, self.code).to_goal, 60)

    def test_nothing_is_guessed(self):
        self.assertIsNone(LP.drive(game(0, possession="home", situation=""), self.code))
        self.assertIsNone(LP.drive(game(0, situation="2nd & 7 at DAL 23"), self.code))        # no possession
        self.assertIsNone(LP.drive(game(0, state="final", possession="home", situation="x"), self.code))
        unknown = LP.drive(game(0, possession="home", situation="2nd & 7 at XYZ 23"), self.code)
        self.assertIsNone(unknown.to_goal)


class TestPicksPoolAndData(unittest.TestCase):
    def test_pick_status(self):
        self.assertEqual(LP.pick_status(game(0, state="pre"), GD.HOME), "upcoming")
        self.assertEqual(LP.pick_status(game(0, home=7, away=0), GD.HOME), "winning")
        self.assertEqual(LP.pick_status(game(0, home=7, away=0), GD.AWAY), "losing")
        self.assertEqual(LP.pick_status(game(0, home=7, away=7), GD.AWAY), "level")
        self.assertEqual(LP.pick_status(game(0, state="final", home=7, away=0), GD.HOME), "correct")
        self.assertEqual(LP.pick_status(game(0, state="final", home=7, away=0), GD.AWAY), "incorrect")
        self.assertEqual(LP.pick_status(game(0, state="final", home=7, away=7), GD.AWAY), "push")
        self.assertEqual(LP.pick_status(game(0, state="off"), GD.AWAY), "postponed")

    def test_pool_changes_are_said_once(self):
        watch = LP.PoolWatch()
        rows = [("a", "Ann", 1, 9), ("b", "Bob", 2, 8), ("y", "You", 5, 6), ("c", "Cat", 4, 7)]
        self.assertEqual(watch.events(rows, "y"), [])                    # the first table is the baseline
        self.assertEqual(watch.events(rows, "y"), [])                    # the same table says nothing
        rows2 = [("b", "Bob", 1, 10), ("a", "Ann", 2, 9), ("y", "You", 3, 8), ("c", "Cat", 4, 7)]
        said = watch.events(rows2, "y")
        self.assertIn(("pool", "Bob takes the lead"), said)
        self.assertIn(("you", "You climb to 3rd (from 5th)"), said)
        watch.events(rows, "y")
        again = watch.events(rows2, "y")                                 # back and forth: not said twice
        self.assertEqual(again, [])

    def test_data_labels_are_honest(self):
        def fresh(level, age):
            return LS.Freshness("scores", level, 100.0 if level != "error" else None, 100.0, "", age)
        self.assertEqual(LP.data_label(None)[0], "UNAVAILABLE")
        self.assertEqual(LP.data_label(fresh("error", None))[0], "UNAVAILABLE")
        self.assertEqual(LP.data_label(fresh("failed", 50))[0], "CACHED")
        self.assertEqual(LP.data_label(fresh("stale", 4000))[0], "STALE")
        self.assertEqual(LP.data_label(fresh("fresh", 200))[0], "DELAYED")
        self.assertEqual(LP.data_label(fresh("fresh", 10))[0], "LIVE")
        self.assertIn("polled", LP.data_label(fresh("fresh", 10))[1])

    def test_filters(self):
        states = [game(0, state="pre"), game(1), game(2, state="final"), game(3, state="off")]
        self.assertEqual([s.index for s in LP.filter_states(states, "live")], [1])
        self.assertEqual([s.index for s in LP.filter_states(states, "upcoming")], [0, 3])
        self.assertEqual([s.index for s in LP.filter_states(states, "final")], [2])
        self.assertEqual([s.index for s in LP.filter_states(states, "mine", {2: 1})], [2])
        self.assertEqual(len(LP.filter_states(states, "all")), 4)


class TestWorstPlaces(unittest.TestCase):
    @staticmethod
    def _state(i, state="pre", leader=0, line=None, fav=None, routed=(0.0, 0.0)):
        home, away = f"H{i}", f"A{i}"
        g = NS(index=i, home=home, away=away, line=line, line_favourite={"home": home, "away": away}.get(fav))
        return NS(index=i, game=g, state=state, leader=leader, blowout_home=routed[0], blowout_away=routed[1])

    def test_against_every_way_the_week_can_go(self):
        import itertools
        import random
        rng = random.Random(17)
        for _ in range(150):
            states = [self._state(i, rng.choice(["pre", "in", "final", "off"]), rng.choice([1, -1]),
                                  *rng.choice([(None, None), (3, "home"), (7.5, "away"), (16.5, "home")]))
                      for i in range(rng.randint(1, 4))]
            cards = [GD.Card(key=str(c), name=str(c),
                             picks={i: s for i in range(len(states)) if (s := rng.choice([1, -1, 0]))},
                             losers=[(i, rng.choice([1, -1])) for i in range(len(states)) if rng.random() < .3],
                             in_field=c > 0 or rng.random() < .5)
                     for c in range(rng.randint(2, 5))]
            worst = GD.worst_places(states, cards)
            best = GD.best_places(states, cards)
            field = [c for c, k in enumerate(cards) if k.in_field]
            for c, card in enumerate(cards):
                places = []
                for combo in itertools.product(*(GD._ways(st) for st in states)):
                    tot = [sum((bool(k.picks.get(g)) and k.picks.get(g) == side)
                               + sum((hr if held == 1 else ar) for gi, held in k.losers if gi == g)
                               for g, (side, hr, ar) in enumerate(combo)) for k in cards]
                    places.append(1 + sum(1 for r in field if r != c and tot[r] > tot[c]))
                self.assertEqual(worst[card.key], max(places))
                self.assertLessEqual(best[card.key], worst[card.key])


class TestScreens(unittest.TestCase):
    """Both modes in hidden windows, on one shared feed."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QCoreApplication, QSettings
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        QCoreApplication.setOrganizationName("ACQL Test")
        QCoreApplication.setApplicationName("ACQL Live Modes Test")
        QSettings().clear()

    def _host(self):
        from PySide6.QtWidgets import QWidget
        from acql.ui.cinema import LiveFeed

        class Host(QWidget):
            season = None
            cinema = None
            redzone = None
            opened: list = []

            def open_game(self, week, index):
                self.opened.append((week, index))
        host = Host()
        feed = LiveFeed()
        feed.week = 7
        feed.states = [real(game(0, state="pre", kickoff=4e9)),
                       real(game(1, red_zone=True, possession="home", situation="1st & Goal at PHI 4")),
                       real(game(2, state="final", home=10, away=24, home_name="Chicago", away_name="New England"))]
        import time
        now = time.time()
        feed.fresh = LS.freshness("scores", now - 5, now - 5, live=True, now=now)
        return host, feed

    def test_cinema_filters_density_detail_and_hand_over(self):
        from PySide6.QtCore import Qt
        from acql.ui import cinema, theme
        host, feed = self._host()
        win = cinema.CinemaWindow(host, feed, theme.DARK)
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        win.resize(1600, 900)
        win.enter()
        self.assertEqual(set(win.tiles), {0, 1, 2})
        win.set_filter("live")
        self.assertEqual(win._order, [1])
        win.set_filter("final")
        self.assertEqual(win._order, [2])
        win.set_filter("mine")                                  # no sheet here: an honest empty grid
        self.assertFalse(win.empty.isHidden())
        win.set_filter("all")
        self.assertEqual(len(win._order), 3)
        cols = win._columns_for(1600)
        win.set_density(1)
        self.assertEqual(win._columns_for(1600), cols + 1)
        win.set_density(-1)
        self.assertEqual(win._columns_for(1600), max(1, cols - 1))
        win.set_density(0)
        win._choose(1)
        self.assertTrue(win.detail.isVisibleTo(win))
        self.assertIn("1st & Goal", win.detail_body.text())
        self.assertEqual(feed.selected, 1)
        win.open_selected()
        self.assertEqual(host.opened[-1], (7, 1))
        self.assertFalse(win.isVisible())
        # the health line says what the data is, and that it is polled
        win.enter()
        self.assertIn("LIVE", win.health.text())
        self.assertIn("polling", win.health.text())
        win.leave()

    def test_halftime_and_pool_events_reach_the_feed_once(self):
        from acql.ui.cinema import LiveFeed
        feed = LiveFeed()
        rows = [("a", "Ann", 1, 9), ("b", "Bob", 2, 8)]
        feed.note_pool(rows, "")
        feed.note_pool([("b", "Bob", 1, 10), ("a", "Ann", 2, 9)], "")
        feed.note_pool([("b", "Bob", 1, 10), ("a", "Ann", 2, 9)], "")    # a second screen, same table
        self.assertEqual([t for _at, t, _k in feed.recent], ["Bob takes the lead"])

    def test_redzone_spotlight_queue_spoilers_and_switch(self):
        from PySide6.QtCore import Qt
        from acql.ui import cinema, redzone, theme
        host, feed = self._host()
        feed.states.append(real(game(3, home_name="Denver", away_name="Arizona")))
        win = redzone.RedZoneWindow(host, feed, theme.DARK)
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        win.fit_stream = lambda quiet=False: None               # never touch a real window in a test
        win.resize(1600, 900)
        win.refresh()
        self.assertEqual(feed.spotlight.current, 1)             # the red-zone game
        self.assertIn("RED ZONE", win.spot_reason.text())
        self.assertIn("1st & Goal", win.down.text())
        self.assertEqual(win.field.to_goal, 4)
        self.assertEqual(win._queue, [3])
        win.choose_game(3)                                      # from the queue or the ticker
        self.assertEqual(feed.spotlight.current, 3)
        self.assertIn("YOUR CHOICE", win.spot_reason.text())
        win.toggle_pin()
        self.assertEqual(feed.spotlight.pinned, 3)
        cinema.set_pref("spoilers", True)
        try:
            win.refresh()
            self.assertNotIn("24", win.spot_line.text())
            self.assertTrue(win.spoiler_note.isVisibleTo(win))
            self.assertFalse(win.board_scroll.isVisibleTo(win))
        finally:
            cinema.set_pref("spoilers", False)
        win.refresh()
        self.assertIn("LIVE", win.data_tag.text())
        # over to Cinema: the featured game arrives chosen
        host.cinema = cinema.CinemaWindow(host, feed, theme.DARK)
        host.cinema.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        host.cinema_showing = lambda: host.cinema.isVisible()
        host.toggle_cinema = host.cinema.enter
        win.to_cinema()
        self.assertTrue(host.cinema.isVisible())
        self.assertEqual(host.cinema.selected, 3)
        host.cinema.leave()


if __name__ == "__main__":
    unittest.main()
