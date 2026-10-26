"""The website's layout after the 2026-10-26 cleanup: every page has one home in
the navigation, each question is answered in one place, and the numbers shown in
more than one place come from one calculation.

    python tests/test_site_layout.py

These read the joined page (pool_page parts plus the league modes) as text; the
league modes tests drive the modes' engine itself.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql.ui import poolpage  # noqa: E402


def _function(page: str, name: str) -> str:
    """The text of one top-level page function, up to the next one."""
    start = page.index("  function " + name + "(")
    nxt = page.find("\n  function ", start + 10)
    return page[start:nxt if nxt > 0 else len(page)]


class TestNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = poolpage.template()
        block = re.search(r"var SECTIONS = \[(.*?)\n  \];", cls.page, re.S).group(1)
        cls.sections = {m.group(1): re.findall(r'"(\w+)"', m.group(2))
                        for m in re.finditer(r'id: "(\w+)".*?views: \[([^\]]*)\]', block)}
        views = re.search(r"var VIEWS = \{(.*?)\n  \};", cls.page, re.S).group(1)
        cls.views = re.findall(r"^\s+(\w+): \{ label:", views, re.M)

    def test_every_page_has_exactly_one_section(self):
        placed = [v for vs in self.sections.values() for v in vs]
        self.assertEqual(len(placed), len(set(placed)), "a page is listed under two sections")
        self.assertEqual(set(self.views) - {"me"} - set(placed), set(), "a page no section leads to")

    def test_sections_answer_one_kind_of_question_each(self):
        self.assertEqual(list(self.sections), ["home", "week", "standings", "explore", "pools"])
        self.assertEqual(self.sections["standings"], ["standings", "awards", "history"])
        self.assertEqual(self.sections["explore"], ["charts", "h2h", "factions", "teams"])
        self.assertEqual(self.sections["pools"], ["pools", "money"])

    def test_the_modes_live_in_explore_not_a_home_page_block(self):
        if not poolpage._modes_on():
            self.skipTest("league modes are switched off")
        shell = (poolpage.MODES_DIR / "522-modes-shell.js").read_text(encoding="utf-8")
        self.assertIn('getAttribute("data-section") === "explore"', shell)
        self.assertIn('.group[data-section="explore"] .links', shell)
        self.assertNotIn('el("b", { text: "League modes" })', shell, "the separate League modes menu group is gone")
        self.assertIn("v.appendChild(lmLauncher())", shell, "the home page's row sits at its foot")


class TestOneHomeForEachQuestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = poolpage.template()

    def test_home_and_live_show_the_short_side_pool_word(self):
        for name in ("previewHome", "gamedayHome", "finalHome", "liveView"):
            body = _function(self.page, name)
            self.assertIn("weekPoolsBrief(t)", body, name)
            self.assertNotIn("weekSuicideCard(", body, name)
            self.assertNotIn("weekLosersCard(", body, name)
        self.assertIn("twoUp([weekSuicideCard(t), weekLosersCard(t)])", _function(self.page, "poolsView"))

    def test_the_home_page_says_who_leads_before_kickoff(self):
        self.assertIn("tableTop()", _function(self.page, "previewHome"))

    def test_charts_no_longer_repeats_the_coach_and_money_charts(self):
        charts = _function(self.page, "chartsView")
        self.assertNotIn('chartBox("spread"', charts)
        self.assertNotIn('chartBox("money"', charts)
        self.assertIn('chartBox("money-page"', _function(self.page, "moneyChartModule"))
        self.assertIn("weekScoreChart(p, w)", _function(self.page, "trendModule"))

    def test_the_coach_page_has_one_week_by_week_table(self):
        coach = _function(self.page, "coachView")
        self.assertNotIn("maxModule", self.page)
        self.assertIn('text: "Of max"', coach)
        self.assertIn('"data-card": "weeks"', coach)

    def test_the_title_race_does_not_repeat_the_table(self):
        race = _function(self.page, "raceCard")
        self.assertIn('text: "Per week"', race)
        self.assertNotIn('text: "Wins"', race)
        self.assertNotIn('text: "Back"', race)


class TestOneCalculation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = poolpage.template()

    def test_side_pool_cards_and_the_short_word_share_their_tallies(self):
        self.assertIn("weekSuicideTally(t)", _function(self.page, "weekSuicideCard"))
        self.assertIn("weekLosersTally(t)", _function(self.page, "weekLosersCard"))
        brief = _function(self.page, "weekPoolsBrief")
        self.assertIn("weekSuicideTally(t)", brief)
        self.assertIn("weekLosersTally(t)", brief)

    def test_suicide_count_counts_everyone_still_in(self):
        self.assertIn("aliveNames().filter(function (n) { return !carded[n]; })", _function(self.page, "weekSuicideTally"))

    def test_head_to_head_is_worked_out_once(self):
        if not poolpage._modes_on():
            self.skipTest("league modes are switched off")
        vs = _function(self.page, "lmVs")
        self.assertIn("compare(a, b, st.from, st.to)", vs)
        self.assertNotIn("sideOf(", vs)
        self.assertIn("function compare(a, b, from, to)", self.page)


if __name__ == "__main__":
    unittest.main(verbosity=1)
