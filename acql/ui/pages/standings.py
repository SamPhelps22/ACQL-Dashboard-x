"""Full season standings, with search and a week-by-week grid."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from ..charts import HeatmapChart
from ..theme import ramp_direction
from ..widgets import Card, TableModel, make_table, section
from .base import Page

HEADERS = [
    "#", "Player", "W", "L", "PCT", "GB", "Net $",
    "This Wk", "Last 3", "Move", "Best", "Avg", "Weeks",
]
NUMERIC = {0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}


class StandingsPage(Page):
    title = "Standings"
    subtitle = "Official positions from the latest stats.xls export"
    icon = "\N{SPORTS MEDAL}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter players…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self._apply_filter)
        controls.addWidget(self.search)
        controls.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        controls.addWidget(self.count_label)
        self.layout_.addLayout(controls)

        self.table_card = Card()
        self.table_container = QVBoxLayout()
        self.table_card.body().addLayout(self.table_container)
        self.layout_.addWidget(self.table_card, 3)
        self.table = None
        self.proxy = None

        self.grid_card = Card("Wins by week")
        self.grid_chart = HeatmapChart(self.palette, height=7.0)
        self.grid_card.add(self.grid_chart, 1)
        self.layout_.addWidget(self.grid_card, 2)

    def _apply_filter(self, text: str) -> None:
        if self.proxy is not None:
            self.proxy.setFilterFixedString(text)
            self._update_count()

    def _update_count(self) -> None:
        if self.proxy is None or self.season is None:
            return
        shown, total = self.proxy.rowCount(), len(self.season.players)
        self.count_label.setText(
            f"{total} players" if shown == total else f"{shown} of {total} players"
        )

    def refresh(self) -> None:
        s = self.season
        if s is None:
            return
        order = s.ordered_players()

        rows, tones, tooltips = [], {}, {}
        for r, p in enumerate(order):
            move = p.rank_movement
            if move is None:
                move_text = "–"
            elif move > 0:
                move_text = f"▲ {move}"
            elif move < 0:
                move_text = f"▼ {abs(move)}"
            else:
                move_text = "–"
            net = p.net_points
            rows.append([
                p.pos or r + 1,
                p.display,
                p.wins,
                p.losses,
                f"{p.pct:.3f}",
                f"{p.games_behind:.0f}" if p.games_behind else "–",
                self.money(net),
                p.current_week_wins or "–",
                p.three_week_wins or "–",
                move_text,
                p.best_week or "–",
                f"{p.average_wins:.1f}" if p.weeks_played else "–",
                len(p.weeks_played),
            ])
            tones[(r, 6)] = "good" if net > 0 else ("bad" if net < 0 else "muted")
            if move is not None and move != 0:
                tones[(r, 9)] = "good" if move > 0 else "bad"
            tooltips[(r, 1)] = (
                f"{p.display}\nBest week {p.best_week}, worst {p.worst_week}\n"
                f"Consistency +/-{p.consistency:.2f}\n"
                f"Big-loser wins {p.big_loser_wins}\n"
                f"Suicide pool: {'alive' if p.suicide_alive else 'eliminated'}"
            )

        sort_values = {
            0: list(range(len(order))),
            4: [p.pct for p in order],
            5: [p.games_behind for p in order],
            6: [p.net_points for p in order],
            7: [p.current_week_wins for p in order],
            8: [p.three_week_wins for p in order],
            9: [p.rank_movement if p.rank_movement is not None else -99 for p in order],
            10: [p.best_week for p in order],
            11: [p.average_wins for p in order],
        }

        model = TableModel(
            HEADERS, rows,
            palette=self.palette,
            numeric_columns=NUMERIC,
            sort_values=sort_values,
            tones=tones,
            tooltips=tooltips,
            bold_columns={1},
        )
        view, proxy = make_table(
            model, stretch_column=1, sort_column=0, ascending=True, row_height=29
        )
        proxy.set_filter_columns([1])
        if self.table is not None:
            self.table.deleteLater()
        self.table, self.proxy = view, proxy
        self.table_container.addWidget(view)
        view.setMinimumHeight(320)
        self._apply_filter(self.search.text())

        # ---- week-by-week grid ----
        weeks = s.played_weeks()
        if not weeks or not order:
            self.grid_chart.empty("No weeks scored yet")
            return
        shown = order[:24]
        values = [
            [
                p.weekly_wins.get(w, p.provisional_wins.get(w))
                for w in weeks
            ]
            for p in shown
        ]
        labels = [
            f"Wk {w}" + ("*" if w in s.provisional_weeks else "") for w in weeks
        ]
        note = " (* in progress)" if s.provisional_weeks else ""
        self.grid_card.set_title(
            f"Wins by week - top {len(shown)} players, "
            f"{ramp_direction(self.palette)} is a better week{note}"
        )
        self.grid_chart.plot(
            [p.display for p in shown],
            labels,
            values,
            cell_text=len(weeks) <= 10,
            tooltip_fn=lambda player, week, v: (
                f"{player} - {week}\n"
                + ("not played" if v is None else f"{v:g} wins")
            ),
        )
