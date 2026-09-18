"""The two side pools: Big Loser and Suicide."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ..charts import BarChart
from ..widgets import Card, StatTile, TableModel, make_table, section
from .base import Page

BL_HEADERS = ["#", "Player", "Points", "Wins", "Avg / week"]
SUICIDE_HEADERS = ["Player", "Status", "Latest pick", "Picks made"]


class PoolsPage(Page):
    title = "Side Pools"
    subtitle = "Big Loser standings and who is still alive in the suicide pool"
    icon = "\N{DIRECT HIT}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_bl_leader = StatTile("Big Loser Leader")
        self.tile_alive = StatTile("Suicide Survivors")
        self.tile_out = StatTile("Eliminated")
        self.tile_bl_max = StatTile("Big Loser Picks")
        for t in (self.tile_bl_leader, self.tile_alive, self.tile_out, self.tile_bl_max):
            tiles.addWidget(t)
        self.layout_.addLayout(tiles)

        self.teams_card = Card("Big Loser teams by week")
        self.teams_label = QLabel("")
        self.teams_label.setWordWrap(True)
        self.teams_label.setObjectName("StatDetail")
        self.teams_card.add(self.teams_label)
        self.layout_.addWidget(self.teams_card)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.bl_card = Card("Big Loser pool")
        self.bl_chart = BarChart(self.palette, height=4.2)
        self.bl_card.add(self.bl_chart, 1)
        self.bl_box = QVBoxLayout()
        self.bl_card.body().addLayout(self.bl_box)
        row.addWidget(self.bl_card, 1)

        self.suicide_card = Card("Suicide pool")
        self.suicide_box = QVBoxLayout()
        self.suicide_card.body().addLayout(self.suicide_box)
        row.addWidget(self.suicide_card, 1)
        self.layout_.addLayout(row)

        self.bl_table = None
        self.suicide_table = None

    def refresh(self) -> None:
        s = self.season
        if s is None:
            return
        players = list(s.players.values())
        if not players:
            for t in (self.tile_bl_leader, self.tile_alive, self.tile_out, self.tile_bl_max):
                t.update_values("–", "No data")
            self.bl_chart.empty()
            return

        bl = sorted(players, key=lambda p: (-p.big_loser_points, p.display.lower()))
        alive = [p for p in players if p.suicide_alive]
        out = [p for p in players if not p.suicide_alive]

        best = bl[0].big_loser_points if bl else 0
        leaders = [p.display for p in bl if p.big_loser_points == best and best]
        self.tile_bl_leader.update_values(
            leaders[0] if len(leaders) == 1 else (f"{len(leaders)}-way tie" if leaders else "–"),
            f"{best:g} point(s)" + (f": {', '.join(leaders[:3])}" if len(leaders) > 1 else ""),
        )
        self.tile_alive.update_values(
            str(len(alive)),
            f"of {len(players)} still in",
            "good" if alive else "",
        )
        self.tile_out.update_values(
            str(len(out)),
            ", ".join(sorted(p.display for p in out)[:4]) + ("…" if len(out) > 4 else ""),
        )
        self.tile_bl_max.update_values(
            str(s.max_big_loser_points),
            "picks available each week",
        )

        if s.big_losers_by_week:
            lines = []
            for week in sorted(s.big_losers_by_week):
                teams = ", ".join(t.title() for t in s.big_losers_by_week[week])
                lines.append(f"Week {week}:  {teams}")
            self.teams_label.setText("\n".join(lines))
            self.teams_card.show()
        else:
            self.teams_card.hide()

        scorers = [p for p in bl if p.big_loser_points][:12]
        if scorers:
            self.bl_chart.plot(
                [p.display for p in scorers],
                [p.big_loser_points for p in scorers],
                xlabel="Big Loser points",
                color=self.palette.series[2],
                tooltips=[
                    f"{p.display}\n{p.big_loser_points:g} points across "
                    f"{len(p.weeks_played)} week(s)"
                    for p in scorers
                ],
            )
        else:
            self.bl_chart.empty("No big-loser points recorded yet")

        weeks = max(len(p.weeks_played) for p in players) or 1
        rows = [
            [
                r + 1,
                p.display,
                f"{p.big_loser_points:g}",
                p.big_loser_wins,
                f"{p.big_loser_points / weeks:.2f}",
            ]
            for r, p in enumerate(bl)
        ]
        model = TableModel(
            BL_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 2, 3, 4},
            sort_values={
                0: list(range(len(bl))),
                2: [p.big_loser_points for p in bl],
                4: [p.big_loser_points / weeks for p in bl],
            },
            bold_columns={1},
        )
        view, _ = make_table(model, stretch_column=1, sort_column=0, ascending=True, row_height=27)
        view.setMinimumHeight(260)
        if self.bl_table is not None:
            self.bl_table.deleteLater()
        self.bl_table = view
        self.bl_box.addWidget(view)

        # Suicide pool: status is a word plus a tone, never colour alone.
        ordered = sorted(players, key=lambda p: (not p.suicide_alive, p.display.lower()))
        rows, tones = [], {}
        for r, p in enumerate(ordered):
            latest = max(p.suicide_picks) if p.suicide_picks else None
            rows.append([
                p.display,
                "Alive" if p.suicide_alive else "Eliminated",
                p.suicide_picks.get(latest, "–") if latest else "–",
                len(p.suicide_picks),
            ])
            tones[(r, 1)] = "good" if p.suicide_alive else "bad"
        model = TableModel(
            SUICIDE_HEADERS, rows,
            palette=self.palette,
            numeric_columns={3},
            sort_values={1: [0 if p.suicide_alive else 1 for p in ordered]},
            tones=tones,
            bold_columns={0},
        )
        view, _ = make_table(model, stretch_column=0, sort_column=1, row_height=27)
        view.setMinimumHeight(420)
        if self.suicide_table is not None:
            self.suicide_table.deleteLater()
        self.suicide_table = view
        self.suicide_box.addWidget(view)
