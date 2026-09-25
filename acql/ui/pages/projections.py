"""Looking ahead: who can still win, and how likely each of them is to."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import analytics
from ...config import WEEKS_IN_SEASON
from ..charts import BarChart
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from .base import Page

HEADERS = ["#", "Player", "Wins", "Pace / wk", "Projected", "Best case",
           "Title", "Top 3", "Status"]
ODDS_CHART_SIZE = 10
# Below this the bar is invisible and the label reads 0.0%; it adds nothing.
ODDS_FLOOR = 0.005

GOOD_STATUSES = {"Leader", "Co-leader", "Clinched", "Champion"}
OUT_STATUSES = {"Out of the title race", "Final"}

METHOD_NOTE = (
    "Odds come from {sims:,} simulated finishes to the season. In each one, "
    "every remaining week a player scores one of their own past weeks, picked "
    "at random - blended with the whole pool's weeks until they have about "
    "half a season of their own, so one hot week doesn't make a favourite. "
    "Best case assumes a perfect {per_week}-win week, every week."
)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class ProjectionsPage(Page):
    title = "Projections"
    subtitle = "Title odds, the magic number, and who can still catch the leader"
    icon = "\N{CRYSTAL BALL}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.table: QWidget | None = None

        self.layout_.addWidget(section(self.title, self.subtitle))

        self.tile_favourite = StatTile("Title Favourite")
        self.tile_left = StatTile("Weeks Left")
        self.tile_alive = StatTile("Still In It")
        self.tile_magic = StatTile("Magic Number")
        self._tiles = (self.tile_favourite, self.tile_left, self.tile_alive, self.tile_magic)
        # Wrapped rather than squeezed: 4 to a row keeps every tile
        # wide enough for its own number on a laptop screen.
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        row = QHBoxLayout()
        row.setSpacing(12)
        self.title_card = Card("Chance of winning the title")
        self.title_chart = BarChart(self.palette, height=4.0)
        self.title_card.add(self.title_chart, 1)
        row.addWidget(self.title_card, 1)

        self.top3_card = Card("Chance of a top-three finish")
        self.top3_chart = BarChart(self.palette, height=4.0)
        self.top3_card.add(self.top3_chart, 1)
        row.addWidget(self.top3_card, 1)
        self.layout_.addLayout(row)

        self.table_card = Card("Every player's outlook")
        self.table_box = QVBoxLayout()
        self.table_card.body().addLayout(self.table_box)
        self.method = QLabel("")
        self.method.setObjectName("Muted")
        self.method.setWordWrap(True)
        self.table_card.body().addWidget(self.method)
        self.layout_.addWidget(self.table_card, 2)

    def restyle(self) -> None:
        for chart in (self.title_chart, self.top3_chart):
            chart.set_palette(self.palette)
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        summary = analytics.race(season)
        if not summary.outlooks:
            self._show_empty()
            return
        self._update_tiles(summary)
        self._update_charts(summary)
        self._update_table(summary)
        self.method.setText(
            METHOD_NOTE.format(sims=summary.simulations, per_week=summary.per_week)
        )

    def _show_empty(self) -> None:
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "No data")
            tile.hide_bar()
        self.title_chart.empty("Projections appear once a week is scored")
        self.top3_chart.empty("Projections appear once a week is scored")
        self.clear_layout(self.table_box)
        self.table = None
        self.method.setText("")

    def _update_tiles(self, summary: analytics.RaceSummary) -> None:
        favourite = summary.outlooks[0]
        if summary.remaining == 0:
            champions = [o for o in summary.outlooks if o.status == "Champion"]
            self.tile_favourite.update_values(
                champions[0].player.display if len(champions) == 1
                else f"{len(champions)}-way tie",
                "season over - champion" if len(champions) == 1 else "season over - shared title",
                "good",
            )
        else:
            played = WEEKS_IN_SEASON - summary.remaining
            early = "\nearly days - these odds will move a lot" if played < analytics.EARLY_WEEKS else ""
            self.tile_favourite.update_values(
                favourite.player.display,
                f"{self.pct(favourite.title_odds, 0)} to win the title\n"
                f"{favourite.wins} wins, on pace for {favourite.projected:.0f}{early}",
                "good",
            )

        played = WEEKS_IN_SEASON - summary.remaining
        total = len(summary.outlooks)
        if summary.remaining == 0:
            self.tile_left.update_values("0", f"all {WEEKS_IN_SEASON} weeks final - season complete")
            self.tile_alive.update_values(self.NO_VALUE, "the title is decided")
            self.tile_alive.hide_bar()
        else:
            self.tile_left.update_values(
                str(summary.remaining),
                f"{played} of {WEEKS_IN_SEASON} weeks final\n"
                f"up to {summary.remaining * summary.per_week} wins still available",
            )
            self.tile_alive.update_values(
                str(summary.in_contention),
                f"of {_plural(total, 'player')} can still finish first",
                "good" if summary.in_contention > 1 else "",
            )
            # How open the title still is, as a share of the pool - the bar
            # shrinking week by week is the shape of a season closing.
            if total:
                self.tile_alive.show_bar(
                    summary.in_contention / total, None,
                    "good" if summary.in_contention > 1 else "warning",
                    self.palette,
                )

        leader, chaser = summary.leader, summary.chaser
        if summary.magic_number is None:
            self.tile_magic.update_values(self.NO_VALUE, "season over")
        elif summary.magic_number == 0:
            self.tile_magic.update_values(
                "0", f"{leader.display} has clinched the title", "good",
            )
        else:
            self.tile_magic.update_values(
                str(summary.magic_number),
                f"each {leader.display} win, and each game\n"
                f"{chaser.display} misses, takes one off. At 0, it's clinched.",
            )

    def _update_charts(self, summary: analytics.RaceSummary) -> None:
        p = self.palette
        for chart, card, attr, base_title in (
            (self.title_chart, self.title_card, "title_odds", "Chance of winning the title"),
            (self.top3_chart, self.top3_card, "top3_odds", "Chance of a top-three finish"),
        ):
            ranked = sorted(
                (o for o in summary.outlooks if getattr(o, attr) >= ODDS_FLOOR),
                key=lambda o: (-getattr(o, attr), -o.wins, o.player.display.lower()),
            )[:ODDS_CHART_SIZE]
            if not ranked:
                card.set_title(base_title)
                chart.empty("Nobody has a realistic chance")
                continue
            hidden = sum(1 for o in summary.outlooks if 0 < getattr(o, attr) < ODDS_FLOOR)
            card.set_title(
                base_title + (f"  ({hidden} more under 0.5%)" if hidden else "")
            )
            best = getattr(ranked[0], attr)
            chart.plot(
                [o.player.display for o in ranked],
                [getattr(o, attr) for o in ranked],
                xlabel="Probability",
                # The favourite takes the accent, the field one quiet hue.
                colors=[
                    p.series_color(0) if getattr(o, attr) == best else p.series_color(2)
                    for o in ranked
                ],
                value_format="{:.1%}",
                tooltips=[
                    f"{o.player.display}\n"
                    f"Title {self.pct(o.title_odds)}  ·  top three {self.pct(o.top3_odds)}\n"
                    f"{o.wins} wins now, on pace for {o.projected:.0f}\n{o.status}"
                    for o in ranked
                ],
            )

    def _update_table(self, summary: analytics.RaceSummary) -> None:
        # The table is in standings order: odds sit beside where people are.
        rows_in = sorted(
            summary.outlooks,
            key=lambda o: (-o.wins, -o.title_odds, o.player.display.lower()),
        )
        rows, tones = [], {}
        rank, last = 0, None
        ranks = []
        for i, o in enumerate(rows_in, start=1):
            if o.wins != last:
                rank, last = i, o.wins
            ranks.append(rank)
        for r, (o, place) in enumerate(zip(rows_in, ranks)):
            rows.append([
                place,
                o.player.display,
                o.wins,
                f"{o.pace:.2f}",
                f"{o.projected:.0f}",
                o.best_case,
                self._odds_text(o.title_odds, eliminated=o.status == "Out of the title race"),
                # Out of the title race is not out of the top three, so the
                # Top 3 column never says "out" - it shows the number.
                self._odds_text(o.top3_odds),
                o.status,
            ])
            if o.status in GOOD_STATUSES:
                tones[(r, 8)] = "good"
            elif o.status in OUT_STATUSES:
                tones[(r, 8)] = "muted"
            if o.title_odds >= ODDS_FLOOR:
                tones[(r, 6)] = "good"
            elif o.status == "Out of the title race":
                tones[(r, 6)] = "muted"

        model = TableModel(
            HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 2, 3, 4, 5, 6, 7},
            sort_values={
                0: ranks,
                3: [o.pace for o in rows_in],
                4: [o.projected for o in rows_in],
                6: [o.title_odds for o in rows_in],
                7: [o.top3_odds for o in rows_in],
            },
            tones=tones,
            bold_columns={1},
        )
        sort_column, ascending = self._current_sort()
        view, _ = make_table(
            model, stretch_column=1, sort_column=sort_column,
            ascending=ascending, row_height=28,
        )
        self.clear_layout(self.table_box)
        self.table = view
        self.table_box.addWidget(view)

    def _odds_text(self, odds: float, *, eliminated: bool = False) -> str:
        """Odds in words where a number would mislead.

        "0.0%" for someone mathematically out reads as "almost no chance";
        the true answer is none, so it says so. Likewise a sliver of a chance
        is shown as under 0.1% rather than rounded down to nothing.
        """
        if odds == 0:
            return "out" if eliminated else "0%"
        if odds >= 0.9995:
            return "100%"
        if odds < 0.001:
            return "<0.1%"
        return self.pct(odds)

    def _current_sort(self) -> tuple[int, bool]:
        default = (0, True)
        view = self.table
        if view is None or not hasattr(view, "horizontalHeader"):
            return default
        header = view.horizontalHeader()
        column = header.sortIndicatorSection()
        if not 0 <= column < len(HEADERS):
            return default
        return column, header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder