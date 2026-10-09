"""Files, where each week's results came from, conflicts, and - while a
workbook is still loaded - the editor that writes back to it."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import picks, predictions, results, store, updater
from ..editor import WeekEditor
from ..widgets import Banner, Card, TableModel, make_table, section
from .base import CHECK_RESULTS, CHECK_UPDATES, INSTALL_UPDATE, KEEPING, SELF_CHECK, UNDO_UPDATE, UPDATE_SETTINGS, Page

FILE_HEADERS = ["File", "Type", "Week", "Updated", "What it gave", "Folder", "Status"]
CONFLICT_HEADERS = ["Player", "Field", "stats.xls (used)", "Other count", "Note"]
WEEKLY_HEADERS = ["Week", "Kind", "From", "What is in it", "Status"]
RESULTS_HEADERS = ["Week", "Games", "Results from", "Status"]

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
    subtitle = "What is loaded, where the results came from, what disagrees, and updating the app"
    icon = "\N{CARD INDEX DIVIDERS}"
    #: This is where folders get added, so it must work before any data does.
    needs_data = False

    refresh_requested = Signal()

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        self.banner = Banner()
        self.layout_.addWidget(self.banner)

        # ---- the app itself: its version, its memory, updates ----
        self.app_card = Card("The app")
        self.app_label = QLabel("")
        self.app_label.setWordWrap(True)
        self.app_label.setTextFormat(Qt.TextFormat.RichText)
        self.app_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.app_card.add(self.app_label)
        app_buttons = QHBoxLayout()
        self.update_btn = QPushButton("Install update\u2026")
        self.update_btn.setObjectName("Primary")
        self.update_btn.setToolTip(
            "Install an update zip - it finds one in Downloads by itself. The "
            "current code is backed up first and put back if anything goes wrong."
        )
        self.update_btn.clicked.connect(lambda: self.action_requested.emit(INSTALL_UPDATE))
        self.check_updates_btn = QPushButton("Check for updates")
        self.check_updates_btn.setToolTip("Look in the dashboard's GitHub repository for a newer version now")
        self.check_updates_btn.clicked.connect(lambda: self.action_requested.emit(CHECK_UPDATES))
        self.update_settings_btn = QPushButton("Updates from GitHub\u2026")
        self.update_settings_btn.setToolTip("Where new versions come from: the repository and its token")
        self.update_settings_btn.clicked.connect(lambda: self.action_requested.emit(UPDATE_SETTINGS))
        self.undo_btn = QPushButton("Undo last update")
        self.undo_btn.setToolTip("Put back the code from before the last update")
        self.undo_btn.clicked.connect(lambda: self.action_requested.emit(UNDO_UPDATE))
        self.check_btn = QPushButton("Run self-check")
        self.check_btn.setToolTip(
            "Open every page, photograph it whole and note anything that looks "
            "wrong - one zip to send when something needs fixing"
        )
        self.check_btn.clicked.connect(lambda: self.action_requested.emit(SELF_CHECK))
        self.backup_btn = QPushButton("Back up now")
        self.backup_btn.setToolTip("Save a copy of everything the app remembers, beside the daily ones")
        self.backup_btn.clicked.connect(self._backup_now)
        self.backups_btn = QPushButton("Open backups")
        self.backups_btn.clicked.connect(self._open_backups)
        for button in (self.check_updates_btn, self.update_btn, self.undo_btn, self.update_settings_btn,
                       self.check_btn, self.backup_btn, self.backups_btn):
            app_buttons.addWidget(button)
        app_buttons.addStretch(1)
        self.app_card.body().addLayout(app_buttons)
        self.layout_.addWidget(self.app_card)

        # ---- keeping the website current with nobody here (keeping.py) ----
        self.keep_card = Card("Keeping the website up to date by itself")
        self.keep_note = QLabel(
            "The website updates itself when results come in or a new pick sheet lands "
            "in the folder - but only while the dashboard is running. Turn these on and "
            "it runs out of sight from the moment the computer starts, so the site keeps "
            "up on a Sunday whether or not anyone opens it. The computer still has to be "
            "on and awake."
        )
        self.keep_note.setObjectName("StatDetail")
        self.keep_note.setWordWrap(True)
        self.keep_card.add(self.keep_note)
        self.tray_box = QCheckBox("Keep running in the tray when the window is closed")
        self.startup_box = QCheckBox("Start with Windows, in the tray")
        self.keep_status = QLabel("")
        self.keep_status.setObjectName("Muted")
        self.keep_status.setWordWrap(True)
        for widget in (self.tray_box, self.startup_box, self.keep_status):
            self.keep_card.add(widget)
        self.tray_box.toggled.connect(self._tray_toggled)
        self.startup_box.toggled.connect(self._startup_toggled)
        self.layout_.addWidget(self.keep_card)
        self._show_keeping()

        # ---- where the results come from ----
        self.results_card = Card("Results")
        self.results_note = QLabel(
            "Every week is built from the commissioner's pick sheet: the games, "
            "the pool's lines and everyone's picks. Results come from his graded "
            "copy of the sheet when you've downloaded it, and otherwise from "
            "ESPN's final scores with the pool's lines applied \u2014 the "
            "dashboard looks every few minutes while games are on. stats.xls "
            "stays the official word on the standings."
        )
        self.results_note.setObjectName("StatDetail")
        self.results_note.setWordWrap(True)
        self.results_card.add(self.results_note)
        self.results_box = QVBoxLayout()
        self.results_card.body().addLayout(self.results_box)
        results_row = QHBoxLayout()
        self.results_btn = QPushButton("Check for results now")
        self.results_btn.setToolTip("Ask ESPN about every week that isn't finished, then reload")
        self.results_btn.clicked.connect(lambda: self.action_requested.emit(CHECK_RESULTS))
        results_row.addWidget(self.results_btn)
        results_row.addStretch(1)
        self.results_card.body().addLayout(results_row)
        self.layout_.addWidget(self.results_card)
        self.results_table: QWidget | None = None

        # ---- editor (only while a workbook is still loaded) ----
        self.editor_card = Card("The workbook")
        self.editor_note = QLabel(
            "Your ACQL Dashboard workbook is still being read for the weeks it "
            "has results in. It isn't needed any more \u2014 the pick sheets "
            "and the results do its job \u2014 so take it out of the folder "
            "whenever you like. Until then, anything typed here is kept: a "
            "timestamped backup is taken before each save, and a change set "
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
        self.add_folder_btn.setToolTip("Watch another folder for pick sheets and stats.xls")
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
        self.weekly_card = Card("Pick sheets, graded copies and predictions")
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

    # ---- the app ---------------------------------------------------------
    def _refresh_app(self) -> None:
        try:
            from ...version import VERSION, RELEASED
        except Exception:  # noqa: BLE001
            VERSION, RELEASED = "?", ""
        try:
            counts = store.kinds()
            path = store.db_path()
        except store.StoreError as exc:
            self.app_label.setText(f"<b>ACQL Dashboard {VERSION}</b> \u00b7 {exc}")
            return
        words = {
            "forecasts": "weeks of predictions", "picks": "pick sheets",
            "graded": "graded copies", "results": "weeks of results",
            "spreads": "weeks of typed spreads", "cards": "saved cards",
            "odds": "fetched-lines records", "settings": "settings",
        }
        held = ", ".join(
            f"{counts[k]} {words[k]}" for k in words if counts.get(k)
        ) or "nothing yet"
        backups = sorted(store.backup_folder().glob("acql-????-??-??.db"))
        latest = backups[-1].stem.replace("acql-", "") if backups else "none yet"
        record = updater.last_install(store.project_root())
        self.undo_btn.setEnabled(bool(record))
        installed = (
            f" \u00b7 updated from {record.get('from')} on "
            f"{time.strftime('%a %d %b', time.localtime(record.get('at', 0)))}"
            if record else ""
        )
        self.app_label.setText(
            f"<b>ACQL Dashboard {VERSION}</b> ({RELEASED}){installed}<br>"
            f"Everything the app remembers is in <b>{path.name}</b> in the data folder: "
            f"{held}. A copy is kept every day in {store.BACKUP_FOLDER}\\ "
            f"(latest {latest}); the last {store.KEEP_BACKUPS} are kept."
        )

    # ---- keeping up by itself ---------------------------------------------
    def _show_keeping(self) -> None:
        from .. import keeping
        self._keeping_quiet = True
        try:
            available = keeping.tray_available()
            self.tray_box.setChecked(keeping.tray_wanted())
            self.startup_box.setChecked(keeping.startup_enabled())
            self.tray_box.setEnabled(available)
            self.startup_box.setEnabled(available)
            self.keep_status.setText("" if available else
                                     "This computer has no tray to run in, so these are off.")
        finally:
            self._keeping_quiet = False

    def _tray_toggled(self, on: bool) -> None:
        from .. import keeping
        if self._keeping_quiet:
            return
        keeping.set_tray_wanted(on)
        if not on and keeping.startup_enabled():
            # Starting with Windows means starting in the tray: one goes with the other.
            keeping.set_startup(False)
        self.action_requested.emit(KEEPING)
        self._show_keeping()
        self.keep_status.setText("Closing the window now leaves the dashboard in the tray, by the clock."
                                 if on else "Closing the window quits the dashboard again.")

    def _startup_toggled(self, on: bool) -> None:
        from .. import keeping
        if self._keeping_quiet:
            return
        why = keeping.set_startup(on)
        if on and not why:
            keeping.set_tray_wanted(True)
            self.action_requested.emit(KEEPING)
        self._show_keeping()
        self.keep_status.setText(why or ("It starts in the tray when Windows does." if on
                                         else "It won't start with Windows any more."))

    def _backup_now(self) -> None:
        target = store.backup_folder() / f"acql-manual-{time.strftime('%Y%m%d-%H%M%S')}.db"
        try:
            store.backup_now(target)
        except (OSError, store.StoreError) as exc:
            self.app_label.setText(self.app_label.text() + f"<br>Back-up failed: {exc}")
            return
        self._refresh_app()
        self.app_label.setText(self.app_label.text() + f"<br>Saved {target.name}.")

    def _open_backups(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        folder = store.backup_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ---- inventory -------------------------------------------------------
    def refresh(self) -> None:
        settings = self._load_settings()
        self._refresh_folders(settings)
        try:
            self._refresh_app()
        except Exception as exc:  # noqa: BLE001 - the rest of the page still matters
            self.app_label.setText(f"Couldn't read the app's details: {exc}")

        s = self.season
        if s is None:
            return

        self.banner.show_messages(s.warnings)
        self._refresh_results(s)
        self._refresh_files(s)
        self._refresh_weekly(s)
        self._refresh_conflicts(s)
        self.editor_card.setVisible(getattr(s, "workbook_path", None) is not None)
        try:
            from ...repository import workbook_note
            self.editor_note.setText(workbook_note(s))
        except Exception:  # noqa: BLE001 - the wording it was built with stays
            pass
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
                + "\n\nDrop the week's pick sheet, stats.xls or a predictions CSV "
                "into any of these (pick sheets are found in Downloads too). They "
                "are read as soon as they land or are saved – Rescan now is "
                "only for when you want to force it."
            )
        else:
            self.folders_label.setText(
                "No folders are being watched yet. Use \u201cAdd a folder\u2026\u201d "
                "to point the app at the place you keep the pick sheets and stats.xls."
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

    def _refresh_results(self, s) -> None:
        """Each week: how many games are decided, and who said so."""
        year = results.season_year(s)
        rows, tones = [], {}
        for number in sorted(s.weeks, reverse=True):
            week = s.weeks[number]
            games = sorted(week.games, key=lambda g: g.index)
            if not games:
                continue
            played = [g for g in games if g.played]
            where: dict[str, int] = {}
            for game in played:
                name = game.result_from or "workbook"
                where[name] = where.get(name, 0) + 1
            if len(where) == 1:
                came = next(iter(where))
            else:
                came = " \u00b7 ".join(
                    f"{name} {n}" for name, n in sorted(where.items(), key=lambda kv: -kv[1]))
            left = len(games) - len(played)
            if not left:
                status = "Final"
            else:
                status = f"{left} still to finish" if played else "Not started"
                kept = results.load(year, number)
                ahead = [score.kickoff for g in games if not g.played
                         for score in [results.find(kept, g.away, g.home)[0]]
                         if score is not None and score.kickoff and score.kickoff > time.time()]
                if ahead:
                    status += f" \u00b7 next kickoff {self._clock(min(ahead))}"
                checked = results.checked_at(year, number)
                if checked:
                    status += f" \u00b7 ESPN checked {self._ago(checked)}"
            rows.append([number, f"{len(played)} of {len(games)} decided", came or "\u2013", status])
            tones[(len(rows) - 1, 3)] = "good" if not left else ""
        if not rows:
            self.results_card.hide()
            return
        self.results_card.show()
        model = TableModel(RESULTS_HEADERS, rows, palette=self.palette, numeric_columns={0}, tones=tones)
        view, _ = make_table(model, stretch_column=3, row_height=ROW_HEIGHT, fit_rows=MAX_TABLE_ROWS)
        self.results_table = self._swap_table(self.results_box, self.results_table, view)

    @staticmethod
    def _clock(stamp: float) -> str:
        """"Sun 12:00 PM" in the computer's own time."""
        at = time.localtime(stamp)
        return f"{time.strftime('%a', at)} {at.tm_hour % 12 or 12}:{at.tm_min:02d} {'AM' if at.tm_hour < 12 else 'PM'}"

    @staticmethod
    def _ago(stamp: float) -> str:
        age = max(0.0, time.time() - stamp)
        if age < 90:
            return "just now"
        if age < 3600:
            return f"{int(age // 60)} min ago"
        if age < 86400:
            return f"{int(age // 3600)} hr ago"
        return time.strftime("%a %d %b", time.localtime(stamp))

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
                number, "Graded sheet" if sheet.graded else "Pick sheet",
                Path(sheet.source).name or "\u2013",
                f"{len(coaches)} coach{'' if len(coaches) == 1 else 'es'}"
                + (f", {len(ours)} in this pool" if roster and len(ours) != len(coaches)
                   else ""),
                "Another pool's" if stranger else "In use",
            ])
            tones[(len(rows) - 1, 4)] = "bad" if stranger else "good"
            copy = picks.load_graded(number) if not sheet.graded and not stranger else None
            if copy is not None:
                graded_games = sum(1 for g in copy.games if g.credited)
                rows.append([
                    number, "Graded copy", Path(copy.source).name or "\u2013",
                    f"{graded_games} of {len(copy.games)} games graded",
                    "In use" if graded_games else "Nothing graded yet",
                ])
                tones[(len(rows) - 1, 4)] = "good" if graded_games else ""

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
            "\u2014 worth a look."
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