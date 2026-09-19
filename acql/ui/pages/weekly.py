"""One week at a time: the slate, who won it, and which games were traps."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout

from ..charts import BarChart
from ..widgets import Card, StatTile, TableModel, make_table, section
from .base import Page

SLATE_HEADERS = ["#", "Matchup", "Result", "Got it right", "Hit rate"]
BOARD_HEADERS = ["#", "Player", "Total", "Regular", "Big Loser", "Suicide pick"]


class WeeklyPage(Page):
    title = "Weekly"
    subtitle = "The slate, the scoreboard and the trap games"
    icon = "\N{SPIRAL CALENDAR PAD}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Week"))
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(170)
        self.week_picker.currentIndexChanged.connect(lambda _: self._render())
        controls.addWidget(self.week_picker)
        controls.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        controls.addWidget(self.status)
        self.layout_.addLayout(controls)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_winner = StatTile("Week Winner")
        self.tile_high = StatTile("High Score")
        self.tile_avg = StatTile("Week Average")
        self.tile_low = StatTile("Low Score")
        for t in (self.tile_winner, self.tile_high, self.tile_avg, self.tile_low):
            tiles.addWidget(t)
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

        self.board_card = Card("Scoreboard")
        self.board_box = QVBoxLayout()
        self.board_card.body().addLayout(self.board_box)
        self.layout_.addWidget(self.board_card, 2)

        self.slate_table = None
        self.board_table = None
        self._weeks: list[int] = []

    def refresh(self) -> None:
        s = self.season
        if s is None:
            return
        self._weeks = sorted(s.weeks)
        current = self.week_picker.currentData()
        self.week_picker.blockSignals(True)
        self.week_picker.clear()
        for w in self._weeks:
            suffix = ""
            if w in s.provisional_weeks:
                suffix = "  (in progress)"
            elif not s.weeks[w].scored:
                suffix = "  (not played)"
            self.week_picker.addItem(f"Week {w}{suffix}", w)
        if current in self._weeks:
            self.week_picker.setCurrentIndex(self._weeks.index(current))
        elif s.current_week in self._weeks:
            self.week_picker.setCurrentIndex(self._weeks.index(s.current_week))
        self.week_picker.blockSignals(False)
        self._render()

    def _render(self) -> None:
        s = self.season
        if s is None or not self._weeks:
            self.status.setText("No week sheets found in the workbook.")
            return
        number = self.week_picker.currentData()
        week = s.weeks.get(number)
        if week is None:
            return

        scores = sorted(
            ((key, line) for key, line in week.lines.items() if line.total_wins),
            key=lambda kv: -kv[1].total_wins,
        )
        if scores:
            top = scores[0][1].total_wins
            winners = [s.players[k].display for k, l in scores if l.total_wins == top]
            values = [l.total_wins for _, l in scores]
            average = sum(values) / len(values)
            self.tile_winner.update_values(
                winners[0] if len(winners) == 1 else f"{len(winners)}-way tie",
                ", ".join(winners[:4]) + ("…" if len(winners) > 4 else ""),
            )
            self.tile_high.update_values(str(top), f"out of {week.game_count or len(week.games)} games")
            self.tile_avg.update_values(f"{average:.1f}", f"across {len(values)} players")
            self.tile_low.update_values(str(min(values)), f"{values.count(min(values))} player(s)")
        else:
            for tile, label in (
                (self.tile_winner, "Not scored yet"),
                (self.tile_high, "Not scored yet"),
                (self.tile_avg, "Not scored yet"),
                (self.tile_low, "Not scored yet"),
            ):
                tile.update_values("–", label)

        played = sum(1 for g in week.games if g.played)
        self.status.setText(
            f"{len(week.games)} games · {played} result(s) entered · "
            f"{len(week.lines)} players"
        )

        self._render_slate(week)
        self._render_traps(week)
        self._render_board(week, scores)

    def _render_slate(self, week) -> None:
        entrants = len(week.lines) or 1
        rows: list[list[object]] = []
        data = []
        for g in week.games:
            correct = week.correct_count(g.index)
            rate = correct / entrants
            data.append((g, correct, rate))
            rows.append([
                g.index,
                g.label,
                g.winner or "–",
                correct,
                self.pct(rate),
            ])
        tone_map = {}
        for r, (_, _, rate) in enumerate(data):
            tone_map[(r, 4)] = "good" if rate >= 0.75 else ("bad" if rate <= 0.3 else "muted")

        model = TableModel(
            SLATE_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 3, 4},
            sort_values={4: [rate for _, _, rate in data]},
            tones=tone_map,
            bold_columns={1},
        )
        view, _ = make_table(model, stretch_column=1, sort_column=0, row_height=27)
        view.setMinimumHeight(260)
        if self.slate_table is not None:
            self.slate_table.deleteLater()
        self.slate_table = view
        self.slate_box.addWidget(view)

    def _render_traps(self, week) -> None:
        entrants = len(week.lines) or 1
        scored = [
            (g, week.correct_count(g.index))
            for g in week.games
            if week.correct_count(g.index) or g.played
        ]
        if not scored:
            self.trap_chart.empty("No picks recorded for this week")
            return
        scored.sort(key=lambda gc: gc[1])
        shown = scored[:10]
        self.trap_chart.plot(
            [g.label for g, _ in shown],
            [c for _, c in shown],
            xlabel=f"Players correct (of {entrants})",
            color=self.palette.series[1],
            tooltips=[
                f"{g.label}\nWinner: {g.winner or 'not entered'}\n"
                f"{c} of {entrants} correct ({c / entrants * 100:.0f}%)"
                for g, c in shown
            ],
        )

    def _render_board(self, week, scores) -> None:
        s = self.season
        rows, tones = [], {}
        for r, (key, line) in enumerate(scores):
            player = s.players.get(key)
            rows.append([
                line.rank or r + 1,
                player.display if player else line.player,
                line.total_wins,
                line.regular_wins,
                line.big_loser_wins,
                line.suicide_pick or "–",
            ])
            if line.big_loser_wins:
                tones[(r, 4)] = "good"
        model = TableModel(
            BOARD_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 2, 3, 4},
            sort_values={0: list(range(len(rows)))},
            tones=tones,
            bold_columns={1},
        )
        view, _ = make_table(model, stretch_column=1, sort_column=0, ascending=True, row_height=27)
        view.setMinimumHeight(300)
        if self.board_table is not None:
            self.board_table.deleteLater()
        self.board_table = view
        self.board_box.addWidget(view)
