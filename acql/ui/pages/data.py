"""Files, conflicts, and the weekly result editor that writes back to Excel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...config import GAMES_PER_WEEK, WEEKS_IN_SEASON
from ...writeback import WorkbookEditor, WriteBackError
from ..widgets import Banner, Card, TableModel, make_table, section
from .base import Page

FILE_HEADERS = ["File", "Type", "Week", "Folder", "Status"]
CONFLICT_HEADERS = ["Player", "Field", "stats.xls (used)", "Workbook", "Note"]
NO_PICK = "— no result —"


class DataPage(Page):
    """Inventory of loaded files plus the write-back editor.

    The editor writes only the workbook's genuine input cells - the week's
    matchups and results. Everything else (wins, ranks, money, the Dashboard
    sheet) is an Excel formula that recalculates from them, so those are left
    to Excel rather than overwritten here.
    """

    title = "Data & Update"
    subtitle = "What is loaded, what disagrees, and how to enter this week's results"
    icon = "\N{CARD INDEX DIVIDERS}"

    refresh_requested = Signal()

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        self.banner = Banner()
        self.layout_.addWidget(self.banner)

        # ---- where files come from ----
        self.folders_card = Card("Watched folders")
        self.folders_label = QLabel("")
        self.folders_label.setObjectName("StatDetail")
        self.folders_label.setWordWrap(True)
        self.folders_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.folders_card.add(self.folders_label)

        buttons = QHBoxLayout()
        self.add_folder_btn = QPushButton("Add a folder…")
        self.add_folder_btn.clicked.connect(self._add_folder)
        self.reload_btn = QPushButton("Rescan now")
        self.reload_btn.setObjectName("Primary")
        self.reload_btn.clicked.connect(self.refresh_requested.emit)
        buttons.addWidget(self.add_folder_btn)
        buttons.addWidget(self.reload_btn)
        buttons.addStretch(1)
        self.folders_card.body().addLayout(buttons)
        self.layout_.addWidget(self.folders_card)

        # ---- files ----
        self.files_card = Card("Files loaded")
        self.files_box = QVBoxLayout()
        self.files_card.body().addLayout(self.files_box)
        self.layout_.addWidget(self.files_card)
        self.files_table = None

        # ---- conflicts ----
        self.conflicts_card = Card("Disagreements between files")
        self.conflicts_note = QLabel(
            "stats.xls is treated as authoritative. Anything listed here is "
            "worth checking in the workbook."
        )
        self.conflicts_note.setObjectName("StatDetail")
        self.conflicts_note.setWordWrap(True)
        self.conflicts_card.add(self.conflicts_note)
        self.conflicts_box = QVBoxLayout()
        self.conflicts_card.body().addLayout(self.conflicts_box)
        self.layout_.addWidget(self.conflicts_card)
        self.conflicts_table = None

        # ---- editor ----
        self.editor_card = Card("Enter this week's results")
        self.editor_note = QLabel(
            "Pick a week, set each game's winner, then save. Only the "
            "matchups and results are written; Excel recalculates every win "
            "total, rank, payout and the Dashboard sheet from them. "
            "A timestamped backup is taken before each save."
        )
        self.editor_note.setObjectName("StatDetail")
        self.editor_note.setWordWrap(True)
        self.editor_card.add(self.editor_note)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Week"))
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(150)
        self.week_picker.currentIndexChanged.connect(lambda _: self._load_week())
        picker_row.addWidget(self.week_picker)
        picker_row.addStretch(1)
        self.editor_status = QLabel("")
        self.editor_status.setObjectName("Muted")
        picker_row.addWidget(self.editor_status)
        self.editor_card.body().addLayout(picker_row)

        self.game_form = QFormLayout()
        self.game_form.setSpacing(7)
        self.game_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.editor_card.body().addLayout(self.game_form)
        self._game_rows: list[tuple[QLabel, QComboBox]] = []

        save_row = QHBoxLayout()
        self.save_btn = QPushButton("Save to workbook")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self._save)
        self.preview_btn = QPushButton("Preview changes")
        self.preview_btn.clicked.connect(self._preview)
        save_row.addWidget(self.save_btn)
        save_row.addWidget(self.preview_btn)
        save_row.addStretch(1)
        self.editor_card.body().addLayout(save_row)

        self.layout_.addWidget(self.editor_card)
        self.layout_.addStretch(1)

    # ---- inventory -------------------------------------------------------
    def refresh(self) -> None:
        s = self.season
        if s is None:
            return
        from ...config import Settings

        self.banner.show_messages(s.warnings)

        settings = Settings.load()
        folders = "\n".join(str(p) for p in settings.search_paths())
        self.folders_label.setText(
            folders + "\n\nDrop each week's stats.xls and the updated "
            "ACQL Dashboard.xlsx into any of these, then press Rescan now."
        )

        rows, tones = [], {}
        for r, src in enumerate(s.sources):
            rows.append([
                src.path.name,
                "Standings export" if src.kind == "stats" else "Dashboard workbook",
                src.week or "–",
                str(src.path.parent),
                src.error or "Loaded",
            ])
            tones[(r, 4)] = "bad" if src.error else "good"
        if not rows:
            rows = [["No files found", "–", "–", "–", "Drop files into data/"]]
        model = TableModel(
            FILE_HEADERS, rows,
            palette=self.palette,
            numeric_columns={2},
            tones=tones,
            bold_columns={0},
        )
        view, _ = make_table(model, stretch_column=3, row_height=27)
        view.setMaximumHeight(190)
        if self.files_table is not None:
            self.files_table.deleteLater()
        self.files_table = view
        self.files_box.addWidget(view)

        if s.conflicts:
            rows = [
                [c.player, c.field, str(c.authoritative), str(c.other), c.note]
                for c in s.conflicts
            ]
            model = TableModel(
                CONFLICT_HEADERS, rows, palette=self.palette, bold_columns={0}
            )
            view, _ = make_table(model, stretch_column=4, row_height=27)
            view.setMaximumHeight(190)
            if self.conflicts_table is not None:
                self.conflicts_table.deleteLater()
            self.conflicts_table = view
            self.conflicts_box.addWidget(view)
            self.conflicts_card.show()
        else:
            self.conflicts_card.hide()

        self._populate_weeks()

    def _add_folder(self) -> None:
        from ...config import Settings

        folder = QFileDialog.getExistingDirectory(self, "Choose a folder to watch")
        if not folder:
            return
        settings = Settings.load()
        if folder not in settings.data_dirs:
            settings.data_dirs.append(folder)
            settings.save()
        self.refresh_requested.emit()

    # ---- editor ----------------------------------------------------------
    def _populate_weeks(self) -> None:
        s = self.season
        if s is None:
            return
        weeks = sorted(s.weeks) or list(range(1, WEEKS_IN_SEASON + 1))
        current = self.week_picker.currentData()
        self.week_picker.blockSignals(True)
        self.week_picker.clear()
        for w in weeks:
            self.week_picker.addItem(f"Week {w}", w)
        if current in weeks:
            self.week_picker.setCurrentIndex(weeks.index(current))
        elif s.current_week in weeks:
            self.week_picker.setCurrentIndex(weeks.index(s.current_week))
        self.week_picker.blockSignals(False)
        self._load_week()

    def _clear_form(self) -> None:
        while self.game_form.count():
            item = self.game_form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._game_rows = []

    def _load_week(self) -> None:
        s = self.season
        self._clear_form()
        if s is None or not self.week_picker.count():
            return
        number = self.week_picker.currentData()
        week = s.weeks.get(number)

        writable = s.workbook_path is not None
        self.save_btn.setEnabled(writable)
        self.preview_btn.setEnabled(writable)
        if not writable:
            self.editor_status.setText("No workbook loaded - nothing to write to.")
            return

        games = week.games if week else []
        if not games:
            self.editor_status.setText(
                f"Week {number} has no matchups in the workbook. "
                "Add them in Excel first."
            )
            return

        for game in games[:GAMES_PER_WEEK]:
            label = QLabel(f"{game.index}.  {game.label}")
            picker = QComboBox()
            picker.addItem(NO_PICK, "")
            for team in (game.away, game.home):
                if team:
                    picker.addItem(team, team)
            if game.winner:
                index = picker.findData(game.winner)
                picker.setCurrentIndex(index if index >= 0 else 0)
            picker.setProperty("game_index", game.index)
            picker.setProperty("original", game.winner or "")
            self.game_form.addRow(label, picker)
            self._game_rows.append((label, picker))

        entered = sum(1 for g in games if g.played)
        self.editor_status.setText(
            f"{len(games)} games · {entered} result(s) already entered · "
            f"writing to {s.workbook_path.name}"
        )

    def _pending_edits(self) -> list[tuple[int, str]]:
        """(game index, winner) for every row the user actually changed."""
        changes = []
        for _, picker in self._game_rows:
            chosen = picker.currentData() or ""
            if chosen != (picker.property("original") or ""):
                changes.append((int(picker.property("game_index")), chosen))
        return changes

    def _build_editor(self) -> tuple[WorkbookEditor | None, list[tuple[int, str]]]:
        s = self.season
        changes = self._pending_edits()
        if not changes or s is None or s.workbook_path is None:
            return None, changes
        editor = WorkbookEditor(s.workbook_path)
        week = self.week_picker.currentData()
        for game_index, winner in changes:
            editor.set_result(week, game_index, winner)
        return editor, changes

    def _preview(self) -> None:
        editor, changes = self._build_editor()
        if not changes:
            QMessageBox.information(self, "No changes", "Nothing has been changed yet.")
            return
        result = editor.apply(dry_run=True)
        lines = [f"{e.address}  →  {e.value or '(cleared)'}" for e in result.applied]
        for edit, reason in result.refused:
            lines.append(f"REFUSED {edit.address}: {reason}")
        QMessageBox.information(
            self, "Pending changes", "\n".join(lines) or "Nothing to write."
        )

    def _save(self) -> None:
        s = self.season
        editor, changes = self._build_editor()
        if not changes:
            QMessageBox.information(self, "No changes", "Nothing has been changed yet.")
            return

        week = self.week_picker.currentData()
        confirm = QMessageBox.question(
            self,
            "Write to the workbook?",
            f"{len(changes)} result(s) for week {week} will be written to\n"
            f"{s.workbook_path.name}.\n\n"
            "A timestamped backup is saved to backups/ first.\n"
            "Close the file in Excel before continuing.",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if confirm != QMessageBox.StandardButton.Save:
            return

        try:
            result = editor.apply()
        except WriteBackError as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return
        except PermissionError:
            QMessageBox.critical(
                self,
                "Could not save",
                "The workbook is open in Excel. Close it and try again.",
            )
            return
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", f"Writing failed: {exc}")
            return

        if result.refused:
            QMessageBox.warning(
                self,
                "Nothing was written",
                "These cells were protected and the save was abandoned:\n\n"
                + "\n".join(reason for _, reason in result.refused),
            )
            return

        QMessageBox.information(
            self,
            "Saved",
            f"{result.summary()}.\n\n"
            "Open the workbook in Excel to let it recalculate wins, ranks "
            "and payouts, then save it and press Rescan now.",
        )
        self.refresh_requested.emit()
