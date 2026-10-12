"""Teams: the market's power rankings, beside what each team has actually done."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ... import injuries, power
from ..charts import DivergingBarChart
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from .base import Page

HEADERS = ["#", "Team", "Market rating", "Own rating", "Record", "Points a game", "By results",
           "Market v results", "This week", "Injuries"]
(COL_RANK, COL_TEAM, COL_RATING, COL_OWN, COL_RECORD, COL_MARGIN, COL_RESULTS, COL_GAP, COL_NEXT,
 COL_HURT) = range(10)
RANK_TITLE = "Market power rankings"
#: Places apart before the market and the results are said to disagree.
GAP = 8


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class TeamsPage(Page):
    from ...places import TEAMS as title
    subtitle = "Every team by how good the betting market thinks it is, set against what it has actually done"
    icon = "\N{AMERICAN FOOTBALL}"

    def build(self) -> None:
        self.table: QWidget | None = None
        self.layout_.addWidget(section(self.title, self.subtitle))

        self.tile_best = StatTile("Market's Best")
        self.tile_worst = StatTile("Market's Worst")
        self.tile_under = StatTile("Better Than Their Record")
        self.tile_over = StatTile("Worse Than Their Record")
        self._tiles = (self.tile_best, self.tile_worst, self.tile_under, self.tile_over)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.chart_card = Card("Points better than an average team, by the market")
        self.chart = DivergingBarChart(self.palette, height=7.2)
        self.chart_card.add(self.chart, 1)
        self.layout_.addWidget(self.chart_card)

        self.rank_card = Card(RANK_TITLE)
        self.rank_box = QVBoxLayout()
        self.rank_card.body().addLayout(self.rank_box)
        self.rank_note = QLabel("")
        self.rank_note.setObjectName("Muted")
        self.rank_note.setWordWrap(True)
        self.rank_card.add(self.rank_note)
        self.layout_.addWidget(self.rank_card, 1)

    def restyle(self) -> None:
        self.chart.set_palette(self.palette)
        self.refresh_now()

    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        found = power.rankings(season)
        teams = found.teams
        self.clear_layout(self.rank_box)
        self.table = None
        if not teams:
            for tile in self._tiles:
                tile.update_values(self.NO_VALUE, "Needs a week's betting lines")
            self.chart.empty("Appears once a week's betting lines are in")
            self.rank_card.set_title(RANK_TITLE)
            self.rank_note.setText("")
            return

        best, worst = teams[0], teams[-1]
        self.tile_best.update_values(best.team, f"{best.rating:+.1f} points · {best.record}", "good")
        self.tile_worst.update_values(worst.team, f"{worst.rating:+.1f} points · {worst.record}", "bad")
        under = max(teams, key=lambda t: (t.gap, -t.rank))
        over = min(teams, key=lambda t: (t.gap, t.rank))
        self.tile_under.update_values(
            under.team if under.gap >= GAP else self.NO_VALUE,
            f"{self.ordinal(under.rank)} by the market, {self.ordinal(under.results_rank)} by results\n"
            f"{under.record}, {under.margin:+.1f} a game" if under.gap >= GAP else "nobody stands out yet",
        )
        self.tile_over.update_values(
            over.team if over.gap <= -GAP else self.NO_VALUE,
            f"{self.ordinal(over.rank)} by the market, {self.ordinal(over.results_rank)} by results\n"
            f"{over.record}, {over.margin:+.1f} a game" if over.gap <= -GAP else "nobody stands out yet",
        )

        self.chart.plot(
            [t.team for t in teams], [t.rating for t in teams],
            xlabel="Points better (or worse) than an average team on a neutral field",
            value_format=lambda v: f"{v:+.1f}",
            tooltips=[
                f"{t.team}\n{self.ordinal(t.rank)} by the market: {t.rating:+.1f} points\n"
                f"{t.record}, {t.margin:+.1f} a game - {self.ordinal(t.results_rank)} by results"
                for t in teams
            ],
        )

        rows, tones, tips = [], {}, {}
        for r, t in enumerate(teams):
            if t.gap >= GAP:
                gap, tone = f"market rates them {t.gap} places higher", "good"
            elif t.gap <= -GAP:
                gap, tone = f"market rates them {-t.gap} places lower", "bad"
            else:
                gap, tone = "about the same", "muted"
            rows.append([
                t.rank, t.team, f"{t.rating:+.1f}",
                self.NO_VALUE if t.own is None else f"{t.own:+.1f}", t.record, f"{t.margin:+.1f}",
                self.ordinal(t.results_rank), gap, t.next or "bye", injuries.summary(t.code),
            ])
            report = injuries.team(t.code)
            if report:
                tips[(r, COL_HURT)] = "\n".join(i.words() for i in report)
            tones[(r, COL_GAP)] = tone
            tones[(r, COL_RATING)] = "good" if t.rating >= 1.5 else "bad" if t.rating <= -1.5 else ""
        model = TableModel(
            HEADERS, rows, palette=self.palette,
            numeric_columns={COL_RANK, COL_RATING, COL_OWN, COL_MARGIN},
            sort_values={
                COL_RATING: [t.rating for t in teams], COL_MARGIN: [t.margin for t in teams],
                COL_OWN: [t.own if t.own is not None else -99 for t in teams],
                COL_RESULTS: [t.results_rank for t in teams], COL_GAP: [t.gap for t in teams],
            },
            tones=tones, tooltips=tips, bold_columns={COL_TEAM},
        )
        view, _ = make_table(model, stretch_column=COL_HURT, row_height=27)
        self.table = view
        self.rank_box.addWidget(view)
        self.rank_card.set_title(
            f"{RANK_TITLE} - from {_plural(found.games, 'betting line')} over "
            f"{_plural(len(found.weeks), 'week')}, results through week {found.through}"
        )
        seen = injuries.fetched_at()
        self.rank_note.setText(
            "Each betting line says how many points better one team is than another. Put together, the "
            "lines give every team a rating against an average team. A team the market rates well "
            "above its record is one the pool tends to underrate. Own rating is the dashboard's own, "
            "built from final scores only. "
            + ("Injuries are from ESPN's latest report."
               if seen else "The injury report hasn't been read yet. Update lines on This Week reads it.")
        )

    @staticmethod
    def ordinal(n: int) -> str:
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
