"""The website's shared rules, run in a real browser: one ranking for every
place shown, one freshness rule and one set of words for the score feed, and
kickoff times that follow each date's own clock change.

    python tests/test_site_quality.py

The functions are cut from the joined page itself, so these test what ships.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))

from acql.ui import poolpage  # noqa: E402


def _cut(page: str, start: str, end: str) -> str:
    a = page.index(start)
    return page[a:page.index(end, a)]


def _jsrun():
    import jsrun
    return jsrun


class _Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = poolpage.template()
        helpers = (poolpage.PARTS / "020-small-helpers.js").read_text(encoding="utf-8")
        cls.helpers = helpers[:helpers.index("  function aliveNames()")] + _cut(helpers, "  // ---- places: the one ranking", "  function leaders()")

    def run_js(self, code, answer):
        jsrun = _jsrun()
        try:
            return jsrun.run(self.helpers + code, answer)
        except jsrun.NoBrowser:
            self.skipTest("no Chrome or Edge to run the page's script in")


class TestOneRanking(_Browser):
    def test_ties_share_a_place_and_the_next_is_skipped(self):
        got = self.run_js("", "rankAll({a: 10, b: 8, c: 8, d: 7, e: null})")
        self.assertEqual({k: (v["place"], v["tied"]) for k, v in got.items()},
                         {"a": (1, False), "b": (2, True), "c": (2, True), "d": (4, False)})

    def test_week_and_live_places_read_the_one_ranking(self):
        got = self.run_js("var w = {scores: [{name: 'A', total: 9}, {name: 'B', total: 11}, {name: 'C', total: 9}]};"
                          "var t = {rows: [{c: {name: 'A'}, now: 3}, {c: {name: 'B'}, now: 3}, {c: {name: 'C'}, now: 5}]};",
                          "[weekPlace(w, 'A'), weekPlace(w, 'B'), weekPlace(w, 'C'), weekPlace(w, 'Z'),"
                          " livePlace(t, 'A'), livePlace(t, 'B'), livePlace(t, 'C'), JSON.stringify(w).indexOf('placesCache')]")
        self.assertEqual(got, [2, 1, 2, None, 2, 2, 1, -1])      # the cache never leaks into the data

    def test_every_page_uses_it(self):
        for gone in ("1 + w.scores.filter(function (o) { return o.total >",
                     "1 + t.rows.filter(function (o) { return o.now >"):
            self.assertNotIn(gone, self.page)
        if poolpage._modes_on():
            self.assertIn("function lmRank(values) { return rankAll(values); }", self.page)


class TestFreshness(_Browser):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fresh = (_cut(cls.page, "  // How fresh the scores on screen are", "  // A game's card state")
                     + _cut(cls.page, "  // One formatter for every time shown", "  function kickDay("))

    def state(self, setup):
        return self.run_js("var live = {scores: {}, fetched: null, error: '', failedAt: null};" + self.fresh + setup,
                           "(function () { var f = freshness(); return [f.level, feedLabel(f), f.head]; })()")

    def test_each_state_has_one_word(self):
        game = "live.scores = {x: {state: 'in'}};"
        quiet = "live.scores = {x: {state: 'pre'}};"
        ago = lambda s: f"live.fetched = new Date(Date.now() - {s * 1000});"   # noqa: E731
        self.assertEqual(self.state("")[:2], ["waiting", "Loading"])
        self.assertEqual(self.state("live.error = 'no connection'; live.failedAt = new Date();")[:2], ["error", "Unavailable"])
        self.assertEqual(self.state(game + ago(10))[:2], ["fresh", "Live"])
        self.assertEqual(self.state(quiet + ago(10))[:2], ["fresh", "Up to date"])
        # a game on wants the scores within 90 s; with none on, 15 minutes will do
        self.assertEqual(self.state(game + ago(120))[:2], ["stale", "Stale"])
        self.assertEqual(self.state(quiet + ago(120))[:2], ["fresh", "Up to date"])
        self.assertEqual(self.state(quiet + ago(1000))[:2], ["stale", "Stale"])

    def test_a_failed_refresh_keeps_the_last_good_scores_and_says_when(self):
        level, word, head = self.state("live.scores = {x: {state: 'in'}}; live.fetched = new Date(Date.now() - 40000);"
                                       "live.error = 'HTTP 503'; live.failedAt = new Date();")
        self.assertEqual((level, word), ("failed", "Refresh failed"))
        self.assertIn("showing data from", head)

    def test_recovery_clears_the_failure(self):
        level, word, _ = self.state("live.scores = {x: {state: 'in'}}; live.error = ''; live.failedAt = null; live.fetched = new Date();")
        self.assertEqual((level, word), ("fresh", "Live"))

    def test_the_strip_cinema_and_broadcast_share_the_words(self):
        self.assertIn("function dataLabel(fr) { return feedLabel(fr); }", self.page)
        self.assertIn("var word = feedLabel(fr);", self.page)
        for old in ('"Cached"', '"Delayed"', "Scores unreachable", "Market feed unavailable"):
            self.assertNotIn(old, self.page)


class TestKickoffTimes(_Browser):
    def test_each_date_gets_its_own_zone(self):
        fresh = _cut(self.page, "  // One formatter for every time shown", "  function kickDay(")
        got = self.run_js(fresh, "[zoneName(new Date(Date.UTC(2026, 0, 15, 18))), zoneName(new Date(Date.UTC(2026, 6, 15, 18))),"
                                 " new Intl.DateTimeFormat('en-US', {timeZoneName: 'short'}).formatToParts(new Date(Date.UTC(2026, 0, 15, 18)))"
                                 ".filter(function (p) { return p.type === 'timeZoneName'; })[0].value,"
                                 " new Intl.DateTimeFormat('en-US', {timeZoneName: 'short'}).formatToParts(new Date(Date.UTC(2026, 6, 15, 18)))"
                                 ".filter(function (p) { return p.type === 'timeZoneName'; })[0].value]")
        # the one shared formatter still names each date's own zone (CST in January, CDT in July here)
        self.assertEqual(got[:2], got[2:])


class TestDesktopWords(unittest.TestCase):
    def test_redzone_and_cinema_say_what_the_website_says(self):
        from acql.pool import liveplus as LP
        from acql.pool import livestate as LS

        def fresh(level, age):
            return LS.Freshness("scores", level, 100.0 if level not in ("error", "waiting") else None, 100.0, "", age)
        site = {"waiting": "Loading", "error": "Unavailable", "failed": "Refresh failed", "stale": "Stale"}
        for level, word in site.items():
            self.assertEqual(LP.data_label(fresh(level, 50))[0], word.upper(), level)
        self.assertEqual(LP.data_label(fresh("fresh", 5), live=True)[0], "LIVE")
        self.assertEqual(LP.data_label(fresh("fresh", 5), live=False)[0], "UP TO DATE")
        page = poolpage.template()
        for word in list(site.values()) + ["Live", "Up to date"]:
            self.assertIn(f'"{word}"', page)


class TestAddresses(unittest.TestCase):
    """A chosen week survives a refresh or a shared link; a mode's address is left for the mode."""

    @classmethod
    def setUpClass(cls):
        cls.page = poolpage.template()

    def test_weeks_and_factions_keep_their_week(self):
        self.assertIn('return "#weeks?w=" + state.week;', self.page)
        self.assertIn('return "#factions?w=" + state.fxWeek;', self.page)
        # read back only a week this season has
        self.assertIn('if (wk && v === "weeks" && weekData(Number(wk))) state.week = Number(wk);', self.page)

    def test_the_site_never_rewrites_a_modes_address(self):
        sync = _cut(self.page, "  function syncHash() {", "  function go(view) {")
        self.assertIn("if (base_ && !VIEWS[ALIASES[base_] || base_]) return;", sync)

    def test_a_missing_season_is_said_not_swapped_silently(self):
        if not poolpage._modes_on():
            self.skipTest("league modes are switched off")
        self.assertIn("season isn't in the archive", self.page)
        self.assertIn("LM.missing = String(want)", self.page)


class TestRedZoneFitsASmallLaptop(unittest.TestCase):
    """RedZone must fit 1366 x 768 at 125% (1093 points wide); the picks heading
    used to make it 1245 wide on its own."""

    def test_the_picks_heading_shortens(self):
        src = (ROOT / "acql" / "ui" / "redzone.py").read_text(encoding="utf-8")
        self.assertIn('self.picks_head = ElidedLabel("MY PICKS")', src)
        rib = (ROOT / "acql" / "ui" / "ribbon.py").read_text(encoding="utf-8")
        self.assertIn("self.track.setMinimumHeight(tallest)", rib)


if __name__ == "__main__":
    unittest.main(verbosity=1)
