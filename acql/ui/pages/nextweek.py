"""Next week's slate: a pick for every game, with the pool's lines applied.

The page is a worksheet as much as a prediction. Drop the week's predictions
file in beside the workbook and every game arrives with the betting line and
a few dozen computer models' opinion of it already filled in; otherwise the
spreads can be pasted in or typed. Each row then answers three questions at
once - who to take once the pool's line is applied, how sure that is, and
the biggest pool line the favourite would still be worth backing at.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ... import analytics, lines, picks, predictions, pricing, schedule, weekplan
from ...config import BIG_LOSER_PICKS, WEEKS_IN_SEASON
from ...models import Game
from ..widgets import Card, ColumnFitter, StatTile, fit_height, section
from .base import Page

HEADERS = [
    "#", "Matchup", "Pool line", "Favourite", "Spread", "Current line",
    "Models", "Fav up to", "Pick", "Chance", "Vs pool %", "Why",
]
(COL_NUM, COL_MATCH, COL_LINE, COL_FAV, COL_SPREAD, COL_NOW,
 COL_MODELS, COL_UPTO, COL_PICK, COL_CHANCE, COL_EDGE, COL_WHY) = range(12)

CONFIDENT = 0.60          # picks at or above this are shown as strong
NOTABLE_EDGE = 2.0        # models this far from the book are worth noticing
WORTH_LEVERAGE = 0.10     # a pick worth this much on the field is a week-winner
LIKELY_LINED = 6.0        # the commissioner lines the games bigger than this
#: Every row of the picks table is this tall; the favourite and spread boxes
#: sit inside it with a few pixels of margin (see the theme).
ROW_HEIGHT = 40
LOSER_ROW_HEIGHT = 32
#: The input columns never shrink below what their boxes need.
CONTROL_WIDTH = {3: 170, 4: 84}
PLAN_MINIMUM = 6          # games priced before planning a whole card is worth it
GRADED_ENOUGH = 40        # graded picks before the record says anything
NO_SPREAD = "—"

RULE = (
    "On a lined game the favourite has to win by MORE than the line - a win by "
    "exactly the line goes to the underdog. Chances come from how often NFL "
    "games really land on each margin, so 3, 7 and 10 count for more than the "
    "numbers either side. \"Spread\" starts from the predictions file's opening "
    "line, which is the number the commissioner sets his own against; "
    "\"Current line\" is where the market has got to since, and a game that has "
    "moved three points or more is worth a second look. "
    "\"Models\" is how many points the computer models like "
    "the favourite more (or less) than the bookmakers do, once two things are "
    "taken out: the lean every game on the slate shares, and any disagreement "
    "the market has already moved against since the line opened, which is "
    "usually news the models never saw. A third of what is left goes into the "
    "pick, and the further apart the models are, the closer to a coin flip "
    "every chance moves. \"Fav up to\" is the biggest "
    "pool line the favourite would still be worth backing at - handy before the "
    "commissioner posts one. \"Vs pool\" is what the pick is worth against "
    "everyone else: being right when the whole pool is right wins nothing, so "
    "it is the chance of being right less the share of the pool expected to be "
    "on the same side. That is where weeks are won."
)

MODELS_PLACEHOLDER = (
    "Paste the summary table from The Prediction Tracker - the block with a "
    "row per game and the two lines, the model average and median, the "
    "standard deviation and the two probabilities:\n\n"
    "Green Bay      Atlanta       6.50   5.00   .   7.50   6.79   4.31  0.49 18.26  0.6995 0.5501\n"
    "Buffalo        LA Chargers   4.00   7.00   .  10.36   8.25   4.98  3.95 23.50  0.7617 0.5667"
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

LOSER_HEADERS = ["Take", "Team", "Game", "Line", "Beaten by 15+", "Pool", "Why"]
(LOSER_TAKE, LOSER_TEAM, LOSER_GAME, LOSER_LINE, LOSER_CHANCE, LOSER_POOL,
 LOSER_WHY) = range(7)
LOSER_ROWS = 8            # more than three, so there is something to choose from

BIG_LOSER_RULE = (
    "Three picks a week, a point each, and they add straight onto your record "
    "- so they are worth the same as three more games. A big loser has to lose "
    "by MORE than 14, and the pool's lines have nothing to do with it, so this "
    "is the raw Vegas number asking how often a beating of 15 or more happens. "
    "The top three are marked; the rest are here because a game you know "
    "something about beats a number by a point or two. \"Pool\" is how many "
    "coaches already have that team, once their pick sheet is loaded - the "
    "same arithmetic as the main pool, since a big loser everyone else has "
    "gains you nothing."
)

PLAN_RULE = (
    "Picking the likelier side of every game gets the most games right and "
    "lands you in the top five a third of the time - but it rarely wins the "
    "week, because most of the pool holds the same card and a good week is "
    "shared with them. Only first place is paid. This plays the week 20,000 "
    "times against the other coaches' cards and looks for the card most "
    "likely to finish first, which means taking a side that is less likely "
    "but far less crowded wherever that gets you clear of the pack."
)

WHERE_TO_PUT_IT = (
    "No predictions file for this week yet. Save the week's CSV next to the "
    "workbook (or leave it in Downloads) with the week in its name - "
    "\"nflpredictions_week_3.csv\" - and press Refresh; it is picked up from "
    "then on. Load predictions… takes one from anywhere."
)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _same(a: object, b: object) -> bool:
    """Two team names that mean the same team, whatever the spacing or case."""
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold() != ""


class OddsDialog(QDialog):
    """A scratchpad for a block of text copied off a website.

    Two things get pasted here - a list of odds, and The Prediction Tracker's
    summary table - so the words belong to whoever opens it.
    """

    def __init__(
        self,
        week: int,
        parent=None,
        *,
        title: str = "",
        blurb: str = "",
        placeholder: str = "",
        button: str = "Read odds",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or f"Paste Week {week} odds")
        self.setMinimumSize(560, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        note = QLabel(blurb or (
            "Every line that names one of this week's matchups and carries a "
            "spread is read; moneylines, totals and the odds in brackets are "
            "ignored. Anything that can't be read is listed afterwards, and "
            "games already filled in are only overwritten when the paste "
            "covers them."
        ))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(placeholder or PLACEHOLDER)
        self.editor.setTabChangesFocus(True)
        layout.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(button)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.editor.toPlainText()


class NextWeekPage(Page):
    title = "Every Game"
    subtitle = "A pick for every game on the slate, with your pool's lines applied"
    icon = "\N{AMERICAN FOOTBALL}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self._games: list[Game] = []
        self._typed: dict[int, bool] = {}
        self._typical = 0.0
        self._weight = predictions.CONSENSUS_WEIGHT
        self._fitted: predictions.WeightFit | None = None
        self._forecasts: dict[int, predictions.Forecast] = {}
        self._ctx = pricing.Context(0)
        self._picks: picks.WeekPicks | None = None
        self._lean = 0.0
        self._chalk, self._chalk_games = analytics.CHALK_PRIOR, 0
        self._from_file = False
        self._from_schedule = False
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

        self.load_button = QPushButton("Load predictions…")
        self.load_button.setToolTip(
            "Read a week's predictions CSV - the betting line and every model's "
            "number for each game"
        )
        self.load_button.clicked.connect(self._load_predictions)
        controls.addWidget(self.load_button)

        self.models_button = QPushButton("Paste models…")
        self.models_button.setToolTip(
            "Paste The Prediction Tracker's summary table: both lines, the "
            "models' median and how far apart they are, in one go"
        )
        self.models_button.clicked.connect(self._paste_models)
        controls.addWidget(self.models_button)

        self.paste_button = QPushButton("Paste odds…")
        self.paste_button.setToolTip(
            "Fill the slate from a block of odds copied off a website"
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

        self.source_note = QLabel("")
        self.source_note.setObjectName("Muted")
        self.source_note.setWordWrap(True)
        self.layout_.addWidget(self.source_note)

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
        self.tile_edge = StatTile("Best Leverage")
        self.tile_dogs = StatTile("Underdogs vs the Line")
        self._tiles = (self.tile_slate, self.tile_expected, self.tile_best,
                       self.tile_edge, self.tile_dogs)
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
        # One height for every row. "Why" used to wrap onto as many lines as
        # its sentence needed, and with the columns to its left taking the
        # width that was a dozen lines - rows 180 pixels tall, with the
        # favourite and spread boxes stretched to match. The sentence is now
        # cut to the column and whole in the tooltip.
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.verticalHeader().setMinimumSectionSize(ROW_HEIGHT)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(48)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_WHY, QHeaderView.ResizeMode.Stretch)
        self._fitter = ColumnFitter(self.table, COL_WHY)
        self.table.horizontalHeaderItem(COL_SPREAD).setToolTip(
            "Filled from the predictions file's opening line - the number that "
            "was up when the commissioner set his own. Type over it to change it."
        )
        self.table.horizontalHeaderItem(COL_NOW).setToolTip(
            "The same game's line as it stands now. Where it has moved a long "
            "way from the opener, the market has heard something - hover a row "
            "to see which way and by how much."
        )
        self.table.horizontalHeaderItem(COL_MODELS).setToolTip(
            "How many points the computer models like the favourite more than "
            "the bookmakers do - hover a row for who says what"
        )
        self.table.horizontalHeaderItem(COL_EDGE).setToolTip(
            "How much more likely this pick is to land than the average card is "
            "on this game: the chance of being right, less the share of the pool "
            "expected to take the same side. +32% is a third of a game gained on "
            "everyone else, not 32 points of anything."
        )
        self.table.horizontalHeaderItem(COL_UPTO).setToolTip(
            "The biggest whole-number pool line the favourite is still worth "
            "taking at - one point more and the underdog is the better side"
        )
        self.card.add(self.table)

        self.paste_note = QLabel("")
        self.paste_note.setObjectName("Muted")
        self.paste_note.setWordWrap(True)
        self.paste_note.hide()
        self.card.add(self.paste_note)

        self.plan_card = Card("Week plan")
        self.plan_note = QLabel(PLAN_RULE)
        self.plan_note.setObjectName("Muted")
        self.plan_note.setWordWrap(True)
        self.plan_card.add(self.plan_note)
        self.plan_body = QLabel("")
        self.plan_body.setWordWrap(True)
        self.plan_card.add(self.plan_body)

        self.losers = Card("Big Losers")
        self.losers_note = QLabel(BIG_LOSER_RULE)
        self.losers_note.setObjectName("Muted")
        self.losers_note.setWordWrap(True)
        self.losers.add(self.losers_note)
        self.losers_table = QTableWidget(0, len(LOSER_HEADERS))
        self.losers_table.setHorizontalHeaderLabels(LOSER_HEADERS)
        self.losers_table.verticalHeader().setVisible(False)
        self.losers_table.setAlternatingRowColors(True)
        self.losers_table.setShowGrid(False)
        self.losers_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.losers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.losers_table.verticalHeader().setDefaultSectionSize(LOSER_ROW_HEIGHT)
        self.losers_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.losers_table.setWordWrap(False)
        self.losers_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        loser_header = self.losers_table.horizontalHeader()
        loser_header.setMinimumSectionSize(48)
        loser_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        loser_header.setSectionResizeMode(LOSER_WHY, QHeaderView.ResizeMode.Stretch)
        self._loser_fitter = ColumnFitter(self.losers_table, LOSER_WHY)
        self.losers.add(self.losers_table)

        self.rule = QLabel(RULE)
        self.rule.setObjectName("Muted")
        self.rule.setWordWrap(True)
        self.card.add(self.rule)
        self.layout_.addWidget(self.card, 1)
        self.layout_.addWidget(self.plan_card)
        self.layout_.addWidget(self.losers, 1)

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
        sheet_games = sorted(week.games, key=lambda g: g.index) if week else []
        workbook = getattr(season, "workbook_path", None)
        # The slate goes in too, so a download whose name does not say the
        # week is still recognised by the games in it.
        forecasts, source, _ = predictions.refresh_from_disk(
            number, workbook, sheet_games
        )
        picks.refresh_from_disk(workbook)
        self._picks = picks.load(number)
        # A week the commissioner hasn't typed in yet still has a slate. The
        # predictions file has one, and failing that the league's schedule
        # does - so any week of the season can be looked at, with whatever is
        # known about it. Pool lines only ever come from the sheet.
        self._from_file = not sheet_games and bool(forecasts)
        if sheet_games:
            self._games = sheet_games
        elif forecasts:
            self._games = predictions.slate_from(forecasts)
        else:
            self._games = schedule.slate(number)
        self._from_schedule = not sheet_games and not forecasts and bool(self._games)

        # Everything pricing needs about the week, worked out the one way
        # every page shares (pricing.py): the file matched to the slate, the
        # slate's shared lean, how strung out the models normally are, and
        # how much of them this season's results say to believe.
        self._ctx = pricing.context(season, number, self._games, forecasts)
        self._forecasts = self._ctx.forecasts
        self._lean = self._ctx.lean
        self._typical = self._ctx.typical
        self._fitted = self._ctx.fitted
        self._weight = self._ctx.weight
        self._chalk, self._chalk_games = analytics.pool_chalk(season)
        self._describe_source(number, forecasts, source, self._ctx)

        spreads = lines.load_spreads(number, self._games)
        # Which rows carry a number somebody typed, as against one the file
        # supplied. A typed number is a statement about the line and is what
        # the odds are then worked out from.
        self._typed = {index: True for index in spreads}
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
            # Without a predictions file the Models column is 16 blanks, and
            # the room is better spent on the sentence at the end of the row.
            self.table.setColumnHidden(COL_MODELS, not self._forecasts)
            self.table.setColumnHidden(COL_NOW, not self._forecasts)
            self.table.setRowCount(len(self._games))
            for row, game in enumerate(self._games):
                self._fill_row(row, game, spreads.get(game.index))
            self._fit_table()
        finally:
            self._loading = False

        self.card.set_title(f"Week {number} picks")
        self._update_tiles()
        self._show_big_losers()
        self._show_plan()

    def _describe_source(self, number, forecasts, source, found) -> None:
        """Three short lines: where the numbers came from, who has picked, how it is going.

        One paragraph of everything at once is unreadable, so each source of
        truth gets its own line and each line leads with what it is about.
        """
        lines_out: list[str] = []

        if forecasts:
            where = Path(source).name if source else "a loaded file"
            first = f"Week {number} numbers \u00b7 {predictions.summary(forecasts)}"
            if self._from_file:
                first += " \u00b7 the sheet has no games for this week yet, so the "
                first += "slate is the file's and pool lines appear once it is typed in"
            elif found.missing:
                first += " \u00b7 not in the file: " + ", ".join(found.missing[:3])
                if len(found.missing) > 3:
                    first += f" and {len(found.missing) - 3} more"
            if found.flipped:
                first += (f" \u00b7 {_plural(len(found.flipped), 'game')} listed home "
                          f"and away the other way round, turned around to match")
            lines_out.append(f"{first} \u00b7 from {where}")
        elif self._from_schedule:
            off = schedule.byes(number)
            lines_out.append(
                f"Week {number} fixtures \u00b7 from the league schedule, "
                f"{_plural(len(self._games), 'game')}"
                + (f" \u00b7 on a bye: {', '.join(off)}" if off else "")
                + f" \u00b7 no predictions file yet"
            )
            lines_out.append(WHERE_TO_PUT_IT)
        else:
            lines_out.append(WHERE_TO_PUT_IT)

        if self._picks is not None:
            lines_out.append(
                f"Pick sheet \u00b7 {picks.summary(self._picks)} \u00b7 every "
                f"\"Vs pool\" figure below is counted, not estimated"
            )

        record = self._record()
        if record:
            lines_out.append(record)
        if self._fitted is not None:
            fitted = self._fitted.describe()
            if fitted:
                lines_out.append(fitted)
        self.source_note.setText("\n".join(lines_out))
        self.source_note.setToolTip(str(source or ""))

    def _record(self) -> str:
        """How these picks have done on the weeks that have a file and a result."""
        card = self._scorecard()
        if not card.picks:
            return ""
        line = (
            f"Record \u00b7 {card.straight_hits} of {card.straight_picks} picking "
            f"winners"
            + (f" \u00b7 {card.lined_hits} of {card.lined_picks} against the pool's "
               f"lines" if card.lined_picks else "")
            + f" \u00b7 {card.hits} of {card.picks} all told, against "
              f"{card.expected:.1f} expected, over {_plural(card.weeks, 'week')}"
        )
        if card.picks < GRADED_ENOUGH:
            return line + " \u00b7 too few games to read into yet"
        if card.surprise <= -3:
            return line + " \u00b7 the chances shown are running bold"
        if card.surprise >= 3:
            return line + " \u00b7 the chances shown are running shy"
        return line + " \u00b7 the chances are landing about right"

    def _scorecard(self) -> analytics.Scorecard:
        """Grade every past pick that had stored numbers behind it.

        The same replay the Insights page grades (pricing.graded_entries), so
        the two records always agree. Only weeks whose numbers were kept can
        be graded, so a season graded from week 5 onward says nothing about
        weeks 1 to 4 - it means their files were never loaded.
        """
        season = self.season
        if season is None:
            return analytics.Scorecard(0, 0, 0.0, 0)
        return analytics.grade(pricing.graded_entries(season))

    def _show_blank(self, number: int) -> None:
        self.table.hide()
        self.empty_note.setText(
            f"Week {number} has no games. The workbook's Week {number} sheet is "
            f"empty, there is no predictions file for it, and the schedule "
            f"doesn't have it either - which usually means the season table in "
            f"schedule.py stops short of week {number}."
        )
        self.empty_note.show()
        self.status.setText("")
        self.card.set_title(f"Week {number} picks")
        for tile in (self.tile_slate, self.tile_expected, self.tile_best, self.tile_edge):
            tile.update_values(self.NO_VALUE, "slate not entered yet")
        self._show_big_losers()
        self._show_plan()
        for button in (self.paste_button, self.clear_button):
            button.setEnabled(False)

    def _fit_table(self) -> None:
        """Whole table, no inner scrolling, columns measured to what they hold."""
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        for col in (COL_FAV, COL_SPREAD):
            header.resizeSection(col, max(header.sectionSize(col), CONTROL_WIDTH[col]))
        self._fitter.remeasure()
        fit_height(self.table, self.table.rowCount(), ROW_HEIGHT)

    def _fit_losers(self) -> None:
        self.losers_table.resizeColumnsToContents()
        self._loser_fitter.remeasure()
        fit_height(self.losers_table, self.losers_table.rowCount(), LOSER_ROW_HEIGHT)

    def _fill_row(self, row: int, game: Game, spread: lines.Spread | None) -> None:
        def item(text: str, align=Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
            cell = QTableWidgetItem(text)
            cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
            cell.setTextAlignment(int(align | Qt.AlignmentFlag.AlignVCenter))
            return cell

        self.table.setItem(row, COL_NUM, item(str(game.index), Qt.AlignmentFlag.AlignRight))
        self.table.setItem(row, COL_MATCH, item(predictions.display_matchup(game.away, game.home)))

        favourite = QComboBox()
        favourite.addItem("— choose —", None)
        favourite.addItem(predictions.display_team(game.away), "away")
        favourite.addItem(predictions.display_team(game.home), "home")
        points = QDoubleSpinBox()
        points.setAlignment(Qt.AlignmentFlag.AlignRight)
        points.setRange(0.0, 40.0)
        points.setSingleStep(0.5)
        points.setDecimals(1)
        # A spread typed in by hand wins; otherwise the file's betting line.
        if spread is None:
            spread = self._market_spread(game)
        if spread is not None:
            favourite.setCurrentIndex(favourite.findData(spread.favourite))
            points.setValue(spread.points)
        favourite.currentIndexChanged.connect(lambda _, r=row: self._on_input(r))
        points.valueChanged.connect(lambda _, r=row: self._on_input(r))
        self.table.setCellWidget(row, COL_FAV, favourite)
        self.table.setCellWidget(row, COL_SPREAD, points)
        self._render_row(row)

    def _market_spread(self, game: Game) -> lines.Spread | None:
        """The opening line from the predictions file, as a Spread for this game (pricing.py).

        The opening number rather than the current one, because it is the one
        the commissioner sets his own line against - he posts the week's card
        early, off the number that was up when he looked. Where the market has
        moved since is worth knowing, so it gets a column of its own rather
        than quietly replacing this.

        The file reads positive for the home team and negative for the road
        team; a Spread says which side and by how much, so the sign becomes
        the favourite and the size becomes the points.
        """
        return pricing.opening_spread(game, self._forecasts.get(game.index))

    def _current_line(self, game: Game) -> tuple[str, str, str]:
        """The line as it stands now: what it says, how it moved, and a tone."""
        forecast = self._forecasts.get(game.index)
        if forecast is None:
            return "", "", ""
        now = predictions.home_margin(game, forecast, forecast.market)
        if now is None:
            return "", "", ""
        side = game.home if now >= 0 else game.away
        text = f"{side} by {abs(now):g}" if now else "pick'em"

        opening = predictions.home_margin(game, forecast, forecast.opening)
        if opening is None or abs(now - opening) < 0.05:
            return text, "unmoved since it opened", "muted"
        # Movement is described from the side it moved toward, which is how
        # anyone talks about it: "moved two points to Buffalo".
        toward = game.home if now > opening else game.away
        moved = abs(now - opening)
        if opening:
            was = f"{game.home if opening > 0 else game.away} by {abs(opening):g}"
        else:
            was = "pick'em"
        return (
            text,
            f"opened {was} \u00b7 moved {moved:g} toward {toward}",
            "warning" if moved >= 3 else "",
        )

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
        self._typed[game.index] = side is not None
        self._render_row(row)
        self._update_tiles()
        self._show_big_losers()
        self._show_plan()

    # ---- what the models add ------------------------------------------------
    def _price(self, row: int) -> pricing.Price | None:
        """This row, priced by the one rule every page shares (pricing.py).

        The Spread box shows the opening line, because that is the number the
        commissioner sets his own against. The market's latest is a better
        estimate of how the game will go, so that is what the odds are worked
        out from - unless the box has been typed in by hand, at which point
        the typed number is the statement of what the line is, and it wins.
        Both numbers are on the row, so neither is a surprise. Emptying the
        favourite box takes the game out of the reckoning altogether.
        """
        side, points = self._inputs(row)
        if side is None:
            return None
        game = self._games[row]
        spread = lines.Spread(side, points)
        return pricing.price(game, self._ctx, spread, typed=bool(self._typed.get(game.index)))

    def _margin(self, row: int) -> tuple[float | None, float, str, float]:
        """(expected home margin, spread of results, where it came from, model edge)."""
        found = self._price(row)
        if found is None or found.margin is None:
            return None, analytics.SPREAD_SD, "Vegas", 0.0
        return found.margin, found.sd, found.source, found.edge or 0.0

    def _edge(self, game: Game) -> float | None:
        """What the models say about this game alone, the right way round.

        The slate's shared lean is taken out first: most of a week's
        disagreement is the models carrying a bigger home-field advantage
        than the market, which says nothing about any particular game.
        """
        return pricing.model_edge(game, self._ctx)

    def _prediction(self, row: int) -> analytics.Prediction | None:
        found = self._price(row)
        return found.prediction() if found is not None else None

    def _models_cell(self, row: int) -> tuple[str, str, str]:
        """(text, tooltip, colour) for what the models say about this game."""
        game = self._games[row]
        forecast = self._forecasts.get(game.index)
        if forecast is None:
            return "", "", self.palette.ink_muted
        side, _ = self._inputs(row)
        edge = self._edge(game)                    # this game's own disagreement
        raw = predictions.home_margin(game, forecast, forecast.edge)
        consensus = predictions.home_margin(game, forecast, forecast.consensus)
        if consensus is None or edge is None:
            return "", "", self.palette.ink_muted

        # Everything is said from the side the Spread box calls the favourite.
        backing_home = side != "away"
        team = game.home if backing_home else game.away
        their_margin = consensus if backing_home else -consensus
        their_edge = edge if backing_home else -edge
        their_raw = (raw or 0.0) if backing_home else -(raw or 0.0)

        other = game.away if backing_home else game.home

        def phrase(margin: float) -> str:
            """"Detroit by 9.5", from a margin in this row's favourite's favour."""
            if abs(margin) < analytics.PICK_EM:
                return "a pick 'em"
            return f"{team if margin > 0 else other} by {abs(margin):.1f}"

        text = f"{their_edge:+.1f}"
        tip = (
            f"{forecast.models} models make it {phrase(their_margin)}, against "
            f"the book's {phrase(their_margin - their_raw)}."
        )
        if abs(their_raw - their_edge) >= 0.25:
            tip += (
                f"\nOf that {their_raw:+.1f}, only {their_edge:+.1f} is left once "
                f"the lean the whole slate shares is taken out"
            )
            move = forecast.movement
            if move is not None and abs(move) >= 0.5:
                theirs = move if backing_home else -move
                tip += (
                    f", along with what the market has already moved: the line "
                    f"opened {theirs:+.1f} from where it is now"
                    + (", against the models, which usually means news they "
                       "never saw" if theirs * their_edge < 0 else "")
                )
            tip += "."
        if forecast.disagreement is not None:
            weight = forecast.model_weight(self._weight, self._typical)
            share = weight / self._weight if self._weight else 1
            if self._typical and share < 0.9:
                how = (
                    f", further apart than the {self._typical:.1f} normal for this "
                    f"week, so only {weight:.0%} of their disagreement is believed "
                    f"rather than the usual {self._weight:.0%}"
                )
            elif self._typical and share > 1.1:
                how = (
                    f", closer together than the {self._typical:.1f} normal for this "
                    f"week, so {weight:.0%} of their disagreement is believed rather "
                    f"than the usual {predictions.CONSENSUS_WEIGHT:.0%}"
                )
            else:
                how = ", about the normal for this week"
            tip += (
                f"\nThe models that count are {forecast.disagreement:.1f} points "
                f"apart from each other{how}. Either way it widens every chance "
                f"on this game."
            )
        if forecast.spread_of_opinion:
            tip += f"\nAcross the lot of them, {forecast.spread_of_opinion}."
        colour = (
            self.palette.good if their_edge >= NOTABLE_EDGE
            else self.palette.serious if their_edge <= -NOTABLE_EDGE
            else self.palette.ink_muted
        )
        return text, tip, colour

    # ---- what the rest of the pool will do ----------------------------------
    def _measured_share(self, row: int, pick: str) -> float | None:
        """What the pool actually did, when their pick sheet has been loaded."""
        if self._picks is None:
            return None
        game = self._games[row]
        found = self._picks.game_for(game.away, game.home)
        return found.share_on(pick) if found is not None else None

    def _crowd_share(self, row: int, pick: str) -> float | None:
        """The share of the pool on the same side as this pick (pricing.crowd_share).

        Counted off their own sheet when it is here; estimated from this
        pool's habits, or how pools take favourites of this size, when not.
        """
        side, points = self._inputs(row)
        spread = lines.Spread(side, points) if side is not None else None
        return pricing.crowd_share(
            self.season, self._week_number, self._games[row], pick, spread,
            self._picks, self._chalk,
        )

    def _leverage(self, row: int) -> tuple[float, float] | None:
        """(games gained on the average card, share of the pool on this side)."""
        guess = self._prediction(row)
        if guess is None:
            return None
        share = self._crowd_share(row, guess.pick)
        if share is None:
            return None
        return analytics.leverage(guess.chance, share), share

    def _edge_cell(self, row: int) -> tuple[str, str, str]:
        """(text, tooltip, colour) for what the pick is worth against the field."""
        found = self._leverage(row)
        if found is None:
            return "", "", self.palette.ink_muted
        gain, share = found
        guess = self._prediction(row)
        game = self._games[row]
        other = game.away if _same(guess.pick, game.home) else game.home
        if self._measured_share(row, guess.pick) is not None:
            measured = "counted off the pool's own pick sheet"
        elif getattr(game, "line", None) is not None and self._chalk_games:
            measured = f"measured over {_plural(self._chalk_games, 'lined game')} this season"
        else:
            measured = "from how this pool takes favourites of this size"
        tip = (
            f"{guess.pick} is {guess.chance:.0%} to land, and about {share:.0%} "
            f"of the pool is expected to be on them, {measured}. The pick is "
            f"{abs(gain):.0%} more likely to come in than the average card is "
            f"on this game - {gain:+.2f} of a game {'gained' if gain >= 0 else 'given up'}."
        )
        if gain >= WORTH_LEVERAGE:
            tip += (
                f"\nThis is the shape that wins weeks: most of the pool is on "
                f"{other} and the number says otherwise."
            )
        elif gain <= -WORTH_LEVERAGE:
            tip += (
                "\nStill the right side, but the pool is already on it - being "
                "right here keeps pace rather than gaining."
            )
        colour = (
            self.palette.good if gain >= WORTH_LEVERAGE
            else self.palette.ink_muted if gain <= 0
            else self.palette.ink
        )
        return f"{gain:+.0%}", tip, colour

    # ---- "fav up to" -------------------------------------------------------
    def _threshold(self, row: int) -> tuple[str, str, str]:
        """(cell text, tooltip, colour) for the biggest line worth backing at.

        Worked from the pool's favourite when the game carries a line, so the
        number answers the question actually being asked - is the pool's number
        too big? - and from the favourite in the Spread box otherwise.
        """
        margin, sd, _, _ = self._margin(row)
        if margin is None:
            return "", "", self.palette.ink_muted
        game = self._games[row]

        line = getattr(game, "line", None)
        if line is not None:
            team = getattr(game, "line_favourite", "") or game.home
            backing_home = _same(team, game.home)
        else:
            backing_home = margin >= 0
            team = game.home if backing_home else game.away
        theirs = margin if backing_home else -margin

        if analytics.cover_chance(theirs, 1, sd) <= 0.5:
            return (
                NO_SPREAD,
                f"{team} aren't favoured to win this outright, so they're not "
                f"worth backing at any pool line.",
                self.palette.serious,
            )

        best = analytics.line_threshold(theirs, sd=sd)
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
        return f"{best:g}", tip, self.palette.good if inside else self.palette.ink_muted

    # ---- drawing a row ------------------------------------------------------
    def _pool_line_cell(self, row: int) -> tuple[str, str, str]:
        """(text, tooltip, colour) for the pool's line, posted or expected.

        The commissioner lines the games with a spread over LIKELY_LINED, so a
        big game without a line yet is not a straight pick - it is a lined
        game whose number hasn't been posted. Saying so on Tuesday is the
        difference between planning the week and reacting to it.
        """
        game = self._games[row]
        line = getattr(game, "line", None)
        if line is not None:
            return (f"{game.line_favourite} by {line:g}", "", self.palette.ink)
        margin, sd, _, _ = self._margin(row)
        if margin is None or abs(margin) <= LIKELY_LINED:
            return "straight up", "", self.palette.ink_muted
        team = game.home if margin > 0 else game.away
        most = analytics.line_threshold(abs(margin), sd=sd)
        return (
            "likely lined",
            f"The commissioner normally lines the games bigger than "
            f"{LIKELY_LINED:g}, and Vegas has {team} by {abs(margin):.1f}. If he "
            f"posts {team} by {most} or less, take {team}; at {most + 1} or more, "
            f"take the other side.",
            self.palette.warning,
        )

    def _render_row(self, row: int) -> None:
        game = self._games[row]
        guess = self._prediction(row)
        result = f"Result: {game.winner}. " if game.played else ""
        if guess is None:
            pick, chance, why = "enter the spread", "", result
            why_tip = result
            colour = self.palette.ink_muted
        else:
            pick = guess.pick
            chance = f"{guess.chance:.0%}" + (" · coin flip" if guess.coin_flip else "")
            why = result + guess.reason
            why_tip = result + guess.detail
            colour = (
                self.palette.ink_muted if guess.coin_flip
                else self.palette.good if guess.chance >= CONFIDENT
                else self.palette.ink
            )
        pool_line, pool_tip, pool_colour = self._pool_line_cell(row)
        models, models_tip, models_colour = self._models_cell(row)
        upto, upto_tip, upto_colour = self._threshold(row)
        gain, gain_tip, gain_colour = self._edge_cell(row)
        now_text, now_tip, now_tone = self._current_line(game)
        cells = {
            COL_LINE: QTableWidgetItem(pool_line),
            COL_NOW: QTableWidgetItem(now_text or NO_SPREAD),
            COL_MODELS: QTableWidgetItem(models),
            COL_UPTO: QTableWidgetItem(upto),
            COL_EDGE: QTableWidgetItem(gain),
            COL_PICK: QTableWidgetItem(pick),
            COL_CHANCE: QTableWidgetItem(chance),
            COL_WHY: QTableWidgetItem(why),
        }
        right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bold = QFont()
        bold.setBold(True)
        for col, cell in cells.items():
            cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if col in (COL_PICK, COL_CHANCE):
                cell.setForeground(QColor(colour))
            if col == COL_LINE:
                cell.setForeground(QColor(pool_colour))
                cell.setToolTip(pool_tip)
            if col == COL_NOW:
                cell.setForeground(QColor(
                    self.palette.warning if now_tone == "warning"
                    else self.palette.ink_muted if now_tone == "muted"
                    else self.palette.ink
                ))
                cell.setToolTip(now_tip)
            if col == COL_MODELS:
                cell.setForeground(QColor(models_colour))
                cell.setToolTip(models_tip)
                cell.setTextAlignment(right)
            if col == COL_UPTO:
                cell.setForeground(QColor(upto_colour))
                cell.setToolTip(upto_tip)
                cell.setTextAlignment(right)
            if col == COL_EDGE:
                cell.setForeground(QColor(gain_colour))
                cell.setToolTip(gain_tip)
                cell.setTextAlignment(right)
            if col == COL_PICK and guess is not None:
                cell.setFont(bold)
            if col == COL_CHANCE:
                cell.setTextAlignment(right)
            if col == COL_WHY:
                # The column is the first to be squeezed when the window is
                # narrow, so the whole sentence lives in the tooltip too.
                cell.setToolTip(why_tip)
                cell.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                )
            self.table.setItem(row, col, cell)

    # ---- filling the slate in bulk -----------------------------------------
    def _load_predictions(self) -> None:
        start = predictions.search_folders(
            getattr(self.season, "workbook_path", None) if self.season else None
        )
        path, _ = QFileDialog.getOpenFileName(
            self, f"Week {self._week_number} predictions",
            str(start[0]) if start else "", "Predictions (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            forecasts = predictions.read_csv(path)
        except (OSError, ValueError) as problem:
            self.paste_note.setText(f"Couldn't read that file: {problem}")
            self.paste_note.show()
            return
        named = predictions.week_in_name(path)
        week = self._week_number
        if not forecasts:
            self.paste_note.setText(
                "That file has no games in it - it should have a row per game, "
                "with road and home columns."
            )
            self.paste_note.show()
            return
        predictions.save(week, forecasts, path)
        if named is not None and named != week:
            self.paste_note.setText(
                f"That file's name says week {named}, but it has been loaded "
                f"for week {week} - the week picker decides."
            )
            self.paste_note.show()
        self._show_week()

    def _paste_models(self) -> None:
        """Take the week's models and lines from the pasted summary table.

        The same numbers as the CSV, in the form a person actually has: the
        table on the page rather than the file behind it. What it adds over
        the odds paste is the models - with them the page can say where the
        market and the models disagree, which is the whole point of it.
        """
        week = self._week_number
        dialog = OddsDialog(
            week, self,
            title=f"Paste Week {week} model table",
            blurb=(
                "Both lines, the middle of the models and how far apart they "
                "are, straight off The Prediction Tracker's weekly page. The "
                "updated line is the one used to price the games; the opening "
                "line is kept so the movement can be seen. Rows whose teams "
                "are not on this week's slate are ignored."
            ),
            placeholder=MODELS_PLACEHOLDER,
            button="Read models",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            forecasts = predictions.parse_summary_text(dialog.text())
        except (ValueError, TypeError) as problem:
            self.paste_note.setText(f"Couldn't read that table: {problem}")
            self.paste_note.show()
            return
        if not forecasts:
            self.paste_note.setText(
                "No games found in that paste. Each row needs two team names "
                "and the ten numbers after them - the header rows and blank "
                "lines are skipped, so the whole block can be pasted as it is."
            )
            self.paste_note.show()
            return

        predictions.save(week, forecasts, "pasted model table")
        matched = predictions.match_games(
            sorted(self._games, key=lambda g: g.index), forecasts
        ).by_game if self._games else {}
        missing = len(self._games) - len(matched) if self._games else 0
        parts = [
            f"Read {_plural(len(forecasts), 'game')} from the model table."
        ]
        if self._games:
            parts.append(
                f"{_plural(len(matched), 'game')} on this week's slate matched"
                + (f", {missing} not in the paste." if missing else ".")
            )
        parts.append(
            "Both lines, the models' median and their spread are now on the "
            "table below."
        )
        self.paste_note.setText(" ".join(parts))
        self.paste_note.show()
        self._show_week()

    def _load_picks(self) -> None:
        start = picks.search_folders(
            getattr(self.season, "workbook_path", None) if self.season else None
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "The pool's pick sheet", str(start[0]) if start else "",
            "Pick sheets (*.xls *.xlsx);;All files (*)",
        )
        if not path:
            return
        try:
            sheet = picks.read_file(path)
        except (picks.Unreadable, OSError, ValueError) as problem:
            self.paste_note.setText(str(problem))
            self.paste_note.show()
            return
        picks.save(sheet)
        scored = self._apply_picks(sheet)
        if sheet.week != self._week_number:
            self._user_chose_week = True
            self._set_week(sheet.week)
        self._show_week()
        self.paste_note.setText(
            f"Week {sheet.week} pick sheet loaded: {picks.summary(sheet)}. "
            f"Every \"Vs pool\" figure on this week is now counted rather than "
            f"estimated." + scored
        )
        self.paste_note.show()

    def _apply_picks(self, sheet: "picks.WeekPicks") -> str:
        """Put the sheet into the season, and tell the rest of the app.

        Saving the file only fed this page. Everything the sheet scores -
        the standings, each coach's week, the crowd chart - lives on other
        pages reading the same season, and until this runs they carry on
        showing what was there before, as though the file had not been
        loaded at all. Which is exactly how it looked.
        """
        if self.season is None:
            return ""
        try:
            graded = picks.attach(self.season, {sheet.week: sheet})
        except Exception as problem:             # noqa: BLE001 - never lose the file
            return f" The week could not be scored from it ({problem})."

        # Every page holds the same Season object, so they need telling that
        # what is inside it has changed; each one refreshes when next shown.
        for page in getattr(self.window(), "pages", ()):
            if page is not self:
                page.invalidate()

        if sheet.week in graded.checked:
            return (
                " The workbook already scores this week, so it was checked "
                "against the sheet rather than rescored."
            )
        if sheet.week in graded.built or sheet.week in graded.filled:
            counted = len(self.season.weeks[sheet.week].lines)
            return f" Week {sheet.week} is now scored from it for all {counted} coaches."
        return ""

    def _paste_odds(self) -> None:
        if not self._games:
            return
        dialog = OddsDialog(self._week_number, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        found, notes = lines.parse_odds_text(dialog.text(), self._games)
        self._apply_spreads(found)

        missing = [f"{g.away} @ {g.home}" for g in self._games if g.index not in found]
        parts = [f"Read {_plural(len(found), 'game')} out of {len(self._games)}."]
        if missing:
            parts.append(
                "Not in the paste: " + ", ".join(missing[:6])
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
        self._fit_table()
        self._update_tiles()
        self._show_big_losers()
        self._show_plan()

    def _clear_spreads(self) -> None:
        self._typed = {}
        """Forget the typed-in spreads. The file's lines come back in their place."""
        self._loading = True
        try:
            for row, game in enumerate(self._games):
                lines.save_spread(self._week_number, game, None)
                spread = self._market_spread(game)
                favourite = self.table.cellWidget(row, COL_FAV)
                points = self.table.cellWidget(row, COL_SPREAD)
                favourite.setCurrentIndex(
                    favourite.findData(spread.favourite) if spread else 0
                )
                points.setValue(spread.points if spread else 0.0)
        finally:
            self._loading = False
        self.paste_note.hide()
        for row in range(len(self._games)):
            self._render_row(row)
        self._fit_table()
        self._update_tiles()
        self._show_big_losers()
        self._show_plan()

    # ---- the Big Loser mini pool -------------------------------------------
    def _show_big_losers(self) -> None:
        prices = [p for p in (self._price(row) for row in range(len(self._games)))
                  if p is not None and p.margin is not None and not p.game.played]
        entries = prices

        table = self.losers_table
        table.setRowCount(0)
        if not entries:
            self.losers.set_title("Big Losers")
            self.losers_note.setText(
                "Enter the spreads above and the three best big losers appear here. "
                + BIG_LOSER_RULE
            )
            return
        self.losers_note.setText(BIG_LOSER_RULE)

        # Each game carries its own spread of results - the same numbers the
        # picks use, and the same list This Week's side-pool line reads.
        candidates = pricing.big_loser_candidates(prices)
        best = candidates[:BIG_LOSER_PICKS]
        expected = sum(b.chance for b in best)
        none_of_them = 1.0
        for b in best:
            none_of_them *= 1 - b.chance
        self.losers.set_title(
            f"Big Losers \u00b7 {expected:.1f} points expected from the three marked, "
            f"{1 - none_of_them:.0%} chance at least one lands"
        )

        shown = candidates[:LOSER_ROWS]
        table.setRowCount(len(shown))
        bold = QFont()
        bold.setBold(True)
        for row, pick in enumerate(shown):
            take = "\u2713" if row < BIG_LOSER_PICKS else ""
            beaten = "a beating" if pick.margin <= -7 else "an upset as well"
            held = self._picks.loser_share(pick.team) if self._picks else None
            why = (
                f"{pick.opponent} winning by 15+ takes {beaten}"
                if pick.margin > -7 else
                f"{pick.opponent} are favoured by {abs(pick.margin):.1f}, so a "
                f"15-point beating is the same game only more so"
            )
            if held is not None and held >= 0.4:
                why += f" \u00b7 {held:.0%} of the pool already has them"
            cells = [
                (LOSER_TAKE, take, Qt.AlignmentFlag.AlignCenter),
                (LOSER_TEAM, pick.team, Qt.AlignmentFlag.AlignLeft),
                (LOSER_GAME, f"vs {pick.opponent}", Qt.AlignmentFlag.AlignLeft),
                (LOSER_LINE, f"{pick.margin:+.1f}", Qt.AlignmentFlag.AlignRight),
                (LOSER_CHANCE, f"{pick.chance:.0%}", Qt.AlignmentFlag.AlignRight),
                (LOSER_POOL, "" if held is None else f"{held:.0%}",
                 Qt.AlignmentFlag.AlignRight),
                (LOSER_WHY, why, Qt.AlignmentFlag.AlignLeft),
            ]
            for col, text, align in cells:
                cell = QTableWidgetItem(text)
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
                cell.setTextAlignment(int(align | Qt.AlignmentFlag.AlignVCenter))
                if row < BIG_LOSER_PICKS:
                    if col in (LOSER_TAKE, LOSER_TEAM, LOSER_CHANCE):
                        cell.setForeground(QColor(self.palette.good))
                    if col == LOSER_TEAM:
                        cell.setFont(bold)
                elif col != LOSER_WHY:
                    cell.setForeground(QColor(self.palette.ink_secondary))
                table.setItem(row, col, cell)
        self._fit_losers()

    # ---- planning the whole card --------------------------------------------
    def _week_plan(self) -> tuple[weekplan.Plan, list[int]] | None:
        """(the plan, the table rows it covers), or None when too little is priced."""
        choices, rows = [], []
        for row, game in enumerate(self._games):
            guess = self._prediction(row)
            if guess is None or game.played:
                continue
            other = game.away if _same(guess.pick, game.home) else game.home
            share = self._crowd_share(row, guess.pick)
            choices.append(weekplan.Choice(
                f"{game.away} @ {game.home}", guess.pick, other, guess.chance,
                analytics.CHALK_PRIOR if share is None else share,
            ))
            rows.append(row)
        if len(choices) < PLAN_MINIMUM:
            return None
        cards = pricing.field_cards(
            self._picks, [self._games[r] for r in rows], [c.pick for c in choices]
        )
        coaches = max(1, len(self.season.players) - 1) if self.season else 34
        plan = weekplan.plan_week(choices, cards=cards, coaches=coaches)
        return (plan, rows) if plan is not None else None

    def _show_plan(self) -> None:
        found = self._week_plan()
        if found is None:
            self.plan_card.set_title("Week plan")
            self.plan_body.setText(
                "Price the games above and the best card for the week is worked "
                "out here."
            )
            return
        plan, rows = found
        self.plan_card.set_title(
            f"Week plan \u00b7 finishes first {plan.win_odds:.1%} of weeks, "
            f"against {plan.plain_win_odds:.1%} for taking every likelier side "
            f"(a fair share of {plan.coaches + 1} is {plan.fair_share:.1%})"
        )
        if not plan.flipped:
            self.plan_body.setText(
                f"Take the likelier side of all {_plural(len(rows), 'game')}: "
                f"nothing is crowded enough this week to be worth giving up a "
                f"better chance for. Expected {plan.expected_hits:.1f} right."
            )
            return
        said = []
        for index in plan.flipped:
            row = rows[index]
            game = self._games[row]
            guess = self._prediction(row)
            taking = plan.take[index]
            share = self._crowd_share(row, taking)
            said.append(
                f"\u2022 {game.away} @ {game.home}: take {taking} over {guess.pick}"
                + (f", who {(1 - share):.0%} of the pool has" if share is not None else "")
                + f". Less likely - {1 - guess.chance:.0%} against {guess.chance:.0%} - "
                f"but that is the point."
            )
        field = "real" if plan.field_known else "simulated"
        self.plan_body.setText(
            f"{_plural(len(plan.flipped), 'game')} worth turning around, against "
            f"{plan.coaches} other {field} cards:\n" + "\n".join(said)
            + f"\nIt expects {plan.expected_hits:.1f} right rather than "
              f"{plan.plain_hits:.1f}, and makes the top five less often "
              f"({plan.top_five:.0%} against {plan.plain_top_five:.0%}) - but "
              f"top five pays nothing. First place is what it is after."
        )

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
            + (" · slate from the predictions file" if self._from_file else "")
        )
        self.tile_slate.update_values(
            f"{outlook.priced}/{len(games)}",
            f"games priced · {lined} carry a pool line",
            "good" if games and outlook.priced == len(games) else "",
        )

        best = [
            (row, gain, share) for row in range(len(games))
            for found in (self._leverage(row),) if found is not None
            for gain, share in (found,)
        ]
        if best:
            row, gain, share = max(best, key=lambda item: item[1])
            guess = self._prediction(row)
            game = games[row]
            self.tile_edge.update_values(
                guess.pick,
                f"{gain:+.0%} on the average card \u00b7 {guess.chance:.0%} to land "
                f"against {share:.0%} of the pool\n{game.away} @ {game.home}",
                "good" if gain >= WORTH_LEVERAGE else "",
            )
        else:
            self.tile_edge.update_values(
                self.NO_VALUE, "enter some spreads to see where the pool is wrong"
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
