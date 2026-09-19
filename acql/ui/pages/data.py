"""Files, conflicts, and the weekly editor that writes back to Excel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..editor import WeekEditor
from ..widgets import Banner, Card, TableModel, make_table, section
from .base import Page

FILE_HEADERS = ["File", "Type", "Week", "Folder", "Status"]
CONFLICT_HEADERS = ["Player", "Field", "stats.xls (used)", "Workbook", "Note"]


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

        self.editor.set_season(s)

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
