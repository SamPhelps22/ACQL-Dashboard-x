"""A.C.Q.L. Picks: all three contests on one page, by the league's rules.

Main game, Big Losers and the suicide pick for any week of the season, each
from the same pricing as Your card (acql.acqlpicks), with the owner's own
official picks and results beside the recommendation and never mixed into
it. This file is layout.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ... import acqlpicks, analytics, lines, me, predictions, results, schedule
from ...places import ACQL_PICKS as title_
from ...version import MODEL_NAME
from ..widgets import Card, TableModel, make_table, section
from .base import RELOAD, Page

MAIN_HEADERS = ["#", "Game", "Type", "Pool line", "Line (open \u2192 now)", "Models (consensus)",
                "Winner (win %)", "PICK", "Credit %", "Confidence", "Compare", "My pick", "Won / credited", "Notes"]
(M_NUM, M_GAME, M_TYPE, M_LINE, M_MARKET, M_MODELS, M_WINNER, M_PICK, M_CREDIT, M_CONF, M_SEL,
 M_MINE, M_FINAL, M_NOTES) = range(len(MAIN_HEADERS))
LOSER_HEADERS = ["Rank", "Team", "Opponent", "Opponent by", "Loses by 15+", "Pick", "Lost by", "Hit"]
LOG_HEADERS = ["Week", "Team", "Status", "From"]
DASH = "—"


def _team(code: str) -> str:
    return predictions.display_team(code) if code else DASH


def _short(code: str) -> str:
    """A team as its abbreviation, for the wide table: "DAL"."""
    return code.upper() if code else DASH


def _short_line(game_line: str) -> str:
    """"Dallas by 9" -> "DAL 9"."""
    if " by " not in game_line:
        return game_line or DASH
    team, points = game_line.rsplit(" by ", 1)
    return f"{_short(predictions.team_code(team))} {points}"


def _margin(value: float | None, home: str, away: str) -> str:
    """A home margin as the favourite and their points: "DAL 7.5", "PK"."""
    if value is None:
        return DASH
    if abs(value) < analytics.PICK_EM:
        return "PK"
    return f"{(home if value > 0 else away).upper()} {abs(value):.1f}"


def _pct(value: float | None) -> str:
    return DASH if value is None else f"{value:.0%}"


class AcqlPicksPage(Page):
    title = title_
    subtitle = ("The main game, Big Losers and the suicide pick for any week - what to play by the "
                "league's rules, and your official picks kept beside it")
    icon = "\N{CLIPBOARD}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Week"))
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(150)
        self.week_picker.currentIndexChanged.connect(lambda _: self._render())
        controls.addWidget(self.week_picker)
        controls.addWidget(QLabel("Compare with"))
        self.model_picker = QComboBox()
        self.model_picker.setMinimumWidth(220)
        self.model_picker.setToolTip(
            f"Show another forecast's pick beside {MODEL_NAME}'s. The A.C.Q.L. pick itself is always "
            f"{MODEL_NAME}'s: across 2010-2025 no single model or blend picked better than the market.")
        self.model_picker.currentIndexChanged.connect(lambda _: self._render())
        controls.addWidget(self.model_picker)
        self.lines_button = QPushButton("Line games…")
        self.lines_button.setToolTip("Enter or check the commissioner's line games for this week")
        self.lines_button.clicked.connect(self._line_games)
        controls.addWidget(self.lines_button)
        self.confirm_button = QPushButton("Confirm line games")
        self.confirm_button.setCheckable(True)
        self.confirm_button.setToolTip(
            "Mark this week's line games as complete: every game without a line is then a straight pick")
        self.confirm_button.clicked.connect(self._confirm)
        controls.addWidget(self.confirm_button)
        controls.addStretch(1)
        self.layout_.addLayout(controls)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.layout_.addWidget(self.status)

        # The three answers first, side by side.
        top = QHBoxLayout()
        top.setSpacing(12)
        self.main_card, self.main_summary = self._summary_card("MAIN GAME PICKS")
        self.losers_card, self.losers_summary = self._summary_card("BIG LOSERS — TOP 3")
        self.suicide_card, self.suicide_summary = self._summary_card("SUICIDE PICK")
        for card in (self.main_card, self.losers_card, self.suicide_card):
            top.addWidget(card, 1)
        self.layout_.addLayout(top)

        self.table_card = Card("Main game - every game")
        self.table_box = QVBoxLayout()
        self.table_card.body().addLayout(self.table_box)
        self.table_note = self._note(self.table_card)
        self.layout_.addWidget(self.table_card)

        self.loser_card = Card("Big Loser - lose by more than 14")
        self.loser_box = QVBoxLayout()
        self.loser_card.body().addLayout(self.loser_box)
        self.loser_note = self._note(self.loser_card)
        self.layout_.addWidget(self.loser_card)

        self.survivor_card = Card("Suicide pool - one winner, no repeats")
        self.survivor_box = QVBoxLayout()
        self.survivor_card.body().addLayout(self.survivor_box)
        record = QHBoxLayout()
        record.addWidget(QLabel("My official pick"))
        self.suicide_team = QComboBox()
        self.suicide_team.setMinimumWidth(180)
        record.addWidget(self.suicide_team)
        self.suicide_status = QComboBox()
        for status, label in ((acqlpicks.PENDING, "Pending"), (acqlpicks.SURVIVED, "Survived"),
                              (acqlpicks.OUT, "Eliminated")):
            self.suicide_status.addItem(label, status)
        record.addWidget(self.suicide_status)
        self.suicide_save = QPushButton("Save")
        self.suicide_save.clicked.connect(self._save_suicide)
        record.addWidget(self.suicide_save)
        record.addStretch(1)
        self.survivor_card.body().addLayout(record)
        self.suicide_message = QLabel("")
        self.suicide_message.setWordWrap(True)
        self.survivor_card.add(self.suicide_message)
        self.log_box = QVBoxLayout()
        self.survivor_card.body().addLayout(self.log_box)
        self.survivor_note = self._note(self.survivor_card)
        self.layout_.addWidget(self.survivor_card)
        self._card: acqlpicks.Card | None = None
        self._history: dict[str, str] = {}

    @staticmethod
    def _summary_card(heading: str):
        card = Card(heading)
        label = QLabel("")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        card.add(label)
        return card, label

    @staticmethod
    def _note(card: Card) -> QLabel:
        note = QLabel("")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        card.add(note)
        return note

    def restyle(self) -> None:
        self.refresh_now()

    # ---- refresh -------------------------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        weeks = sorted(n for n, w in season.weeks.items() if w.games)
        upcoming = analytics.upcoming_week(season)
        wanted = self.week_picker.currentData() or upcoming
        self.week_picker.blockSignals(True)
        self.week_picker.clear()
        for number in reversed(weeks):
            self.week_picker.addItem(f"Week {number}" + ("  (this week)" if number == upcoming else ""), number)
        found = self.week_picker.findData(wanted)
        self.week_picker.setCurrentIndex(max(found, 0))
        self.week_picker.blockSignals(False)
        teams = sorted({predictions.team_code(t) for t in schedule.teams()} - {""},
                       key=lambda c: predictions.display_team(c))
        self.suicide_team.blockSignals(True)
        self.suicide_team.clear()
        self.suicide_team.addItem(DASH + " none " + DASH, "")
        for code in teams:
            self.suicide_team.addItem(predictions.display_team(code), code)
        self.suicide_team.blockSignals(False)
        self._render()

    def _week(self) -> int:
        return int(self.week_picker.currentData() or 0)

    def _models(self, week: int) -> None:
        wanted = self.model_picker.currentData() or acqlpicks.MARKET
        self.model_picker.blockSignals(True)
        self.model_picker.clear()
        for label, key in acqlpicks.model_choices(week):
            self.model_picker.addItem(label, key)
        found = self.model_picker.findData(wanted)
        self.model_picker.setCurrentIndex(max(found, 0))
        self.model_picker.blockSignals(False)

    def _render(self) -> None:
        season, week = self.season, self._week()
        if season is None or not week:
            return
        self._models(week)
        owner = me.key(season)
        model = self.model_picker.currentData() or acqlpicks.MARKET
        card = acqlpicks.build(season, week, model=model, me=owner)
        self._card = card
        year = results.season_year(season)
        self.confirm_button.blockSignals(True)
        self.confirm_button.setChecked(acqlpicks.confirmed_by_hand(year, week))
        self.confirm_button.blockSignals(False)
        if card.lines_known:
            self.status.setText(f"Week {week}: line games known from {card.lines_from}. Games without a "
                                f"line are straight picks.")
        else:
            self.status.setText(
                f"<b>Week {week}: the commissioner's line games are not confirmed yet.</b> Every game "
                f"without a line is marked <b>Unconfirmed</b> and priced straight up for now - enter the "
                f"line games, or confirm there are none, once he posts them.")
        self._history = acqlpicks.replay_lines()
        self._render_main(card)
        self._render_losers(card)
        self._render_suicide(card, owner)

    # ---- main game -------------------------------------------------------------------------
    def _render_main(self, card: acqlpicks.Card) -> None:
        self.clear_layout(self.table_box)
        rows, tones, tips = [], {}, {}
        listed = []
        selected_name = self.model_picker.currentText() or acqlpicks.MARKET
        # A note every game shares is the week's, said once above the table.
        shared = set.intersection(*(set(r.flags) for r in card.main)) if card.main else set()
        for r, row in enumerate(card.main):
            final = DASH
            if row.credited:
                won = "tie" if row.outright == "tie" else _short(row.outright)
                cred = "tie" if row.credited == "tie" else _short(row.credited)
                final = won if (won == cred or not row.outright) else f"{won} / {cred}"
            rows.append([
                row.index, f"{_short(row.away)} @ {_short(row.home)}", row.kind, _short_line(row.pool_line),
                f"{_margin(row.opening, row.home, row.away)} \u2192 {_margin(row.current, row.home, row.away)}",
                f"{row.models} \u00b7 {_margin(row.consensus, row.home, row.away)}" if row.models else DASH,
                f"{_short(row.winner)} {_pct(row.win_chance)}" if row.win_chance is not None else DASH,
                _short(row.pick), _pct(row.chance), row.confidence or DASH,
                _short(row.selected_pick),
                _short(row.mine) + ("" if row.right is None else (" \u2713" if row.right else " \u2717")),
                final,
                "; ".join(([row.if_lined] if row.if_lined else []) + [f for f in row.flags if f not in shared]),
            ])
            tips[(r, M_GAME)] = row.matchup
            if row.selected is not None:
                tips[(r, M_SEL)] = f"{selected_name}: {_margin(row.selected, row.home, row.away)}"
            if row.outright and row.outright != row.credited:
                tips[(r, M_FINAL)] = (f"{_team(row.outright)} won outright; the pool credits "
                                      f"{_team(row.credited)} under the line")
            tones[(r, M_PICK)] = "good" if row.pick else "muted"
            if row.kind == acqlpicks.UNCONFIRMED:
                tones[(r, M_TYPE)] = "warning"
            if row.right is not None:
                tones[(r, M_MINE)] = "good" if row.right else "bad"
            if row.frozen:
                tips[(r, M_PICK)] = f"From {MODEL_NAME}'s card as it was kept at the week's lock."
            mark = {acqlpicks.LINE: f" ({row.pool_line})", acqlpicks.UNCONFIRMED: " (line?)"}.get(row.kind, "")
            listed.append(f"{row.index}. {row.matchup} → <b>{_team(row.pick)}</b>{mark}"
                          if row.pick else f"{row.index}. {row.matchup} → not priced yet")
        self.main_summary.setText("<br>".join(listed) or "No games for this week.")
        if shared:
            self.status.setText(self.status.text() + "<br>Every game: " + "; ".join(sorted(shared)) + ".")
        if rows:
            model = TableModel(MAIN_HEADERS, rows, palette=self.palette, numeric_columns={M_NUM},
                               tones=tones, tooltips=tips, bold_columns={M_PICK})
            view, _ = make_table(model, stretch_column=M_NOTES, row_height=27)
            self.table_box.addWidget(view)
        priced = [r for r in card.main if r.pick]
        graded = [r for r in card.main if r.right is not None]
        mine_right = sum(1 for r in graded if r.right)
        deadeye = [r for r in card.main if r.deadeye_right is not None]
        self.table_note.setText(
            f"Win % is the chance the predicted winner wins outright; Credit % is the chance the pool "
            f"credits the A.C.Q.L. pick under its rules (on a line game the favourite must win by at "
            f"least the line - a win by exactly a whole-number line goes to the favourite). Opening, "
            f"current and consensus are the favourite and their margin. “Selected model” "
            f"shows {selected_name}'s pick for comparison only. Chances are estimates from the betting "
            f"line nudged toward the computer models, not guarantees. "
            f"{len(priced)} of {len(card.main)} games priced"
            + (f"; your picks {mine_right}/{len(graded)} right" if graded else "")
            + (f"; {MODEL_NAME} {sum(1 for r in deadeye if r.deadeye_right)}/{len(deadeye)}" if deadeye else "")
            + ". " + self._history.get("main", ""))

    # ---- Big Loser ---------------------------------------------------------------------------
    def _render_losers(self, card: acqlpicks.Card) -> None:
        self.clear_layout(self.loser_box)
        board = card.losers
        if board is None or not board.rows:
            self.losers_summary.setText("Nothing priced yet.")
            self.loser_note.setText("")
            return
        lines_ = [f"{r.rank}. <b>{_team(r.team)}</b> {'vs' if r.home else 'at'} {_team(r.opponent)} "
                  f"({r.opponent.upper()} by {r.opponent_margin:.1f}) — {r.chance:.0%}"
                  + ("" if r.hit is None else (" ✓" if r.hit else " ✗"))
                  for r in board.picks]
        if board.points is not None:
            lines_.append(f"<b>{board.points} point{'' if board.points == 1 else 's'}</b> of 3")
        self.losers_summary.setText("<br>".join(lines_))
        rows, tones = [], {}
        for i, r in enumerate(board.rows):
            rows.append([r.rank, _team(r.team), _team(r.opponent), f"{r.opponent_margin:+.1f}",
                         f"{r.chance:.0%}", "✓ pick" if r.pick else "",
                         DASH if r.lost_by is None else r.lost_by,
                         DASH if r.hit is None else ("yes" if r.hit else "no")])
            if r.pick:
                tones[(i, 5)] = "good"
            if r.hit is not None:
                tones[(i, 7)] = "good" if r.hit else "bad"
        model = TableModel(LOSER_HEADERS, rows, palette=self.palette, numeric_columns={0, 3, 4, 6},
                           tones=tones, bold_columns={1})
        view, _ = make_table(model, stretch_column=2, row_height=27)
        self.loser_box.addWidget(view)
        mine = ", ".join(_team(t) for t in board.mine) or "none recorded"
        self.loser_note.setText(
            f"Three picks, a point each for a team that loses by 15 or more; the lines play no part. "
            f"The chance comes from how often teams priced like this lost by 15+ in 1999-2025 "
            f"(analytics.big_loser_chance), widened when the models disagree. Your picks: {mine}"
            + ("" if board.my_points is None else f" - {board.my_points} point"
               f"{'' if board.my_points == 1 else 's'}") + ". Big Loser points add onto your weekly "
            "total in the standings. " + self._history.get("losers", ""))

    # ---- suicide -----------------------------------------------------------------------------
    def _render_suicide(self, card: acqlpicks.Card, owner: str) -> None:
        self.clear_layout(self.survivor_box)
        self.clear_layout(self.log_box)
        view = card.suicide
        if view is None:
            self.suicide_summary.setText(f"{me.NAME} is not in this season's data.")
            self.survivor_note.setText("")
            return
        if not view.alive:
            head = "Out of the suicide pool - nothing to pick."
        elif view.pick is not None:
            p = view.pick
            head = (f"<b>{p.team}</b> {'vs' if p.home else 'at'} {p.opponent}<br>"
                    f"{p.chance:.0%} to survive{'' if p.from_market else ' (est.)'}"
                    + (f" · {p.line}{' (line not posted yet)' if p.line_assumed else ''}" if p.line else "")
                    + f"<br>{view.advice.reason}")
        else:
            head = (view.advice.reason if view.advice is not None and view.advice.reason
                    else "No eligible team priced yet.")
        self.suicide_summary.setText(head + "".join(f"<br><b>⚠ {w}</b>" for w in view.warnings))

        rows, tones = [], {}
        options = view.advice.options if view.advice is not None else []
        for i, o in enumerate(options[:10]):
            rows.append([o.team, ("vs " if o.home else "at ") + o.opponent, f"{o.chance:.0%}"
                         + ("" if o.from_market else " est."), (o.line + ("?" if o.line_assumed else "")) or DASH,
                         "eligible", "← pick" if view.pick is not None and o.code == view.pick.code else ""])
            if rows[-1][5]:
                tones[(i, 0)] = tones[(i, 5)] = "good"
        if rows:
            model = TableModel(["Team", "Game", "Survive", "Pool line", "Status", ""], rows,
                               palette=self.palette, numeric_columns={2}, tones=tones, bold_columns={0})
            table, _ = make_table(model, stretch_column=1, row_height=27)
            self.survivor_box.addWidget(table)
        # the season's record: the log and the sheets together
        logged = {e.week: e for e in acqlpicks.suicide_log(results.season_year(self.season))}
        log_rows = []
        for team, week in sorted(view.used.items(), key=lambda kv: kv[1]):
            entry = logged.get(week)
            log_rows.append([week, _team(team), entry.status if entry and entry.team == team else "from the sheets",
                             "your log" if entry and entry.team == team else "pick sheet / workbook"])
        if log_rows:
            model = TableModel(LOG_HEADERS, log_rows, palette=self.palette, numeric_columns={0})
            table, _ = make_table(model, stretch_column=3, row_height=26)
            self.log_box.addWidget(table)
        if view.logged is not None:
            self.suicide_team.setCurrentIndex(max(self.suicide_team.findData(view.logged.team), 0))
            self.suicide_status.setCurrentIndex(max(self.suicide_status.findData(view.logged.status), 0))
        else:
            self.suicide_team.setCurrentIndex(0)
            self.suicide_status.setCurrentIndex(0)
        self.survivor_note.setText(
            "Survive by winning; on a commissioner line game the pick is judged against his line. A "
            "team can be used once a season: every team used - in your log or on the sheets - is left "
            "out of the advice. Chances are estimates from the betting lines, not guarantees. How a "
            "tie is graded is not recorded, so a tie is not counted either way here. "
            + self._history.get("suicide", ""))

    def _save_suicide(self) -> None:
        season, week = self.season, self._week()
        if season is None or not week:
            return
        warnings = acqlpicks.record_suicide(season, week, self.suicide_team.currentData() or "",
                                            self.suicide_status.currentData() or acqlpicks.PENDING,
                                            me=me.key(season))
        team = self.suicide_team.currentData()
        self.suicide_message.setText(
            ("⚠ " + " ".join(warnings) + " " if warnings else "")
            + (f"Week {week}: {predictions.display_team(team)} saved as your official pick."
               if team else f"Week {week}: official pick cleared."))
        self._render()

    # ---- line games ----------------------------------------------------------------------------
    def _confirm(self, checked: bool) -> None:
        season, week = self.season, self._week()
        if season is None or not week:
            return
        acqlpicks.confirm_lines(results.season_year(season), week, checked)
        self._render()

    def _line_games(self) -> None:
        season, week = self.season, self._week()
        found = season.weeks.get(week) if season is not None else None
        if found is None or not found.games:
            return
        from .nextweek import OddsDialog
        year = results.season_year(season)
        games = sorted(found.games, key=lambda g: g.index)
        dialog = OddsDialog(
            week, self, title=f"Week {week} line games",
            blurb=("One line game a line, the way the pick sheet writes them - (kc by 10), Chiefs by 10 "
                   "or KC -10. Games not listed are straight picks. The commissioner's pick sheet, once "
                   "it is in, overrides what is typed here."),
            placeholder="(kc by 10)\n(buf by 7)", button="Save line games",
            text=lines.pool_lines_text(year, week) or "\n".join(
                f"({predictions.team_code(g.line_favourite)} by {g.line:g})"
                for g in games if g.line is not None and predictions.team_code(g.line_favourite)))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        typed, problems = lines.parse_pool_lines(dialog.text(), games)
        if problems and not typed:
            self.status.setText("Line games not saved - " + "; ".join(problems[:4]) + ".")
            return
        lines.save_pool_lines(year, week, typed)
        acqlpicks.confirm_lines(year, week, True)
        # The slate's lines are applied when the season loads: reload everything.
        self.action_requested.emit(RELOAD)
