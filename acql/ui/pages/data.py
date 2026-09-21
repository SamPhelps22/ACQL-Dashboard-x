"""Files, conflicts, and the weekly editor that writes back to Excel."""

from __future__ import annotations

import os
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

from ..editor import WeekEditor
from ..widgets import Banner, Card, TableModel, make_table, section
from .base import Page

FILE_HEADERS = ["File", "Type", "Week", "Folder", "Status"]
CONFLICT_HEADERS = ["Player", "Field", "stats.xls (used)", "Workbook", "Note"]

SOURCE_KINDS = {
    "stats": "Standings export",
    "dashboard": "Dashboard workbook",
}

ROW_HEIGHT = 27
TABLE_PADDING = 6          # frame + a little breathing room
MAX_TABLE_HEIGHT = 260     # tables scroll beyond this rather than push the editor away


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

    @staticmethod
    def _fit_height(view, row_count: int) -> None:
        """Size a table to its rows, capped so the editor keeps the spotlight."""
        header = view.horizontalHeader().sizeHint().height()
        wanted = header + row_count * ROW_HEIGHT + TABLE_PADDING
        view.setMaximumHeight(min(wanted, MAX_TABLE_HEIGHT))

    # ---- inventory -------------------------------------------------------
    def refresh(self) -> None:
        settings = self._load_settings()
        self._refresh_folders(settings)

        s = self.season
        if s is None:
            return

        self.banner.show_messages(s.warnings)
        self._refresh_files(s)
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
                + "\n\nDrop each week's stats.xls and the updated "
                "ACQL Dashboard.xlsx into any of these, then press Rescan now."
            )
        else:
            self.folders_label.setText(
                "No folders are being watched yet. Use \u201cAdd a folder\u2026\u201d "
                "to point the app at the place you keep stats.xls and the workbook."
            )

    def _refresh_files(self, s) -> None:
        rows, tones = [], {}
        for r, src in enumerate(s.sources):
            rows.append([
                src.path.name,
                SOURCE_KINDS.get(src.kind, str(src.kind).title()),
                src.week or "\u2013",
                str(src.path.parent),
                src.error or "Loaded",
            ])
            tones[(r, 4)] = "bad" if src.error else "good"
        if not rows:
            rows = [[
                "No files found", "\u2013", "\u2013", "\u2013",
                "Drop files into a watched folder",
            ]]

        model = TableModel(
            FILE_HEADERS, rows,
            palette=self.palette,
            numeric_columns={2},
            tones=tones,
            bold_columns={0},
        )
        view, _ = make_table(model, stretch_column=3, row_height=ROW_HEIGHT)
        self._fit_height(view, len(rows))
        self.files_table = self._swap_table(self.files_box, self.files_table, view)

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
        view, _ = make_table(model, stretch_column=4, row_height=ROW_HEIGHT)
        self._fit_height(view, len(rows))
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