"""Season overview: the headline numbers, the leaderboard and the awards."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import awards as awards_module
from ..charts import BarChart, HistogramChart
from ..widgets import Banner, Card, StatTile, section
from .base import Page


class OverviewPage(Page):
    title = "Overview"
    subtitle = "Where the season stands right now"
    icon = "\N{TROPHY}"

    def build(self) -> None:
        self.header = section(self.title, self.subtitle)
        self.layout_.addWidget(self.header)

        self.banner = Banner()
        self.layout_.addWidget(self.banner)

        # ---- headline tiles ----
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_leader = StatTile("Season Leader")
        self.tile_week = StatTile("Current Week")
        self.tile_pot = StatTile("Pot")
        self.tile_players = StatTile("Players")
        self.tile_avg = StatTile("Pool Average")
        for tile in (
            self.tile_leader, self.tile_week, self.tile_pot,
            self.tile_players, self.tile_avg,
        ):
            tiles.addWidget(tile)
        self.layout_.addLayout(tiles)

        # ---- leaderboard + distribution ----
        row = QHBoxLayout()
        row.setSpacing(12)

        self.leader_card = Card("Top 12 - season wins")
        self.leader_chart = BarChart(self.palette, height=3.9)
        self.leader_card.add(self.leader_chart, 1)
        row.addWidget(self.leader_card, 3)

        self.spread_card = Card("How the pool is bunched")
        self.spread_chart = HistogramChart(self.palette, height=3.9)
        self.spread_card.add(self.spread_chart, 1)
        row.addWidget(self.spread_card, 2)
        self.layout_.addLayout(row)

        # ---- awards ----
        self.awards_card = Card("Season superlatives")
        self.awards_grid = QGridLayout()
        self.awards_grid.setSpacing(10)
        self.awards_card.body().addLayout(self.awards_grid)
        self.layout_.addWidget(self.awards_card)

        self.layout_.addStretch(1)

    def refresh(self) -> None:
        s = self.season
        if s is None:
            return
        self.banner.show_messages(s.warnings)

        order = s.ordered_players()
        if not order:
            for tile in (
                self.tile_leader, self.tile_week, self.tile_pot,
                self.tile_players, self.tile_avg,
            ):
                tile.update_values("-", "No data loaded")
            self.leader_chart.empty("Drop this week's files into data/, then press Refresh")
            self.spread_chart.empty()
            self._fill_awards([])
            return

        leader = order[0]
        tied = [p for p in order if p.wins == leader.wins]
        self.tile_leader.update_values(
            leader.display,
            f"{leader.wins}-{leader.losses}   {leader.pct:.3f}"
            + (f"   (tied with {len(tied) - 1} more)" if len(tied) > 1 else ""),
        )

        weeks = s.final_weeks()
        provisional = f" - week {s.provisional_weeks[0]} in progress" if s.provisional_weeks else ""
        self.tile_week.update_values(
            f"Week {s.current_week}" if s.current_week else "-",
            f"{len(weeks)} week(s) final{provisional}",
        )

        pot = s.pot_total()
        paid_out = sum(p.total_winnings for p in s.players.values())
        self.tile_pot.update_values(
            self.money(pot),
            f"{self.money(paid_out)} paid out so far",
        )

        alive = sum(1 for p in s.players.values() if p.suicide_alive)
        self.tile_players.update_values(
            str(len(s.players)),
            f"{alive} still alive in the suicide pool",
        )

        totals = [p.wins for p in order]
        average = sum(totals) / len(totals) if totals else 0
        above = sum(1 for t in totals if t > average)
        self.tile_avg.update_values(
            f"{average:.1f}",
            f"{above} above the line, {len(totals) - above} below",
        )

        # Leaderboard: the leader takes the accent, the rest a single quiet
        # hue - colour here marks position, not identity.
        top = order[:12]
        best = top[0].wins if top else 0
        colors = [
            self.palette.series[0] if p.wins == best else self.palette.series[2]
            for p in top
        ]
        self.leader_chart.plot(
            [p.display for p in top],
            [p.wins for p in top],
            xlabel="Wins (regular + big loser)",
            colors=colors,
            tooltips=[
                f"{p.display}\n{p.wins}-{p.losses}   {p.pct:.3f}\n"
                f"{p.games_behind:.0f} game(s) back"
                for p in top
            ],
        )
        self.spread_chart.plot(totals, xlabel="Season wins")
        self._fill_awards(awards_module.compute(s))

    def _fill_awards(self, awards: list) -> None:
        while self.awards_grid.count():
            item = self.awards_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not awards:
            note = QLabel("Awards appear once a few weeks have been scored.")
            note.setObjectName("Muted")
            self.awards_grid.addWidget(note, 0, 0)
            return
        for i, award in enumerate(awards):
            self.awards_grid.addWidget(self._award_widget(award), i // 4, i % 4)

    def _award_widget(self, award) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)
        # Icon plus label: the award never relies on colour to be identified.
        heading = QLabel(f"{award.icon}  {award.title}")
        heading.setObjectName("CardTitle")
        winner = QLabel(award.winner)
        winner.setStyleSheet("font-size: 15px; font-weight: 700;")
        value = QLabel(f"{award.value} - {award.detail}")
        value.setObjectName("StatDetail")
        value.setWordWrap(True)
        for w in (heading, winner, value):
            layout.addWidget(w)
        return box
