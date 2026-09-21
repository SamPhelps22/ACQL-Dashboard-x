"""Looking back: the patterns behind the scores."""

from __future__ import annotations

import statistics

from PySide6.QtWidgets import QHBoxLayout, QLabel

from ... import analytics
from ..charts import HeatmapChart, LineChart, ScatterChart
from ..widgets import Card, StatTile, section
from .base import Page

H2H_PLAYERS = 12
FORM_TITLE = "Form against consistency"
QUADRANTS = ("Strong and steady", "Strong but streaky", "Steady, but short", "Feast or famine")


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class InsightsPage(Page):
    title = "Insights"
    subtitle = "What the season's numbers say about the pool"
    icon = "\N{LEFT-POINTING MAGNIFYING GLASS}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_home = StatTile("Home Teams")
        self.tile_momentum = StatTile("Momentum")
        self.tile_hard = StatTile("Hardest Week")
        self.tile_easy = StatTile("Easiest Week")
        self._tiles = (self.tile_home, self.tile_momentum, self.tile_hard, self.tile_easy)
        for tile in self._tiles:
            tiles.addWidget(tile, 2 if tile is self.tile_momentum else 1)
        self.layout_.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.form_card = Card(FORM_TITLE)
        self.form_chart = ScatterChart(self.palette, height=4.2)
        self.form_card.add(self.form_chart, 1)
        self.form_note = QLabel(
            "Up is more wins a week; right is bigger swings between weeks. "
            "The dashed lines are the pool's middle."
        )
        self.form_note.setObjectName("Muted")
        self.form_note.setWordWrap(True)
        self.form_card.add(self.form_note)
        row.addWidget(self.form_card, 1)

        self.weeks_card = Card("Week by week - the best, the average and the worst")
        self.weeks_chart = LineChart(self.palette, height=4.2)
        self.weeks_card.add(self.weeks_chart, 1)
        row.addWidget(self.weeks_card, 1)
        self.layout_.addLayout(row)

        self.h2h_card = Card("Head to head")
        self.h2h_chart = HeatmapChart(self.palette, height=6.0)
        self.h2h_card.add(self.h2h_chart, 1)
        self.h2h_note = QLabel(
            "Read across a row: the share of weeks that player outscored the "
            "player in each column, counting ties as half. Blue beats, red "
            "loses, grey is even."
        )
        self.h2h_note.setObjectName("Muted")
        self.h2h_note.setWordWrap(True)
        self.h2h_card.add(self.h2h_note)
        self.layout_.addWidget(self.h2h_card, 2)

    def restyle(self) -> None:
        for chart in (self.form_chart, self.weeks_chart, self.h2h_chart):
            chart.set_palette(self.palette)
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        self._update_home(season)
        self._update_momentum(season)
        profiles = analytics.week_profiles(season)
        self._update_week_tiles(profiles)
        self._update_weeks_chart(profiles)
        self._update_form(season)
        self._update_h2h(season)

    # ---- tiles -----------------------------------------------------------
    def _update_home(self, season) -> None:
        home, decided = analytics.home_record(season)
        if not decided:
            self.tile_home.update_values(self.NO_VALUE, "No results entered yet")
            return
        rate = home / decided
        # 9 home wins in 16 games is 56%, but so is a run of coin flips; say
        # nothing about an edge until there are enough games to mean one.
        if decided < analytics.MIN_HOME_GAMES:
            lean = "too few games yet to call an edge"
        elif rate >= 0.55:
            lean = "home teams have the edge"
        elif rate <= 0.45:
            lean = "road teams have the edge"
        else:
            lean = "no real home edge"
        self.tile_home.update_values(
            self.pct(rate, 0), f"won {home} of {_plural(decided, 'game')}\n{lean}",
        )

    def _update_momentum(self, season) -> None:
        result = analytics.momentum(season)
        if result is None:
            self.tile_momentum.update_values(
                self.NO_VALUE, "Needs a few more weeks of results to measure",
            )
            return
        r, pairs = result
        self.tile_momentum.update_values(
            f"r = {r:+.2f}",
            f"{analytics.describe_momentum(r).capitalize()}\n"
            f"beating the pool one week against the next, {_plural(pairs, 'pair')}",
            "good" if r >= 0.1 else "",
        )

    def _update_week_tiles(self, profiles: list[analytics.WeekProfile]) -> None:
        if not profiles:
            for tile in (self.tile_hard, self.tile_easy):
                tile.update_values(self.NO_VALUE, "No final weeks yet")
            return
        hard = min(profiles, key=lambda w: (w.average, w.week))
        easy = max(profiles, key=lambda w: (w.average, -w.week))
        season_avg = statistics.fmean(w.average for w in profiles)
        if len(profiles) < 2:
            only = profiles[0]
            for tile in (self.tile_hard, self.tile_easy):
                tile.update_values(f"Week {only.week}", "only one final week so far")
            return
        self.tile_hard.update_values(
            f"Week {hard.week}",
            f"pool averaged {hard.average:.1f}, "
            f"{season_avg - hard.average:.1f} under the season norm\n"
            f"best score that week: {hard.best}",
            "bad",
        )
        self.tile_easy.update_values(
            f"Week {easy.week}",
            f"pool averaged {easy.average:.1f}, "
            f"{easy.average - season_avg:.1f} over the season norm\n"
            f"best score that week: {easy.best}",
            "good",
        )

    # ---- charts ----------------------------------------------------------
    def _update_weeks_chart(self, profiles: list[analytics.WeekProfile]) -> None:
        if len(profiles) < 2:
            self.weeks_chart.empty("Appears once two weeks are final")
            return
        weeks = [w.week for w in profiles]
        # The average is the line the other two are read against, so it is
        # the dashed grey reference rather than a third colour - which would
        # otherwise land green on "Worst" and read as good.
        self.weeks_chart.plot(
            weeks,
            [
                ("Best", [w.best for w in profiles]),
                ("Worst", [w.worst for w in profiles]),
            ],
            ylabel="Wins",
            reference=("Average", [round(w.average, 1) for w in profiles]),
            direct_label=True,
        )

    def _update_form(self, season) -> None:
        points = analytics.form_profile(season)
        if len(points) < 4:
            self.form_card.set_title(FORM_TITLE)
            self.form_chart.empty("Appears once players have three weeks each")
            return
        mid_spread = statistics.median(f.spread for f in points)
        mid_average = statistics.median(f.average for f in points)
        leader = season.leader()
        steady_strong = sum(
            1 for f in points if f.average >= mid_average and f.spread <= mid_spread
        )
        self.form_card.set_title(
            f"{FORM_TITLE} - {steady_strong} of {len(points)} strong and steady"
        )
        self.form_chart.plot(
            [(f.player.display, f.spread, f.average) for f in points],
            xlabel="Week-to-week swing (± wins)",
            ylabel="Average wins a week",
            quadrants=(mid_spread, mid_average),
            quadrant_labels=QUADRANTS,
            highlight=leader.display if leader else None,
            tooltips=[
                f"{f.player.display}\n"
                f"averages {f.average:.1f} a week, give or take {f.spread:.1f}\n"
                f"over {_plural(f.weeks, 'week')}"
                for f in points
            ],
        )

    def _update_h2h(self, season) -> None:
        weeks = season.final_weeks()
        order = season.ordered_players()[:H2H_PLAYERS]
        if len(order) < 2 or len(weeks) < 2:
            self.h2h_card.set_title("Head to head")
            self.h2h_chart.empty("Appears once two weeks are final")
            return
        grid = analytics.head_to_head(order, weeks)
        values = [
            [None if m is None or not m.shared else round(m.share * 100) for m in row]
            for row in grid
        ]
        names = [p.display for p in order]
        total = len(season.players)
        self.h2h_card.set_title(
            "Head to head - "
            + (f"top {len(order)} in the standings" if total > len(order) else "every player")
        )

        def tooltip(row_name, col_name, value, grid=grid, names=names):
            if value is None:
                return f"{row_name}" if row_name == col_name else f"{row_name} v {col_name}: no shared weeks"
            m = grid[names.index(row_name)][names.index(col_name)]
            losses = m.shared - m.wins - m.ties
            return (
                f"{row_name} v {col_name}\n"
                f"{m.wins}-{losses}" + (f"-{m.ties}" if m.ties else "")
                + f" over {_plural(m.shared, 'shared week')}\n"
                f"{row_name} won {self.pct(m.share, 0)}"
            )

        self.h2h_chart.plot(
            names, names, values,
            vmin=0, vmax=100, center=50,
            cell_text=len(order) <= 14, cell_format="{:.0f}",
            key_label="% of shared weeks the row player won",
            tooltip_fn=tooltip, tick_rotation=40,
        )
