#!/usr/bin/env python3
"""Tests for the Operation Sunday Lab (acql/lab): calibration, the confidence
distribution, postmortem research summary, the per-book odds table, the shared
live poller, the research assistant's tool loop and the server's guards.

Run from the project root:

    python tests/test_lab.py

Made-up numbers, a scratch database and a scratch raw archive; nothing is
fetched and no API is called (the assistant gets a fake client). No Qt.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import rawarchive
from acql.feeds.results import Score
from acql.lab import assistant, data, live, server
from acql.model import forecastlog


def scratch_log(rows) -> tuple[sqlite3.Connection, Path, tempfile.TemporaryDirectory]:
    """A forecast log with games and forecasts: rows are
    (game_id, week, away, home, away_score, home_score, model, prob, status)."""
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "acql.db"
    conn = forecastlog.connect(path)
    for m in {r[6] for r in rows}:
        conn.execute("INSERT INTO lab_models(model_id, display_name, model_type, created_at_utc) VALUES (?,?,?,?)",
                     (m, m.title(), "recipe", "2026-10-01T00:00:00+00:00"))
    for gid, week, away, home, a, h, *_ in rows:
        conn.execute("INSERT OR IGNORE INTO lab_games(game_id, season, week, kickoff_utc, away_team, home_team, "
                     "away_score, home_score) VALUES (?,?,?,?,?,?,?,?)",
                     (gid, 2026, week, "2026-10-12T17:00:00+00:00", away, home, a, h))
    for gid, _w, _a, _h, _as, _hs, model, prob, status in rows:
        conn.execute("INSERT INTO lab_predictions(game_id, model_id, model_version, home_win_probability, "
                     "retrieved_at_utc, recorded_at_utc, eligibility_status) VALUES (?,?,?,?,?,?,?)",
                     (gid, model, "2.17.0", prob, "2026-10-09T17:00:00+00:00", "2026-10-09T17:00:00+00:00", status))
    conn.commit()
    conn.close()
    return data.connect(path), path, tmp


ROWS = [
    # favoured side's chance 0.55, home wins -> right
    ("G1", 6, "AAA", "BBB", 10, 20, "deadeye", 0.55, "eligible"),
    # 0.35 home = 0.65 away favoured; away wins -> right
    ("G2", 6, "CCC", "DDD", 24, 17, "deadeye", 0.35, "eligible"),
    # 0.72 home, home loses -> wrong
    ("G3", 6, "EEE", "FFF", 27, 13, "deadeye", 0.72, "eligible"),
    # tie: left out of calibration
    ("G4", 6, "GGG", "HHH", 20, 20, "deadeye", 0.60, "eligible"),
    # recorded after kickoff: never scored
    ("G5", 6, "III", "JJJ", 0, 31, "deadeye", 0.90, "postgame"),
    # the market beside them
    ("G1", 6, "AAA", "BBB", 10, 20, "market-moneyline", 0.50, "eligible"),
    ("G3", 6, "EEE", "FFF", 27, 13, "market-moneyline", 0.80, "eligible"),
]


class TestCalibration(unittest.TestCase):
    def setUp(self):
        self.conn, _p, self.tmp = scratch_log(ROWS)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_only_eligible_decided_games_are_scored(self):
        c = data.calibration(self.conn)
        self.assertEqual(c["games"], 3)                     # G4 tie and G5 postgame left out
        self.assertEqual(c["ties_left_out"], 1)
        self.assertEqual(c["postgame_left_out"], 1)
        self.assertEqual(c["actual_wins"], 2)
        self.assertAlmostEqual(c["expected_wins"], 0.55 + 0.65 + 0.72)

    def test_brier_and_log_loss_use_the_recorded_home_chance(self):
        c = data.calibration(self.conn)
        brier = ((0.55 - 1) ** 2 + (0.35 - 0) ** 2 + (0.72 - 0) ** 2) / 3
        self.assertAlmostEqual(c["brier"], brier)
        ll = -(math.log(0.55) + math.log(0.65) + math.log(0.28)) / 3
        self.assertAlmostEqual(c["log_loss"], ll)
        self.assertAlmostEqual(c["accuracy"], 2 / 3)

    def test_bins_and_intervals(self):
        c = data.calibration(self.conn, width=0.1)
        by = {b["lo"]: b for b in c["bins"]}
        self.assertEqual((by[0.5]["n"], by[0.5]["hits"]), (1, 1))
        self.assertEqual((by[0.6]["n"], by[0.6]["hits"]), (1, 1))
        self.assertEqual((by[0.7]["n"], by[0.7]["hits"]), (1, 0))
        lo, hi = by[0.7]["interval"]
        self.assertTrue(0 <= lo < hi <= 1)
        self.assertIn("rough look", c["warning"])

    def test_two_eligible_forecasts_for_one_game_are_left_out(self):
        self.conn.close()
        self.conn, _p, tmp2 = scratch_log(ROWS + [("G1", 6, "AAA", "BBB", 10, 20, "deadeye", 0.80, "eligible")])
        self.addCleanup(tmp2.cleanup)
        self.assertEqual(data.calibration(self.conn)["games"], 2)

    def test_the_database_is_opened_read_only(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.conn.execute("UPDATE lab_predictions SET home_win_probability = 0.99")

    def test_distribution_compares_with_the_market(self):
        d = data.distribution(self.conn)
        self.assertEqual(d["games"], 4)                     # eligible, tie included (it was forecast)
        games = {g["game"]: g for b in d["bins"] for g in b["games"]}
        self.assertAlmostEqual(games["G3"]["market"], 0.80)
        self.assertIsNone(games["G2"]["market"])
        self.assertAlmostEqual(sum(b["share"] for b in d["bins"]), 1.0)


class TestResearchSummary(unittest.TestCase):
    def item(self, p, right, market=None):
        return {"status": "eligible", "right": right, "p": p, "market_p": market, "brier": (p - int(right)) ** 2,
                "disagreement": None if market is None else p - market, "favoured": "bbb", "home": "bbb"}

    def test_wins_in_line_with_chances_read_as_luck(self):
        items = [self.item(0.7, True)] * 7 + [self.item(0.7, False)] * 3
        s = data.research_summary(items)
        self.assertEqual(s["games"], 10)
        self.assertAlmostEqual(s["z"], 0.0)
        self.assertEqual(s["findings"][0]["kind"], "established")
        self.assertIn("ordinary luck", s["findings"][0]["text"])

    def test_postgame_forecasts_are_not_evidence(self):
        late = dict(self.item(0.9, False), status="postgame")
        self.assertEqual(data.research_summary([late])["games"], 0)

    def test_small_samples_are_hypotheses(self):
        s = data.research_summary([self.item(0.6, True, 0.5), self.item(0.7, False, 0.75)])
        kinds = [f["kind"] for f in s["findings"][1:]]
        self.assertTrue(kinds and all(k == "hypothesis" for k in kinds))


ODDS = [{"home_team": "Philadelphia Eagles", "away_team": "Dallas Cowboys", "commence_time": "2026-10-27T00:15:00Z",
         "bookmakers": [
             {"key": "a", "title": "Book A", "last_update": "2026-10-26T13:00:00Z", "markets": [
                 {"key": "h2h", "outcomes": [{"name": "Dallas Cowboys", "price": -200}, {"name": "Philadelphia Eagles", "price": 170}]},
                 {"key": "spreads", "outcomes": [{"name": "Dallas Cowboys", "price": -110, "point": -4.5},
                                                 {"name": "Philadelphia Eagles", "price": -110, "point": 4.5}]},
                 {"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": 43.5},
                                                {"name": "Under", "price": -110, "point": 43.5}]}]},
             {"key": "b", "title": "Book B", "last_update": "2026-10-26T14:00:00Z", "markets": [
                 {"key": "h2h", "outcomes": [{"name": "Dallas Cowboys", "price": -190}, {"name": "Philadelphia Eagles", "price": 180}]},
                 {"key": "spreads", "outcomes": [{"name": "Dallas Cowboys", "price": -105, "point": -4},
                                                 {"name": "Philadelphia Eagles", "price": -115, "point": 4}]}]},
         ]}]


class TestBooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rawarchive.use(Path(self.tmp.name))

    def tearDown(self):
        rawarchive.use(None)
        self.tmp.cleanup()

    def test_nothing_archived_is_said(self):
        b = data.books()
        self.assertFalse(b["available"])

    def test_each_book_is_shown_as_it_came(self):
        rawarchive.keep("odds", json.dumps(ODDS), now=1_793_000_000)
        b = data.books(now=1_793_000_600)
        self.assertTrue(b["available"])
        self.assertEqual(b["age_minutes"], 10)
        g = b["games"][0]
        self.assertEqual((g["away"], g["home"], g["books"]), ("dal", "phi", 2))
        a = g["lines"][0]
        self.assertEqual((a["ml_home"], a["ml_away"], a["spread_home"], a["total"]), (170, -200, 4.5, 43.5))
        ih, ia = 100 / 270, 200 / 300
        self.assertAlmostEqual(a["nv_home"], round(ih / (ih + ia), 4))
        self.assertAlmostEqual(a["hold"], round(ih + ia - 1, 4))
        self.assertIsNone(g["lines"][1].get("total"))              # Book B quoted no total: not filled in
        self.assertEqual(g["best"]["ml_home"], (180, "Book B"))
        self.assertEqual(g["best"]["ml_away"], (-190, "Book B"))
        self.assertEqual(g["spread_range"], [4, 4.5])
        self.assertEqual(g["consensus"]["total"], 43.5)
        self.assertIn("not the whole market", b["coverage"])


class FakeFeed:
    def __init__(self):
        self.answers = []

    def __call__(self, year, week):
        out = self.answers.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


class TestLiveHub(unittest.TestCase):
    def hub(self, start, feed, now=1000.0):
        clock = SimpleNamespace(t=now)
        h = live.LiveHub(2026, 7, fetch=feed, load=lambda y, w: start, clock=lambda: clock.t)
        return h, clock

    def test_score_and_phase_changes_are_events_and_repeats_are_not(self):
        feed = FakeFeed()
        pre = Score("dal", "phi", kickoff=2000.0)
        q2 = Score("dal", "phi", 7, 3, state="in", detail="Q2 4:00")
        half = Score("dal", "phi", 7, 3, state="in", detail="Halftime")
        td = Score("dal", "phi", 7, 10, state="in", detail="Q3 12:00")
        feed.answers = [[q2], [q2], [half], [td]]
        h, _ = self.hub([pre], feed)
        self.assertEqual(h.games["dal@phi"]["phase"], "upcoming")
        kinds = [[e["kind"] for e in h.poll()] for _ in range(4)]
        self.assertEqual(kinds, [["score"], [], ["phase"], ["score"]])
        self.assertEqual(h.games["dal@phi"]["phase"], "live")
        versions = [e["version"] for e in h.events]
        self.assertEqual(versions, sorted(set(versions)))           # each event once, in order
        later = h.since(versions[2])
        self.assertTrue(all(e["version"] > versions[2] for e in later))

    def test_a_failure_keeps_the_last_good_scores_and_backs_off(self):
        feed = FakeFeed()
        q2 = Score("dal", "phi", 7, 3, state="in", detail="Q2 4:00")
        feed.answers = [[q2], RuntimeError("ESPN down"), RuntimeError("ESPN down"), [q2]]
        h, _ = self.hub([], feed)
        h.poll()
        self.assertEqual(h.interval(), live.LIVE_S)
        h.poll()
        h.poll()
        self.assertEqual(h.failures, 2)
        self.assertEqual(h.interval(), 2 * live.LIVE_S)
        self.assertEqual(h.games["dal@phi"]["home_points"], 3)
        self.assertEqual(h.snapshot()["error"], "ESPN down")
        h.poll()
        self.assertEqual((h.failures, h.snapshot()["error"]), (0, ""))

    def test_polling_slows_when_nothing_is_on(self):
        h, clock = self.hub([Score("dal", "phi", kickoff=1000.0 + 600)], FakeFeed())
        self.assertEqual(h.interval(), live.SOON_S)
        clock.t = 0.0
        self.assertEqual(h.interval(), live.IDLE_S)
        self.assertTrue(h.snapshot()["stale"])                       # never heard from ESPN

    def test_phases(self):
        self.assertEqual(live.phase({"state": "post"}), "final")
        self.assertEqual(live.phase({"state": "in", "detail": "Halftime"}), "halftime")
        self.assertEqual(live.phase({"called_off": True, "state": "post"}), "called-off")


class FakeClient:
    """Answers with one tool call, then text."""

    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


def block(**kw):
    return SimpleNamespace(**kw)


class TestAssistant(unittest.TestCase):
    def setUp(self):
        self.conn, _p, self.tmp = scratch_log(ROWS)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_tool_loop_answers_from_tool_results(self):
        client = FakeClient([
            SimpleNamespace(stop_reason="tool_use", content=[
                block(type="tool_use", id="t1", name="calibration", input={}),
                block(type="tool_use", id="t2", name="rm_rf", input={})]),
            SimpleNamespace(stop_reason="end_turn", content=[block(type="text", text="Three games: too few.")]),
        ])
        out = assistant.ask("Is Deadeye overconfident?", self.conn, client=client)
        self.assertEqual(out["answer"], "Three games: too few.")
        self.assertEqual([c["tool"] for c in out["calls"]], ["calibration", "rm_rf"])
        self.assertTrue(out["calls"][1]["error"])                    # no such tool: an error, not an action
        sent = client.calls[1]["messages"]       # the same list, later grown: user, assistant, results, ...
        self.assertEqual([m["role"] for m in sent[:3]], ["user", "assistant", "user"])
        results = sent[2]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["t1", "t2"])   # both results in one message
        self.assertEqual(json.loads(results[0]["content"])["games"], 3)
        kw = client.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertNotIn("thinking", kw)
        self.assertNotIn("tool_choice", kw)

    def test_refusal_and_cut_off_answers_are_said(self):
        out = assistant.ask("x", self.conn, client=FakeClient([SimpleNamespace(stop_reason="refusal", content=[])]))
        self.assertIn("declined", out["error"])
        out = assistant.ask("x", self.conn, client=FakeClient([SimpleNamespace(stop_reason="max_tokens", content=[])]))
        self.assertIn("cut off", out["error"])

    def test_no_key_is_said_not_faked(self):
        real = assistant.available
        assistant.available = lambda: (False, "No Anthropic API key is set.")
        try:
            out = assistant.ask("anything", self.conn)
        finally:
            assistant.available = real
        self.assertTrue(out["unavailable"])
        self.assertNotIn("answer", out)

    def test_tools_have_no_way_to_write(self):
        names = {t["name"] for t in assistant.TOOLS}
        self.assertFalse(names & {"write", "delete", "shell", "exec", "update", "approve"})
        self.assertIn("error", assistant.run_tool("bench_approve", {}, self.conn))


class TestServerGuards(unittest.TestCase):
    def setUp(self):
        self.conn, _p, self.tmp = scratch_log(ROWS)
        self.opened = []
        lab = server.Lab(conn=self.conn, client=FakeClient([]), actions={"redzone": lambda: self.opened.append(1)})
        self.lab = lab
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.handler_for(lab, port)
        self.port = port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.conn.close()
        self.tmp.cleanup()

    def get(self, path, host=None, method="GET", headers=None, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=body,
                                     headers={**(headers or {}), "Host": host or f"127.0.0.1:{self.port}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_routes_and_guards(self):
        code, body = self.get("/api/calibration")
        self.assertEqual((code, body["games"]), (200, 3))
        self.assertEqual(self.get("/api/models", host="evil.example:80")[0], 403)
        self.assertEqual(self.get("/etc/passwd")[0], 404)
        self.assertEqual(self.get("/api/ask", method="POST", body=b"{}")[0], 403)           # no X-Lab header
        code, body = self.get("/api/tool", method="POST", body=b'{"name":"list_models"}', headers={"X-Lab": "1"})
        self.assertEqual(code, 200)
        self.assertEqual(self.get("/api/tool", method="POST", body=b'{"name":"os.system"}', headers={"X-Lab": "1"})[0], 400)


    def test_redzone_is_asked_of_the_dashboard(self):
        code, body = self.get("/api/open", method="POST", body=b'{"what":"redzone"}', headers={"X-Lab": "1"})
        self.assertEqual((code, body["ok"], self.opened), (200, True, [1]))
        self.assertEqual(self.get("/api/open", method="POST", body=b'{"what":"redzone"}')[0], 403)
        self.lab.actions.clear()
        code, body = self.get("/api/open", method="POST", body=b'{"what":"redzone"}', headers={"X-Lab": "1"})
        self.assertFalse(body["ok"])
        self.assertIn("dashboard first", body["error"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
