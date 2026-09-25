"""Files, conflicts, and the weekly editor that writes back to Excel."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import picks, predictions
from ..editor import WeekEditor
from ..widgets import Banner, Card, TableModel, make_table, section
from .base import Page

FILE_HEADERS = ["File", "Type", "Week", "Updated", "What it gave", "Folder", "Status"]
CONFLICT_HEADERS = ["Player", "Field", "stats.xls (used)", "Workbook", "Note"]
WEEKLY_HEADERS = ["Week", "Kind", "From", "What is in it", "Status"]

SOURCE_KINDS = {
    "stats": "Standings export",
    "workbook": "Dashboard workbook",
    "dashboard": "Dashboard workbook",
}

ROW_HEIGHT = 27
MAX_TABLE_ROWS = 8         # tables scroll beyond this rather than push the editor away


def _norm(path: str | Path) -> str:
    """Comparable form of a folder path (resolved, case-folded on Windows)."""
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        pass
    return os.path.normcase(str(p))


class DataPage(Page):
    """Inventory of loaded files plus the write-back editor.

    The embedded editor covers every cell the workbook treats as an input -
    matchups, results, picks, big-loser slots, suicide picks and the week's
    game count. Everything else (wins, ranks, money, the Dashboard sheet) is
    an Excel formula that recalculates from them, so those are left to Excel
    rather than overwritten here.
    """

    title = "Data & Update"
    subtitle = "What is loaded, what disagrees, and how to enter this week's results"
    icon = "\N{CARD INDEX DIVIDERS}"
    #: This is where folders get added, so it must work before any data does.
    needs_data = False

    refresh_requested = Signal()

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        self.banner = Banner()
        self.layout_.addWidget(self.banner)

        # ---- editor ----
        self.editor_card = Card("Enter this week's results")
        self.editor_note = QLabel(
            "The workbook's only input cells are a week's matchups, results, "
            "picks, big-loser picks and suicide picks \u2014 every win total, "
            "rank, payout and the whole Dashboard sheet is an Excel formula "
            "fed by them. Edit those here and Excel recalculates the rest. "
            "A timestamped backup is taken before each save, and a change set "
            "that would touch a formula is refused whole."
        )
        self.editor_note.setObjectName("StatDetail")
        self.editor_note.setWordWrap(True)
        self.editor_card.add(self.editor_note)

        self.editor = WeekEditor(self.palette)
        self.editor.saved.connect(self.refresh_requested.emit)
        self.editor.setMinimumHeight(560)
        self.editor_card.add(self.editor, 1)

        self.layout_.addWidget(self.editor_card, 1)

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
        self.add_folder_btn = QPushButton("Add a folder\u2026")
        self.add_folder_btn.setToolTip("Watch another folder for stats.xls and the workbook")
        self.add_folder_btn.clicked.connect(self._add_folder)
        self.reload_btn = QPushButton("Rescan now")
        self.reload_btn.setObjectName("Primary")
        self.reload_btn.setToolTip("Re-read every watched folder")
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
        self.files_table: QWidget | None = None

        # ---- the week-by-week files ----
        # Pick sheets and predictions are read from Downloads as much as from
        # the watched folders, and they are stored once read - so the folder
        # listing above says nothing about them. Without this the only way to
        # find out which sheets the app is actually holding was to read the
        # numbers and work backwards.
        self.weekly_card = Card("Pick sheets and predictions")
        self.weekly_note = QLabel(
            "Everything the app is holding for a particular week, whatever "
            "folder it came from. A sheet from another pool is named here "
            "rather than quietly ignored."
        )
        self.weekly_note.setObjectName("StatDetail")
        self.weekly_note.setWordWrap(True)
        self.weekly_card.add(self.weekly_note)
        self.weekly_box = QVBoxLayout()
        self.weekly_card.body().addLayout(self.weekly_box)
        old_row = QHBoxLayout()
        self.clear_old_btn = QPushButton("Clear sheets from other seasons")
        self.clear_old_btn.setToolTip(
            "Delete the stored pick sheets whose games are not this season's. "
            "They are already being ignored; this just stops them being listed."
        )
        self.clear_old_btn.clicked.connect(self._clear_old_sheets)
        self.clear_old_btn.hide()
        old_row.addWidget(self.clear_old_btn)
        old_row.addStretch(1)
        self.weekly_card.body().addLayout(old_row)
        self.layout_.addWidget(self.weekly_card)
        self.weekly_table: QWidget | None = None

        # ---- conflicts ----
        self.conflicts_card = Card("Disagreements between files")
        self.conflicts_note = QLabel("")
        self.conflicts_note.setObjectName("StatDetail")
        self.conflicts_note.setWordWrap(True)
        self.conflicts_card.add(self.conflicts_note)
        self.conflicts_box = QVBoxLayout()
        self.conflicts_card.body().addLayout(self.conflicts_box)
        self.layout_.addWidget(self.conflicts_card)
        self.conflicts_table: QWidget | None = None

        self.layout_.addStretch(1)

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _load_settings():
        # Imported lazily so this page never creates an import cycle with config.
        from ...config import Settings

        return Settings.load()

    @staticmethod
    def _swap_table(box: QVBoxLayout, old: QWidget | None, new: QWidget) -> QWidget:
        """Replace ``old`` with ``new`` in ``box`` without a flicker of both."""
        if old is not None:
            box.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
        box.addWidget(new)
        return new

    # ---- inventory -------------------------------------------------------
    def refresh(self) -> None:
        settings = self._load_settings()
        self._refresh_folders(settings)

        s = self.season
        if s is None:
            return

        self.banner.show_messages(s.warnings)
        self._refresh_files(s)
        self._refresh_weekly(s)
        self._refresh_conflicts(s)
        self.editor.set_season(s)

    def _refresh_folders(self, settings) -> None:
        paths = list(settings.search_paths())
        if paths:
            lines = [
                str(p) if Path(p).exists() else f"{p}  (missing)"
                for p in paths
            ]
            self.folders_label.setText(
                "\n".join(lines)
                + "\n\nDrop the updated ACQL Dashboard.xlsx, the week's pick "
                "sheets or a predictions CSV into any of these. They are read "
                "as soon as they land or are saved – Rescan now is only "
                "for when you want to force it."
            )
        else:
            self.folders_label.setText(
                "No folders are being watched yet. Use \u201cAdd a folder\u2026\u201d "
                "to point the app at the place you keep stats.xls and the workbook."
            )

    @staticmethod
    def _when(source) -> str:
        """When the file was last written, in words rather than a timestamp."""
        stamp = getattr(source, "modified", 0) or 0
        if not stamp:
            return "\u2013"
        try:
            age = max(0.0, time.time() - float(stamp))
        except (TypeError, ValueError):
            return "\u2013"
        if age < 3600:
            return f"{int(age // 60)} min ago"
        if age < 86400:
            return f"{int(age // 3600)} hr ago"
        days = int(age // 86400)
        return "yesterday" if days == 1 else f"{days} days ago"

    def _gave(self, s, source) -> str:
        """What the app actually got out of this file.

        A file can load without error and still contribute nothing - the
        workbook whose every cell is a formula did exactly that for weeks.
        "Loaded" was true and useless; this says what came of it.
        """
        if source.error:
            return "nothing"
        name = source.path.name
        people = sum(1 for p in s.players.values() if name in p.sources)
        weeks = sorted(
            number for number, week in s.weeks.items()
            if getattr(week, "source", None) is not None
            and Path(getattr(week, "source", "")).name == name
        )
        parts = []
        if people:
            parts.append(f"{people} coach{'' if people == 1 else 'es'}")
        if weeks:
            scored = [w for w in weeks if s.weeks[w].scored]
            parts.append(
                f"{len(weeks)} week{'' if len(weeks) == 1 else 's'}"
                + (f" ({len(scored)} scored)" if scored else ", none scored")
            )
        return " \u00b7 ".join(parts) if parts else "nothing the app could use"

    def _refresh_files(self, s) -> None:
        rows, tones = [], {}
        for r, src in enumerate(s.sources):
            gave = self._gave(s, src)
            rows.append([
                src.path.name,
                SOURCE_KINDS.get(src.kind, str(src.kind).title()),
                src.week or "\u2013",
                self._when(src),
                gave,
                str(src.path.parent),
                src.error or "Loaded",
            ])
            tones[(r, 6)] = "bad" if src.error else "good"
            # A file that loaded but gave nothing is the quiet failure worth
            # seeing, so it is marked even though nothing went wrong.
            if not src.error and gave.startswith("nothing"):
                tones[(r, 4)] = "bad"
        if not rows:
            rows = [[
                "No files found", "\u2013", "\u2013", "\u2013", "\u2013", "\u2013",
                "Drop files into a watched folder",
            ]]

        model = TableModel(
            FILE_HEADERS, rows,
            palette=self.palette,
            numeric_columns={2},
            tones=tones,
            bold_columns={0},
        )
        view, _ = make_table(model, stretch_column=5, row_height=ROW_HEIGHT, fit_rows=MAX_TABLE_ROWS)
        self.files_table = self._swap_table(self.files_box, self.files_table, view)

    def _refresh_weekly(self, s) -> None:
        """Pick sheets and prediction files, whichever folder they came from."""
        rows, tones = [], {}
        roster = {
            "".join(c for c in p.display.casefold() if c.isalnum())
            for p in s.players.values()
        }
        old = picks.other_season_weeks()
        self.clear_old_btn.setVisible(bool(old))
        for number, sheet in sorted(picks.load_all(every_season=True).items()):
            coaches = sheet.coaches
            if number in old:
                rows.append([
                    number, "Pick sheet", Path(sheet.source).name or "\u2013",
                    f"{len(coaches)} coaches - games are not this season's week {number}",
                    "Another season's",
                ])
                tones[(len(rows) - 1, 4)] = "bad"
                continue
            ours = [
                name for name in coaches
                if "".join(c for c in name.casefold() if c.isalnum()) in roster
            ]
            stranger = roster and len(ours) < max(2, 0.4 * len(coaches))
            rows.append([
                number, "Pick sheet", Path(sheet.source).name or "\u2013",
                f"{len(coaches)} coach{'' if len(coaches) == 1 else 'es'}"
                + (f", {len(ours)} in this pool" if roster and len(ours) != len(coaches)
                   else ""),
                "Another pool's" if stranger else "In use",
            ])
            tones[(len(rows) - 1, 4)] = "bad" if stranger else "good"

        for number, stored in sorted(predictions.stored_weeks().items()):
            _, where = predictions.load(number)
            priced = sum(1 for f in stored if f.market is not None)
            rows.append([
                number, "Predictions", Path(where).name if where else "pasted",
                f"{len(stored)} games, {priced} with a line",
                "In use" if priced else "no lines in it",
            ])
            tones[(len(rows) - 1, 4)] = "good" if priced else "bad"

        if not rows:
            self.weekly_card.hide()
            return
        self.weekly_card.show()
        model = TableModel(
            WEEKLY_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0},
            tones=tones,
            bold_columns={2},
        )
        view, _ = make_table(model, stretch_column=3, row_height=ROW_HEIGHT, fit_rows=MAX_TABLE_ROWS)
        self.weekly_table = self._swap_table(self.weekly_box, self.weekly_table, view)

    def _clear_old_sheets(self) -> None:
        picks.forget_weeks(picks.other_season_weeks())
        self.refresh_requested.emit()

    def _refresh_conflicts(self, s) -> None:
        if not s.conflicts:
            self.conflicts_card.hide()
            return

        n = len(s.conflicts)
        self.conflicts_note.setText(
            f"stats.xls is treated as authoritative. {n} "
            f"{'disagreement was' if n == 1 else 'disagreements were'} found "
            "\u2014 worth checking in the workbook."
        )
        rows = [
            [c.player, c.field, str(c.authoritative), str(c.other), c.note]
            for c in s.conflicts
        ]
        model = TableModel(
            CONFLICT_HEADERS, rows, palette=self.palette, bold_columns={0}
        )
        view, _ = make_table(model, stretch_column=4, row_height=ROW_HEIGHT, fit_rows=MAX_TABLE_ROWS)
        self.conflicts_table = self._swap_table(
            self.conflicts_box, self.conflicts_table, view
        )
        self.conflicts_card.show()

    # ---- actions ---------------------------------------------------------
    def _add_folder(self) -> None:
        settings = self._load_settings()

        # Open the dialog somewhere useful: the first watched folder that exists.
        start = next(
            (str(p) for p in settings.search_paths() if Path(p).is_dir()),
            str(Path.home()),
        )
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a folder to watch", start
        )
        if not folder:
            return

        # Compare resolved paths so a different slash style, trailing separator,
        # or a folder that's already covered by the defaults isn't added twice.
        known = {_norm(p) for p in settings.data_dirs}
        known.update(_norm(p) for p in settings.search_paths())
        if _norm(folder) not in known:
            settings.data_dirs.append(str(Path(folder).expanduser().resolve()))
            settings.save()

        self.refresh_requested.emit()