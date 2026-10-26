"""The website's league modes (League Broadcast, League Time Machine, the
Numbers Room): switched on, out of the page entirely when switched off, joined in
the right place when on, and their shared numbers - standings after each week,
ties, the official latest table, stats, records, CSV - worked out the way the
dashboard works them out. The JavaScript runs in headless Chrome or Edge
(packaging/jsrun.py); those tests are skipped where there is neither."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))

from acql.ui import poolpage  # noqa: E402
from acql.ui import recap  # noqa: E402

MODE_PARTS = ["521-modes-engine.js", "522-modes-shell.js", "523-time-machine.js", "524-numbers-room.js", "525-broadcast.js"]


class ModesOn:
    """poolpage.MODES set for a block, put back after."""
    value = True

    def __enter__(self):
        self.was = poolpage.MODES
        poolpage.MODES = self.value

    def __exit__(self, *exc):
        poolpage.MODES = self.was


class ModesOff(ModesOn):
    value = False


class TestTheSwitch(unittest.TestCase):
    def test_modes_are_on(self):
        # Sam turned them on (2026-10-26): the published page carries them.
        self.assertTrue(poolpage.MODES)
        self.assertIn("lmBoard", poolpage.template())

    def test_off_means_the_page_is_exactly_the_old_one(self):
        old = "".join(p.read_text(encoding="utf-8") for p in sorted(poolpage.PARTS.iterdir())
                      if p.suffix in (".html", ".js") and p.name[:3].isdigit())
        with ModesOff():
            self.assertEqual(poolpage.template(), old)
            self.assertFalse(any(p.parent == poolpage.MODES_DIR for p in poolpage.parts()))
            self.assertNotIn("lmBoard", poolpage.template())

    def test_a_copy_without_the_modes_folder_still_builds(self):
        # poolpage.py committed without pool_modes/ must not stop the site publishing.
        real = poolpage.MODES_DIR
        poolpage.MODES_DIR = real.with_name("no-such-folder")
        try:
            with ModesOn():
                with ModesOff():
                    old = poolpage.template()
                self.assertEqual(poolpage.template(), old)
        finally:
            poolpage.MODES_DIR = real

    def test_the_switch_changes_the_site_fingerprint(self):
        with ModesOff():
            off = poolpage.site_fingerprint({"weeks": []})
        with ModesOn():
            on = poolpage.site_fingerprint({"weeks": []})
        self.assertNotEqual(off, on)             # flipping it either way republishes, as it should


class TestModesJoinIn(unittest.TestCase):
    def test_parts_sit_between_the_boot_sequence_and_start_up(self):
        with ModesOn():
            names = [p.name for p in poolpage.parts()]
        for name in MODE_PARTS:
            self.assertIn(name, names)
        first, last = names.index(MODE_PARTS[0]), names.index(MODE_PARTS[-1])
        self.assertLess(names.index("520-the-sunday-boot-sequence.js"), first)
        self.assertLess(last, names.index("530-starting-up.js"))   # set up before the page routes and draws
        self.assertEqual(names[-1], "999-page-end.html")

    def test_styles_go_in_the_one_style_block(self):
        with ModesOff():
            before = poolpage.template().count("</style>")
        with ModesOn():
            page = poolpage.template()
        self.assertEqual(page.count("</style>"), before)                 # added inside, no new block
        self.assertIn("/* ---- league modes ---- */", page.split("</style>")[0])
        self.assertIn(".lm-board", page.split("</style>")[0])


def _script(page: str) -> str:
    return page.split('<script id="pool-app">', 1)[1].rsplit("</script>", 1)[0]


def _jsrun():
    import jsrun
    return jsrun


class TestScriptParses(unittest.TestCase):
    def test_the_joined_script_compiles_with_the_modes_on(self):
        jsrun = _jsrun()
        with ModesOn():
            code = _script(poolpage.template())
        try:
            got = jsrun.run("var src = " + json.dumps(code) + "; new Function(src);", "true")
        except jsrun.NoBrowser:
            self.skipTest("no Chrome or Edge to parse the page's script")
        self.assertTrue(got)


# A small made-up season: four coaches, three weeks, a tie, a missed card.
#   A 10  8  9 -> 10 18 27     B  9 10  8 -> 9 19 27
#   C 10  7  6 -> 10 17 23     D  5  -  12 -> 5  5 17
WEEKLY = {"A": {"1": 10, "2": 8, "3": 9}, "B": {"1": 9, "2": 10, "3": 8},
          "C": {"1": 10, "2": 7, "3": 6}, "D": {"1": 5, "3": 12}}
WEEKS = [{"week": 1, "top": 10, "winners": ["A", "C"], "average": 8.5},
         {"week": 2, "top": 10, "winners": ["B"], "average": 8.33},
         {"week": 3, "top": 12, "winners": ["D"], "average": 8.75}]
OFFICIAL = {"A": (1, 1), "B": (2, -1), "C": (3, 0), "D": (4, 0)}     # place, move: the official table breaks the A-B tie


def _fixture() -> str:
    weeks = []
    for w in WEEKS:
        n = str(w["week"])
        scores = [{"name": k, "total": v[n], "regular": v[n], "big_loser": 0} for k, v in WEEKLY.items() if n in v]
        picks = {k: ("10" if k in ("A", "B") else "01") for k, v in WEEKLY.items() if n in v}
        results = [{"matchup": "Xs @ Ys", "home": "Ys", "away": "Xs", "winner": "Ys", "loser": "Xs", "fav": "Ys", "spread": 3},
                   {"matchup": "Ps @ Qs", "home": "Qs", "away": "Ps", "winner": "Ps", "loser": "Qs", "fav": "Qs", "spread": 2}]
        weeks.append(dict(w, scores=scores, picks=picks, results=results, most=16, games=16))
    players = [{"name": k, "place": OFFICIAL[k][0], "move": OFFICIAL[k][1], "wins": sum(v.values()), "weekly": v}
               for k, v in WEEKLY.items()]
    season = {"year": 2026, "current": True, "through_week": 3, "season_weeks": 18, "complete": False, "entrants": 4,
              "standings": [{"name": p["name"], "place": p["place"], "wins": p["wins"], "weekly": p["weekly"], "big_loser": 0}
                            for p in players],
              "weeks": WEEKS}
    return ("var DATA = " + json.dumps({"weeks": weeks, "players": players, "through_week": 3}) + ";"
            "var state = { me: '' }; var historyData = null; var SEASON = " + json.dumps(season) + ";"
            "function allSeasons() { return [SEASON]; }")


def _engine() -> str:
    helpers = (poolpage.PARTS / "020-small-helpers.js").read_text(encoding="utf-8")
    lens = (poolpage.PARTS / "425-factions-and-team-lens.js").read_text(encoding="utf-8")
    picks = lens[:lens.index("  // Rows in an order")]           # sideOf and pickedWeeks, nothing else
    engine = (poolpage.MODES_DIR / "521-modes-engine.js").read_text(encoding="utf-8")
    return helpers + picks + _fixture() + engine


class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jsrun = _jsrun()
        probe = """(function () {
          var s = lmSeason(2026), C = lmCheckpoints(s);
          var cps = C.cps.map(function (c) { return { week: c.week, leaders: c.leaders, official: !!c.official,
            rows: c.rows.map(function (r) { return [r.name, r.total, r.place, r.tied, r.move, r.behind, r.score]; }) }; });
          var st = lmStats(s), a = st.by.A, d = st.by.D;
          var part = lmStats(s, 2, 3);
          var vs = lmVs(s, 'A', 'B');
          var recs = {}; lmRecords().forEach(function (r) { recs[r.id] = [r.value, r.holders.map(function (h) { return h.name + (h.week ? h.week : ''); })]; });
          var ev = lmEvents(s).map(function (e) { return [e.week, e.kind, e.src]; });
          var games = lmGames(); var teams = lmTeamPicks();
          var csv = lmCsv([{ label: 'Coach', get: function (r) { return r.n; } }, { label: 'Avg', derived: true, get: function (r) { return r.v; } }],
                          [{ n: 'A, "the" one', v: 9 }, { n: 'B', v: null }]);
          return { cps: cps, verify: C.verify, missing: C.missing,
            a: [a.weeks, a.total, a.avg, a.sd, a.wins, a.outright, a.atTop, a.best, a.bestWeeks, a.worst, a.vsAvg],
            d: [d.weeks, d.total, d.avg, d.wins, d.outright],
            part: [part.weeks, part.by.A.total, part.by.D.weeks],
            vs: [vs.aw, vs.bw, vs.ties, vs.shared], recs: recs, ev: ev,
            games: games.map(function (g) { return [g.week, g.cards, g.right, g.upset]; }),
            teamsA: teams.cells.A, favA: teams.fav.A, csv: csv,
            hash: [lmHash('abc'), lmHash('abc') === lmHash('abd')], rank: lmRank({ x: 3, y: 5, z: 3, w: null }) };
        })()"""
        try:
            cls.got = jsrun.run(_engine(), probe)
        except jsrun.NoBrowser:
            raise unittest.SkipTest("no Chrome or Edge to run the page's script in")

    def cp(self, week):
        return {r[0]: r for r in next(c for c in self.got["cps"] if c["week"] == week)["rows"]}

    def test_standings_after_each_week_follow_the_dashboard_rule(self):
        # The dashboard's own competition ranking (recap._places) on the same totals.
        for week in (1, 2):
            totals = {k: sum(v.get(str(n), 0) for n in range(1, week + 1)) for k, v in WEEKLY.items()}
            want = recap._places(totals)
            got = self.cp(week)
            for name, place in want.items():
                self.assertEqual(got[name][2], place, f"week {week} {name}")
        self.assertTrue(self.cp(1)["A"][3] and self.cp(1)["C"][3])     # 10 and 10 share first
        self.assertEqual(self.cp(1)["B"][2], 3)                         # and the next place is skipped

    def test_moves_and_gaps(self):
        wk2 = self.cp(2)
        self.assertEqual(wk2["B"][4], 2)          # 3rd -> 1st
        self.assertEqual(wk2["C"][4], -2)         # 1st -> 3rd
        self.assertIsNone(self.cp(1)["A"][4])     # no week before the first
        self.assertEqual(wk2["D"][5], 14)         # 19 - 5 behind
        self.assertIsNone(wk2["D"][6])            # no card in week 2: nothing invented
        self.assertEqual(wk2["D"][1], 5)          # and nothing added

    def test_the_latest_week_is_the_official_table(self):
        v = self.got["verify"]
        self.assertEqual((v["checked"], v["matched"], v["ties"], v["off"]), (4, 3, 1, []))
        last = next(c for c in self.got["cps"] if c["week"] == 3)
        self.assertTrue(last["official"])
        wk3 = self.cp(3)
        self.assertEqual((wk3["A"][2], wk3["B"][2]), (1, 2))            # the tie broken the official way
        self.assertFalse(wk3["A"][3])
        self.assertEqual((wk3["A"][4], wk3["B"][4]), (1, -1))           # the official moves
        self.assertEqual(last["leaders"], ["A"])
        self.assertEqual([r[0] for r in last["rows"]], ["A", "B", "C", "D"])
        self.assertEqual(self.got["missing"], [])

    def test_coach_numbers(self):
        weeks, total, avg, sd, wins, outright, at_top, best, best_weeks, worst, vs_avg = self.got["a"]
        self.assertEqual((weeks, total, wins, outright, best, best_weeks, worst), (3, 27, 1, 0, 10, [1], 8))
        self.assertAlmostEqual(avg, 9.0)
        self.assertAlmostEqual(sd, (2 / 3) ** 0.5)                      # population standard deviation
        self.assertAlmostEqual(vs_avg, ((10 - 8.5) + (8 - 8.33) + (9 - 8.75)) / 3)
        self.assertEqual(at_top, 2)                                     # shared 1st in week 1, official 1st in week 3
        self.assertEqual(self.got["d"][:2], [2, 17])                    # a missed card isn't a zero week
        self.assertAlmostEqual(self.got["d"][2], 8.5)
        self.assertEqual(self.got["d"][3:], [1, 1])
        self.assertEqual(self.got["part"], [[2, 3], 17, 1])             # weeks 2-3 only

    def test_head_to_head(self):
        aw, bw, ties, shared = self.got["vs"]
        self.assertEqual((aw, bw, ties), (2, 1, 0))
        self.assertEqual(shared, {"same": 6, "games": 6})              # A and B always picked alike

    def test_records(self):
        r = self.got["recs"]
        self.assertEqual(r["high"], [12, ["D3"]])
        self.assertEqual(r["low"], [5, ["D1"]])
        self.assertEqual(r["total"], [27, ["A", "B"]])                  # D missed a week: not a full season
        self.assertEqual(r["weeks"][0], 1)
        self.assertNotIn("winrun", r)                                   # nobody won two in a row: no such record

    def test_events_are_dated_by_week_and_sourced(self):
        ev = self.got["ev"]
        self.assertIn([1, "win", "official"], ev)
        self.assertIn([2, "lead", "calc"], ev)
        self.assertIn([2, "first", "calc"], ev)                         # B's first time in front
        self.assertIn([3, "record", "official"], ev)                    # 12 beat the season's 10
        self.assertTrue(all(e[2] in ("official", "calc") for e in ev))

    def test_games_and_team_picks_come_only_from_graded_cards(self):
        games = self.got["games"]
        self.assertEqual(len(games), 6)
        self.assertEqual(games[0], [1, 4, 2, False])                    # 4 cards, A and B right, favourite won
        self.assertEqual(games[1], [1, 4, 2, True])                     # the underdog won
        self.assertEqual(games[2][1], 3)                                # D had no card in week 2
        self.assertEqual(self.got["teamsA"], {"Ys": {"n": 3, "ok": 3}, "Qs": {"n": 3, "ok": 0}})
        self.assertEqual(self.got["favA"], {"games": 6, "fav": 6, "favOk": 3, "dog": 0, "dogOk": 0})

    def test_csv_marks_worked_out_columns_and_quotes(self):
        self.assertEqual(self.got["csv"], 'Coach,Avg (calculated)\r\n"A, ""the"" one",9\r\nB,\r\n')

    def test_small_helpers(self):
        h, same = self.got["hash"]
        self.assertRegex(h, r"^[0-9a-f]{8}$")
        self.assertFalse(same)
        self.assertEqual(self.got["rank"], {"x": {"place": 2, "tied": True}, "y": {"place": 1, "tied": False},
                                            "z": {"place": 2, "tied": True}})


class TestPreviewBuild(unittest.TestCase):
    def test_preview_has_the_modes_whatever_the_switch(self):
        import tempfile
        from acql.site import modespreview
        out = Path(tempfile.mkdtemp(prefix="acql-modes-"))
        seen = {}
        real_site = poolpage.site

        def fake_site(season, **kw):
            seen["modes"] = poolpage.MODES
            return ("<html><script>x</script>__SITE__</html>", {"history.json": b"{}", poolpage.SERVICE_WORKER: b"sw"}, {"live": None})
        poolpage.site = fake_site
        try:
            with ModesOff():
                page = modespreview.build(out, season=object())
                self.assertFalse(poolpage.MODES)                         # put back
        finally:
            poolpage.site = real_site
        self.assertTrue(seen["modes"])
        self.assertTrue(page.is_file())
        self.assertNotIn("__SITE__", page.read_text(encoding="utf-8"))
        self.assertFalse((out / poolpage.SERVICE_WORKER).exists())      # no offline cache from a preview


if __name__ == "__main__":
    unittest.main()
