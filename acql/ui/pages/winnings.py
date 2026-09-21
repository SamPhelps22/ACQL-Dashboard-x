"""The money: what each player has won, week by week, against their buy-in."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...models import Season
from ..charts import DivergingBarChart
from ..widgets import Card, StatTile, TableModel, make_table, section
from .base import Page

FIXED_HEADERS = ["#", "Player", "Buy-in", "Won", "Net", "Weeks cashed"]
NET_COLUMN = 4
FIRST_WEEK_COLUMN = len(FIXED_HEADERS)
CHART_TITLE = "Net position - above the line is in profit"
# Chart this many players from each end; the middle of the pack is flat.
CHART_EXTREMES = 10


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


@dataclass(frozen=True)
class _Standing:
    """One player's money, computed once per refresh."""

    name: str
    won: float                 # everything paid to them across all weeks
    net: float                 # won minus the buy-in, rounded to cents
    weekly: dict[int, float]   # week -> payout, only weeks they were paid


class WinningsPage(Page):
    title = "Winnings"
    subtitle = "Weekly payouts against each player's buy-in"
    icon = "\N{MONEY BAG}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_total = StatTile("Total Won")
        self.tile_best = StatTile("Biggest Week")
        self.tile_top = StatTile("Top Earner")
        self.tile_up = StatTile("In Profit")
        self._tiles = (self.tile_total, self.tile_best, self.tile_top, self.tile_up)
        for tile in self._tiles:
            tiles.addWidget(tile)
        self.layout_.addLayout(tiles)

        self.chart_card = Card(CHART_TITLE)
        self.chart = DivergingBarChart(self.palette, height=5.0)
        self.chart_card.add(self.chart, 1)
        self.layout_.addWidget(self.chart_card, 2)

        self.table_card = Card("Every player, week by week")
        self.table_box = QVBoxLayout()
        self.table_card.body().addLayout(self.table_box)
        self.layout_.addWidget(self.table_card, 2)
        self.table: QWidget | None = None

    def restyle(self) -> None:
        """Follow a theme change without the window rebuilding this page."""
        for chart in (self.chart,):
            chart.set_palette(self.palette)
        # Tables bake the palette into their models, so a refresh rebuilds them.
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        standings = self._standings(season)
        if not standings:
            self._show_empty()
            return

        self._update_tiles(season, standings)
        self._update_chart(season, standings)
        self._update_table(season, standings)

    @staticmethod
    def _standings(season: Season) -> list[_Standing]:
        """Every player, most won first, ties broken alphabetically."""
        buy_in = season.buy_in
        standings = []
        for p in season.players.values():
            # Weekly values can be None or 0 for weeks a player wasn't paid.
            weekly = {w: v for w, v in p.weekly_winnings.items() if v and v > 0}
            won = sum(weekly.values())
            standings.append(_Standing(p.display, won, round(won - buy_in, 2), weekly))
        standings.sort(key=lambda s: (-s.net, s.name.lower()))
        return standings

    @staticmethod
    def _ranks(standings: list[_Standing]) -> list[int]:
        """Competition ranking: players level on net share a rank (1, 2, 2, 4)."""
        ranks: list[int] = []
        rank, last_net = 0, None
        for i, s in enumerate(standings, start=1):
            if s.net != last_net:
                rank, last_net = i, s.net
            ranks.append(rank)
        return ranks

    @classmethod
    def _dollars(cls, value: float) -> str:
        """Compact money for week columns: $110, but $110.50 when there are cents."""
        return f"${value:,.0f}" if float(value).is_integer() else cls.money(value)

    def _show_empty(self) -> None:
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "No data")
        self.chart_card.set_title(CHART_TITLE)
        self.chart.empty()

        self.clear_layout(self.table_box)
        self.table = None
        label = QLabel("No players in this season yet.")
        label.setWordWrap(True)
        self.table_box.addWidget(label)

    def _update_tiles(self, season: Season, standings: list[_Standing]) -> None:
        count = len(standings)
        total = sum(s.won for s in standings)
        ahead = sum(1 for s in standings if s.net > 0)

        if total > 0:
            paid_weeks = {w for s in standings for w in s.weekly}
            self.tile_total.update_values(
                self.money(total),
                f"paid out over {_plural(len(paid_weeks), 'week')}",
            )

            # The biggest single payout; a tie goes to whoever comes first.
            amount, week, name = max(
                ((v, w, s.name) for s in standings for w, v in s.weekly.items()),
                key=lambda c: c[0],
            )
            self.tile_best.update_values(self.money(amount), f"{name} - week {week}")

            top = standings[0]
            self.tile_top.update_values(
                top.name,
                f"{self.money(top.won)} won   {self.money(top.net, signed=True)} net",
                "good" if top.net > 0 else ("bad" if top.net < 0 else ""),
            )
        else:
            for tile in (self.tile_total, self.tile_best, self.tile_top):
                tile.update_values(self.NO_VALUE, "No payouts yet")

        verb = "is" if count == 1 else "are"
        self.tile_up.update_values(
            str(ahead),
            f"of {_plural(count, 'player')} {verb} past the {self.money(season.buy_in)} buy-in",
            "good" if ahead else "",
        )

    def _update_chart(self, season: Season, standings: list[_Standing]) -> None:
        trimmed = len(standings) > 2 * CHART_EXTREMES + 2
        shown = standings[:CHART_EXTREMES] + standings[-CHART_EXTREMES:] if trimmed else standings

        self.chart_card.set_title(
            CHART_TITLE + (f" (top and bottom {CHART_EXTREMES})" if trimmed else "")
        )
        self.chart.plot(
            [s.name for s in shown],
            [s.net for s in shown],
            xlabel="Net position",
            tooltips=[
                f"{s.name}\nWon {self.money(s.won)}\n"
                f"Buy-in {self.money(season.buy_in)}\n"
                f"Net {self.money(s.net, signed=True)}"
                for s in shown
            ],
        )

    def _update_table(self, season: Season, standings: list[_Standing]) -> None:
        buy_in = season.buy_in
        ranks = self._ranks(standings)
        # One column per week that has been played or paid.
        weeks = sorted(set(season.played_weeks()) | {w for s in standings for w in s.weekly})
        headers = FIXED_HEADERS + [f"Wk {w}" for w in weeks]

        rows, tones = [], {}
        for r, (rank, s) in enumerate(zip(ranks, standings)):
            row = [
                rank,
                s.name,
                self.money(buy_in),
                self.money(s.won),
                self.money(s.net, signed=True),
                len(s.weekly),
            ]
            for column, week in enumerate(weeks, start=FIRST_WEEK_COLUMN):
                amount = s.weekly.get(week)
                row.append(self._dollars(amount) if amount else "")
                if amount:
                    tones[(r, column)] = "good"
            rows.append(row)
            tones[(r, NET_COLUMN)] = "good" if s.net > 0 else ("bad" if s.net < 0 else "muted")

        sort_values = {
            0: ranks,
            2: [buy_in] * len(standings),
            3: [s.won for s in standings],
            4: [s.net for s in standings],
        }
        for column, week in enumerate(weeks, start=FIRST_WEEK_COLUMN):
            sort_values[column] = [s.weekly.get(week, 0.0) for s in standings]

        model = TableModel(
            headers,
            rows,
            palette=self.palette,
            numeric_columns={0, 2, 3, 4, 5} | set(range(FIRST_WEEK_COLUMN, len(headers))),
            sort_values=sort_values,
            tones=tones,
            bold_columns={1},
        )

        # Rebuilding the table resets its sort, so carry the user's choice over.
        sort_column, ascending = self._current_sort(len(headers))
        view, _ = make_table(
            model,
            stretch_column=1,
            sort_column=sort_column,
            ascending=ascending,
            row_height=28,
        )
        view.setMinimumHeight(300)

        self.clear_layout(self.table_box)
        self.table = view
        self.table_box.addWidget(view)

    def _current_sort(self, columns: int) -> tuple[int, bool]:
        """The table's current (column, ascending), or the default if unknown."""
        default = (0, True)
        view = self.table
        if view is None or not hasattr(view, "horizontalHeader"):
            return default
        header = view.horizontalHeader()
        column = header.sortIndicatorSection()
        if not 0 <= column < columns:
            return default
        return column, header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder