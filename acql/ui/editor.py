"""The weekly editor: every cell the workbook actually treats as an input.

The workbook is almost entirely derived. Its literal cells are the week's
matchups, each game's result, each player's picks, their big-loser picks and
their suicide pick, plus the per-week game count on the Season sheet. This
widget exposes exactly those, and nothing else: win totals, ranks, payouts and
the Dashboard sheet are Excel formulas fed by them and recalculate on open.

Edits are collected across both tabs and applied as one guarded change set, so
a week's worth of entry is a single backup and a single save.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import BIG_LOSER_PICKS, GAMES_PER_WEEK
from ..models import Season
from ..writeback import WorkbookEditor, WriteBackError
from .theme import Palette

NO_RESULT = "— not played —"
NO_PICK = "— no pick —"


def _select_team(combo: QComboBox, stored: str, options: list[str]) -> None:
    """Fill a team chooser and select what the workbook already holds.

    The sheet is inconsistent about capitalisation - several home-team picks
    are stored shouted ("CINCINNATI") while others are not - so options are
    matched case-insensitively and the stored spelling is kept as the item's
    value. Selecting the entry a cell already contains is then a no-op rather
    than a spurious change, and the list never shows the same team twice.
    """
    combo.clear()
    combo.addItem(NO_PICK, "")
    matched = False
    for team in options:
        team = (team or "").strip()
        if not team:
            continue
        if stored and team.casefold() == stored.casefold():
            combo.addItem(stored, stored)   # keep the workbook's own spelling
            matched = True
        else:
            combo.addItem(team, team)
    if stored and not matched:
        # A pick for a team no longer on the slate still has to be visible.
        combo.addItem(stored, stored)
    index = combo.findData(stored) if stored else 0
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.setProperty("original", stored)



class WeekEditor(QWidget):
    """Edits one week's input cells and writes them back to the workbook."""

    saved = Signal()

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_ = palette
        self.season: Season | None = None
        self._week: int | None = None
        self._loading = False
        # Only one player's picks are on screen at a time, so edits to the
        # others are held here rather than lost when the selection changes.
        self._loaded_player: str = ""
        self._pending_players: dict[str, list[tuple]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ---- week selector -------------------------------------------
        top = QHBoxLayout()
        top.addWidget(QLabel("Week"))
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(140)
        self.week_picker.currentIndexChanged.connect(lambda _: self.load_week())
        top.addWidget(self.week_picker)

        top.addSpacing(18)
        top.addWidget(QLabel("Games counted"))
        self.game_count = QSpinBox()
        self.game_count.setRange(0, GAMES_PER_WEEK)
        self.game_count.setToolTip(
            "The week's game count on the Season sheet, which the win "
            "percentages divide by."
        )
        self.game_count.valueChanged.connect(self._mark_dirty)
        top.addWidget(self.game_count)

        top.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        top.addWidget(self.status)
        layout.addLayout(top)

        # ---- tabs -----------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_slate_tab(), "Slate && results")
        self.tabs.addTab(self._build_picks_tab(), "Picks")
        layout.addWidget(self.tabs, 1)

        # ---- actions --------------------------------------------------
        actions = QHBoxLayout()
        self.save_btn = QPushButton("Save to workbook")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self.save)
        self.preview_btn = QPushButton("Preview changes")
        self.preview_btn.clicked.connect(self.preview)
        self.revert_btn = QPushButton("Discard changes")
        self.revert_btn.clicked.connect(self.load_week)
        self.pending_label = QLabel("No changes")
        self.pending_label.setObjectName("Muted")
        actions.addWidget(self.save_btn)
        actions.addWidget(self.preview_btn)
        actions.addWidget(self.revert_btn)
        actions.addSpacing(12)
        actions.addWidget(self.pending_label)
        actions.addStretch(1)
        layout.addLayout(actions)

    # ---- construction -------------------------------------------------
    def _build_slate_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 8, 0, 0)
        note = QLabel(
            "Type the teams and pick each winner. The winner list follows "
            "whatever the two team cells say."
        )
        note.setObjectName("StatDetail")
        note.setWordWrap(True)
        box.addWidget(note)

        self.slate = QTableWidget(GAMES_PER_WEEK, 4)
        self.slate.setHorizontalHeaderLabels(["#", "Home team", "Away team", "Winner"])
        self.slate.verticalHeader().setVisible(False)
        self.slate.setAlternatingRowColors(True)
        self.slate.setShowGrid(False)
        self.slate.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.slate.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

        self._home_fields: list[QLineEdit] = []
        self._away_fields: list[QLineEdit] = []
        self._winner_fields: list[QComboBox] = []
        for row in range(GAMES_PER_WEEK):
            number = QTableWidgetItem(str(row + 1))
            number.setFlags(Qt.ItemFlag.ItemIsEnabled)
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.slate.setItem(row, 0, number)

            home, away = QLineEdit(), QLineEdit()
            winner = QComboBox()
            for field in (home, away):
                field.setFrame(False)
                field.textChanged.connect(self._mark_dirty)
            # Retyping a team must keep the winner list in step with it.
            home.editingFinished.connect(lambda r=row: self._refresh_winner_options(r))
            away.editingFinished.connect(lambda r=row: self._refresh_winner_options(r))
            winner.currentIndexChanged.connect(self._mark_dirty)

            self.slate.setCellWidget(row, 1, home)
            self.slate.setCellWidget(row, 2, away)
            self.slate.setCellWidget(row, 3, winner)
            self._home_fields.append(home)
            self._away_fields.append(away)
            self._winner_fields.append(winner)

        self.slate.verticalHeader().setDefaultSectionSize(34)
        box.addWidget(self.slate, 1)
        return page

    def _build_picks_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 8, 0, 0)

        row = QHBoxLayout()
        row.addWidget(QLabel("Player"))
        self.player_picker = QComboBox()
        self.player_picker.setMinimumWidth(220)
        self.player_picker.currentIndexChanged.connect(lambda _: self._load_player())
        row.addWidget(self.player_picker)
        row.addStretch(1)
        self.player_status = QLabel("")
        self.player_status.setObjectName("Muted")
        row.addWidget(self.player_status)
        box.addLayout(row)

        self.picks = QTableWidget(GAMES_PER_WEEK, 2)
        self.picks.setHorizontalHeaderLabels(["Game", "Pick"])
        self.picks.verticalHeader().setVisible(False)
        self.picks.setAlternatingRowColors(True)
        self.picks.setShowGrid(False)
        self.picks.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        picks_header = self.picks.horizontalHeader()
        picks_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        picks_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self._pick_fields: list[QComboBox] = []
        for r in range(GAMES_PER_WEEK):
            label = QTableWidgetItem("")
            label.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.picks.setItem(r, 0, label)
            pick = QComboBox()
            pick.currentIndexChanged.connect(self._mark_dirty)
            self.picks.setCellWidget(r, 1, pick)
            self._pick_fields.append(pick)
        self.picks.verticalHeader().setDefaultSectionSize(32)
        box.addWidget(self.picks, 1)

        extras = QHBoxLayout()
        extras.addWidget(QLabel("Big loser picks"))
        self._loser_fields: list[QLineEdit] = []
        for _ in range(BIG_LOSER_PICKS):
            field = QLineEdit()
            # A slot reads "1" once that pick came in, which is how the sheet
            # marks a big-loser win; editing must not silently discard it.
            field.setPlaceholderText("team, or 1 if it won")
            field.textChanged.connect(self._mark_dirty)
            extras.addWidget(field)
            self._loser_fields.append(field)
        extras.addSpacing(16)
        extras.addWidget(QLabel("Suicide pick"))
        self.suicide_field = QLineEdit()
        self.suicide_field.setPlaceholderText("team, or DEAD once eliminated")
        self.suicide_field.textChanged.connect(self._mark_dirty)
        extras.addWidget(self.suicide_field)
        box.addLayout(extras)
        return page

    # ---- populating -----------------------------------------------------
    def set_season(self, season: Season) -> None:
        self.season = season
        weeks = sorted(season.weeks) or [1]
        current = self.week_picker.currentData()
        self.week_picker.blockSignals(True)
        self.week_picker.clear()
        for w in weeks:
            self.week_picker.addItem(f"Week {w}", w)
        if current in weeks:
            self.week_picker.setCurrentIndex(weeks.index(current))
        elif season.current_week in weeks:
            self.week_picker.setCurrentIndex(weeks.index(season.current_week))
        self.week_picker.blockSignals(False)

        names = [p.display for p in season.ordered_players()]
        chosen = self.player_picker.currentText()
        self.player_picker.blockSignals(True)
        self.player_picker.clear()
        self.player_picker.addItems(names)
        if chosen in names:
            self.player_picker.setCurrentIndex(names.index(chosen))
        self.player_picker.blockSignals(False)

        self.load_week()

    def load_week(self) -> None:
        """Reload every field from the workbook, discarding pending edits."""
        season = self.season
        if season is None or not self.week_picker.count():
            return
        self._loading = True
        try:
            self._week = self.week_picker.currentData()
            self._pending_players.clear()
            self._loaded_player = ""
            week = season.weeks.get(self._week)
            games = {g.index: g for g in (week.games if week else [])}

            for row in range(GAMES_PER_WEEK):
                game = games.get(row + 1)
                self._home_fields[row].setText(game.home if game else "")
                self._away_fields[row].setText(game.away if game else "")
                self._refresh_winner_options(row, select=game.winner if game else "")

            counted = (week.game_count if week else 0) or len(games)
            self.game_count.setValue(min(counted, GAMES_PER_WEEK))

            writable = season.workbook_path is not None
            for button in (self.save_btn, self.preview_btn, self.revert_btn):
                button.setEnabled(writable)
            if writable:
                entered = sum(1 for g in games.values() if g.played)
                self.status.setText(
                    f"{len(games)} games · {entered} result(s) entered · "
                    f"writing to {season.workbook_path.name}"
                )
            else:
                self.status.setText("No workbook loaded - nothing to write to.")

            self._load_player()
        finally:
            self._loading = False
        self._mark_dirty()

    def _refresh_winner_options(self, row: int, select: str | None = None) -> None:
        """Rebuild a winner list from the row's current team names."""
        combo = self._winner_fields[row]
        keep = select if select is not None else (combo.currentData() or "")
        original = combo.property("original")
        was_loading, self._loading = self._loading, True
        try:
            _select_team(
                combo, keep,
                [self._away_fields[row].text(), self._home_fields[row].text()],
            )
            combo.setItemText(0, NO_RESULT)
            # Only a reload re-baselines what the workbook holds; retyping a
            # team name must not make a pending change look already saved.
            if select is None and original is not None:
                combo.setProperty("original", original)
        finally:
            self._loading = was_loading
        if not self._loading:
            self._mark_dirty()

    def _load_player(self) -> None:
        season, week_no = self.season, self._week
        if season is None or week_no is None:
            return
        self._stash_current_player()
        was_loading, self._loading = self._loading, True
        try:
            player = season.by_display(self.player_picker.currentText())
            week = season.weeks.get(week_no)
            line = week.lines.get(player.key) if week and player else None
            games = {g.index: g for g in (week.games if week else [])}

            for row in range(GAMES_PER_WEEK):
                game = games.get(row + 1)
                item = self.picks.item(row, 0)
                item.setText(f"{row + 1}.  {game.label}" if game else f"{row + 1}.  –")
                current = line.correct_picks.get(row + 1, "") if line else ""
                _select_team(
                    self._pick_fields[row], current,
                    [game.away, game.home] if game else [],
                )

            # Edit the cells as they really are, so a win marker survives a
            # change to a neighbouring slot.
            losers = list(line.big_loser_raw) if line else ["", "", ""]
            for i, field in enumerate(self._loser_fields):
                value = losers[i] if i < len(losers) else ""
                field.setText(value)
                field.setProperty("original", value)

            suicide = line.suicide_pick if line else ""
            if line is not None and line.suicide_out:
                suicide = "DEAD"
            self.suicide_field.setText(suicide)
            self.suicide_field.setProperty("original", suicide)

            self._loaded_player = self.player_picker.currentText()
            # Returning to a player must show the edits they already have
            # pending, not the workbook values those edits replace.
            self._restore_stashed(self._loaded_player)
            if line is None:
                self.player_status.setText("This player has no row on the week sheet.")
            else:
                self.player_status.setText(
                    f"{line.total_wins} win(s) recorded · "
                    f"{line.big_loser_wins} big-loser win(s)"
                )
        finally:
            self._loading = was_loading
        if not self._loading:
            self._mark_dirty()

    # ---- change tracking --------------------------------------------
    def _mark_dirty(self, *_) -> None:
        if self._loading:
            return
        changes = self._collect()
        players = {c[2] for c in changes if c[0] in {"pick", "losers", "suicide"}}
        if not changes:
            text = "No changes"
        else:
            text = f"{len(changes)} pending change(s)"
            if len(players) > 1:
                text += f" across {len(players)} players"
        self.pending_label.setText(text)
        self.save_btn.setEnabled(
            bool(changes)
            and self.season is not None
            and self.season.workbook_path is not None
        )

    def _collect(self) -> list[tuple]:
        """Every field that differs from what the workbook holds.

        Each entry is (kind, *arguments) so the caller can both describe the
        change and apply it without re-deriving anything.
        """
        season, week = self.season, self._week
        if season is None or week is None:
            return []
        changes: list[tuple] = []

        stored = {g.index: g for g in (season.weeks[week].games if week in season.weeks else [])}
        for row in range(GAMES_PER_WEEK):
            game = stored.get(row + 1)
            home = self._home_fields[row].text().strip()
            away = self._away_fields[row].text().strip()
            if home != (game.home if game else "") or away != (game.away if game else ""):
                changes.append(("matchup", week, row + 1, home, away))
            combo = self._winner_fields[row]
            winner = combo.currentData() or ""
            if winner != (combo.property("original") or ""):
                changes.append(("result", week, row + 1, winner))

        counted = season.weeks[week].game_count if week in season.weeks else 0
        if self.game_count.value() != (counted or len(stored)):
            changes.append(("game_count", week, self.game_count.value()))

        current = self._loaded_player
        for player, stashed in self._pending_players.items():
            if player != current:
                changes.extend(stashed)
        if current:
            changes.extend(self._player_changes(current))
        return changes

    def _player_changes(self, player: str) -> list[tuple]:
        """Edits to the player whose picks are on screen right now."""
        week = self._week
        if week is None or not player:
            return []
        changes: list[tuple] = []
        for row in range(GAMES_PER_WEEK):
            combo = self._pick_fields[row]
            value = combo.currentData() or ""
            if value != (combo.property("original") or ""):
                changes.append(("pick", week, player, row + 1, value))

        losers = [f.text().strip() for f in self._loser_fields]
        originals = [(f.property("original") or "") for f in self._loser_fields]
        if losers != originals:
            changes.append(("losers", week, player, losers))

        suicide = self.suicide_field.text().strip()
        if suicide != (self.suicide_field.property("original") or ""):
            changes.append(("suicide", week, player, suicide))
        return changes

    def _restore_stashed(self, player: str) -> None:
        """Re-apply a player's held edits over the freshly loaded values.

        Only the widget selections are changed; each field's recorded original
        stays at what the workbook holds, so the edit is still seen as pending.
        """
        for change in self._pending_players.get(player, []):
            kind = change[0]
            if kind == "pick":
                combo = self._pick_fields[change[3] - 1]
                value = change[4]
                index = combo.findData(value)
                if index < 0 and value:
                    combo.addItem(value, value)
                    index = combo.findData(value)
                combo.setCurrentIndex(index if index >= 0 else 0)
            elif kind == "losers":
                for field, value in zip(self._loser_fields, change[3]):
                    field.setText(value)
            elif kind == "suicide":
                self.suicide_field.setText(change[3])

    def _stash_current_player(self) -> None:
        """Hold the on-screen player's edits before another one is loaded."""
        player = self._loaded_player
        if not player:
            return
        live = self._player_changes(player)
        if live:
            self._pending_players[player] = live
        else:
            self._pending_players.pop(player, None)

    def _build_editor(self) -> tuple[WorkbookEditor | None, list[tuple]]:
        changes = self._collect()
        season = self.season
        if not changes or season is None or season.workbook_path is None:
            return None, changes
        editor = WorkbookEditor(season.workbook_path)
        for change in changes:
            kind = change[0]
            if kind == "matchup":
                editor.set_matchup(change[1], change[2], change[3], change[4])
            elif kind == "result":
                editor.set_result(change[1], change[2], change[3])
            elif kind == "game_count":
                editor.set_game_count(change[1], change[2])
            elif kind == "pick":
                editor.set_pick(change[1], change[2], change[3], change[4])
            elif kind == "losers":
                editor.set_big_loser_picks(change[1], change[2], change[3])
            elif kind == "suicide":
                editor.set_suicide_pick(change[1], change[2], change[3])
        return editor, changes

    # ---- actions ------------------------------------------------------
    def preview(self) -> None:
        try:
            editor, changes = self._build_editor()
        except WriteBackError as exc:
            QMessageBox.warning(self, "Cannot prepare the change", str(exc))
            return
        if not changes:
            QMessageBox.information(self, "No changes", "Nothing has been changed yet.")
            return
        result = editor.apply(dry_run=True)
        lines = [
            f"{e.address}   {e.description}   →   {e.value or '(cleared)'}"
            for e in result.applied
        ]
        for edit, reason in result.refused:
            lines.append(f"REFUSED  {edit.address}: {reason}")
        QMessageBox.information(self, "Pending changes", "\n".join(lines))

    def save(self) -> None:
        season = self.season
        try:
            editor, changes = self._build_editor()
        except WriteBackError as exc:
            QMessageBox.warning(self, "Cannot prepare the change", str(exc))
            return
        if not changes:
            QMessageBox.information(self, "No changes", "Nothing has been changed yet.")
            return

        confirm = QMessageBox.question(
            self,
            "Write to the workbook?",
            f"{len(changes)} change(s) for week {self._week} will be written to\n"
            f"{season.workbook_path.name}.\n\n"
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
                self, "Could not save",
                "The workbook is open in Excel. Close it and try again.",
            )
            return
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", f"Writing failed: {exc}")
            return

        if result.refused:
            QMessageBox.warning(
                self, "Nothing was written",
                "These cells were protected and the save was abandoned:\n\n"
                + "\n".join(reason for _, reason in result.refused),
            )
            return

        self._pending_players.clear()
        QMessageBox.information(
            self, "Saved",
            f"{result.summary()}.\n\n"
            "Open the workbook in Excel so it recalculates wins, ranks and "
            "payouts, save it there, then press Refresh.",
        )
        self.saved.emit()
