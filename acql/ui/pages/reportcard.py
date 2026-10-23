"""The Model's report card: how accurate it is, and should you follow it.

The answer first, then the evidence for it in the order anyone would ask:
how often it is right, how that compares with you and the pool, whether its
chances can be trusted, and what fifteen seasons say. The workings live in
acql.reportcard; this file is layout.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ...model import grades, reportcard
from ...pool import journal, me
from ..charts import LineChart
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from ...version import MODEL_NAME
from ...wording import ordinal as _ordinal, plural as _plural
from .base import Page

VERDICT_TITLE = "Should I follow it?"
WEEKS_TITLE = "Week by week - its card against yours"
WEEK_HEADERS = ["Week", f"{MODEL_NAME}'s card", "Line alone", "Its chances said", "You", "Pool average",
                "Week's best", f"{MODEL_NAME} would have been", "You were"]
GRADES_TITLE = "Subject by subject"
RUNNING_TITLE = "Running total - games ahead of the pool's average coach"
STANDING_TITLE = "Where its card would stand in the pool"
STANDING_HEADERS = ["Place", "Coach", "Games right"]
LOSER_TITLE = "Big Losers - its three likeliest against yours"
LOSER_HEADERS = ["Week", f"{MODEL_NAME}'s three", "Its points", "Your points"]
JOURNAL_TITLE = "Your calls against it - and whose reasons hold up"
LONG_TITLE = "Over the long run - 2011 to 2025 under this pool's rules"
#: Shared with The Model > Details so both pages remember the same coach.
ME_KEY = "insights/me"


class ReportCardPage(Page):
    from ...places import REPORT_CARD as title
    subtitle = f"{MODEL_NAME}'s grades: an overall mark, eight subjects, and whether to follow its card"
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

        top = QHBoxLayout()
        top.setSpacing(16)
        self.grade_card = Card("Overall grade")
        self.grade_card.setFixedWidth(250)
        self.grade_card.setMinimumHeight(236)
        self.grade_label = QLabel("")
        self.grade_label.setTextFormat(Qt.TextFormat.RichText)
        self.grade_label.setWordWrap(True)
        self.grade_card.add(self.grade_label)
        top.addWidget(self.grade_card, 0)
        self.verdict_card = Card(VERDICT_TITLE)
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        self.verdict.setTextFormat(Qt.TextFormat.RichText)
        self.verdict_card.add(self.verdict)
        top.addWidget(self.verdict_card, 1)
        self.layout_.addLayout(top)

        self.grades_card = Card(GRADES_TITLE)
        self.grades_box = QGridLayout()
        self.grades_box.setHorizontalSpacing(22)
        self.grades_box.setVerticalSpacing(7)
        self.grades_box.setColumnStretch(2, 5)
        self.grades_box.setColumnStretch(3, 6)
        self.grades_card.body().addLayout(self.grades_box)
        self.grades_note = QLabel("")
        self.grades_note.setObjectName("Muted")
        self.grades_note.setTextFormat(Qt.TextFormat.RichText)
        self.grades_note.setWordWrap(True)
        self.grades_card.add(self.grades_note)
        self.layout_.addWidget(self.grades_card)

        self.tile_right = StatTile("Games Right")
        self.tile_line = StatTile("Against The Line")
        self.tile_you = StatTile("Against You")
        self.tile_pool = StatTile("In The Pool")
        self.tile_best = StatTile("Week's Best Score")
        self.tile_honest = StatTile("Honest Chances")
        self.tile_margin = StatTile("Margin Error")
        self.tile_form = StatTile("Best And Worst Week")
        self._tiles = (self.tile_right, self.tile_line, self.tile_you, self.tile_pool,
                       self.tile_best, self.tile_honest, self.tile_margin, self.tile_form)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.weeks_card = Card(WEEKS_TITLE)
        self.weeks_chart = LineChart(self.palette, height=3.0)
        self.weeks_card.add(self.weeks_chart, 1)
        self.weeks_box = QVBoxLayout()
        self.weeks_card.body().addLayout(self.weeks_box)
        self.weeks_note = QLabel(
            f"{MODEL_NAME}'s card is the one Picks recommends, saved before the first kickoff. "
            "\u201cLine alone\u201d is what the betting line scored. \u201cIts chances said\u201d is "
            "what it expected to get. \u201cRebuilt\u201d weeks were re-made after the fact, which "
            "flatters it slightly."
        )
        self.weeks_note.setObjectName("Muted")
        self.weeks_note.setTextFormat(Qt.TextFormat.RichText)
        self.weeks_note.setWordWrap(True)
        self.weeks_card.add(self.weeks_note)
        self.layout_.addWidget(self.weeks_card, 1)

        lower = QHBoxLayout()
        lower.setSpacing(16)
        self.running_card = Card(RUNNING_TITLE)
        self.running_chart = LineChart(self.palette, height=3.0)
        self.running_card.add(self.running_chart, 1)
        self.running_note = QLabel(
            "Each line is a card's games right so far, minus the pool's average coach. "
            "A line going up is pulling away from the pool."
        )
        self.running_note.setObjectName("Muted")
        self.running_note.setWordWrap(True)
        self.running_card.add(self.running_note)
        lower.addWidget(self.running_card, 3)
        self.standing_card = Card(STANDING_TITLE)
        self.standing_lead = QLabel("")
        self.standing_lead.setWordWrap(True)
        self.standing_card.add(self.standing_lead)
        self.standing_box = QVBoxLayout()
        self.standing_card.body().addLayout(self.standing_box)
        self.standing_card.body().addStretch(1)
        lower.addWidget(self.standing_card, 2)
        self.layout_.addLayout(lower)

        self.loser_card = Card(LOSER_TITLE)
        self.loser_summary = QLabel("")
        self.loser_summary.setWordWrap(True)
        self.loser_card.add(self.loser_summary)
        self.loser_box = QVBoxLayout()
        self.loser_card.body().addLayout(self.loser_box)
        self.layout_.addWidget(self.loser_card)

        # The decision journal (pool/journal.py): each game taken against Deadeye, why, and who was right.
        self.journal_card = Card(JOURNAL_TITLE)
        self.journal_lead = QLabel("")
        self.journal_lead.setWordWrap(True)
        self.journal_lead.setTextFormat(Qt.TextFormat.RichText)
        self.journal_card.add(self.journal_lead)
        self.journal_box = QVBoxLayout()
        self.journal_card.body().addLayout(self.journal_box)
        editor = QHBoxLayout()
        self.journal_game = QComboBox()
        self.journal_game.setMinimumWidth(320)
        self.journal_game.currentIndexChanged.connect(self._journal_pick)
        self.journal_tag = QComboBox()
        self.journal_tag.addItem("no reason", "")
        for tag in journal.TAGS:
            self.journal_tag.addItem(tag, tag)
        self.journal_note = QLineEdit()
        self.journal_note.setPlaceholderText("Why, in a line (optional)")
        self.journal_note.setMaxLength(200)
        self.journal_save = QPushButton("Keep reason")
        self.journal_save.clicked.connect(self._journal_keep)
        for widget, stretch in ((QLabel("Game"), 0), (self.journal_game, 0), (QLabel("Reason"), 0),
                                (self.journal_tag, 0), (self.journal_note, 1), (self.journal_save, 0)):
            editor.addWidget(widget, stretch)
        self.journal_editor = QWidget()
        self.journal_editor.setLayout(editor)
        self.journal_card.add(self.journal_editor)
        self.journal_note_label = QLabel("")
        self.journal_note_label.setObjectName("Muted")
        self.journal_note_label.setWordWrap(True)
        self.journal_card.add(self.journal_note_label)
        self.layout_.addWidget(self.journal_card)
        self._overrides: list = []

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

        # ---- time-travel: a past week as it stood at its deadline (#7)
        self.past_card = Card("As it stood at the deadline")
        pick_row = QHBoxLayout()
        self.past_week = QComboBox()
        self.past_week.currentIndexChanged.connect(self._render_past)
        pick_row.addWidget(self.past_week)
        pick_row.addStretch(1)
        self.past_card.body().addLayout(pick_row)
        self.past_lead = QLabel("")
        self.past_lead.setWordWrap(True)
        self.past_card.add(self.past_lead)
        self.past_box = QVBoxLayout()
        self.past_card.body().addLayout(self.past_box)
        self.past_note = QLabel("")
        self.past_note.setObjectName("Muted")
        self.past_note.setWordWrap(True)
        self.past_card.add(self.past_note)
        self.layout_.addWidget(self.past_card)

    def _fill_past_weeks(self) -> None:
        from ...model import deadline
        wanted = self.past_week.currentData()
        found = deadline.weeks(self.season)
        self.past_week.blockSignals(True)
        self.past_week.clear()
        for n in found:
            self.past_week.addItem(f"Week {n}", n)
        at = self.past_week.findData(wanted) if wanted is not None else -1
        self.past_week.setCurrentIndex(at if at >= 0 else (1 if len(found) > 1 else 0))
        self.past_week.blockSignals(False)
        self.past_card.setVisible(bool(found))
        self._render_past()

    def _render_past(self, *_args) -> None:
        from ...model import deadline
        week = self.past_week.currentData()
        self.clear_layout(self.past_box)
        if week is None or self.season is None:
            return
        v = deadline.view(self.season, int(week))
        self.past_lead.setText(
            f"Week {week}'s lines were written down {deadline.stamp(v.snapshot_at)}"
            + (" and sealed at the deadline" if v.frozen else "")
            + f"; {MODEL_NAME}'s card was recorded {deadline.stamp(v.card_at)}."
            + (f" Your card was saved {deadline.stamp(v.mine_at)}." if v.mine_at else ""))
        rows = []
        for r in v.rows:
            outcome = ""
            if r.result:
                you = "you ✓" if r.yours and r.yours == r.result else "you ✗" if r.yours else ""
                model = f"{MODEL_NAME} ✓" if r.deadeye == r.result else f"{MODEL_NAME} ✗" if r.deadeye else ""
                outcome = f"{r.result} · " + " · ".join(x for x in (you, model) if x)
            rows.append([r.matchup, r.line or "—", r.pool_line or "—", r.deadeye or "—",
                         f"{r.chance:.0%}" if r.chance is not None else "—", r.yours or "—", outcome or "to play"])
        if rows:
            model_ = TableModel(["Game", "Line then", "Pool line", MODEL_NAME, "Chance then", "You",
                                 "What happened"], rows, palette=self.palette, bold_columns={0})
            view, _ = make_table(model_, stretch_column=6)
            self.past_box.addWidget(view)
        self.past_note.setText(" ".join(v.caveats()) + " Everything left of 'What happened' is as it was "
                               "written down before the deadline; nothing in it is rebuilt with hindsight"
                               + (" except where said." if v.caveats() else "."))

    def restyle(self) -> None:
        self.weeks_chart.set_palette(self.palette)
        self.running_chart.set_palette(self.palette)
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        wanted = self.me_picker.currentData() or me.key(season) or QSettings().value(ME_KEY, "") \
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
        self._fill_past_weeks()

    def _render(self) -> None:
        season = self.season
        if season is None:
            return
        key = self.me_picker.currentData()
        if key:
            QSettings().setValue(ME_KEY, key)
        name = self.me_picker.currentText() or "you"
        report = reportcard.build(season, key, name)
        card = grades.build(season, report, key)
        self._render_verdict(report)
        self._render_grades(card)
        self._render_tiles(report)
        self._render_more_tiles(report, card)
        self._render_weeks(report, card)
        self._render_running(report, card)
        self._render_standing(report, card)
        self._render_losers(report)
        self._render_journal(key)
        self._render_long_run(report)

    # ---- the decision journal ---------------------------------------------------
    def _render_journal(self, key: str) -> None:
        self.clear_layout(self.journal_box)
        season = self.season
        mine = bool(key) and key == me.key(season)
        self.journal_editor.setVisible(mine)
        if not mine:
            self._overrides = []
            self.journal_lead.setText(f"The journal is {me.NAME}'s own: choose {me.NAME} above to see it.")
            self.journal_note_label.setText("")
            return
        found = journal.overrides(season)
        self._overrides = found
        tallies = journal.tallies(found)
        total = next((t for t in tallies if t.tag == "all"), None)
        if total is None:
            self.journal_lead.setText(f"No game yet where your card went against {MODEL_NAME}'s.")
            self.journal_note_label.setText("")
            self.journal_editor.hide()
            return
        self.journal_lead.setText(
            f"<b>{_plural(total.games, 'game')} taken against {MODEL_NAME}</b>: you were right and it wrong "
            f"{total.you} time{'' if total.you == 1 else 's'}, it right and you wrong {total.deadeye}"
            + (f", {total.games - total.decided} still to play" if total.games > total.decided else "")
            + ". Give each one a reason and the reasons are scored below: the ones worth keeping show themselves.")
        rows = [[t.tag, t.games, t.decided, t.you, t.deadeye, f"{t.net:+d}"] for t in tallies]
        tones = {(r, 5): ("good" if t.net > 0 else "bad" if t.net < 0 else "muted") for r, t in enumerate(tallies)}
        model = TableModel(["Reason", "Games", "Decided", "You right", f"{MODEL_NAME} right", "Net"], rows,
                           palette=self.palette, numeric_columns={1, 2, 3, 4, 5}, tones=tones, bold_columns={0})
        view, _ = make_table(model, stretch_column=0, row_height=26)
        self.journal_box.addWidget(view)
        detail = [[o.week, o.matchup, o.yours, o.deadeye + (" (rebuilt)" if o.rebuilt else ""), o.credited or "-",
                   o.outcome, o.tag or "-", o.note] for o in reversed(found)]
        tones = {(r, 5): ("good" if row[5] == "you" else "bad" if row[5] == MODEL_NAME else "muted")
                 for r, row in enumerate(detail)}
        model = TableModel(["Week", "Game", "You took", f"{MODEL_NAME} took", "Credited", "Right", "Reason", "Note"],
                           detail, palette=self.palette, numeric_columns={0}, tones=tones, bold_columns={2})
        view, _ = make_table(model, stretch_column=7, row_height=26)
        self.journal_box.addWidget(view)
        self.journal_game.blockSignals(True)
        current = self.journal_game.currentData()
        self.journal_game.clear()
        for o in reversed(found):
            self.journal_game.addItem(f"Week {o.week} · {o.matchup} · you {o.yours}", o.key)
        at = self.journal_game.findData(current) if current else -1
        self.journal_game.setCurrentIndex(max(at, 0))
        self.journal_game.blockSignals(False)
        self._journal_pick()
        rebuilt = sorted({o.week for o in found if o.rebuilt})
        self.journal_note_label.setText(
            "Your side is your row on the commissioner's sheet; " + MODEL_NAME + "'s is its card as kept at the "
            "deadline" + (f" (weeks {', '.join(map(str, rebuilt))}: rebuilt afterwards, as nothing was kept then)"
                          if rebuilt else "") + ". Right means credited by the pool's rule. Small counts say little: "
            "a reason needs a dozen or so decided games before its net means much.")

    def _journal_pick(self, _index: int = 0) -> None:
        key = self.journal_game.currentData()
        found = next((o for o in self._overrides if o.key == key), None)
        self.journal_tag.setCurrentIndex(max(self.journal_tag.findData(found.tag if found else ""), 0))
        self.journal_note.setText(found.note if found else "")

    def _journal_keep(self) -> None:
        key = self.journal_game.currentData()
        if not key:
            return
        week, index = (int(part) for part in str(key).split("-"))
        journal.give_reason(week, index, self.journal_tag.currentData() or "", self.journal_note.text())
        self._render_journal(self.me_picker.currentData())

    # ---- the answer ---------------------------------------------------------
    def _render_verdict(self, report: reportcard.Report) -> None:
        colour = getattr(self.palette, "good" if report.tone == "good" else "ink", "")
        bullets = "".join(f"<li>{reason}</li>" for reason in report.reasons)
        self.verdict.setText(
            f"<p style='font-size:20px; font-weight:700;{f' color:{colour};' if colour else ''} margin:0'>"
            f"{report.headline}</p>"
            f"<ul style='margin-top:6px'>{bullets}</ul>"
            f"<p style='margin:0'>Picks plays {MODEL_NAME}'s card by default: the likeliest "
            "side of every game and the three likeliest Big Losers (<i>Safe</i>). You can also choose "
            "<i>Win the week</i>, which picks Big Losers the pool isn't on, or <i>Long shot</i>, "
            "which turns games against the pool.</p>"
        )

    # ---- the grades -----------------------------------------------------------
    def _render_grades(self, card: grades.Card) -> None:
        p = self.palette
        colours = {"good": p.good, "warning": p.warning, "bad": p.critical, "muted": p.ink_muted, "": p.accent}
        overall = card.overall
        if overall:
            best, worst = card.best, card.worst
            self.grade_label.setText(
                f"<div style='font-size:64px; font-weight:800; color:{colours[grades.tone(overall)]}; "
                f"margin:0'>{overall.replace('-', '&minus;')}</div>"
                f"<div style='color:{p.ink_secondary}'>{'Provisional \u00b7 ' if card.provisional else ''}"
                f"{_plural(card.weeks, 'week')} \u00b7 {len(card.marked)} of {len(card.subjects)} marked</div>"
                + (f"<div>Best: <b>{best.name}</b> ({best.grade.replace('-', '&minus;')})</div>"
                   f"<div>Weakest: <b>{worst.name}</b> ({worst.grade.replace('-', '&minus;')})</div>"
                   if best is not None and worst is not None and best is not worst else "")
            )
        else:
            self.grade_label.setText(
                f"<div style='font-size:64px; font-weight:800; color:{p.ink_muted}; margin:0'>&ndash;</div>"
                f"<div style='color:{p.ink_secondary}'>Marked once a week is graded</div>")
        # Laid out as wrapped lines rather than a table: the reading under each
        # grade is a sentence, and a table would cut it short.
        self.clear_layout(self.grades_box)
        for r, s in enumerate(card.subjects):
            colour = colours[grades.tone(s.grade)]
            name = QLabel(f"<b>{s.name}</b>")
            mark = QLabel(f"<span style='font-size:20px; font-weight:800; color:{colour}'>"
                          f"{s.grade.replace('-', '&minus;') or '&ndash;'}</span>")
            mark.setMinimumWidth(46)
            figure = QLabel(f"{s.figure}<br><span style='color:{p.ink_muted}'>{s.against}</span>")
            reading = QLabel(
                f"<span style='color:{p.ink_secondary}'>{s.meaning}</span>"
                + (f"<br><span style='color:{p.ink_muted}'><b>To raise it:</b> {s.better}</span>" if s.better else ""))
            for column, label in enumerate((name, mark, figure, reading)):
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setWordWrap(column >= 2)
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                if s.scale:
                    label.setToolTip(s.scale)
                self.grades_box.addWidget(label, 2 * r, column)
            if r < len(card.subjects) - 1:
                rule = QFrame()
                rule.setFixedHeight(1)
                rule.setStyleSheet(f"background: {p.grid}; border: none;")
                self.grades_box.addWidget(rule, 2 * r + 1, 0, 1, 4)
        self.grades_note.setText(
            f"Each subject is one number compared with one yardstick. Hover over a grade to see its scale. "
            f"Level with the betting line is a B, because beating the market is rare."
            + (f" The overall grade is provisional until {grades.MATURE_WEEKS} weeks are in."
               if card.provisional else "")
        )

    def _render_more_tiles(self, report: reportcard.Report, card: grades.Card) -> None:
        hits = card.hits
        overall = getattr(hits, "overall", None)
        if overall is not None and overall.line_games:
            ahead = overall.right - overall.line_right
            self.tile_line.update_values(
                f"{ahead:+d}" if ahead else "level",
                f"games, on the same {overall.line_games}\n"
                f"{overall.right} to the betting line's {overall.line_right}",
                "good" if ahead >= 3 else "bad" if ahead <= -3 else "",
            )
        else:
            self.tile_line.update_values(self.NO_VALUE, "needs a graded week with betting lines")
        stand = card.standing
        if stand is not None:
            mine = (f"\n{report.coach} would be {_ordinal(stand.mine[0])} with {stand.mine[1]}" if stand.mine else "")
            self.tile_pool.update_values(
                ("T-" if stand.tied else "") + _ordinal(stand.rank),
                f"of {stand.of} with {stand.total} \u00b7 the best coach: {stand.leader[0]}, {stand.leader[1]}{mine}",
                "good" if stand.share >= 0.75 else "",
            )
        else:
            self.tile_pool.update_values(self.NO_VALUE, "appears once a week is graded")
        error = getattr(hits, "error", None)
        if error is not None and error.games:
            self.tile_margin.update_values(
                f"{error.deadeye:.1f} pts",
                f"average miss on the final margin, {error.games} games\nthe betting line alone: {error.line:.1f}",
                "good" if error.deadeye < error.line - 0.15 else "bad" if error.deadeye > error.line + 0.15 else "",
            )
        else:
            self.tile_margin.update_values(self.NO_VALUE, "needs final scores from the scoreboard")
        if report.weeks:
            best = max(report.weeks, key=lambda w: (w.model / max(1, w.games), -w.week))
            worst = min(report.weeks, key=lambda w: (w.model / max(1, w.games), w.week))
            self.tile_form.update_values(
                f"{best.model} & {worst.model}",
                f"best: week {best.week}, {best.model} of {best.games} ({_ordinal(best.model_place)})\n"
                f"worst: week {worst.week}, {worst.model} of {worst.games} ({_ordinal(worst.model_place)})",
            )
        else:
            self.tile_form.update_values(self.NO_VALUE, "appears once a week is graded")

    def _render_running(self, report: reportcard.Report, card: grades.Card) -> None:
        weeks = report.weeks
        if not weeks:
            self.running_chart.empty("Appears once a week is graded")
            return
        by_week = card.by_week()

        def running(values):
            total, out = 0.0, []
            for value, w in zip(values, weeks):
                if value is None:
                    out.append(None)
                    continue
                total += value - w.pool_average
                out.append(round(total, 1))
            return out

        series = [(MODEL_NAME, running([w.model for w in weeks]))]
        # the betting line's side; a week where a game had no line is judged
        # against the pool's average on just the games that had one
        line, known = [], True
        for w in weeks:
            n = by_week.get(w.week, (0, 0, 0.0))[0]
            known = known and n > 0
            if not known:
                line.append(None)
            elif n == w.games:
                line.append(by_week[w.week][1])
            else:
                line.append(by_week[w.week][1] + w.pool_average * (w.games - n) / w.games)
        if sum(v is not None for v in line) >= 2:
            series.append(("Betting line", running(line)))
        if any(w.mine is not None for w in weeks):
            series.append((report.coach, running([w.mine for w in weeks])))
        self.running_chart.plot(
            [w.week for w in weeks], series, ylabel="Games ahead",
            reference=("Pool average", [0.0 for _ in weeks]),
            front=(MODEL_NAME,),    # stays visible where it and the line agree
        )

    def _render_standing(self, report: reportcard.Report, card: grades.Card) -> None:
        self.clear_layout(self.standing_box)
        stand = card.standing
        if stand is None:
            self.standing_lead.setText("Appears once a week is graded.")
            return
        self.standing_lead.setText(
            f"Regular games over the same {_plural(len(report.weeks), 'week')}: its card would be "
            f"{'tied ' if stand.tied else ''}{_ordinal(stand.rank)} of {stand.of}."
        )
        rows, tones = [], {}
        for r, (rank, name, total) in enumerate(stand.table):
            rows.append([_ordinal(rank), name, total])
            if name == f"{MODEL_NAME}'s card":
                tones[(r, 1)] = tones[(r, 2)] = "good"
        model = TableModel(STANDING_HEADERS, rows, palette=self.palette, numeric_columns={2}, tones=tones,
                           bold_columns={1})
        view, _ = make_table(model, stretch_column=1, row_height=28)
        self.standing_box.addWidget(view)

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
    def _render_weeks(self, report: reportcard.Report, card: grades.Card | None = None) -> None:
        by_week = card.by_week() if card is not None else {}
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
            picks, line_hits, said = by_week.get(w.week, (0, 0, 0.0))
            rows.append([
                f"{w.week}" + ("  (rebuilt)" if w.rebuilt else ""),
                f"{w.model} of {w.games}",
                (f"{line_hits}" + ("" if picks == w.games else f" of {picks}")) if picks else self.NO_VALUE,
                f"{said:.1f}" if picks else self.NO_VALUE,
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
                tones[(r, 7)] = "good"
            tones[(r, 2)] = tones[(r, 3)] = "muted"
        model = TableModel(WEEK_HEADERS, rows, palette=self.palette,
                           numeric_columns={1, 2, 3, 4, 5, 6}, tones=tones, bold_columns={1})
        view, _ = make_table(model, stretch_column=7, row_height=28)
        self.weeks_box.addWidget(view)

    # ---- big losers -------------------------------------------------------------
    def _render_losers(self, report: reportcard.Report) -> None:
        self.clear_layout(self.loser_box)
        found = report.losers
        if not found:
            self.loser_summary.setText(
                "This is graded once a week has its pick sheet and final scores."
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
        from ...model import backtest
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
