"""Everyone's picks: the whole pool's cards for one week, side by side."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout

from ...pool import everyone, me
from ...places import EVERYONE as title_
from ...version import MODEL_NAME
from ...wording import plural as _plural
from ..widgets import Card, StatTile, TableModel, fit_height, make_table, section, tile_grid
from .base import Page

BOARD_TITLE = "Every card"
GAMES_TITLE = "Game by game - how the pool split"
SIDES_TITLE = "Big Losers and suicide picks"
POOL_ROW = "Most cards"
NO_PICK = "·"
ROW_HEIGHT = 26


class EveryonePage(Page):
    title = title_
    subtitle = "Every coach's card for the week, side by side, and how the pool split on each game"
    icon = "\N{BUSTS IN SILHOUETTE}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Week"))
        self.week_picker = QComboBox()
        self.week_picker.setMinimumWidth(170)
        self.week_picker.currentIndexChanged.connect(lambda _: self._render())
        chooser.addWidget(self.week_picker)
        chooser.addStretch(1)
        self.layout_.addLayout(chooser)

        self.tile_cards = StatTile("Cards In")
        self.tile_agreed = StatTile("Most Agreed On")
        self.tile_split = StatTile("Most Split")
        self.tile_crowd = StatTile("You And The Crowd")
        self._tiles = (self.tile_cards, self.tile_agreed, self.tile_split, self.tile_crowd)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.cards = {}
        for key, heading in (("board", BOARD_TITLE), ("games", GAMES_TITLE), ("sides", SIDES_TITLE)):
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
        weeks = everyone.weeks(season)
        wanted = self.week_picker.currentData()
        self.week_picker.blockSignals(True)
        self.week_picker.clear()
        for number in reversed(weeks):
            self.week_picker.addItem(f"Week {number}" + ("  (latest)" if number == weeks[-1] else ""), number)
        found = self.week_picker.findData(wanted) if wanted else -1
        self.week_picker.setCurrentIndex(max(found, 0))
        self.week_picker.blockSignals(False)
        self._render()

    # ---- drawing ---------------------------------------------------------------------------
    def _render(self) -> None:
        season = self.season
        if season is None:
            return
        number = self.week_picker.currentData()
        board = everyone.build(season, number) if number else everyone.Board(0)
        mine = board.coach(me.key(season))
        model = self._model_card(season, board)
        self._render_tiles(season, board, mine)
        self._render_board(board, mine, model)
        self._render_games(board, mine, model)
        self._render_sides(board, mine)

    @staticmethod
    def _model_card(season, board: everyone.Board):
        """The model's own card for the week, as a row like anyone's - if one was kept."""
        try:
            from ...pool import cards
            week = season.weeks.get(board.week)
            snap = cards.model(board.week)
            if week is None or snap is None:
                return None
            snap = cards.aligned(snap, cards._slate(week.games))
            sides = snap.plain or snap.take
            return everyone.CoachCard(key="", name=f"{MODEL_NAME}'s card",
                                      picks={i: everyone.short(team) for i, team in sides.items() if everyone.short(team)},
                                      losers=tuple(code.upper() for code in snap.losers))
        except Exception:  # noqa: BLE001 - the board stands without it
            return None

    def _render_tiles(self, season, board: everyone.Board, mine) -> None:
        if not board.coaches:
            for tile in self._tiles:
                tile.update_values(self.NO_VALUE, "once a week's pick sheet is in")
            return
        self.tile_cards.update_values(
            str(len(board.coaches)),
            f"of {len(season.players)} coaches, week {board.week}\n"
            f"{len(board.decided)} of {_plural(len(board.games), 'game')} decided",
        )
        agreed, split = board.most_popular, board.most_split
        if agreed is not None:
            self.tile_agreed.update_values(
                agreed.favourite or "Level",
                f"on {max(agreed.on_away, agreed.on_home)} of {agreed.cards} cards\n{agreed.matchup}",
            )
        if split is not None:
            self.tile_split.update_values(
                f"{split.away} {split.on_away} – {split.on_home} {split.home}",
                f"the closest the pool came to an even split\n{split.matchup}",
            )
        if mine is None:
            self.tile_crowd.update_values(self.NO_VALUE, f"{me.NAME} has no card this week")
        else:
            same, of = mine.with_crowd(board.games)
            apart = [g for g in board.games if g.favourite and mine.picks.get(g.index) not in ("", None, g.favourite)]
            self.tile_crowd.update_values(
                f"{same} of {of}",
                "games you are on the side most cards are on\n"
                + ("you went your own way on " + ", ".join(mine.picks[g.index] for g in apart) if apart
                   else "you never left the crowd"),
            )

    def _render_board(self, board: everyone.Board, mine, model) -> None:
        card, box, note = self.cards["board"]
        self.clear_layout(box)
        if not board.coaches:
            card.set_title(BOARD_TITLE)
            note.setText("Shows up once a week's pick sheet is in the folder.")
            return
        games = board.games
        pool = everyone.CoachCard(key="", name=POOL_ROW, picks={g.index: g.favourite for g in games if g.favourite})
        others = sorted((c for c in board.coaches if c is not mine),
                        key=lambda c: (-c.right(games), c.name.casefold()))
        listed = [pool] + ([model] if model is not None else []) + ([mine] if mine is not None else []) + others
        rows, tones, tips = [], {}, {}
        for r, coach in enumerate(listed):
            name = f"{coach.name} (you)" if coach is mine else coach.name
            cells = [name]
            for c, game in enumerate(games, 1):
                state = coach.state(game)
                cells.append(coach.picks.get(game.index) or NO_PICK)
                tones[(r, c)] = {"right": "good", "wrong": "bad", "": "muted"}.get(state, "")
                tips[(r, c)] = game.matchup + (f" · pool line {game.line}" if game.line else "")
            cells.append(f"{coach.right(games)}" if board.decided else NO_PICK)
            if coach is pool or coach is model:
                tones[(r, 0)] = "muted"
            rows.append(cells)
        headers = ["Coach"] + [f"{g.away}\n{g.home}" for g in games] + ["Right"]
        table = TableModel(headers, rows, palette=self.palette, numeric_columns={len(games) + 1},
                           tones=tones, tooltips=tips, bold_columns={0},
                           sort_values={len(games) + 1: [c.right(games) for c in listed]})
        view, _ = make_table(table, stretch_column=0, row_height=ROW_HEIGHT, fit_rows=None)
        view.horizontalHeader().setFixedHeight(48)          # two lines: the road team over the home team
        fit_height(view, len(rows), ROW_HEIGHT, 60)
        box.addWidget(view)
        card.set_title(f"{BOARD_TITLE} - week {board.week}, {len(board.coaches)} coaches")
        note.setText(
            "Each row is a coach and each column is a game (road team on top). Green picks came in, red "
            "ones didn't, and white ones haven't been played yet. "
            f"\u201c{POOL_ROW}\u201d is the side most of the pool took."
            + ("" if board.from_sheet else " This week has no pick sheet, so only finished games are shown.")
        )

    def _render_games(self, board: everyone.Board, mine, model) -> None:
        card, box, note = self.cards["games"]
        self.clear_layout(box)
        card.setVisible(bool(board.coaches))
        if not board.coaches:
            return
        rows, tones = [], {}
        for r, g in enumerate(board.games):
            first, second = ((g.home, g.on_home), (g.away, g.on_away)) if g.on_home >= g.on_away else ((g.away, g.on_away), (g.home, g.on_home))
            cells = [g.matchup, g.line or "straight up", f"{first[0]} {first[1]}  ·  {second[0]} {second[1]}",
                     f"{g.share:.0%}" if g.cards else NO_PICK, g.winner or "to play"]
            for c, coach in ((5, mine), (6, model)):
                pick = coach.picks.get(g.index) if coach is not None else None
                cells.append(pick or NO_PICK)
                state = coach.state(g) if coach is not None else ""
                tones[(r, c)] = {"right": "good", "wrong": "bad", "": "muted"}.get(state, "")
            if g.winner:
                tones[(r, 4)] = "good" if g.winner == g.favourite else "warning"
            else:
                tones[(r, 4)] = "muted"
            rows.append(cells)
        table = TableModel(["Game", "Pool line", "Cards on each side", "On the favourite side", "Credited", "You",
                            MODEL_NAME], rows, palette=self.palette, numeric_columns={3}, tones=tones,
                           sort_values={3: [g.share for g in board.games]}, bold_columns={0})
        view, _ = make_table(table, stretch_column=0, row_height=28)
        box.addWidget(view)
        upsets = [g for g in board.decided if g.favourite and g.winner != g.favourite]
        note.setText(
            (f"The side most cards were on lost {_plural(len(upsets), 'game')}: "
             f"{', '.join(g.matchup for g in upsets)}. " if upsets else
             "The side most cards were on has won every game so far. " if board.decided else "")
            + "\u201cCredited\u201d is the side that got the point. Yellow means it was not the side most cards were on."
        )

    def _render_sides(self, board: everyone.Board, mine) -> None:
        card, box, note = self.cards["sides"]
        self.clear_layout(box)
        with_sides = [c for c in board.coaches if c.losers or c.suicide]
        card.setVisible(bool(with_sides))
        if not with_sides:
            return
        ordered = sorted(with_sides, key=lambda c: (c is not mine, c.name.casefold()))
        rows = [[f"{c.name} (you)" if c is mine else c.name, ", ".join(c.losers) or NO_PICK, c.suicide or NO_PICK]
                for c in ordered]
        table = TableModel(["Coach", "Big Losers", "Suicide pick"], rows, palette=self.palette, bold_columns={0})
        view, _ = make_table(table, stretch_column=1, row_height=ROW_HEIGHT)
        box.addWidget(view)
        counts: dict[str, int] = {}
        for c in with_sides:
            for team in c.losers:
                counts[team] = counts.get(team, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        alive = sum(1 for c in with_sides if c.suicide)
        note.setText(
            ("Most popular Big Losers: " + ", ".join(f"{team} ({n})" for team, n in top) + ". " if top else "")
            + (f"{alive} coach{'' if alive == 1 else 'es'} made a suicide pick." if alive
               else "Nobody made a suicide pick this week.")
        )
