"""The Model Lab: every recipe on the same games, its form, the week's misses, the record kept, and what has changed."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QLabel, QPushButton, QTabBar, QVBoxLayout, QWidget,
)

import time

from ...model import challengers, closing, contenders, ledger, modellab, pfmcheck
from ...feeds import nflverse, oddslock, results
from ...places import LAB as title_
from ...version import MODEL_NAME, VERSION
from ...wording import plural as _plural
from ..modelcharts import FormChart
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from .base import Page
from .forecastlog import ForecastLogView

HEADERS = ["Recipe", "Credited", "Winners", "On pool lines", "Avg miss", "Log loss", "Standing", "Goes on"]
DUEL_TITLE = f"Head to head with {MODEL_NAME} - the games they split"
DUEL_HEADERS = ["Recipe", "Same games", "Only it was right", f"Only {MODEL_NAME} was right", "Net", "Log loss",
                "Could it be luck?"]
PARTS_TITLE = "What each ingredient adds"
PARTS_HEADERS = ["Ingredient", "With it", "Without it", "Same games", "Split games", "Log loss", "Reading"]
CALIB_TITLE = "Calibration - did the chances come in?"
COVER_TITLE = "Coverage - which games each recipe could price, and why not the rest"
COVER_HEADERS = ["Recipe", "Priced", "Not priced", "Why", "On the games every recipe priced"]
KINDS_TITLE = "Market, football or both - every season on games none of them had seen"
KINDS_HEADERS = ["Kind of model", "Winners", "Avg miss", "Against the closing spread", "When 2+ points from it"]
KINDS_BY_SEASON = "The same, season by season - winners picked"
SEASONS_TITLE = "Season by season - taught on the seasons before, asked about the next"
SEASONS_HEADERS = ["Season", "Games", "Ratings alone", contenders.ANALYST, contenders.MACHINE, "Avg miss (points)"]
VALUE_HEADERS = ["Week", "Game", "Took", "Line at the deadline", "Line at kickoff", "Moved"]
LAB_TITLE = "Every recipe, on the same games"
FORM_TITLE = "Straight up, and against the pool's line - the season beside the last four weeks"
FORM_HEADERS = ["Recipe", "Winners", "Winners, last 4 wks", "On pool lines", "Pool lines, last 4 wks", "Winners lately",
                "Right when most missed"]
SHOCKS_TITLE = "The week's biggest misses - every recipe, not only the one in service"
SHOCKS_HEADERS = ["Week", "What", "Game", "Most recipes took", "They expected", "It finished", "Had it right"]
RECORD_TITLE = "The record - each recipe's number, written down when the cards went in"
RECORD_HEADERS = ["Week", "Odds locked", "Written down", "Standing", "Games", "Against today's replay"]
#: Weeks of misses listed, newest first.
SHOCK_WEEKS = 4
#: A record on fewer games than this is shown in grey: too few to rank on.
FEW = 20
VALUE_TITLE = "Closing line value - did the line come round to the picks?"
TAUGHT_TITLE = "Challengers taught on past seasons - is any clearly better than the rule in use?"
PFM_TITLE = "Pro Football Mania's ratings - do they add anything to the card? (shadow only)"
PFM_WEEK_TITLE = "This week beside PFM - the shadow chance is not a pick"
WEEKS_TITLE = "Week by week - each recipe's record, on the games it priced"
#: The page's views. It had grown to eight tiles and sixteen cards on one
#: scroll, answering four different questions; each now has a view of its own.
VIEWS = (
    ("Scoreboard", "Every recipe on the same games: who leads, head to head, and week by week"),
    ("Form & misses", "Straight up and against the pool's line, the last four weeks, and each week's biggest misses"),
    ("Long run", "Market, football or both: every season since 2011, on games none of them had seen"),
    ("The record", "What was written down before kickoff, the closing line, coverage, and what has changed"),
    ("Outside forecasts", "Any model's forecasts, kept with the time they were made, scored on the same games - "
                          "CSV in and out"),
)
SCORE, FORM, LONG, RECORD, OUTSIDE = range(len(VIEWS))
#: Which view was open last.
VIEW_KEY = "modellab/view"


def _record(tally: modellab.Tally, none: str) -> str:
    """A record with its size and how far luck alone moves one that size: "49 of 77, 64%, give or take 11"."""
    if not tally.games:
        return none
    return f"{tally.right} of {tally.games} \u00b7 {tally.rate:.0%} \u00b1{tally.reach * 100:.0f}"


def _by(points: float | None, none: str, *, behind: str = "lost by", places: int = 0) -> str:
    """A margin from one side: "by 7", "lost by 3", "level"."""
    if points is None:
        return none
    if abs(points) < 0.25:
        return "level"
    return f"{'by' if points > 0 else behind} {abs(points):.{places}f}"


def _when(at: float) -> str:
    """"Thu Oct 8, 6:04 PM" on this computer's clock."""
    if not at:
        return ""
    t = time.localtime(at)
    return (f"{time.strftime('%a %b', t)} {t.tm_mday}, {t.tm_hour % 12 or 12}:{t.tm_min:02d} "
            f"{'AM' if t.tm_hour < 12 else 'PM'}")


def _line(margin: float, team: str) -> str:
    """A line from one team's side: "Dallas -3", "Dallas +2.5", "pick'em"."""
    if abs(margin) < 0.25:
        return "pick'em"
    sign = "\u2212" if margin > 0 else "+"
    return f"{team} {sign}{abs(margin):g}"


class ModelLabPage(Page):
    title = title_
    subtitle = f"Would anything beat {MODEL_NAME}? Ten ways of pricing a game, tested on the same games"
    icon = "\N{MICROSCOPE}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        self.views = QTabBar()
        self.views.setDrawBase(False)
        self.views.setExpanding(False)
        for label, about in VIEWS:
            self.views.setTabToolTip(self.views.addTab(label.replace("&", "&&")), about)
        self.layout_.addWidget(self.views)

        self.tile_service = StatTile("In Service")
        self.tile_challenger = StatTile("Best Challenger So Far")
        self.tile_value = StatTile("Closing Line Value")
        self.tile_ratings = StatTile("Own Ratings, 2011-2025")
        self.tile_winners = StatTile("Best Straight Up")
        self.tile_lines = StatTile("Best On Pool Lines")
        self.tile_agreed = StatTile("Recipes Agreed")
        self.tile_upset = StatTile("Biggest Miss")
        self._tiles = (self.tile_service, self.tile_challenger, self.tile_value, self.tile_ratings)
        self._more_tiles = (self.tile_winners, self.tile_lines, self.tile_agreed, self.tile_upset)

        self.lab_card = Card(LAB_TITLE)
        self.lab_box = QVBoxLayout()
        self.lab_card.body().addLayout(self.lab_box)
        self.lab_note = QLabel("")
        self.lab_note.setObjectName("Muted")
        self.lab_note.setWordWrap(True)
        self.lab_card.add(self.lab_note)

        self.recipes_card = Card("What each recipe is")
        self.recipes_box = QGridLayout()
        self.recipes_box.setHorizontalSpacing(20)
        self.recipes_box.setVerticalSpacing(6)
        self.recipes_box.setColumnStretch(2, 1)
        self.recipes_card.body().addLayout(self.recipes_box)

        self.extra = {}
        self.form_chart = FormChart(self.palette, height=2.9)
        self.extra["form"] = self._card(FORM_TITLE, self.form_chart)
        for key, heading in (("duel", DUEL_TITLE), ("shocks", SHOCKS_TITLE), ("parts", PARTS_TITLE),
                             ("calib", CALIB_TITLE), ("cover", COVER_TITLE)):
            self.extra[key] = self._card(heading)

        self.weeks_card = Card(WEEKS_TITLE)
        self.weeks_box = QVBoxLayout()
        self.weeks_card.body().addLayout(self.weeks_box)

        self.extra["taught"] = self._card(TAUGHT_TITLE)
        self.taught_lead = QLabel("")
        self.taught_lead.setWordWrap(True)
        self.taught_lead.setTextFormat(Qt.TextFormat.RichText)
        self.extra["taught"][0].body().insertWidget(1, self.taught_lead)      # under the card's title
        self.extra["pfm"] = self._card(PFM_TITLE)
        self.pfm_lead = QLabel("")
        self.pfm_lead.setWordWrap(True)
        self.pfm_lead.setTextFormat(Qt.TextFormat.RichText)
        self.extra["pfm"][0].body().insertWidget(1, self.pfm_lead)
        self.extra["pfm_week"] = self._card(PFM_WEEK_TITLE)
        self.extra["kinds"] = self._card(KINDS_TITLE)
        self.extra["kinds_by_season"] = self._card(KINDS_BY_SEASON)
        self.extra["seasons"] = self._card(SEASONS_TITLE)
        self.seasons_button = QPushButton("Work it out now (about ten seconds)")
        self.seasons_button.clicked.connect(self._work_out_seasons)
        self.seasons_button.hide()
        self.extra["seasons"][0].add(self.seasons_button)

        self.value_card = Card(VALUE_TITLE)
        self.value_lead = QLabel("")
        self.value_lead.setWordWrap(True)
        self.value_card.add(self.value_lead)
        self.value_box = QVBoxLayout()
        self.value_card.body().addLayout(self.value_box)
        self.value_note = QLabel("")
        self.value_note.setObjectName("Muted")
        self.value_note.setWordWrap(True)
        self.value_card.add(self.value_note)

        self.extra["record"] = self._card(RECORD_TITLE)

        self.versions_card = Card(f"What has changed in {MODEL_NAME}")
        self.versions_label = QLabel("")
        self.versions_label.setWordWrap(True)
        self.versions_label.setTextFormat(Qt.TextFormat.RichText)
        self.versions_card.add(self.versions_label)
        self.table: QWidget | None = None

        # Each view: its tiles, then its cards in the order they are read.
        card = lambda key: self.extra[key][0]  # noqa: E731
        self._view_holders: list[QWidget] = []
        for tiles, cards in (
            (self._tiles, (self.lab_card, card("duel"), card("parts"), self.weeks_card, self.recipes_card)),
            (self._more_tiles, (card("form"), card("shocks"), card("calib"))),
            ((), (card("taught"), card("pfm"), card("pfm_week"), card("kinds"), card("kinds_by_season"),
                  card("seasons"))),
            ((), (card("record"), self.value_card, card("cover"), self.versions_card)),
        ):
            holder = QWidget()
            box = QVBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(self.layout_.spacing())
            if tiles:
                box.addLayout(tile_grid(list(tiles), per_row=4))
            for each in cards:
                box.addWidget(each)
            self.layout_.addWidget(holder)
            self._view_holders.append(holder)
        self.outside = ForecastLogView(self)
        self.layout_.addWidget(self.outside)
        self._view_holders.append(self.outside)
        try:
            wanted = int(QSettings().value(VIEW_KEY, SCORE))
        except (TypeError, ValueError):
            wanted = SCORE
        self.views.setCurrentIndex(wanted if 0 <= wanted < len(VIEWS) else SCORE)
        self._show_view(self.views.currentIndex(), remember=False)
        self.views.currentChanged.connect(self._show_view)

    def _show_view(self, index: int, remember: bool = True) -> None:
        for n, holder in enumerate(self._view_holders):
            holder.setVisible(n == index)
        if remember:
            QSettings().setValue(VIEW_KEY, index)
            self._scroll.verticalScrollBar().setValue(0)        # a new view is read from its top

    def _card(self, heading: str, chart=None):
        """A card with room for a table and a note under it: (card, the table's box, the note).
        It is set out in its view at the end of build."""
        card = Card(heading)
        box = QVBoxLayout()
        card.body().addLayout(box)
        if chart is not None:
            card.add(chart, 1)
        note = QLabel("")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.RichText)
        card.add(note)
        return card, box, note

    def _fill(self, key: str, headers, rows, note: str = "", **options) -> None:
        card, box, label = self.extra[key]
        self.clear_layout(box)
        card.setVisible(bool(rows) or bool(note))
        if rows:
            stretch = options.pop("stretch", 0)
            model = TableModel(headers, rows, palette=self.palette, **options)
            view, _ = make_table(model, stretch_column=stretch, row_height=28)
            box.addWidget(view)
        label.setText(note)

    def restyle(self) -> None:
        self.form_chart.set_palette(self.palette)
        self.outside.restyle()
        self.refresh_now()

    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        lab = modellab.run(season)      # the record is written by the scheduled jobs, never by looking
        value = closing.value(season)
        self._update_lab(lab)
        self._update_recipes(lab)
        self._update_form(lab)
        self._update_duel(lab)
        self._update_shocks(lab)
        self._update_record(lab)
        self._update_more_tiles(lab)
        self._update_parts(lab)
        self._update_calibration(lab)
        self._update_coverage(lab)
        self._update_weeks(lab)
        self._update_taught()
        self._update_pfm()
        self._update_kinds()
        self._update_seasons()
        self._update_value(value)
        self._update_tiles(lab, value)
        self.outside.refresh(results.season_year(season))
        self.versions_label.setText("<br><br>".join(
            f"<b>{version}</b> · {when}<br>{what}" for version, when, what in modellab.VERSIONS))

    def _update_tiles(self, lab: modellab.Lab, value: closing.Value) -> None:
        service = next((e for e in lab.entries if e.incumbent), None)
        if service is None:
            for tile in self._tiles[:2]:
                tile.update_values(self.NO_VALUE, "Needs a graded week with betting lines")
        else:
            self.tile_service.update_values(
                f"{service.rate:.0%}",
                f"{MODEL_NAME}: {service.right} of {_plural(service.games, 'game')} right\n"
                f"log loss {service.mean_logloss:.3f} · a coin flip is 0.693",
                "good" if service.rate >= 0.6 else "",
            )
            best = lab.front_runner
            if best is None:
                self.tile_challenger.update_values("None", f"nothing is ahead of {MODEL_NAME} on the same games")
            else:
                duel = modellab.pair(best, service)
                self.tile_challenger.update_values(
                    best.name,
                    f"{best.shared_right} right to {MODEL_NAME}'s {best.deadeye_right} over {best.shared} games "
                    f"\u00b7 split {duel.first}\u2013{duel.second}\n"
                    f"log loss better by {duel.edge:.3f} \u00b7 {best.shared} of the {modellab.ENOUGH_GAMES} "
                    f"games needed before a switch",
                    "good" if best.verdict == "has earned the switch" else "",
                )
        if value.picks:
            self.tile_value.update_values(
                f"{value.points:+.1f} pts",
                f"a pick, toward {MODEL_NAME}'s side by kickoff\n"
                f"{value.toward} moved its way, {value.away} away, of {_plural(len(value.picks), 'pick')}",
                "good" if value.points > 0.2 else "bad" if value.points < -0.2 else "",
            )
        else:
            self.tile_value.update_values(self.NO_VALUE, "starts with the first week whose lines are read after the deadline")
        run = lab.long_run or {}
        if run.get("games"):
            self.tile_ratings.update_values(
                f"{run.get('straight_up', 0):.1%}",
                f"of winners, over {run['games']:,} games it had not seen\n"
                f"the closing line gets about 66%",
            )
        else:
            self.tile_ratings.update_values(self.NO_VALUE, "the long replay hasn't been run")

    def _update_lab(self, lab: modellab.Lab) -> None:
        self.clear_layout(self.lab_box)
        self.table = None
        if not lab.entries:
            self.lab_card.set_title(LAB_TITLE)
            self.lab_note.setText("Appears once a week with betting lines has been graded.")
            return
        rows, tones, tips = [], {}, {}
        for r, e in enumerate(lab.entries):
            won, known = e.winners
            covered, lined = e.lined
            rows.append([e.name, f"{e.right} of {e.games} \u00b7 {e.rate:.0%}",
                         f"{won} of {known}" if known else self.NO_VALUE,
                         f"{covered} of {lined}" if lined else self.NO_VALUE,
                         self.NO_VALUE if e.mean_miss is None else f"{e.mean_miss:.1f}",
                         f"{e.mean_logloss:.3f}", e.verdict, e.kind])
            tones[(r, 7)] = "muted"
            tips[(r, 7)] = {"Market": "The betting market and nothing else.",
                            "Football": "Football of its own - results or other people's models - and no betting line.",
                            "Hybrid": "The betting line and football together."}.get(e.kind, "")
            tips[(r, 0)] = e.about
            tips[(r, 1)] = "Its side was credited under the pool's rules - the pool's line counted where there is one."
            tips[(r, 2)] = "It had the team that simply won the game, whatever the pool's line."
            tips[(r, 3)] = "Only the games the pool put a line on: the side it took was the one credited."
            if not e.incumbent and e.shared < modellab.ENOUGH_GAMES:
                tips[(r, 6)] = (f"So far only: a recipe is judged against {MODEL_NAME} once the two have "
                                f"priced {modellab.ENOUGH_GAMES} games in common.")
            tones[(r, 6)] = ("good" if e.incumbent or e.verdict == "has earned the switch" else "muted")
        model = TableModel(
            HEADERS, rows, palette=self.palette, numeric_columns={1, 2, 3, 4, 5},
            sort_values={1: [e.rate for e in lab.entries],
                         2: [e.winners[0] / e.winners[1] if e.winners[1] else 0.0 for e in lab.entries],
                         3: [e.lined[0] / e.lined[1] if e.lined[1] else 0.0 for e in lab.entries],
                         4: [e.mean_miss or 99.0 for e in lab.entries],
                         5: [e.mean_logloss for e in lab.entries]},
            tones=tones, tooltips=tips, bold_columns={0},
        )
        view, _ = make_table(model, stretch_column=6, row_height=28)
        self.table = view
        self.lab_box.addWidget(view)
        self.lab_card.set_title(f"{LAB_TITLE} - {_plural(lab.games, 'graded game')} over {_plural(len(lab.weeks), 'week')}")
        winner, service, line, front = lab.challenger, lab.service, lab.entry(modellab.LINE), lab.front_runner
        now = ""
        if service is not None:
            now = f"<b>Right now:</b> {MODEL_NAME} has {service.right} of {service.games} credited"
            if line is not None and line.games == service.games:
                gap = service.right - line.right
                now += (", level with the betting line" if not gap else
                        f", {abs(gap)} {'more' if gap > 0 else 'fewer'} than the betting line's {line.right}")
            now += ". "
            if winner is not None:
                now += f"<b>{winner.name} has earned the switch</b>: clearly better over {winner.shared} games. "
            else:
                now += (f"Nothing has earned its place - that takes {modellab.ENOUGH_GAMES} games in common and a "
                        f"log loss lower by {modellab.CLEARLY_BETTER:.3f}"
                        + (f"; {front.name} is closest, {front.shared} games in. " if front is not None else ". "))
        self.lab_note.setText(
            now + self._kinds(lab) +
            "<br><b>Credited</b> means its side got the pool's point. <b>Winners</b> means it had the team "
            "that won the game. <b>On pool lines</b> counts only games with a pool line. <b>Avg miss</b> is "
            "points off the final margin. <b>Log loss</b> scores the percentages: lower is better, and a "
            "coin flip is 0.693."
        )
        self.lab_note.setTextFormat(Qt.TextFormat.RichText)

    # ---- two questions kept apart, each beside its last few weeks ------------------------------
    def _update_more_tiles(self, lab: modellab.Lab) -> None:
        if not lab.entries:
            for tile in self._more_tiles:
                tile.update_values(self.NO_VALUE, "Awaiting graded games")
            return
        common = len(lab.common)
        for tile, what, noun in ((self.tile_winners, "winners", "winners picked"),
                                 (self.tile_lines, "lined", "credited, pool-line games only")):
            leaders, record = lab.best(what)
            if not leaders:
                tile.update_values(self.NO_VALUE, "no game every recipe priced yet" if what == "winners"
                                   else "no pool-line game every recipe priced yet")
                continue
            names = ", ".join(e.name for e in leaders[:3]) + (f" and {len(leaders) - 3} more" if len(leaders) > 3 else "")
            few = record.games < FEW
            tile.update_values(
                leaders[0].name if len(leaders) == 1 else f"{len(leaders)} level",
                (f"{names}\n" if len(leaders) > 1 else "")
                + f"{record.right} of {record.games} {noun} \u00b7 {record.rate:.0%} \u00b1{record.reach * 100:.0f}\n"
                + (f"only {_plural(record.games, 'game')}: too few to rank on" if few else
                   f"on the {common} games every recipe priced"),
            )
        agreed, rooms, came = lab.agreement()
        if rooms:
            self.tile_agreed.update_values(
                f"{agreed / rooms:.0%}",
                f"every recipe took the same side in {agreed} of {_plural(rooms, 'game')}\n"
                + (f"that side was credited in {came} of them" if agreed else "they never all agreed"),
            )
        else:
            self.tile_agreed.update_values(self.NO_VALUE, "Awaiting graded games")
        worst = lab.upset()
        if worst is None:
            self.tile_upset.update_values(self.NO_VALUE, "no game most recipes had wrong, with a score kept")
        else:
            finished = "tied" if not worst.actual else f"{'won' if worst.actual > 0 else 'lost'} by {abs(worst.actual):g}"
            self.tile_upset.update_values(
                f"{worst.off:.0f} pts",
                f"Week {worst.fixture.week}: {worst.fixture.matchup}\n"
                f"{worst.took} of {worst.priced} recipes took {worst.side} "
                f"{_by(worst.margin, '', behind='behind by', places=1)}; it {finished}",
                "bad",
            )

    def _update_form(self, lab: modellab.Lab) -> None:
        forms = lab.form()
        room = lab.against_the_room()
        rows, tones, tips = [], {}, {}
        for r, f in enumerate(forms):
            most, alone = room.get(f.name, (0, 0))
            rows.append([f.name, _record(f.winners, self.NO_VALUE), _record(f.winners_late, self.NO_VALUE),
                         _record(f.lined, self.NO_VALUE), _record(f.lined_late, self.NO_VALUE), f.reading,
                         f"{most}" + (f" \u00b7 {alone} alone" if alone else "")])
            for c, tally in ((1, f.winners), (2, f.winners_late), (3, f.lined), (4, f.lined_late)):
                if tally.games < FEW:
                    tones[(r, c)] = "muted"
                    tips[(r, c)] = f"Fewer than {FEW} games: too few to rank a recipe on."
            tones[(r, 5)] = {modellab.BETTER: "good", modellab.WORSE: "bad"}.get(f.reading, "muted")
            tips[(r, 5)] = (
                f"On winners: {f.late.right} of {f.late.games} over the last {modellab.FORM_WEEKS} graded weeks, "
                f"{f.early.right} of {f.early.games} in the weeks before them. "
                + (f"Needs {modellab.FORM_GAMES} games on each side before the two are compared."
                   if f.luck is None else
                   f"That is {abs(f.luck):.1f} spreads of luck apart; {modellab.FORM_LUCK:g} are needed to call "
                   "it a change."))
            tones[(r, 6)] = "" if most else "muted"
        moved = [f for f in forms if f.reading in (modellab.BETTER, modellab.WORSE)]
        early = bool(forms) and all(f.reading == modellab.EARLY for f in forms)
        now = ("too few weeks are graded to set the last four against the ones before. " if early else
               "no recipe's last four weeks differ from the weeks before by more than luck - a good month so far "
               "is a good month, not an improvement. " if not moved else
               "; ".join(f"{f.name} is {f.reading}" for f in moved) + ", by more than luck alone explains. ")
        self._fill("form", FORM_HEADERS, rows, numeric_columns={1, 2, 3, 4, 6}, tones=tones, tooltips=tips,
                   bold_columns={0}, stretch=0, note=(
            ("<b>Right now:</b> " + now +
             "<b>Winners</b> is straight up: it had the team that won. <b>On pool lines</b> is against the "
             "spread, on the games the pool put a line on and no others. The two are never added together. "
             "<b>Winners lately</b> sets the winners of the last four weeks against the winners of the weeks "
             f"before; with ten recipes looked at every week it takes {modellab.FORM_LUCK:g} spreads of luck, "
             "not the usual two, to call one a change. "
             "The \u00b1 is how far luck alone moves a record that size: 8 of 10 is 80% \u00b125 and 120 of 200 is "
             "60% \u00b17, so the second is the one to trust. Grey is fewer than "
             f"{FEW} games. <b>Right when most missed</b> counts the games it had right when most of the "
             "other recipes that priced them did not. The chart follows three of them.") if rows else ""))
        self._draw_form(lab)

    def _draw_form(self, lab: modellab.Lab) -> None:
        service, line = lab.service, lab.entry(modellab.LINE)
        third = lab.front_runner or max(
            (e for e in lab.entries if e is not service and e is not line),
            key=lambda e: (e.games, e.rate), default=None)
        chosen = [e for e in (service, line, third) if e is not None]
        seen, series = set(), []
        for e in chosen:
            if e.name in seen:
                continue
            seen.add(e.name)
            series.append((e.name, [(week, lately.right, lately.games, season.right, season.games)
                                    for week, lately, season in lab.rolling(e.name)]))
        self.form_chart.plot(series, modellab.FORM_WEEKS)

    # ---- the week's misses, across every recipe -----------------------------------------------
    def _update_shocks(self, lab: modellab.Lab) -> None:
        shocks = lab.shocks()
        weeks = sorted({s.week for s in shocks}, reverse=True)
        rows, tones = [], {}
        for s in (s for s in shocks if s.week in weeks[:SHOCK_WEEKS]):
            room, r = s.room, len(rows)
            won = (room.actual or 0) > 0
            finished = (self.NO_VALUE if room.actual is None else "tied" if not room.actual else
                        f"{'won' if won else 'lost'} by {abs(room.actual):g}")
            right = len(room.right)
            rows.append([
                s.week, s.kind, room.fixture.matchup,
                f"{room.side}, {room.took} of {room.priced} \u00b7 {room.sure:.0%}",
                _by(room.margin, self.NO_VALUE, behind="behind by", places=1)
                + (f" \u00b7 {room.spread:.1f} apart" if s.kind == modellab.SPLIT and room.spread is not None else ""),
                finished + ("" if not room.fixture.lined or room.missed != won else
                            " \u00b7 not by the pool's line" if won else " \u00b7 inside the pool's line"),
                "none" if not right else "all" if right == room.priced else
                f"{right} of {room.priced}" + (f": {', '.join(room.right)}" if right <= 2 else ""),
            ])
            tones[(r, 1)] = "muted"
            tones[(r, 5)] = "bad" if room.missed else "good"
            tones[(r, 6)] = "muted" if not right or right == room.priced else ""
        surest = [s for s in shocks if s.kind == modellab.SUREST]
        shared = sum(1 for s in surest if s.room.agreed)
        split = [s for s in shocks if s.kind == modellab.SPLIT]
        split_right = sum(1 for s in split if not s.room.missed)
        graded = len({s.week for s in shocks})
        self._fill("shocks", SHOCKS_HEADERS, rows, numeric_columns={0}, tones=tones, bold_columns={2}, stretch=2,
                   note=(
            (f"<b>Right now:</b> in {shared} of {_plural(len(surest), 'week')} with a miss, the surest pick that "
             f"missed was one every recipe had the same side of - no recipe in the lab would have saved it. "
             f"On the most disputed game the side most recipes took was credited in {split_right} of "
             f"{_plural(len(split), 'week')}. "
             "Each week's three: the pick the recipes were surest of that missed (surest miss), the result "
             "furthest from the margin they expected (furthest off), and the game their numbers were furthest "
             "apart on (most disputed). \u201cMost recipes "
             "took\u201d gives the side, how many took it and the average chance they gave it. A row says "
             "what kind of miss a game was, never why: one game is one game."
             + (f" The last {SHOCK_WEEKS} of {graded} graded weeks are listed." if graded > SHOCK_WEEKS else ""))
            if rows else ""))

    # ---- the record: what was written down, and whether the replay still says the same ---------
    def _update_record(self, lab: modellab.Lab) -> None:
        year = results.season_year(self.season)
        try:
            record = ledger.check(lab, year)
        except Exception:  # noqa: BLE001 - the page stands without it
            record = ledger.Record()
        rows, tones = [], {}
        for r, line in enumerate(sorted(record.lines, key=lambda line: -line.week)):
            rows.append([
                line.week, oddslock.when(year, line.week) if not line.lock else _when(line.lock), _when(line.at),
                line.standing, line.games,
                "not graded yet" if not line.numbers else
                f"all {line.numbers} numbers the same" if not line.changed else
                f"{line.changed} of {line.numbers} have changed, {line.worst} most"
                + ("" if not line.version else
                   f" \u00b7 written under version {line.version}, this is {VERSION}" if line.version != VERSION else
                   f" \u00b7 same version ({VERSION}), so not from an update"),
            ])
            tones[(r, 3)] = ("good" if line.before == line.games else
                             "warning" if line.before or line.unknown else "muted")
            tones[(r, 5)] = "muted" if not line.numbers else "warning" if line.changed else "good"
        replayed = record.graded - record.at_the_time - record.unknown
        note = ""
        if lab.entries:
            note = (
                f"<b>Right now:</b> {record.at_the_time} of the {_plural(record.graded, 'graded game')} "
                f"{'was' if record.at_the_time == 1 else 'were'} written down before kickoff. "
                + (f"The other {replayed} are a replay: each week priced again from the lines and files kept "
                   f"at the time. The Scoreboard's tables count both. " if replayed else "")
                + (f"{_plural(record.unknown, 'game')} had no kickoff time on file when "
                   f"{'it was' if record.unknown == 1 else 'they were'} written, so "
                   f"{'it is' if record.unknown == 1 else 'they are'} not counted as before kickoff. "
                   if record.unknown else "")
                + ("Since they were written, some replayed numbers have changed - the rows in yellow. Each says "
                   "which version wrote it: a different version means the recipe was changed on purpose; the "
                   "same version means something it reads has changed. "
                   if record.changed else "")
                + "From here on a week's numbers are written when its cards are due, and never written again. "
                "The nightly job and the game-day job do it; looking at this page writes nothing. In the two "
                "days before the cards are due they also keep a draft, so a game whose numbers did not move "
                "after its draft is dated from the draft - a computer asleep at the deadline does not make the "
                "week late. A week first written after its games is kept too, so the past stops moving, but it "
                "is marked as that."
            )
        self._fill("record", RECORD_HEADERS, rows, note, numeric_columns={0, 4}, tones=tones, bold_columns={0},
                   stretch=5)

    # ---- head to head: only the games two recipes split can tell them apart -----------
    def _update_duel(self, lab: modellab.Lab) -> None:
        service = lab.service
        rows, tones, proven = [], {}, []
        for e in (lab.entries if service is not None else []):
            if e.incumbent:
                continue
            duel = modellab.pair(e, service)
            r = len(rows)
            rows.append([e.name, duel.games, duel.first, duel.second, f"{duel.net:+d}" if duel.net else "level",
                         f"{'better' if duel.edge > 0 else 'worse'} by {abs(duel.edge):.3f}", duel.reading])
            real = duel.luck is not None and duel.luck < modellab.REAL and duel.net
            if real:
                proven.append(e.name)
            tones[(r, 4)] = ("good" if duel.net > 0 else "bad") if real else "muted"
            tones[(r, 5)] = "good" if duel.edge >= modellab.CLEARLY_BETTER else "bad" if duel.edge <= -modellab.CLEARLY_BETTER else "muted"
            tones[(r, 6)] = ("good" if duel.net > 0 else "bad") if real else "muted"
        self._fill("duel", DUEL_HEADERS, rows, numeric_columns={1, 2, 3, 4}, tones=tones, bold_columns={0},
                   stretch=6, note=(
            (("<b>Right now:</b> " + (
                f"{', '.join(proven)} {'has' if len(proven) == 1 else 'have'} a real gap from {MODEL_NAME}. "
                if proven else f"no recipe is different enough from {MODEL_NAME} to rule out luck. ")
             + "Two recipes can only be told apart by the games where one was right and the other wrong. "
             f"\u201cCould it be luck?\u201d says how often that would happen by chance. Under "
             f"{modellab.REAL:.0%} counts as a real difference.") if rows else "")))

    # ---- what each ingredient adds ---------------------------------------------------------
    def _update_parts(self, lab: modellab.Lab) -> None:
        rows, tones, earned = [], {}, []
        for what, with_it, without, duel in lab.ablation():
            r = len(rows)
            rows.append([what, with_it, without, duel.games,
                         f"{duel.first} won, {duel.second} lost" if duel.split else "none",
                         (f"{'better' if duel.edge > 0 else 'worse'} by {abs(duel.edge):.3f}" if duel.games else self.NO_VALUE),
                         duel.reading])
            real = duel.luck is not None and duel.luck < modellab.REAL and duel.net
            if real:
                earned.append(what.lower())
            tones[(r, 5)] = "good" if duel.edge >= modellab.CLEARLY_BETTER else "bad" if duel.edge <= -modellab.CLEARLY_BETTER else "muted"
            tones[(r, 6)] = ("good" if duel.net > 0 else "bad") if real else "muted"
        self._fill("parts", PARTS_HEADERS, rows, numeric_columns={3}, tones=tones, bold_columns={0}, stretch=6,
                   note=(
            (("<b>Right now:</b> " + (
                f"{', '.join(earned)} {'has' if len(earned) == 1 else 'have'} made a real difference. "
                if earned else "no ingredient has proved itself yet. ")
             + "Each row compares a recipe with the same recipe minus one ingredient, on the same games. "
             "An ingredient is worth keeping only if it helps over many games.") if rows else "")))

    # ---- calibration -------------------------------------------------------------------------
    def _update_calibration(self, lab: modellab.Lab) -> None:
        service, line = lab.service, lab.entry(modellab.LINE)
        rows, tones = [], {}
        if service is not None:
            ours = modellab.calibration(service)
            theirs = modellab.calibration(line) if line is not None else [None] * len(ours)
            for r, (a, b) in enumerate(zip(ours, theirs)):
                cells = [a.label]
                for c, band in ((1, a), (4, b)):
                    if band is None or not band.picks:
                        cells += [0 if band is not None else self.NO_VALUE, self.NO_VALUE, self.NO_VALUE]
                        continue
                    cells += [band.picks, f"{band.said:.0%}", f"{band.came:.0%}"]
                    # how far luck alone moves a band this size
                    reach = 2 * (band.said * (1 - band.said) / band.picks) ** 0.5
                    tones[(r, c + 2)] = ("muted" if band.picks < 15 else
                                         "" if abs(band.came - band.said) <= reach else
                                         "good" if band.came > band.said else "bad")
                rows.append(cells)
        headers = ["Chance it gave its side", f"{MODEL_NAME}: picks", "it said", "came in",
                   "Betting line: picks", "it said", "came in"]
        self._fill("calib", headers, rows, numeric_columns={1, 2, 3, 4, 5, 6}, tones=tones, bold_columns={0},
                   stretch=0, note=(
            ((self._calibration_now(service) +
             "Picks it calls 60% should come in about 60% of the time. Green means they came in more "
             "often than it said. Red means less often. Grey means too few picks to tell.") if rows else "")))

    @staticmethod
    def _calibration_now(service) -> str:
        """Every pick together: what it said, and what came in."""
        plays = list(service.log.values()) if service is not None else []
        if not plays:
            return ""
        said = sum(max(play.chance, 1 - play.chance) for play in plays) / len(plays)
        came = sum(play.hit for play in plays) / len(plays)
        return (f"<b>Right now:</b> across all {len(plays)} picks {MODEL_NAME} said {said:.0%} and "
                f"{came:.0%} came in. ")

    # ---- coverage: compare like with like -------------------------------------------------
    def _update_coverage(self, lab: modellab.Lab) -> None:
        common = lab.common
        rows, tones = [], {}
        for r, e in enumerate(lab.entries):
            missing = sum(e.missing.values())
            why = "; ".join(f"{reason} ({count})" for reason, count in sorted(e.missing.items(), key=lambda kv: -kv[1]))
            right, games = e.on(common)
            rows.append([e.name, e.games, missing or "none", why or "priced every graded game",
                         f"{right} of {games}" if games else self.NO_VALUE])
            tones[(r, 2)] = "warning" if missing else "muted"
            tones[(r, 3)] = "" if missing else "muted"
        best = max((e.on(common)[0] for e in lab.entries), default=0)
        for r, e in enumerate(lab.entries):
            if common and e.on(common)[0] == best:
                tones[(r, 4)] = "good"
        self._fill("cover", COVER_HEADERS, rows, numeric_columns={1, 2, 4}, tones=tones, bold_columns={0},
                   stretch=3, note=(
            ((f"<b>Right now:</b> {lab.decided} games are graded. "
             f"{sum(1 for e in lab.entries if not e.missing)} of {len(lab.entries)} recipes priced every "
             f"one, and all of them can be compared on the same {len(common)}. "
             "A recipe that priced fewer games wasn't worse on the rest; it just had nothing to go on.")
            if rows else "")))

    # ---- market, football, hybrid: many seasons, not one ---------------------------------------
    def _update_taught(self) -> None:
        """The training ground's weekly answer. Read from the file it leaves; nothing is run here."""
        found = challengers.read()
        if found is None:
            self.taught_lead.setText("")
            self._fill("taught", challengers.HEADERS, [], note=(
                "No answer yet. The weekly training job (the \"ACQL Training\" scheduled task) teaches "
                f"challengers on past seasons, tests them on games they had not seen, and says here whether "
                f"any is clearly better than {MODEL_NAME}'s rule. It changes no pick."))
            return
        self.taught_lead.setText(f"<b>{found.call}</b>")
        tones = {(r, 6): "good" for r in found.cases} | {(r, 6): "bad" for r in found.behind}
        span = f"{found.seasons[0]}–{found.seasons[-1]}" if found.seasons else "no seasons"
        held = (f" Newest seasons is {found.held_back[0]}–{found.held_back[-1]} on their own: "
                f"a lead has to hold there too."
                if found.held_back else "")
        doubts = []
        if found.stale():
            doubts.append("<b>This answer is more than a week old</b> - the weekly job has not run since.")
        if found.sealed is False:
            doubts.append("<b>The run's own check failed</b> (a result could have leaked backwards): "
                          "do not act on it.")
        if found.problems:
            doubts.append(f"{found.problems} problem{'s' if found.problems != 1 else ''} left rows out "
                          "(the run's report says which).")
        self._fill("taught", challengers.HEADERS, found.rows, numeric_columns={1, 2, 3, 4, 5}, tones=tones,
                   bold_columns={0}, stretch=0, note=" ".join([
            f"Each challenger against {found.in_use}, the rule in use, on {found.games:,} games from "
            f"{span}, every one priced by a model taught only on earlier games. Each number is log loss a "
            f"game (the Model Lab's own measure); a plus is better than the rule. Could be from is where "
            f"it could plausibly lie, and only a range wholly above zero counts.{held}",
            f"This season is {found.now_games} games on the lines as they stood at each deadline."
            if found.now_games else "",
            f"Worked out {_when(found.made)} by the weekly training job. A case here is a reason to look, "
            f"never a switch: the rule above ({modellab.ENOUGH_GAMES} games priced live) is untouched.",
            *doubts]))

    def _update_pfm(self) -> None:
        """The PFM check's answer, read from the file the training job leaves; nothing is run here."""
        found = pfmcheck.read()
        if found is None:
            self.pfm_lead.setText("")
            self._fill("pfm", pfmcheck.HEADERS, [], note=(
                "No answer yet. The PFM study (its own command, and a step of the weekly training job) takes a "
                f"snapshot of PFM's ratings and measures them against {MODEL_NAME}, on games the fit had not "
                "seen. It changes no pick."))
            self._fill("pfm_week", pfmcheck.WEEK_HEADERS, [], note="")
            return
        self.pfm_lead.setText(f"<b>{found.call.capitalize()}.</b> {found.why}")
        tones = {(r, 6): "good" for r in found.better} | {(r, 6): "bad" for r in found.worse}
        doubts = []
        if found.fresh_state in ("stale", "none", "partial"):
            doubts.append(f"<b>{found.freshness}.</b>")
        if found.stale():
            doubts.append("<b>This answer is more than a week old</b> - the study has not run since.")
        if found.sealed is False:
            doubts.append("<b>The study's own check failed</b> (a result could have leaked backwards): "
                          "do not act on it.")
        if found.revisions:
            doubts.append(f"PFM has rewritten {found.revisions} past weekly score(s) since an earlier snapshot.")
        self._fill("pfm", pfmcheck.HEADERS, found.rows, numeric_columns={1, 2, 3, 4}, tones=tones,
                   bold_columns={0}, stretch=6, note=" ".join([
            f"Each version priced only from what was known at the deadline, with any PFM weight taught on "
            f"earlier weeks only. Log loss and Brier a game, lower is better; against {MODEL_NAME} is on the same "
            "games, minus is better, and only a range wholly below zero counts. B is the betting line with no "
            "models' share; C adds the PFM Team Score gap to the card, C2 to the bare line.",
            f"{found.freshness}. Worked out {_when(found.made)}.",
            f"A case here is a reason to look, never a switch: {MODEL_NAME}'s picks are untouched.",
            *doubts]))
        self._fill("pfm_week", pfmcheck.WEEK_HEADERS, found.week_rows, numeric_columns={2, 3, 4, 5, 6},
                   bold_columns={0}, stretch=0, note=(
            f"Week {found.week}: the home side's chance of being credited. {MODEL_NAME} is the card; the PFM "
            "shadow is the card with the PFM gap added at the weight earlier weeks taught - kept in its own "
            "ledger (data/training/pfm/shadow.jsonl), never the pick."
            + ("" if found.weight is None else
               f" The weight taught so far is {found.weight:+.2f} a spread of the gap"
               + (" - minus: it fades PFM's favourite, so the shadow moves against PFM, not with it"
                  if found.weight < 0 else "")
               + ". Until the check above says otherwise, that is no better than luck.")
            if found.week_rows else ""))

    def _update_kinds(self) -> None:
        try:
            found = nflverse.families()
        except Exception:  # noqa: BLE001 - the lab stands without it
            found = None
        if found is None or not found.lines:
            self._fill("kinds", KINDS_HEADERS, [], note=(
                "Needs the nflverse game and team files in data/nflverse - and, once they are there, a "
                "night for the scheduled job to work it out." if not nflverse.available() else
                "Not worked out yet for these files: the scheduled job does it overnight."))
            self._fill("kinds_by_season", [], [], note="")
            return
        about = {
            nflverse.MARKET: "The closing betting line and nothing else",
            nflverse.RATINGS: "The dashboard's ratings from final scores - no line",
            nflverse.FOOTBALL: "Ratings, each team's efficiency over its last eight games, rest - no line",
            nflverse.TREES: "The same football inputs through gradient-boosted trees - no line",
            nflverse.HYBRID: "The closing line with the football inputs on top",
        }

        def record(won: int, bets: int, rate) -> str:
            return f"{won}\u2013{bets - won} \u00b7 {rate:.1%}" if bets else self.NO_VALUE

        market = found.of(nflverse.MARKET)
        rows, tones, tips = [], {}, {}
        for r, kind in enumerate(nflverse.KINDS):
            line = found.of(kind)
            if line is None:
                continue
            rows.append([kind, f"{line.winners:,} of {line.games:,} \u00b7 {line.rate:.1%}", f"{line.miss:.2f}",
                         record(line.covers, line.bets, line.cover_rate),
                         record(line.big_covers, line.big_bets, line.big_rate)])
            tips[(r, 0)] = about.get(kind, "")
            if market is not None and kind != nflverse.MARKET:
                tones[(r, 1)] = "good" if line.rate > market.rate + 0.01 else "bad" if line.rate < market.rate - 0.01 else "muted"
                tones[(r, 2)] = "good" if line.miss < market.miss - 0.05 else "bad" if line.miss > market.miss + 0.05 else "muted"
            for c, rate in ((3, line.cover_rate), (4, line.big_rate)):
                if rate is not None:
                    tones[(r, c)] = "good" if rate >= nflverse.BREAK_EVEN + 0.01 else "muted"
        hybrid, football = found.of(nflverse.HYBRID), found.of(nflverse.FOOTBALL)
        seasons = found.seasons
        leans = sorted(((abs(w), name) for name, w in found.weights.items() if name != "the closing line"), reverse=True)[:2]
        line_weight = found.weights.get("the closing line", 0.0)
        verdict = ""
        if market is not None and hybrid is not None and football is not None:
            ahead = hybrid.winners - market.winners
            verdict = (
                f"<b>Right now:</b> football stats alone pick {football.rate:.1%} of winners and the betting "
                f"line picks {market.rate:.1%}. Adding the stats to the line gives {hybrid.rate:.1%}: "
                f"{abs(ahead)} {'more' if ahead >= 0 else 'fewer'} winners in {hybrid.games:,} games. "
                f"Against the spread that mix wins {hybrid.cover_rate:.1%}, and it takes "
                f"{nflverse.BREAK_EVEN:.1%} to break even. The betting line already knows what these "
                f"stats know. ")
        self._fill("kinds", KINDS_HEADERS, rows, numeric_columns={1, 2, 3, 4}, tones=tones, tooltips=tips,
                   bold_columns={0}, stretch=0, note=(
            (verdict +
            f"<br>Each season from {seasons[0]} to {seasons[-1]} was predicted using only earlier seasons. "
            f"\u201cAgainst the closing spread\u201d takes the model's side when it is {nflverse.EDGE:g} "
            f"points or more from the line. Starting quarterbacks are left out, because they aren't known "
            f"on Thursday.")))
        season_rows, season_tones = [], {}
        for r, season in enumerate(seasons):
            cells = [season, found.of(nflverse.MARKET, season).games]
            best = max(found.of(kind, season).rate for kind in nflverse.KINDS)
            for c, kind in enumerate(nflverse.KINDS, 2):
                line = found.of(kind, season)
                cells.append(f"{line.rate:.1%}")
                if line.rate >= best - 1e-9:
                    season_tones[(r, c)] = "good"
            spread = found.of(nflverse.HYBRID, season)
            cells.append(f"{spread.covers}\u2013{spread.bets - spread.covers}")
            season_rows.append(cells)
        wins = {kind: sum(1 for s in seasons if found.of(kind, s).rate >= max(found.of(k, s).rate for k in nflverse.KINDS) - 1e-9)
                for kind in nflverse.KINDS}
        self._fill("kinds_by_season", ["Season", "Games", *nflverse.KINDS, "Hybrid v the spread"], season_rows,
                   numeric_columns=set(range(0, 8)), tones=season_tones, bold_columns={0}, stretch=0, note=(
            f"The betting line was best or level-best in {wins[nflverse.MARKET]} of {len(seasons)} seasons, the "
            f"hybrid in {wins[nflverse.HYBRID]} and football alone in {wins[nflverse.FOOTBALL]}. The hybrid's "
            f"record against the spread swings both ways. That is what no edge looks like."))

    # ---- season by season ----------------------------------------------------------------------
    def _update_seasons(self) -> None:
        year = results.season_year(self.season)
        try:
            lines = contenders.seasons(year)
        except Exception:  # noqa: BLE001 - the lab stands without it
            lines = None
        if not lines:
            self.seasons_button.setVisible(lines is None)
            self._fill("seasons", SEASONS_HEADERS, [], note=(
                "Not worked out yet for this history: the scheduled job does it overnight (it takes a few "
                "seconds, and only changes when a season ends)."))
            return
        self.seasons_button.hide()
        rows, tones = [], {}

        def cell(right: int, games: int) -> str:
            return f"{right} \u00b7 {right / games:.1%}" if games else self.NO_VALUE

        for r, s in enumerate(lines):
            rows.append([s.season, s.games, cell(s.ratings, s.games), cell(s.analyst, s.games), cell(s.machine, s.games),
                         f"{s.ratings_miss:.1f} / {s.analyst_miss:.1f} / {s.machine_miss:.1f}"])
            best = max(s.ratings, s.analyst, s.machine)
            for c, value in ((2, s.ratings), (3, s.analyst), (4, s.machine)):
                if value == best:
                    tones[(r, c)] = "good"
        games = sum(s.games for s in lines)
        totals = [sum(getattr(s, name) for s in lines) for name in ("ratings", "analyst", "machine")]
        rows.append([f"All {len(lines)}", games, *(cell(total, games) for total in totals),
                     " / ".join(f"{sum(getattr(s, name) * s.games for s in lines) / games:.1f}"
                                for name in ("ratings_miss", "analyst_miss", "machine_miss"))])
        wins = [sum(1 for s in lines if getattr(s, name) == max(s.ratings, s.analyst, s.machine))
                for name in ("ratings", "analyst", "machine")]
        self._fill("seasons", SEASONS_HEADERS, rows, numeric_columns={0, 1, 2, 3, 4, 5}, tones=tones,
                   bold_columns={0}, stretch=0, note=(
            (f"<b>Right now:</b> there is nothing to choose between them. Each was best or "
            f"level-best in {wins[0]}, {wins[1]} and {wins[2]} of {len(lines)} seasons. Each season was "
            f"predicted using only earlier seasons. The betting line picks about 66% of winners over the "
            f"same years.")))

    def _work_out_seasons(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            contenders.seasons(results.season_year(self.season), compute=True)
        except Exception:  # noqa: BLE001
            pass
        finally:
            QApplication.restoreOverrideCursor()
        self._update_seasons()

    def _update_recipes(self, lab: modellab.Lab) -> None:
        """Every recipe in a sentence, where it can be read without hovering."""
        self.clear_layout(self.recipes_box)
        self.recipes_card.setVisible(bool(lab.entries))
        p = self.palette
        for r, e in enumerate(lab.entries):
            name = QLabel(f"<b>{e.name}</b>")
            kind = QLabel(f"<span style='color:{p.ink_muted}'>{e.kind}</span>")
            what = QLabel(e.about + (f" <span style='color:{p.good}'>In service.</span>" if e.incumbent else ""))
            for column, label in enumerate((name, kind, what)):
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setWordWrap(column == 2)
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.recipes_box.addWidget(label, 2 * r, column)
            if r < len(lab.entries) - 1:
                rule = QFrame()
                rule.setFixedHeight(1)
                rule.setStyleSheet(f"background: {p.grid}; border: none;")
                self.recipes_box.addWidget(rule, 2 * r + 1, 0, 1, 3)

    @staticmethod
    def _kinds(lab: modellab.Lab) -> str:
        """The market, football alone and the two together, on the games every recipe priced."""
        best = lab.best_of_each_kind()
        if len(best) < 2:
            return ""
        said = "; ".join(f"{kind.lower()} - {e.name}, {right} of {games}" for kind, e, right, games in best)
        return f"On the {len(lab.common)} games every recipe priced, the best of each kind: {said}. "

    def _update_weeks(self, lab: modellab.Lab) -> None:
        self.clear_layout(self.weeks_box)
        self.weeks_card.setVisible(bool(lab.entries))
        if not lab.entries:
            return
        weeks = list(lab.weeks)
        rows, tones = [], {}
        best = {w: max((e.by_week[w][0] / e.by_week[w][1] for e in lab.entries if w in e.by_week and e.by_week[w][1]),
                       default=None) for w in weeks}
        for r, e in enumerate(lab.entries):
            cells = [e.name]
            for c, w in enumerate(weeks, 1):
                right, games = e.by_week.get(w, (0, 0))
                cells.append(f"{right} of {games}" if games else self.NO_VALUE)
                if games and best[w] is not None and right / games >= best[w] - 1e-9:
                    tones[(r, c)] = "good"          # the week's best, or level with it
                elif not games:
                    tones[(r, c)] = "muted"
            rows.append(cells)
        model = TableModel(["Recipe"] + [f"Week {w}" for w in weeks], rows, palette=self.palette,
                           numeric_columns=set(range(1, len(weeks) + 1)), tones=tones, bold_columns={0})
        view, _ = make_table(model, stretch_column=0, row_height=28)
        self.weeks_box.addWidget(view)

    def _update_value(self, value: closing.Value) -> None:
        self.clear_layout(self.value_box)
        if not value.picks:
            self.value_lead.setText(
                f"Nothing to measure yet. From the next deadline on, each game's line is tracked until "
                f"kickoff and compared with {MODEL_NAME}'s pick."
            )
            self.value_note.setText("")
            return
        rows, tones = [], {}
        for r, p in enumerate(sorted(value.picks, key=lambda p: (-p.week, -abs(p.moved)))):
            verdict = p.verdict
            rows.append([p.week, p.matchup, p.pick, _line(p.then, p.pick), _line(p.close, p.pick),
                         ("no real move" if not verdict else
                          f"{abs(p.moved):g} {'toward' if verdict > 0 else 'away from'} the pick")
                         + (" *" if p.mixed else "")])
            tones[(r, 5)] = "good" if verdict > 0 else "bad" if verdict < 0 else "muted"
        model = TableModel(VALUE_HEADERS, rows, palette=self.palette, numeric_columns={0},
                           tones=tones, bold_columns={2})
        view, _ = make_table(model, stretch_column=1, row_height=27)
        self.value_box.addWidget(view)
        self.value_lead.setText(
            f"{_plural(len(value.picks), 'pick')} over {_plural(len(value.weeks), 'week')}: the line "
            f"moved toward {MODEL_NAME}'s side {value.toward} times and away {value.away}, "
            f"{value.points:+.1f} points a pick on average."
        )
        self.value_note.setText(
            "Cards go in on Thursday, but lines keep moving until kickoff. If they keep moving toward "
            f"{MODEL_NAME}'s picks, it saw something the market only saw later. Over a season that is "
            "the best sign of a real edge."
            + (" * For this week the starting line comes from the card itself, so only a move of a "
               "full point counts." if any(p.mixed for p in value.picks) else "")
        )
