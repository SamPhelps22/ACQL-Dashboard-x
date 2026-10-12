"""The model's charts: Deadeye's season drawn seven ways (showcase.py has the numbers)."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel

from ... import showcase
from ...places import MODEL_CHARTS as title_
from ...version import MODEL_NAME
from ..modelcharts import CalibrationChart, MatrixChart, RollingChart, ScopeChart, ThinBars, TrajectoryChart
from ..widgets import Card, section
from .base import Page

EMPTY = "Appears once a week with betting lines has been graded"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class ModelChartsPage(Page):
    title = title_
    subtitle = f"{MODEL_NAME}'s season in seven pictures - who is ahead, whether its chances are honest, and where it misses"
    icon = "\N{CHART WITH UPWARDS TREND}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        self.lead = QLabel("")
        self.lead.setObjectName("Muted")
        self.lead.setWordWrap(True)
        self.layout_.addWidget(self.lead)

        self.trajectory = TrajectoryChart(self.palette, height=3.5)
        self.truth = CalibrationChart(self.palette, height=3.3)
        self.confidence = ThinBars(self.palette, height=3.3)
        self.matrix = MatrixChart(self.palette, height=4.5)
        self.scope = ScopeChart(self.palette, height=4.5)
        self.hot_hand = RollingChart(self.palette, height=3.2)
        self.misses = ThinBars(self.palette, height=3.2)
        self._charts = (self.trajectory, self.truth, self.confidence, self.matrix, self.scope,
                        self.hot_hand, self.misses)
        self.notes: dict[str, QLabel] = {}

        def card(key: str, heading: str, chart) -> Card:
            made = Card(heading)
            made.add(chart, 1)
            note = QLabel("")
            note.setObjectName("Muted")
            note.setWordWrap(True)
            made.add(note)
            self.notes[key] = note
            return made

        self.layout_.addWidget(card("trajectory", "The Mission Trajectory - who is ahead, pick by pick", self.trajectory))
        for left, right in (
            (card("truth", "The Truth Test - what it said against what happened", self.truth),
             card("confidence", "Confidence vs. Reality - how often each kind of pick came in", self.confidence)),
            (card("matrix", "The Performance Matrix - where it does well and badly", self.matrix),
             card("scope", "The Accuracy Scope - the margin it expected against the one that happened", self.scope)),
            (card("hot", "The Hot-Hand Monitor - its latest picks against plain luck", self.hot_hand),
             card("miss", "The Miss Report - how far off its margins were", self.misses)),
        ):
            row = QHBoxLayout()
            row.setSpacing(16)
            row.addWidget(left, 1)
            row.addWidget(right, 1)
            self.layout_.addLayout(row)

    def restyle(self) -> None:
        for chart in self._charts:
            chart.set_palette(self.palette)
        self.refresh_now()

    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        found = showcase.build(season)
        games = len(found.games)
        self.lead.setText(
            f"{_plural(games, 'graded pick')} over {_plural(len(found.weeks), 'week')}. \u201cRight\u201d "
            f"means the pick got the pool's point. Hover over any mark to see the game."
            if games else EMPTY + ".")

        # ---- who is ahead
        self.trajectory.plot(found.trajectory)
        lines = found.trajectory.lines
        if lines:
            self.notes["trajectory"].setText(
                "A line goes up when a pick comes in and down when it doesn't. Above zero is beating a coin "
                "flip, and the gap between two lines is the lead. So far: "
                f"{', '.join(f'{line.name} {line.right} of {line.picks} ({line.rate:.0%})' for line in lines)}.")
        else:
            self.notes["trajectory"].setText("")

        # ---- are its chances honest
        self.truth.plot(found.calibration)
        self.notes["truth"].setText(
            "Each dot is a group of picks it gave about the same chance. Across is what it said; up is "
            "how often they came in. Dots on the line are exactly right. The whiskers show how far "
            "luck alone can move a dot."
            if found.calibration else "")
        bands = [b for b in found.buckets if b.picks]
        if bands:
            self.confidence.plot(
                [f"{b.label}  ·  {_plural(b.picks, 'pick')}" for b in bands], [b.rate for b in bands],
                value_format="{:.0%}", markers=[b.said for b in bands],
                marker_label="What its chances said",
                tooltips=[f"Picks it called {b.label}: {b.right} of {b.picks} came in ({b.rate:.0%})\n"
                          f"its chances said {b.said:.0%}" for b in bands],
            )
            empty = [b.label for b in found.buckets if not b.picks]
            self.notes["confidence"].setText(
                "The bar is how often each kind of pick came in. The tick is what it expected. "
                "Surer picks should have longer bars."
                + (f" No picks yet at {', '.join(empty)}." if empty else ""))
        else:
            self.confidence.empty(EMPTY)
            self.notes["confidence"].setText("")

        # ---- where it does well and badly
        self.matrix.plot(found.matrix, MODEL_NAME)
        self.notes["matrix"].setText(
            f"Each row is one kind of game: how often {MODEL_NAME}'s pick came in, what the betting line "
            f"did on the same games, and what it expected. Red is worse than a coin flip, blue is "
            f"better. Rows under {showcase.CELL} picks are left unshaded: too few to judge."
            if found.matrix else "")
        self.scope.plot(found.scope)
        if found.scope:
            off = showcase.mean_error(found.scope)
            far = sum(1 for q in found.scope if q.error >= 14)
            self.notes["scope"].setText(
                f"Each mark is a game. Across is the margin {MODEL_NAME} expected; up is what happened. On "
                f"the line it was exactly right. On average it was {off:.1f} points off, and "
                f"{_plural(far, 'game')} of {len(found.scope)} missed by 14 or more. That is normal: "
                "nobody gets margins closer than about ten points.")
        else:
            self.notes["scope"].setText("")

        # ---- lately
        self.hot_hand.plot(found.rolling)
        roll = found.rolling
        if roll.picks:
            inside = abs(roll.rate[-1] - roll.said[-1]) <= roll.reach[-1]
            self.notes["hot"].setText(
                f"Its last {roll.window} picks: {roll.rate[-1]:.0%} right, where it expected "
                f"{roll.said[-1]:.0%}. The grey band is what luck alone covers. "
                + ("It is running about as expected." if inside else
                   "It is running " + ("hot" if roll.rate[-1] > roll.said[-1] else "cold") + " for now."))
        else:
            self.notes["hot"].setText("")
        sizes = found.miss_sizes
        if sum(n for _label, n, _line in sizes):
            total = sum(n for _label, n, _line in sizes)
            self.misses.plot(
                [f"{label} points" for label, _n, _line in sizes], [float(n) for _label, n, _line in sizes],
                value_format="{:.0f}", markers=[float(line) for _label, _n, line in sizes], xlabel="Games",
                marker_label="The betting line's own",
                tooltips=[f"Off by {label} points: {n} of {total} games ({n / total:.0%})\n"
                          f"the betting line's own margin: {line}" for label, n, line in sizes],
            )
            close = sizes[0][1] + sizes[1][1]
            self.notes["miss"].setText(
                f"How far the final margin was from what it expected, over {_plural(total, 'game')}: "
                f"{close} within a touchdown, {sizes[-2][1] + sizes[-1][1]} off by two scores or more. "
                "The tick on each bar is the betting line's count.")
        else:
            self.misses.empty("Appears once final scores are in for a week with betting lines")
            self.notes["miss"].setText("")
