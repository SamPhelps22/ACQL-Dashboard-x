#!/usr/bin/env python3
"""Tests for the Model Lab's historical dataset (lab/history).

Run on their own or as part of the suite:

    python tests/test_lab_history.py
    python tests/run_tests.py

The leakage tests build a small invented season through the real build
pipeline - schedule, a Prediction Tracker file, the app's fetched odds, a
pool sheet - then try to influence each prediction record with information
dated after its cutoff. No network, no Qt, and the app's database is never
opened.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import predictions  # noqa: E402
from lab.history import asof, build, schema  # noqa: E402

# 2030 week 1: Thursday night opener, then Sunday afternoon. 2029 week 1 uses
# different matchups so the season of a store slate has to be worked out.
THURSDAY = ("2030-09-05", "20:15")
SUNDAY = ("2030-09-08", "13:00")
SCHEDULE = [
    # game_id, season, week, (day, time), away, home, away pts, home pts, spread, total, ml home, ml away
    ("2030_01_BAL_KC", 2030, 1, THURSDAY, "BAL", "KC", 20, 27, 3.0, 47.5, -150, 130),
    ("2030_01_ATL_PIT", 2030, 1, SUNDAY, "ATL", "PIT", 17, 10, 2.5, 41.0, -135, 115),
    ("2030_01_NE_MIA", 2030, 1, SUNDAY, "NE", "MIA", 14, 24, 6.5, 44.0, -270, 220),
    ("2030_01_SF_SEA", 2030, 1, SUNDAY, "SF", "SEA", 31, 28, -3.5, 45.5, 160, -190),
    ("2030_01_DAL_NYG", 2030, 1, SUNDAY, "DAL", "NYG", 24, 24, -1.0, 43.0, 105, -125),
    ("2030_01_LA_LAC", 2030, 1, SUNDAY, "LA", "LAC", 21, 20, None, None, None, None),
    ("2029_01_BAL_KC", 2029, 1, ("2029-09-06", "20:20"), "BAL", "KC", 10, 13, 4.0, 46.0, -180, 155),
    ("2029_01_CHI_GB", 2029, 1, ("2029-09-09", "13:00"), "CHI", "GB", 3, 6, 5.5, 39.0, -240, 200),
    ("2029_01_DEN_LV", 2029, 1, ("2029-09-09", "16:25"), "DEN", "LV", 7, 3, -2.0, 40.0, 110, -130),
    ("2029_01_TEN_HOU", 2029, 1, ("2029-09-09", "13:00"), "TEN", "HOU", 9, 19, 7.0, 42.0, -320, 260),
]

# The Prediction Tracker file for 2030 week 1. SF @ SEA is written the other
# way round (SEA as road) to prove a flipped row is turned around.
PT_ROWS = [
    # road, home, lineopen, line, linesag, linemass, lineavg
    ("Baltimore", "Kansas City", 2.5, 3.0, 4.0, 1.0, 2.5),
    ("Atlanta", "Pittsburgh", 3.0, 2.5, 0.5, 6.0, 3.25),
    ("New England", "Miami", 7.0, 6.5, 9.0, 5.0, 7.0),
    ("Seattle", "San Francisco", -3.0, -3.5, -6.0, -1.0, -3.5),
    ("Dallas", "New York Giants", -1.5, -1.0, 2.0, -2.0, 0.0),
]


def iso_utc(day: str, clock: str) -> float:
    return build.eastern_to_utc(day, clock)


T_THU = iso_utc(*THURSDAY)                 # week lock
T_SUN = iso_utc(*SUNDAY)
T_FILE = T_THU - 6 * 3600                  # PT file imported Thursday afternoon
T_ODDS_EARLY = T_THU - 3 * 3600            # an Odds API update before the lock
T_ODDS_LATE = T_THU + 36 * 3600            # one on Saturday: after the lock, before Sunday kickoff


def write_fixtures(folder: Path) -> build.Inputs:
    games_csv = folder / "games.csv"
    with open(games_csv, "w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow(["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team",
                      "away_score", "home_team", "home_score", "location", "spread_line",
                      "total_line", "home_moneyline", "away_moneyline"])
        for gid, season, week, (day, clock), away, home, ap, hp, spread, total, mlh, mla in SCHEDULE:
            na = lambda v: "NA" if v is None else v  # noqa: E731
            out.writerow([gid, season, "REG", week, day, clock, away, ap, home, hp, "Home",
                          na(spread), na(total), na(mlh), na(mla)])
        # A playoff row that must be ignored.
        out.writerow(["2030_19_KC_BUF", 2030, "DIV", 19, "2031-01-18", "20:15", "KC", 1, "BUF", 2,
                      "Home", 1, 40, -110, -110])

    pt_csv = folder / "nflpredictions week 1.csv"
    with open(pt_csv, "w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow(["lineopen", "line", "road", "home", "linesag", "linemass", "lineavg"])
        for road, home, opening, line, sag, mass, avg in PT_ROWS:
            out.writerow([opening, line, road, home, sag, mass, avg])

    stored_games = [asdict(f) for f in predictions.read_csv(pt_csv)]
    for g in stored_games:
        g["opinions"] = list(g["opinions"])
    store = {
        "forecasts": {"1": {"source": str(pt_csv), "imported": T_FILE, "games": stored_games}},
        "odds_weeks": {"1": {"history": [
            {"at": T_ODDS_EARLY, "lines": {"bal@kc": 3.5, "atl@pit": 2.0, "ne@mia": 6.0}},
            {"at": T_ODDS_LATE, "lines": {"atl@pit": -1.0, "ne@mia": 8.0}},
        ]}},
        "spreads": {"1": {"6": {"match": "los angeles rams@los angeles chargers",
                                "favourite": "home", "points": 1.5}}},
        "picks": {"1": {"source": "picks.xls", "imported": T_SUN + 7 * 86400, "games": [
            {"away": "baltimore", "home": "KANSAS CITY", "note": "(kc by 7)"},
            {"away": "atlanta", "home": "PITTSBURGH", "note": ""},
            {"away": "new england", "home": "MIAMI", "note": "(mia by 8)"},
            {"away": "san francisco", "home": "SEATTLE", "note": "(sf by 7)"},
            {"away": "dallas", "home": "NEW YORK GIANTS", "note": "|"},
            {"away": "los angeles rams", "home": "LOS ANGELES CHARGERS", "note": ""},
        ]}},
    }
    extract = folder / "store_extract.json"
    extract.write_text(json.dumps({"database": "synthetic", "database_sha256": "0" * 64, "store": store},
                                  sort_keys=True), encoding="utf-8")
    meta = {"url": "synthetic", "retrieved_at": None, "retrieved_at_basis": "test fixture"}
    return build.Inputs(games_csv, meta, extract, None, [pt_csv])


def rows(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def records(conn: sqlite3.Connection) -> dict[str, dict]:
    return {r["record_id"]: r for r in asof.all_records(conn)}


class LabCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix="lab-history-"))
        cls.inputs = write_fixtures(cls.folder)
        cls.db = cls.folder / "history.db"
        cls.result = build.build(cls.inputs, cls.db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def open_copy(self) -> sqlite3.Connection:
        """A private, writable copy of the built dataset for one test to tamper with."""
        copy = self.folder / f"copy-{self.id().rsplit('.', 1)[-1]}.db"
        shutil.copyfile(self.db, copy)
        return sqlite3.connect(copy)

    def record(self, conn, gid: str, kind: str) -> dict:
        return records(conn)[f"{gid}|{kind}"]


class TestLeakage(LabCase):
    """Nothing recorded after a cutoff can influence that cutoff's record."""

    def test_records_are_built_without_reading_outcomes(self):
        conn = sqlite3.connect(f"{self.db.resolve().as_uri()}?mode=ro", uri=True)

        def deny_outcomes(action, table, *_):
            if action == sqlite3.SQLITE_READ and table == "outcomes":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(deny_outcomes)
        with self.assertRaises(sqlite3.DatabaseError):      # the guard is live
            conn.execute("SELECT home_score FROM outcomes").fetchall()
        built = asof.all_records(conn)                      # and building never trips it
        self.assertEqual(len(built), 2 * len(SCHEDULE))
        conn.close()

    def test_record_table_has_no_result_columns(self):
        conn = sqlite3.connect(self.db)
        columns = schema.columns(conn, "prediction_records")
        conn.close()
        for word in ("score", "result", "winner", "margin", "credited", "outcome", "final"):
            self.assertFalse([c for c in columns if word in c], f"record column mentions {word!r}")

    def test_changing_results_changes_no_record(self):
        conn = self.open_copy()
        before = records(conn)
        conn.execute("UPDATE outcomes SET home_score = home_score + 30, home_margin = home_margin + 30")
        self.assertEqual(records(conn), before)
        conn.close()

    def test_odds_after_the_cutoff_change_no_record(self):
        conn = self.open_copy()
        before = records(conn)
        for rec in before.values():
            if rec["cutoff_at"] is None:
                continue
            for market in ("spread", "total", "moneyline"):
                build.insert(conn, "odds_snapshots", {
                    "snapshot_id": f"late:{rec['record_id']}:{market}", "game_id": rec["game_id"],
                    "market": market, "home_value": 99.0, "away_value": 99.0, "timing": "snapshot",
                    "as_of": rec["cutoff_at"] + 1, "available_at": rec["cutoff_at"] + 1,
                    "available_at_basis": "test", "orientation": "as_source",
                    "source_id": "store:odds", "raw": "{}"})
        after = records(conn)
        # The week-lock record of a Sunday game must not see a line added one
        # second after Thursday's kickoff - but the kickoff record legitimately
        # may, since Thursday + 1s is before its own cutoff.
        for rid, rec in before.items():
            if self._sees_lock_plus_one(before, rec):
                # It takes the injected line unless it already held a later one.
                lock = before[f"{rec['game_id']}|week_lock"]["cutoff_at"]
                held = conn.execute("SELECT available_at FROM odds_snapshots WHERE snapshot_id = ?",
                                    (rec["spread_snapshot_id"],)).fetchone()
                newer = held is not None and held[0] is not None and held[0] > lock + 1
                self.assertEqual(after[rid]["spread_home"], rec["spread_home"] if newer else 99.0, rid)
            else:
                self.assertEqual(after[rid], rec, rid)
        conn.close()

    @staticmethod
    def _sees_lock_plus_one(before: dict, rec: dict) -> bool:
        """A kickoff record whose game starts after its week's lock."""
        lock = before[f"{rec['game_id']}|week_lock"]["cutoff_at"]
        return rec["cutoff_kind"] == "kickoff" and lock is not None and rec["cutoff_at"] > lock

    def test_forecasts_after_the_cutoff_change_no_record(self):
        conn = self.open_copy()
        before = records(conn)
        for rec in before.values():
            if rec["cutoff_at"] is None:
                continue
            for model in ("linesag", "linenew"):
                build.insert(conn, "model_forecasts", {
                    "forecast_id": f"late:{rec['record_id']}:{model}", "game_id": rec["game_id"],
                    "model": model, "home_margin": -40.0, "published_at": None,
                    "published_at_basis": "test", "retrieved_at": rec["cutoff_at"] + 1,
                    "retrieved_at_basis": "test", "available_at": rec["cutoff_at"] + 1,
                    "orientation": "as_source", "source_id": f"late:{rec['record_id']}"})
        after = records(conn)
        for rid, rec in before.items():
            if self._sees_lock_plus_one(before, rec):
                self.assertEqual(after[rid]["n_models"], 2, rid)     # the late file, seen in time
            else:
                self.assertEqual(after[rid], rec, rid)
        conn.close()

    def test_random_future_information_never_moves_a_record(self):
        conn = self.open_copy()
        before = records(conn)
        lock = {rid: r["cutoff_at"] for rid, r in before.items()}
        rng = random.Random(2030)
        for n in range(300):
            rid = rng.choice(sorted(lock))
            at = lock[rid]
            if at is None:
                continue
            # anything after the EARLIEST cutoff of this game, so neither of its records may see it
            game = before[rid]["game_id"]
            earliest = min(lock[f"{game}|week_lock"] or at, lock[f"{game}|kickoff"] or at)
            later = max(at, lock[f"{game}|kickoff"] or at) + rng.uniform(1, 30 * 86400)
            if rng.random() < 0.5:
                build.insert(conn, "odds_snapshots", {
                    "snapshot_id": f"noise{n}", "game_id": game,
                    "market": rng.choice(("spread", "total", "moneyline")),
                    "home_value": rng.uniform(-30, 30), "away_value": rng.uniform(-300, 300),
                    "timing": rng.choice(("snapshot", "file_market", "file_opening")),
                    "as_of": later, "available_at": later, "available_at_basis": "test",
                    "orientation": "as_source", "source_id": "noise", "raw": "{}"})
            else:
                build.insert(conn, "model_forecasts", {
                    "forecast_id": f"noise{n}", "game_id": game, "model": f"line{n}",
                    "home_margin": rng.uniform(-30, 30), "published_at": None,
                    "published_at_basis": "test", "retrieved_at": later, "retrieved_at_basis": "test",
                    "available_at": later, "orientation": "as_source", "source_id": f"noise{n % 7}"})
            self.assertGreater(later, earliest)
        self.assertEqual(records(conn), before)
        conn.close()

    def test_a_snapshot_exactly_at_the_cutoff_counts_and_one_second_later_does_not(self):
        conn = self.open_copy()
        gid = "2030_01_SF_SEA"
        for at, value in ((T_THU, 11.0), (T_THU + 1, 22.0)):
            build.insert(conn, "odds_snapshots", {
                "snapshot_id": f"edge{value}", "game_id": gid, "market": "spread",
                "home_value": value, "away_value": None, "timing": "snapshot", "as_of": at,
                "available_at": at, "available_at_basis": "test", "orientation": "as_source",
                "source_id": "store:odds", "raw": "{}"})
        self.assertEqual(self.record(conn, gid, "week_lock")["spread_home"], 11.0)
        conn.close()

    def test_week_lock_ignores_a_line_fetched_after_thursday(self):
        conn = sqlite3.connect(self.db)
        lock = self.record(conn, "2030_01_ATL_PIT", "week_lock")
        game = self.record(conn, "2030_01_ATL_PIT", "kickoff")
        conn.close()
        self.assertEqual(lock["cutoff_at"], T_THU)
        self.assertEqual(game["cutoff_at"], T_SUN)
        self.assertEqual(lock["spread_home"], 2.0)       # the update before Thursday's kickoff
        self.assertEqual(game["spread_home"], -1.0)      # Saturday's update, before Sunday's kickoff

    def test_a_stored_record_is_rebuilt_exactly(self):
        count, problems = build.verify(self.db)
        self.assertEqual(count, 2 * len(SCHEDULE))
        self.assertEqual(problems, [])

    def test_the_build_is_deterministic(self):
        again = self.folder / "again.db"
        build.build(self.inputs, again)
        one, two = sqlite3.connect(self.db), sqlite3.connect(again)
        for table in ("games", "outcomes", "odds_snapshots", "model_forecasts", "pool_lines",
                      "prediction_records"):
            self.assertEqual(rows(one, table), rows(two, table), table)
        one.close()
        two.close()


class TestNoFabrication(LabCase):
    """Missing times stay missing, and undated lines never pass as verified."""

    def test_undated_lines_are_quarantined_and_flagged(self):
        conn = sqlite3.connect(self.db)
        rec = self.record(conn, "2030_01_DAL_NYG", "week_lock")
        self.assertEqual(rec["spread_home"], -1.0)              # from the dated PT file
        nfl = self.record(conn, "2030_01_LA_LAC", "week_lock")  # no dated line at all
        self.assertIsNone(nfl["spread_home"])
        self.assertIn("NO_VERIFIED_SPREAD_AT_CUTOFF", json.loads(nfl["flags"]))
        self.assertEqual(nfl["spread_home_unverified"], 1.5)    # the typed spread, undated
        self.assertIn("SPREAD_TIME_UNVERIFIED", json.loads(nfl["flags"]))
        with self.assertRaises(ValueError):
            asof.production_forecast(conn, nfl["record_id"])
        self.assertEqual(asof.production_forecast(conn, nfl["record_id"], allow_unverified=True).market, 1.5)
        conn.close()

    def test_no_line_without_a_time_ever_fills_a_verified_field(self):
        conn = sqlite3.connect(self.db)
        bad = conn.execute(
            "SELECT r.record_id FROM prediction_records r JOIN odds_snapshots o "
            "ON o.snapshot_id IN (r.spread_snapshot_id, r.total_snapshot_id, r.moneyline_snapshot_id, "
            "r.spread_open_snapshot_id) WHERE o.available_at IS NULL OR o.available_at > r.cutoff_at"
        ).fetchall()
        self.assertEqual(bad, [])
        conn.close()

    def test_missing_publication_and_posting_times_stay_empty(self):
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM model_forecasts WHERE published_at IS NOT NULL")
                         .fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM pool_lines WHERE posted_at IS NOT NULL")
                         .fetchone()[0], 0)
        rec = self.record(conn, "2030_01_BAL_KC", "week_lock")
        self.assertIn("MODEL_PUBLICATION_TIME_UNKNOWN", json.loads(rec["flags"]))
        self.assertIn("POOL_LINE_TIME_UNVERIFIED", json.loads(rec["flags"]))
        conn.close()

    def test_a_season_without_kickoff_times_gets_no_cutoff(self):
        conn = self.open_copy()
        conn.execute("UPDATE games SET kickoff_utc = NULL WHERE game_id = '2030_01_NE_MIA'")
        lock = self.record(conn, "2030_01_BAL_KC", "week_lock")   # same week: first kickoff now unknown
        self.assertIsNone(lock["cutoff_at"])
        self.assertIsNone(lock["spread_home"])
        self.assertIn("CUTOFF_UNKNOWN", json.loads(lock["flags"]))
        conn.close()

    def test_a_download_that_does_not_match_its_pin_is_refused(self):
        class Fake:
            def __init__(self, *_a, **_k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b"not the pinned file"

        raw = self.folder / "raw"
        with self.assertRaises(SystemExit):
            build.fetch_nflverse(raw=raw, opener=Fake)
        self.assertFalse((raw / "nflverse_games.csv").exists())


class TestImport(LabCase):
    def test_margins_are_home_positive_and_flipped_rows_turned_round(self):
        conn = sqlite3.connect(self.db)
        sag = conn.execute("SELECT home_margin, orientation FROM model_forecasts "
                           "WHERE game_id = '2030_01_SF_SEA' AND model = 'linesag'").fetchone()
        # The file had SEA as road with SF favoured by 6 (home margin -6); on the
        # schedule SEA is home, so SEA's margin is +6.
        self.assertEqual(sag, (6.0, "flipped"))
        rec = self.record(conn, "2030_01_SF_SEA", "week_lock")
        self.assertEqual(rec["spread_home"], 3.5)
        self.assertIn("SOURCE_HOME_AWAY_FLIPPED", json.loads(rec["flags"]))
        self.assertEqual(self.record(conn, "2030_01_NE_MIA", "week_lock")["spread_home"], 6.0)
        conn.close()

    def test_models_keep_their_names_and_exclude_market_and_summary_columns(self):
        conn = sqlite3.connect(self.db)
        models = {m for (m,) in conn.execute("SELECT DISTINCT model FROM model_forecasts")}
        self.assertEqual(models, {"linesag", "linemass"})
        rec = self.record(conn, "2030_01_BAL_KC", "week_lock")
        self.assertEqual(rec["n_models"], 2)
        forecast = asof.production_forecast(conn, rec["record_id"])
        self.assertEqual(sorted(forecast.opinions), [1.0, 4.0])
        self.assertEqual(forecast.market, 3.5)           # the Odds API update beat the file
        self.assertEqual(forecast.opening, 2.5)          # the file's own lineopen
        conn.close()

    def test_pool_lines_and_their_status(self):
        conn = sqlite3.connect(self.db)
        by_game = {g: self.record(conn, g, "kickoff") for g in
                   ("2030_01_BAL_KC", "2030_01_SF_SEA", "2030_01_ATL_PIT", "2030_01_DAL_NYG")}
        self.assertEqual(by_game["2030_01_BAL_KC"]["pool_line_home"], 7.0)
        self.assertEqual(by_game["2030_01_SF_SEA"]["pool_line_home"], -7.0)   # road favourite
        self.assertEqual(by_game["2030_01_ATL_PIT"]["pool_line_status"], "straight_up")
        self.assertEqual(by_game["2030_01_DAL_NYG"]["pool_line_status"], "straight_up")
        # 2030 is after the rule's evidence, 2029 has no sheet at all.
        self.assertEqual(by_game["2030_01_BAL_KC"]["rules_verified"], 1)
        self.assertEqual(self.record(conn, "2029_01_BAL_KC", "kickoff")["pool_line_status"], "unknown")
        conn.close()

    def test_store_slates_find_their_own_season(self):
        conn = sqlite3.connect(self.db)
        slates = build.Slates(conn)
        pair = lambda a, b: frozenset((a, b))  # noqa: E731
        both = {pair("bal", "kc")}                       # in 2029 AND 2030 week 1
        self.assertEqual(slates.infer_season(1, both), (None, 1))
        mine = {pair("bal", "kc"), pair("atl", "pit"), pair("ne", "mia"), pair("sf", "sea")}
        self.assertEqual(slates.infer_season(1, mine), (2030, 4))
        sheet = conn.execute("SELECT season FROM pool_sheets").fetchone()[0]
        self.assertEqual(sheet, 2030)
        conn.close()

    def test_playoff_games_are_left_out(self):
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM games WHERE week > 18").fetchone()[0], 0)
        conn.close()


class TestAppDatabaseIsOnlyRead(unittest.TestCase):
    def test_reading_the_store_changes_nothing_and_leaves_secrets_behind(self):
        folder = Path(tempfile.mkdtemp(prefix="lab-store-"))
        try:
            db = folder / "acql.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE docs (kind TEXT, key TEXT, value TEXT, updated REAL)")
            for kind, key, value in (
                ("settings", "web", {"sealed_token": "secret"}),
                ("odds", "key", "api-key"),
                ("odds", "weeks", {"1": {"history": []}}),
                ("forecasts", "1", {"games": []}),
                ("picks", "1", {"source": "x.xls", "imported": 1.0, "games": [
                    {"away": "a", "home": "B", "note": "(b by 7)", "picks": {"Coach": "a"}}]}),
            ):
                conn.execute("INSERT INTO docs VALUES (?, ?, ?, 0)", (kind, key, json.dumps(value)))
            conn.commit()
            conn.close()
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            found = build.read_store(db)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)
            text = json.dumps(found)
            self.assertNotIn("secret", text)
            self.assertNotIn("api-key", text)
            self.assertNotIn("Coach", text)                      # coaches' picks stay behind
            self.assertEqual(found["picks"]["1"]["games"][0]["note"], "(b by 7)")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


@unittest.skipUnless(build.DB_FILE.exists(), "lab/data/history.db not built")
class TestBuiltDataset(unittest.TestCase):
    """The real dataset, when it has been built: reproducible and leak-free."""

    def test_every_record_reproduces(self):
        count, problems = build.verify(build.DB_FILE)
        self.assertGreater(count, 0)
        self.assertEqual(problems, [])

    def test_nothing_selected_postdates_its_cutoff(self):
        conn = sqlite3.connect(f"{build.DB_FILE.resolve().as_uri()}?mode=ro", uri=True)
        late_odds = conn.execute(
            "SELECT COUNT(*) FROM prediction_records r JOIN odds_snapshots o ON o.snapshot_id IN "
            "(r.spread_snapshot_id, r.total_snapshot_id, r.moneyline_snapshot_id, r.spread_open_snapshot_id) "
            "WHERE o.available_at IS NULL OR o.available_at > r.cutoff_at").fetchone()[0]
        late_models = 0
        for record_id, cutoff, ids in conn.execute(
                "SELECT record_id, cutoff_at, forecast_ids FROM prediction_records WHERE n_models > 0"):
            for fid in json.loads(ids):
                at = conn.execute("SELECT available_at FROM model_forecasts WHERE forecast_id = ?",
                                  (fid,)).fetchone()[0]
                late_models += at is None or at > cutoff
        conn.close()
        self.assertEqual((late_odds, late_models), (0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
