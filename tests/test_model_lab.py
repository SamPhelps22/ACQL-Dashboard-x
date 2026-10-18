#!/usr/bin/env python3
"""Tests for the Model Lab's forecast log (acql/model/forecastlog.py).

Run from the project root:

    python tests/test_model_lab.py

Begun as the starter module's own tests; the rest check what was added to fit
the app: tables in a scratch acql.db, CSV eligibility worked out again, the
same source record never logged twice, ties left out, and `bring_in` taking
only what the ledger and fetched lines can date - on made-up games. The
last class builds the Model Lab page's new view, so it needs PySide6.
"""

from __future__ import annotations

import csv
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql.model.forecastlog import (  # noqa: E402
    add_prediction, brier_score, connect, determine_eligibility, evaluate_models, export_evaluation_csv,
    export_history_csv, export_template_csv, import_predictions_csv, log_loss, no_vig_two_way,
    register_model, upsert_game,
)
from acql.model import forecastlog  # noqa: E402

KICK = "2026-10-18T17:00:00+00:00"


class ModelLabTests(unittest.TestCase):
    """The starter's own known answers."""

    def test_american_odds_and_no_vig(self):
        self.assertAlmostEqual(no_vig_two_way(-110, -110)[0], 0.5)
        self.assertAlmostEqual(sum(no_vig_two_way(-120, 100)), 1.0)

    def test_brier_known_answer(self):
        self.assertAlmostEqual(brier_score([0.8, 0.3], [1, 0]), 0.065)

    def test_log_loss_known_answer(self):
        self.assertAlmostEqual(log_loss([0.8, 0.3], [1, 0]), -(math.log(0.8) + math.log(0.7)) / 2)

    def test_empty_metrics(self):
        self.assertIsNone(brier_score([], []))
        self.assertIsNone(log_loss([], []))

    def test_probability_validation(self):
        with self.assertRaises(ValueError):
            brier_score([1.2], [1])

    def test_eligible_when_in_before_cutoff(self):
        status, _ = determine_eligibility(KICK, "2026-10-18T14:00:00+00:00", 60, "2026-10-18T14:00:00+00:00")
        self.assertEqual(status, "eligible")

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            determine_eligibility(KICK, "2026-10-18T14:00:00", 60, "2026-10-18T14:00:00+00:00")

    def test_missing_publication_time_not_assumed_eligible(self):
        status, _ = determine_eligibility(KICK, "2026-10-18T14:00:00+00:00", 60, None)
        self.assertEqual(status, "missing_timestamp")

    def test_late_and_postgame(self):
        self.assertEqual(determine_eligibility(KICK, "2026-10-18T16:30:00+00:00", 60, "2026-10-18T16:30:00+00:00")[0],
                         "late")
        self.assertEqual(determine_eligibility(KICK, "2026-10-18T17:00:00+00:00", 60, "2026-10-18T13:00:00+00:00")[0],
                         "postgame")


class _Log(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="acql-lab-test-"))
        self.conn = connect(self.folder / "test.db")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.folder, ignore_errors=True)

    def game(self, gid="game1", home=24, away=17, kick=KICK, week=7):
        upsert_game(self.conn, gid, 2026, week, kick, "AWAY", "HOME", away, home, "final")

    def predict(self, model, p, gid="game1", status="eligible", ref="", winner=None):
        return add_prediction(self.conn, game_id=gid, model_id=model, home_win_probability=p,
                              predicted_winner=winner, retrieved_at_utc="2026-10-18T14:00:00+00:00",
                              source_published_at_utc="2026-10-18T13:55:00+00:00",
                              eligibility_status=status, source_reference=ref, snapshot_key="wk7")


class TestScoring(_Log):
    def test_append_and_evaluate(self):
        register_model(self.conn, "deadeye", "Deadeye")
        self.game(home=17, away=24)                 # the road side won
        self.predict("deadeye", 0.7, winner="HOME")
        result = evaluate_models(self.conn, season=2026, snapshot_key="wk7")
        self.assertEqual((len(result), result[0]["games"]), (1, 1))
        self.assertAlmostEqual(result[0]["brier_score"], 0.49)
        self.assertEqual(result[0]["winner_accuracy"], 0.0)

    def test_only_eligible_scored(self):
        register_model(self.conn, "m", "M")
        self.game()
        self.predict("m", 0.9, status="postgame")
        self.assertEqual(evaluate_models(self.conn), [])

    def test_duplicates_left_out_and_counted(self):
        register_model(self.conn, "m", "M")
        self.game()
        self.predict("m", 0.6)
        self.predict("m", 0.7)
        self.assertEqual(evaluate_models(self.conn), [])
        result = evaluate_models(self.conn, eligible_only=False)
        self.assertEqual(result, [])
        self.game("game2")
        self.predict("m", 0.6, gid="game2")
        self.assertEqual(evaluate_models(self.conn)[0]["duplicate_game_records_excluded"], 2)

    def test_tie_left_out(self):
        register_model(self.conn, "m", "M")
        self.game(home=20, away=20)
        self.predict("m", 0.6)
        self.assertEqual(evaluate_models(self.conn), [])

    def test_common_games_only(self):
        for m in ("a", "b"):
            register_model(self.conn, m, m.upper())
        self.game("g1")
        self.game("g2")
        self.predict("a", 0.6, "g1")
        self.predict("a", 0.6, "g2")
        self.predict("b", 0.7, "g1")
        self.assertEqual({r["model_id"]: r["games"] for r in evaluate_models(self.conn)}, {"a": 2, "b": 1})
        self.assertEqual({r["model_id"]: r["games"] for r in evaluate_models(self.conn, common_only=True)},
                         {"a": 1, "b": 1})

    def test_append_only(self):
        register_model(self.conn, "m", "M")
        self.game()
        first = self.predict("m", 0.6)
        second = self.predict("m", 0.6)
        self.assertNotEqual(first, second)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM lab_predictions").fetchone()[0], 2)


class TestCsv(_Log):
    def write(self, rows, fields=None):
        path = self.folder / "in.csv"
        fields = fields or list(rows[0])
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_status_worked_out_again_and_new_model_registered(self):
        self.game()
        path = self.write([
            {"game_id": "game1", "model_id": "friend", "model_name": "A Friend", "home_win_probability": "0.6",
             "retrieved_at_utc": "2026-10-18T16:45:00+00:00", "source_published_at_utc": "2026-10-18T16:40:00+00:00",
             "eligibility_status": "eligible"},
            {"game_id": "nope", "model_id": "friend", "model_name": "", "home_win_probability": "0.6",
             "retrieved_at_utc": "2026-10-18T14:00:00+00:00", "source_published_at_utc": "",
             "eligibility_status": ""},
        ])
        done = import_predictions_csv(self.conn, path)
        self.assertEqual((done["rows_imported"], done["rows_rejected"]), (1, 1))
        row = self.conn.execute("SELECT * FROM lab_predictions").fetchone()
        self.assertEqual(row["eligibility_status"], "late")        # the file said eligible; the times say late
        self.assertIn("file said 'eligible'", row["data_quality_note"])
        name = self.conn.execute("SELECT display_name FROM lab_models WHERE model_id='friend'").fetchone()[0]
        self.assertEqual(name, "A Friend")
        self.assertEqual(self.conn.execute("SELECT rows_rejected FROM lab_import_log").fetchone()[0], 1)

    def test_missing_columns_refused(self):
        with self.assertRaises(ValueError):
            import_predictions_csv(self.conn, self.write([{"game_id": "x"}]))

    def test_exports_round_trip(self):
        register_model(self.conn, "m", "M")
        self.game()
        self.predict("m", 0.6)
        board = self.folder / "board.csv"
        export_evaluation_csv(evaluate_models(self.conn), board)
        with open(board, encoding="utf-8") as f:
            self.assertEqual(next(csv.DictReader(f))["model_id"], "m")
        self.assertEqual(export_history_csv(self.conn, self.folder / "h.csv"), 1)
        template = self.folder / "t.csv"
        self.assertEqual(export_template_csv(self.conn, template, 2026, 7), 1)
        # the blank template goes back in: every row turned away for want of numbers, nothing half-written
        done = import_predictions_csv(self.conn, template)
        self.assertEqual(done["rows_imported"], 0)


GAMES_HEADER = ("game_id,season,game_type,week,gameday,weekday,gametime,away_team,away_score,home_team,home_score,"
                "location,result,total,away_moneyline,home_moneyline,spread_line")


class TestGamesCsv(_Log):
    """nflverse's games.csv: games and results in, never forecasts."""

    def write(self, lines, header=GAMES_HEADER, name="games.csv"):
        path = self.folder / name
        path.write_text("\n".join([header] + lines) + "\n", encoding="utf-8")
        return path

    def test_games_and_results_import_without_prediction_columns(self):
        path = self.write([
            "2026_05_TB_DAL,2026,REG,5,2026-10-08,Thursday,20:15,TB,24,DAL,16,Home,-8,40,400,-535,9.5",
            "2026_18_PHI_NYG,2026,REG,18,2027-01-10,Sunday,13:00,PHI,,NYG,,Home,,,,,",
            "2026_05_LA_SF,2026,REG,5,2026-10-11,Sunday,16:25,LA,20,SF,20,Home,0,40,,,",
        ])
        self.assertEqual(forecastlog.csv_kind(path), "games")
        done = forecastlog.import_games_csv(self.conn, path)
        self.assertEqual((done["rows_imported"], done["rows_rejected"], done["finals"]), (3, 0, 2))
        games = {r["game_id"]: r for r in self.conn.execute("SELECT * FROM lab_games")}
        played = games["2026-W05-TB@DAL"]
        self.assertEqual((played["away_score"], played["home_score"], played["status"]), (24, 16, "final"))
        self.assertEqual(played["kickoff_utc"], "2026-10-09T00:15:00+00:00")     # 20:15 Eastern, summer time
        later = games["2026-W18-PHI@NYG"]
        self.assertEqual((later["away_score"], later["home_score"], later["status"]), (None, None, "scheduled"))
        self.assertEqual(later["kickoff_utc"], "2027-01-10T18:00:00+00:00")      # winter time
        self.assertIn("2026-W05-LAR@SF", games)                                   # nflverse's LA is the app's lar
        # nothing was made into a forecast - the moneylines carry no time they were taken
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM lab_predictions").fetchone()[0], 0)

    def test_no_kickoff_time_is_turned_away_not_made_up(self):
        done = forecastlog.import_games_csv(self.conn, self.write([
            "1999_01_MIN_ATL,1999,REG,1,1999-09-12,Sunday,,MIN,17,ATL,14,Home,-3,31,,,-4"]))
        self.assertEqual((done["rows_imported"], done["rows_rejected"]), (0, 1))
        self.assertIn("kickoff", done["errors"][0]["error"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM lab_games").fetchone()[0], 0)

    def test_one_sided_score_rejected(self):
        done = forecastlog.import_games_csv(self.conn, self.write([
            "2026_05_TB_DAL,2026,REG,5,2026-10-08,Thursday,20:15,TB,24,DAL,,Home,,,,,"]))
        self.assertEqual(done["rows_rejected"], 1)

    def test_seasons_filter_and_reimport_updates_in_place(self):
        path = self.write(["2025_05_TB_DAL,2025,REG,5,2025-10-05,Sunday,13:00,TB,24,DAL,16,Home,,,,,",
                           "2026_05_TB_DAL,2026,REG,5,2026-10-08,Thursday,20:15,TB,,DAL,,Home,,,,,"])
        done = forecastlog.import_games_csv(self.conn, path, seasons=[2026])
        self.assertEqual((done["rows_imported"], done["other_seasons"]), (1, 1))
        path = self.write(["2026_05_TB_DAL,2026,REG,5,2026-10-08,Thursday,20:15,TB,24,DAL,16,Home,,,,,"])
        forecastlog.import_games_csv(self.conn, path)
        rows = self.conn.execute("SELECT * FROM lab_games").fetchall()
        self.assertEqual([(r["away_score"], r["status"]) for r in rows], [(24, "final")])

    def test_neutral_site_kept_in_the_logs_orientation(self):
        upsert_game(self.conn, "2026-W05-JAX@PHI", 2026, 5, "2026-10-11T13:30:00+00:00", "JAX", "PHI")
        forecastlog.import_games_csv(self.conn, self.write([
            "2026_05_PHI_JAX,2026,REG,5,2026-10-11,Sunday,09:30,PHI,17,JAX,19,Neutral,2,36,,,"]))
        rows = self.conn.execute("SELECT * FROM lab_games").fetchall()
        self.assertEqual([(r["game_id"], r["away_score"], r["home_score"]) for r in rows],
                         [("2026-W05-JAX@PHI", 19, 17)])

    def test_missing_games_columns(self):
        with self.assertRaises(ValueError) as caught:
            forecastlog.import_games_csv(self.conn, self.write(["x,2026"], header="game_id,season"))
        self.assertIn("gameday", str(caught.exception))

    def test_games_file_into_forecasts_importer_says_which_importer(self):
        path = self.write(["2026_05_TB_DAL,2026,REG,5,2026-10-08,Thursday,20:15,TB,24,DAL,16,Home,,,,,"])
        with self.assertRaises(ValueError) as caught:
            import_predictions_csv(self.conn, path)
        self.assertIn("games", str(caught.exception))

    def test_games_then_forecasts_scored(self):
        forecastlog.import_games_csv(self.conn, self.write([
            "2026_05_TB_DAL,2026,REG,5,2026-10-08,Thursday,20:15,TB,24,DAL,16,Home,,,,,"]))
        path = self.write(["2026-W05-TB@DAL,friend,0.3,2026-10-08T12:00:00+00:00,2026-10-08T11:00:00+00:00"],
                          header="game_id,model_id,home_win_probability,retrieved_at_utc,source_published_at_utc",
                          name="f.csv")
        self.assertEqual(forecastlog.csv_kind(path), "predictions")
        self.assertEqual(import_predictions_csv(self.conn, path)["rows_imported"], 1)
        board = evaluate_models(self.conn)
        self.assertAlmostEqual(board[0]["brier_score"], 0.09)


class TestForecastCsvStrict(_Log):
    HEADER = "game_id,model_id,home_win_probability,retrieved_at_utc,source_published_at_utc"

    def run_rows(self, *lines):
        self.game()
        path = self.folder / "f.csv"
        path.write_text("\n".join([self.HEADER] + list(lines)) + "\n", encoding="utf-8")
        return import_predictions_csv(self.conn, path)

    def test_bad_rows_each_turned_away(self):
        ok = "2026-10-18T12:00:00+00:00"
        done = self.run_rows(
            f"game1,m,1.2,{ok},{ok}",                       # probability above 1
            f"game1,m,-0.1,{ok},{ok}",                      # below 0
            f"game1,m,nan,{ok},{ok}",                       # not a number
            f"game1,m,,{ok},{ok}",                          # empty
            f"game1,bad id!,0.5,{ok},{ok}",                 # model id
            f"game1,,0.5,{ok},{ok}",                        # no model id
            "game1,m,0.5,2026-10-18T12:00:00,",             # no timezone
            f"nope,m,0.5,{ok},{ok}",                        # unknown game
        )
        self.assertEqual((done["rows_imported"], done["rows_rejected"]), (0, 8))

    def test_missing_prediction_columns(self):
        path = self.folder / "f.csv"
        path.write_text("game_id,model_id\nx,y\n", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            import_predictions_csv(self.conn, path)
        self.assertIn("home_win_probability", str(caught.exception))

    def test_duplicates_turned_away_in_file_and_on_reimport(self):
        ok = "2026-10-18T12:00:00+00:00"
        done = self.run_rows(f"game1,m,0.6,{ok},{ok}", f"game1,m,0.6,{ok},{ok}")
        self.assertEqual((done["rows_imported"], done["rows_rejected"]), (1, 1))
        self.assertIn("duplicate", done["errors"][0]["error"])
        again = self.run_rows(f"game1,m,0.6,{ok},{ok}")
        self.assertEqual(again["rows_imported"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM lab_predictions").fetchone()[0], 1)

    def test_game_without_final_score_is_logged_not_scored(self):
        upsert_game(self.conn, "later", 2026, 8, "2026-10-25T17:00:00+00:00", "AWAY", "HOME")
        path = self.folder / "f.csv"
        ok = "2026-10-20T12:00:00+00:00"
        path.write_text(f"{self.HEADER}\nlater,m,0.6,{ok},{ok}\n", encoding="utf-8")
        self.assertEqual(import_predictions_csv(self.conn, path)["rows_imported"], 1)
        self.assertEqual(evaluate_models(self.conn), [])


class TestBringIn(unittest.TestCase):
    """Only what can be dated comes across, and the same record never twice."""

    KICK = 1_792_342_800.0              # 2026-10-18 17:00 UTC

    def setUp(self):
        from acql import store
        self.folder = Path(tempfile.mkdtemp(prefix="acql-lab-test-"))
        self.previous = store._OVERRIDE
        store.use(self.folder / "test.db")
        for kind in ("odds", "forecasts", "picks", "ledger"):
            store.delete(kind)
        k = self.KICK
        store.put("ledger", "2026-7", {"at": k + 86400, "version": "t", "games": [
            {"index": 1, "road": "sea", "home": "den", "kickoff": k, "at": k - 7200, "before": True,
             "margins": {"Deadeye": 3.0}},
            {"index": 2, "road": "chi", "home": "atl", "kickoff": k, "at": k + 86400, "before": False,
             "margins": {"Deadeye": -2.0}}]})
        store.put("odds", "weeks", {"7": {
            "at": k - 600, "win": {"sea@den": 0.6},
            "history": [{"at": k - 9000, "lines": {"sea@den": 2.5, "atl@chi": 1.0}},
                        {"at": k - 1800, "lines": {"sea@den": 3.5}}]}})
        self.scores = [
            SimpleNamespace(away="sea", home="den", away_points=10, home_points=20, final=True, state="post",
                            kickoff=k),
            SimpleNamespace(away="chi", home="atl", away_points=21, home_points=14, final=True, state="post",
                            kickoff=k),
        ]

    def tearDown(self):
        from acql import store
        store.use(self.previous)
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_dated_records_only_and_idempotent(self):
        conn = connect()
        try:
            with mock.patch("acql.feeds.results.load", lambda year, week: self.scores):
                made = forecastlog.bring_in(conn, 2026, now=self.KICK + 2 * 86400)
                again = forecastlog.bring_in(conn, 2026, now=self.KICK + 2 * 86400)
            self.assertEqual((made["ledger"], made["lines"], made["moneylines"]), (2, 2, 1))
            self.assertEqual(again["ledger"] + again["lines"] + again["moneylines"], 0)
            status = {(r["model_id"], r["game_id"]): r for r in conn.execute("SELECT * FROM lab_predictions")}
            self.assertEqual(status[("deadeye", "2026-W07-SEA@DEN")]["eligibility_status"], "eligible")
            self.assertEqual(status[("deadeye", "2026-W07-CHI@ATL")]["eligibility_status"], "postgame")
            # the line taken is the last fetched before the cutoff, not the one 30 minutes out
            spread = status[(forecastlog.MARKET_SPREAD, "2026-W07-SEA@DEN")]
            self.assertIn("+2.5", spread["data_quality_note"])
            self.assertGreater(spread["home_win_probability"], 0.5)
            # neutral site: the line was kept the other way round, so the chance is turned over
            flipped = status[(forecastlog.MARKET_SPREAD, "2026-W07-CHI@ATL")]
            self.assertLess(flipped["home_win_probability"], 0.5)
            self.assertEqual(status[(forecastlog.MARKET_MONEYLINE, "2026-W07-SEA@DEN")]["eligibility_status"], "late")
            names = {r["model_name"]: r["games"] for r in evaluate_models(conn, season=2026)}
            self.assertEqual(names, {"Deadeye": 1, "Betting line (fetched)": 2})
        finally:
            conn.close()

    def test_lines_wait_for_the_cutoff(self):
        conn = connect()
        try:
            with mock.patch("acql.feeds.results.load", lambda year, week: self.scores):
                made = forecastlog.bring_in(conn, 2026, now=self.KICK - 4 * 3600)
            self.assertEqual(made["lines"] + made["moneylines"], 0)
        finally:
            conn.close()


class TestScorecard(_Log):
    """Every past forecast graded: hit rate, average miss, and against the closing line."""

    def line(self, gid, margin, at="2026-10-18T15:00:00+00:00"):
        register_model(self.conn, forecastlog.MARKET_SPREAD, "Betting line (fetched)", model_type="market")
        add_prediction(self.conn, game_id=gid, model_id=forecastlog.MARKET_SPREAD,
                       home_win_probability=0.5 + (0.1 if margin > 0 else -0.1), predicted_winner=None,
                       retrieved_at_utc=at, source_published_at_utc=at, eligibility_status="eligible",
                       raw_payload={"home_margin": margin})

    def scored(self, model, gid, home, away, status="eligible", p=None):
        add_prediction(self.conn, game_id=gid, model_id=model,
                       home_win_probability=p if p is not None else (0.6 if home > away else 0.4),
                       predicted_winner=None, retrieved_at_utc="2026-10-18T14:00:00+00:00",
                       source_published_at_utc="2026-10-18T13:55:00+00:00", eligibility_status=status,
                       projected_home_score=home, projected_away_score=away)

    def test_hit_rate_miss_and_closing_line(self):
        register_model(self.conn, "m", "M")
        self.game("g1", home=24, away=17)                     # home by 7
        self.game("g2", home=10, away=20, week=8)             # road by 10
        self.line("g1", 3.0)                                  # line missed by 4
        self.line("g2", 2.0)                                  # line missed by 12
        self.scored("m", "g1", 30, 20)                        # had the winner, missed by 3: beat it
        self.scored("m", "g2", 27, 20)                        # wrong winner, missed by 17: lost
        [m] = [r for r in forecastlog.scorecard(self.conn, 2026) if r["model_id"] == "m"]
        self.assertEqual((m["games"], m["hits"], m["picks"]), (2, 1, 2))
        self.assertAlmostEqual(m["hit_rate"], 0.5)
        self.assertAlmostEqual(m["avg_miss"], 10.0)
        self.assertEqual((m["beat_line"], m["lost_to_line"], m["beat_line_rate"]), (1, 1, 0.5))
        self.assertAlmostEqual(m["line_edge"], ((4 - 3) + (12 - 17)) / 2)
        # the running tally: after week 7 it was unbeaten against the close
        self.assertEqual([(w["week"], w["beat_line"], w["games"]) for w in m["weeks"]], [(7, 1, 1), (8, 1, 2)])
        line = [r for r in forecastlog.scorecard(self.conn, 2026) if r["model_id"] == forecastlog.MARKET_SPREAD][0]
        self.assertEqual(line["line_games"], 0)               # nothing for the line to beat
        self.assertAlmostEqual(line["avg_miss"], 8.0)

    def test_latest_line_is_the_close(self):
        register_model(self.conn, "m", "M")
        self.game("g1", home=24, away=17)
        self.line("g1", 10.0, at="2026-10-18T12:00:00+00:00")
        self.line("g1", 3.0, at="2026-10-18T15:00:00+00:00")
        self.scored("m", "g1", 25, 20)
        [g] = [r for r in forecastlog.grade_forecasts(self.conn) if r["model_id"] == "m"]
        self.assertEqual((g["closing_line"], g["versus_line"]), (3.0, "beat"))

    def test_only_eligible_ties_and_duplicates(self):
        register_model(self.conn, "m", "M")
        self.game("tie", home=20, away=20)
        self.game("g2", home=24, away=17)
        self.scored("m", "tie", 23, 20)                       # graded on its miss, no winner to have
        self.scored("m", "g2", 21, 20, status="late")         # not graded
        [m] = forecastlog.scorecard(self.conn, 2026)
        self.assertEqual((m["games"], m["picks"], m["avg_miss"]), (1, 0, 3.0))
        self.scored("m", "tie", 24, 20)                       # two eligible on one game: left out
        self.assertEqual(forecastlog.scorecard(self.conn, 2026), [])

    def test_brought_in_margin_follows_its_win_chance(self):
        register_model(self.conn, "r", "R")
        self.game("g1", home=24, away=17)
        add_prediction(self.conn, game_id="g1", model_id="r", home_win_probability=0.3, predicted_winner=None,
                       retrieved_at_utc="2026-10-18T14:00:00+00:00",
                       source_published_at_utc="2026-10-18T14:00:00+00:00", eligibility_status="eligible",
                       raw_payload={"margin": 4.0})            # neutral site, written the other way round
        [g] = forecastlog.grade_forecasts(self.conn)
        self.assertEqual((g["home_margin"], g["hit"], g["miss"]), (-4.0, False, 11.0))

    def test_export(self):
        register_model(self.conn, "m", "M")
        self.game("g1")
        self.scored("m", "g1", 24, 20)
        path = self.folder / "card.csv"
        forecastlog.export_scorecard_csv(forecastlog.scorecard(self.conn, 2026), path)
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        self.assertEqual([(r["week"], r["games"]) for r in rows], [("7", "1"), ("", "1")])


class TestOutsideForecastsView(unittest.TestCase):
    """The Model Lab page builds with its fifth view and fills it from a scratch log."""

    def test_view_fills(self):
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"PySide6 unavailable: {exc}")
        from acql import store
        from acql.ui.pages import modellab
        app = QApplication.instance() or QApplication([])
        folder = Path(tempfile.mkdtemp(prefix="acql-lab-test-"))
        previous = store._OVERRIDE
        store.use(folder / "test.db")
        try:
            conn = connect()
            register_model(conn, "m", "M")
            upsert_game(conn, "g", 2026, 7, KICK, "SEA", "DEN", 10, 20, "final")
            add_prediction(conn, game_id="g", model_id="m", home_win_probability=0.6, predicted_winner="DEN",
                           retrieved_at_utc="2026-10-18T10:00:00+00:00",
                           source_published_at_utc="2026-10-18T10:00:00+00:00", eligibility_status="eligible")
            conn.close()
            self.assertEqual(modellab.VIEWS[modellab.OUTSIDE][0], "Outside forecasts")
            from acql.ui.widgets import theme_palette
            page = modellab.ModelLabPage(theme_palette())
            page.outside.refresh(2026)
            self.assertIn("1 forecasts in the log, 1 of them eligible", page.outside.lead.text())
            self.assertEqual(page.outside.week_pick.currentData(), 7)
            self.assertEqual(page.outside.model_pick.count(), 2)
            self.assertIn("Hit rate", page.outside.score_note.text())
            page.deleteLater()
            app.processEvents()
        finally:
            store.use(previous)
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
