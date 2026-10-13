#!/usr/bin/env python3
"""Tests for the ACQL Dashboard's data layer.

Run from the project root:

    python tests/run_tests.py

These exercise the parsers, the merge rules and the write-back guards against
the real spreadsheets in data/. No Qt is imported, so they run headless.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import awards
from acql.config import Settings
from acql.models import Player, Season
from acql.names import AliasTable, normalize
from acql.repository import load_season
from acql.sources import classify, discover
from acql.writeback import WorkbookEditor, WriteBackError


def find_sources() -> tuple[Path | None, Path | None]:
    """Locate a stats export and a workbook among the watched folders."""
    stats = workbook = None
    for source in discover(Settings().search_paths()):
        if source.kind == "stats" and stats is None:
            stats = source.path
        elif source.kind == "workbook" and workbook is None:
            workbook = source.path
    return stats, workbook


STATS_PATH, WORKBOOK_PATH = find_sources()
needs_stats = unittest.skipIf(STATS_PATH is None, "no stats.xls available")
needs_workbook = unittest.skipIf(WORKBOOK_PATH is None, "no workbook available")


class TestNames(unittest.TestCase):
    def test_normalize_collapses_incidental_differences(self):
        self.assertEqual(normalize("SaleeNmd "), normalize("saleenmd"))
        self.assertEqual(normalize("MayeDay! MayeDay!"), "mayeday mayeday")
        self.assertEqual(normalize("  Bob   h "), "bob h")
        self.assertEqual(normalize(None), "")

    def test_distinct_players_stay_distinct(self):
        self.assertNotEqual(normalize("Phelpy"), normalize("Phelps Phamily"))

    def test_aliases_map_to_a_canonical_key(self):
        table = AliasTable({"Zach N": "Zachary Nelson"})
        self.assertEqual(table.key("zach n"), normalize("Zachary Nelson"))
        # An unmapped name is returned normalized, not dropped.
        self.assertEqual(table.key("Phelpy"), "phelpy")

    def test_alias_does_not_chain_indefinitely(self):
        table = AliasTable({"a": "b", "b": "c"})
        self.assertEqual(table.key("a"), "b")


class TestDiscovery(unittest.TestCase):
    @needs_stats
    def test_stats_file_declares_its_own_week(self):
        source = classify(STATS_PATH)
        self.assertIsNotNone(source)
        self.assertEqual(source.kind, "stats")
        self.assertIsInstance(source.week, int)
        self.assertEqual(source.season, "ACQL 2026")

    @needs_workbook
    def test_workbook_is_identified(self):
        source = classify(WORKBOOK_PATH)
        self.assertEqual(source.kind, "workbook")

    def test_unrelated_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            junk = Path(tmp) / "notes.txt"
            junk.write_text("not a spreadsheet", encoding="utf-8")
            self.assertIsNone(classify(junk))

    @needs_stats
    def test_identical_content_is_collapsed(self):
        """A re-download under a new name must not be counted twice."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            shutil.copy2(STATS_PATH, folder / "stats.xls")
            shutil.copy2(STATS_PATH, folder / "stats (1).xls")
            found = discover([folder])
            self.assertEqual(len(found), 1, "byte-identical copies should collapse")


class TestSeasonLoad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.season = load_season(Settings())

    def test_players_are_loaded(self):
        self.assertGreater(len(self.season.players), 20)

    def test_the_marker_row_is_not_a_player(self):
        """stats.xls trails a 'Big Losers week N' row in the coach column."""
        for name in (p.display.lower() for p in self.season.players.values()):
            self.assertNotIn("big loser", name)

    def test_standings_are_ordered_by_position(self):
        order = self.season.ordered_players()
        positions = [p.pos for p in order if p.pos]
        self.assertEqual(positions, sorted(positions))

    def test_wins_include_big_loser_points(self):
        """W* covers regular + big-loser wins, so W + L is the full slate."""
        for p in self.season.players.values():
            if p.wins and p.losses:
                total = self.season.max_regular_points + self.season.max_big_loser_points
                self.assertEqual(p.wins + p.losses, total, p.display)

    def test_provisional_weeks_are_excluded_from_averages(self):
        for week in self.season.provisional_weeks:
            self.assertGreater(week, self.season.current_week)
            for p in self.season.players.values():
                self.assertNotIn(week, p.weekly_wins)

    def test_conflicts_are_reported_not_swallowed(self):
        for c in self.season.conflicts:
            self.assertNotEqual(c.authoritative, c.other)
            self.assertIn(c.player, {p.display for p in self.season.players.values()})

    def test_buy_in_comes_from_the_workbook(self):
        self.assertGreater(self.season.buy_in, 0)

    def test_weeks_carry_slates_and_lines(self):
        played = self.season.played_weeks()
        self.assertTrue(played)
        week = self.season.weeks[played[0]]
        self.assertTrue(week.games)
        self.assertTrue(week.lines)

    def test_correct_pick_counts_are_within_the_field(self):
        for week in self.season.weeks.values():
            for game in week.games:
                self.assertLessEqual(week.correct_count(game.index), len(week.lines))

    def test_big_loser_slots_round_trip(self):
        """The raw slots keep their position; the readable view drops markers."""
        for week in self.season.weeks.values():
            for line in week.lines.values():
                self.assertEqual(len(line.big_loser_raw), 3)
                markers = sum(1 for v in line.big_loser_raw if v == "1")
                if markers:
                    self.assertEqual(markers, line.big_loser_wins, line.player)
                for pick in line.big_loser_picks:
                    self.assertIn(pick, line.big_loser_raw)

    def test_suicide_markers_are_not_treated_as_picks(self):
        for p in self.season.players.values():
            for pick in p.suicide_picks.values():
                self.assertNotIn(pick.casefold(), {"dead", "out", "eliminated"})

    def test_eliminated_players_are_not_alive(self):
        for p in self.season.players.values():
            if p.suicide_out_week:
                self.assertFalse(p.suicide_alive, p.display)


class TestDerivedStats(unittest.TestCase):
    def setUp(self):
        self.player = Player(key="x", display="X")
        self.player.weekly_wins = {1: 10, 2: 14, 3: 6}

    def test_season_aggregates(self):
        self.assertEqual(self.player.season_wins, 30)
        self.assertEqual(self.player.best_week, 14)
        self.assertEqual(self.player.worst_week, 6)
        self.assertAlmostEqual(self.player.average_wins, 10.0)

    def test_trend_uses_the_most_recent_weeks(self):
        self.assertAlmostEqual(self.player.trend(2), 10.0)   # weeks 2 and 3
        self.assertAlmostEqual(self.player.trend(3), 10.0)

    def test_rank_movement_is_positive_when_climbing(self):
        self.player.prev_pos, self.player.pos = 10, 4
        self.assertEqual(self.player.rank_movement, 6)
        self.player.prev_pos, self.player.pos = 2, 5
        self.assertEqual(self.player.rank_movement, -3)

    def test_empty_player_does_not_divide_by_zero(self):
        blank = Player(key="y", display="Y")
        self.assertEqual(blank.average_wins, 0.0)
        self.assertEqual(blank.consistency, 0.0)
        self.assertEqual(blank.trend(), 0.0)


class TestAwards(unittest.TestCase):
    def test_awards_never_raise_on_an_empty_season(self):
        self.assertEqual(awards.compute(Season()), [])

    def test_awards_have_real_winners(self):
        season = load_season(Settings())
        names = {p.display for p in season.players.values()}
        for award in awards.compute(season):
            self.assertIn(award.winner, names, award.title)
            self.assertTrue(award.value)


@needs_workbook
class TestWriteBack(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.book = self.tmp / WORKBOOK_PATH.name
        shutil.copy2(WORKBOOK_PATH, self.book)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def census(self) -> dict:
        import openpyxl
        from openpyxl.worksheet.formula import ArrayFormula

        wb = openpyxl.load_workbook(self.book, data_only=False)
        try:
            return {
                "formulas": sum(
                    1 for ws in wb.worksheets for row in ws.iter_rows() for c in row
                    if isinstance(c.value, str) and c.value.startswith("=")
                ),
                "arrays": sum(
                    1 for ws in wb.worksheets for row in ws.iter_rows() for c in row
                    if isinstance(c.value, ArrayFormula)
                ),
                "tables": sum(len(ws.tables) for ws in wb.worksheets),
                "cf": sum(len(ws.conditional_formatting._cf_rules) for ws in wb.worksheets),
                "validation": sum(len(ws.data_validations.dataValidation) for ws in wb.worksheets),
                "merged": sum(len(ws.merged_cells.ranges) for ws in wb.worksheets),
            }
        finally:
            wb.close()

    def test_writing_results_preserves_every_formula(self):
        before = self.census()
        editor = WorkbookEditor(self.book)
        editor.set_result(1, 1, "Seattle")
        editor.set_result(1, 2, "San Francisco")
        editor.set_matchup(1, 3, "Cincinnati", "Tampa Bay")
        result = editor.apply(backup=False)
        self.assertTrue(result.ok, [r for _, r in result.refused])
        self.assertEqual(before, self.census())

    def test_values_land_where_they_were_addressed(self):
        import openpyxl

        editor = WorkbookEditor(self.book)
        editor.set_result(1, 4, "Detroit")
        editor.apply(backup=False)
        wb = openpyxl.load_workbook(self.book, data_only=False)
        try:
            # Game 4 sits in column I on row 6 of the week sheet.
            self.assertEqual(wb["Week 1"]["I6"].value, "Detroit")
        finally:
            wb.close()

    def test_a_formula_cell_is_refused(self):
        editor = WorkbookEditor(self.book)
        # Dashboard!B7 is a SORTBY formula driving the whole leaderboard.
        editor._queue("Dashboard", 7, 2, "overwritten", "test")
        result = editor.apply(backup=False)
        self.assertFalse(result.ok)
        self.assertEqual(result.applied, [])
        self.assertIn("formula", result.refused[0][1])

    def test_a_refused_edit_abandons_the_whole_change_set(self):
        import openpyxl

        editor = WorkbookEditor(self.book)
        editor.set_result(1, 5, "Tennessee")            # valid
        editor._queue("Dashboard", 7, 2, "nope", "test")  # invalid
        result = editor.apply(backup=False)
        self.assertFalse(result.ok)
        wb = openpyxl.load_workbook(self.book, data_only=False)
        try:
            self.assertNotEqual(wb["Week 1"]["J6"].value, "Tennessee")
        finally:
            wb.close()

    def test_unknown_player_is_rejected(self):
        editor = WorkbookEditor(self.book)
        with self.assertRaises(WriteBackError):
            editor.set_pick(1, "Nobody McGee", 1, "Seattle")

    def test_out_of_range_week_and_game_are_rejected(self):
        editor = WorkbookEditor(self.book)
        with self.assertRaises(WriteBackError):
            editor.set_result(99, 1, "Seattle")
        with self.assertRaises(WriteBackError):
            editor.set_result(1, 99, "Seattle")

    def test_dry_run_changes_nothing(self):
        before = self.book.read_bytes()
        editor = WorkbookEditor(self.book)
        editor.set_result(1, 6, "Baltimore")
        result = editor.apply(dry_run=True)
        self.assertTrue(result.applied)
        self.assertEqual(before, self.book.read_bytes())

    def test_a_backup_is_written_before_saving(self):
        editor = WorkbookEditor(self.book)
        editor.set_result(1, 7, "Pittsburgh")
        result = editor.apply(backup=True)
        self.assertIsNotNone(result.backup)
        self.assertTrue(result.backup.is_file())
        result.backup.unlink(missing_ok=True)

    def test_big_loser_win_markers_survive_editing_a_neighbour(self):
        """A slot reading 1 marks a win; editing slot 3 must not clear 1 and 2."""
        import openpyxl

        editor = WorkbookEditor(self.book)
        editor.set_big_loser_picks(1, "cuetop", ["1", "1", "Denver"])
        self.assertTrue(editor.apply(backup=False).ok)
        wb = openpyxl.load_workbook(self.book, data_only=False)
        try:
            ws = wb["Week 1"]
            row = next(
                r for r in range(10, 45)
                if str(ws.cell(r, 5).value).strip() == "cuetop"
            )
            self.assertEqual(
                [ws.cell(row, c).value for c in (22, 23, 24)], [1, 1, "Denver"]
            )
        finally:
            wb.close()

    def test_a_numeric_entry_is_stored_as_a_number(self):
        """Excel counts 1 but not "1", so a win marker must not become text."""
        import openpyxl

        editor = WorkbookEditor(self.book)
        editor.set_big_loser_picks(1, "Phelpy", ["1", "Arizona", "Miami"])
        editor.apply(backup=False)
        wb = openpyxl.load_workbook(self.book, data_only=False)
        try:
            ws = wb["Week 1"]
            row = next(
                r for r in range(10, 45)
                if str(ws.cell(r, 5).value).strip() == "Phelpy"
            )
            self.assertIsInstance(ws.cell(row, 22).value, int)
            self.assertEqual(ws.cell(row, 22).value, 1)
        finally:
            wb.close()

    def test_picks_and_suicide_write_to_the_right_columns(self):
        import openpyxl

        editor = WorkbookEditor(self.book)
        editor.set_pick(1, "Phelpy", 2, "Los Angeles Rams")
        editor.set_suicide_pick(1, "Phelpy", "Buffalo")
        editor.set_game_count(1, 15)
        self.assertTrue(editor.apply(backup=False).ok)
        wb = openpyxl.load_workbook(self.book, data_only=False)
        try:
            ws = wb["Week 1"]
            row = next(
                r for r in range(10, 45)
                if str(ws.cell(r, 5).value).strip() == "Phelpy"
            )
            self.assertEqual(ws.cell(row, 7).value, "Los Angeles Rams")   # game 2 -> G
            self.assertEqual(ws.cell(row, 25).value, "Buffalo")           # suicide -> Y
            self.assertEqual(wb["Season"]["B3"].value, 15)
        finally:
            wb.close()

    def test_row_lookups_are_cached_within_a_session(self):
        editor = WorkbookEditor(self.book)
        editor.set_pick(1, "Phelpy", 1, "Seattle")
        self.assertTrue(editor._row_cache)
        editor.set_pick(1, "DPSOG", 1, "Seattle")
        # A second player must not have reopened the workbook.
        self.assertEqual(len(editor._row_cache), 1)

    def test_repeated_edits_to_one_cell_collapse(self):
        editor = WorkbookEditor(self.book)
        editor.set_result(1, 8, "Carolina")
        editor.set_result(1, 8, "Chicago")
        self.assertEqual(len(editor), 1)
        self.assertEqual(editor.edits[0].value, "Chicago")


@needs_workbook
class TestEditorState(unittest.TestCase):
    """The editor widget's change tracking, driven headlessly."""

    @classmethod
    def setUpClass(cls):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as exc:  # pragma: no cover - Qt absent
            raise unittest.SkipTest(f"PySide6 unavailable: {exc}")
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self):
        from acql.ui.editor import WeekEditor
        from acql.ui.theme import DARK

        editor = WeekEditor(DARK)
        editor.set_season(load_season(Settings()))
        return editor

    def test_a_freshly_loaded_week_has_no_pending_changes(self):
        editor = self._editor()
        self.assertEqual(editor._collect(), [])

    def test_edits_survive_switching_players_and_back(self):
        editor = self._editor()
        first = editor.player_picker.itemText(0)
        second = editor.player_picker.itemText(1)

        editor.player_picker.setCurrentIndex(0)
        editor.suicide_field.setText("Buffalo")
        self.assertEqual(len(editor._collect()), 1)

        editor.player_picker.setCurrentIndex(1)
        self.assertIn(first, editor._pending_players)
        editor._loser_fields[2].setText("Denver")
        changes = editor._collect()
        self.assertEqual(len(changes), 2)
        self.assertEqual({c[2] for c in changes}, {first, second})

        # Returning shows the held edit rather than the workbook value.
        editor.player_picker.setCurrentIndex(0)
        self.assertEqual(editor.suicide_field.text(), "Buffalo")
        self.assertEqual(len(editor._collect()), 2)

    def test_discarding_clears_every_held_edit(self):
        editor = self._editor()
        editor.player_picker.setCurrentIndex(0)
        editor.suicide_field.setText("Buffalo")
        editor.player_picker.setCurrentIndex(1)
        editor._loser_fields[0].setText("Denver")
        self.assertTrue(editor._collect())
        editor.load_week()
        self.assertEqual(editor._collect(), [])
        self.assertEqual(editor._pending_players, {})

    def test_selecting_the_stored_pick_is_not_a_change(self):
        """Picks stored shouted ("CINCINNATI") must not look edited."""
        editor = self._editor()
        for index in range(min(6, editor.player_picker.count())):
            editor.player_picker.setCurrentIndex(index)
            self.assertEqual(
                [c for c in editor._collect() if c[0] == "pick"], [],
                editor.player_picker.currentText(),
            )

    def test_a_large_change_set_previews_without_flooding_the_dialog(self):
        from acql.ui.editor import PREVIEW_LIMIT, _describe

        editor = self._editor()
        for index in range(min(6, editor.player_picker.count())):
            editor.player_picker.setCurrentIndex(index)
            for row in range(16):
                combo = editor._pick_fields[row]
                if combo.count() > 1:
                    combo.setCurrentIndex(1)
        workbook_editor, changes = editor._build_editor()
        self.assertGreater(len(changes), PREVIEW_LIMIT)

        summary, preview, detail = _describe(workbook_editor.apply(dry_run=True))
        self.assertIn("would be written", summary)
        # The shortened view is capped; the full listing stays complete.
        self.assertLessEqual(len(preview.splitlines()), PREVIEW_LIMIT + 1)
        self.assertIn("more cell(s)", preview)
        self.assertGreater(len(detail.splitlines()), PREVIEW_LIMIT)

    def test_retyping_a_team_keeps_a_pending_result(self):
        editor = self._editor()
        editor._winner_fields[0].setCurrentIndex(0)
        before = [c for c in editor._collect() if c[0] == "result"]
        self.assertTrue(before)
        editor._home_fields[0].setText("Seattle Seahawks")
        editor._refresh_winner_options(0)
        after = editor._collect()
        self.assertTrue([c for c in after if c[0] == "result"])
        self.assertTrue([c for c in after if c[0] == "matchup"])


def main() -> int:
    if STATS_PATH is None and WORKBOOK_PATH is None:
        print("No spreadsheets found in data/ - only the pure-logic tests will run.\n")
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


class _ScratchStore(unittest.TestCase):
    """Points the app's database at a temporary file for the test."""

    def setUp(self):
        from acql import store
        self._store = store
        self._dir = Path(tempfile.mkdtemp(prefix="acql-test-"))
        self._previous = store._OVERRIDE
        store.use(self._dir / "test.db")

    def tearDown(self):
        self._store.use(self._previous)
        shutil.rmtree(self._dir, ignore_errors=True)


SCHEDULE_CSV = """season,game_type,week,away_team,home_team,away_score,home_score,away_qb_name,home_qb_name,spread_line
2026,REG,1,CHI,MIN,20,24,Caleb Williams,J.J. McCarthy,3.0
2026,REG,2,CHI,DET,17,30,Case Keenum,Jared Goff,6.5
2026,REG,3,GB,CHI,21,14,Jordan Love,Case Keenum,-3.0
2026,REG,4,CHI,LA,10,27,Case Keenum,Matthew Stafford,7.5
2026,REG,5,BAL,CHI,,,Lamar Jackson,Tyson Bagent,-2.5
"""
INJURY_CSV = """season,week,team,position,full_name,report_status
2026,4,BAL,QB,Lamar Jackson,Out
2026,5,CHI,QB,Caleb Williams,Questionable
"""


class TestQbCheck(_ScratchStore):
    def _fetch(self, url):
        return INJURY_CSV if "injuries" in url else SCHEDULE_CSV

    def test_usual_starter_and_change(self):
        from acql import qbcheck
        rows = qbcheck.schedule_rows(SCHEDULE_CSV, 2026)
        self.assertEqual(qbcheck.usual_starter(rows, "chi", 5), "Case Keenum")
        self.assertEqual(qbcheck.usual_starter(rows, "lar", 5), "Matthew Stafford")   # nflverse LA -> pool lar

    def test_check_flags_and_reads_only_the_kept_copy(self):
        from acql import qbcheck
        empty = qbcheck.check(2026, 5, [(1, "bal", "chi")])          # nothing kept yet, no network
        self.assertFalse(empty.available)
        self.assertTrue(qbcheck.refresh(2026, fetch=self._fetch))
        got = qbcheck.check(2026, 5, [(1, "bal", "chi")])
        game = got.games[1]
        self.assertTrue(game.home.changed)                            # Bagent, not Keenum
        self.assertIn("Caleb Williams: Questionable", game.home.injured)
        self.assertEqual(game.away.last_week, "Out")                  # Lamar Out last week, no report yet
        self.assertTrue(game.worrying)
        self.assertIn("Tyson Bagent expected to start", game.note())

    def test_offline_refresh_is_harmless(self):
        from acql import qbcheck
        import urllib.error

        def down(url):
            raise urllib.error.URLError("offline")
        self.assertFalse(qbcheck.refresh(2026, fetch=down))


class TestArchive(_ScratchStore):
    def test_files_kept_once_and_week_closed_once(self):
        from acql import archive, predictions
        src = self._dir / "nflpredictions week 5.csv"
        src.write_text("line,road,home\n3,Chicago,Minnesota\n")
        games = [predictions.Forecast("Chicago", "Minnesota", market=3.0, opinions=(2.0, 4.0))]
        self.assertTrue(archive.keep_file(2026, 5, src, games))
        self.assertFalse(archive.keep_file(2026, 5, src, games))      # same file again: kept once
        src.write_text("line,road,home\n3.5,Chicago,Minnesota\n")
        self.assertTrue(archive.keep_file(2026, 5, src, games))       # a changed file is a new entry
        rec = archive.record(2026, 5)
        self.assertEqual(len(rec["files"]), 2)
        self.assertTrue(Path(rec["files"][0]["copy"]).exists())
        self.assertTrue(archive.close_week(2026, 5, None, games))
        self.assertFalse(archive.close_week(2026, 5, None, []))       # never rewritten
        self.assertEqual(archive.record(2026, 5)["final"]["lines"][0]["market"], 3.0)
        self.assertIn("2026-05", archive.describe())


class TestLineHabit(unittest.TestCase):
    def _season(self, rows):
        from acql.models import Game, Season, Week
        games = [Game(i + 1, home=h, away=a, line=line, line_favourite=fav)
                 for i, (a, h, line, fav) in enumerate(rows)]
        return Season(weeks={1: Week(number=1, games=games)})

    def test_rule_and_verdict(self):
        from acql import linehabit
        from acql.predictions import Forecast
        self.assertEqual(linehabit.current_rule(6.5), 7.0)
        self.assertEqual(linehabit.current_rule(7.0), 8.0)
        self.assertIsNone(linehabit.current_rule(6.0))
        rows = [("Chicago", "Detroit", 8.0, "Detroit"), ("Miami", "Buffalo", 11.0, "Buffalo"),
                ("Denver", "Kansas City", None, ""), ("Tennessee", "Houston", None, "")]
        forecasts = {1: [Forecast("Chicago", "Detroit", market=7.0), Forecast("Miami", "Buffalo", market=10.5),
                         Forecast("Denver", "Kansas City", market=9.5), Forecast("Tennessee", "Houston", market=3.0)]}
        h = linehabit.measure(self._season(rows), 2026, forecasts, closing={})
        self.assertEqual((h.lined, h.exact), (2, 2))
        self.assertEqual(len(h.skipped_big), 1)                       # KC favoured by 9.5, no line
        self.assertFalse(h.drifting)
        self.assertIn("too few to judge", h.verdict)

    def test_drift_detected(self):
        from acql import linehabit
        from acql.predictions import Forecast
        teams = [("T%02d" % i, "H%02d" % i) for i in range(20)]
        rows = [(a, h, 10.0, h) for a, h in teams]                    # always spread + 2.5
        forecasts = {1: [Forecast(a, h, market=7.5) for a, h in teams]}
        import acql.predictions as P
        original = P.team_code
        P.team_code = lambda name: str(name).lower()
        try:
            h = linehabit.measure(self._season(rows), 2026, forecasts, closing={})
        finally:
            P.team_code = original
        self.assertEqual(h.lined, 20)
        self.assertTrue(h.drifting)
        self.assertIn("shifted", h.verdict)


if __name__ == "__main__":
    raise SystemExit(main())
