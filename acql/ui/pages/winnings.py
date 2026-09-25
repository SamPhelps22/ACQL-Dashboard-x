"""The money: what each player has won, week by week, against their buy-in."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...models import Season
from ..charts import DivergingBarChart, LineChart
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from .base import Page

FIXED_HEADERS = ["#", "Player", "Buy-in", "Won", "Net", "Weeks cashed"]
# The same table when only season totals are known: no week columns to fill,
# and what each coach paid out in place of the buy-in, because that is what
# stats.xls counts.
SEASON_HEADERS = ["#", "Player", "Won", "Paid out", "Net"]
NET_COLUMN = 4
FIRST_WEEK_COLUMN = len(FIXED_HEADERS)
CHART_TITLE = "Net position - above the line is in profit"
# Chart this many players from each end; the middle of the pack is flat.
CHART_EXTREMES = 10
# Earners traced over the season. Five fixed colour slots stay distinguishable;
# past that the lines tangle and the legend has to do all the work.
TRAJECTORY_PLAYERS = 5
TRAJECTORY_TITLE = "Money over the season - crossing the buy-in line is profit"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def running_totals(weekly: dict[int, float], weeks: list[int]) -> list[float]:
    """A running total across `weeks`, carrying the last value through gaps.

    A week with no payout leaves the total where it was rather than dropping
    it, because money won stays won.
    """
    total, out = 0.0, []
    for week in weeks:
        total += weekly.get(week) or 0.0
        out.append(round(total, 2))
    return out


@dataclass(frozen=True)
class _Standing:
    """One player's money, computed once per refresh."""

    name: str
    won: float                 # everything paid to them across all weeks
    net: float                 # what they are up or down, rounded to cents
    weekly: dict[int, float]   # week -> payout, only weeks they were paid
    paid: float = 0.0          # what they have paid out to others


class WinningsPage(Page):
    title = "Winnings"
    subtitle = "Weekly payouts against each player's buy-in"
    icon = "\N{MONEY BAG}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        self.tile_total = StatTile("Total Won")
        self.tile_best = StatTile("Biggest Week")
        self.tile_top = StatTile("Top Earner")
        self.tile_up = StatTile("In Profit")
        self._tiles = (self.tile_total, self.tile_best, self.tile_top, self.tile_up)
        # Wrapped rather than squeezed: 4 to a row keeps every tile
        # wide enough for its own number on a laptop screen.
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.chart_card = Card(CHART_TITLE)
        self.chart = DivergingBarChart(self.palette, height=5.0)
        self.chart_card.add(self.chart, 1)
        self.layout_.addWidget(self.chart_card, 2)

        # Where the net chart says who is up, this says when they got there.
        self.trajectory_card = Card(TRAJECTORY_TITLE)
        self.trajectory_chart = LineChart(self.palette, height=3.6)
        self.trajectory_card.add(self.trajectory_chart, 1)
        self.layout_.addWidget(self.trajectory_card, 2)

        # Which file the money came from decides what this page can show, so
        # it is settled on every refresh and read by the tiles, the charts and
        # the table alike. Until then, nothing has been read.
        self._source = "none"
        self.table_card = Card("Every player, week by week")
        self.table_box = QVBoxLayout()
        self.table_card.body().addLayout(self.table_box)
        self.layout_.addWidget(self.table_card, 2)
        self.table: QWidget | None = None

    def restyle(self) -> None:
        """Follow a theme change without the window rebuilding this page."""
        for chart in (self.chart, self.trajectory_chart):
            chart.set_palette(self.palette)
        # Tables bake the palette into their models, so a refresh rebuilds them.
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        standings, source = self._standings(season)
        if not standings:
            self._show_empty()
            return

        self._source = source
        self._update_tiles(season, standings)
        self._update_chart(season, standings)
        self._update_trajectory(season, standings)
        self._update_table(season, standings)

    @staticmethod
    def _standings(season: Season) -> tuple[list[_Standing], str]:
        """Every player's money, and which file it came from.

        Two files describe the same money differently, and only one of them
        is usually filled in:

        * The workbook's Winnings sheet gives the week-by-week split, which
          is what this page is built around.
        * stats.xls gives each coach's season totals - won, paid out, net -
          with no weekly breakdown. Standings and the player pages already
          read those, which is why they show money while this page showed
          everyone level at minus the buy-in.

        So the weekly split is used when it exists and the season totals when
        it doesn't, rather than showing nothing because the better of the two
        is missing.
        """
        people = list(season.players.values())
        weekly_known = any(
            v for p in people for v in p.weekly_winnings.values() if v and v > 0
        )
        totals_known = any(
            p.points_won or p.points_paid or p.net_points for p in people
        )

        buy_in = season.buy_in
        standings: list[_Standing] = []
        if weekly_known or not totals_known:
            for p in people:
                # Weekly values can be None or 0 for weeks a player wasn't paid.
                weekly = {w: v for w, v in p.weekly_winnings.items() if v and v > 0}
                won = sum(weekly.values())
                standings.append(
                    _Standing(p.display, won, round(won - buy_in, 2), weekly, buy_in)
                )
            source = "weekly" if weekly_known else "none"
        else:
            for p in people:
                won, paid = p.points_won, abs(p.points_paid)
                net = p.net_points if p.net_points else round(won - paid, 2)
                standings.append(_Standing(p.display, won, round(net, 2), {}, paid))
            source = "season"

        standings.sort(key=lambda s: (-s.net, s.name.lower()))
        return standings, source

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
            tile.hide_bar()
        self.chart_card.set_title(CHART_TITLE)
        self.chart.empty()
        self.trajectory_card.set_title(TRAJECTORY_TITLE)
        self.trajectory_chart.empty("No payouts yet")

        self._source = "none"
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
                f"paid out over {_plural(len(paid_weeks), 'week')}"
                if paid_weeks else "won across the pool so far",
            )

            if paid_weeks:
                # The biggest single payout; a tie goes to whoever comes first.
                amount, week, name = max(
                    ((v, w, s.name) for s in standings for w, v in s.weekly.items()),
                    key=lambda c: c[0],
                )
                self.tile_best.set_title("Biggest Week")
                self.tile_best.update_values(self.money(amount), f"{name} - week {week}")
            else:
                # Without the weekly split there is no biggest week to name,
                # so the tile answers the next question instead: how much of
                # the money has changed hands rather than sat still.
                # There is no biggest week to name without the weekly split,
                # so the tile changes what it answers rather than sitting empty.
                self.tile_best.set_title("Most Won")
                biggest = max(standings, key=lambda s: s.won)
                self.tile_best.update_values(
                    self.money(biggest.won),
                    f"{biggest.name} - most won\n"
                    f"week by week needs the workbook's Winnings sheet",
                )

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
        against = (
            f"past the {self.money(season.buy_in)} buy-in"
            if self._source != "season" else "ahead on the season"
        )
        self.tile_up.update_values(
            str(ahead),
            f"of {_plural(count, 'player')} {verb} {against}",
            "good" if ahead else "",
        )
        # "8" means nothing until you know it is 8 of 35. The bar says the
        # share at a glance, which is the question being asked.
        if count:
            self.tile_up.show_bar(ahead / count, None, "good" if ahead else "bad",
                                  self.palette)
        else:
            self.tile_up.hide_bar()

    def _update_trajectory(self, season: Season, standings: list[_Standing]) -> None:
        """Running winnings for the top earners, against the buy-in."""
        earners = sorted(
            (s for s in standings if s.won > 0),
            key=lambda s: (-s.won, s.name.lower()),
        )[:TRAJECTORY_PLAYERS]
        weeks = sorted(
            set(season.played_weeks()) | {w for s in standings for w in s.weekly}
        )
        if self._source == "season":
            # stats.xls carries each coach's totals and nothing week by week,
            # so there is no line to draw. Saying which file would fill it in
            # beats an empty box that looks broken.
            self.trajectory_card.set_title(TRAJECTORY_TITLE)
            self.trajectory_chart.empty(
                "Season totals only - the week-by-week split lives on the "
                "workbook's Winnings sheet"
            )
            return
        if not earners or len(weeks) < 2:
            self.trajectory_card.set_title(TRAJECTORY_TITLE)
            self.trajectory_chart.empty(
                "No payouts yet" if not earners else "Appears once a second week is paid"
            )
            return

        cashed = sum(1 for s in standings if s.won > 0)
        scope = (
            f"top {len(earners)} of {_plural(cashed, 'earner')}"
            if cashed > len(earners)
            else f"every earner ({cashed})"
        )
        self.trajectory_card.set_title(f"{TRAJECTORY_TITLE}  ({scope})")
        self.trajectory_chart.plot(
            weeks,
            [(s.name, running_totals(s.weekly, weeks)) for s in earners],
            ylabel="Won so far ($)",
            # The buy-in is the line that matters: above it, a player is up.
            reference=(
                f"Buy-in {self.money(season.buy_in)}", [season.buy_in] * len(weeks)
            ),
        )

    def _update_chart(self, season: Season, standings: list[_Standing]) -> None:
        # Everyone who has not cashed yet is at exactly minus the buy-in.
        # Drawn one bar each, that was seventeen identical red bars and the
        # three players with a story squeezed in above them; they are now one
        # bar, "Everyone else (32)", and every earner gets a bar of their own.
        cashed = [s for s in standings if s.won > 0]
        waiting = [s for s in standings if s.won <= 0]
        same = bool(waiting) and all(abs(s.net - waiting[0].net) < 0.005 for s in waiting)
        if same and len(waiting) > 1:
            if len(cashed) > 2 * CHART_EXTREMES + 2:
                cashed = cashed[:CHART_EXTREMES] + cashed[-CHART_EXTREMES:]
            labels = [s.name for s in cashed] + [f"Everyone else ({len(waiting)})"]
            values = [s.net for s in cashed] + [waiting[0].net]
            names = ", ".join(s.name for s in waiting[:12]) + ("\u2026" if len(waiting) > 12 else "")
            tooltips = [self._net_tip(season, s) for s in cashed] + [
                f"{len(waiting)} players who have not cashed yet\n"
                f"each {self.money(waiting[0].net, signed=True)}\n{names}"
            ]
            self.chart_card.set_title(
                f"{CHART_TITLE}  \u00b7  {_plural(len([s for s in standings if s.won > 0]), 'player')} "
                f"cashed, {len(waiting)} still at {self.money(waiting[0].net)}"
            )
        else:
            trimmed = len(standings) > 2 * CHART_EXTREMES + 2
            shown = (
                standings[:CHART_EXTREMES] + standings[-CHART_EXTREMES:]
                if trimmed else standings
            )
            labels = [s.name for s in shown]
            values = [s.net for s in shown]
            tooltips = [self._net_tip(season, s) for s in shown]
            self.chart_card.set_title(
                CHART_TITLE + (f" (top and bottom {CHART_EXTREMES})" if trimmed else "")
            )
        self.chart.plot(labels, values, xlabel="Net position ($)", tooltips=tooltips)

    def _net_tip(self, season: Season, s: _Standing) -> str:
        return (
            f"{s.name}\nWon {self.money(s.won)}\n"
            + (
                f"Paid out {self.money(s.paid)}\n"
                if self._source == "season"
                else f"Buy-in {self.money(season.buy_in)}\n"
            )
            + f"Net {self.money(s.net, signed=True)}"
        )

    def _update_table(self, season: Season, standings: list[_Standing]) -> None:
        buy_in = season.buy_in
        ranks = self._ranks(standings)
        season_only = self._source == "season"
        # One column per week that has been played or paid. With season totals
        # there is nothing to put in them, so they are left off rather than
        # printed empty eighteen times across.
        weeks = (
            []
            if season_only
            else sorted(set(season.played_weeks()) | {w for s in standings for w in s.weekly})
        )
        headers = (
            list(SEASON_HEADERS)
            if season_only
            else FIXED_HEADERS + [f"Wk {w}" for w in weeks]
        )

        rows, tones = [], {}
        for r, (rank, s) in enumerate(zip(ranks, standings)):
            if season_only:
                row = [
                    rank,
                    s.name,
                    self.money(s.won),
                    self.money(s.paid),
                    self.money(s.net, signed=True),
                ]
            else:
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

        if season_only:
            sort_values = {
                0: ranks,
                2: [s.won for s in standings],
                3: [s.paid for s in standings],
                4: [s.net for s in standings],
            }
            numeric = {0, 2, 3, 4}
        else:
            sort_values = {
                0: ranks,
                2: [buy_in] * len(standings),
                3: [s.won for s in standings],
                4: [s.net for s in standings],
            }
            numeric = {0, 2, 3, 4, 5} | set(range(FIRST_WEEK_COLUMN, len(headers)))
        for column, week in enumerate(weeks, start=FIRST_WEEK_COLUMN):
            sort_values[column] = [s.weekly.get(week, 0.0) for s in standings]

        model = TableModel(
            headers,
            rows,
            palette=self.palette,
            numeric_columns=numeric,
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

        self.table_card.set_title(
            "Every player, season totals" if season_only
            else "Every player, week by week"
        )

        self.clear_layout(self.table_box)
        self.table = view
        self.table_box.addWidget(view)

        # Two files describe this money and they are filled in at different
        # times, so the page says which one it read rather than leaving the
        # difference to be guessed at from the shape of the table.
        computed = sorted(getattr(season, "computed_winnings", []))
        if season_only:
            text = (
                "Season totals from stats.xls. The week-by-week split appears "
                "here once the workbook's Winnings sheet is filled in."
            )
        elif computed:
            # The workbook saves these as formulas without results, so they
            # are worked out from the scores by the pool's own rule: a dollar
            # a game for every coach your record differs from, to the best
            # card of the week, shared when it is tied.
            covered = (
                f"{_plural(len(computed), 'week')}"
                if len(computed) > 3 else
                ", ".join(f"week {w}" for w in computed)
            )
            text = (
                f"Worked out from the scores for {covered}, by the pool's rule: "
                f"a dollar a game for every coach your record differs from, paid "
                f"to the week's best card and split when it is tied. Net is "
                f"against the {self.money(buy_in)} buy-in."
            )
        else:
            text = (
                "Week-by-week payouts from the workbook's Winnings sheet, "
                f"against the {self.money(buy_in)} buy-in."
            )
        note = QLabel(text)
        note.setObjectName("Muted")
        note.setWordWrap(True)
        self.table_box.addWidget(note)

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