"""Rulebook Explorer, Power Rankings, Connection Map and the Import Workbench.

    python tests/test_four_features.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))

from acql import config  # noqa: E402
from acql.feeds import results  # noqa: E402
from acql.pool import importbench, powerrank, rulebook  # noqa: E402
from acql.ui import poolpage  # noqa: E402

PARTS = ROOT / "acql" / "ui" / "pool_page"


# ---- rulebook ------------------------------------------------------------------------------
class TestRulebook(unittest.TestCase):
    def setUp(self):
        self.book = rulebook.rulebook("2026", 40)

    def test_every_rule_is_complete_and_unique(self):
        ids = [r["id"] for r in self.book["rules"]]
        self.assertEqual(len(ids), len(set(ids)))
        cats = {c["id"] for c in self.book["categories"]}
        for r in self.book["rules"]:
            self.assertIn(r["category"], cats)
            self.assertIn(r["status"], self.book["statuses"])
            self.assertTrue(r["source"], r["id"])
            if r["status"] != rulebook.UNVERIFIED:
                self.assertTrue(r["example"].startswith("Hypothetical"), r["id"])

    def test_every_category_has_a_rule(self):
        used = {r["category"] for r in self.book["rules"]}
        self.assertEqual(used, {c["id"] for c in self.book["categories"]})

    def test_numbers_come_from_the_scoring_constants(self):
        big = next(r for r in self.book["rules"] if r["id"] == "bigloser-picks")
        self.assertIn(f"{results.BLOWOUT} points or more", big["rule"])
        self.assertIn(f"{config.BIG_LOSER_PICKS} teams", big["rule"])
        fee = next(r for r in self.book["rules"] if r["id"] == "buy-in")
        self.assertIn("$40", fee["rule"])

    def test_line_rule_matches_the_grading(self):
        from acql.analytics import line_need
        self.assertEqual(line_need(3), 3)       # a win by exactly the line counts for the favourite
        self.assertEqual(line_need(6.5), 7)     # the rule's example: 6.5 needs 7
        rule = next(r for r in self.book["rules"] if r["id"] == "lined-games")
        self.assertIn("needed 7", rule["example"])

    def test_tie_breaker_matches_the_standings_code(self):
        from acql.pool import standings
        self.assertIn("a tie goes to whoever was higher the week before", standings.__doc__)
        rule = next(r for r in self.book["rules"] if r["id"] == "season-tie")
        self.assertIn("week before", rule["rule"])

    def test_unwritten_rules_are_marked_unverified(self):
        unverified = {r["id"] for r in self.book["rules"] if r["status"] == rulebook.UNVERIFIED}
        self.assertTrue({"suicide-reuse", "suicide-prize", "bigloser-prize", "rule-versions"} <= unverified)

    def test_only_the_documented_season(self):
        self.assertEqual(self.book["seasons"], ["2026"])


# ---- power rankings ------------------------------------------------------------------------
WEEKLY = {"A": {"1": 10, "2": 8, "3": 9, "4": 12}, "B": {"1": 9, "2": 10, "3": 8, "4": 7},
          "C": {"1": 10, "2": 7, "3": 6, "4": 8}, "D": {"1": 5, "3": 12, "4": 9}}


class TestPowerRankings(unittest.TestCase):
    def test_by_hand(self):
        rows = {r["name"]: r for r in powerrank.rankings(WEEKLY, 4)}
        avg = {1: 8.5, 2: 25 / 3, 3: 8.75, 4: 9.0}
        rel_a = [10 - 8.5, 8 - 25 / 3, 9 - 8.75, 12 - 9]
        self.assertAlmostEqual(rows["A"]["recent"], round(sum(rel_a[1:]) / 3, 2))
        self.assertAlmostEqual(rows["A"]["earlier"], round(rel_a[0], 2))
        self.assertEqual(rows["A"]["rank"], 1)
        self.assertEqual(avg[2], 25 / 3)

    def test_missed_week_is_left_out(self):
        rows = {r["name"]: r for r in powerrank.rankings(WEEKLY, 4)}
        self.assertEqual(rows["D"]["weeks"], 3)
        self.assertEqual(rows["D"]["last3"], [None, 12, 9])

    def test_cutoff_uses_no_later_week(self):
        before = powerrank.rankings(WEEKLY, 2)
        changed = json.loads(json.dumps(WEEKLY))
        for s in changed.values():
            s["3"] = 0
            s["4"] = 16
        self.assertEqual(before, powerrank.rankings(changed, 2))
        snap = powerrank.history(WEEKLY)["weeks"]
        self.assertEqual(snap[1]["rows"], [dict(r, move=snap[1]["rows"][i]["move"]) for i, r in enumerate(before)])

    def test_ties_share_a_place(self):
        rows = powerrank.rankings({"X": {"1": 8}, "Y": {"1": 8}, "Z": {"1": 5}}, 1)
        self.assertEqual([r["rank"] for r in rows], [1, 1, 3])

    def test_no_weeks_no_rankings(self):
        self.assertEqual(powerrank.rankings({"X": {}}, 3), [])
        self.assertEqual(powerrank.rankings(WEEKLY, 0), [])

    def test_small_samples_flagged(self):
        rows = powerrank.rankings(WEEKLY, 2)
        self.assertTrue(all(r["small"] for r in rows))

    def test_movement_and_recorded_label(self):
        h = powerrank.history(WEEKLY, recorded={"4": {"at": 1, "ranks": {r["name"]: r["rank"] for r in powerrank.rankings(WEEKLY, 4)}}})
        self.assertEqual(h["weeks"][-1]["kind"], "recorded")
        self.assertEqual(h["weeks"][0]["kind"], "reconstructed")
        self.assertTrue(all(r["move"] is None for r in h["weeks"][0]["rows"]))
        h2 = powerrank.history(WEEKLY, recorded={"4": {"at": 1, "ranks": {"A": 9}}})
        self.assertEqual(h2["weeks"][-1]["kind"], "reconstructed")   # a saved ranking that no longer matches isn't claimed

    def test_cannot_touch_official_places(self):
        players = [{"name": k, "weekly": v, "place": i + 1, "wins": sum(v.values())} for i, (k, v) in enumerate(WEEKLY.items())]
        before = json.dumps(players, sort_keys=True)
        out = poolpage._power(players, False)
        self.assertEqual(before, json.dumps(players, sort_keys=True))
        last = out["weeks"][-1]["rows"]
        self.assertEqual({r["name"]: r["official"] for r in last}, {p["name"]: p["place"] for p in players})


# ---- the website pieces --------------------------------------------------------------------
def _script(page: str) -> str:
    return page.split('<script id="pool-app">', 1)[1].rsplit("</script>", 1)[0]


class TestSitePieces(unittest.TestCase):
    def test_parts_are_inside_the_page_script(self):
        names = [p.name for p in poolpage.parts()]
        for f in ("526-rulebook.js", "527-power-rankings.js", "528-connection-map.js"):
            self.assertIn(f, names)
            self.assertLess(names.index(f), names.index("540-updating-the-page-only-whoever.js"))

    def test_styles_go_in_the_one_style_block(self):
        page = poolpage.template()
        self.assertIn(".cm-svg", page.split("</style>")[0])

    def test_views_are_in_navigation_and_routes(self):
        places = (PARTS / "100-the-places-on-the-site.js").read_text(encoding="utf-8")
        glue = (PARTS / "180-putting-it-together.js").read_text(encoding="utf-8")
        for v in ("rules", "power", "connections"):
            self.assertIn(f'"{v}"', places)
            self.assertIn(f'case "{v}"', glue)

    def test_script_compiles(self):
        import jsrun
        try:
            got = jsrun.run("var src = " + json.dumps(_script(poolpage.template())) + "; new Function(src);", "true")
        except jsrun.NoBrowser:
            self.skipTest("no Chrome or Edge")
        self.assertTrue(got)

    def test_map_pairs_match_head_to_head(self):
        """Every link's numbers are the head-to-head page's compare()."""
        import jsrun
        h2h = (PARTS / "370-head-to-head-the-tale.js").read_text(encoding="utf-8")
        compare = h2h[h2h.index("function compare("):h2h.index("function h2hView(")]
        cm = (PARTS / "528-connection-map.js").read_text(encoding="utf-8")
        weeks = []
        for n in (1, 2, 3):
            weeks.append({"week": n, "scores": [{"name": k, "total": v[str(n)]} for k, v in WEEKLY.items() if str(n) in v],
                          "picks": {k: v for k, v in {"A": "110", "B": "100", "C": "011", "D": "1-1"}.items() if str(n) in WEEKLY[k]}, "results": [{"matchup": "g", "winner": "W", "loser": "L"}] * 3})
        data = {"weeks": weeks, "players": [{"name": k} for k in WEEKLY]}
        code = "var DATA = " + json.dumps(data) + "; var state = {}; function plural(n,w){return n+' '+w;}\n" + compare + cm
        try:
            got = jsrun.run(code, "JSON.stringify({p: cmPairs(1, 3), c: compare('A','B',1,3), e: cmEdges('shared', cmPairs(1,3), 1, '').length})")
        except jsrun.NoBrowser:
            self.skipTest("no Chrome or Edge")
        got = json.loads(got)
        ab = next(p for p in got["p"] if p["a"] == "A" and p["b"] == "B")
        self.assertEqual((ab["games"], ab["agree"], ab["aWeeks"], ab["bWeeks"]),
                         (got["c"]["both"], got["c"]["agree"], got["c"]["aWeeks"], got["c"]["bWeeks"]))
        self.assertEqual(ab["games"], 9)            # 3 weeks x 3 games, all picked by both
        ad = next(p for p in got["p"] if p["a"] == "A" and p["b"] == "D")
        self.assertEqual(ad["games"], 4)            # D's missing game and missing week 2 are left out
        self.assertEqual(ad["weeks"], 2)
        self.assertEqual(len(got["p"]), 6)
        self.assertEqual(got["e"], 0)               # fewer than 16 games compared: no shared-pick links drawn


# ---- import workbench ----------------------------------------------------------------------
def _rec(name, weekly, **kw):
    r = {"name": name, "weekly": weekly, "wins": sum(weekly.values()), "pos": 1, "net": 0.0, "won": 0.0, "paid": 0.0,
         "big_loser": 0.0, "suicide_alive": True}
    r.update(kw)
    return r


class TestImportCompare(unittest.TestCase):
    META = {"kind": "stats", "week": 3, "max_week_score": 19, "warnings": []}

    def test_new_week_is_harmless_changed_week_is_serious(self):
        old = {"a": _rec("Ava", {1: 10, 2: 9})}
        new = {"a": _rec("Ava", {1: 10, 2: 8, 3: 11})}
        got = {(c["field"], c["severity"]) for c in importbench.compare(new, old, self.META, 2)}
        self.assertIn(("week 3", "harmless"), got)
        self.assertIn(("week 2", "serious"), got)

    def test_problems_found(self):
        old = {"a": _rec("Ava", {1: 10}), "b": _rec("Ben", {1: 9})}
        new = {"a": _rec("Ava", {1: 10, 2: 25}), "c": _rec("ava", {1: 3})}
        kinds = {c["kind"]: c["severity"] for c in importbench.compare(new, old, self.META, 1)}
        self.assertEqual(kinds["invalid"], "serious")      # 25 > most possible
        self.assertEqual(kinds["missing"], "serious")      # Ben is gone
        self.assertEqual(kinds["duplicate"], "serious")    # Ava twice
        self.assertEqual(kinds["addition"], "check")       # an unknown coach

    def test_older_file_and_money(self):
        old = {"a": _rec("Ava", {1: 10}, won=5.0)}
        new = {"a": _rec("Ava", {1: 10}, won=9.0)}
        got = importbench.compare(new, old, dict(self.META, week=1), 1)
        self.assertEqual([c["severity"] for c in got if c["kind"] == "money"], ["serious"])   # money moves, no new week
        older = importbench.compare(new, old, dict(self.META, week=1), 2)
        self.assertTrue(any(c["kind"] == "conflict" and c["severity"] == "serious" for c in older))


class TestImportWorkflow(unittest.TestCase):
    """History, approval gates, duplicates and undo, with the data folder in a temp dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        self.data.mkdir()
        self.saved = (config.DATA_DIR, config.BACKUP_DIR)
        config.DATA_DIR, config.BACKUP_DIR = self.data, self.tmp / "backups"
        self.orig = self.data / "stats week 1.xls"
        self.orig.write_bytes(b"week one")
        self.new = self.tmp / "stats week 2.xls"
        self.new.write_bytes(b"week two")

    def tearDown(self):
        config.DATA_DIR, config.BACKUP_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _entry(self, changes, status="checked"):
        e = {"id": "t1", "file": self.new.name, "source": str(self.new), "digest": importbench._digest(self.new),
             "status": status, "changes": changes, "problems": [], "detected": {}}
        importbench._update(e)
        return e

    def test_serious_needs_explicit_acceptance(self):
        self._entry([{"n": 1, "severity": "serious", "kind": "update", "coach": "Ava", "field": "week 1", "before": 1, "after": 2, "why": ""}])
        with self.assertRaises(PermissionError):
            importbench.approve("t1", "Sam")
        with self.assertRaises(PermissionError):
            importbench.approve("t1", "", accept_serious=True)
        e = importbench.approve("t1", "Sam", accept_serious=True)
        self.assertEqual(e["accepted_serious"], [1])

    def test_apply_needs_approval(self):
        self._entry([])
        with self.assertRaises(PermissionError):
            importbench.apply("t1")

    def test_apply_backs_up_and_undo_restores(self):
        self._entry([])
        importbench.approve("t1", "Sam")
        real_candidate, real_current = importbench.candidate, importbench.current
        importbench.candidate = lambda p: ({}, {"kind": "stats"})
        importbench.current = lambda s=None: ({}, 2)
        try:
            e = importbench.apply("t1")
        finally:
            importbench.candidate, importbench.current = real_candidate, real_current
        self.assertTrue((self.data / self.new.name).exists())
        self.assertEqual(e["backed_up"], [self.orig.name])
        self.assertEqual(self.orig.read_bytes(), b"week one")      # nothing on record overwritten
        importbench.undo("t1")
        self.assertFalse((self.data / self.new.name).exists())
        self.assertEqual(self.orig.read_bytes(), b"week one")
        self.assertEqual(importbench.history()[0]["status"], "undone")

    def test_changed_file_after_check_is_refused(self):
        self._entry([])
        importbench.approve("t1", "Sam")
        self.new.write_bytes(b"edited later")
        with self.assertRaises(RuntimeError):
            importbench.apply("t1")

    def test_duplicate_detected(self):
        copy = self.tmp / "again.xls"
        copy.write_bytes(self.orig.read_bytes())
        real = importbench.detect
        importbench.detect = lambda p: {"file": p.name, "kind": "stats", "week": 1, "error": ""}
        importbench.candidate = (lambda p: (_ for _ in ()).throw(ValueError("stop")))
        try:
            e = importbench.check(copy)
        finally:
            importbench.detect = real
            from importlib import reload
            reload(importbench)
        self.assertTrue(any("already imported" in p for p in e["problems"]))

    def test_not_on_the_website(self):
        page = poolpage.template()
        self.assertNotIn("importbench", page)
        self.assertNotIn("import-history", page)


if __name__ == "__main__":
    unittest.main(verbosity=1)
