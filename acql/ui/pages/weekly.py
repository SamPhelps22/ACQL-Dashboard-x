"""One week at a time: the slate, who won it, and which games were traps."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...models import Season, Week
from ..charts import BarChart, HistogramChart
from ..widgets import Card, StatTile, TableModel, make_table, section
from .base import Page

SLATE_HEADERS = ["#", "Matchup", "Result", "Got it right", "Hit rate"]
BOARD_HEADERS = ["#", "Player", "Total", "Regular", "Big Loser", "Suicide pick"]
TRAP_COUNT = 10
EASY_RATE = 0.75      # most of the pool got it - not a trap
TRAP_RATE = 0.30      # most of the pool missed it


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class WeeklyPage(Page):
    title = "Weekly"
    subtitle = "The slate, the scoreboard and the trap games"
    icon = "\N{SPIRAL CALENDAR PAD}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.slate_table: QWidget | None = None
        self.board_table: QWidget | None = None
        self._weeks: list[int] = []

        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Week"))
        self.prev_btn = self._step_button("‹", "Previous week (Alt+Left)")
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(180)
        self.next_btn = self._step_button("›", "Next week (Alt+Right)")
        for widget in (self.prev_btn, self.week_picker, self.next_btn):
            controls.addWidget(widget)
        controls.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        controls.addWidget(self.status)
        self.layout_.addLayout(controls)

        self.week_picker.currentIndexChanged.connect(lambda _: self._render())
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn.clicked.connect(lambda: self._step(1))
        for keys, delta in (("Alt+Left", -1), ("Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda d=delta: self._step(d))

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_winner = StatTile("Week Winner")
        self.tile_high = StatTile("High Score")
        self.tile_avg = StatTile("Week Average")
        self.tile_low = StatTile("Low Score")
        self._tiles = (self.tile_winner, self.tile_high, self.tile_avg, self.tile_low)
        for tile in self._tiles:
            tiles.addWidget(tile, 2 if tile is self.tile_winner else 1)
        self.layout_.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.slate_card = Card("The slate")
        self.slate_box = QVBoxLayout()
        self.slate_card.body().addLayout(self.slate_box)
        row.addWidget(self.slate_card, 3)

        self.trap_card = Card("Hardest games - fewest correct picks")
        self.trap_chart = BarChart(self.palette, height=4.4)
        self.trap_card.add(self.trap_chart, 1)
        row.addWidget(self.trap_card, 2)
        self.layout_.addLayout(row)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.board_card = Card("Scoreboard")
        self.board_box = QVBoxLayout()
        self.board_card.body().addLayout(self.board_box)
        bottom.addWidget(self.board_card, 3)

        # The tiles give the week's high, low and average; this shows the
        # shape between them - a tight pack or a runaway winner.
        self.spread_card = Card("How the week was scored")
        self.spread_chart = HistogramChart(self.palette, height=3.4)
        self.spread_card.add(self.spread_chart, 1)
        bottom.addWidget(self.spread_card, 2)
        self.layout_.addLayout(bottom)

    @staticmethod
    def _step_button(text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setFixedWidth(38)
        button.setStyleSheet("padding: 6px 0;")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def restyle(self) -> None:
        self.trap_chart.set_palette(self.palette)
        self.spread_chart.set_palette(self.palette)
        self.refresh_now()

    # ---- week selection -------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        self._weeks = sorted(season.weeks)
        current = self.week_picker.currentData()
        self.week_picker.blockSignals(True)
        self.week_picker.clear()
        for week in self._weeks:
            if week in season.provisional_weeks:
                suffix = "  (in progress)"
            elif not season.weeks[week].scored:
                suffix = "  (not played)"
            else:
                suffix = ""
            self.week_picker.addItem(f"Week {week}{suffix}", week)
        if current in self._weeks:
            self.week_picker.setCurrentIndex(self._weeks.index(current))
        elif season.current_week in self._weeks:
            self.week_picker.setCurrentIndex(self._weeks.index(season.current_week))
        self.week_picker.blockSignals(False)
        self._render()

    def _step(self, delta: int) -> None:
        target = self.week_picker.currentIndex() + delta
        if 0 <= target < self.week_picker.count():
            self.week_picker.setCurrentIndex(target)

    # ---- render ---------------------------------------------------------
    def _render(self) -> None:
        season = self.season
        if season is None:
            return
        if not self._weeks:
            self._show_empty("No week sheets found in the workbook.")
            return
        week = season.weeks.get(self.week_picker.currentData())
        if week is None:
            return

        self.prev_btn.setEnabled(self.week_picker.currentIndex() > 0)
        self.next_btn.setEnabled(
            self.week_picker.currentIndex() < self.week_picker.count() - 1
        )

        scores = self._scores(week)
        self._update_tiles(week, scores)

        entered = sum(1 for g in week.games if g.played)
        self.status.setText(
            f"{_plural(len(week.games), 'game')} · "
            f"{_plural(entered, 'result')} entered · "
            f"{_plural(len(week.lines), 'player')}"
        )

        self._render_slate(week)
        self._render_traps(week)
        self._render_board(week, scores)
        self._render_spread(scores)

    @staticmethod
    def _scores(week: Week) -> list[tuple[str, object]]:
        """Every line on a scored week, best first.

        A player who genuinely scored zero is part of the week. Filtering on
        `line.total_wins` dropped them from the scoreboard and, worse, out of
        the low-score and average tiles, which then described only the players
        who had put a number on the board.
        """
        if not week.scored:
            return []
        return sorted(
            week.lines.items(),
            key=lambda kv: (-kv[1].total_wins, kv[1].player.lower()),
        )

    def _show_empty(self, message: str) -> None:
        self.status.setText(message)
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "No data")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.trap_chart.empty("No picks recorded for this week")
        self.spread_chart.empty("Not scored yet")
        for box, attr in ((self.slate_box, "slate_table"), (self.board_box, "board_table")):
            self.clear_layout(box)
            setattr(self, attr, None)

    def _update_tiles(self, week: Week, scores: list[tuple[str, object]]) -> None:
        season = self.season
        if not scores:
            for tile in self._tiles:
                tile.update_values(self.NO_VALUE, "Not scored yet")
            return

        values = [line.total_wins for _, line in scores]
        top, low = max(values), min(values)
        games = week.game_count or len(week.games) or 1

        winners = [
            (season.players[key].display if key in season.players else line.player)
            for key, line in scores if line.total_wins == top
        ]
        self.tile_winner.update_values(
            winners[0] if len(winners) == 1 else f"{len(winners)}-way tie",
            ", ".join(winners[:4]) + ("…" if len(winners) > 4 else ""),
            "good",
        )
        self.tile_high.update_values(
            str(top), f"of {_plural(games, 'game')}  ·  {self.pct(top / games, 0)}"
        )

        average = sum(values) / len(values)
        self.tile_avg.update_values(
            f"{average:.1f}",
            f"across {_plural(len(values), 'player')}  ·  "
            f"{self.pct(average / games, 0)}",
        )
        self.tile_low.update_values(
            str(low),
            f"{_plural(values.count(low), 'player')} on it"
            + (f"  ·  {top - low} behind the winner" if top != low else ""),
            "bad" if top != low else "",
        )

    # ---- the slate ------------------------------------------------------
    def _render_slate(self, week: Week) -> None:
        entrants = len(week.lines) or 1
        rows, tones, rates = [], {}, []
        for r, game in enumerate(week.games):
            correct = week.correct_count(game.index)
            rate = correct / entrants
            rates.append(rate)
            rows.append([
                game.index,
                game.label,
                game.winner or self.NO_VALUE,
                correct,
                self.pct(rate) if game.played or correct else self.NO_VALUE,
            ])
            if not (game.played or correct):
                tones[(r, 4)] = "muted"
            elif rate >= EASY_RATE:
                tones[(r, 4)] = "good"
            elif rate <= TRAP_RATE:
                tones[(r, 4)] = "bad"
            else:
                tones[(r, 4)] = "muted"
            if not game.played:
                tones[(r, 2)] = "muted"

        model = TableModel(
            SLATE_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 3, 4},
            sort_values={4: rates},
            tones=tones,
            bold_columns={1},
        )
        view, _ = make_table(model, stretch_column=1, sort_column=0, row_height=27)
        view.setMinimumHeight(260)
        self.clear_layout(self.slate_box)
        self.slate_table = view
        self.slate_box.addWidget(view)

    def _render_traps(self, week: Week) -> None:
        entrants = len(week.lines) or 1
        scored = [
            (game, week.correct_count(game.index))
            for game in week.games
            if game.played or week.correct_count(game.index)
        ]
        if not scored:
            self.trap_chart.empty("No picks recorded for this week")
            self.trap_card.set_title("Hardest games - fewest correct picks")
            return
        # Slate order breaks ties, so two equally hard games keep a stable
        # order between refreshes instead of swapping around.
        scored.sort(key=lambda pair: (pair[1], pair[0].index))
        shown = scored[:TRAP_COUNT]
        self.trap_card.set_title(
            f"Hardest {len(shown)} games - fewest correct picks"
            if len(scored) > TRAP_COUNT
            else "Every game - fewest correct picks first"
        )
        # The hardest game takes the warm slot; the rest stay quiet, so colour
        # marks the trap rather than repeating the bar length.
        hardest = shown[0][1]
        colors = [
            self.palette.series_color(1) if count == hardest
            else self.palette.series_color(2)
            for _, count in shown
        ]
        self.trap_chart.plot(
            [game.label for game, _ in shown],
            [count for _, count in shown],
            xlabel=f"Players correct (of {entrants})",
            colors=colors,
            tooltips=[
                f"{game.label}\nWinner: {game.winner or 'not entered'}\n"
                f"{count} of {entrants} correct ({self.pct(count / entrants, 0)})"
                for game, count in shown
            ],
        )

    # ---- the scoreboard --------------------------------------------------
    def _render_board(self, week: Week, scores: list[tuple[str, object]]) -> None:
        season = self.season
        if not scores:
            self.clear_layout(self.board_box)
            self.board_table = None
            note = QLabel("This week has not been scored yet.")
            note.setObjectName("Muted")
            self.board_box.addWidget(note)
            return

        top = scores[0][1].total_wins
        ranks = self._ranks([line.total_wins for _, line in scores])
        rows, tones = [], {}
        for r, ((key, line), rank) in enumerate(zip(scores, ranks)):
            player = season.players.get(key)
            rows.append([
                line.rank or rank,
                player.display if player else line.player,
                line.total_wins,
                line.regular_wins,
                line.big_loser_wins,
                line.suicide_pick or self.NO_VALUE,
            ])
            if line.big_loser_wins:
                tones[(r, 4)] = "good"
            if line.total_wins == top:
                tones[(r, 2)] = "good"

        model = TableModel(
            BOARD_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 2, 3, 4},
            sort_values={
                0: [line.rank or rank for (_, line), rank in zip(scores, ranks)],
                2: [line.total_wins for _, line in scores],
                3: [line.regular_wins for _, line in scores],
                4: [line.big_loser_wins for _, line in scores],
            },
            tones=tones,
            bold_columns={1},
        )
        view, _ = make_table(
            model, stretch_column=1, sort_column=0, ascending=True, row_height=27
        )
        view.setMinimumHeight(300)
        self.clear_layout(self.board_box)
        self.board_table = view
        self.board_box.addWidget(view)

    def _render_spread(self, scores: list[tuple[str, object]]) -> None:
        if not scores:
            self.spread_card.set_title("How the week was scored")
            self.spread_chart.empty("Not scored yet")
            return
        values = [line.total_wins for _, line in scores]
        self.spread_card.set_title(
            f"How the week was scored - {_plural(len(values), 'player')}, "
            f"{max(values) - min(values)}-win spread"
        )
        self.spread_chart.plot(values, xlabel="Wins this week")

    @staticmethod
    def _ranks(totals: list[int]) -> list[int]:
        """Competition ranking: players level on the week share a place."""
        ranks: list[int] = []
        rank, last = 0, None
        for i, total in enumerate(totals, start=1):
            if total != last:
                rank, last = i, total
            ranks.append(rank)
        return ranks