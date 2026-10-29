"""Explain This: the metric registry, the evidence behind each number, and the
honesty rules - nothing is called verified unless a recount from another
input agreed, nothing is made up, and no folder path reaches the public page.

    python tests/test_explain.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))

from acql import store  # noqa: E402
from acql.feeds.results import Score  # noqa: E402
from acql.models import Game, Player, PlayerWeek, Season, Week  # noqa: E402
from acql.site import explain  # noqa: E402
from acql.ui import poolpage  # noqa: E402
from acql.ui.pages import base as _pagebase  # noqa: E402


def _season() -> Season:
    """Week 1: two games, ESPN has both. Week 2: no ESPN scores kept.
    Week 3: ESPN has one of the two games."""
    s = Season(title="Test")
    s.results_year = 2026

    def games():
        return [Game(index=1, away="BUF", home="MIA", winner="BUF", line=3.0, line_favourite="BUF"),
                Game(index=2, away="NE", home="NYJ", winner="NYJ")]

    def line(who, n, picks, total, bl=0, bl_picks=()):
        return PlayerWeek(player=who, week=n, correct_picks=picks, total_wins=total,
                          regular_wins=total - bl, big_loser_wins=bl, big_loser_picks=list(bl_picks))
    for n in (1, 2, 3):
        s.weeks[n] = Week(number=n, games=games(), game_count=2, source=Path("C:/secret folder/stats week %d.xls" % n))
    # A: right twice plus a Big Loser (NE lost by 30) = 3, as on file
    s.weeks[1].lines["a"] = line("A", 1, {1: "BUF", 2: "NYJ"}, 3, bl=1, bl_picks=["NE"])
    # B: right once = 1, as on file
    s.weeks[1].lines["b"] = line("B", 1, {1: "BUF", 2: "NE"}, 1)
    # C: right once, but the file says 3
    s.weeks[1].lines["c"] = line("C", 1, {1: "MIA", 2: "NYJ"}, 3)
    for n in (2, 3):
        for k in "abc":
            s.weeks[n].lines[k] = line(k.upper(), n, {1: "BUF", 2: "NYJ"}, 2)
    s.players = {
        "a": Player(key="a", display="A", wins=7, pos=1, prev_pos=2, big_loser_points=1),
        "b": Player(key="b", display="B", wins=5, pos=3, prev_pos=1),
        "c": Player(key="c", display="C", wins=7, pos=2, prev_pos=3),
    }
    s.current_week = 3
    return s


SCORES = {
    1: [Score(away="buf", home="mia", away_points=20, home_points=10, state="post", final=True),
        Score(away="ne", home="nyj", away_points=10, home_points=40, state="post", final=True)],
    2: [],
    3: [Score(away="buf", home="mia", away_points=20, home_points=10, state="post", final=True),
        Score(away="ne", home="nyj", state="pre")],
}


def _shown(season: Season) -> list[dict]:
    return [{"name": p.display, "wins": p.wins, "place": p.pos, "move": p.prev_pos - p.pos,
             "big_loser": float(p.big_loser_points), "suicide": {"alive": False, "out": None}}
            for p in season.players.values()]


class _Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.use(Path(self.tmp.name) / "t.db")
        self._log = _pagebase.log_path
        _pagebase.log_path = lambda: Path(self.tmp.name) / "log.txt"

    def tearDown(self):
        store.use(None)
        _pagebase.log_path = self._log
        self.tmp.cleanup()

    def build(self, season=None):
        season = season or _season()
        return explain.build(season, weeks=[1, 2, 3], players=_shown(season), official=True, generated="2026-10-28 09:00",
                             scores_for=lambda year, n: SCORES.get(n, []), sheet_for=lambda n: None)


class TestEvidence(_Store):
    def test_verified_only_when_an_independent_recount_agrees(self):
        ex = self.build()
        wk = {name: c["weeks"]["1"] for name, c in ex["coaches"].items()}
        self.assertEqual(wk["A"][:3], [explain.VERIFIED, 3, 3])
        self.assertEqual(wk["B"][:3], [explain.VERIFIED, 1, 1])
        self.assertEqual(wk["C"][:3], [explain.DIFFERS, 1, 3])
        self.assertEqual(wk["A"][4], 1)                        # the Big Loser point, from ESPN's margin

    def test_missing_scores_are_unchecked_and_part_scores_partial(self):
        ex = self.build()
        for c in ex["coaches"].values():
            self.assertEqual(c["weeks"]["2"][0], explain.UNCHECKED)
            self.assertEqual(c["weeks"]["3"][0], explain.PARTIAL)
            self.assertIsNone(c["weeks"]["3"][1])             # no made-up recount
        self.assertTrue(any("No ESPN final scores" in i for i in ex["weeks"]["2"]["issues"]))
        self.assertTrue(any("1 of 2" in i for i in ex["weeks"]["3"]["issues"]))

    def test_season_figures_are_cross_checks_never_verified(self):
        ex = self.build()
        for c in ex["coaches"].values():
            for field in ("wins", "place", "move"):
                self.assertNotEqual(c[field]["status"], explain.VERIFIED, field)
        self.assertEqual(ex["coaches"]["A"]["wins"]["status"], explain.CROSS)      # 3+2+2 = 7
        self.assertEqual(ex["coaches"]["B"]["wins"]["sum_of_weeks"], 5)              # 1+2+2, as shown
        s = _season()
        s.players["b"].wins = 6                                # the export says one more
        self.assertEqual(self.build(s)["coaches"]["B"]["wins"]["status"], explain.DIFFERS)

    def test_tie_order_from_the_export_is_consistent_not_a_fault(self):
        ex = self.build()
        a, c = ex["coaches"]["A"]["place"], ex["coaches"]["C"]["place"]     # both on 7
        self.assertEqual((a["recount"], c["recount"]), (1, 1))
        self.assertEqual(a["status"], explain.CROSS)
        self.assertEqual(c["status"], explain.CROSS)
        self.assertIn("tie order", c["note"])
        s = _season()
        s.players["c"].pos = 3                                 # outside the tied group
        s.players["b"].pos = 2
        self.assertEqual(self.build(s)["coaches"]["C"]["place"]["status"], explain.DIFFERS)

    def test_big_loser_recounted_from_final_margins_only_when_every_week_allows(self):
        ex = self.build()
        bl = ex["coaches"]["A"]["big_loser"]
        self.assertIsNone(bl["independent"])                   # weeks 2 and 3 can't be recounted
        self.assertEqual(bl["status"], explain.CROSS)
        s = _season()
        ex = explain.build(s, weeks=[1], players=_shown(s), official=False,
                           scores_for=lambda y, n: SCORES[1], sheet_for=lambda n: None)
        self.assertEqual(ex["coaches"]["A"]["big_loser"]["independent"], 1.0)
        self.assertEqual(ex["coaches"]["A"]["big_loser"]["status"], explain.VERIFIED)

    def test_no_folder_path_reaches_the_page(self):
        text = json.dumps(self.build())
        self.assertNotIn("secret folder", text)
        self.assertIn("stats week 1.xls", text)
        self.assertNotRegex(text, r"[A-Za-z]:[\\/]")
        self.assertEqual(explain._plain("could not read C:\\a\\b\\stats.xls"), "could not read stats.xls")
        self.assertEqual(explain._file("C:\\a b\\c d\\picks Week 7.xls"), "picks Week 7.xls")
        self.assertIsNone(explain._file(""))

    def test_a_failed_recount_is_reported_not_hidden(self):
        def boom(year, n):
            raise OSError("disk")
        s = _season()
        ex = explain.build(s, weeks=[1], players=_shown(s), official=True, scores_for=boom, sheet_for=lambda n: None)
        self.assertTrue(any("failed" in i for i in ex["weeks"]["1"]["issues"]))
        self.assertTrue(all(c["weeks"]["1"][0] == explain.UNCHECKED for c in ex["coaches"].values()))


class TestRegistry(unittest.TestCase):
    def test_every_metric_is_described(self):
        for key, m in explain.METRICS.items():
            for field in ("label", "definition", "method", "rules", "reads"):
                self.assertTrue(m.get(field), (key, field))

    def test_also_shown_in_is_found_in_the_page_code(self):
        where = explain.shown_in()
        self.assertIn("Standings", where["place"])
        self.assertIn("Head-to-head", where["h2h"])
        self.assertIn("Side pools", where["big_loser"])
        self.assertIn("One week", where["weekly_score"])

    def test_every_tag_in_the_page_names_a_known_metric_and_the_panel_handles_it(self):
        tagged = set()
        for path in poolpage.PARTS.glob("*.js"):
            for args in _calls(path.read_text(encoding="utf-8"), "xa("):
                if len(args) > 1:
                    tagged.update(re.findall(r'"([^"]*)"', args[1]))
        self.assertGreaterEqual(len(tagged), 6)
        self.assertLessEqual(tagged, set(explain.METRICS))
        panel = (poolpage.EXPLAIN_DIR / "535-explain-this.js").read_text(encoding="utf-8")
        for key in explain.METRICS:
            self.assertIn('"' + key + '"', panel, key)


class TestSharedPlaces(unittest.TestCase):
    def test_equal_wins_share_a_place_and_the_next_is_skipped(self):
        wins = {"A": 70, "B": 60, "C": 60, "D": 60, "E": 55}
        last = {"A": 10, "B": 10, "C": 5, "D": 10, "E": 10}       # before: A60 B50 C55 D50 E45
        players = [{"name": n, "wins": w, "weekly": {"2": last[n]}, "move": None} for n, w in wins.items()]
        poolpage._share_places(players, None, [1, 2])
        got = {p["name"]: (p["place"], p["tied"], p["move"]) for p in players}
        self.assertEqual(got, {"A": (1, False, 0), "B": (2, True, 1), "C": (2, True, 0),
                               "D": (2, True, 1), "E": (5, False, 0)})


class TestPage(unittest.TestCase):
    def test_the_panel_is_inside_the_page_script_and_off_means_gone(self):
        page = poolpage.template()
        self.assertIn("function openExplain(", page)
        self.assertIn(".xp-panel", page)
        self.assertLess(page.index("function openExplain("), page.rindex("})();"))
        was = poolpage.EXPLAIN
        poolpage.EXPLAIN = False
        try:
            off = poolpage.template()
        finally:
            poolpage.EXPLAIN = was
        self.assertNotIn("function openExplain(", off)
        self.assertNotIn(".xp-panel", off)
        self.assertIn("function xa(", off)                     # tags stay, and do nothing


def _calls(text: str, name: str) -> list[list[str]]:
    """The top-level arguments of every call to `name` in some JavaScript."""
    out = []
    at = text.find(name)
    while at >= 0:
        if not text[max(0, at - 9):at].endswith("function "):
            i, depth, quote, args, cur = at + len(name), 1, "", [], ""
            while i < len(text) and depth:
                ch = text[i]
                if quote:
                    if ch == "\\":
                        cur += ch + text[i + 1]
                        i += 2
                        continue
                    if ch == quote:
                        quote = ""
                elif ch in "\"'":
                    quote = ch
                elif ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                    if not depth:
                        break
                elif ch == "," and depth == 1:
                    args.append(cur.strip())
                    cur = ""
                    i += 1
                    continue
                cur += ch
                i += 1
            args.append(cur.strip())
            out.append(args)
        at = text.find(name, at + 1)
    return out


def _jsrun():
    import jsrun
    return jsrun


class TestTagHelper(unittest.TestCase):
    def test_xa_sets_attributes_and_ignores_no_metric(self):
        helpers = (poolpage.PARTS / "020-small-helpers.js").read_text(encoding="utf-8")
        code = helpers[:helpers.index("  function svgEl(")] + helpers[helpers.index("  function xa("):helpers.index("  function leaders()")]
        jsrun = _jsrun()
        try:
            got = jsrun.run(code, "(function () { var a = xa(el('span', {text: '7'}), 'place', 'Ann', 3, 'Bo'), b = xa(el('span'), null, 'Ann');"
                                  " return [a.getAttribute('data-x'), a.getAttribute('data-xc'), a.getAttribute('data-xw'), a.getAttribute('data-xb'), b.hasAttribute('data-x')]; })()")
        except jsrun.NoBrowser:
            self.skipTest("no Chrome or Edge to run the page's script in")
        self.assertEqual(got, ["place", "Ann", "3", "Bo", False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
