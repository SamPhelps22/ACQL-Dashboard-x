"""Hits and misses: whether the confidence is earned, where the picks come good, and each miss."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout

from ... import autopsy
from ...places import HITS as title_
from ...version import MODEL_NAME
from ...wording import plural as _plural
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from .base import Page

TIER_HEADERS = ["Confidence", "Picks", "Right", "Rate", "Its chances said", "Reading"]
CUT_HEADERS = ["Compared by", "Its picks on", "Picks", "Right", "Rate", "Its chances said", "The line alone",
               "Avg miss", "Reading"]
SPOT_TITLE = "Blind spots - where it has fallen furthest short of its own chances"
MISS_HEADERS = ["Week", "Game", "Took", "Chance", "Expected", "Finished", "What kind of miss"]
TIER_TITLE = "Is the confidence earned?"
CUT_TITLE = "Where its picks come good"
MISS_TITLE = "Every miss, and what kind it was"
#: Games ahead of or behind the betting line before a row is coloured for it.
CLEAR = 3


def _reading_tone(row: autopsy.Row) -> str:
    return {"surer than it should be": "bad", "better than it said": "good",
            "too few to say": "muted"}.get(row.verdict, "")


class HitsMissesPage(Page):
    title = title_
    subtitle = f"Where {MODEL_NAME}'s picks come good, its blind spots, and what kind of miss each miss was"
    icon = "\N{DIRECT HIT}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        self.tile_record = StatTile("Record")
        self.tile_chances = StatTile("Against Its Own Chances")
        self.tile_error = StatTile("Margin Error")
        self.tile_shared = StatTile("Misses The Line Shared")
        self._tiles = (self.tile_record, self.tile_chances, self.tile_error, self.tile_shared)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.cards = {}
        self.spot_card = Card(SPOT_TITLE)
        self.spot_label = QLabel("")
        self.spot_label.setWordWrap(True)
        self.spot_label.setTextFormat(Qt.TextFormat.RichText)
        self.spot_card.add(self.spot_label)
        self.layout_.addWidget(self.spot_card)
        for key, heading in (("tiers", TIER_TITLE), ("cuts", CUT_TITLE), ("misses", MISS_TITLE)):
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
        rep = autopsy.report(season)
        self._update_tiles(rep)
        self._update_spots(rep)
        self._update_tiers(rep)
        self._update_cuts(rep)
        self._update_misses(rep)

    def _update_tiles(self, rep: autopsy.Report) -> None:
        o = rep.overall
        if not o.picks:
            for tile in self._tiles:
                tile.update_values(self.NO_VALUE, "Needs a graded week with betting lines")
            return
        hits, cold = rep.streaks
        self.tile_record.update_values(
            f"{o.right}–{o.picks - o.right}",
            f"{o.rate:.0%} of {_plural(o.picks, 'pick')} over {_plural(len(rep.weeks), 'week')}\n"
            f"longest runs: {hits} right, {cold} wrong",
            "good" if o.rate >= 0.6 else "",
        )
        ahead = o.right - o.expected
        self.tile_chances.update_values(
            f"{ahead:+.1f}",
            f"picks right against the {o.expected:.1f} its own chances called for\n"
            + ("running hot - part of that is luck" if o.off >= 1.0 else
               "running cold - part of that is luck" if o.off <= -1.0 else "about what it said it would get"),
            "good" if o.off >= 1.0 else "bad" if o.off <= -1.0 else "",
        )
        e = rep.error
        if e.games:
            self.tile_error.update_values(
                f"{e.deadeye:.1f} pts",
                f"its average miss on the final margin, {_plural(e.games, 'game')}\n"
                f"the betting line alone: {e.line:.1f}",
                "good" if e.deadeye < e.line - 0.15 else "bad" if e.deadeye > e.line + 0.15 else "",
            )
        else:
            self.tile_error.update_values(self.NO_VALUE, "needs final scores from the scoreboard")
        kinds = dict(rep.kinds())
        shared, total = kinds.get(autopsy.SHARED, 0), len(rep.misses)
        if total:
            self.tile_shared.update_values(
                f"{shared} of {total}",
                f"misses the betting line had the same side on\n"
                f"{_plural(kinds.get(autopsy.TOSS_UP, 0), 'toss-up')} · "
                f"{kinds.get(autopsy.AGAINST, 0)} against the line",
            )
        else:
            self.tile_shared.update_values("0", "no misses yet")

    def _update_spots(self, rep: autopsy.Report) -> None:
        if not rep.overall.picks:
            self.spot_label.setText("Appears once a week with betting lines has been graded.")
            return
        if not rep.blind_spots:
            self.spot_label.setText(
                f"None so far. No kind of game with {autopsy.WATCH} or more picks is clearly below what "
                f"{MODEL_NAME} expected.")
            return
        lines = []
        for row in rep.blind_spots:
            sure = ("a real gap - luck alone rarely does this" if row.enough and row.off <= -autopsy.OFF else
                    "worth watching, not yet proven" if row.enough else
                    f"only {row.picks} picks - too few to act on")
            miss = f", missing the final margin by {row.error:.1f} points on average" if row.scored else ""
            lines.append(f"<b>{row.name}</b>: {row.right} of {row.picks} right where its own chances said "
                         f"{row.expected:.1f}{miss}. <span style='color:{self.palette.ink_muted}'>{sure}.</span>")
        self.spot_label.setText(
            "<br>".join(lines) + f"<br><span style='color:{self.palette.ink_muted}'>A blind spot is a kind of "
            f"game where its picks keep coming in less often than it expected. Finished weeks are saved "
            f"and never rewritten.</span>")

    def _table(self, key: str, headers, rows, **options):
        card, box, note = self.cards[key]
        self.clear_layout(box)
        if rows:
            stretch = options.pop("stretch", None)
            model = TableModel(headers, rows, palette=self.palette, **options)
            view, _ = make_table(model, stretch_column=stretch, row_height=28)
            box.addWidget(view)
        return card, note

    def _update_tiers(self, rep: autopsy.Report) -> None:
        tiers = [t for t in rep.tiers if t.picks]
        rows, tones = [], {}
        for r, t in enumerate(tiers):
            rows.append([t.name, t.picks, t.right, f"{t.rate:.0%}", f"{t.expected_rate:.0%}", t.verdict])
            tones[(r, 5)] = _reading_tone(t)
        _card, note = self._table("tiers", TIER_HEADERS, rows, numeric_columns={1, 2, 3, 4}, tones=tones,
                                  bold_columns={0}, stretch=5)
        if not rows:
            note.setText("Appears once a week with betting lines has been graded.")
            return
        judged = [t for t in tiers if t.enough]
        off = [t for t in judged if t.verdict != "as good as it said"]
        now = ("no confidence level has enough picks to judge yet. " if not judged else
               "; ".join(f"{t.name.lower()} picks are {t.verdict}" for t in off) + ". " if off else
               f"every level with {autopsy.ENOUGH} picks or more is coming in as often as it said. ")
        note.setText(
            f"<b>Right now:</b> {now}"
            f"Surer picks should come in more often: Lock is 75% or better, Strong 65%, Lean 55%, "
            f"Coin flip anything under. A level is only judged once it has {autopsy.ENOUGH} picks."
        )

    def _update_cuts(self, rep: autopsy.Report) -> None:
        rows, tones = [], {}
        for group, cut in rep.situations:
            for i, row in enumerate(cut):
                r = len(rows)
                # Against the line on the same games - and a game or two either
                # way is nothing, so it is only coloured from CLEAR games apart.
                ahead = row.right - row.line_right if row.line_games == row.picks else 0
                reading = ("too few to say" if not row.enough else
                           "level with the line" if not ahead else
                           f"{abs(ahead)} {'ahead of' if ahead > 0 else 'behind'} the line")
                rows.append([
                    group if i == 0 else "", row.name, row.picks, row.right, f"{row.rate:.0%}",
                    f"{row.expected_rate:.0%}",
                    f"{row.line_right} of {row.line_games}" if row.line_games else self.NO_VALUE,
                    f"{row.error:.1f}" if row.scored else self.NO_VALUE,
                    reading,
                ])
                tones[(r, 8)] = ("muted" if not row.enough or abs(ahead) < CLEAR else
                                 "good" if ahead > 0 else "bad")
                tones[(r, 0)] = "muted"
        _card, note = self._table("cuts", CUT_HEADERS, rows, numeric_columns={2, 3, 4, 5, 7}, tones=tones,
                                  bold_columns={1}, stretch=1)
        if not rows:
            note.setText("Appears once a week with betting lines has been graded.")
            return
        every = [row for _group, cut in rep.situations for row in cut if row.enough and row.line_games == row.picks]
        best = max(every, key=lambda row: row.right - row.line_right, default=None)
        worst = min(every, key=lambda row: row.right - row.line_right, default=None)
        now = ("no kind of game has enough picks to read yet. " if best is None else
               f"against the betting line it does best on {best.name[0].lower() + best.name[1:]} "
               f"({best.right - best.line_right:+d}) and worst on {worst.name[0].lower() + worst.name[1:]} "
               f"({worst.right - worst.line_right:+d}) - a game or two either way is luck. ")
        note.setText(
            f"<b>Right now:</b> {now}"
            f"Each row is one kind of game. \u201cThe line alone\u201d is what the betting line scored "
            f"on the same games. \u201cAvg miss\u201d is points off the final margin. Rows with under "
            f"{autopsy.ENOUGH} picks are too few to judge."
        )

    def _update_misses(self, rep: autopsy.Report) -> None:
        rows, tones = [], {}
        tone_of = {autopsy.TOSS_UP: "muted", autopsy.SHARED: "", autopsy.COVER: "warning",
                   autopsy.AGAINST: "bad", autopsy.OWN: ""}
        for r, m in enumerate(rep.misses):
            g = m.game
            finished = autopsy.margin_text(g.actual) or self.NO_VALUE
            if g.pool_line is not None:
                finished += f" · pool line {g.pool_favourite} by {g.pool_line:g}"
            rows.append([g.week, g.matchup, g.pick, f"{g.chance:.0%}", autopsy.margin_text(g.margin), finished,
                         m.kind + (" · never close" if m.never_close else "")])
            tones[(r, 6)] = tone_of.get(m.kind, "")
        card, note = self._table("misses", MISS_HEADERS, rows, numeric_columns={0, 3}, tones=tones,
                                 bold_columns={2}, stretch=1,
                                 sort_values={3: [m.game.chance for m in rep.misses]})
        card.set_title(f"{MISS_TITLE} - {len(rep.misses)} miss{'' if len(rep.misses) == 1 else 'es'}, surest first"
                       if rep.misses else MISS_TITLE)
        if not rep.misses:
            note.setText("No misses to go through yet." if rep.overall.picks else
                         "Appears once a week with betting lines has been graded.")
            return
        counted = ", ".join(f"{n} {kind.lower()}" for kind, n in rep.kinds())
        explained = " ".join(f"<b>{kind}</b>: {autopsy.KINDS[kind]}." for kind, _n in rep.kinds())
        note.setText(
            f"<b>Right now:</b> {counted}. {explained} A label says what kind of miss it was, not what "
            f"caused it."
        )
