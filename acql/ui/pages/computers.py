"""Computer models: each published model on its own, and what the crowd of them is worth (computers.py does the sums)."""

from __future__ import annotations

import statistics

from PySide6.QtWidgets import QLabel, QVBoxLayout

from ... import computers
from ...places import COMPUTERS as title_
from ...version import MODEL_NAME
from ...wording import plural as _plural
from ..widgets import Card, StatTile, TableModel, fit_height, make_table, section, tile_grid
from .base import Page

SLATE, RESIDUAL, GROUPS, WAYS, BOARD, ALIKE, CHECKS = "slate", "residual", "groups", "ways", "board", "alike", "checks"
HEADINGS = {
    SLATE: "This week, game by game",
    RESIDUAL: "Do the models know something the betting line doesn't?",
    GROUPS: "When the models agree, and when they don't",
    WAYS: "Ways to average the models",
    BOARD: "Model by model",
    ALIKE: "Look-alikes",
    CHECKS: "Checks",
}
ROW_HEIGHT = 28
PAIRS_SHOWN = 12


def _signed(value: float | None, digits: int = 1) -> str:
    return "–" if value is None else f"{value:+.{digits}f}"


class ComputersPage(Page):
    title = title_
    subtitle = ("Each published computer model on its own: which are closest, which are copies of each other, "
                "and whether they know anything the betting line doesn't")
    icon = "\N{DESKTOP COMPUTER}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        self.tile_models = StatTile("Models This Week")
        self.tile_gap = StatTile("Furthest From The Line")
        self.tile_apart = StatTile("Most Disputed")
        self.tile_blend = StatTile("Blend Advantage")
        self._tiles = (self.tile_models, self.tile_gap, self.tile_apart, self.tile_blend)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))
        self.cards = {}
        for key, heading in HEADINGS.items():
            card = Card(heading)
            box = QVBoxLayout()
            card.body().addLayout(box)
            note = QLabel("")
            note.setObjectName("Muted")
            note.setWordWrap(True)
            card.add(note)
            self.layout_.addWidget(card)
            self.cards[key] = (card, box, note)

    def restyle(self) -> None:
        self.refresh_now()

    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        try:
            report = computers.build(season)
        except Exception:  # noqa: BLE001 - an empty page rather than no page
            report = computers.Report()
        self._render_tiles(report)
        self._render_slate(report)
        self._render_residual(report)
        self._render_groups(report)
        self._render_ways(report)
        self._render_board(report)
        self._render_alike(report)
        self._render_checks(report)

    # ---- drawing ---------------------------------------------------------------------------
    def _table(self, key: str, headers: list[str], rows: list[list[object]], note: str, *, title: str = "",
               stretch: int = 0, most: int = 20, **options) -> None:
        card, box, label = self.cards[key]
        self.clear_layout(box)
        card.setVisible(True)
        card.set_title(title or HEADINGS[key])
        if rows:
            model = TableModel(headers, rows, palette=self.palette, bold_columns={0}, **options)
            view, _ = make_table(model, stretch_column=stretch, row_height=ROW_HEIGHT, fit_rows=None)
            fit_height(view, len(rows), ROW_HEIGHT, most)
            box.addWidget(view)
        label.setText(note)

    def _render_tiles(self, report: computers.Report) -> None:
        slate = report.slate
        if not slate:
            for tile in self._tiles:
                tile.update_values(self.NO_VALUE, "once a week's computer predictions are in")
            return
        typical = int(statistics.median(len(r.opinions) for r in slate))
        named = int(statistics.median(len(r.named) for r in slate))
        self.tile_models.update_values(
            str(typical),
            f"priced a typical week {report.week} game\n"
            + (f"{named} of them kept by name" if named else "their names were not kept for this week"),
        )
        gaps = [r for r in slate if r.gap is not None]
        if gaps:
            far = max(gaps, key=lambda r: abs(r.gap))
            self.tile_gap.update_values(
                f"{abs(far.gap):.1f} pts",
                f"{far.matchup}\nmodels {_signed(far.middle)}, betting line {_signed(far.line)}",
            )
        else:
            self.tile_gap.update_values(self.NO_VALUE, "no betting line to measure against")
        spread = [r for r in slate if r.apart is not None]
        if spread:
            wild = max(spread, key=lambda r: r.apart)
            self.tile_apart.update_values(
                f"{wild.apart:.1f} pts",
                f"{wild.matchup}\nmodels ranged {_signed(wild.opinions[0])} to {_signed(wild.opinions[-1])}",
            )
        else:
            self.tile_apart.update_values(self.NO_VALUE, "")
        blend = report.blend
        if blend is None:
            self.tile_blend.update_values(self.NO_VALUE, "once games with the models' numbers are played")
        else:
            gain, games = blend
            self.tile_blend.update_values(
                f"{gain:+.2f} pts",
                f"{MODEL_NAME}'s number was {'closer to' if gain >= 0 else 'further from'} the final margin\n"
                f"than the betting line alone, over {_plural(games, 'game')}",
                "good" if gain > 0 else "bad" if gain < 0 else "",
            )

    def _render_slate(self, report: computers.Report) -> None:
        rows, tones = [], {}
        for i, r in enumerate(report.slate):
            rows.append([
                r.matchup, _signed(r.line), _signed(r.middle), _signed(r.gap),
                "–" if r.apart is None else f"{r.apart:.1f}",
                _signed(r.opinions[0]), _signed(r.opinions[-1]), len(r.opinions),
                "to play" if r.actual is None else _signed(r.actual, 0),
            ])
            if r.gap is not None and abs(r.gap) >= 2:
                tones[(i, 3)] = "warning"
            if r.actual is None:
                tones[(i, 8)] = "muted"
        self._table(
            SLATE, ["Game", "Betting line", "Models' middle", "Gap", "Spread", "Lowest", "Highest", "Models", "Result"],
            rows,
            "Every number is points for the home team, the second team named: +3 means the home team by 3. "
            "Gap is how far the models' middle sits from the betting line. Spread is how far apart the models are."
            if rows else
            "Shows up once a week's computer predictions have been read in.",
            title=f"{HEADINGS[SLATE]} - week {report.week}" if rows else "",
            numeric_columns={1, 2, 3, 4, 5, 6, 7, 8}, tones=tones,
            sort_values={3: [abs(r.gap) if r.gap is not None else -1 for r in report.slate],
                         4: [r.apart if r.apart is not None else -1 for r in report.slate]},
        )

    def _render_residual(self, report: computers.Report) -> None:
        res = report.residual
        rows = []
        if res.slope is not None:
            needed = int(round(res.games * (2 * res.error / res.share) ** 2, -1)) if res.share > 0 else 0
            rows = [[
                "The models' view of the line", res.games, f"{res.slope:+.2f}",
                f"{res.low:+.2f} to {res.high:+.2f}", f"{res.share:.2f}",
                f"about {needed:,} games" if needed > res.games else "enough already",
            ]]
        self._table(
            RESIDUAL, ["Test", "Games", "Share that showed up", "Could really be", "Share the picks use",
                       "Needed to tell them apart"], rows,
            res.reading + (" 0 would mean the line already knows everything the models know. "
                           "1 would mean the models were right and the line was wrong." if rows else ""),
            numeric_columns={1, 2, 3, 4, 5},
        )

    def _render_groups(self, report: computers.Report) -> None:
        card = self.cards[GROUPS][0]
        if not report.groups:
            card.setVisible(False)
            return
        rows = [[g.name, g.games, f"{g.apart:.1f}", f"{g.line_miss:.2f}", f"{g.middle_miss:.2f}"] for g in report.groups]
        harder = len(report.groups) == 2 and report.groups[1].line_miss > report.groups[0].line_miss
        self._table(
            GROUPS, ["Games where", "Games", "Models apart by", "Line's average miss", "Models' average miss"], rows,
            "The played games, split in half by how far apart the models were. "
            + ("So far the games they split on were harder to call." if harder else
               "So far the games they split on were no harder to call than the rest.")
            + f" {MODEL_NAME} trusts the models less on a game they are split on.",
            numeric_columns={1, 2, 3, 4},
        )

    def _render_ways(self, report: computers.Report) -> None:
        ways = report.ways
        rows, tones = [], {}
        for i, w in enumerate(ways):
            line = w.name == computers.LINE_ROW
            rows.append([
                w.name, w.games, f"{w.miss:.2f}",
                "–" if line else f"{w.closer} of {w.games}",
                "–" if line else f"{w.cover} of {w.cover_games}",
            ])
            if line:
                tones[(i, 0)] = "muted"
        note = "Shows up once games the models priced have been played."
        if ways:
            best, used = ways[0], next((w for w in ways if w.in_use), None)
            note = ("Each way boils the models down to one number for a game. Average miss is how many points that "
                    "number was from the final margin. ")
            if used is not None and best is not used:
                note += (f"{best.name} has been {used.miss - best.miss:.2f} of a point closer than the middle 60% "
                         f"the picks use, over {_plural(best.games, 'game')}. That is too small and too few to act on.")
            elif used is not None:
                note += f"The middle 60% the picks use has been the closest so far, over {_plural(used.games, 'game')}."
        self._table(WAYS, ["Way", "Games", "Average miss", "Closer than the line", "Right side of the line"], rows,
                    note, numeric_columns={1, 2, 3, 4}, tones=tones,
                    sort_values={2: [w.miss for w in ways]})

    def _render_board(self, report: computers.Report) -> None:
        board = report.board
        rows, tones = [], {}
        for i, s in enumerate(board):
            rows.append([
                computers.label(s.code), s.games, f"{s.miss:.2f}", f"{s.line_miss:.2f}", f"{s.edge:+.2f}",
                f"{s.closer} of {s.games}", f"{s.cover} of {s.cover_games}", f"{s.winners} of {s.winner_games}",
                f"{s.lean:+.1f}",
            ])
            if not s.ranked:
                for c in range(9):
                    tones[(i, c)] = "muted"
            else:
                tones[(i, 4)] = "good" if s.edge > 0 else "bad"
        ranked = [s for s in board if s.ranked]
        ahead = sum(1 for s in ranked if s.edge > 0)
        note = "Shows up once games the models priced by name have been played."
        if board:
            note = (
                f"{ahead} of {_plural(len(ranked), 'model')} with {computers.MIN_GAMES} or more games "
                f"{'was' if ahead == 1 else 'were'} closer to the results than the betting line on average. "
                f"Over only {_plural(report.named_graded, 'game')} that is mostly luck, so no model has earned "
                "extra weight yet. Line's miss is the betting line's average miss on the same games, and Against "
                "the line is how many points closer the model was. Closer counts the games it beat the line; "
                "Right side counts the games the result fell on its side of the line. "
                "Leans is its average error: plus means too kind to home teams. "
                f"Grey rows have fewer than {computers.MIN_GAMES} games."
            )
        self._table(
            BOARD, ["Model", "Games", "Average miss", "Line's miss", "Against the line", "Closer",
                    "Right side", "Winners", "Leans"], rows, note,
            title=f"{HEADINGS[BOARD]} - {_plural(len(board), 'model')}, weeks {report.weeks[0]} to {report.weeks[-1]}"
            if board else "",
            most=16, numeric_columns={1, 2, 3, 4, 5, 6, 7, 8}, tones=tones,
            sort_values={1: [s.games for s in board], 2: [s.miss for s in board], 3: [s.line_miss for s in board],
                         4: [s.edge for s in board], 5: [s.closer / s.games for s in board],
                         6: [s.cover / s.cover_games if s.cover_games else 0 for s in board],
                         7: [s.winners / s.winner_games if s.winner_games else 0 for s in board],
                         8: [s.lean for s in board]},
        )

    def _render_alike(self, report: computers.Report) -> None:
        alike = report.alike
        card = self.cards[ALIKE][0]
        if not alike.crowd and not alike.pairs:
            card.setVisible(False)
            return
        rows = [[computers.label(a), computers.label(b), f"{r:.2f}", games]
                for a, b, r, games in alike.pairs[:PAIRS_SHOWN]]
        note = ""
        if alike.effective is not None:
            note = (f"The {alike.crowd} models that priced nearly every game behave like about "
                    f"{alike.effective:.0f} independent opinions, not {alike.crowd}. ")
        note += ("Two models are alike when their views of the betting line rise and fall together. "
                 "1.00 means they always say the same thing. "
                 + (f"{_plural(len(alike.pairs), 'pair')} are at {computers.LOOK_ALIKE:.2f} or more"
                    + (f"; the closest {PAIRS_SHOWN} are shown." if len(alike.pairs) > PAIRS_SHOWN else ".")
                    if alike.pairs else "No two models are that close."))
        self._table(ALIKE, ["Model", "Moves with", "How alike", "Games"], rows, note, numeric_columns={2, 3})

    def _render_checks(self, report: computers.Report) -> None:
        card = self.cards[CHECKS][0]
        if not report.found:
            card.setVisible(False)
            return
        rows = [[computers.label(f.code), f.what, f.detail] for f in report.flags]
        tones = {(i, 1): "warning" for i in range(len(rows))}
        self._table(
            CHECKS, ["Column", "Looks like", "Why"], rows,
            "Every column in the file is counted as a model unless it is listed here. "
            + ("These are worth leaving out or turning round before they are averaged in." if rows else
               "Nothing odd found: no column runs backwards, copies the betting line or sits far from the rest."),
            stretch=2, tones=tones,
        )
