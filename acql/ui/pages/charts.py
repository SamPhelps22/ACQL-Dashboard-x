"""The season in pictures: the race, each week, the suicide pool, hot and cold,
the crowd against the results, and how the title odds have moved."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel

from .. import seasoncharts as SC
from ..charts import HeatmapChart, LineChart
from ..funcharts import CrowdChart, FunnelChart, LandedChart, RaceChart
from ..widgets import Card, section
from .base import Page

HIGHLIGHT_KEY = "charts/highlight"
DEFAULT_HIGHLIGHT = "Phelpy"


class ChartsPage(Page):
    title = "Charts"
    subtitle = "The race, each week, the suicide pool, hot and cold streaks, upsets and title odds"
    icon = "\N{CHART WITH UPWARDS TREND}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Highlight"))
        self.highlight = QComboBox()
        self.highlight.setMinimumWidth(200)
        controls.addWidget(self.highlight)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Week"))
        self.week = QComboBox()
        self.week.setMinimumWidth(120)
        controls.addWidget(self.week)
        controls.addStretch(1)
        self.layout_.addLayout(controls)
        self.highlight.currentIndexChanged.connect(lambda _i: self._highlight_changed())
        self.week.currentIndexChanged.connect(lambda _i: self._draw_week())

        self.race_card = Card("The season race - place after each week")
        self.race_chart = RaceChart(self.palette, height=5.0)
        self.race_card.add(self.race_chart, 1)
        self.layout_.addWidget(self.race_card)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.landed_card = Card("Where everyone landed")
        self.landed_chart = LandedChart(self.palette, height=3.4)
        self.landed_card.add(self.landed_chart, 1)
        row.addWidget(self.landed_card, 1)
        self.funnel_card = Card("The suicide pool, week by week")
        self.funnel_chart = FunnelChart(self.palette, height=3.4)
        self.funnel_card.add(self.funnel_chart, 1)
        row.addWidget(self.funnel_card, 1)
        self.layout_.addLayout(row)

        self.hot_card = Card("Hot and cold - each week against the pool's average")
        self.hot_chart = HeatmapChart(self.palette, height=8.0)
        self.hot_card.add(self.hot_chart, 1)
        self.layout_.addWidget(self.hot_card)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.crowd_card = Card("The crowd against the results")
        self.crowd_chart = CrowdChart(self.palette, height=3.6)
        self.crowd_card.add(self.crowd_chart, 1)
        row.addWidget(self.crowd_card, 1)
        self.title_card = Card("Title odds, week by week")
        self.title_chart = LineChart(self.palette, height=3.6)
        self.title_card.add(self.title_chart, 1)
        row.addWidget(self.title_card, 1)
        self.layout_.addLayout(row)

        self._charts = (self.race_chart, self.landed_chart, self.funnel_chart,
                        self.hot_chart, self.crowd_chart, self.title_chart)
        self._filling = False

    def restyle(self) -> None:
        for chart in self._charts:
            chart.set_palette(self.palette)

    # ---- refresh -------------------------------------------------------
    def _chosen(self) -> str:
        return self.highlight.currentData() or ""

    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        weeks = SC.weeks(season)
        self._filling = True
        try:
            settings = QSettings()
            wanted = (self._chosen() or str(settings.value(HIGHLIGHT_KEY, "") or "")
                      or str(settings.value("thisweek/suicide_coach", "") or "") or DEFAULT_HIGHLIGHT)
            names = sorted((p.display for p in season.players.values()), key=str.casefold)
            self.highlight.clear()
            self.highlight.addItem("Nobody", "")
            for name in names:
                self.highlight.addItem(name, name)
            if wanted in names:
                self.highlight.setCurrentIndex(names.index(wanted) + 1)
            shown_week = self.week.currentData()
            self.week.clear()
            for number in reversed(weeks):
                self.week.addItem(f"Week {number}", number)
            if shown_week in weeks:
                self.week.setCurrentIndex(list(reversed(weeks)).index(shown_week))
        finally:
            self._filling = False
        if not weeks:
            for chart in self._charts:
                chart.empty("Charts appear once a week is finished")
            return
        self._draw_all()

    def _highlight_changed(self) -> None:
        if self._filling:
            return
        QSettings().setValue(HIGHLIGHT_KEY, self._chosen())
        self._draw_all()

    def _draw_all(self) -> None:
        season = self.season
        if season is None:
            return
        me = self._chosen()
        weeks, series = SC.race(season)
        self.race_chart.plot(weeks, series, highlight=me)
        self._draw_week()
        rows = SC.funnel(season)
        self.funnel_chart.plot(rows)
        if rows:
            self.funnel_card.set_title(f"The suicide pool, week by week - {rows[-1].left} still in")
        names, cols, values = SC.hot_cold(season)
        self.hot_chart.plot(
            names, [f"Wk {w}" for w in cols], values, center=0, cell_text=True,
            key_label="wins above or below that week's average", cell_format="{:+g}",
            tooltip_fn=lambda name, col, v: f"{name}, {col}: {v:+g} against that week's average",
        )
        self.crowd_chart.plot(SC.crowd(season), highlight_week=self.week.currentData())
        tw, ts = SC.title_history(season, highlight=me)
        self.title_chart.plot(tw, ts, ylabel="Chance of the title (%)")

    def _draw_week(self) -> None:
        season = self.season
        if season is None or self._filling:
            return
        number = self.week.currentData()
        made = SC.landed(season, number) if number else None
        if made is None:
            self.landed_chart.empty("No scores for this week yet")
            return
        self.landed_card.set_title(f"Where everyone landed - week {made.week}")
        self.landed_chart.plot(made.scores, winners=made.winners, average=made.average,
                               highlight=self._chosen(), week=made.week)
        self.crowd_chart.plot(SC.crowd(season), highlight_week=number)
