"""The two side pools: Big Loser and Suicide."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import analytics
from ...pool import bigloser
from ...feeds import oddslock
from ...models import Player, Season
from ...version import MODEL_NAME
from ...wording import plural as _plural
from ..charts import BarChart, LineChart
from ..widgets import Card, StatTile, TableModel, current_sort, make_table, section, tile_grid
from .base import Page

BL_HEADERS = ["#", "Player", "Points", "Wins", "Weeks", "Avg / week"]
SUICIDE_HEADERS = ["Player", "Status", "Latest pick", "Picks made", "Out in"]
BL_CHART_SIZE = 12
SURVIVAL_TITLE = "Suicide pool - still alive after each week"
OPTIMIZER_TITLE = "Big Loser optimizer"
RECORD_TITLE = "Big Loser picking - every coach's record"
OPTIMIZER_HEADERS = ["Team", "Game", "Lose by 15+", "Pool has it", "Gain on the pool", "Take"]
RECORD_HEADERS = ["Coach", "Came in", "Picks", "Rate", "Deserved", "Luck", "With the pool"]
#: Candidates listed on the optimizer; the rest are long shots nobody holds.
OPTIMIZER_SHOWN = 14


def survivors_by_week(
    players: list[Player], weeks: list[int]
) -> tuple[list[int], int]:
    """How many were still alive after each week, and how many can't be placed.

    A player is placed if they are alive or the week they went out is known.
    Someone marked eliminated with no week recorded cannot be put on the
    timeline honestly - counting them out from week one would invent a
    collapse that never happened - so they are left off and counted instead.
    """
    placed = [p for p in players if p.suicide_alive or p.suicide_out_week]
    unplaced = len(players) - len(placed)
    counts = [
        sum(
            1 for p in placed
            if p.suicide_alive or (p.suicide_out_week or 0) > week
        )
        for week in weeks
    ]
    return counts, unplaced


class PoolsPage(Page):
    from ...places import SIDE_POOLS as title
    subtitle = "Big Loser standings and the best picks left, and who is still alive in the suicide pool"
    icon = "\N{DIRECT HIT}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.bl_table: QWidget | None = None
        self.suicide_table: QWidget | None = None

        self.layout_.addWidget(section(self.title, self.subtitle))

        self.tile_bl_leader = StatTile("Big Loser Leader")
        self.tile_alive = StatTile("Suicide Survivors")
        self.tile_out = StatTile("Eliminated")
        self.tile_bl_max = StatTile("Big Loser Picks")
        self._tiles = (
            self.tile_bl_leader, self.tile_alive, self.tile_out, self.tile_bl_max,
        )
        # Wrapped rather than squeezed: 4 to a row keeps every tile
        # wide enough for its own number on a laptop screen.
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        # Which three to take: the blowout, the pool's share of it, the gain.
        self.optimizer_card = Card(OPTIMIZER_TITLE)
        self.optimizer_lead = QLabel("")
        self.optimizer_lead.setWordWrap(True)
        self.optimizer_lead.setTextFormat(Qt.TextFormat.RichText)
        self.optimizer_card.add(self.optimizer_lead)
        self.optimizer_box = QVBoxLayout()
        self.optimizer_card.body().addLayout(self.optimizer_box)
        self.optimizer_note = QLabel("")
        self.optimizer_note.setObjectName("Muted")
        self.optimizer_note.setWordWrap(True)
        self.optimizer_card.add(self.optimizer_note)
        self.layout_.addWidget(self.optimizer_card)

        self.record_card = Card(RECORD_TITLE)
        self.record_lead = QLabel("")
        self.record_lead.setWordWrap(True)
        self.record_card.add(self.record_lead)
        self.record_box = QVBoxLayout()
        self.record_card.body().addLayout(self.record_box)
        self.record_note = QLabel("")
        self.record_note.setObjectName("Muted")
        self.record_note.setWordWrap(True)
        self.record_card.add(self.record_note)
        self.layout_.addWidget(self.record_card)
        self.record_table: QWidget | None = None

        self.teams_card = Card("Big Loser teams by week")
        self.teams_label = QLabel("")
        self.teams_label.setWordWrap(True)
        self.teams_label.setObjectName("StatDetail")
        self.teams_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.teams_card.add(self.teams_label)
        self.layout_.addWidget(self.teams_card)

        # The table lists who fell; this shows the pool thinning week by week,
        # which is the story of a survivor pool.
        self.survival_card = Card(SURVIVAL_TITLE)
        self.survival_chart = LineChart(self.palette, height=3.0)
        self.survival_card.add(self.survival_chart, 1)
        self.layout_.addWidget(self.survival_card)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.bl_card = Card("Big Loser pool")
        self.bl_chart = BarChart(self.palette, height=4.2)
        self.bl_card.add(self.bl_chart, 1)
        self.bl_box = QVBoxLayout()
        self.bl_card.body().addLayout(self.bl_box)
        row.addWidget(self.bl_card, 1, Qt.AlignmentFlag.AlignTop)

        self.suicide_card = Card("Suicide pool")
        self.suicide_box = QVBoxLayout()
        self.suicide_card.body().addLayout(self.suicide_box)
        row.addWidget(self.suicide_card, 1, Qt.AlignmentFlag.AlignTop)
        self.layout_.addLayout(row)

    def restyle(self) -> None:
        self.bl_chart.set_palette(self.palette)
        self.survival_chart.set_palette(self.palette)
        # Both tables bake the palette into their models, so they are rebuilt.
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        players = list(season.players.values())
        if not players:
            self._show_empty()
            return

        big_loser = sorted(
            players, key=lambda p: (-p.big_loser_points, p.display.lower())
        )
        self._update_tiles(season, players, big_loser)
        self._update_optimizer(season)
        self._update_record(season)
        self._update_teams(season)
        self._update_survival(season, players)
        self._update_bl_chart(big_loser)
        self._update_bl_table(big_loser)
        self._update_suicide_table(players)

    def _show_empty(self) -> None:
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "No data")
            tile.hide_bar()
        self.teams_card.hide()
        self.survival_card.set_title(SURVIVAL_TITLE)
        self.survival_chart.empty("No suicide entries yet")
        self.bl_chart.empty("No big-loser points recorded yet")
        for box, attr, text in (
            (self.bl_box, "bl_table", "No players in this season yet."),
            (self.suicide_box, "suicide_table", "No suicide entries yet."),
        ):
            self.clear_layout(box)
            setattr(self, attr, None)
            note = QLabel(text)
            note.setObjectName("Muted")
            box.addWidget(note)

    def _update_tiles(
        self, season: Season, players: list[Player], big_loser: list[Player]
    ) -> None:
        best = big_loser[0].big_loser_points if big_loser else 0
        leaders = [p.display for p in big_loser if p.big_loser_points == best and best]
        if not leaders:
            self.tile_bl_leader.update_values(self.NO_VALUE, "No points scored yet")
        else:
            shared = ", ".join(leaders[:3]) + ("…" if len(leaders) > 3 else "")
            self.tile_bl_leader.update_values(
                leaders[0] if len(leaders) == 1 else f"{len(leaders)}-way tie",
                f"{best:g} {'point' if best == 1 else 'points'}"
                + (f": {shared}" if len(leaders) > 1 else ""),
                "good",
            )

        alive = [p for p in players if p.suicide_alive]
        out = sorted(p.display for p in players if not p.suicide_alive)
        self.tile_alive.update_values(
            str(len(alive)),
            f"of {_plural(len(players), 'entrant')} still in",
            "good" if alive else "bad",
        )
        # A suicide pool is read by how much of it is left, not by the count.
        if players:
            self.tile_alive.show_bar(len(alive) / len(players), None,
                                     "good" if alive else "bad", self.palette)
        else:
            self.tile_alive.hide_bar()
        self.tile_out.update_values(
            str(len(out)),
            (", ".join(out[:4]) + ("…" if len(out) > 4 else ""))
            or "nobody is out yet",
        )
        self.tile_bl_max.update_values(
            str(season.max_big_loser_points), "picks available each week",
        )

    # ---- the Big Loser optimizer and record (bigloser.py) ---------------------------
    def _optimizer_week(self, season: Season) -> int:
        """The week still open to pick: the one ahead, or the next when its cards are in."""
        week = analytics.upcoming_week(season)
        if week and oddslock.locked_for(season, week) and season.weeks.get(week + 1) is not None:
            return week + 1
        return week

    def _update_optimizer(self, season: Season) -> None:
        self.clear_layout(self.optimizer_box)
        week = self._optimizer_week(season)
        board = bigloser.board(season, week) if week else bigloser.Board(0)
        if not board.options:
            self.optimizer_card.set_title(OPTIMIZER_TITLE)
            self.optimizer_lead.setText(
                f"Appears once week {week} has its betting lines." if week else "No week to pick yet.")
            self.optimizer_note.setText("")
            return
        likeliest = {o.code for o in board.likeliest}
        gains = {o.code for o in board.best_gain}
        shown = [o for o in board.options if o.code in likeliest | gains][:OPTIMIZER_SHOWN]
        shown += [o for o in board.options if o not in shown][:max(0, OPTIMIZER_SHOWN - len(shown))]
        shown.sort(key=lambda o: -o.chance)
        rows, tones = [], {}
        for r, o in enumerate(shown):
            take = " + ".join(filter(None, [
                "\u2605 most points" if o.code in likeliest else "",
                "\u25b2 gains most" if o.code in gains else "",
            ]))
            rows.append([o.team, f"against {o.opponent}", f"{o.chance:.0%}", f"{o.held:.0%}",
                         f"+{o.gain:.2f}", take])
            if take:
                tones[(r, 5)] = "good"
            if o.code in gains:
                tones[(r, 4)] = "good"
            if o.code in likeliest:
                tones[(r, 2)] = "good"
        model = TableModel(
            OPTIMIZER_HEADERS, rows, palette=self.palette, numeric_columns={2, 3, 4},
            sort_values={2: [o.chance for o in shown], 3: [o.held for o in shown], 4: [o.gain for o in shown]},
            tones=tones, bold_columns={0},
        )
        view, _ = make_table(model, stretch_column=1, row_height=27)
        self.optimizer_box.addWidget(view)

        def names(options) -> str:
            return ", ".join(o.team for o in options)

        top, gain = board.likeliest, board.best_gain
        self.optimizer_card.set_title(f"{OPTIMIZER_TITLE} - week {week}")
        self.optimizer_lead.setText(
            f"<b>\u2605 Most points:</b> {names(top)} - {sum(o.chance for o in top):.2f} expected, "
            f"held by {sum(o.held for o in top) / len(top):.0%} of the pool on average.<br>"
            f"<b>\u25b2 Gains most on the pool:</b> {names(gain)} - {sum(o.chance for o in gain):.2f} "
            f"expected, held by {sum(o.held for o in gain) / len(gain):.0%}."
        )
        self.optimizer_note.setText(
            "A Big Loser scores a point when the team loses by 15 or more; its chance is how often teams "
            "with that line have, in every season since 1999. Gain is how much a team puts "
            "you ahead of the average card: a point everybody has moves nobody. "
            + ("The pool's share is counted from this week's pick sheet. " if board.counted else
               "The pool's share is an estimate until this week's pick sheet is in. ")
            + "Over 2011-2025, picking for gain paid about $3.70 a week more than picking the three "
              "likeliest."
        )

    def _update_record(self, season: Season) -> None:
        self.clear_layout(self.record_box)
        self.record_table = None
        review = bigloser.review(season)
        if not review.coaches:
            self.record_lead.setText("Appears once a finished week's pick sheet is loaded.")
            self.record_note.setText("")
            return
        rows, tones = [], {}
        for r, c in enumerate(review.coaches):
            luck = c.luck
            rows.append([c.name, c.hits, c.picks, f"{c.rate:.0%}", f"{c.expected:.1f}",
                         self.NO_VALUE if luck != luck else f"{luck:+.1f}", f"{c.crowd:.0%}"])
            if luck == luck and abs(luck) >= 1:
                tones[(r, 5)] = "good" if luck > 0 else "bad"
        model = TableModel(
            RECORD_HEADERS, rows, palette=self.palette, numeric_columns={1, 2, 3, 4, 5, 6},
            sort_values={3: [c.rate for c in review.coaches], 4: [c.expected for c in review.coaches],
                         5: [c.luck if c.luck == c.luck else 0.0 for c in review.coaches],
                         6: [c.crowd for c in review.coaches]},
            tones=tones, bold_columns={0},
        )
        view, _ = make_table(model, stretch_column=0, row_height=27)
        self.record_table = view
        self.record_box.addWidget(view)
        pool, model_ = review.pool, review.model
        weeks = len(review.weeks)
        self.record_card.set_title(f"{RECORD_TITLE}, over {_plural(weeks, 'week')}")
        self.record_lead.setText(
            f"The pool: {pool.hits} of {pool.picks} came in ({pool.rate:.0%}); its picks deserved "
            f"{pool.expected:.0f}. {MODEL_NAME}'s three likeliest each week: {model_.hits} of "
            f"{model_.picks}, deserved {model_.expected:.1f}."
        )
        self.record_note.setText(
            "Deserved is what the picks' own odds added up to; the difference is luck. With the pool is "
            "the share of cards holding the same team. "
            + ("So far the popular teams haven't been blown out."
               if pool.picks and pool.hits < pool.expected - 0.15 * pool.picks else "")
        )

    def _update_teams(self, season: Season) -> None:
        if not season.big_losers_by_week:
            self.teams_card.hide()
            return
        lines = [
            f"Week {week}:  " + ", ".join(t.title() for t in season.big_losers_by_week[week])
            for week in sorted(season.big_losers_by_week)
        ]
        self.teams_label.setText("\n".join(lines))
        self.teams_card.show()

    def _update_survival(self, season: Season, players: list[Player]) -> None:
        weeks = season.played_weeks()
        # With no week recorded for anyone's exit - the files say who is out,
        # not when - or fewer than two weeks played, there is no line to draw.
        # The card used to stay, a half-screen box reading "No elimination
        # weeks recorded" beneath a tile counting eighteen eliminations; it
        # now steps aside and the table beside it tells the story.
        if not any(p.suicide_out_week for p in players) or len(weeks) < 2:
            self.survival_card.hide()
            return
        self.survival_card.show()

        counts, unplaced = survivors_by_week(players, weeks)
        # Everyone on the timeline entered, including anyone out in week one,
        # so the starting field is the placed count - not the week-one figure.
        entered = len(players) - unplaced
        note = f"  ({unplaced} out in an unrecorded week, not shown)" if unplaced else ""
        self.survival_card.set_title(
            f"{SURVIVAL_TITLE} - {counts[-1]} of {entered} left{note}"
        )
        self.survival_chart.plot(
            weeks,
            [("Still alive", counts)],
            ylabel="Entrants",
            direct_label=False,
            zero_baseline=True,
        )

    def _update_bl_chart(self, big_loser: list[Player]) -> None:
        scorers = [p for p in big_loser if p.big_loser_points][:BL_CHART_SIZE]
        if not scorers:
            self.bl_card.set_title("Big Loser pool")
            self.bl_chart.empty("No big-loser points recorded yet")
            return
        total = sum(1 for p in big_loser if p.big_loser_points)
        self.bl_card.set_title(
            f"Big Loser pool - top {len(scorers)} of {_plural(total, 'scorer')}"
            if total > len(scorers)
            else f"Big Loser pool - every scorer ({total})"
        )
        # The leader takes the accent; the rest a single quiet hue, so colour
        # marks the lead rather than repeating the bar length.
        best = scorers[0].big_loser_points
        colors = [
            self.palette.series_color(0) if p.big_loser_points == best
            else self.palette.series_color(2)
            for p in scorers
        ]
        self.bl_chart.plot(
            [p.display for p in scorers],
            [p.big_loser_points for p in scorers],
            xlabel="Big Loser points",
            colors=colors,
            value_format="{:g}",
            tooltips=[
                f"{p.display}\n{p.big_loser_points:g} points from "
                f"{_plural(p.big_loser_wins, 'correct pick')}\n"
                f"{_plural(len(p.weeks_played), 'week')} played"
                for p in scorers
            ],
        )

    def _update_bl_table(self, big_loser: list[Player]) -> None:
        # Per-player weeks, not the pool's longest run: dividing everyone's
        # points by the busiest player's week count understated anyone who
        # joined late or missed a week.
        averages = [
            p.big_loser_points / len(p.weeks_played) if p.weeks_played else 0.0
            for p in big_loser
        ]
        ranks = self._ranks([p.big_loser_points for p in big_loser])
        rows, tones = [], {}
        for r, (player, rank, average) in enumerate(zip(big_loser, ranks, averages)):
            rows.append([
                rank,
                player.display,
                f"{player.big_loser_points:g}",
                player.big_loser_wins,
                len(player.weeks_played),
                f"{average:.2f}" if player.weeks_played else self.NO_VALUE,
            ])
            if player.big_loser_points:
                tones[(r, 2)] = "good"

        model = TableModel(
            BL_HEADERS, rows,
            palette=self.palette,
            numeric_columns={0, 2, 3, 4, 5},
            sort_values={
                0: ranks,
                2: [p.big_loser_points for p in big_loser],
                5: averages,
            },
            tones=tones,
            bold_columns={1},
        )
        sort_column, ascending = self._current_sort(self.bl_table, len(BL_HEADERS))
        view, _ = make_table(
            model, stretch_column=1, sort_column=sort_column,
            ascending=ascending, row_height=27,
        )
        self.clear_layout(self.bl_box)
        self.bl_table = view
        self.bl_box.addWidget(view)

    def _update_suicide_table(self, players: list[Player]) -> None:
        # Status is a word plus a tone, never colour alone.
        ordered = sorted(players, key=lambda p: (not p.suicide_alive, p.display.lower()))
        rows, tones = [], {}
        for r, player in enumerate(ordered):
            latest = max(player.suicide_picks) if player.suicide_picks else None
            out_week = player.suicide_out_week
            rows.append([
                player.display,
                "Alive" if player.suicide_alive else "Eliminated",
                (player.suicide_picks.get(latest) or self.NO_VALUE) if latest else self.NO_VALUE,
                len(player.suicide_picks),
                # The model records when a player went out; showing it turns a
                # flat list of the eliminated into the order they fell in.
                f"Week {out_week}" if out_week else self.NO_VALUE,
            ])
            tones[(r, 1)] = "good" if player.suicide_alive else "bad"

        model = TableModel(
            SUICIDE_HEADERS, rows,
            palette=self.palette,
            numeric_columns={3},
            sort_values={
                1: [0 if p.suicide_alive else 1 for p in ordered],
                4: [p.suicide_out_week or 0 for p in ordered],
            },
            tones=tones,
            bold_columns={0},
        )
        sort_column, ascending = self._current_sort(
            self.suicide_table, len(SUICIDE_HEADERS), default=(1, True)
        )
        view, _ = make_table(
            model, stretch_column=0, sort_column=sort_column,
            ascending=ascending, row_height=27,
        )
        self.clear_layout(self.suicide_box)
        self.suicide_table = view
        self.suicide_box.addWidget(view)

    # ---- shared helpers -------------------------------------------------
    @staticmethod
    def _ranks(points: list[float]) -> list[int]:
        """Competition ranking: players level on points share a place."""
        ranks: list[int] = []
        rank, last = 0, None
        for i, value in enumerate(points, start=1):
            if value != last:
                rank, last = i, value
            ranks.append(rank)
        return ranks

    @staticmethod
    def _current_sort(
        view, columns: int, default: tuple[int, bool] = (0, True)
    ) -> tuple[int, bool]:
        """A table's current (column, ascending), or the default if unknown.

        Both tables here are rebuilt on every refresh, which resets the sort
        indicator, so the user's choice has to be carried across.
        """
        return current_sort(view, columns, default)
