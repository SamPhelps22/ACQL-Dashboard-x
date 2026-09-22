"""Next week's slate: a pick for every game, with the pool's lines applied.

The page is a worksheet as much as a prediction: type (or paste) the Vegas
spread for each game and every row answers three questions at once - who the
model takes once the pool's line is applied, how sure it is, and the biggest
pool line the favourite would still be worth backing at.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ... import analytics, lines
from ...config import WEEKS_IN_SEASON
from ...models import Game
from ..widgets import Card, StatTile, section
from .base import Page

HEADERS = [
    "#", "Matchup", "Pool line", "Vegas favourite", "Spread",
    "Fav up to", "Pick", "Chance", "Why",
]
(COL_NUM, COL_MATCH, COL_LINE, COL_FAV, COL_SPREAD,
 COL_UPTO, COL_PICK, COL_CHANCE, COL_WHY) = range(9)

CONFIDENT = 0.60          # picks at or above this are shown as strong
NO_SPREAD = "—"

RULE = (
    "On a lined game the favourite has to win by MORE than the line - a win by "
    "exactly the line goes to the underdog. Enter the Vegas favourite and spread "
    "for each game (or paste a block of odds); the pick takes the Vegas favourite "
    "on straight-up games, and on lined games works out how often that spread "
    "actually clears the pool's number. \"Fav up to\" is the biggest pool line the "
    "Vegas favourite would still be worth backing at - handy before the "
    "commissioner posts one. Chances come from how often NFL games really land on "
    "each margin, so 3, 7 and 10 count for more than the numbers either side."
)

PLACEHOLDER = (
    "Paste odds here, one game per line - most sportsbook and scores pages "
    "copy out in a shape this can read:\n\n"
    "Bengals -3.5 at Steelers\n"
    "ATL @ GB | GB -7 (-110)\n"
    "Eagles -4 at Chicago Bears\n"
    "Falcons +6.5 Panthers"
)

STALE_MODELS = (
    "This copy of the app has an older models.py, which has no place to keep a "
    "game's pool line - so the \"(phi by 8)\" notes can't be read and every game "
    "is treated as straight up. Copy the new models.py over acql/models.py and "
    "restart to get the lined-game picks back."
)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _same(a: object, b: object) -> bool:
    """Two team names that mean the same team, whatever the spacing or case."""
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold() != ""


class OddsDialog(QDialog):
    """A scratchpad for a block of odds copied off a website."""

    def __init__(self, week: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Paste Week {week} odds")
        self.setMinimumSize(560, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        blurb = QLabel(
            "Every line that names one of this week's matchups and carries a "
            "spread is read; moneylines, totals and the odds in brackets are "
            "ignored. Anything that can't be read is listed afterwards, and "
            "games already filled in are only overwritten when the paste "
            "covers them."
        )
        blurb.setObjectName("Muted")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(PLACEHOLDER)
        self.editor.setTabChangesFocus(True)
        layout.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Read odds")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.editor.toPlainText()


class NextWeekPage(Page):
    title = "Next Week"
    subtitle = "A pick for every game on the slate, with your pool's lines applied"
    icon = "\N{AMERICAN FOOTBALL}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self._games: list[Game] = []
        self._loading = False
        self._user_chose_week = False

        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Week"))
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(140)
        for number in range(1, WEEKS_IN_SEASON + 1):
            self.week_picker.addItem(f"Week {number}", number)
        self.week_picker.currentIndexChanged.connect(lambda _: self._on_week_chosen())
        controls.addWidget(self.week_picker)

        self.paste_button = QPushButton("Paste odds…")
        self.paste_button.setToolTip(
            "Fill the whole slate at once from a block of odds copied off a website"
        )
        self.paste_button.clicked.connect(self._paste_odds)
        controls.addWidget(self.paste_button)

        self.clear_button = QPushButton("Clear spreads")
        self.clear_button.setToolTip("Empty every spread on this week's slate")
        self.clear_button.clicked.connect(self._clear_spreads)
        controls.addWidget(self.clear_button)

        controls.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        controls.addWidget(self.status)
        self.layout_.addLayout(controls)

        self.stale_note = QLabel(STALE_MODELS)
        self.stale_note.setObjectName("Muted")
        self.stale_note.setWordWrap(True)
        self.stale_note.setVisible("line" not in getattr(Game, "__dataclass_fields__", {}))
        self.layout_.addWidget(self.stale_note)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_slate = StatTile("Slate")
        self.tile_expected = StatTile("Expected Wins")
        self.tile_best = StatTile("Best Bet")
        self.tile_dogs = StatTile("Underdogs vs the Line")
        self._tiles = (self.tile_slate, self.tile_expected, self.tile_best, self.tile_dogs)
        for tile in self._tiles:
            tiles.addWidget(tile, 2 if tile is self.tile_best else 1)
        self.layout_.addLayout(tiles)

        self.card = Card("Picks")
        self.empty_note = QLabel("")
        self.empty_note.setObjectName("Muted")
        self.empty_note.setWordWrap(True)
        self.card.add(self.empty_note)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        for col in range(len(HEADERS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_WHY, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeaderItem(COL_UPTO).setToolTip(
            "The biggest whole-number pool line the Vegas favourite is still "
            "worth taking at - one point more and the underdog is the better side"
        )
        self.table.setMinimumHeight(420)
        self.card.add(self.table, 1)

        self.paste_note = QLabel("")
        self.paste_note.setObjectName("Muted")
        self.paste_note.setWordWrap(True)
        self.paste_note.hide()
        self.card.add(self.paste_note)

        self.rule = QLabel(RULE)
        self.rule.setObjectName("Muted")
        self.rule.setWordWrap(True)
        self.card.add(self.rule)
        self.layout_.addWidget(self.card, 1)

    def restyle(self) -> None:
        # Pick colours come from the palette, so the rows are redrawn.
        self.refresh_now()

    # ---- week selection -------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        # Follow the season to the upcoming week unless someone has chosen
        # a week themselves; then leave their choice alone across refreshes.
        if not self._user_chose_week:
            self._set_week(analytics.upcoming_week(season))
        self._show_week()

    def _set_week(self, number: int) -> None:
        index = self.week_picker.findData(number)
        if index >= 0:
            self.week_picker.blockSignals(True)
            self.week_picker.setCurrentIndex(index)
            self.week_picker.blockSignals(False)

    def _on_week_chosen(self) -> None:
        if self.season is None:
            return
        self._user_chose_week = True
        self._show_week()

    @property
    def _week_number(self) -> int:
        return int(self.week_picker.currentData())

    # ---- the table --------------------------------------------------------
    def _show_week(self) -> None:
        season = self.season
        if season is None:
            return
        number = self._week_number
        week = season.weeks.get(number)
        self._games = sorted(week.games, key=lambda g: g.index) if week else []
        spreads = lines.load_spreads(number, self._games)
        self.paste_note.hide()

        dogs, decided = analytics.underdog_record(season)
        if decided:
            self.tile_dogs.update_values(
                f"{dogs}/{decided}", "lined games the underdog won this season",
                "good" if dogs * 2 > decided else "",
            )
        else:
            self.tile_dogs.update_values(self.NO_VALUE, "no lined games decided yet")

        self._loading = True
        try:
            self.table.setRowCount(0)
            if not self._games:
                self._show_blank(number)
                return
            self.empty_note.hide()
            self.table.show()
            self.table.setRowCount(len(self._games))
            for row, game in enumerate(self._games):
                self._fill_row(row, game, spreads.get(game.index))
        finally:
            self._loading = False

        self.card.set_title(f"Week {number} picks")
        self._update_tiles()

    def _show_blank(self, number: int) -> None:
        self.table.hide()
        self.empty_note.setText(
            f"Week {number}'s slate isn't in the workbook yet. Once the teams "
            f"(and any lines, like \"(phi by 8)\" in row 8) are typed into the "
            f"Week {number} sheet and saved, press Refresh and the games appear here."
        )
        self.empty_note.show()
        self.status.setText("")
        self.card.set_title(f"Week {number} picks")
        for tile in (self.tile_slate, self.tile_expected, self.tile_best):
            tile.update_values(self.NO_VALUE, "slate not entered yet")
        for button in (self.paste_button, self.clear_button):
            button.setEnabled(False)

    def _fill_row(self, row: int, game: Game, spread: lines.Spread | None) -> None:
        def item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
            cell = QTableWidgetItem(text)
            cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
            cell.setTextAlignment(int(align | Qt.AlignmentFlag.AlignVCenter))
            return cell

        line = getattr(game, "line", None)
        self.table.setItem(row, COL_NUM, item(str(game.index), Qt.AlignmentFlag.AlignRight))
        self.table.setItem(row, COL_MATCH, item(f"{game.away} @ {game.home}"))
        self.table.setItem(
            row, COL_LINE,
            item(f"{game.line_favourite} by {line:g}" if line is not None else "straight up"),
        )
        if line is None:
            self.table.item(row, COL_LINE).setForeground(QColor(self.palette.ink_muted))

        favourite = QComboBox()
        favourite.addItem("— choose —", None)
        favourite.addItem(game.away, "away")
        favourite.addItem(game.home, "home")
        points = QDoubleSpinBox()
        points.setRange(0.0, 40.0)
        points.setSingleStep(0.5)
        points.setDecimals(1)
        if spread is not None:
            favourite.setCurrentIndex(favourite.findData(spread.favourite))
            points.setValue(spread.points)
        favourite.currentIndexChanged.connect(lambda _, r=row: self._on_input(r))
        points.valueChanged.connect(lambda _, r=row: self._on_input(r))
        self.table.setCellWidget(row, COL_FAV, favourite)
        self.table.setCellWidget(row, COL_SPREAD, points)
        self._render_row(row)

    def _inputs(self, row: int) -> tuple[str | None, float]:
        favourite = self.table.cellWidget(row, COL_FAV)
        points = self.table.cellWidget(row, COL_SPREAD)
        return favourite.currentData(), float(points.value())

    def _on_input(self, row: int) -> None:
        if self._loading or not 0 <= row < len(self._games):
            return
        side, points = self._inputs(row)
        game = self._games[row]
        lines.save_spread(
            self._week_number, game, lines.Spread(side, points) if side else None
        )
        self._render_row(row)
        self._update_tiles()

    def _prediction(self, row: int) -> analytics.Prediction | None:
        side, points = self._inputs(row)
        return analytics.predict(self._games[row], side, points if side else None)

    # ---- "fav up to" -------------------------------------------------------
    def _threshold(self, row: int) -> tuple[str, str, str]:
        """(cell text, tooltip, colour) for the biggest line worth backing at.

        Worked from the pool's favourite when the game carries a line, so the
        number answers the question actually being asked - is the pool's number
        too big? - and from the Vegas favourite otherwise.
        """
        side, points = self._inputs(row)
        game = self._games[row]
        if side is None:
            return "", "", self.palette.ink_muted

        line = getattr(game, "line", None)
        if line is not None:
            team = getattr(game, "line_favourite", "") or game.home
            backing_home = _same(team, game.home)
        else:
            backing_home = side == "home"
            team = game.home if backing_home else game.away
        margin = points if (side == "home") == backing_home else -points

        if analytics.win_chance(margin) <= 0.5:
            return (
                NO_SPREAD,
                f"Vegas doesn't have {team} winning this outright, so they're "
                f"not worth backing at any pool line.",
                self.palette.serious,
            )

        best = analytics.line_threshold(margin)
        tip = (
            f"Take {team} at a pool line up to {best}; at {best + 1} the "
            f"underdog becomes the better side."
            if best else
            f"{team} are only worth taking straight up - at any pool line the "
            f"underdog is the better side."
        )
        if line is None:
            return str(best), tip, self.palette.ink
        inside = best >= line
        tip += (
            f"\nThe pool's line is {line:g}, "
            + ("inside that, so the favourite is the side to take."
               if inside else "past that, so the underdog is the side to take.")
        )
        colour = self.palette.good if inside else self.palette.ink_muted
        return f"{best:g}", tip, colour

    # ---- drawing a row ------------------------------------------------------
    def _render_row(self, row: int) -> None:
        game = self._games[row]
        guess = self._prediction(row)
        result = f"Result: {game.winner}. " if game.played else ""
        if guess is None:
            pick, chance, why = "enter the spread", "", result
            colour = self.palette.ink_muted
        else:
            pick = guess.pick
            chance = f"{guess.chance:.0%}" + (" · coin flip" if guess.coin_flip else "")
            why = result + guess.reason
            colour = (
                self.palette.ink_muted if guess.coin_flip
                else self.palette.good if guess.chance >= CONFIDENT
                else self.palette.ink
            )
        upto, tip, upto_colour = self._threshold(row)
        cells = {
            COL_UPTO: QTableWidgetItem(upto),
            COL_PICK: QTableWidgetItem(pick),
            COL_CHANCE: QTableWidgetItem(chance),
            COL_WHY: QTableWidgetItem(why),
        }
        bold = QFont()
        bold.setBold(True)
        for col, cell in cells.items():
            cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if col in (COL_PICK, COL_CHANCE):
                cell.setForeground(QColor(colour))
            if col == COL_UPTO:
                cell.setForeground(QColor(upto_colour))
                cell.setToolTip(tip)
                cell.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                )
            if col == COL_PICK and guess is not None:
                cell.setFont(bold)
            if col == COL_CHANCE:
                cell.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                )
            self.table.setItem(row, col, cell)

    # ---- filling the slate in bulk -----------------------------------------
    def _paste_odds(self) -> None:
        if not self._games:
            return
        dialog = OddsDialog(self._week_number, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        found, notes = lines.parse_odds_text(dialog.text(), self._games)
        self._apply_spreads(found)

        read = _plural(len(found), "game")
        missing = [
            f"{g.away} @ {g.home}" for g in self._games if g.index not in found
        ]
        parts = [f"Read {read} out of {len(self._games)}."]
        if missing:
            parts.append(
                "Still to fill in: " + ", ".join(missing[:6])
                + (f" and {len(missing) - 6} more" if len(missing) > 6 else "") + "."
            )
        parts.extend(notes[:4])
        self.paste_note.setText(" ".join(parts))
        self.paste_note.show()

    def _apply_spreads(self, found: dict[int, lines.Spread]) -> None:
        """Fill in every game the paste covered, saving as it goes."""
        self._loading = True
        try:
            for row, game in enumerate(self._games):
                spread = found.get(game.index)
                if spread is None:
                    continue
                favourite = self.table.cellWidget(row, COL_FAV)
                points = self.table.cellWidget(row, COL_SPREAD)
                index = favourite.findData(spread.favourite)
                if index < 0:
                    continue
                favourite.setCurrentIndex(index)
                points.setValue(abs(spread.points))
                lines.save_spread(
                    self._week_number, game,
                    lines.Spread(spread.favourite, abs(spread.points)),
                )
        finally:
            self._loading = False
        for row in range(len(self._games)):
            self._render_row(row)
        self._update_tiles()

    def _clear_spreads(self) -> None:
        self._loading = True
        try:
            for row, game in enumerate(self._games):
                self.table.cellWidget(row, COL_FAV).setCurrentIndex(0)
                self.table.cellWidget(row, COL_SPREAD).setValue(0.0)
                lines.save_spread(self._week_number, game, None)
        finally:
            self._loading = False
        self.paste_note.hide()
        for row in range(len(self._games)):
            self._render_row(row)
        self._update_tiles()

    # ---- the headline numbers ----------------------------------------------
    def _update_tiles(self) -> None:
        games = self._games
        for button in (self.paste_button, self.clear_button):
            button.setEnabled(bool(games))
        lined = sum(1 for g in games if getattr(g, "line", None) is not None)
        guesses = [self._prediction(row) for row in range(len(games))]
        outlook = analytics.slate_outlook(guesses)

        self.status.setText(
            f"{_plural(len(games), 'game')} · {lined} with a pool line"
        )
        self.tile_slate.update_values(
            f"{outlook.priced}/{len(games)}",
            f"spreads entered · {lined} of these carry a pool line"
            if outlook.priced < len(games) else
            f"spreads in · {lined} carry a pool line",
            "good" if games and outlook.priced == len(games) else "",
        )

        if not outlook.priced:
            for tile in (self.tile_expected, self.tile_best):
                tile.update_values(self.NO_VALUE, "enter some spreads to see picks")
            return

        self.tile_expected.update_values(
            f"{outlook.expected:.1f}",
            f"picks expected to land from the {_plural(outlook.priced, 'game')} "
            f"priced · {outlook.strong} strong, "
            f"{_plural(outlook.coin_flips, 'coin flip')}",
            "good" if outlook.priced and outlook.expected / outlook.priced >= 0.6 else "",
        )

        entered = [(row, g) for row, g in enumerate(guesses) if g is not None]
        row, best = max(entered, key=lambda rg: (rg[1].chance, -rg[0]))
        game = games[row]
        self.tile_best.update_values(
            best.pick,
            f"{best.chance:.0%} · {game.away} @ {game.home}"
            + (f"\nagainst the line: {best.reason}" if best.against_line else ""),
            "good",
        )