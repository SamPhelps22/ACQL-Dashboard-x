"""Full season standings, with search and a week-by-week grid."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ... import analytics
from ...models import Player, Season
from ..charts import HeatmapChart, LineChart
from ..widgets import Card, TableModel, make_table, section
from .base import Page

HEADERS = [
    "#", "Player", "W", "L", "PCT", "GB", "Won", "Net $",
    "This Wk", "Last 3", "Move", "Best", "Avg", "Lines", "Lines %", "Weeks",
]
NUMERIC = {0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}
LINES_COLUMN, LINES_PCT_COLUMN = 13, 14
NAME_COLUMN = 1
GRID_ROWS = 24
# Contenders in the race chart. Four is the most the lines can be labelled
# directly at their ends; past that, identity would rest on the legend alone.
RACE_PLAYERS = 10
RACE_TITLE = "The race - wins behind the leader, week by week"
UP, DOWN = "▲", "▼"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def running_wins(player: Player, weeks: list[int]) -> list[int]:
    """Season wins after each week. A missed week adds nothing but keeps the
    total, since the wins a player already has do not go away."""
    total, out = 0, []
    for week in weeks:
        total += player.weekly_wins.get(week) or 0
        out.append(total)
    return out


def gaps_to_leader(
    contenders: list[Player], field: list[Player], weeks: list[int]
) -> list[list[int]]:
    """Each contender's wins behind whoever led the whole pool that week.

    Raw running totals all climb together, so a four-win gap is a sliver on
    an axis that runs to a hundred. Measured against the leader, the week's
    leader sits at zero and everyone else is plainly behind: lead changes,
    and whether the race is closing or pulling apart, read straight off it.
    """
    totals = {p.key: running_wins(p, weeks) for p in field}
    leader = [max(t[i] for t in totals.values()) for i in range(len(weeks))]
    return [
        [totals[p.key][i] - leader[i] for i in range(len(weeks))]
        for p in contenders
    ]


class StandingsPage(Page):
    title = "Standings"
    subtitle = "Official positions from the latest stats.xls export"
    icon = "\N{SPORTS MEDAL}"

    #: Emitted when a row is opened, so the window can show that player.
    player_selected = Signal(str)

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.table: QWidget | None = None
        self.proxy = None

        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter players…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self._apply_filter)
        controls.addWidget(self.search)
        controls.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        controls.addWidget(self.count_label)
        self.layout_.addLayout(controls)

        self.table_card = Card()
        self.table_container = QVBoxLayout()
        self.table_card.body().addLayout(self.table_container)
        self.hint = QLabel("Double-click a row to open that player.")
        self.hint.setObjectName("Muted")
        self.table_card.body().addWidget(self.hint)
        self.layout_.addWidget(self.table_card, 3)

        # The table says where everyone stands; this says how the leaders got
        # there, and whether the race is pulling apart or closing up.
        self.race_card = Card(RACE_TITLE)
        self.race_chart = LineChart(self.palette, height=3.6)
        self.race_card.add(self.race_chart, 1)
        self.layout_.addWidget(self.race_card, 2)

        self.grid_card = Card("Wins by week")
        self.grid_chart = HeatmapChart(self.palette, height=7.0)
        self.grid_card.add(self.grid_chart, 1)
        self.layout_.addWidget(self.grid_card, 2)

    def restyle(self) -> None:
        """Follow a theme change without the window rebuilding this page."""
        self.grid_chart.set_palette(self.palette)
        self.race_chart.set_palette(self.palette)
        # The table bakes the palette into its model, so it has to be rebuilt.
        self.refresh_now()

    # ---- filtering -----------------------------------------------------
    def _apply_filter(self, text: str) -> None:
        if self.proxy is not None:
            self.proxy.setFilterFixedString(text)
            self._update_count()

    def _update_count(self) -> None:
        if self.proxy is None or self.season is None:
            return
        shown, total = self.proxy.rowCount(), len(self.season.players)
        self.count_label.setText(
            _plural(total, "player") if shown == total else f"{shown} of {total} players"
        )

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        order = season.ordered_players()
        if not order:
            self._show_empty()
            return
        self._update_table(order, analytics.line_records(season))
        self._update_race(season, order)
        self._update_grid(season, order)

    def _show_empty(self) -> None:
        self.clear_layout(self.table_container)
        self.table = self.proxy = None
        self.count_label.setText("")
        self.hint.hide()
        note = QLabel("No players in this season yet.")
        note.setObjectName("Muted")
        self.table_container.addWidget(note)
        self.grid_chart.empty("No weeks scored yet")
        self.race_card.set_title(RACE_TITLE)
        self.race_chart.empty("No weeks scored yet")

    @staticmethod
    def _movement(player: Player) -> tuple[str, str, int]:
        """Arrow, tone and sort key for a player's change of position."""
        move = player.rank_movement
        if not move:                       # None or 0 - both read as no change
            return "–", "", -99 if move is None else 0
        if move > 0:
            return f"{UP} {move}", "good", move
        return f"{DOWN} {abs(move)}", "bad", move

    @staticmethod
    def _count(value: int | None, played: bool) -> object:
        """A real zero is a score, not a blank.

        `0 or "-"` collapses the two, so a player who genuinely went 0-16 this
        week looked as though they had not played at all.
        """
        if value is None or not played:
            return None
        return value

    def _update_table(self, order: list[Player], records: dict[str, analytics.LineRecord]) -> None:
        pool_rate = analytics.pool_line_rate(records)
        none = analytics.LineRecord(0, 0, 0)
        rows, tones, tooltips = [], {}, {}
        for r, player in enumerate(order):
            lined = records.get(player.key, none)
            played = bool(player.weeks_played)
            move_text, move_tone, _ = self._movement(player)
            net = player.net_points
            won = player.total_winnings
            rows.append([
                player.pos or r + 1,
                player.display,
                player.wins,
                player.losses,
                f"{player.pct:.3f}",
                f"{player.games_behind:.0f}" if player.games_behind else self.NO_VALUE,
                self.money(won) if won else self.NO_VALUE,
                self.money(net, signed=True),
                self._blank(self._count(player.current_week_wins, played)),
                self._blank(self._count(player.three_week_wins, played)),
                move_text,
                self._blank(player.best_week if played else None),
                f"{player.average_wins:.1f}" if played else self.NO_VALUE,
                f"{lined.correct}/{lined.decided}" if lined.decided else self.NO_VALUE,
                self.pct(lined.rate, 0) if lined.decided else self.NO_VALUE,
                len(player.weeks_played),
            ])
            if lined.decided:
                # Measured against the pool, not against 50%: the pool as a
                # whole may be well under half on lined games.
                tones[(r, LINES_PCT_COLUMN)] = (
                    "good" if lined.rate > pool_rate else "bad" if lined.rate < pool_rate else "muted"
                )
            tones[(r, 7)] = "good" if net > 0 else ("bad" if net < 0 else "muted")
            if move_tone:
                tones[(r, 10)] = move_tone
            if won > 0:
                tones[(r, 6)] = "good"
            tooltips[(r, NAME_COLUMN)] = (
                f"{player.display}\nBest week {player.best_week}, "
                f"worst {player.worst_week}\n"
                f"Consistency +/-{player.consistency:.2f}\n"
                f"Big-loser wins {player.big_loser_wins}\n"
                f"Suicide pool: {'alive' if player.suicide_alive else 'eliminated'}\n"
                "Double-click to open this player"
            )
            if lined.decided:
                tooltips[(r, LINES_COLUMN)] = tooltips[(r, LINES_PCT_COLUMN)] = (
                    f"{player.display}: {lined.correct} of {lined.decided} lined games right "
                    f"({self.pct(lined.rate, 0)}), {lined.per_week:.1f} a week\n"
                    f"Pool average {self.pct(pool_rate, 0)}"
                )

        sort_values = {
            # The displayed position, not the row number: after a re-sort the
            # two differ, and the column has to keep meaning what it shows.
            0: [p.pos if p.pos is not None else 9_999 for p in order],
            4: [p.pct for p in order],
            5: [p.games_behind for p in order],
            6: [p.total_winnings for p in order],
            7: [p.net_points for p in order],
            8: [p.current_week_wins for p in order],
            9: [p.three_week_wins for p in order],
            10: [self._movement(p)[2] for p in order],
            11: [p.best_week for p in order],
            12: [p.average_wins for p in order],
            LINES_COLUMN: [records.get(p.key, none).correct for p in order],
            LINES_PCT_COLUMN: [
                records.get(p.key, none).rate if records.get(p.key, none).decided else None
                for p in order
            ],
        }

        model = TableModel(
            HEADERS, rows,
            palette=self.palette,
            numeric_columns=NUMERIC,
            sort_values=sort_values,
            tones=tones,
            tooltips=tooltips,
            bold_columns={NAME_COLUMN},
        )
        # Rebuilding the table resets its sort, so carry the user's choice over.
        sort_column, ascending = self._current_sort()
        view, proxy = make_table(
            model, stretch_column=NAME_COLUMN, sort_column=sort_column,
            ascending=ascending, row_height=29,
        )
        proxy.set_filter_columns([NAME_COLUMN])
        view.setMinimumHeight(320)
        view.doubleClicked.connect(self._open_player)

        self.clear_layout(self.table_container)
        self.table, self.proxy = view, proxy
        self.table_container.addWidget(view)
        self.hint.show()
        self._apply_filter(self.search.text())

    def _blank(self, value: object) -> object:
        return self.NO_VALUE if value is None else value

    def _open_player(self, index) -> None:
        """Hand the double-clicked player's name to whoever is listening."""
        if self.proxy is None or not index.isValid():
            return
        source = self.proxy.mapToSource(index)
        name = self.proxy.sourceModel().row_values(source.row())[NAME_COLUMN]
        if name:
            self.player_selected.emit(str(name))

    def _current_sort(self) -> tuple[int, bool]:
        """The table's current (column, ascending), or the default if unknown."""
        default = (0, True)
        view = self.table
        if view is None or not hasattr(view, "horizontalHeader"):
            return default
        header = view.horizontalHeader()
        column = header.sortIndicatorSection()
        if not 0 <= column < len(HEADERS):
            return default
        return column, header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder

    # ---- the race -------------------------------------------------------
    def _update_race(self, season: Season, order: list[Player]) -> None:
        # Final weeks only: a half-entered week would dip every line at the end.
        weeks = season.final_weeks()
        contenders = order[:RACE_PLAYERS]
        if len(weeks) < 2:
            self.race_card.set_title(RACE_TITLE)
            self.race_chart.empty("The race appears once two weeks are final")
            return

        gaps = gaps_to_leader(contenders, order, weeks)
        title = f"{RACE_TITLE} - top {len(contenders)}"
        if len(contenders) > 1:
            spread = -min(g[-1] for g in gaps)
            title += f", all within {_plural(spread, 'win')} of the lead"
        self.race_card.set_title(title)
        self.race_chart.plot(
            weeks,
            [(p.display, g) for p, g in zip(contenders, gaps)],
            ylabel="Wins behind the lead",
            direct_label=True,
        )

    # ---- week-by-week grid ---------------------------------------------
    def _update_grid(self, season: Season, order: list[Player]) -> None:
        weeks = season.played_weeks()
        if not weeks:
            self.grid_chart.empty("No weeks scored yet")
            self.grid_card.set_title("Wins by week")
            return

        shown = order[:GRID_ROWS]
        values = [
            [p.weekly_wins.get(w, p.provisional_wins.get(w)) for w in weeks]
            for p in shown
        ]
        labels = [f"Wk {w}" + ("*" if w in season.provisional_weeks else "") for w in weeks]

        # The chart now carries its own colour key, so the title says what is
        # in the grid rather than how to read the shading.
        scope = (
            f"top {len(shown)} players"
            if len(order) > GRID_ROWS
            else f"all {_plural(len(shown), 'player')}"
        )
        note = "  (* week in progress)" if season.provisional_weeks else ""
        self.grid_card.set_title(f"Wins by week - {scope}{note}")

        self.grid_chart.plot(
            [p.display for p in shown],
            labels,
            values,
            cell_text=len(weeks) <= 10,
            key_label="more wins",
            tooltip_fn=lambda player, week, v: (
                f"{player} - {week}\n" + ("not played" if v is None else f"{v:g} wins")
            ),
        )