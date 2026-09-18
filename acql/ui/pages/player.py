"""Per-player deep dive: form, rank trajectory and the weekly record."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
)

from ..charts import BarChart, LineChart, RankChart
from ..widgets import Card, StatTile, TableModel, make_table, section
from .base import Page

HEADERS = ["Week", "Wins", "Regular", "Big Loser", "Rank", "Suicide pick", "vs pool avg"]


class PlayerPage(Page):
    title = "Player"
    subtitle = "One coach's season in detail"
    icon = "\N{BUST IN SILHOUETTE}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Player"))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(240)
        self.picker.currentIndexChanged.connect(lambda _: self._render())
        controls.addWidget(self.picker)
        controls.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        controls.addWidget(self.status)
        self.layout_.addLayout(controls)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_rank = StatTile("Position")
        self.tile_record = StatTile("Record")
        self.tile_form = StatTile("Recent Form")
        self.tile_money = StatTile("Net")
        self.tile_swing = StatTile("Consistency")
        for t in (
            self.tile_rank, self.tile_record, self.tile_form,
            self.tile_money, self.tile_swing,
        ):
            tiles.addWidget(t)
        self.layout_.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.form_card = Card("Wins by week, against the pool average")
        self.form_stack = QStackedWidget()
        self.form_chart = LineChart(self.palette, height=3.4)
        self.form_bars = BarChart(self.palette, height=3.4)
        self.form_stack.addWidget(self.form_chart)
        self.form_stack.addWidget(self.form_bars)
        self.form_card.add(self.form_stack, 1)
        row.addWidget(self.form_card, 1)

        self.rank_card = Card("Position through the season")
        self.rank_chart = RankChart(self.palette, height=3.4)
        self.rank_card.add(self.rank_chart, 1)
        row.addWidget(self.rank_card, 1)
        self.layout_.addLayout(row)

        self.table_card = Card("Week by week")
        self.table_box = QVBoxLayout()
        self.table_card.body().addLayout(self.table_box)
        self.layout_.addWidget(self.table_card, 1)
        self.table = None

    def refresh(self) -> None:
        s = self.season
        if s is None:
            return
        names = [p.display for p in s.ordered_players()]
        current = self.picker.currentText()
        self.picker.blockSignals(True)
        self.picker.clear()
        self.picker.addItems(names)
        if current in names:
            self.picker.setCurrentIndex(names.index(current))
        self.picker.blockSignals(False)
        self._render()

    def select(self, display: str) -> None:
        index = self.picker.findText(display)
        if index >= 0:
            self.picker.setCurrentIndex(index)

    def _render(self) -> None:
        s = self.season
        if s is None or not self.picker.count():
            return
        player = s.by_display(self.picker.currentText())
        if player is None:
            return

        move = player.rank_movement
        detail = f"{len(s.players)} players"
        if move:
            detail += f"   ▲ {move}" if move > 0 else f"   ▼ {abs(move)}"
        self.tile_rank.update_values(
            f"#{player.pos}" if player.pos else "–",
            detail,
            "good" if (move or 0) > 0 else ("bad" if (move or 0) < 0 else ""),
        )
        self.tile_record.update_values(
            f"{player.wins}-{player.losses}",
            f"{player.pct:.3f}   {player.games_behind:.0f} back",
        )
        self.tile_form.update_values(
            f"{player.trend(3):.1f}",
            "average over the last 3 weeks played",
        )
        net = player.net_points
        self.tile_money.update_values(
            self.money(net),
            f"{self.money(player.points_won)} won, {self.money(abs(player.points_paid))} in",
            "good" if net > 0 else ("bad" if net < 0 else ""),
        )
        self.tile_swing.update_values(
            f"±{player.consistency:.2f}",
            f"between {player.worst_week} and {player.best_week} wins",
        )

        alive = "alive" if player.suicide_alive else "eliminated"
        self.status.setText(
            f"Big-loser points {player.big_loser_points:g} · suicide pool {alive} "
            f"· seen in {len(player.sources)} file(s)"
        )

        weeks = s.final_weeks()
        pool_avg = [self._pool_average(w) for w in weeks]
        if len(weeks) >= 2:
            self.form_stack.setCurrentWidget(self.form_chart)
            self.form_card.set_title("Wins by week, against the pool average")
            self.form_chart.plot(
                weeks,
                [(player.display, [player.weekly_wins.get(w) for w in weeks])],
                ylabel="Wins",
                reference=("Pool average", pool_avg),
                direct_label=False,
            )
        elif len(weeks) == 1:
            # A single week is a comparison, not a trend: bars read it better.
            week = weeks[0]
            mine = player.weekly_wins.get(week, 0)
            self.form_stack.setCurrentWidget(self.form_bars)
            self.form_card.set_title(f"Week {week} - against the pool")
            self.form_bars.plot(
                [player.display, "Pool average", "Pool best"],
                [mine, pool_avg[0], self._pool_best(week)],
                xlabel="Wins",
                colors=[
                    self.palette.series[0],
                    self.palette.ink_muted,
                    self.palette.series[2],
                ],
                value_format="{:.1f}",
                tooltips=[
                    f"{player.display}: {mine} wins",
                    f"Pool average: {pool_avg[0]:.1f} wins",
                    f"Best in the pool: {self._pool_best(week):g} wins",
                ],
            )
        else:
            self.form_stack.setCurrentWidget(self.form_chart)
            self.form_chart.empty("No finalised weeks yet")

        rank_weeks = sorted(player.weekly_rank)
        if rank_weeks:
            self.rank_chart.plot(
                rank_weeks,
                [(player.display, [player.weekly_rank.get(w) for w in rank_weeks])],
                ylabel="Position (1 is best)",
                direct_label=False,
            )
        else:
            self.rank_chart.empty("No weekly rankings recorded")

        self._render_table(player, weeks)

    def _pool_average(self, week: int) -> float:
        """Mean score for a week, taken from whichever pot the week lives in."""
        s = self.season
        if s is None:
            return 0.0
        peers = [p.weekly_wins[week] for p in s.players.values() if week in p.weekly_wins]
        if not peers:
            peers = [
                p.provisional_wins[week]
                for p in s.players.values()
                if week in p.provisional_wins
            ]
        return sum(peers) / len(peers) if peers else 0.0

    def _pool_best(self, week: int) -> float:
        s = self.season
        if s is None:
            return 0.0
        peers = [p.weekly_wins.get(week, p.provisional_wins.get(week)) for p in s.players.values()]
        return max((v for v in peers if v is not None), default=0)

    def _render_table(self, player, weeks: list[int]) -> None:
        s = self.season
        all_weeks = sorted(set(weeks) | set(player.provisional_wins))
        rows, tones = [], {}
        for r, w in enumerate(all_weeks):
            provisional = w in s.provisional_weeks
            wins = player.weekly_wins.get(w, player.provisional_wins.get(w))
            if wins is None:
                continue
            avg = self._pool_average(w)
            delta = wins - avg
            line = s.weeks.get(w)
            pick = line.lines.get(player.key).suicide_pick if line and player.key in line.lines else ""
            rows.append([
                f"Week {w}" + (" *" if provisional else ""),
                wins,
                player.weekly_regular.get(w, "–"),
                player.weekly_big_loser.get(w, "–"),
                player.weekly_rank.get(w, "–"),
                pick or "–",
                f"{delta:+.1f}",
            ])
            tones[(len(rows) - 1, 6)] = "good" if delta > 0 else ("bad" if delta < 0 else "muted")

        model = TableModel(
            HEADERS, rows,
            palette=self.palette,
            numeric_columns={1, 2, 3, 4, 6},
            sort_values={0: all_weeks[:len(rows)]},
            tones=tones,
        )
        view, _ = make_table(model, stretch_column=5, sort_column=0, row_height=28)
        view.setMinimumHeight(200)
        if self.table is not None:
            self.table.deleteLater()
        self.table = view
        self.table_box.addWidget(view)
