"""The Model Lab's "Outside forecasts" view: the forecast log (model/forecastlog.py) on screen.

A leaderboard on eligible forecasts only, a chart of it and of each week, a
week's games with every model's number side by side, the full history with
each forecast's times and standing, and CSV in and out. Every number here
was in the log before its cutoff, or it is shown but not scored.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ...model import forecastlog as log
from ..charts import BarChart, LineChart
from ..widgets import Card, TableModel, make_table

LEADER_TITLE = "Leaderboard - eligible forecasts only, on finished games"
LEADER_HEADERS = ["Model", "Games", "Brier", "Log loss", "Winners", "Margin miss", "Duplicates left out"]
WEEKLY_TITLE = "Week by week - Brier score (lower is better)"
MATCHUP_TITLE = "The week's games - every model's chance for the home side"
HISTORY_TITLE = "Every forecast in the log, newest first"
HISTORY_HEADERS = ["#", "Week", "Game", "Model", "Home win", "Published", "Taken", "Standing", "Note"]
SOURCES_TITLE = "Where the forecasts came from - and how many can be scored"
SOURCES_HEADERS = ["Model", "Provider", "Eligible", "Late", "Postgame", "No publication time", "Other"]
HISTORY_ROWS = 400
TONE = {"eligible": "good", "late": "warning", "postgame": "bad", "missing_timestamp": "warning"}


def _pct(p) -> str:
    return "" if p is None else f"{p:.0%}"


def _num(x, places: int = 3) -> str:
    return "" if x is None else f"{x:.{places}f}"


def _short(stamp: str | None) -> str:
    return (stamp or "")[:16].replace("T", " ")


class ForecastLogView(QWidget):
    """Built once by the Model Lab page; `refresh(year)` reads the log again."""

    def __init__(self, page) -> None:
        super().__init__()
        self.page = page
        self.year: int | None = None
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(page.layout_.spacing())

        actions = Card("The forecast log")
        self.lead = QLabel("")
        self.lead.setWordWrap(True)
        actions.add(self.lead)
        row = QHBoxLayout()
        for label, slot in (("Bring in what's on file", self._bring_in), ("Import games CSV...", self._import_games),
                            ("Import forecasts CSV...", self._import),
                            ("Export leaderboard...", self._export_board), ("Export history...", self._export_history),
                            ("Blank CSV for a week...", self._export_template)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        actions.body().addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        actions.add(self.status)
        box.addWidget(actions)

        self.leader_card, self.leader_box, self.leader_note = self._card(LEADER_TITLE)
        self.common = QCheckBox("Only the games every model priced")
        self.common.toggled.connect(lambda _on: self.refresh(self.year))
        self.leader_card.body().insertWidget(1, self.common)
        self.leader_chart = BarChart(page.palette, height=2.4)
        self.leader_card.add(self.leader_chart)
        box.addWidget(self.leader_card)

        self.weekly_card, _, self.weekly_note = self._card(WEEKLY_TITLE)
        self.weekly_chart = LineChart(page.palette, height=2.6)
        self.weekly_card.body().insertWidget(1, self.weekly_chart)
        box.addWidget(self.weekly_card)

        self.match_card, self.match_box, self.match_note = self._card(MATCHUP_TITLE)
        self.week_pick = QComboBox()
        self.week_pick.currentIndexChanged.connect(lambda _i: self._update_matchups())
        self.match_card.body().insertWidget(1, self.week_pick)
        box.addWidget(self.match_card)

        self.sources_card, self.sources_box, _ = self._card(SOURCES_TITLE)
        box.addWidget(self.sources_card)

        self.history_card, self.history_box, self.history_note = self._card(HISTORY_TITLE)
        self.model_pick = QComboBox()
        self.model_pick.currentIndexChanged.connect(lambda _i: self._update_history())
        self.history_card.body().insertWidget(1, self.model_pick)
        box.addWidget(self.history_card)

    # ---- layout helpers ------------------------------------------------------------------
    @staticmethod
    def _card(heading: str):
        card = Card(heading)
        inner = QVBoxLayout()
        card.body().addLayout(inner)
        note = QLabel("")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        card.add(note)
        return card, inner, note

    def _table(self, box, headers, rows, **options) -> None:
        self.page.clear_layout(box)
        if rows:
            stretch = options.pop("stretch", 0)
            view, _ = make_table(TableModel(headers, rows, palette=self.page.palette, **options),
                                 stretch_column=stretch, row_height=28)
            box.addWidget(view)

    def restyle(self) -> None:
        self.leader_chart.set_palette(self.page.palette)
        self.weekly_chart.set_palette(self.page.palette)

    # ---- reading the log -------------------------------------------------------------------
    def refresh(self, year: int | None) -> None:
        self.year = year
        try:
            conn = log.connect()
        except Exception as exc:  # noqa: BLE001 - shown, not raised: the rest of the lab still works
            self.lead.setText(f"The forecast log couldn't be opened: {exc}")
            return
        try:
            self._update_lead(conn)
            self._update_leaderboard(conn)
            self._update_weekly(conn)
            self._fill_weeks(conn)
            self._update_sources(conn)
            self._fill_models(conn)
        finally:
            conn.close()
        self._update_matchups()
        self._update_history()

    def _update_lead(self, conn) -> None:
        total = conn.execute("SELECT COUNT(*) FROM lab_predictions").fetchone()[0]
        eligible = conn.execute("SELECT COUNT(*) FROM lab_predictions WHERE eligibility_status = 'eligible'"
                                ).fetchone()[0]
        self.lead.setText(
            f"{total} forecasts in the log, {eligible} of them eligible to be scored: published and taken at "
            f"least {log.CUTOFF_MINUTES} minutes before their own kickoff. Forecasts are only ever added; one "
            "without a provable time is kept and shown, never scored.")
        last = log.imports(conn, 1)
        if last:
            r = last[0]
            self.status.setText(f"Last CSV: {r['filename']} at {_short(r['imported_at_utc'])} UTC - "
                                f"{r['rows_imported']} of {r['rows_seen']} rows in, {r['rows_rejected']} turned away.")

    def _results(self, conn) -> list[dict]:
        return log.evaluate_models(conn, season=self.year, common_only=self.common.isChecked())

    def _update_leaderboard(self, conn) -> None:
        board = self._results(conn)
        rows, tones = [], {}
        for n, r in enumerate(board):
            rows.append([r["model_name"], r["games"], _num(r["brier_score"]), _num(r["log_loss"]),
                         f"{_pct(r['winner_accuracy'])} of {r['winner_predictions_scored']}",
                         _num(r["margin_mae"], 1), r["duplicate_game_records_excluded"] or ""])
            if n == 0:
                tones[(0, 0)] = "lead"
        self._table(self.leader_box, LEADER_HEADERS, rows, numeric_columns={1, 2, 3, 6}, tones=tones)
        self.leader_chart.plot([r["model_name"] for r in board], [r["brier_score"] for r in board],
                               xlabel="Brier score (lower is better)", value_format="{:.3f}")
        self.leader_note.setText(
            "Nothing eligible on a finished game yet. 'Bring in what's on file' copies the ledger and fetched "
            "lines across; a forecast counts only if its time shows it was in before the cutoff."
            if not board else
            "Ties are left out of the win-chance scores. Winners are counted only where a forecast named one."
            + ("" if len(board) > 1 else " Only one model has eligible forecasts so far - nothing to compare yet."))

    def _update_weekly(self, conn) -> None:
        by = log.weekly_brier(conn, self.year) if self.year is not None else {}
        weeks = sorted({w for v in by.values() for w in v})
        self.weekly_chart.plot(weeks, [(name, [v.get(w) for w in weeks]) for name, v in sorted(by.items())],
                               ylabel="Brier")
        self.weekly_note.setText("" if weeks else "Appears once a week with eligible forecasts has finished.")

    def _fill_weeks(self, conn) -> None:
        wanted = self.week_pick.currentData()
        self.week_pick.blockSignals(True)
        self.week_pick.clear()
        for week in (log.weeks(conn, self.year) if self.year is not None else []):
            self.week_pick.addItem(f"Week {week}", week)
        index = self.week_pick.findData(wanted)
        self.week_pick.setCurrentIndex(index if index >= 0 else self.week_pick.count() - 1)
        self.week_pick.blockSignals(False)

    def _fill_models(self, conn) -> None:
        wanted = self.model_pick.currentData()
        self.model_pick.blockSignals(True)
        self.model_pick.clear()
        self.model_pick.addItem("Every model", None)
        for m in log.models(conn):
            self.model_pick.addItem(m["display_name"], m["model_id"])
        index = self.model_pick.findData(wanted)
        self.model_pick.setCurrentIndex(max(index, 0))
        self.model_pick.blockSignals(False)

    def _update_matchups(self) -> None:
        week = self.week_pick.currentData()
        if self.year is None or week is None:
            self._table(self.match_box, [], [])
            self.match_note.setText("No games in the log yet.")
            return
        conn = log.connect()
        try:
            games, found = log.matchups(conn, self.year, week)
        finally:
            conn.close()
        names = sorted({(row["model_id"], row["display_name"]) for row in found.values()}, key=lambda x: x[1])
        headers = ["Game", "Kickoff (UTC)", "Final"] + [name for _, name in names]
        rows, tones, tips = [], {}, {}
        for r, g in enumerate(games):
            final = "" if g["home_score"] is None else f"{g['away_score']}-{g['home_score']}"
            line = [f"{g['away_team']} @ {g['home_team']}", _short(g["kickoff_utc"]), final]
            for c, (model_id, _) in enumerate(names, start=3):
                p = found.get((g["game_id"], model_id))
                if p is None:
                    line.append("")
                    continue
                line.append(_pct(p["home_win_probability"]))
                status = p["eligibility_status"]
                tones[(r, c)] = TONE.get(status, "muted")
                tips[(r, c)] = f"{status}: published {_short(p['source_published_at_utc'])}, " \
                               f"taken {_short(p['retrieved_at_utc'])} UTC. {p['data_quality_note']}"
            rows.append(line)
        self._table(self.match_box, headers, rows, tones=tones, tooltips=tips,
                    numeric_columns=set(range(3, len(headers))))
        self.match_note.setText("Green: eligible. Amber: late, or no publication time. Red: in after kickoff - "
                                "kept, never scored. Hover a number for its times.")

    def _update_sources(self, conn) -> None:
        rows = []
        for m in log.models(conn):
            counts = dict(conn.execute("SELECT eligibility_status, COUNT(*) FROM lab_predictions WHERE model_id = ? "
                                       "GROUP BY eligibility_status", (m["model_id"],)).fetchall())
            other = sum(v for k, v in counts.items() if k not in ("eligible", "late", "postgame", "missing_timestamp"))
            rows.append([m["display_name"], m["provider"], counts.get("eligible", 0), counts.get("late", 0),
                         counts.get("postgame", 0), counts.get("missing_timestamp", 0), other])
        self._table(self.sources_box, SOURCES_HEADERS, rows, numeric_columns={2, 3, 4, 5, 6})

    def _update_history(self) -> None:
        conn = log.connect()
        try:
            found = log.history(conn, self.model_pick.currentData(), HISTORY_ROWS)
        finally:
            conn.close()
        rows, tones = [], {}
        for r, p in enumerate(found):
            rows.append([p["prediction_id"], f"{p['season']} wk {p['week']}", f"{p['away_team']} @ {p['home_team']}",
                         p["display_name"], _pct(p["home_win_probability"]), _short(p["source_published_at_utc"]),
                         _short(p["retrieved_at_utc"]), p["eligibility_status"], p["data_quality_note"]])
            tones[(r, 7)] = TONE.get(p["eligibility_status"], "muted")
        self._table(self.history_box, HISTORY_HEADERS, rows, numeric_columns={0, 4}, tones=tones, stretch=8)
        self.history_note.setText(f"The newest {HISTORY_ROWS} shown; export the history for all of them."
                                  if len(found) >= HISTORY_ROWS else "")

    # ---- actions ------------------------------------------------------------------------------
    def _bring_in(self) -> None:
        try:
            conn = log.connect()
            try:
                made = log.bring_in(conn, self.year)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Forecast log", f"Couldn't bring them in: {exc}")
            return
        self.status.setText(f"Brought in {made['ledger']} ledger numbers, {made['lines']} fetched lines and "
                            f"{made['moneylines']} moneylines on {made['games']} games; {made['skipped']} were "
                            "already in the log. Nothing was fetched.")
        self.refresh(self.year)

    def _import_games(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import games and results (nflverse games.csv)", "",
                                              "CSV files (*.csv)")
        if not path:
            return
        try:
            conn = log.connect()
            try:
                done = log.import_games_csv(conn, path)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Import games", str(exc))
            return
        said = (f"{done['rows_imported']} of {done['rows_seen']} games imported, {done['finals']} with a final "
                "score. No forecasts were made from the file.")
        if done["errors"]:
            said += (f"\n\n{done['rows_rejected']} turned away, for example:\n"
                     + "\n".join(f"line {e['line']}: {e['error']}" for e in done["errors"][:8]))
        QMessageBox.information(self, "Import games", said)
        self.refresh(self.year)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import forecasts", "", "CSV files (*.csv)")
        if not path:
            return
        try:
            conn = log.connect()
            try:
                done = log.import_predictions_csv(conn, path)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Import forecasts", str(exc))
            return
        said = f"{done['rows_imported']} of {done['rows_seen']} rows imported."
        if done["errors"]:
            said += "\n\nTurned away:\n" + "\n".join(f"line {e['line']}: {e['error']}" for e in done["errors"][:12])
        QMessageBox.information(self, "Import forecasts", said)
        self.refresh(self.year)

    def _save_as(self, title: str, name: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, str(Path.home() / name), "CSV files (*.csv)")
        return path

    def _export_board(self) -> None:
        path = self._save_as("Export leaderboard", f"model-lab-leaderboard-{self.year}.csv")
        if path:
            conn = log.connect()
            try:
                log.export_evaluation_csv(self._results(conn), path)
            finally:
                conn.close()
            self.status.setText(f"Leaderboard saved to {path}.")

    def _export_history(self) -> None:
        path = self._save_as("Export history", "model-lab-forecasts.csv")
        if path:
            conn = log.connect()
            try:
                n = log.export_history_csv(conn, path, self.model_pick.currentData())
            finally:
                conn.close()
            self.status.setText(f"{n} forecasts saved to {path}.")

    def _export_template(self) -> None:
        week = self.week_pick.currentData()
        if self.year is None or week is None:
            QMessageBox.information(self, "Blank CSV", "Bring in what's on file first, so the log has the games.")
            return
        path = self._save_as("Blank CSV for a week", f"forecasts-{self.year}-week{week}.csv")
        if path:
            conn = log.connect()
            try:
                n = log.export_template_csv(conn, path, self.year, week)
            finally:
                conn.close()
            self.status.setText(f"A blank CSV with week {week}'s {n} game ids saved to {path}.")
