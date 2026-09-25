"""This Week: the card to hand in, and why.

The other pages answer questions. This one answers the question - what to
play - and answers it in the order the decision is actually made: how the
week looks, which few games decide it, the card itself, then the side pools.

It works entirely off `acql.briefing`, which knows nothing about Qt and is
checked against real weeks without a screen. This file is layout.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ... import briefing, cards, odds, survivor
from ...predictions import display_team
from ...models import Season
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from .base import Page

HEADERS = ["#", "Game", "Take", "Chance", "Vs pool", "If flipped", "Pool line", "Why"]
(COL_NUM, COL_GAME, COL_TAKE, COL_CHANCE, COL_EDGE, COL_FLIP, COL_LINE, COL_WHY) = range(8)
#: A flip that moves the week-winning chance by less than this is noise.
FLIP_NOISE = 0.001
CHANGES_TITLE = "Did anything change?"

CARD_TITLE = "Your card"
SWING_TITLE = "Where the week is won"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _when(at: float) -> str:
    """"Thu 6:10 pm" - or "today 6:10 pm"."""
    stamp = time.localtime(at)
    day = "today" if time.strftime("%Y%m%d", stamp) == time.strftime("%Y%m%d") \
        else time.strftime("%a", stamp)
    return f"{day} {time.strftime('%I:%M %p', stamp).lstrip('0').lower()}"


class _Fetcher(QThread):
    """Fetches the lines off the main thread; the API can take a few seconds."""

    done = Signal(object)      # (quotes, remaining) or the reason it failed

    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key

    def run(self) -> None:
        try:
            self.done.emit(odds.fetch(self.key))
        except odds.OddsError as exc:
            self.done.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - shown to the person, never swallowed
            self.done.emit(f"Updating the lines failed: {exc}")


class OddsDialog(QDialog):
    """The Odds API key. Asked for once."""

    def __init__(self, reason: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Betting lines")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        intro = QLabel(
            (f"<p style='color:#d03b3b'>{reason}</p>" if reason else "")
            + "Lines come from <b>The Odds API</b>. Its free plan is 500 "
            "requests a month, and one update is one request. Sign up with "
            f"just an email at <a href='{odds.SIGNUP_PAGE}'>the-odds-api.com</a>, "
            "and paste the key it emails you below. It is stored locked to "
            "your Windows account."
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)
        form = QFormLayout()
        self.key = QLineEdit("")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(
            "saved - leave blank to keep it" if odds.api_key() else "your API key"
        )
        form.addRow("API key", self.key)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self) -> None:
        if self.key.text().strip():
            odds.set_api_key(self.key.text())


class BriefingPage(Page):
    title = "This Week"
    subtitle = "The card most likely to win the week, and the games that decide it"
    icon = "\N{MEMO}"

    #: Asks the window to re-read everything - after new lines are stored.
    refresh_requested = Signal()

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self._brief: briefing.Brief | None = None

        self._fetcher: _Fetcher | None = None
        self._week_shown = 0
        self._update_note = ""        # what the last "Update lines" did
        head = QHBoxLayout()
        head.addWidget(section(self.title, self.subtitle), 1)
        self.style_picker = QComboBox()
        self.style_picker.addItem("Card: built to win the week", briefing.STYLE_WIN)
        self.style_picker.addItem("Card: most games right", briefing.STYLE_STRAIGHT)
        self.style_picker.setToolTip(
            "Built to win the week turns a game or two against the pool when "
            "that makes finishing first likelier; most games right takes the "
            "likelier side everywhere, which is what counts toward the season "
            "title. Replayed over 2011-2025 the two won about as many weeks - "
            "see Insights > The model."
        )
        wanted = QSettings().value(self.STYLE_KEY, briefing.STYLE_WIN)
        found = self.style_picker.findData(wanted)
        self.style_picker.setCurrentIndex(max(found, 0))
        self.style_picker.currentIndexChanged.connect(self._style_changed)
        self.lines_button = QPushButton("\u21bb  Update lines")
        self.lines_button.setToolTip(
            "Fetch the latest betting lines for this week and re-plan the card"
        )
        self.lines_button.clicked.connect(self._update_lines)
        head.addWidget(self.lines_button, 0)
        self.lines_settings = QPushButton("\u2699")
        self.lines_settings.setToolTip("The Odds API key")
        self.lines_settings.setFixedWidth(36)
        self.lines_settings.clicked.connect(lambda: self._odds_settings())
        head.addWidget(self.lines_settings, 0)
        self.save_button = QPushButton("\N{PUSHPIN}  Save card")
        self.save_button.setToolTip(
            "Remember this card as the one you're handing in, so any change "
            "before the lock can be pointed out"
        )
        self.save_button.clicked.connect(self._save_card)
        head.addWidget(self.save_button, 0)
        self.copy_button = QPushButton("Copy as text")
        self.copy_button.setToolTip(
            "Put the whole briefing on the clipboard, ready to paste into a "
            "message"
        )
        self.copy_button.clicked.connect(self._copy)
        head.addWidget(self.copy_button, 0)
        self.layout_.addLayout(head)
        # Second row: which card to play, and where the lines stand.
        options = QHBoxLayout()
        options.setSpacing(12)
        options.addWidget(self.style_picker, 0)
        self.lines_status = QLabel("")
        self.lines_status.setObjectName("Muted")
        self.lines_status.setWordWrap(True)
        options.addWidget(self.lines_status, 1)
        self.layout_.addLayout(options)

        self.tile_expected = StatTile("Expected Wins")
        self.tile_swing = StatTile("Biggest Swing")
        self.tile_pays = StatTile("Chance To Win The Week")
        self.tile_flips = StatTile("Coin Flips")
        self._tiles = (
            self.tile_expected, self.tile_swing, self.tile_pays, self.tile_flips,
        )
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        # What moved since the card was saved (or since the last update).
        self.changes_card = Card(CHANGES_TITLE)
        self.changes_box = QVBoxLayout()
        self.changes_card.body().addLayout(self.changes_box)
        self.layout_.addWidget(self.changes_card)
        self.changes_card.hide()

        # The swings go above the card. They are three lines and they are the
        # reason the card looks the way it does, so they are read first.
        self.swing_card = Card(SWING_TITLE)
        self.swing_box = QVBoxLayout()
        self.swing_card.body().addLayout(self.swing_box)
        self.layout_.addWidget(self.swing_card)

        self.card = Card(CARD_TITLE)
        self.card_box = QVBoxLayout()
        self.card.body().addLayout(self.card_box)
        self.layout_.addWidget(self.card, 2)
        self.table: QWidget | None = None

        self.side_card = Card("The side pools")
        self.side_box = QVBoxLayout()
        self.side_card.body().addLayout(self.side_box)
        self.layout_.addWidget(self.side_card)

        # The suicide pool: which team to spend this week, for any coach.
        self.suicide_card = Card("Suicide pool")
        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Coach"))
        self.coach_picker = QComboBox()
        self.coach_picker.setMinimumWidth(220)
        self.coach_picker.currentIndexChanged.connect(lambda _: self._render_suicide())
        chooser.addWidget(self.coach_picker)
        chooser.addStretch(1)
        self.suicide_card.body().addLayout(chooser)
        self.suicide_advice = QLabel("")
        self.suicide_advice.setWordWrap(True)
        self.suicide_advice.setTextFormat(Qt.TextFormat.RichText)
        self.suicide_card.add(self.suicide_advice)
        self.suicide_box = QVBoxLayout()
        self.suicide_card.body().addLayout(self.suicide_box)
        self.suicide_note = QLabel("")
        self.suicide_note.setObjectName("Muted")
        self.suicide_note.setWordWrap(True)
        self.suicide_card.add(self.suicide_note)
        self.layout_.addWidget(self.suicide_card)
        self._suicide_week = 0

    def restyle(self) -> None:
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        week = self._week(season)
        self._week_shown = week
        self._update_suicide(season, week)
        self._brief = briefing.build(season, week, self._style()) if week else None
        brief = self._brief
        self.card.set_title(f"{CARD_TITLE} - week {week}" if week else CARD_TITLE)
        self._update_lines_status(week)

        if brief is None or not brief.choices:
            self._show_empty(week)
            self.changes_card.hide()
            return

        # The model's card is kept as it stands before the first kickoff, to
        # be scored against yours once the week is graded (Insights).
        cards.record_model(season, week, brief)
        self.copy_button.setEnabled(True)
        self.save_button.setEnabled(not cards.week_started(season, week))
        self._update_changes(week, brief)
        self._update_tiles(brief)
        self._update_swings(brief)
        self._update_table(brief)
        self._update_side(brief)

    # ---- which card --------------------------------------------------------
    STYLE_KEY = "thisweek/style"

    def _style(self) -> str:
        return self.style_picker.currentData() or briefing.STYLE_WIN

    def _style_changed(self, _index: int = 0) -> None:
        QSettings().setValue(self.STYLE_KEY, self._style())
        self.refresh_now()

    # ---- the suicide pool ------------------------------------------------
    SUICIDE_KEY = "thisweek/suicide_coach"
    SUICIDE_SHOWN = 10

    def _update_suicide(self, season: Season, week: int) -> None:
        """Fill the coach list - still alive first - and keep the choice."""
        self._suicide_week = week
        wanted = self.coach_picker.currentData() or QSettings().value(self.SUICIDE_KEY, "")
        players = sorted(
            season.players.values(),
            key=lambda p: (not p.suicide_alive, p.display.casefold()),
        )
        self.coach_picker.blockSignals(True)
        self.coach_picker.clear()
        for p in players:
            self.coach_picker.addItem(p.display + ("" if p.suicide_alive else "  (out)"), p.key)
        found = self.coach_picker.findData(wanted) if wanted else -1
        self.coach_picker.setCurrentIndex(max(found, 0))
        self.coach_picker.blockSignals(False)
        self._render_suicide()

    def _render_suicide(self) -> None:
        season, week = self.season, self._suicide_week
        key = self.coach_picker.currentData()
        self.clear_layout(self.suicide_box)
        if season is None or not key or not week:
            self.suicide_advice.setText("")
            self.suicide_note.setText("")
            return
        QSettings().setValue(self.SUICIDE_KEY, key)
        advice = survivor.advise(season, key, week)
        if advice is None:
            self.suicide_advice.setText("No suicide picks recorded for this coach.")
            return
        used = ", ".join(f"{team} (wk {w})" for w, team in advice.used) or "none yet"
        if advice.pick is not None:
            where = "vs" if advice.pick.home else "at"
            headline = (
                f"<b>Week {week}: take {advice.pick.team}</b> {where} "
                f"{advice.pick.opponent}"
                + (f" ({advice.pick.line}{'?' if advice.pick.line_assumed else ''})" if advice.pick.line else "")
                + f" - {advice.pick.chance:.0%} to survive. "
                f"{advice.reason}"
            )
        else:
            headline = advice.reason or "No team left to pick this week."
        self.suicide_advice.setText(f"{headline}<br><span>Used so far: {used}.</span>")

        rows, tones = [], {}
        for r, o in enumerate(advice.options[: self.SUICIDE_SHOWN]):
            note = ("\u2190 pick" if advice.pick is not None and o.code == advice.pick.code
                    else "worth saving" if o.save else "")
            rows.append([
                o.team,
                ("vs " if o.home else "at ") + o.opponent
                + (f"  \u00b7  {o.line}{'?' if o.line_assumed else ''}" if o.line else ""),
                f"{o.chance:.0%}" + ("" if o.from_market else " est."),
                o.later_text,
                o.strong_spots,
                note,
            ])
            if note.endswith("pick"):
                tones[(r, 0)] = tones[(r, 5)] = "good"
            elif o.save:
                tones[(r, 5)] = "warning"
        if rows:
            model = TableModel(
                ["Team", "Game", "This week", "Best later week", "Strong weeks left", ""],
                rows, palette=self.palette, numeric_columns={2, 4}, tones=tones,
                bold_columns={0},
            )
            view, _ = make_table(model, stretch_column=3, row_height=28)
            self.suicide_box.addWidget(view)
        self.suicide_note.setText(
            f"Teams already used are left out. 'Strong' is a later week at "
            f"{survivor.STRONG:.0%} or better; later weeks are estimated from the "
            f"{advice.rated_from} betting lines seen so far this season, so they "
            f"sharpen as the season goes. 'est.' means this week's line isn't in yet. "
            f"The pool's lines apply: a lined favourite must win by more than "
            f"the line and an underdog survives by covering, so big favourites "
            f"are close to coin flips. A line with '?' is a guess - the pool "
            f"hasn't posted it."
        )

    @staticmethod
    def _week(season: Season) -> int:
        from ... import analytics
        return analytics.upcoming_week(season)

    def _show_empty(self, week: int) -> None:
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "Nothing priced yet")
        for box, message in (
            (self.swing_box, "The swings appear once the week is priced."),
            (self.card_box,
             f"Week {week} has no prices yet. Open the Every game tab, load the "
             f"predictions file or type the spreads, and the card appears here."),
            (self.side_box, ""),
        ):
            self.clear_layout(box)
            if message:
                note = QLabel(message)
                note.setObjectName("Muted")
                note.setWordWrap(True)
                box.addWidget(note)
        self.table = None

    def _update_tiles(self, brief: briefing.Brief) -> None:
        self.tile_expected.update_values(
            f"{brief.expected:.1f}",
            f"of {_plural(len(brief.choices), 'game')} priced\n"
            f"{len(brief.strong)} strong, {len(brief.flips)} coin "
            f"{'flip' if len(brief.flips) == 1 else 'flips'}",
            "good" if brief.expected >= len(brief.choices) * 0.6 else "",
        )
        self.tile_expected.show_bar(
            brief.expected / max(1, len(brief.choices)), None, "good", self.palette
        )

        swings = brief.swings
        if swings:
            best = swings[0]
            self.tile_swing.update_values(
                best.pick,
                f"{best.leverage:+.0%} on the average card\n{best.matchup}",
                "good",
            )
        else:
            self.tile_swing.update_values(
                self.NO_VALUE,
                "no pick gains much on the field this week - "
                "the card is the card",
            )

        plan = brief.plan
        if plan is not None:
            odds_now = brief.win_odds or 0.0
            other = (
                f"built to win the week: {plan.win_odds:.1%}" if brief.straight
                else f"the likeliest side of every game: {plan.plain_win_odds:.1%}"
            )
            self.tile_pays.update_values(
                f"{odds_now:.1%}",
                f"first of {plan.coaches + 1} \u00b7 a fair share is "
                f"{plan.fair_share:.1%}\n{other}",
                "good" if odds_now > plan.fair_share else "",
            )
            self.tile_pays.show_bar(
                # Half-way along is a fair share of the week; past it, better.
                min(1.0, odds_now / plan.fair_share / 2 if plan.fair_share else 0.0), 0.5,
                "good" if odds_now > plan.fair_share else "", self.palette,
            )
        else:
            self.tile_pays.update_values(
                self.NO_VALUE, "needs most of the week priced"
            )
            self.tile_pays.hide_bar()

        flips = brief.flips
        self.tile_flips.update_values(
            str(len(flips)),
            ", ".join(c.matchup for c in flips[:2]) + ("…" if len(flips) > 2 else "")
            if flips else "every game has a side worth taking",
            "warning" if len(flips) >= 4 else "",
        )

    def _update_swings(self, brief: briefing.Brief) -> None:
        self.clear_layout(self.swing_box)
        swings = brief.swings
        counted = (
            "counted from the pool's own sheet" if brief.counted_crowd
            else "estimated from how the pool usually picks"
        )
        if not swings:
            self.swing_card.set_title(SWING_TITLE)
            note = QLabel(
                "No pick on this card gains much on the field. Every game the "
                "pool is likely to see the same way, so the week will be "
                "decided by the games everyone gets wrong rather than by "
                "anything chosen here."
            )
            note.setObjectName("Muted")
            note.setWordWrap(True)
            self.swing_box.addWidget(note)
            return

        self.swing_card.set_title(
            f"{SWING_TITLE} - {_plural(len(swings), 'pick')}, {counted}"
        )
        for choice in swings:
            line = QLabel(
                f"<b>{choice.pick}</b> ({choice.matchup}) - {choice.chance:.0%} to "
                f"land, and only {choice.crowd:.0%} of the pool is expected to be "
                f"on it. That is {choice.leverage:+.0%} on the average card"
                + (f", played against {choice.line}." if choice.line else ".")
            )
            line.setWordWrap(True)
            self.swing_box.addWidget(line)

    def _update_table(self, brief: briefing.Brief) -> None:
        rows, tones = [], {}
        for r, choice in enumerate(brief.choices):
            gain = choice.leverage
            rows.append([
                choice.index,
                choice.matchup,
                choice.pick + ("  \u21ba" if choice.turned else ""),
                f"{choice.chance:.0%}" + (
                    " · against the pool" if choice.turned
                    else " · coin flip" if choice.coin_flip else ""
                ),
                f"{gain:+.0%}" if gain is not None else self.NO_VALUE,
                self._flip_text(brief, choice),
                choice.line or self.NO_VALUE,
                choice.why,
            ])
            if gain is not None:
                tones[(r, COL_EDGE)] = (
                    "good" if gain >= briefing.SWING_LEVERAGE
                    else "bad" if gain <= -0.15 else "muted"
                )
            tones[(r, COL_CHANCE)] = (
                "warning" if choice.turned
                else "good" if choice.chance >= briefing.CONFIDENT
                else "muted" if choice.coin_flip else ""
            )
            if choice.turned:
                tones[(r, COL_TAKE)] = "warning"
            if choice.if_flipped is not None and brief.win_odds is not None:
                cost = brief.win_odds - choice.if_flipped
                tones[(r, COL_FLIP)] = (
                    "bad" if cost >= 0.005 else "muted" if abs(cost) < FLIP_NOISE else ""
                )

        model = TableModel(
            HEADERS, rows,
            palette=self.palette,
            numeric_columns={COL_NUM, COL_CHANCE, COL_EDGE, COL_FLIP},
            sort_values={
                COL_CHANCE: [c.chance for c in brief.choices],
                COL_FLIP: [
                    c.if_flipped if c.if_flipped is not None else 1.0 for c in brief.choices
                ],
                COL_EDGE: [
                    c.leverage if c.leverage is not None else -1 for c in brief.choices
                ],
            },
            tones=tones,
            bold_columns={COL_TAKE},
        )
        view, _ = make_table(model, stretch_column=COL_WHY, row_height=28)
        self.clear_layout(self.card_box)
        self.table = view
        self.card_box.addWidget(view)

        plan = brief.plan
        if plan is not None:
            turned = brief.turned
            if brief.straight:
                would = [brief.choices[i] for i in plan.flipped]
                text = (
                    f"This card takes the likelier side of every game: about "
                    f"{plan.plain_hits:.1f} right, which is what counts toward "
                    f"the season title, and first {plan.plain_win_odds:.1%} of "
                    f"the time."
                    + (
                        f" Built to win the week instead, it would take "
                        f"{', '.join(c.other for c in would)} against the pool and "
                        f"finish first {plan.win_odds:.1%} of the time, with about "
                        f"{plan.expected_hits:.1f} right."
                        if would else
                        " The card built to win the week is the same card this week."
                    )
                    + " Replayed over 2011-2025 the two won about as many weeks, "
                      "so it's your call."
                )
            elif turned:
                text = (
                    f"This card is built to finish <b>first</b>, not just near "
                    f"the top. \u21ba marks the "
                    f"{_plural(len(turned), 'game')} it takes against the pool "
                    f"({', '.join(c.pick for c in turned)}). Taking the likelier "
                    f"side everywhere gets about {plan.plain_hits:.1f} right and "
                    f"lands in the top five {plan.plain_top_five:.0%} of weeks - "
                    f"but it wins only {plan.plain_win_odds:.1%}, because most "
                    f"of the pool holds the same card and a good week is shared "
                    f"with them. This one expects {plan.expected_hits:.1f} right "
                    f"and makes the top five less often ({plan.top_five:.0%}), "
                    f"but finishes first {plan.win_odds:.1%} of the time"
                    + (
                        f" \u2013 {plan.win_odds / plan.plain_win_odds:.1f}\u00d7 as often."
                        if plan.plain_win_odds > 0 else "."
                    )
                )
            else:
                text = (
                    "No game is crowded enough this week to be worth turning "
                    "over: the likeliest side of every game is also the card "
                    f"most likely to finish first ({plan.win_odds:.1%})."
                )
            text += (
                f" <b>If flipped</b> is the chance of winning the week with "
                f"only that game taken the other way (now {brief.win_odds or 0.0:.1%}): "
                f"the lower it is, the more that pick matters."
            )
            text += (
                " Played against the pool's real cards."
                if plan.field_known else
                " Played against simulated cards drawn from how the pool "
                "usually picks; load this week's pick sheet to play against "
                "the real ones."
            )
            note = QLabel(text)
            note.setObjectName("Muted")
            note.setWordWrap(True)
            note.setTextFormat(Qt.TextFormat.RichText)
            self.card_box.addWidget(note)

    def _flip_text(self, brief: briefing.Brief, choice: briefing.Choice) -> str:
        if choice.if_flipped is None or brief.win_odds is None:
            return self.NO_VALUE
        if abs(brief.win_odds - choice.if_flipped) < FLIP_NOISE:
            return "about the same"
        return f"{choice.if_flipped:.1%}"

    # ---- lines ------------------------------------------------------------
    def _update_lines_status(self, week: int) -> None:
        found = odds.stored(week) if week else None
        note = self._update_note
        if found is None:
            self.lines_status.setText((note + "  " if note else "") + (
                "Lines: from the predictions file or typed spreads. "
                "\u21bb Update lines fetches the latest from the books."
                if odds.api_key() else
                "Lines: from the predictions file or typed spreads. Add a free "
                "Odds API key (\u2699) and \u21bb Update lines fetches them for you."
            ))
            return
        moved = odds.movements(week)
        text = (note + "  " if note else "") + f"Lines updated {_when(found.at)}"
        left = odds.remaining()
        if left is not None:
            text += f" \u00b7 {left} requests left this month"
        if moved:
            text += " \u00b7 moved since opening: " + ", ".join(
                f"{odds.describe_margin(label, then)} \u2192 {odds.describe_margin(label, now)}"
                for label, then, now in moved[:4]
            ) + ("\u2026" if len(moved) > 4 else "")
        self.lines_status.setText(text)

    def _odds_settings(self, reason: str = "") -> bool:
        dialog = OddsDialog(reason, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        dialog.save()
        return bool(odds.api_key())

    def _update_lines(self) -> None:
        if self._fetcher is not None:
            return
        key = odds.api_key()
        if not key:
            if not self._odds_settings():
                return
            key = odds.api_key()
        self.lines_button.setEnabled(False)
        self.lines_button.setText("\u21bb  Updating\u2026")
        fetcher = _Fetcher(key)
        fetcher.done.connect(self._lines_fetched)
        # Only let go of the thread once it has really stopped.
        fetcher.finished.connect(lambda f=fetcher: self._release_fetcher(f))
        self._fetcher = fetcher
        fetcher.start()

    def _release_fetcher(self, fetcher) -> None:
        if self._fetcher is fetcher:
            self._fetcher = None
        fetcher.deleteLater()

    def _lines_fetched(self, result: object) -> None:
        self.lines_button.setEnabled(True)
        self.lines_button.setText("\u21bb  Update lines")
        if isinstance(result, str):
            self.lines_status.setText(f"Lines not updated. {result}")
            if "key" in result:
                self._odds_settings(result)
            return
        quotes, left = result
        week = self._week_shown
        season = self.season
        if not week or season is None:
            return
        # What the card was just before, so the change panel has something
        # to compare with even if no card was saved.
        cards.remember_before_update(week, self._brief)
        update = odds.update(week, quotes, odds.week_pairs(season, week), left)
        self._update_note = update.summary()
        # This page at once; every other page reads lines too, so the whole
        # window re-reads after.
        self.refresh_now()
        self.refresh_requested.emit()

    # ---- did anything change ---------------------------------------------
    def _save_card(self) -> None:
        if self._brief is None or not self._brief.choices:
            return
        snap = cards.save_mine(self._week_shown, self._brief)
        self.save_button.setText("\N{PUSHPIN}  Saved")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.save_button.setText("\N{PUSHPIN}  Save card"))
        self._update_changes(self._week_shown, self._brief)
        self.lines_status.setText(
            f"Card saved {_when(snap.at)}. Update the lines before the lock and "
            f"anything worth changing shows up above the card."
        )

    def _update_changes(self, week: int, brief: briefing.Brief) -> None:
        self.clear_layout(self.changes_box)
        found = cards.changes(week, brief)
        if found is None:
            self.changes_card.hide()
            return
        self.changes_card.show()
        self.changes_card.set_title(
            f"{CHANGES_TITLE} - since {found.what}, {_when(found.since.at)}"
        )
        lines = []
        if found.win_odds_then is not None and found.win_odds_now is not None:
            lines.append(
                f"Chance to win the week: {found.win_odds_then:.1%} \u2192 "
                f"<b>{found.win_odds_now:.1%}</b>"
            )
        for change in found.items:
            lines.append(("<b>" + change.text + "</b>") if change.kind == "swap" else change.text)
        if not found.items:
            lines.append(
                "Nothing worth changing: every pick is still the card's side, "
                "and none has moved 5 points."
            )
        for text in lines:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            self.changes_box.addWidget(label)
        if found.swaps and found.what == "the card you saved":
            note = QLabel(
                "Changed your card? Press \N{PUSHPIN} Save card again so the "
                "next check starts from it."
            )
            note.setObjectName("Muted")
            note.setWordWrap(True)
            self.changes_box.addWidget(note)

    def _update_side(self, brief: briefing.Brief) -> None:
        self.clear_layout(self.side_box)
        parts = []
        if brief.losers:
            parts.append(
                "<b>Big Losers</b> · " + " · ".join(
                    f"{display_team(loser.team)} vs {display_team(loser.opponent)} ({loser.chance:.0%})"
                    for loser in brief.losers
                )
            )
        if brief.suicide_note:
            parts.append(f"<b>Suicide pool</b> · {brief.suicide_note}")
        if not parts:
            parts.append("Nothing to say about the side pools this week.")
        for text in parts:
            line = QLabel(text)
            line.setWordWrap(True)
            self.side_box.addWidget(line)

    # ---- the whole thing as text ---------------------------------------
    def _copy(self) -> None:
        """Put the briefing on the clipboard, ready to paste into a message."""
        if self._brief is None:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._brief.as_text())
        self.copy_button.setText("Copied")
        self.copy_button.setEnabled(False)
        # Put the button back after a moment, so it can be used again.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, self._restore_copy)

    def _restore_copy(self) -> None:
        self.copy_button.setText("Copy as text")
        self.copy_button.setEnabled(self._brief is not None)
