"""Per-player deep dive: form, rank trajectory and the weekly record."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import analytics, picks
from ...models import Player, Season
from ..charts import BarChart, LineChart, RankChart
from ..widgets import Card, StatTile, TableModel, make_table, section
from .base import Page

HEADERS = ["Week", "Wins", "Regular", "Big Loser", "Rank", "Suicide pick",
           "vs pool avg", "With pool"]
FORM_TITLE = "Wins by week, against the pool average"
RECENT_WEEKS = 3
NO_COMPARISON = "No comparison"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


@dataclass(frozen=True)
class _PoolWeek:
    """What the whole pool scored in one week."""

    average: float
    best: float


class PlayerPage(Page):
    title = "Player"
    subtitle = "One coach's season in detail"
    icon = "\N{BUST IN SILHOUETTE}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self._pool: dict[int, _PoolWeek] = {}
        self._line_records: dict[str, analytics.LineRecord] = {}
        self._line_pool_rate = 0.0
        # Per week, how much each coach went with the crowd. Empty until a
        # pick sheet has been loaded; the column simply stays blank.
        self._chalk: dict[int, dict[str, float]] = {}
        self._steadiness: list[float] = []   # sorted consistency of the pool
        self._wanted: str | None = None      # player requested via select()
        self.table: QWidget | None = None

        self.layout_.addWidget(section(self.title, self.subtitle))

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Player"))
        self.prev_btn = self._step_button("\u2039", "Previous player (Alt+Left)")
        self.picker = QComboBox()
        self.picker.setMinimumWidth(220)
        self.next_btn = self._step_button("\u203a", "Next player (Alt+Right)")
        for widget in (self.prev_btn, self.picker, self.next_btn):
            controls.addWidget(widget)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Compare with"))
        self.rival_picker = QComboBox()
        self.rival_picker.setMinimumWidth(180)
        controls.addWidget(self.rival_picker)
        controls.addStretch(1)
        self.layout_.addLayout(controls)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.layout_.addWidget(self.status)

        self.picker.currentIndexChanged.connect(lambda _: self._render())
        self.rival_picker.currentIndexChanged.connect(lambda _: self._render())
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn.clicked.connect(lambda: self._step(1))
        # Only fire while this page is on screen (Qt ignores hidden widgets').
        for keys, delta in (("Alt+Left", -1), ("Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda d=delta: self._step(d))

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_rank = StatTile("Position")
        self.tile_record = StatTile("Record")
        self.tile_form = StatTile("Recent Form")
        self.tile_money = StatTile("Net")
        self.tile_swing = StatTile("Consistency")
        self.tile_lines = StatTile("Against the Line")
        self._tiles = (
            self.tile_rank, self.tile_record, self.tile_form,
            self.tile_money, self.tile_swing, self.tile_lines,
        )
        for tile in self._tiles:
            tiles.addWidget(tile)
        self.layout_.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.form_card = Card(FORM_TITLE)
        self.form_stack = QStackedWidget()
        self.form_chart = LineChart(self.palette, height=3.4)
        self.form_bars = BarChart(self.palette, height=3.4)
        self.form_stack.addWidget(self.form_chart)
        self.form_stack.addWidget(self.form_bars)
        self.form_card.add(self.form_stack, 1)
        row.addWidget(self.form_card, 1)

        self.rank_card = Card("Position through the season")
        self.rank_chart = RankChart(self.palette, height=3.4)
        self.rank_card.add(self.rank_chart, 1)
        row.addWidget(self.rank_card, 1)
        self.layout_.addLayout(row)

        self.table_card = Card("Week by week")
        self.table_box = QVBoxLayout()
        self.table_card.body().addLayout(self.table_box)
        self.table_note = QLabel("* Week in progress - not counted in averages.")
        self.table_note.setObjectName("Muted")
        self.table_note.hide()
        self.table_card.body().addWidget(self.table_note)
        self.layout_.addWidget(self.table_card, 1)

    @staticmethod
    def _step_button(text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setFixedWidth(38)
        button.setStyleSheet("padding: 6px 0;")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def restyle(self) -> None:
        """Follow a theme change without the window rebuilding this page."""
        for chart in (self.form_chart, self.form_bars, self.rank_chart):
            chart.set_palette(self.palette)
        # Tables bake the palette into their models, so a refresh rebuilds them.
        self.refresh_now()

    # ---- data flow -----------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        self._build_pool(season)
        # Once per data change, like the pool figures - not on every player switch.
        self._line_records = analytics.line_records(season)
        self._line_pool_rate = analytics.pool_line_rate(self._line_records)
        self._chalk = {
            number: picks.chalk(sheet) for number, sheet in picks.load_all().items()
        }

        names = [p.display for p in season.ordered_players()]
        keep = self._wanted or self.picker.currentText()
        self._wanted = None
        rival_keep = self.rival_picker.currentData() or ""

        self.picker.blockSignals(True)
        self.picker.clear()
        self.picker.addItems(names)
        if keep in names:
            self.picker.setCurrentIndex(names.index(keep))
        self.picker.blockSignals(False)

        self.rival_picker.blockSignals(True)
        self.rival_picker.clear()
        self.rival_picker.addItem(NO_COMPARISON, "")
        for name in names:
            self.rival_picker.addItem(name, name)
        index = self.rival_picker.findData(rival_keep)
        self.rival_picker.setCurrentIndex(max(index, 0))
        self.rival_picker.blockSignals(False)

        self._render()

    def select(self, display: str) -> None:
        """Jump to a player, even if this page hasn't refreshed yet.

        Hidden pages defer their refresh, so their picker can still be empty
        when another page asks for a player; the request is held until the
        list exists.
        """
        self._wanted = display
        self.refresh_now()

    def _build_pool(self, season: Season) -> None:
        """Per-week pool average/best and the pool's spread of consistency.

        Computed once per data change rather than on every player switch. A
        player's score for a week is whichever pot it lives in: the final
        standings if present, otherwise the provisional week in progress.
        """
        scores: dict[int, list[float]] = {}
        for p in season.players.values():
            for week in set(p.weekly_wins) | set(p.provisional_wins):
                value = p.weekly_wins.get(week)
                if value is None:
                    value = p.provisional_wins.get(week)
                if value is not None:
                    scores.setdefault(week, []).append(value)
        self._pool = {
            week: _PoolWeek(sum(v) / len(v), max(v)) for week, v in scores.items()
        }
        self._steadiness = sorted(
            p.consistency for p in season.players.values() if len(p.weeks_played) >= 3
        )

    def _pool_week(self, week: int) -> _PoolWeek:
        return self._pool.get(week, _PoolWeek(0.0, 0.0))

    @staticmethod
    def _same_name(a: str, b: str) -> bool:
        return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()

    def _chalk_for(self, player: Player, week: int) -> float | None:
        """How much of the pool this coach agreed with, that week."""
        for coach, value in self._chalk.get(week, {}).items():
            if self._same_name(coach, player.display):
                return value
        return None

    def _chalk_season(self, player: Player) -> tuple[float, float] | None:
        """(this coach's average, the pool's average) across every loaded week."""
        mine = [v for week in self._chalk if (v := self._chalk_for(player, week)) is not None]
        everyone = [v for week in self._chalk.values() for v in week.values()]
        if not mine or not everyone:
            return None
        return sum(mine) / len(mine), sum(everyone) / len(everyone)

    # ---- navigation ----------------------------------------------------
    def _step(self, delta: int) -> None:
        target = self.picker.currentIndex() + delta
        if 0 <= target < self.picker.count():
            self.picker.setCurrentIndex(target)

    # ---- render --------------------------------------------------------
    def _render(self) -> None:
        season = self.season
        if season is None:
            return
        if not self.picker.count():
            self._show_empty()
            return
        player = season.by_display(self.picker.currentText())
        if player is None:
            return
        rival = self._rival(season, player)
        weeks = season.final_weeks()

        self.prev_btn.setEnabled(self.picker.currentIndex() > 0)
        self.next_btn.setEnabled(self.picker.currentIndex() < self.picker.count() - 1)

        self._update_tiles(season, player)
        self._update_status(player, rival, weeks)
        self._update_form_chart(player, rival, weeks)
        self._update_rank_chart(player, rival)
        self._update_table(season, player, weeks)

    def _rival(self, season: Season, player: Player) -> Player | None:
        name = self.rival_picker.currentData()
        rival = season.by_display(name) if name else None
        return None if rival is None or rival.key == player.key else rival

    def _show_empty(self) -> None:
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "No data loaded")
        self.status.setText("")
        self.form_stack.setCurrentWidget(self.form_chart)
        self.form_card.set_title(FORM_TITLE)
        self.form_chart.empty()
        self.rank_chart.empty()
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.clear_layout(self.table_box)
        self.table = None
        self.table_note.hide()

    def _update_tiles(self, season: Season, player: Player) -> None:
        move = player.rank_movement or 0
        detail = f"of {_plural(len(season.players), 'player')}"
        if move:
            detail += f"   \u25b2 {move}" if move > 0 else f"   \u25bc {abs(move)}"
        self.tile_rank.update_values(
            f"#{player.pos}" if player.pos else self.NO_VALUE,
            detail,
            "good" if move > 0 else ("bad" if move < 0 else ""),
        )

        self.tile_record.update_values(
            f"{player.wins}-{player.losses}",
            f"{player.pct:.3f}   {player.games_behind:.0f} back",
        )

        recent = player.trend(RECENT_WEEKS)
        form_detail = f"average over the last {RECENT_WEEKS} weeks played"
        form_tone = ""
        if len(player.weeks_played) > RECENT_WEEKS:
            diff = recent - player.average_wins
            form_detail = f"{diff:+.1f} against a {player.average_wins:.1f} season average"
            if diff >= 0.25:
                form_tone = "good"
            elif diff <= -0.25:
                form_tone = "bad"
        self.tile_form.update_values(f"{recent:.1f}", form_detail, form_tone)

        net = player.net_points
        self.tile_money.update_values(
            self.money(net, signed=True),
            f"{self.money(player.points_won)} won, {self.money(abs(player.points_paid))} in",
            "good" if net > 0 else ("bad" if net < 0 else ""),
        )

        swing = f"between {player.worst_week} and {player.best_week} wins"
        if len(player.weeks_played) >= 3 and len(self._steadiness) > 1:
            # How many of the *other* players swing more than this one does.
            steadier_than = len(self._steadiness) - bisect_right(self._steadiness, player.consistency)
            share = steadier_than / (len(self._steadiness) - 1)
            swing += f"\nsteadier than {self.pct(share, 0)} of the pool"
        self.tile_swing.update_values(f"\u00b1{player.consistency:.2f}", swing)

        lined = self._line_records.get(player.key)
        if lined is None or not lined.decided:
            self.tile_lines.update_values(self.NO_VALUE, "no lined games decided yet")
        else:
            pool = self._line_pool_rate
            self.tile_lines.update_values(
                f"{lined.correct}/{lined.decided}",
                f"{self.pct(lined.rate, 0)} right, {lined.per_week:.1f} a week\n"
                f"pool average {self.pct(pool, 0)}",
                "good" if lined.rate > pool else ("bad" if lined.rate < pool else ""),
            )

    def _update_status(self, player: Player, rival: Player | None, weeks: list[int]) -> None:
        alive = "alive" if player.suicide_alive else "eliminated"
        parts = [
            f"Big-loser points {player.big_loser_points:g}",
            f"suicide pool {alive}",
            f"seen in {_plural(len(player.sources), 'file')}",
        ]
        crowd = self._chalk_season(player)
        if crowd is not None:
            mine, pool = crowd
            parts.append(
                f"with the pool on {self.pct(mine, 0)} of picks, against "
                f"{self.pct(pool, 0)} for the field"
            )
        if rival is not None:
            parts.append(self._head_to_head(player, rival, weeks))
        self.status.setText(" \u00b7 ".join(parts))

    @staticmethod
    def _head_to_head(player: Player, rival: Player, weeks: list[int]) -> str:
        ahead = level = behind = 0
        for week in weeks:
            mine, theirs = player.weekly_wins.get(week), rival.weekly_wins.get(week)
            if mine is None or theirs is None:
                continue
            if mine > theirs:
                ahead += 1
            elif mine < theirs:
                behind += 1
            else:
                level += 1
        shared = ahead + level + behind
        if not shared:
            return f"no shared weeks with {rival.display} yet"
        text = f"against {rival.display}: ahead in {ahead} of {_plural(shared, 'week')}"
        if level:
            text += f", level in {level}"
        return text

    def _update_form_chart(self, player: Player, rival: Player | None, weeks: list[int]) -> None:
        p = self.palette
        if len(weeks) >= 2:
            # Each player keeps a fixed colour slot: you first, the rival second.
            series = [(player.display, [player.weekly_wins.get(w) for w in weeks])]
            if rival is not None:
                series.append((rival.display, [rival.weekly_wins.get(w) for w in weeks]))
            self.form_stack.setCurrentWidget(self.form_chart)
            self.form_card.set_title(FORM_TITLE)
            self.form_chart.plot(
                weeks,
                series,
                ylabel="Wins",
                reference=("Pool average", [self._pool_week(w).average for w in weeks]),
                direct_label=False,
            )
        elif len(weeks) == 1:
            # A single week is a comparison, not a trend: bars read it better.
            week = weeks[0]
            pool = self._pool_week(week)
            mine = player.weekly_wins.get(week, 0)
            labels, values = [player.display], [mine]
            colors = [p.series[0]]
            tips = [f"{player.display}: {mine} wins"]
            if rival is not None:
                theirs = rival.weekly_wins.get(week, 0)
                labels.append(rival.display)
                values.append(theirs)
                colors.append(p.series[1])
                tips.append(f"{rival.display}: {theirs} wins")
            labels += ["Pool average", "Pool best"]
            values += [pool.average, pool.best]
            colors += [p.ink_muted, p.series[2]]
            tips += [
                f"Pool average: {pool.average:.1f} wins",
                f"Best in the pool: {pool.best:g} wins",
            ]
            self.form_stack.setCurrentWidget(self.form_bars)
            self.form_card.set_title(f"Week {week} - against the pool")
            self.form_bars.plot(
                labels, values,
                xlabel="Wins",
                colors=colors,
                value_format="{:.1f}",
                tooltips=tips,
            )
        else:
            self.form_stack.setCurrentWidget(self.form_chart)
            self.form_card.set_title(FORM_TITLE)
            self.form_chart.empty("No finalised weeks yet")

    def _update_rank_chart(self, player: Player, rival: Player | None) -> None:
        rank_weeks = set(player.weekly_rank)
        if rival is not None:
            rank_weeks |= set(rival.weekly_rank)
        if not rank_weeks:
            self.rank_chart.empty("No weekly rankings recorded")
            return
        weeks = sorted(rank_weeks)
        series = [(player.display, [player.weekly_rank.get(w) for w in weeks])]
        if rival is not None:
            series.append((rival.display, [rival.weekly_rank.get(w) for w in weeks]))
        self.rank_chart.plot(
            weeks,
            series,
            ylabel="Position (1 is best)",
            direct_label=False,
        )

    def _update_table(self, season: Season, player: Player, weeks: list[int]) -> None:
        all_weeks = sorted(set(weeks) | set(player.provisional_wins))
        entries = []  # (week, wins) for every week the player has a score
        for week in all_weeks:
            wins = player.weekly_wins.get(week, player.provisional_wins.get(week))
            if wins is not None:
                entries.append((week, wins))

        final_wins = [w for wk, w in entries if wk not in season.provisional_weeks]
        best = max(final_wins, default=None)
        worst = min(final_wins, default=None)

        rows, tones = [], {}
        sort = {col: [] for col in (0, 1, 2, 3, 4, 6, 7)}
        for r, (week, wins) in enumerate(entries):
            provisional = week in season.provisional_weeks
            delta = wins - self._pool_week(week).average
            week_obj = season.weeks.get(week)
            line = week_obj.lines.get(player.key) if week_obj else None
            regular = player.weekly_regular.get(week)
            big_loser = player.weekly_big_loser.get(week)
            rank = player.weekly_rank.get(week)

            crowd = self._chalk_for(player, week)
            rows.append([
                f"Week {week}" + (" *" if provisional else ""),
                wins,
                self.NO_VALUE if regular is None else regular,
                self.NO_VALUE if big_loser is None else big_loser,
                self.NO_VALUE if rank is None else rank,
                (line.suicide_pick if line else "") or self.NO_VALUE,
                f"{delta:+.1f}",
                self.NO_VALUE if crowd is None else self.pct(crowd, 0),
            ])
            # Sort keys stay aligned with the rows actually shown.
            for col, value in zip((0, 1, 2, 3, 4, 6, 7),
                                  (week, wins, regular, big_loser, rank, delta, crowd)):
                sort[col].append(value)

            tones[(r, 6)] = "good" if delta > 0 else ("bad" if delta < 0 else "muted")
            if not provisional and best is not None and best != worst and wins == best:
                tones[(r, 1)] = "good"

        model = TableModel(
            HEADERS,
            rows,
            palette=self.palette,
            numeric_columns={1, 2, 3, 4, 6, 7},
            sort_values=sort,
            tones=tones,
        )

        # Switching player rebuilds the table; keep the user's chosen sort.
        sort_column, ascending = self._current_sort()
        view, _ = make_table(
            model, stretch_column=5, sort_column=sort_column,
            ascending=ascending, row_height=28,
        )
        view.setMinimumHeight(200)

        self.clear_layout(self.table_box)
        self.table = view
        self.table_box.addWidget(view)
        self.table_note.setVisible(any(wk in season.provisional_weeks for wk, _ in entries))

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