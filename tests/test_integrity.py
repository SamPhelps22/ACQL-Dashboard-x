#!/usr/bin/env python3
"""Tests for the Integrity Engine (acql/integrity): scoring recounts, standings
reconciliation, missing and duplicate records, stale feeds, historical
consistency, the correction workflow, recovery after a failed run, and the
Integrity Center's guards.

Run from the project root:

    python tests/test_integrity.py

A made-up season and a scratch database; nothing is fetched, no file in the
project is read or written. No Qt.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import store
from acql.feeds.results import Score
from acql.integrity import center, engine, history
from acql.models import Game, Player, PlayerWeek, Season, SourceFile, Week
from acql.pool import reconcile, rulings

YEAR = 2026
COACHES = ("Ann", "Bob", "Cat")
# Week 1: KC beats DEN (KC by 3 needed, wins by 7) and BUF beats MIA straight up.
# Week 2: PHI beats DAL, SF beats SEA.
GAMES = {
    1: [(1, "DEN", "KC", "KC", 3.0, "KC", 24, 17), (2, "MIA", "BUF", "BUF", None, "", 30, 10)],
    2: [(1, "DAL", "PHI", "PHI", None, "", 27, 20), (2, "SEA", "SF", "SF", None, "", 21, 14)],
}
PICKS = {  # coach -> week -> {game: team picked}
    "Ann": {1: {1: "KC", 2: "BUF"}, 2: {1: "PHI", 2: "SF"}},
    "Bob": {1: {1: "KC", 2: "MIA"}, 2: {1: "PHI", 2: "SEA"}},
    "Cat": {1: {1: "DEN", 2: "MIA"}, 2: {1: "DAL", 2: "SF"}},
}


def make_season() -> Season:
    """Two finished weeks, three coaches, everything consistent."""
    s = Season(buy_in=40.0, results_year=YEAR)
    s.sources = [SourceFile(Path("stats.xls"), "stats", week=2, modified=1.0, digest="a")]
    for number, rows in GAMES.items():
        week = Week(number)
        for idx, away, home, winner, line, fav, hp, ap in rows:
            week.games.append(Game(idx, home=home, away=away, winner=winner, line=line, line_favourite=fav,
                                   home_points=hp, away_points=ap))
        s.weeks[number] = week
    for name in COACHES:
        p = Player(key=name.lower(), display=name)
        for number, week in s.weeks.items():
            won = {i: t for i, t in PICKS[name][number].items()
                   if t == next(g.winner for g in week.games if g.index == i)}
            line = PlayerWeek(name, number, correct_picks=won, regular_wins=len(won), total_wins=len(won))
            week.lines[p.key] = line
            p.weekly_wins[number] = p.weekly_regular[number] = len(won)
            p.weekly_big_loser[number] = 0
        p.official_weeks = {1, 2}
        p.wins = sum(p.weekly_wins.values())
        s.players[p.key] = p
    order = sorted(s.players.values(), key=lambda p: -p.wins)
    leader = order[0].wins
    for i, p in enumerate(order, start=1):
        p.pos, p.prev_pos, p.games_behind = i, i, float(leader - p.wins)
    # money: each week the top card takes everyone's games behind
    for number, week in s.weeks.items():
        top = max(l.total_wins for l in week.lines.values())
        pot = sum(top - l.total_wins for l in week.lines.values())
        winners = [k for k, l in week.lines.items() if l.total_wins == top]
        for k in winners:
            s.players[k].weekly_winnings[number] = pot / len(winners)
    for p in s.players.values():
        won = sum(p.weekly_winnings.values())
        short = sum(p.weekly_wins[w] - max(q.weekly_wins[w] for q in s.players.values()) for w in s.weeks)
        p.points_paid, p.points_won = -40.0 + short, won
        p.net_points = p.points_paid + p.points_won
    s.big_losers_by_week = {1: ["MIA"], 2: []}
    s.current_week = 2
    s.workbook_path = Path("ACQL Dashboard.xlsx")
    return s


def kept_scores(season: Season):
    from acql.model.predictions import team_code
    by_week = {n: [Score(team_code(g.away), team_code(g.home), g.away_points, g.home_points, "post", True, kickoff=1.0)
                   for g in w.games] for n, w in season.weeks.items()}
    return lambda year, week: by_week.get(week, [])


def site_from(season: Season) -> dict:
    """What poolpage.snapshot would publish for this season (same fields)."""
    rows = []
    for p in season.ordered_players():
        rows.append({"name": p.display, "place": p.pos, "wins": p.wins, "net": p.net_points,
                     "weekly": {str(w): v for w, v in p.weekly_wins.items()}})
    return {"through_week": season.current_week, "money": "stats", "players": rows}


def ctx(season: Season, **over) -> engine.Context:
    args = dict(year=YEAR, now=1_000_000.0, scores=kept_scores(season), checked_at=lambda y, w: 999_000.0,
                ruling=lambda y, w: None, recount=reconcile.check, snapshot=site_from, feeds=lambda: [])
    args.update(over)
    return engine.Context(season, **args)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.previous = store._OVERRIDE
        store.use(Path(self.dir.name) / "t.db")

    def tearDown(self):
        store.use(self.previous)
        self.dir.cleanup()

    def open_findings(self, rep, check=None):
        return [f for f in rep.findings if f.open and (check is None or f.check == check)]


class CleanSeason(Scratch):
    def test_consistent_season_is_verified(self):
        rep = engine.run(ctx(make_season()))
        self.assertTrue(rep.complete, rep.checks)
        self.assertEqual(self.open_findings(rep), [], [f.title for f in rep.findings])
        self.assertEqual(rep.state, "verified")
        self.assertEqual(rep.health, 100)
        self.assertEqual(engine.publish_gate(rep), [])


class Scoring(Scratch):
    def test_card_that_does_not_add_up(self):
        s = make_season()
        s.weeks[1].lines["ann"].total_wins = 5
        rep = engine.run(ctx(s), only=("weekly",))
        hit = [f for f in rep.findings if f.field == "total_wins"]
        self.assertEqual(len(hit), 1)
        self.assertEqual((hit[0].status, hit[0].official, hit[0].computed), (engine.CONFIRMED, 5, 2))

    def test_official_total_against_recount_uses_the_line_rule(self):
        # KC won by 7 with a 3-point line: KC's pickers are right. Give Cat an
        # official 2 in week 1 when the picks score 0.
        s = make_season()
        s.weeks[1].lines["cat"].total_wins = 2
        s.weeks[1].lines["cat"].regular_wins = 2
        rep = engine.run(ctx(s), only=("weekly",))
        recount = [f for f in rep.findings if f.field == "recount"]
        self.assertEqual(len(recount), 1)
        self.assertEqual(recount[0].status, engine.CONFIRMED)
        self.assertIn(("Cat", 2, 0), recount[0].items)

    def test_line_favourite_failing_to_cover(self):
        # KC wins by only 2 against a 3-point line: DEN is credited. The file still says KC.
        s = make_season()
        g = s.weeks[1].games[0]
        g.home_points, g.away_points = 19, 17
        rep = engine.run(ctx(s), only=("weekly",))
        wrong = [f for f in rep.findings if f.field == "winner" and f.status == engine.CONFIRMED]
        self.assertEqual(len(wrong), 1)
        self.assertEqual((wrong[0].official, wrong[0].computed), ("KC", "DEN"))

    def test_ruling_settles_without_changing_values(self):
        s = make_season()
        s.weeks[1].lines["cat"].total_wins = s.weeks[1].lines["cat"].regular_wins = 2
        rep = engine.run(ctx(s, ruling=lambda y, w: {"ruling": "official", "note": "x", "at": 0} if w == 1 else None),
                         only=("weekly",))
        recount = [f for f in rep.findings if f.field == "recount"][0]
        self.assertEqual(recount.status, engine.SETTLED)
        self.assertEqual(s.weeks[1].lines["cat"].total_wins, 2)   # untouched

    def test_missing_final_is_unavailable_not_passed(self):
        s = make_season()
        rep = engine.run(ctx(s, scores=lambda y, w: []), only=("weekly",))
        self.assertTrue(any(f.status == engine.UNAVAILABLE for f in rep.findings))
        self.assertFalse(any(f.status == engine.CONFIRMED for f in rep.findings))


class Standings(Scratch):
    def test_season_total_not_sum_of_weeks(self):
        s = make_season()
        s.players["bob"].wins += 1
        rep = engine.run(ctx(s), only=("standings",))
        f = [f for f in rep.findings if f.field == "wins"]
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0].severity, f[0].official, f[0].computed), ("critical", 3, 2))

    def test_place_out_of_order(self):
        s = make_season()
        s.players["ann"].pos, s.players["cat"].pos = 3, 1
        rep = engine.run(ctx(s), only=("standings",))
        self.assertTrue(any(f.field == "pos" and f.status == engine.CONFIRMED for f in rep.findings))

    def test_tie_order_follows_last_week(self):
        s = make_season()
        a, b = s.players["bob"], s.players["cat"]
        a.wins = b.wins = 1
        a.weekly_wins = {1: 1, 2: 0}
        b.weekly_wins = {1: 0, 2: 1}
        a.pos, b.pos, a.prev_pos, b.prev_pos = 2, 3, 3, 2   # the tie rule wants Cat first
        a.games_behind = b.games_behind = float(s.players["ann"].wins - 1)
        rep = engine.run(ctx(s), only=("standings",))
        tie = [f for f in rep.findings if f.key.startswith("tie")]
        self.assertEqual(len(tie), 1)
        self.assertEqual(tie[0].status, engine.SUSPECTED)

    def test_games_behind(self):
        s = make_season()
        s.players["cat"].games_behind = 9.0
        rep = engine.run(ctx(s), only=("standings",))
        self.assertTrue(any(f.field == "games_behind" for f in rep.findings))


class Money(Scratch):
    def test_pot_not_fully_paid(self):
        s = make_season()
        s.players["ann"].weekly_winnings[1] -= 1
        rep = engine.run(ctx(s), only=("money",))
        self.assertTrue(any("payouts don't equal the pot" in f.title for f in rep.findings))

    def test_tied_pot_split_evenly(self):
        s = make_season()
        # week 2: make Ann and Bob tie on 2; pot is Cat's 1 behind, paid unevenly
        s.weeks[2].lines["bob"].total_wins = s.weeks[2].lines["bob"].regular_wins = 2
        for k in s.players:
            s.players[k].weekly_winnings.pop(2, None)
        s.players["bob"].weekly_wins[2] = 2
        s.players["ann"].weekly_winnings[2] = 0.75
        s.players["bob"].weekly_winnings[2] = 0.25
        rep = engine.run(ctx(s), only=("money",))
        self.assertTrue(any(f.key == "tie" for f in rep.findings), [f.title for f in rep.findings])

    def test_net_is_paid_plus_won(self):
        s = make_season()
        s.players["cat"].net_points += 5
        rep = engine.run(ctx(s), only=("money",))
        self.assertTrue(any(f.field == "net_points" and f.coach == "Cat" for f in rep.findings))


class StatsMoney(Scratch):
    def test_workbook_winnings_give_way_to_stats_scores(self):
        from acql import analytics
        s = make_season()
        s.players["ann"].weekly_winnings[1] = 5.0          # an old workbook figure; the pot is 3
        s.players["cat"].weekly_winnings[1] = 1.0          # paid to a coach without the top card
        analytics.fill_winnings(s)
        self.assertEqual(s.players["ann"].weekly_winnings[1], 3.0)
        self.assertNotIn(1, s.players["cat"].weekly_winnings)
        self.assertTrue(any("stats.xls payouts are used" in w for w in s.warnings))
        rep = engine.run(ctx(s), only=("money",))
        self.assertEqual([f.title for f in rep.findings if f.open], [])

    def test_coach_without_a_card_still_counts_in_the_pot(self):
        from acql import analytics
        s = make_season()
        del s.weeks[1].lines["cat"]                        # no card read; stats.xls scored Cat 0
        for p in s.players.values():
            p.weekly_winnings.pop(1, None)
        analytics.fill_winnings(s)
        self.assertEqual(s.players["ann"].weekly_winnings[1], 3.0)


class SidePools(Scratch):
    def test_survivor_alive_after_a_loss(self):
        s = make_season()
        p = s.players["bob"]
        p.suicide_alive = True
        p.suicide_picks = {1: "MIA"}
        rep = engine.run(ctx(s), only=("side_pools",))
        self.assertTrue(any(f.field == "suicide_alive" for f in rep.findings))

    def test_big_loser_more_than_blowouts(self):
        s = make_season()
        s.weeks[2].lines["ann"].big_loser_wins = 1
        s.weeks[2].lines["ann"].total_wins += 1
        rep = engine.run(ctx(s), only=("side_pools",))
        self.assertTrue(any(f.field == "big_loser_wins" for f in rep.findings))


class Records(Scratch):
    def test_duplicate_game_and_team_twice(self):
        s = make_season()
        s.weeks[1].games.append(Game(3, home="KC", away="DEN", winner="KC"))
        rep = engine.run(ctx(s), only=("records",))
        self.assertTrue(any(f.key.startswith("pair") for f in rep.findings))

    def test_duplicate_coach_spelling(self):
        s = make_season()
        s.players["ann2"] = Player(key="ann2", display="ANN")
        rep = engine.run(ctx(s), only=("records",))
        self.assertTrue(any(f.key == "dup" for f in rep.findings))

    def test_missing_official_score(self):
        s = make_season()
        s.players["cat"].official_weeks = {1}
        s.players["cat"].weekly_wins.pop(2)
        rep = engine.run(ctx(s), only=("records",))
        self.assertTrue(any(f.key == "missing" and f.week == 2 for f in rep.findings))

    def test_phantom_coach(self):
        s = make_season()
        s.players["x"] = Player(key="x", display="0.857")
        rep = engine.run(ctx(s), only=("records",))
        self.assertTrue(any(f.field == "roster" and f.status == engine.CONFIRMED for f in rep.findings))


class Freshness(Scratch):
    def test_stale_live_scores(self):
        s = make_season()
        live = [Score("dal", "phi", 7, 3, "in", False, kickoff=10.0)]
        rep = engine.run(ctx(s, scores=lambda y, w: live if w == 2 else [], checked_at=lambda y, w: 1.0),
                         only=("freshness",))
        self.assertTrue(any(f.field == "scores" and f.status == engine.SUSPECTED for f in rep.findings))

    def test_missing_stats_export_is_unavailable(self):
        s = make_season()
        s.sources = []
        rep = engine.run(ctx(s), only=("freshness",))
        self.assertTrue(any(f.status == engine.UNAVAILABLE and f.severity == "critical" for f in rep.findings))
        self.assertEqual(rep.state, "incomplete")

    def test_failing_feed(self):
        from acql.sourcehealth import Health
        h = Health("espn", 5, 0, None, 999_000.0, "timeout", None, "")
        rep = engine.run(ctx(make_season(), feeds=lambda: [h]), only=("freshness",))
        self.assertTrue(any(f.field == "feed" for f in rep.findings))

    def test_weeks_past_export_are_a_note_not_official(self):
        s = make_season()
        s.sources[0].week = 1
        rep = engine.run(ctx(s), only=("freshness",))
        note = [f for f in rep.findings if f.key == "rolled"]
        self.assertEqual(note[0].status, engine.NOTE)


class CrossPage(Scratch):
    def test_website_shows_different_wins(self):
        s = make_season()

        def site(season):
            d = site_from(season)
            d["players"][0]["wins"] += 1
            d["players"][0]["weekly"]["1"] += 1
            return d
        rep = engine.run(ctx(s, snapshot=site), only=("cross_page",))
        fields = {f.field for f in rep.findings if f.status == engine.CONFIRMED}
        self.assertIn("wins", fields)
        self.assertIn("weekly", fields)

    def test_real_site_builder_agrees(self):
        """The actual website data builder against the same season."""
        from acql.ui import poolpage
        rep = engine.run(ctx(make_season(), snapshot=poolpage.snapshot), only=("cross_page",))
        self.assertTrue(rep.checks["cross_page"]["ran"], rep.checks)
        self.assertEqual([f.title for f in rep.findings if f.status == engine.CONFIRMED], [])


class History(Scratch):
    def make_ctx(self, season, **kw):
        return lambda s, **more: ctx(s, **{**more, **kw})

    def test_baseline_grows_then_catches_a_changed_record(self):
        s = make_season()
        history.run(s, make_context=self.make_ctx(s))
        self.assertEqual(sorted(history.baseline()[str(YEAR)]), ["1", "2"])
        s2 = make_season()
        s2.players["bob"].weekly_wins[1] = 0          # someone loaded a different export
        s2.players["bob"].wins = 1
        d = history.run(s2, make_context=self.make_ctx(s2))
        moved = [f for f in d["findings"] if f["check"] == "history"]
        self.assertEqual(moved[0]["severity"], "critical")
        self.assertIn(["Bob", 1, 0], moved[0]["items"])
        # the accepted record was not overwritten by the failing run
        self.assertEqual(history.baseline()[str(YEAR)]["1"]["Bob"], 1)
        self.assertTrue(engine.publish_gate(d))

    def test_accepting_a_change_needs_name_and_note(self):
        s = make_season()
        history.run(s, make_context=self.make_ctx(s))
        s.players["bob"].weekly_wins[1] = 0
        with self.assertRaises(ValueError):
            history.decide("accept_change", by="", note="", week=1, year=YEAR, season=s)
        history.decide("accept_change", by="Sam", note="commissioner corrected week 1", week=1, year=YEAR, season=s)
        self.assertEqual(history.baseline()[str(YEAR)]["1"]["Bob"], 0)
        self.assertEqual(history.decisions()[-1]["value"]["before"]["Bob"], 1)

    def test_correction_is_logged_and_changes_nothing(self):
        s = make_season()
        history.decide("correction", by="Sam", note="Ann week 1 should be 1", finding="abc", week=1, year=YEAR, value=1)
        self.assertEqual(s.weeks[1].lines["ann"].total_wins, 2)
        self.assertIn("nothing here was changed", history.decisions()[-1]["status"])

    def test_ruling_goes_through_rulings(self):
        history.decide("ruling", by="Sam", note="follow stats", week=3, year=YEAR, choice="official")
        self.assertEqual(rulings.get(YEAR, 3)["ruling"], "official")

    def test_issue_log_resolves_only_when_check_ran(self):
        s = make_season()
        s.players["cat"].games_behind = 9.0
        history.run(s, make_context=self.make_ctx(s))
        fid = next(k for k, v in history.issues().items() if v["check"] == "standings")
        s.players["cat"].games_behind = float(s.players["ann"].wins - s.players["cat"].wins)
        history.run(s, make_context=self.make_ctx(s))
        self.assertIsNotNone(history.issues()[fid]["resolved_at"])

    def test_ensure_reuses_and_debounces(self):
        s = make_season()
        calls = []

        def counting(season, **kw):
            calls.append(1)
            return ctx(season, **{k: v for k, v in kw.items() if k != "now"}, now=kw.get("now", 1_000_000.0))
        history.ensure(s, now=1_000_000.0, make_context=counting)
        history.ensure(s, now=1_000_010.0, make_context=counting)      # same inputs: reused
        self.assertEqual(len(calls), 1)
        history.ensure(s, now=1_000_020.0, force=True, make_context=counting)
        self.assertEqual(len(calls), 2)


class Recovery(Scratch):
    def test_crashing_check_is_incomplete_not_passed(self):
        def broken(season):
            raise RuntimeError("site builder broke")
        rep = engine.run(ctx(make_season(), snapshot=broken))
        self.assertFalse(rep.complete)
        self.assertFalse(rep.checks["cross_page"]["ran"])
        self.assertEqual(rep.state, "incomplete")
        self.assertIn("the last integrity run didn't complete", engine.publish_gate(rep))

    def test_recover_after_failure_keeps_last_good_and_baseline(self):
        s = make_season()
        good = history.run(s, now=1_000_000.0, make_context=lambda se, **kw: ctx(se, **kw))
        base = json.dumps(history.baseline(), sort_keys=True)

        def broken_loader():
            raise OSError("stats.xls is locked by Excel")
        d = history.recover(broken_loader, now=1_000_100.0)
        self.assertFalse(d["complete"])
        self.assertEqual(d["trusted"]["run_at"], good["run_at"])
        self.assertEqual(json.dumps(history.baseline(), sort_keys=True), base)
        # the file is free again: recovery validates and the new run is trusted
        d2 = history.recover(make_season, now=1_000_200.0, make_context=lambda se, **kw: ctx(se, **kw))
        self.assertTrue(d2["complete"])
        self.assertEqual(d2["trusted"]["run_at"], 1_000_200.0)
        self.assertEqual(history.last_good()["run_at"], 1_000_200.0)


class CenterGuards(Scratch):
    def setUp(self):
        super().setUp()
        self.center = center.Center(loader=make_season, make_context=lambda s, **kw: ctx(s, **kw))
        self.server = center.serve(0, self.center)
        self.port = self.server.server_address[1]
        Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read() or b"null") if "json" in r.headers.get("Content-Type", "") else None
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def test_post_needs_header(self):
        self.assertEqual(self.call("/api/run", {})[0], 403)

    def test_run_then_report_then_decide(self):
        status, d = self.call("/api/run", {}, {"X-Integrity": "1"})
        self.assertEqual((status, d["state"]), (200, "verified"))
        status, rep = self.call("/api/report")
        self.assertEqual(rep["last"]["state"], "verified")
        status, err = self.call("/api/decide", {"kind": "acknowledge", "by": "", "note": ""}, {"X-Integrity": "1"})
        self.assertEqual(status, 400)
        status, ok = self.call("/api/decide", {"kind": "acknowledge", "by": "Sam", "note": "known", "finding": "x"},
                               {"X-Integrity": "1"})
        self.assertEqual(status, 200)

    def test_page_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as r:
            self.assertIn(b"Integrity Center", r.read())


if __name__ == "__main__":
    unittest.main(verbosity=1)
