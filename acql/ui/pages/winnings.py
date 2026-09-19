"""The money: who is up, who is down, and what the pot has paid out."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from ..charts import DivergingBarChart
from ..widgets import Card, StatTile, TableModel, make_table, section
from .base import Page

HEADERS = ["#", "Player", "Buy-in", "Won", "Net", "Weeks cashed", "Best week"]


class WinningsPage(Page):
    title = "Winnings"
    subtitle = "Buy-ins, payouts and where everyone stands"
    icon = "\N{MONEY BAG}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_pot = StatTile("Total Pot")
        self.tile_paid = StatTile("Paid Out")
        self.tile_held = StatTile("Still Held")
        self.tile_up = StatTile("In Profit")
        for t in (self.tile_pot, self.tile_paid, self.tile_held, self.tile_up):
            tiles.addWidget(t)
        self.layout_.addLayout(tiles)

        self.chart_card = Card("Net position - above the line is in profit")
        self.chart = DivergingBarChart(self.palette, height=5.0)
        self.chart_card.add(self.chart, 1)
        self.layout_.addWidget(self.chart_card, 2)

        self.table_card = Card("Every player")
        self.table_box = QVBoxLayout()
        self.table_card.body().addLayout(self.table_box)
        self.layout_.addWidget(self.table_card, 2)
        self.table = None

    def refresh(self) -> None:
        s = self.season
        if s is None:
            return
        players = sorted(
            s.players.values(),
            key=lambda p: (-p.net(s.buy_in), p.display.lower()),
        )
        if not players:
            for t in (self.tile_pot, self.tile_paid, self.tile_held, self.tile_up):
                t.update_values("–", "No data")
            self.chart.empty()
            return

        pot = s.pot_total()
        paid = sum(p.total_winnings for p in players)
        up = [p for p in players if p.net(s.buy_in) > 0]

        self.tile_pot.update_values(
            self.money(pot),
            f"{len(players)} players at {self.money(s.buy_in)} each",
        )
        self.tile_paid.update_values(self.money(paid), f"{paid / pot * 100:.0f}% of the pot" if pot else "")
        self.tile_held.update_values(self.money(pot - paid), "still to be played for")
        self.tile_up.update_values(
            f"{len(up)}",
            f"of {len(players)} players are ahead",
            "good" if up else "",
        )

        # Chart the extremes; the middle of the pack is flat and uninformative.
        shown = players[:10] + players[-10:] if len(players) > 22 else players
        self.chart_card.set_title(
            "Net position - above the line is in profit"
            + (" (top and bottom 10)" if len(shown) < len(players) else "")
        )
        self.chart.plot(
            [p.display for p in shown],
            [p.net(s.buy_in) for p in shown],
            xlabel="Net position",
            tooltips=[
                f"{p.display}\nWon {self.money(p.total_winnings)}\n"
                f"Buy-in {self.money(s.buy_in)}\nNet {self.money(p.net(s.buy_in))}"
                for p in shown
            ],
        )

        rows, tones = [], {}
        for r, p in enumerate(players):
            net = p.net(s.buy_in)
            cashed = [w for w, v in p.weekly_winnings.items() if v and v > 0]
            best = max(p.weekly_winnings.values(), default=0.0)
            rows.append([
                r + 1,
                p.display,
                self.money(s.buy_in),
                self.money(p.total_winnings),
                self.money(net),
                len(cashed),
                self.money(best) if best else "–",
            ])
            tones[(r, 4)] = "good" if net > 0 else ("bad" if net < 0 else "muted")

        model = TableModel(
            HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 2, 3, 4, 5, 6},
            sort_values={
                0: list(range(len(players))),
                2: [s.buy_in] * len(players),
                3: [p.total_winnings for p in players],
                4: [p.net(s.buy_in) for p in players],
                6: [max(p.weekly_winnings.values(), default=0.0) for p in players],
            },
            tones=tones,
            bold_columns={1},
        )
        view, _ = make_table(model, stretch_column=1, sort_column=0, ascending=True, row_height=28)
        view.setMinimumHeight(300)
        if self.table is not None:
            self.table.deleteLater()
        self.table = view
        self.table_box.addWidget(view)
