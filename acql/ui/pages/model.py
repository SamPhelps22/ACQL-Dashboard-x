"""The model: how the dashboard's own picks have done, and whether to trust them.

Three questions, one page, all about the app rather than the pool:

  * Is it right as often as it says? - every graded pick, week by week, and
    its chances sorted into bands to see whether 70% means seven in ten.
  * Should I follow its card? - its whole card each week, kept before the
    first kickoff, scored against the card actually played.
  * Do its rules work over the long run? - the win-the-week planner and the
    suicide helper replayed over the 2010-2025 seasons under this pool's
    rules (backtest.py).
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout

from ... import analytics, cards, pricing
from ..charts import BarChart, LineChart
from ..widgets import Card, TableModel, make_table, section
from .base import Page

MODEL_TITLE = "How the dashboard's own picks are doing"
CALIBRATION_TITLE = "Are its chances honest?"
TRACK_TITLE = "Following the model - its card against yours"
TRACK_KEY = "insights/me"
TRACK_HEADERS = ["Week", "Model's card", "Likeliest side", "You", "Week's best",
                 "Model would have been"]
BACKTEST_TITLE = "Over the long run - 2010 to 2025 under this pool's rules"
#: A band needs this many picks before its colour says anything about it.
CALIBRATION_MIN_PICKS = 20


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class ModelPage(Page):
    title = "The Model"
    subtitle = "How the dashboard's own picks have done, and whether to follow them"
    icon = "\N{BAR CHART}"
    needs_data = False

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        # How the app's own picks have done, which is the one thing on this
        # page that is about the app rather than the pool.
        self.model_card = Card(MODEL_TITLE)
        self.model_chart = LineChart(self.palette, height=3.4)
        self.model_card.add(self.model_chart, 1)
        self.model_note = QLabel("")
        self.model_note.setObjectName("Muted")
        self.model_note.setWordWrap(True)
        self.model_card.add(self.model_note)
        self.layout_.addWidget(self.model_card, 1)

        # The model's whole card each week, kept before kickoff, against the
        # card you really played - the "should I follow it?" question.
        self.track_card = Card(TRACK_TITLE)
        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("You are"))
        self.me_picker = QComboBox()
        self.me_picker.setMinimumWidth(200)
        self.me_picker.currentIndexChanged.connect(lambda _: self._render_track())
        chooser.addWidget(self.me_picker)
        chooser.addStretch(1)
        self.track_card.body().addLayout(chooser)
        self.track_summary = QLabel("")
        self.track_summary.setWordWrap(True)
        self.track_card.add(self.track_summary)
        self.track_box = QVBoxLayout()
        self.track_card.body().addLayout(self.track_box)
        self.track_note = QLabel(
            "The model's card is kept as it stood before the week's first "
            "kickoff - the card This Week showed you - and scored on the 16 "
            "regular games once results are in. \u201cRebuilt\u201d weeks came "
            "before this was kept, and were re-made from the stored lines."
        )
        self.track_note.setObjectName("Muted")
        self.track_note.setWordWrap(True)
        self.track_card.add(self.track_note)
        self.layout_.addWidget(self.track_card)

        self.calibration_card = Card(CALIBRATION_TITLE)
        self.calibration_chart = BarChart(self.palette, height=3.0)
        self.calibration_card.add(self.calibration_chart, 1)
        self.calibration_note = QLabel(
            "A pick that says 70% should come in about seven times in ten. "
            "Landing above what it claims is not a bonus - it means the "
            "chances are understated, and every \"worth it against the field\" "
            "call is made on a wrong number."
        )
        self.calibration_note.setObjectName("Muted")
        self.calibration_note.setWordWrap(True)
        self.calibration_card.add(self.calibration_note)
        self.layout_.addWidget(self.calibration_card, 1)

        # The rules replayed over sixteen seasons: the one answer here that
        # doesn't depend on this season's handful of weeks.
        self.backtest_card = Card(BACKTEST_TITLE)
        self.backtest_label = QLabel("")
        self.backtest_label.setWordWrap(True)
        self.backtest_label.setTextFormat(Qt.TextFormat.RichText)
        self.backtest_card.add(self.backtest_label)
        self.backtest_box = QVBoxLayout()
        self.backtest_card.body().addLayout(self.backtest_box)
        self.backtest_note = QLabel("")
        self.backtest_note.setObjectName("Muted")
        self.backtest_note.setWordWrap(True)
        self.backtest_card.add(self.backtest_note)
        self.layout_.addWidget(self.backtest_card)

    def restyle(self) -> None:
        for chart in (self.model_chart, self.calibration_chart):
            chart.set_palette(self.palette)
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        self._update_model(season)
        self._update_track(season)
        self._update_backtest()

    # ---- following the model -------------------------------------------
    def _update_track(self, season) -> None:
        wanted = self.me_picker.currentData() or QSettings().value(TRACK_KEY, "") \
            or QSettings().value("thisweek/suicide_coach", "")
        players = sorted(season.players.values(), key=lambda p: p.display.casefold())
        self.me_picker.blockSignals(True)
        self.me_picker.clear()
        for p in players:
            self.me_picker.addItem(p.display, p.key)
        found = self.me_picker.findData(wanted) if wanted else -1
        self.me_picker.setCurrentIndex(max(found, 0))
        self.me_picker.blockSignals(False)
        self._render_track()

    def _render_track(self) -> None:
        season = self.season
        self.clear_layout(self.track_box)
        if season is None:
            return
        key = self.me_picker.currentData()
        if key:
            QSettings().setValue(TRACK_KEY, key)
        name = self.me_picker.currentText() or "you"
        scores = cards.history(season, key)
        if not scores:
            self.track_summary.setText(
                "Nothing to score yet. The model's card is kept each week from "
                "This Week, and graded here once the results are in."
            )
            return
        self.track_summary.setText(cards.record(scores).sentence(name))
        rows, tones = [], {}
        for r, sc in enumerate(scores):
            rows.append([
                f"{sc.week}" + ("  (rebuilt)" if sc.rebuilt else ""),
                f"{sc.model} of {sc.games}",
                sc.plain,
                sc.mine if sc.mine is not None else self.NO_VALUE,
                sc.best,
                ("tied " if sc.model_tied else "")
                + ("first" if sc.model_place == 1 else _ordinal(sc.model_place))
                + f" of {sc.entrants + 1}",
            ])
            if sc.mine is not None:
                tones[(r, 1)] = "good" if sc.model > sc.mine else "bad" if sc.model < sc.mine else ""
            tones[(r, 5)] = "good" if sc.model_place == 1 else ""
        model = TableModel(
            TRACK_HEADERS, rows, palette=self.palette,
            numeric_columns={1, 2, 3, 4}, tones=tones, bold_columns={1},
        )
        view, _ = make_table(model, stretch_column=5, row_height=28)
        self.track_box.addWidget(view)

    def _model_entries(self, season) -> list:
        """Every pick the app has made on a week that has since been scored.

        Replayed rather than remembered, by the same rules every page prices
        with (pricing.graded_entries) - so this record, the Every Game page's
        and the chances shown for the week ahead can never disagree.
        """
        return pricing.graded_entries(season)

    def _update_model(self, season) -> None:
        """Week by week: what the picks got, against what they said they would."""
        entries = self._model_entries(season)
        if not entries:
            self.model_card.set_title(MODEL_TITLE)
            self.model_chart.empty(
                "Appears once a week with a predictions file has been scored"
            )
            self.model_note.setText(
                "Load a week's predictions on This Week \u203a Every game and this fills "
                "in as the results come."
            )
            self.calibration_card.set_title(CALIBRATION_TITLE)
            self.calibration_chart.empty("Appears with the record above")
            return

        by_week = analytics.grade_by_week(entries)
        weeks = sorted(by_week)
        card = analytics.grade(entries)
        self.model_card.set_title(
            f"{MODEL_TITLE} - {card.hits} of {card.picks} over "
            f"{_plural(len(weeks), 'week')}"
        )
        self.model_chart.plot(
            weeks,
            [
                ("Got right", [by_week[w].hits for w in weeks]),
                ("Said it would", [round(by_week[w].expected, 1) for w in weeks]),
            ],
            ylabel="Picks",
            zero_baseline=True,
        )
        gap = card.surprise
        self.model_note.setText(
            f"{card.straight_hits} of {card.straight_picks} picking winners"
            + (f", {card.lined_hits} of {card.lined_picks} against the pool's lines"
               if card.lined_picks else "")
            + f". It expected {card.expected:.1f} and got {card.hits}"
            + (" - about right." if abs(gap) < 3
               else " - it is running bold." if gap < 0
               else " - it is running shy.")
        )

        bands = analytics.calibration(entries)
        if not bands:
            self.calibration_card.set_title(CALIBRATION_TITLE)
            self.calibration_chart.empty("Appears once there are picks to sort")
            return
        few = all(band.picks < CALIBRATION_MIN_PICKS for band in bands)
        self.calibration_card.set_title(
            f"{CALIBRATION_TITLE} - {card.picks} picks sorted by what they claimed"
            + (" (too few in each band to judge yet)" if few else "")
        )
        self.calibration_chart.plot(
            [f"said {band.claimed:.0%}" for band in bands],
            [band.actual for band in bands],
            xlabel="Bar: how often it was right  \u00b7  tick: what it said it would be",
            value_format="{:.0%}",
            markers=[band.claimed for band in bands],
            # Colour says whether a band can be judged yet, and which way it
            # errs. A handful of picks proves nothing, so small bands stay
            # neutral; a shy band (better than it claimed) is a caution, and
            # only a bold one - worse than it promised - is marked red.
            colors=[
                self.palette.accent if band.picks < CALIBRATION_MIN_PICKS
                else self.palette.good if abs(band.gap) < 0.05
                else self.palette.warning if band.gap > 0
                else self.palette.critical
                for band in bands
            ],
            tooltips=[
                f"Picks it gave about {band.claimed:.0%}\n"
                f"{band.hits} of {band.picks} came in ({band.actual:.0%})\n"
                + ("about right" if abs(band.gap) < 0.05
                   else f"{abs(band.gap):.0%} "
                        + ("better than it claimed - the chances are shy"
                           if band.gap > 0 else
                           "worse than it claimed - the chances are bold"))
                for band in bands
            ],
        )

    # ---- the long run ----------------------------------------------------
    def _update_backtest(self) -> None:
        from ... import backtest
        self.clear_layout(self.backtest_box)
        found = backtest.stored_results()
        if found is None:
            self.backtest_label.setText(
                "No long-run results are stored with this copy of the app."
            )
            self.backtest_note.setText("")
            return
        self.backtest_label.setText(found.headline_html())
        for headers, rows in ((found.WEEK_HEADERS, found.week_rows()),
                              (found.TABLE_HEADERS, found.table_rows())):
            if not rows:
                continue
            model = TableModel(
                headers, rows, palette=self.palette,
                numeric_columns=set(range(1, len(headers))),
                bold_columns={0},
            )
            view, _ = make_table(model, stretch_column=0, row_height=28)
            self.backtest_box.addWidget(view)
        self.backtest_note.setText(found.method_note())
