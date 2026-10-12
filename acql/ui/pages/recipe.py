"""The recipe, taken apart: the nudge simulator, what each ingredient changed, and the line recorder."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

from ... import analytics, recipe
from ...places import RECIPE as title_
from ...version import MODEL_NAME
from ..charts import LineChart
from ..modelcharts import FlightChart
from ..widgets import Card, TableModel, make_table, section
from .base import Page

SIM_TITLE = "The nudge simulator - what if the published models had more say, or less?"
SHARE_TITLE = "The season at every share - why the share is what it is"
PARTS_TITLE = "What each ingredient changed"
FLIGHT_TITLE = "Line recorder"
SIM_HEADERS = ["Game", "Betting line", "Models", "They lean", "With none", "In use", "At the share set", "Credited"]
PART_HEADERS = ["Ingredient", "Had a say in", "Picks it changed", "Came in", "Didn't", "For example"]
FLIGHT_HEADERS = ["Game", "Took", "Opened", "Latest", "Moved", "Models' middle", "Readings"]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _line(margin: float | None, home: str, away: str) -> str:
    if margin is None:
        return "—"
    if abs(margin) < 0.25:
        return "pick'em"
    return f"{home if margin > 0 else away} −{abs(margin):g}"


def _from_pick(value: float | None) -> str:
    """A line from the pick's side: "-3" favoured by three, "+2.5" getting points."""
    if value is None:
        return "—"
    if abs(value) < 0.25:
        return "pick'em"
    return f"{'−' if value > 0 else '+'}{abs(value):g}"


class RecipePage(Page):
    title = title_
    subtitle = (f"{MODEL_NAME}'s recipe taken apart: what a different share of the models would change, "
                f"what each ingredient has changed so far, and how every line has moved")
    icon = "\N{ALEMBIC}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Week"))
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(170)
        self.week_picker.currentIndexChanged.connect(lambda _: self._week_chosen())
        chooser.addWidget(self.week_picker)
        chooser.addStretch(1)
        self.layout_.addLayout(chooser)
        self._sim: recipe.Simulation | None = None
        self._filling = False

        # ---- the nudge simulator
        self.sim_card = Card(SIM_TITLE)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.share_label = QLabel("")
        self.share_label.setMinimumWidth(250)
        row.addWidget(self.share_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(5)
        self.slider.setTickInterval(5)
        self.slider.valueChanged.connect(lambda _: self._render_simulator())
        row.addWidget(self.slider, 1)
        self.presets = []
        for words, value in (("None", 0), ("In use", None), ("Half", 50), ("Best-scoring", -1), ("All", 100)):
            button = QPushButton(words)
            button.clicked.connect(lambda _=False, v=value: self._preset(v))
            row.addWidget(button)
            self.presets.append(button)
        self.sim_card.body().addLayout(row)
        self.sim_lead = QLabel("")
        self.sim_lead.setWordWrap(True)
        self.sim_card.add(self.sim_lead)
        self.sim_box = QVBoxLayout()
        self.sim_card.body().addLayout(self.sim_box)
        self.sim_note = QLabel(
            "Every game is priced again with the published models given the share on the slider, from none of "
            "their say (the betting line alone) to all of it. “Models” is how many priced the game and how "
            "far apart they are; “they lean” is the side their middle favours over the line, and by how many "
            "points, once the slate's shared lean and anything the line has since moved against are taken out. "
            f"A game with fewer than {recipe.FEW_MODELS} models has hardly a consensus to nudge by. "
            "Nothing here changes the card: the share in use is set by the season's results, below."
        )
        self.sim_note.setObjectName("Muted")
        self.sim_note.setWordWrap(True)
        self.sim_card.add(self.sim_note)
        self.layout_.addWidget(self.sim_card)

        # ---- the season at every share
        self.share_card = Card(SHARE_TITLE)
        self.share_chart = LineChart(self.palette, height=2.7)
        self.share_card.add(self.share_chart, 1)
        self.share_note = QLabel("")
        self.share_note.setObjectName("Muted")
        self.share_note.setWordWrap(True)
        self.share_card.add(self.share_note)
        self.layout_.addWidget(self.share_card)

        # ---- what each ingredient changed
        self.parts_card = Card(PARTS_TITLE)
        self.parts_box = QVBoxLayout()
        self.parts_card.body().addLayout(self.parts_box)
        self.parts_note = QLabel("")
        self.parts_note.setObjectName("Muted")
        self.parts_note.setWordWrap(True)
        self.parts_card.add(self.parts_note)
        self.layout_.addWidget(self.parts_card)

        # ---- the line recorder
        self.flight_card = Card(FLIGHT_TITLE)
        self.flight_chart = FlightChart(self.palette, height=2.0)
        self.flight_card.add(self.flight_chart, 1)
        self.flight_box = QVBoxLayout()
        self.flight_card.body().addLayout(self.flight_box)
        self.flight_note = QLabel(
            "Each small chart is one game's betting line from the pick's side, reading by reading: up is the "
            "market moving toward the pick. The upright line is the deadline, the level line where the published "
            "models' middle sat, and a diamond a spread typed in by hand. The lines are read more often as the "
            "deadline nears, and nothing after a game's kickoff is kept."
        )
        self.flight_note.setObjectName("Muted")
        self.flight_note.setWordWrap(True)
        self.flight_card.add(self.flight_note)
        self.layout_.addWidget(self.flight_card)

    def restyle(self) -> None:
        self.share_chart.set_palette(self.palette)
        self.flight_chart.set_palette(self.palette)
        self.refresh_now()

    # ---- which week ---------------------------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        weeks = recipe.weeks_with_lines(season)
        wanted = self.week_picker.currentData()
        if wanted not in weeks:
            # the week ahead once its models are in; until then the latest week that had them
            ahead = analytics.upcoming_week(season)
            with_models = [w for w in weeks if recipe.simulate(season, w).with_models]
            wanted = ahead if ahead in with_models else (with_models[-1] if with_models else (weeks[-1] if weeks else None))
        self._filling = True
        self.week_picker.clear()
        for number in weeks:
            self.week_picker.addItem(f"Week {number}", number)
        if wanted in weeks:
            self.week_picker.setCurrentIndex(weeks.index(wanted))
        self._filling = False
        self._render_week()
        self._render_season()

    def _week_chosen(self) -> None:
        if not self._filling and self.season is not None:
            self._render_week()

    def _render_week(self) -> None:
        season, week = self.season, self.week_picker.currentData()
        if season is None or week is None:
            self._sim = None
            self.sim_lead.setText("Appears once a week has betting lines.")
            self.clear_layout(self.sim_box)
            self.flight_chart.empty("Appears once a week has betting lines")
            self.clear_layout(self.flight_box)
            return
        self._sim = recipe.simulate(season, week)
        self.slider.blockSignals(True)
        self.slider.setValue(round(self._sim.in_use * 100))
        self.slider.blockSignals(False)
        self._render_simulator()
        self._render_flights(season, week)

    # ---- the simulator ---------------------------------------------------------------------------
    def _preset(self, value: int | None) -> None:
        sim = self._sim
        if sim is None:
            return
        if value is None:
            value = round(sim.in_use * 100)
        elif value == -1:
            best = getattr(self, "_best_share", None)
            value = round((best if best is not None else sim.in_use) * 100)
        self.slider.setValue(int(value))

    def _share(self) -> float:
        sim = self._sim
        wanted = self.slider.value() / 100
        return min(sim.shares, key=lambda s: abs(s - wanted)) if sim is not None else wanted

    def _render_simulator(self) -> None:
        self.clear_layout(self.sim_box)
        sim = self._sim
        if sim is None:
            return
        share = self._share()
        in_use = sim.in_use
        flipped = sim.flipped(share)
        self.share_label.setText(
            f"Share of the models' say: <b>{share:.0%}</b>"
            + (" - the one in use" if abs(share - in_use) < 0.005 else f" (in use: {in_use:.0%})"))
        self.share_label.setTextFormat(Qt.TextFormat.RichText)
        words = recipe.summary(sim)
        if sim.with_models and sim.graded:
            right, graded = sim.record(share)
            base_right, _ = sim.record(in_use)
            words += (f" Week {sim.week} is played: the card at {share:.0%} got {right} of {graded}"
                      + (f", the one in use {base_right}." if abs(share - in_use) >= 0.005 else "."))
        self.sim_lead.setText(words)
        rows, tones, tips = [], {}, {}
        for r, g in enumerate(sim.games):
            away, _, home = g.matchup.partition(" @ ")
            none, now, then = g.at(0.0), g.at(in_use), g.at(share)

            def said(found) -> str:
                return f"{found[0]} {found[1]:.0%}" if found else "—"

            models = "—" if not g.models else f"{g.models}, {g.apart:.1f} apart" if g.apart else f"{g.models}"
            view = ("—" if g.view is None else "with the line" if abs(g.view) < 0.05 else
                    f"{home if g.view > 0 else away} +{abs(g.view):.1f}")
            tips[(r, 3)] = ("The published models' middle against the betting line, with the slate's shared home "
                            "lean and anything the line has since moved against taken out.")
            rows.append([g.matchup, _line(g.line, home, away), models, view, said(none), said(now), said(then),
                         g.credited or "—"])
            if g.thin:
                tones[(r, 2)] = "warning"
                tips[(r, 2)] = f"Only {g.models} published models priced this game - hardly a consensus."
            elif not g.models:
                tones[(r, 2)] = tones[(r, 3)] = "muted"
            if g.flips(in_use, share):
                right = g.right(share)
                tones[(r, 6)] = "good" if right else "bad" if right is False else "warning"
                tips[(r, 6)] = "This share takes the other side from the one in use" + (
                    "" if right is None else " - and it " + ("was right." if right else "was wrong."))
            if g.credited:
                tones[(r, 7)] = "muted"
        model = TableModel(SIM_HEADERS, rows, palette=self.palette, tones=tones, tooltips=tips, bold_columns={6})
        view_, _ = make_table(model, stretch_column=0, row_height=28)
        self.sim_box.addWidget(view_)
        self.sim_card.set_title(f"{SIM_TITLE}  Week {sim.week}: "
                                + (f"{_plural(len(flipped), 'pick')} would change at {share:.0%}" if flipped
                                   else "no pick changes at this share"))

    # ---- the season at every share, and the ingredients ---------------------------------------------
    def _render_season(self) -> None:
        season = self.season
        lines = recipe.season_by_share(season) if season is not None else []
        self._best_share = None
        if lines:
            best = min(lines, key=lambda s: s.surprise)
            most = max(lines, key=lambda s: (s.right, -abs(s.share - 0.33)))
            self._best_share = best.share
            in_use = self._sim.in_use if self._sim is not None else 0.33
            at = min(lines, key=lambda s: abs(s.share - in_use))
            none = lines[0]
            self.share_chart.plot(
                [round(s.share * 100) for s in lines], [("Picks right", [s.right for s in lines])],
                xlabel="Share of the models' say (%)", ylabel=f"Right, of {lines[0].games}", direct_label=False,
            )
            self.share_note.setText(
                f"The season's {lines[0].games} graded picks, picked again at every share. With none of the "
                f"models' say it gets {none.right}; at the {at.share:.0%} in use, {at.right}; the most is "
                f"{most.right}, at {most.share:.0%}. Counted by how surprised each share was by the results "
                f"(lower is better) the best is {best.share:.0%}, at {best.surprise:.4f} a pick against "
                f"{at.surprise:.4f} in use - a difference this small over this few games is mostly luck, which "
                f"is why the share only moves when another beats it by a clear margin, and then only part of "
                f"the way. Each week is priced on the weeks before it, so the share in use can differ by week.")
        else:
            self.share_chart.empty("Appears once a week with published models has been graded")
            self.share_note.setText("")

        self.clear_layout(self.parts_box)
        parts = recipe.ingredients(season) if season is not None else []
        line = next((p for p in parts if p.name == recipe.LINE), None)
        if line is None or not line.games:
            self.parts_note.setText("Appears once a week with betting lines has been graded.")
            return
        rows, tones, tips = [], {}, {}
        for r, part in enumerate(parts):
            if part.name == recipe.LINE:
                rows.append([part.name, _plural(part.games, "game"), "where every pick starts", part.helped,
                             part.games - part.helped, f"on its own: {part.helped} of {part.games} right"])
            else:
                rows.append([part.name, _plural(part.games, "game"), part.changed if part.games else "—",
                             part.helped if part.changed else "—", part.hurt if part.changed else "—",
                             "; ".join(part.examples[:2]) if part.examples else
                             ("has had no say yet" if not part.games else "has not changed a pick")])
                if part.changed:
                    tones[(r, 3)] = "good" if part.net > 0 else ""
                    tones[(r, 4)] = "bad" if part.net < 0 else ""
            tips[(r, 0)] = recipe.ABOUT.get(part.name, "")
            tips[(r, 5)] = "\n".join(part.examples)
        model = TableModel(PART_HEADERS, rows, palette=self.palette, numeric_columns={2, 3, 4}, tones=tones,
                           tooltips=tips, bold_columns={0})
        view, _ = make_table(model, stretch_column=5, row_height=30)
        self.parts_box.addWidget(view)
        self.parts_note.setText(
            f"Each step of the recipe against the step before it, over {_plural(line.games, 'graded game')}: how "
            "many picks it turned to the other side, and how many of those turns came in. The pool's line is set "
            "against the side likelier to win the game outright - it changes the most picks because a favourite "
            "that has to win by seven is often not the side to take. A step that has changed three picks has "
            "not been tested by them: these are counts to watch, and the Model Lab's rule - enough games, and "
            "clearly better - is what decides whether anything stays in the recipe.")

    # ---- the line recorder ---------------------------------------------------------------------------
    def _render_flights(self, season, week: int) -> None:
        self.clear_layout(self.flight_box)
        found = recipe.flights(season, week)
        self.flight_card.set_title(f"{FLIGHT_TITLE} - week {week}, every reading of each game's line")
        if not found:
            self.flight_chart.empty("Appears once the week has betting lines")
            return
        self.flight_chart.plot(found)
        rows, tones = [], {}
        for r, f in enumerate(found):
            toward = f.toward_models
            rows.append([
                f.matchup, f.pick, _from_pick(f.opened), _from_pick(f.latest),
                "no move" if abs(f.moved) < 0.25 else f"{abs(f.moved):g} {'toward' if f.moved > 0 else 'away from'} the pick",
                "—" if f.models is None else _from_pick(f.models)
                + ("" if toward is None else " - the line moved " + ("toward it" if toward else "away from it")),
                len(f.readings),
            ])
            if abs(f.moved) >= 0.25:
                tones[(r, 4)] = "good" if f.moved > 0 else "bad"
        model = TableModel(FLIGHT_HEADERS, rows, palette=self.palette, numeric_columns={6}, tones=tones,
                           bold_columns={1})
        view, _ = make_table(model, stretch_column=0, row_height=27)
        self.flight_box.addWidget(view)
