"""The slate radar: every game ahead by how it could go - upsets, close ones, routs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ...model import radar
from ...places import RADAR as title_
from ...version import MODEL_NAME
from ..widgets import Card, IconButton, StatTile, TableModel, make_table, section, tile_grid
from .base import Page

HEADERS = ["Game", "Betting line", "Card takes", "Credited", "Upset", "Within 3", "By 14+", "Hard to call"]
(COL_GAME, COL_LINE, COL_PICK, COL_CHANCE, COL_UPSET, COL_CLOSE, COL_ROUT, COL_HARD) = range(8)
TABLE_TITLE = "Every game, by how it could go"
#: "Hard to call" at or above this is worth a second look.
HARD = 55


def _line(shape: radar.Shape) -> str:
    """The betting line as it is written: "Buffalo −4.5", "pick'em"."""
    if shape.line is None:
        return "—"
    if abs(shape.line) < 0.25:
        return "pick'em"
    side = shape.favourite if shape.line > 0 else shape.underdog
    return f"{side} −{abs(shape.line):g}"


class RadarPage(Page):
    title = title_
    subtitle = "How each game could go - upsets, close ones and routs - and where to trust the card least. Double-click a game for its scouting report"
    icon = "\N{SATELLITE ANTENNA}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        self.tile_pulse = StatTile("Sunday Pulse")
        self.tile_hard = StatTile("Hardest To Call")
        self.tile_fear = StatTile(f"{MODEL_NAME}'s Biggest Fear")
        self.tile_upset = StatTile("Upset Watch")
        self.tile_rout = StatTile("Rout Watch")
        self.tile_edge = StatTile("Furthest From The Line")
        self._tiles = (self.tile_pulse, self.tile_hard, self.tile_fear, self.tile_upset, self.tile_rout,
                       self.tile_edge)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=3))

        self.table_card = Card(TABLE_TITLE)
        open_row = QHBoxLayout()
        self.scout_hint = QLabel("Double-click a game to open its scouting report: both teams, injuries, "
                                 "the projected score and what could make the pick wrong.")
        self.scout_hint.setObjectName("Muted")
        self.scout_hint.setWordWrap(True)
        self.scout_button = IconButton("Scouting report", "search")
        self.scout_button.setToolTip("Open the scouting report for the game selected in the table")
        self.scout_button.setEnabled(False)
        self.scout_button.clicked.connect(lambda: self._scout())
        open_row.addWidget(self.scout_hint, 1)
        open_row.addWidget(self.scout_button, 0)
        self.table_card.body().addLayout(open_row)
        self.table_box = QVBoxLayout()
        self.table_card.body().addLayout(self.table_box)
        self._shown: list[radar.Shape] = []
        self._view = None
        self.table_note = QLabel("")
        self.table_note.setObjectName("Muted")
        self.table_note.setWordWrap(True)
        self.table_card.add(self.table_note)
        self.layout_.addWidget(self.table_card)

        self.doubt_card = Card("Where the card could be wrong")
        self.doubt_label = QLabel("")
        self.doubt_label.setWordWrap(True)
        self.doubt_label.setTextFormat(Qt.TextFormat.RichText)
        self.doubt_card.add(self.doubt_label)
        self.layout_.addWidget(self.doubt_card)

    def restyle(self) -> None:
        self.refresh_now()

    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        slate = radar.build(season)
        self._update_tiles(slate)
        self._update_table(slate)
        self._update_doubts(slate)

    def _update_tiles(self, slate: radar.Slate) -> None:
        if not slate.games:
            for tile in self._tiles:
                tile.update_values(self.NO_VALUE, f"once week {slate.week} has betting lines")
            return
        real = sum(1 for g in slate.games if g.real_underdog)
        self.tile_pulse.update_values(
            f"{slate.pulse:.0f}",
            f"of 100 - {slate.mood.lower()}: how hard the week as a whole is to call\n"
            f"{slate.toss_ups} toss-up{'' if slate.toss_ups == 1 else 's'} \u00b7 {real} with a real underdog "
            f"\u00b7 {len(slate.games)} games priced",
            "warning" if slate.pulse >= 45 else "",
        )
        self._update_fear(slate)
        hardest = slate.hardest
        self.tile_hard.update_values(
            hardest.matchup,
            f"{hardest.hard:.0f} of 100 - the card takes {hardest.pick} at {hardest.chance:.0%}\n"
            f"decided by 3 or fewer {hardest.close:.0%} of the time",
            "warning" if hardest.hard >= HARD else "",
        )
        edge = slate.edge
        if edge is None:
            self.tile_edge.update_values("None", f"{MODEL_NAME} is within half a point of the betting line on every game")
        else:
            self.tile_edge.update_values(
                edge.favourite,
                f"{abs(edge.gap):g} point{'' if abs(edge.gap) == 1 else 's'} "
                f"{'better' if edge.gap > 0 else 'worse'} than the betting line has them\n{edge.matchup}",
            )
        upset = slate.upset
        if upset is None:
            self.tile_upset.update_values("None", "no underdog of three points or more on the slate")
        else:
            self.tile_upset.update_values(
                upset.underdog,
                f"{upset.upset:.0%} to win outright, getting {upset.line:g}\n{upset.matchup}",
                "warning" if upset.upset >= 0.35 else "",
            )
        rout = slate.rout
        self.tile_rout.update_values(
            rout.matchup,
            f"{rout.rout:.0%} to be decided by {radar.ROUT} or more\n{rout.favourite} favoured by {rout.margin:.1f}",
        )

    def _update_fear(self, slate: radar.Slate) -> None:
        """The situation its record is worst in, when this week's slate has games in it."""
        from ...model import autopsy
        try:
            found = autopsy.fear(autopsy.graded(self.season), {g.matchup: g.tags for g in slate.games})
        except Exception:  # noqa: BLE001 - the radar stands without it
            found = None
        if found is None:
            self.tile_fear.update_values("Nothing yet", f"no kind of game where {MODEL_NAME} has fallen clearly "
                                                         f"short of its own chances")
            return
        row, games = found.row, found.games
        shown = ", ".join(games[:2]) + (f" and {len(games) - 2} more" if len(games) > 2 else "")
        self.tile_fear.update_values(
            row.name,
            f"{row.right} of {row.picks} so far, where its chances said {row.expected:.1f}"
            + (" - too few to be sure" if not row.enough else "") + f"\nthis week: {shown}",
            "bad" if row.enough else "warning",
        )
        self.tile_fear.setToolTip("This week's games of that kind: " + "; ".join(games))

    def _update_table(self, slate: radar.Slate) -> None:
        self.clear_layout(self.table_box)
        self._shown, self._view = [], None
        self.scout_button.setEnabled(False)
        if not slate.games:
            self.table_card.set_title(TABLE_TITLE)
            self.table_note.setText(f"Appears once week {slate.week} has betting lines - Update lines on Your card fetches them.")
            return
        games = sorted(slate.games, key=lambda g: -g.hard)
        rows, tones, tips = [], {}, {}
        for r, g in enumerate(games):
            rows.append([g.matchup, _line(g), g.pick, f"{g.chance:.0%}", f"{g.upset:.0%}", f"{g.close:.0%}",
                         f"{g.rout:.0%}", f"{g.hard:.0f}"])
            tones[(r, COL_CHANCE)] = "good" if g.chance >= 0.65 else "warning" if g.chance < 0.55 else ""
            tones[(r, COL_HARD)] = "warning" if g.hard >= HARD else "muted" if g.hard < 35 else ""
            tips[(r, COL_UPSET)] = f"{g.underdog} winning the game outright"
            tips[(r, COL_CHANCE)] = f"{g.pick} being credited under the pool's rules"
            if g.flags:
                tips[(r, COL_HARD)] = "; ".join(g.flags)
        model = TableModel(
            HEADERS, rows, palette=self.palette,
            numeric_columns={COL_CHANCE, COL_UPSET, COL_CLOSE, COL_ROUT, COL_HARD},
            sort_values={COL_CHANCE: [g.chance for g in games], COL_UPSET: [g.upset for g in games],
                         COL_CLOSE: [g.close for g in games], COL_ROUT: [g.rout for g in games],
                         COL_HARD: [g.hard for g in games]},
            tones=tones, tooltips=tips, bold_columns={COL_PICK},
        )
        view, _ = make_table(model, stretch_column=COL_GAME, row_height=28)
        self.table_box.addWidget(view)
        self._shown, self._view = games, view
        view.doubleClicked.connect(lambda index: self._scout(index))
        view.selectionModel().selectionChanged.connect(
            lambda *_: self.scout_button.setEnabled(bool(view.selectionModel().selectedRows())))
        self.table_card.set_title(f"{TABLE_TITLE} - week {slate.week}, hardest to call first")
        self.table_note.setText(
            "These are the card's own numbers, read another way. Credited is the chance the card's side "
            "gets the pool's point. Upset is the underdog winning the game. Hard to call (0 to 100) shows "
            "where to trust a pick least; it doesn't predict anything."
        )

    def _scout(self, index=None) -> None:
        """Open the scouting report for a row (the one double-clicked, else the one selected)."""
        view = self._view
        if view is None:
            return
        if index is None:
            chosen = view.selectionModel().selectedRows()
            index = chosen[0] if chosen else None
        if index is None or self.season is None:
            return
        row = view.model().mapToSource(index).row()
        if not 0 <= row < len(self._shown):
            return
        from ...model import scouting
        from ..scouting import ScoutingDialog
        report = scouting.report(self.season, self._shown[row].index)
        if report is None:
            return
        dialog = ScoutingDialog(report, self.palette, self.window())
        dialog.exec()
        dialog.deleteLater()

    def _update_doubts(self, slate: radar.Slate) -> None:
        doubts = slate.doubts
        if not slate.games:
            self.doubt_label.setText("Nothing to weigh until the week has lines.")
        elif not doubts:
            self.doubt_label.setText("Nothing stands out: no toss-ups, no split among the models, no weather, no line still to come.")
        else:
            self.doubt_label.setText("<br>".join(
                f"<b>{game}</b>:{rest}" for game, _, rest in (d.partition(":") for d in doubts)))
