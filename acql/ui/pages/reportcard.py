"""The Model's report card: how accurate it is, and should you follow it.

The answer first, then the evidence for it in the order anyone would ask:
how often it is right, how that compares with you and the pool, whether its
chances can be trusted, and what fifteen seasons say. The workings live in
acql.reportcard; this file is layout.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout

from ... import reportcard
from ..charts import LineChart
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from ...version import MODEL_NAME
from .base import Page

VERDICT_TITLE = "Should I follow it?"
WEEKS_TITLE = "Week by week - its card against yours"
WEEK_HEADERS = ["Week", f"{MODEL_NAME}'s card", "You", "Pool average", "Week's best",
                f"{MODEL_NAME} would have been", "You were"]
LOSER_TITLE = "Big Losers - its three likeliest against yours"
LOSER_HEADERS = ["Week", f"{MODEL_NAME}'s three", "Its points", "Your points"]
LONG_TITLE = "Over the long run - 2011 to 2025 under this pool's rules"
#: Shared with The Model > Details so both pages remember the same coach.
ME_KEY = "insights/me"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class ReportCardPage(Page):
    title = "Report Card"
    subtitle = f"How accurate {MODEL_NAME} is, and whether to follow it"
    icon = "\N{BAR CHART}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("You are"))
        self.me_picker = QComboBox()
        self.me_picker.setMinimumWidth(200)
        self.me_picker.currentIndexChanged.connect(lambda _: self._render())
        chooser.addWidget(self.me_picker)
        chooser.addStretch(1)
        self.layout_.addLayout(chooser)

        self.verdict_card = Card(VERDICT_TITLE)
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        self.verdict.setTextFormat(Qt.TextFormat.RichText)
        self.verdict_card.add(self.verdict)
        self.layout_.addWidget(self.verdict_card)

        self.tile_right = StatTile("Games Right")
        self.tile_you = StatTile("Against You")
        self.tile_best = StatTile("Week's Best Score")
        self.tile_honest = StatTile("Honest Chances")
        self._tiles = (self.tile_right, self.tile_you, self.tile_best, self.tile_honest)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.weeks_card = Card(WEEKS_TITLE)
        self.weeks_chart = LineChart(self.palette, height=3.0)
        self.weeks_card.add(self.weeks_chart, 1)
        self.weeks_box = QVBoxLayout()
        self.weeks_card.body().addLayout(self.weeks_box)
        self.weeks_note = QLabel(
            "Regular games only, so every card is scored on the same games. "
            f"{MODEL_NAME}'s card is the likeliest side of every game as it stood before "
            "the week's first kickoff - the card This Week recommends. "
            "“Rebuilt” weeks came before cards were kept, and were re-made "
            f"from the stored lines, which is a little kind to {MODEL_NAME}."
        )
        self.weeks_note.setObjectName("Muted")
        self.weeks_note.setWordWrap(True)
        self.weeks_card.add(self.weeks_note)
        self.layout_.addWidget(self.weeks_card, 1)

        self.loser_card = Card(LOSER_TITLE)
        self.loser_summary = QLabel("")
        self.loser_summary.setWordWrap(True)
        self.loser_card.add(self.loser_summary)
        self.loser_box = QVBoxLayout()
        self.loser_card.body().addLayout(self.loser_box)
        self.layout_.addWidget(self.loser_card)

        self.long_card = Card(LONG_TITLE)
        self.long_label = QLabel("")
        self.long_label.setWordWrap(True)
        self.long_label.setTextFormat(Qt.TextFormat.RichText)
        self.long_card.add(self.long_label)
        self.long_box = QVBoxLayout()
        self.long_card.body().addLayout(self.long_box)
        self.long_note = QLabel("")
        self.long_note.setObjectName("Muted")
        self.long_note.setWordWrap(True)
        self.long_card.add(self.long_note)
        self.layout_.addWidget(self.long_card)

    def restyle(self) -> None:
        self.weeks_chart.set_palette(self.palette)
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        wanted = self.me_picker.currentData() or QSettings().value(ME_KEY, "") \
            or QSettings().value("thisweek/suicide_coach", "")
        players = sorted(season.players.values(), key=lambda p: p.display.casefold())
        self.me_picker.blockSignals(True)
        self.me_picker.clear()
        for p in players:
            self.me_picker.addItem(p.display, p.key)
        found = self.me_picker.findData(wanted) if wanted else -1
        self.me_picker.setCurrentIndex(max(found, 0))
        self.me_picker.blockSignals(False)
        self._render()

    def _render(self) -> None:
        season = self.season
        if season is None:
            return
        key = self.me_picker.currentData()
        if key:
            QSettings().setValue(ME_KEY, key)
        name = self.me_picker.currentText() or "you"
        report = reportcard.build(season, key, name)
        self._render_verdict(report)
        self._render_tiles(report)
        self._render_weeks(report)
        self._render_losers(report)
        self._render_long_run(report)

    # ---- the answer ---------------------------------------------------------
    def _render_verdict(self, report: reportcard.Report) -> None:
        colour = getattr(self.palette, "good" if report.tone == "good" else "ink", "")
        bullets = "".join(f"<li>{reason}</li>" for reason in report.reasons)
        self.verdict.setText(
            f"<p style='font-size:20px; font-weight:700;{f' color:{colour};' if colour else ''} margin:0'>"
            f"{report.headline}</p>"
            f"<ul style='margin-top:6px'>{bullets}</ul>"
            f"<p style='margin:0'>This Week plays {MODEL_NAME}'s card by default: the likeliest "
            "side of every game and the three likeliest Big Losers - the most wins toward "
            "the season title. Its card picker also offers <i>most money this week</i>, "
            "which chooses Big Losers the pool isn't on.</p>"
        )

    def _render_tiles(self, report: reportcard.Report) -> None:
        if report.weeks:
            rate, pool = report.model_rate or 0.0, report.pool_rate or 0.0
            self.tile_right.update_values(
                f"{rate:.0%}",
                f"{report.model_total} of {report.games} this season\n"
                f"the pool's average coach: {pool:.0%}",
                "good" if rate > pool else "",
            )
            self.tile_right.show_bar(rate, pool, "good" if rate > pool else "", self.palette)
            lead = report.lead
            if lead is None:
                self.tile_you.update_values(self.NO_VALUE, f"no graded weeks for {report.coach}")
            else:
                self.tile_you.update_values(
                    f"{lead:+d}" if lead else "level",
                    f"games, its card against {report.coach}'s\n"
                    f"{report.model_total} to {report.mine_total}",
                    "good" if lead > 0 else "bad" if lead < 0 else "",
                )
            weeks = len(report.weeks)
            self.tile_best.update_values(
                f"{report.weeks_best} of {weeks}",
                f"weeks it would have had the best score (ties count)\n"
                f"it averaged {_ordinal(round(report.average_place or 0))} of "
                f"{report.weeks[0].entrants + 1}"
                + (f", {report.coach} {_ordinal(round(report.my_average_place))}"
                   if report.my_average_place is not None else ""),
                "good" if report.weeks_best else "",
            )
        else:
            for tile in (self.tile_right, self.tile_you, self.tile_best):
                tile.update_values(self.NO_VALUE, "appears once a week is graded")
            self.tile_right.hide_bar()
        if report.expected is not None and report.graded_picks:
            said = report.honesty
            self.tile_honest.update_values(
                f"{report.graded_hits} of {report.graded_picks}",
                f"it said it would get {report.expected:.1f} right\n{said}",
                "good" if said.startswith("about") else "warning",
            )
        else:
            self.tile_honest.update_values(self.NO_VALUE, "needs a graded week with stored lines")

    # ---- week by week ------------------------------------------------------------
    def _render_weeks(self, report: reportcard.Report) -> None:
        self.clear_layout(self.weeks_box)
        weeks = report.weeks
        if not weeks:
            self.weeks_chart.empty(f"Appears once a week with {MODEL_NAME}'s card is graded")
            return
        x = [w.week for w in weeks]
        series = [(f"{MODEL_NAME}'s card", [w.model for w in weeks])]
        if any(w.mine is not None for w in weeks):
            series.append((report.coach, [w.mine for w in weeks]))
        series.append(("Week's best", [w.best for w in weeks]))
        self.weeks_chart.plot(
            x, series, ylabel="Games right",
            reference=("Pool average", [round(w.pool_average, 1) for w in weeks]),
        )
        rows, tones = [], {}
        for r, w in enumerate(reversed(weeks)):
            rows.append([
                f"{w.week}" + ("  (rebuilt)" if w.rebuilt else ""),
                f"{w.model} of {w.games}",
                w.mine if w.mine is not None else self.NO_VALUE,
                f"{w.pool_average:.1f}",
                w.best,
                ("tied " if w.model_tied else "") + _ordinal(w.model_place)
                + f" of {w.entrants + 1}",
                _ordinal(w.my_place) if w.my_place is not None else self.NO_VALUE,
            ])
            if w.mine is not None:
                tones[(r, 1)] = "good" if w.model > w.mine else "bad" if w.model < w.mine else ""
            if w.model_place == 1:
                tones[(r, 5)] = "good"
        model = TableModel(WEEK_HEADERS, rows, palette=self.palette,
                           numeric_columns={1, 2, 3, 4}, tones=tones, bold_columns={1})
        view, _ = make_table(model, stretch_column=5, row_height=28)
        self.weeks_box.addWidget(view)

    # ---- big losers -------------------------------------------------------------
    def _render_losers(self, report: reportcard.Report) -> None:
        self.clear_layout(self.loser_box)
        found = report.losers
        if not found:
            self.loser_summary.setText(
                "Graded once a week has its pick sheet and its final scores (or "
                "the standings export names the week's big losers) - that is how "
                "the app knows which teams were blown out."
            )
            return
        model = sum(x.model_points for x in found)
        mine = sum(x.mine for x in found)
        self.loser_summary.setText(
            f"Over {_plural(len(found), 'week')} its three likeliest Big Losers scored "
            f"{model}, {report.coach}'s {mine}."
        )
        rows = [[x.week, ", ".join(t.upper() for t in x.model), x.model_points, x.mine]
                for x in reversed(found)]
        table = TableModel(LOSER_HEADERS, rows, palette=self.palette, numeric_columns={2, 3})
        view, _ = make_table(table, stretch_column=1, row_height=28)
        self.loser_box.addWidget(view)

    # ---- the long run -------------------------------------------------------------
    def _render_long_run(self, report: reportcard.Report) -> None:
        from ... import backtest
        self.clear_layout(self.long_box)
        if not report.long_run:
            self.long_label.setText("No long-run results are stored with this copy of the app.")
            self.long_note.setText("")
            return
        found = backtest.Results(report.long_run)
        self.long_label.setText(found.headline_html().split("<br><br>")[0])
        rows = found.week_rows()
        if rows:
            model = TableModel(found.WEEK_HEADERS, rows, palette=self.palette,
                               numeric_columns=set(range(1, len(found.WEEK_HEADERS))),
                               bold_columns={0})
            view, _ = make_table(model, stretch_column=0, row_height=28)
            self.long_box.addWidget(view)
        self.long_note.setText(found.method_note())
