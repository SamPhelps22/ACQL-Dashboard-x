"""One week at a time: the slate, who won it, and which games were traps."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import mailer, picks
from ...predictions import display_team
from ...models import Season, Week
from ..charts import BarChart, HistogramChart
from .. import recap
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from .base import Page

SLATE_HEADERS = [
    "#", "Matchup", "Pool line", "Result", "Pool took", "Got it right", "Hit rate",
]
SLATE_LINE, SLATE_RESULT, SLATE_TOOK, SLATE_RIGHT, SLATE_RATE = 2, 3, 4, 5, 6
BOARD_HEADERS = ["#", "Player", "Total", "Regular", "Big Loser", "Suicide pick"]
TRAP_COUNT = 10
EASY_RATE = 0.75      # most of the pool got it - not a trap
TRAP_RATE = 0.30      # most of the pool missed it


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class WeeklyPage(Page):
    title = "Weekly"
    subtitle = "The slate, the scoreboard and the trap games"
    icon = "\N{SPIRAL CALENDAR PAD}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.slate_table: QWidget | None = None
        self.board_table: QWidget | None = None
        self._weeks: list[int] = []

        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Week"))
        self.prev_btn = self._step_button("‹", "Previous week (Alt+Left)")
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(180)
        self.next_btn = self._step_button("›", "Next week (Alt+Right)")
        for widget in (self.prev_btn, self.week_picker, self.next_btn):
            controls.addWidget(widget)
        controls.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        controls.addWidget(self.status)
        self.share_btn = QPushButton("\N{CAMERA}  Share recap")
        self.share_btn.setObjectName("Primary")
        self.share_btn.setToolTip(
            "Make a picture of this week - winner, standings, awards and the "
            "games that sank the pool - and copy it, ready to paste into the "
            "group chat. A copy is saved in the data folder too."
        )
        self.share_btn.clicked.connect(self._share)
        controls.addWidget(self.share_btn)
        self.email_btn = QPushButton("\N{ENVELOPE}  Email recap")
        self.email_btn.setToolTip(
            "Email this week's recap picture from your Gmail. The first time, "
            "it asks where to send it and for a Gmail app password."
        )
        self.email_btn.clicked.connect(self._email)
        controls.addWidget(self.email_btn)
        self.email_settings_btn = QPushButton("\N{GEAR}")
        self.email_settings_btn.setToolTip("Email settings - who it goes to, and the Gmail it sends from")
        self.email_settings_btn.setFixedWidth(40)
        self.email_settings_btn.clicked.connect(lambda: self._email_settings())
        controls.addWidget(self.email_settings_btn)
        self._sender: _Sender | None = None
        self.layout_.addLayout(controls)

        self.share_note = QLabel("")
        self.share_note.setObjectName("Muted")
        self.share_note.setWordWrap(True)
        self.share_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.share_note.hide()
        self.layout_.addWidget(self.share_note)

        self.week_picker.currentIndexChanged.connect(lambda _: self._render())
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn.clicked.connect(lambda: self._step(1))
        for keys, delta in (("Alt+Left", -1), ("Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda d=delta: self._step(d))

        self.tile_winner = StatTile("Week Winner")
        self.tile_high = StatTile("High Score")
        self.tile_avg = StatTile("Week Average")
        self.tile_low = StatTile("Low Score")
        self._tiles = (self.tile_winner, self.tile_high, self.tile_avg, self.tile_low)
        # Wrapped rather than squeezed: 4 to a row keeps every tile
        # wide enough for its own number on a laptop screen.
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        row = QHBoxLayout()
        row.setSpacing(12)
        self.slate_card = Card("The slate")
        self.slate_box = QVBoxLayout()
        self.slate_card.body().addLayout(self.slate_box)
        row.addWidget(self.slate_card, 3, Qt.AlignmentFlag.AlignTop)

        self.trap_card = Card("Hardest games - fewest correct picks")
        self.trap_chart = BarChart(self.palette, height=4.4)
        self.trap_card.add(self.trap_chart, 1)
        row.addWidget(self.trap_card, 2, Qt.AlignmentFlag.AlignTop)
        self.layout_.addLayout(row)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.board_card = Card("Scoreboard")
        self.board_box = QVBoxLayout()
        self.board_card.body().addLayout(self.board_box)
        bottom.addWidget(self.board_card, 3, Qt.AlignmentFlag.AlignTop)

        # The tiles give the week's high, low and average; this shows the
        # shape between them - a tight pack or a runaway winner.
        self.spread_card = Card("How the week was scored")
        self.spread_chart = HistogramChart(self.palette, height=3.4)
        self.spread_card.add(self.spread_chart, 1)
        bottom.addWidget(self.spread_card, 2, Qt.AlignmentFlag.AlignTop)
        self.layout_.addLayout(bottom)

    @staticmethod
    def _step_button(text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setFixedWidth(38)
        button.setStyleSheet("padding: 6px 0;")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def restyle(self) -> None:
        self.trap_chart.set_palette(self.palette)
        self.spread_chart.set_palette(self.palette)
        self.refresh_now()

    # ---- week selection -------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        self._weeks = sorted(season.weeks)
        current = self.week_picker.currentData()
        self.week_picker.blockSignals(True)
        self.week_picker.clear()
        for week in self._weeks:
            if week in season.provisional_weeks:
                suffix = "  (in progress)"
            elif not season.weeks[week].scored:
                suffix = "  (not played)"
            else:
                suffix = ""
            self.week_picker.addItem(f"Week {week}{suffix}", week)
        if current in self._weeks:
            self.week_picker.setCurrentIndex(self._weeks.index(current))
        elif season.current_week in self._weeks:
            self.week_picker.setCurrentIndex(self._weeks.index(season.current_week))
        self.week_picker.blockSignals(False)
        self._render()

    def _step(self, delta: int) -> None:
        target = self.week_picker.currentIndex() + delta
        if 0 <= target < self.week_picker.count():
            self.week_picker.setCurrentIndex(target)

    # ---- render ---------------------------------------------------------
    def _render(self) -> None:
        self.share_note.hide()          # a note about another week is stale
        season = self.season
        if season is None:
            return
        if not self._weeks:
            self._show_empty("No week sheets found in the workbook.")
            return
        week = season.weeks.get(self.week_picker.currentData())
        if week is None:
            return

        self.prev_btn.setEnabled(self.week_picker.currentIndex() > 0)
        self.next_btn.setEnabled(
            self.week_picker.currentIndex() < self.week_picker.count() - 1
        )

        scores = self._scores(week)
        self._update_tiles(week, scores)

        entered = sum(1 for g in week.games if g.played)
        self.status.setText(
            f"{_plural(len(week.games), 'game')} · "
            f"{_plural(entered, 'result')} entered · "
            f"{_plural(len(week.lines), 'player')}"
        )

        self._render_slate(week)
        self._render_traps(week)
        self._render_board(week, scores)
        self._render_spread(scores)

    @staticmethod
    def _scores(week: Week) -> list[tuple[str, object]]:
        """Every line on a scored week, best first.

        A player who genuinely scored zero is part of the week. Filtering on
        `line.total_wins` dropped them from the scoreboard and, worse, out of
        the low-score and average tiles, which then described only the players
        who had put a number on the board.
        """
        if not week.scored:
            return []
        return sorted(
            week.lines.items(),
            key=lambda kv: (-kv[1].total_wins, kv[1].player.lower()),
        )

    # ---- sharing the week ------------------------------------------------
    def _make_recap(self):
        """(the recap, the saved picture) for the week on screen, or None."""
        season = self.season
        number = self.week_picker.currentData()
        made = recap.build(season, number) if season is not None and number else None
        if made is None:
            self.share_note.setText("This week has no scores yet, so there is nothing to share.")
            self.share_note.show()
            return None
        try:
            from ...config import DATA_DIR
            folder = DATA_DIR / "recaps"
        except Exception:  # noqa: BLE001 - fall back to the home folder
            from pathlib import Path
            folder = Path.home() / "ACQL recaps"
        return made, recap.render(made, recap.default_path(folder, made), self.palette)

    def _share(self) -> None:
        """Render this week's recap, save it, and put it on the clipboard."""
        found = self._make_recap()
        if found is None:
            return
        made, path = found
        clipboard = QGuiApplication.clipboard()
        copied = False
        if clipboard is not None:
            image = QImage(str(path))
            if not image.isNull():
                clipboard.setImage(image)
                copied = True
        self.share_note.setText(
            ("Copied - paste it straight into the group chat. " if copied else "")
            + f"Saved as {path}"
        )
        self.share_note.show()

    # ---- emailing it ------------------------------------------------------
    def _email_settings(self, reason: str = "") -> bool:
        """Ask who to send to and how; True if there is now enough to send."""
        dialog = EmailDialog(mailer.MailSettings.load(), reason, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        settings = dialog.result_settings()
        settings.save()
        return settings.ready

    def _email(self) -> None:
        if self._sender is not None:
            return                      # one send at a time
        settings = mailer.MailSettings.load()
        if not settings.ready and not self._email_settings():
            return
        settings = mailer.MailSettings.load()
        found = self._make_recap()
        if found is None:
            return
        made, path = found
        top3 = ", ".join(f"{s.name} {s.wins}" for s in made.standings[:3])
        summary = (
            f"Week {made.week}: {made.headline} "
            f"{'win' if len(made.winners) > 1 else 'wins'} with {made.score_line}.\n"
            f"Top of the standings: {top3}."
        )
        if made.killer:
            tied = f" (tied with {', '.join(made.killer_tied)})" if made.killer_tied else ""
            left = f"; {made.suicide_left} still alive" if made.suicide_left is not None else ""
            summary += (
                f"\nSuicide pool: {made.killer} knocked out {made.killed}{tied}{left}."
            )
        message = mailer.build_message(
            settings, path, f"{made.season_title} - week {made.week} recap", summary,
        )
        self.email_btn.setEnabled(False)
        self.email_btn.setText("\N{ENVELOPE}  Sending\N{HORIZONTAL ELLIPSIS}")
        sender = _Sender(settings, message)
        sender.done.connect(lambda error, to=settings.recipients: self._emailed(error, to))
        # The thread is only let go once it has really stopped: "done" arrives
        # while run() is still returning, and dropping the last reference then
        # would destroy a running QThread.
        sender.finished.connect(lambda s=sender: self._release(s))
        self._sender = sender
        sender.start()

    def _release(self, sender) -> None:
        if self._sender is sender:
            self._sender = None
        sender.deleteLater()

    def _emailed(self, error: str, recipients: list[str]) -> None:
        self.email_btn.setEnabled(True)
        self.email_btn.setText("\N{ENVELOPE}  Email recap")
        if error:
            self.share_note.setText(f"Not sent. {error}")
            self.share_note.show()
            if "app password" in error:
                self._email_settings(error)
            return
        self.share_note.setText(f"Emailed to {', '.join(recipients)}.")
        self.share_note.show()

    def _show_empty(self, message: str) -> None:
        self.status.setText(message)
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "No data")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.trap_chart.empty("No picks recorded for this week")
        self.spread_chart.empty("Not scored yet")
        for box, attr in ((self.slate_box, "slate_table"), (self.board_box, "board_table")):
            self.clear_layout(box)
            setattr(self, attr, None)

    def _update_tiles(self, week: Week, scores: list[tuple[str, object]]) -> None:
        season = self.season
        if not scores:
            for tile in self._tiles:
                tile.update_values(self.NO_VALUE, "Not scored yet")
            return

        values = [line.total_wins for _, line in scores]
        top, low = max(values), min(values)
        games = week.game_count or len(week.games) or 1

        winners = [
            (season.players[key].display if key in season.players else line.player)
            for key, line in scores if line.total_wins == top
        ]
        self.tile_winner.update_values(
            winners[0] if len(winners) == 1 else f"{len(winners)}-way tie",
            ", ".join(winners[:4]) + ("…" if len(winners) > 4 else ""),
            "good",
        )
        self.tile_high.update_values(
            str(top), f"of {_plural(games, 'game')}  ·  {self.pct(top / games, 0)}"
        )

        average = sum(values) / len(values)
        self.tile_avg.update_values(
            f"{average:.1f}",
            f"across {_plural(len(values), 'player')}  ·  "
            f"{self.pct(average / games, 0)}",
        )
        self.tile_low.update_values(
            str(low),
            f"{_plural(values.count(low), 'player')} on it"
            + (f"  ·  {top - low} behind the winner" if top != low else ""),
            "bad" if top != low else "",
        )

    # ---- the slate ------------------------------------------------------
    def _render_slate(self, week: Week) -> None:
        entrants = len(week.lines) or 1
        # Who the pool actually backed, when their pick sheet has been loaded.
        # Unlike the hit rate, this is known before the game is played.
        sheet = picks.load(week.number)
        rows, tones, rates, shares = [], {}, [], []
        for r, game in enumerate(week.games):
            correct = week.correct_count(game.index)
            rate = correct / entrants
            rates.append(rate)
            line = getattr(game, "line", None)
            took, share = self._pool_took(sheet, game)
            shares.append(share)
            rows.append([
                game.index,
                game.label,
                f"{display_team(game.line_favourite)} by {line:g}" if line is not None else self.NO_VALUE,
                display_team(game.winner) or self.NO_VALUE,
                took,
                correct,
                self.pct(rate) if game.played or correct else self.NO_VALUE,
            ])
            if not (game.played or correct):
                tones[(r, SLATE_RATE)] = "muted"
            elif rate >= EASY_RATE:
                tones[(r, SLATE_RATE)] = "good"
            elif rate <= TRAP_RATE:
                tones[(r, SLATE_RATE)] = "bad"
            else:
                tones[(r, SLATE_RATE)] = "muted"
            if not game.played:
                tones[(r, SLATE_RESULT)] = "muted"
            if line is None:
                tones[(r, SLATE_LINE)] = "muted"
            # A pool piled onto one side is where a week is won or lost, so
            # it is marked whichever way the game went.
            if share is not None and share >= 0.75:
                tones[(r, SLATE_TOOK)] = "warning"

        model = TableModel(
            SLATE_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, SLATE_RIGHT, SLATE_RATE},
            sort_values={SLATE_RATE: rates, SLATE_TOOK: shares},
            tones=tones,
            bold_columns={1},
        )
        view, _ = make_table(model, stretch_column=1, sort_column=0, row_height=27)
        self.clear_layout(self.slate_box)
        self.slate_table = view
        self.slate_box.addWidget(view)

    def _pool_took(self, sheet, game) -> tuple[str, float | None]:
        """(the side most of the pool backed and its share, that share).

        Straight from their own pick sheet, so it says what the pool did
        rather than what a curve says pools usually do.
        """
        if sheet is None:
            return self.NO_VALUE, None
        found = sheet.game_for(game.away, game.home)
        if found is None or not found.counted:
            return self.NO_VALUE, None
        best, share = "", 0.0
        for team in (game.home, game.away):
            value = found.share_on(team)
            if value is not None and value > share:
                best, share = team, value
        if not best:
            return self.NO_VALUE, None
        return f"{display_team(best)} {self.pct(share, 0)}", share

    def _render_traps(self, week: Week) -> None:
        entrants = len(week.lines) or 1
        scored = [
            (game, week.correct_count(game.index))
            for game in week.games
            if game.played or week.correct_count(game.index)
        ]
        if not scored:
            self.trap_chart.empty("No picks recorded for this week")
            self.trap_card.set_title("Hardest games - fewest correct picks")
            return
        # Slate order breaks ties, so two equally hard games keep a stable
        # order between refreshes instead of swapping around.
        scored.sort(key=lambda pair: (pair[1], pair[0].index))
        shown = scored[:TRAP_COUNT]
        self.trap_card.set_title(
            f"Hardest {len(shown)} games - fewest correct picks"
            if len(scored) > TRAP_COUNT
            else "Every game - fewest correct picks first"
        )
        # The hardest game takes the warm slot; the rest stay quiet, so colour
        # marks the trap rather than repeating the bar length.
        hardest = shown[0][1]
        colors = [
            self.palette.series_color(1) if count == hardest
            else self.palette.series_color(2)
            for _, count in shown
        ]
        self.trap_chart.plot(
            [game.label for game, _ in shown],
            [count for _, count in shown],
            xlabel=f"Players correct (of {entrants})",
            colors=colors,
            tooltips=[
                f"{game.label}\nWinner: {display_team(game.winner) or 'not entered'}\n"
                f"{count} of {entrants} correct ({self.pct(count / entrants, 0)})"
                for game, count in shown
            ],
        )

    # ---- the scoreboard --------------------------------------------------
    def _render_board(self, week: Week, scores: list[tuple[str, object]]) -> None:
        season = self.season
        if not scores:
            self.clear_layout(self.board_box)
            self.board_table = None
            note = QLabel("This week has not been scored yet.")
            note.setObjectName("Muted")
            self.board_box.addWidget(note)
            return

        top = scores[0][1].total_wins
        ranks = self._ranks([line.total_wins for _, line in scores])
        rows, tones = [], {}
        for r, ((key, line), rank) in enumerate(zip(scores, ranks)):
            player = season.players.get(key)
            rows.append([
                line.rank or rank,
                player.display if player else line.player,
                line.total_wins,
                line.regular_wins,
                line.big_loser_wins,
                display_team(line.suicide_pick) or self.NO_VALUE,
            ])
            if line.big_loser_wins:
                tones[(r, 4)] = "good"
            if line.total_wins == top:
                tones[(r, 2)] = "good"

        model = TableModel(
            BOARD_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 2, 3, 4},
            sort_values={
                0: [line.rank or rank for (_, line), rank in zip(scores, ranks)],
                2: [line.total_wins for _, line in scores],
                3: [line.regular_wins for _, line in scores],
                4: [line.big_loser_wins for _, line in scores],
            },
            tones=tones,
            bold_columns={1},
        )
        view, _ = make_table(
            model, stretch_column=1, sort_column=0, ascending=True, row_height=27
        )
        self.clear_layout(self.board_box)
        self.board_table = view
        self.board_box.addWidget(view)

    def _render_spread(self, scores: list[tuple[str, object]]) -> None:
        if not scores:
            self.spread_card.set_title("How the week was scored")
            self.spread_chart.empty("Not scored yet")
            return
        values = [line.total_wins for _, line in scores]
        self.spread_card.set_title(
            f"How the week was scored - {_plural(len(values), 'player')}, "
            f"{max(values) - min(values)}-win spread"
        )
        self.spread_chart.plot(values, xlabel="Wins this week")

    @staticmethod
    def _ranks(totals: list[int]) -> list[int]:
        """Competition ranking: players level on the week share a place."""
        ranks: list[int] = []
        rank, last = 0, None
        for i, total in enumerate(totals, start=1):
            if total != last:
                rank, last = i, total
            ranks.append(rank)
        return ranks


class _Sender(QThread):
    """Sends one email off the main thread; Gmail can take a few seconds."""

    done = Signal(str)      # "" when sent, otherwise the reason it wasn't

    def __init__(self, settings, message) -> None:
        super().__init__()
        self.settings = settings
        self.message = message

    def run(self) -> None:
        try:
            mailer.send(self.settings, self.message)
            self.done.emit("")
        except mailer.MailError as exc:
            self.done.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - shown to the person, never swallowed
            self.done.emit(f"Sending failed: {exc}")


class EmailDialog(QDialog):
    """Where the recap goes, and the Gmail it goes from. Asked for once."""

    def __init__(self, settings, reason: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Email the weekly recap")
        self.setMinimumWidth(520)
        self._settings = settings
        layout = QVBoxLayout(self)
        intro = QLabel(
            (f"<p style='color:#d03b3b'>{reason}</p>" if reason else "")
            + "The recap is sent from your own Gmail. Gmail needs an <b>app "
            "password</b> for this, not your normal one: turn on 2-Step "
            "Verification, then make one at "
            f"<a href='{mailer.APP_PASSWORD_PAGE}'>{mailer.APP_PASSWORD_PAGE}</a> "
            "(call it \u201cACQL Dashboard\u201d) and paste the 16 letters below. "
            "It is stored locked to your Windows account, and you can revoke it "
            "from the same page at any time."
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)

        form = QFormLayout()
        self.sender = QLineEdit(settings.sender)
        self.sender.setPlaceholderText("you@gmail.com")
        self.recipients = QLineEdit(", ".join(settings.recipients))
        self.recipients.setPlaceholderText("who gets it - separate several with commas")
        self.password = QLineEdit("")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(
            "saved - leave blank to keep it" if settings.sealed_password
            else "16-letter Gmail app password"
        )
        form.addRow("Send from (Gmail)", self.sender)
        form.addRow("Send to", self.recipients)
        form.addRow("App password", self.password)
        layout.addLayout(form)
        self.sender.textChanged.connect(self._default_recipient)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _default_recipient(self, text: str) -> None:
        # Most people start by sending it to themselves.
        if not self.recipients.text().strip() or self.recipients.text().strip() == self._last_sender:
            self.recipients.setText(text.strip())
        self._last_sender = text.strip()

    _last_sender = ""

    def result_settings(self):
        settings = self._settings
        settings.sender = self.sender.text().strip()
        settings.recipients = mailer.parse_recipients(self.recipients.text()) or (
            [settings.sender] if settings.sender else []
        )
        if self.password.text().strip():
            settings.set_password(self.password.text())
        return settings