"""Computer models: each published model on its own, and what the crowd of them is worth (computers.py does the sums)."""

from __future__ import annotations

import statistics

from PySide6.QtWidgets import QLabel, QVBoxLayout

from ...model import computers, longrecord
from ...places import COMPUTERS as title_
from ...version import MODEL_NAME
from ...wording import plural as _plural
from ..widgets import Card, StatTile, TableModel, fit_height, make_table, section, tile_grid
from .base import Page

SLATE, RESIDUAL, GROUPS, WAYS, BOARD, ALIKE, CHECKS = "slate", "residual", "groups", "ways", "board", "alike", "checks"
CARRY, YEARS, LONG = "carry", "years", "long"
HEADINGS = {
    SLATE: "This week, game by game",
    RESIDUAL: "Do the models know something the betting line doesn't?",
    GROUPS: "When the models agree, and when they don't",
    WAYS: "Ways to average the models",
    BOARD: "Model by model",
    ALIKE: "Look-alikes",
    CHECKS: "Checks",
    CARRY: "Does a good year carry over?",
    YEARS: "The betting line against the models, season by season",
    LONG: "The long record",
}
#: What a bet against the spread has to win to break even at the usual price.
BREAK_EVEN = 0.524
ROW_HEIGHT = 28
#: The widest a number column is let go, so a model's or a game's name is not cut short beside eight of them.
NUMBER_WIDTH = 96
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
        self._render_carry(report)
        self._render_years(report)
        self._render_long(report)

    # ---- drawing ---------------------------------------------------------------------------
    def _table(self, key: str, headers: list[str], rows: list[list[object]], note: str, *, title: str = "",
               stretch: int = 0, most: int = 20, cap: int | None = None, **options) -> None:
        card, box, label = self.cards[key]
        self.clear_layout(box)
        card.setVisible(True)
        card.set_title(title or HEADINGS[key])
        if rows:
            model = TableModel(headers, rows, palette=self.palette, bold_columns={0}, **options)
            sized = {"max_column_width": cap} if cap else {}
            view, _ = make_table(model, stretch_column=stretch, row_height=ROW_HEIGHT, fit_rows=None, **sized)
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
            SLATE, ["Game", "Line", "Middle", "Gap", "Spread", "Lowest", "Highest", "Models", "Result"],
            rows,
            "Every number is points for the home team, the second team named: +3 means the home team by 3. "
            "Line is the betting line and Middle is the models' middle. Gap is how far apart those two are. "
            "Spread is how far apart the models are from each other. A gap of 2 points or more is in yellow."
            if rows else
            "Shows up once a week's computer predictions have been read in.",
            title=f"{HEADINGS[SLATE]} - week {report.week}" if rows else "",
            cap=NUMBER_WIDTH, numeric_columns={1, 2, 3, 4, 5, 6, 7, 8}, tones=tones,
            sort_values={3: [abs(r.gap) if r.gap is not None else -1 for r in report.slate],
                         4: [r.apart if r.apart is not None else -1 for r in report.slate]},
        )

    def _render_residual(self, report: computers.Report) -> None:
        res = report.residual
        rows = []
        if res.slope is not None:
            needed = int(round(res.games * (2 * res.error / res.share) ** 2, -1)) if res.share > 0 else 0
            rows = [[
                "Models against the line", res.games, f"{res.slope:+.2f}",
                f"{res.low:+.2f} to {res.high:+.2f}", f"{res.share:.2f}",
                f"about {needed:,} games" if needed > res.games else "enough already",
            ]]
        self._table(
            RESIDUAL, ["Test", "Games", "Share seen", "Could really be", "Share in use", "Games needed"], rows,
            res.reading + (" 0 would mean the line already knows everything the models know. "
                           "1 would mean the models were right and the line was wrong. Games needed is roughly "
                           "how many it takes to tell the share in use from zero." if rows else "")
            + self._long_answer(report),
            numeric_columns={1, 2, 3, 4, 5},
        )

    @staticmethod
    def _long_answer(report: computers.Report) -> str:
        """The same question, asked of the season pages' far longer record."""
        nudged = report.record.nudged
        if nudged is None or not nudged[3] + nudged[4]:
            return ""
        won, lost = nudged[3], nudged[4]
        return (f" The long record further down has {won + lost:,} games on the same question: the line moved "
                f"toward the models was on the right side of the line {won / (won + lost):.1%} of the time.")

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
            picked = [w for w in ways if w.name in (computers.PROVEN, computers.WITHOUT_WEAKEST)]
            if picked and used is not None:
                better = [w for w in picked if w.miss < used.miss]
                note += (" \u201cProven half only\u201d and \u201cWithout the weakest quarter\u201d take the same "
                         "middle over a crowd chosen on the models' last three seasons, before this one began. "
                         + ("Neither has beaten the middle 60% of everyone so far." if not better else
                            f"{better[0].name} is ahead of the middle 60% of everyone so far, by "
                            f"{used.miss - better[0].miss:.2f} of a point."))
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
                _signed(report.form.get(s.code), 2),
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
                "extra weight yet. Line's miss is the betting line's average miss on the same games, and Vs "
                "line is how many points closer the model was. Closer counts the games it beat the line; "
                "Right side counts the games the result fell on its side of the line. "
                "Past form is how many points closer than the typical model it was over its last three "
                "seasons, before this one"
                + (f"; across {report.form_r[1]} models it has gone with this season's showing "
                   f"({report.form_r[0]:+.2f}, where 0 is not at all and 1 is exactly). " if report.form_r else ". ")
                +
                f"Grey rows have fewer than {computers.MIN_GAMES} games."
            )
        self._table(
            BOARD, ["Model", "Games", "Avg miss", "Line's miss", "Vs line", "Closer",
                    "Right side", "Winners", "Past form"], rows, note,
            title=f"{HEADINGS[BOARD]} - {_plural(len(board), 'model')}, weeks {report.weeks[0]} to {report.weeks[-1]}"
            if board else "",
            most=16, cap=NUMBER_WIDTH, numeric_columns={1, 2, 3, 4, 5, 6, 7, 8}, tones=tones,
            sort_values={1: [s.games for s in board], 2: [s.miss for s in board], 3: [s.line_miss for s in board],
                         4: [s.edge for s in board], 5: [s.closer / s.games for s in board],
                         6: [s.cover / s.cover_games if s.cover_games else 0 for s in board],
                         7: [s.winners / s.winner_games if s.winner_games else 0 for s in board],
                         8: [report.form.get(s.code, -99) for s in board]},
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

    # ---- the long record -------------------------------------------------------------------
    def _render_carry(self, report: computers.Report) -> None:
        rec, card = report.record, self.cards[CARRY][0]
        carry = rec.carry
        if not carry.pairs or carry.miss_r is None:
            card.setVisible(False)
            return
        rows = [
            ["The closest quarter of the models", f"{carry.top_was:.2f} pts closer than the typical model",
             f"{carry.top_next:.2f} pts closer"],
        ]
        if carry.cover_was is not None and carry.cover_next is not None:
            rows.append(["The best quarter against the spread", f"{carry.cover_was:.1%} right",
                         f"{carry.cover_next:.1%} right"])
        rows.append(["The single closest model", "the closest of all",
                     f"beat the typical model {carry.hot_beat_typical} of {carry.hot_seasons} times, "
                     f"the betting line {carry.hot_beat_line} of {carry.hot_seasons}"])
        note = (
            f"Every model was followed from each season into the next, {rec.first} to {rec.last} "
            f"({carry.pairs:,} times in all). Accuracy carries over: {carry.miss_r:.2f}, where 0 is not at all and "
            "1 is completely. A weak model stays weak, so leaving the weakest out is fair to test. "
        )
        if carry.cover_r is not None:
            note += (f"Records against the spread do not carry over ({carry.cover_r:+.2f}): a model that beat the "
                     "spread last year is no more likely to do it this year. ")
        note += "Nothing here picks out a model that beats the betting line."
        self._table(CARRY, ["What was followed", "In the season it was picked", "The season after"], rows, note,
                    title=f"{HEADINGS[CARRY]} - {rec.first} to {rec.last}", stretch=2)

    def _render_years(self, report: computers.Report) -> None:
        rec, card = report.record, self.cards[YEARS][0]
        if not rec.seasons:
            card.setVisible(False)
            return
        listed = sorted(rec.seasons, key=lambda s: -s.season)
        rows, tones = [], {}
        for i, s in enumerate(listed):
            rows.append([
                s.season, s.models,
                "–" if s.line is None else f"{s.line:.2f}",
                "–" if s.median is None else f"{s.median:.2f}",
                "–" if s.adjusted is None else f"{s.adjusted:.2f}",
                "–" if s.line is None else f"{s.ahead} of {s.models}",
                f"{s.best} ({s.best_miss:.2f})" if s.best_miss is not None else "–",
            ])
            for column, value in ((3, s.median), (4, s.adjusted)):
                if s.line is not None and value is not None and round(value, 2) != round(s.line, 2):
                    tones[(i, column)] = "good" if value < s.line else "bad"
        note = "Average miss in points, each full season. "
        crowd, nudged, lately = rec.crowd, rec.nudged, rec.nudged_lately
        if crowd is not None:
            note += (f"The models' middle was closer than the betting line in {crowd[0]} of {crowd[1]} seasons, and "
                     f"{abs(crowd[2]):.2f} points {'closer' if crowd[2] > 0 else 'further away'} on average. ")
        if nudged is not None:
            won, lost = nudged[3], nudged[4]
            note += (f"Line + models is the site's own version of what {MODEL_NAME} does: the line moved toward the "
                     f"models. It was closer than the line in {nudged[0]} of {nudged[1]} seasons, with no real "
                     f"difference in points ({nudged[2]:+.2f}). ")
            if won + lost:
                note += f"Its side of the line came in {won:,} times and lost {lost:,} ({won / (won + lost):.1%})"
                if lately is not None and lately[0] + lately[1]:
                    note += (f"; over the last {lately[2]} seasons, {lately[0]:,} and {lately[1]:,} "
                             f"({lately[0] / (lately[0] + lately[1]):.1%})")
                note += f". A bet needs {BREAK_EVEN:.1%} to break even. "
        ahead, of = rec.model_seasons
        if of:
            note += f"In all, {ahead:,} of {of:,} model-seasons ({ahead / of:.0%}) were closer than the line."
        self._table(
            YEARS, ["Season", "Models", "Betting line", "Models' middle", "Line + models", "Closer than the line",
                    "Closest model"], rows, note, stretch=6, most=12,
            numeric_columns={0, 1, 2, 3, 4, 5}, tones=tones,
            sort_values={5: [s.ahead for s in listed]},
        )

    def _render_long(self, report: computers.Report) -> None:
        rec, card = report.record, self.cards[LONG][0]
        careers = rec.careers
        if not careers:
            card.setVisible(False)
            return
        rows, tones = [], {}
        for i, c in enumerate(careers):
            rows.append([
                c.name, f"{c.seasons} ({c.first}-{str(c.last)[2:]})", f"{c.games:,}", f"{c.miss:.2f}",
                f"{c.line_miss:.2f}", f"{c.edge:+.2f}", f"{c.ahead} of {c.of}", f"{c.cover:.1%}",
                "yes" if c.current else "",
            ])
            if not c.current:
                for column in range(9):
                    tones[(i, column)] = "muted"
            else:
                tones[(i, 5)] = "good" if c.edge > 0 else "bad"
        ahead = sum(1 for c in careers if c.edge > 0)
        long_runs = [c for c in careers if c.ats_won + c.ats_lost >= 1500]
        best = max(long_runs, key=lambda c: c.cover, default=None)
        note = (
            f"Every model with {longrecord.MIN_SEASONS} or more full seasons. {ahead} of {len(careers)} "
            f"{'was' if ahead == 1 else 'were'} closer than the betting line over the whole of its record. "
            + (f"Against the spread the best long record is {best.name} at {best.cover:.1%}, and a bet needs "
               f"{BREAK_EVEN:.1%} to break even. " if best is not None else "")
            + "Vs line is points closer than the line (minus is further away). Vs spread is how often the "
            "result fell on its side of the line. Grey rows are no longer published."
        )
        self._table(
            LONG, ["Model", "Seasons", "Games", "Avg miss", "Line's miss", "Vs line", "Seasons ahead",
                   "Vs spread", "This year"], rows, note,
            title=f"{HEADINGS[LONG]} - {_plural(len(careers), 'model')}, {rec.first} to {rec.last}",
            most=14, cap=NUMBER_WIDTH + 24, numeric_columns={1, 2, 3, 4, 5, 6, 7}, tones=tones,
            sort_values={1: [c.seasons for c in careers], 2: [c.games for c in careers], 3: [c.miss for c in careers],
                         4: [c.line_miss for c in careers], 5: [c.edge for c in careers],
                         6: [c.ahead / c.of if c.of else 0 for c in careers], 7: [c.cover for c in careers],
                         8: [c.current for c in careers]},
        )
