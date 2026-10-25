"""Screener: every game of the week in one sortable grid (model/screener.py), and
why the chosen game's chance moved (model/changes.py)."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ...model import changes, screener
from ...places import SCREENER as title_
from ...version import MODEL_NAME
from ..widgets import Card, TableModel, make_table, section
from .base import Page

HEADERS = ["Game", "Card", MODEL_NAME, "Market", "Pool on it", "Pool line", "Pool v market",
           "Move to flip", "Big Loser", "Hard", "News"]
(C_GAME, C_PICK, C_CHANCE, C_MARKET, C_CROWD, C_LINE, C_GAP, C_FLIP, C_LOSER, C_HARD, C_NEWS) = range(11)


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def _pts(value: float | None) -> str:
    if value is None:
        return "–"
    pts = value * 100
    if abs(pts) < 0.05:
        return "0.0 pts"
    return f"{'+' if pts > 0 else '−'}{abs(pts):.1f} pts"


class AdvocateRun(QThread):
    """The devil's advocate brief (pool/advocate.py), off the window's thread."""

    done = Signal(str, bool)

    def __init__(self, season, week: int) -> None:
        super().__init__()
        self.season, self.week = season, week

    def run(self) -> None:
        from ...pool import advocate
        try:
            text, _facts = advocate.write(self.season, self.week)
            self.done.emit(text, True)
        except advocate.AdvocateError as exc:
            self.done.emit(str(exc), False)
        except Exception as exc:  # noqa: BLE001 - shown, never a crash
            self.done.emit(f"The brief couldn't be written ({exc}).", False)


class ScreenerPage(Page):
    title = title_
    subtitle = ("Every game of the week in one grid - sort any column, or filter to the games that need "
                "a look. Choose a game to see why its chance has moved.")
    icon = "\N{CHART WITH UPWARDS TREND}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show"))
        self.filter = QComboBox()
        for key, (label, _test) in screener.FILTERS.items():
            self.filter.addItem(label, key)
        self.filter.currentIndexChanged.connect(lambda _i: self.refresh_now())
        bar.addWidget(self.filter)
        bar.addStretch(1)
        self.layout_.addLayout(bar)

        self.grid_card = Card("The slate")
        self.grid_box = QVBoxLayout()
        self.grid_card.body().addLayout(self.grid_box)
        self.grid_note = self._note()
        self.grid_card.add(self.grid_note)
        self.layout_.addWidget(self.grid_card)

        self.move_card = Card("What moved it")
        head = QHBoxLayout()
        head.addWidget(QLabel("Compared with"))
        self.since = QComboBox()
        self.since.currentIndexChanged.connect(lambda _i: self._show_move())
        head.addWidget(self.since)
        head.addStretch(1)
        self.move_card.body().addLayout(head)
        self.move_box = QVBoxLayout()
        self.move_card.body().addLayout(self.move_box)
        self.move_note = self._note()
        self.move_card.add(self.move_note)
        self.layout_.addWidget(self.move_card)

        self.devil_card = Card("Devil's advocate")
        self.devil_btn = QPushButton("Argue against the shakiest picks")
        self.devil_btn.setToolTip("Claude makes the best case against the card's three most fragile picks, from "
                                  "the numbers on this page only; every number is checked. A few cents.")
        self.devil_btn.clicked.connect(self._advocate)
        self.devil_card.add(self.devil_btn)
        self.devil_text = QLabel("")
        self.devil_text.setWordWrap(True)
        self.devil_card.add(self.devil_text)
        self.layout_.addWidget(self.devil_card)
        self._devil: AdvocateRun | None = None

        self._rows: list[screener.Row] = []
        self._shown: list[screener.Row] = []
        self._chosen: int | None = None
        self._week = 0

    @staticmethod
    def _note() -> QLabel:
        label = QLabel("")
        label.setObjectName("Muted")
        label.setWordWrap(True)
        return label

    def restyle(self) -> None:
        self.refresh_now()

    def refresh(self) -> None:
        season = self.season
        assert season is not None
        found = screener.build(season)
        self._week = found.week
        self._rows = found.rows
        key = self.filter.currentData() or "all"
        self._shown = screener.filtered(found, key)
        self.clear_layout(self.grid_box)
        if not found.rows:
            self.grid_card.set_title("The slate")
            self.grid_note.setText("Nothing to screen yet: the week needs betting lines (Update lines on My picks).")
            self._fill_moments()
            self._show_move()
            return
        self.grid_card.set_title(f"Week {found.week} - {len(self._shown)} of {len(found.rows)} games")
        self._table(found)
        self._fill_moments()
        if self._chosen is None or all(r.index != self._chosen for r in self._rows):
            self._chosen = self._rows[0].index
        self._show_move()

    # ---- the grid ----------------------------------------------------------------------------
    def _table(self, found: screener.Screen) -> None:
        rows, tones, tips = [], {}, {}
        for i, r in enumerate(self._shown):
            news = "; ".join(x for x in (r.weather, r.injuries) if x)
            rows.append([
                r.matchup, r.pick, _pct(r.chance), _pct(r.market),
                _pct(r.crowd) + ("" if r.counted or r.crowd is None else " est."),
                r.pool_line or "–",
                "–" if r.pool_gap is None else f"{r.pool_gap:+.1f}",
                "–" if r.flip is None else f"{r.flip:.1f} pts",
                f"{r.loser} {r.loser_chance:.0%}", f"{r.hard:.0f}",
                ("QB " if r.injuries else "") + ("Weather" if r.weather else ""),
            ])
            if r.chance < 0.55:
                tones[(i, C_CHANCE)] = "bad"
            if r.market is not None and r.market < 0.5:
                tones[(i, C_MARKET)] = "bad"
            if r.lean is not None and r.lean >= 0.15:
                tones[(i, C_CROWD)] = "bad"
            if r.pool_gap is not None and abs(r.pool_gap) >= 1.0:
                tones[(i, C_GAP)] = "good"
            if r.flip is not None and r.flip <= 1.5:
                tones[(i, C_FLIP)] = "bad"
            if r.loser_chance >= 0.2:
                tones[(i, C_LOSER)] = "good"
            if r.hard >= 65:
                tones[(i, C_HARD)] = "bad"
            tips[(i, C_MARKET)] = (f"The betting line's own chance for {r.pick}, under the pool's rules"
                                   + ("" if r.edge is None else f" ({_pts(r.edge)} from {MODEL_NAME})"))
            tips[(i, C_CROWD)] = ("Counted off this week's pick sheet" if r.counted else
                                  "Expected, from how this pool usually picks a game like it")
            tips[(i, C_GAP)] = "The market's number minus the pool's line, for the pool's favourite. " \
                               "+ means the favourite is better than the pool's line asks."
            tips[(i, C_FLIP)] = "How far the market would have to move for the card to take the other side"
            tips[(i, C_HARD)] = "0-100, how hard the game is to call (Radar)"
            if news:
                tips[(i, C_NEWS)] = news
        model = TableModel(
            HEADERS, rows, palette=self.palette,
            numeric_columns={C_CHANCE, C_MARKET, C_CROWD, C_GAP, C_FLIP, C_HARD},
            sort_values={
                C_CHANCE: [r.chance for r in self._shown],
                C_MARKET: [-1 if r.market is None else r.market for r in self._shown],
                C_CROWD: [-1 if r.crowd is None else r.crowd for r in self._shown],
                C_GAP: [-99 if r.pool_gap is None else abs(r.pool_gap) for r in self._shown],
                C_FLIP: [99 if r.flip is None else r.flip for r in self._shown],
                C_LOSER: [r.loser_chance for r in self._shown],
                C_HARD: [r.hard for r in self._shown],
            },
            tones=tones, tooltips=tips, bold_columns={C_PICK},
        )
        view, proxy = make_table(model, stretch_column=C_GAME, row_height=28)
        shown = list(self._shown)

        def chosen(current, _previous) -> None:
            if not current.isValid():
                return
            row = proxy.mapToSource(current).row()
            if 0 <= row < len(shown):
                self._chosen = shown[row].index
                self._show_move()

        view.selectionModel().currentRowChanged.connect(chosen)
        self.grid_box.addWidget(view)
        self.grid_note.setText(
            f"{MODEL_NAME} is the card's chance of being credited; Market is the betting line's own chance "
            f"for the same side. Pool on it is counted off the pick sheet once it is in"
            + ("" if found.sheet else " (not yet: these are estimates)")
            + ". Red marks what deserves a second look; green marks a Big Loser worth a slot or a pool line "
              "the market disagrees with. Nothing here changes the card.")

    # ---- the devil's advocate ------------------------------------------------------------------
    def _advocate(self) -> None:
        if self.season is None or not self._week or self._devil is not None:
            return
        self.devil_btn.setEnabled(False)
        self.devil_text.setText("Writing… (about half a minute)")
        self._devil = AdvocateRun(self.season, self._week)
        self._devil.done.connect(self._advocated)
        self._devil.start()

    def _advocated(self, text: str, ok: bool) -> None:
        self.devil_text.setText(text if ok else f"Not written: {text}")
        self.devil_text.setObjectName("" if ok else "Muted")
        self.devil_btn.setEnabled(True)
        if self._devil is not None:
            self._devil.wait(100)
            self._devil.deleteLater()
        self._devil = None

    # ---- what moved -------------------------------------------------------------------------
    def _fill_moments(self) -> None:
        wanted = self.since.currentText()
        self.since.blockSignals(True)
        self.since.clear()
        for label, at in changes.moments(self._week) if self._week else []:
            self.since.addItem(label, at)
        at = self.since.findText(wanted)
        if at >= 0:
            self.since.setCurrentIndex(at)
        self.since.blockSignals(False)

    def _show_move(self) -> None:
        self.clear_layout(self.move_box)
        season = self.season
        since = self.since.currentData()
        if season is None or self._chosen is None or since is None:
            self.move_card.set_title("What moved it")
            self.move_note.setText("Once the card's chances have been kept for a while (once an hour while the "
                                   "week is open), this splits each move into the line's part and the rest.")
            return
        moves = {m.index: m for m in changes.explain(season, self._week, float(since))}
        m = moves.get(self._chosen)
        if m is None:
            self.move_note.setText("This game isn't priced, or has been played.")
            return
        self.move_card.set_title(f"What moved it - {m.matchup}, for {m.pick}")
        rows = [["Chance then", _pct(m.then)], ["Chance now", _pct(m.now)], ["Whole move", _pts(m.total)],
                ["From the line moving", _pts(m.line_part)], ["From everything else", _pts(m.rest_part)]]
        if m.line_then is not None and m.line_now is not None:
            rows.insert(3, ["Line (home side)", f"{m.line_then:+g} → {m.line_now:+g}"])
        model = TableModel(["Step", "Value"], rows, palette=self.palette, numeric_columns={1}, bold_columns={0})
        view, _ = make_table(model, stretch_column=0, row_height=26)
        self.move_box.addWidget(view)
        self.move_note.setText(
            "The line's part is today's price worked out again with the line as it stood then and everything "
            "else as it is now. Everything else is the rest of the move: a newer predictions file, the "
            "moneyline, the share of the models' opinion or a typed spread. After the deadline the week's "
            "numbers are locked, so nothing moves.")
