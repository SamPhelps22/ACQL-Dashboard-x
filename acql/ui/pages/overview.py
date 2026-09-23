"""Season overview: the headline numbers, the leaderboard and the awards."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from ... import analytics, awards as awards_module
from ...awards import Award
from ...config import WEEKS_IN_SEASON
from ...models import Player, Season
from ..charts import BarChart, HistogramChart
from ..widgets import Banner, Card, ElidedLabel, StatTile, section, tile_grid
from .base import Page

LEADERBOARD_SIZE = 12
AWARD_COLUMNS = 4
LEADERBOARD_TITLE = "Leaderboard - season wins"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class AwardTile(QFrame):
    """One superlative: what it is, who holds it, and the number behind it.

    The winner's name is the largest thing on the tile, because that is what
    the pool reads. The number sits beside it in a chip tinted by tone, and
    the tone is never the only signal: the icon and the wording carry it too.
    """

    def __init__(self, award: Award) -> None:
        super().__init__()
        # Same raised surface as the headline tiles (see StatTile).
        self.setObjectName("AwardTile")
        self.setProperty("tone", award.tone if award.tone in ("good", "bad") else "")
        self.setMinimumHeight(104)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(5)

        # Icon plus label: the award never relies on colour to be identified.
        icon = QLabel(award.icon)
        icon.setObjectName("AwardIcon")
        title = QLabel(award.title)
        title.setObjectName("CardTitle")
        heading = QHBoxLayout()
        heading.setSpacing(7)
        heading.addWidget(icon)
        heading.addWidget(title, 1)
        layout.addLayout(heading)

        winner = ElidedLabel(award.winner)
        winner.setObjectName("AwardWinner")
        value = QLabel(award.value)
        value.setObjectName("AwardValue")
        value.setProperty("tone", self.property("tone"))
        headline = QHBoxLayout()
        headline.setSpacing(8)
        headline.addWidget(winner, 1)
        headline.addWidget(value, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(headline)

        detail = QLabel(award.detail)
        detail.setObjectName("AwardDetail")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        layout.addStretch(1)
        self.setToolTip(f"{award.title}\n{award.winner} - {award.value}\n{award.detail}")


class OverviewPage(Page):
    title = "Overview"
    subtitle = "Where the season stands right now"
    icon = "\N{TROPHY}"

    def build(self) -> None:
        self.header = section(self.title, self.subtitle)
        self.layout_.addWidget(self.header)

        self.banner = Banner()
        self.layout_.addWidget(self.banner)

        # ---- headline tiles ----
        # The leader is the one thing on this page worth extra room.
        self.tile_leader = StatTile("Season Leader")
        self.tile_week = StatTile("Current Week")
        self.tile_winnings = StatTile("Leader's Winnings")
        self.tile_players = StatTile("Players")
        self.tile_avg = StatTile("Pool Average")
        self.tile_lines = StatTile("Against the Line")
        self._tiles = (
            self.tile_leader, self.tile_week, self.tile_winnings,
            self.tile_players, self.tile_avg, self.tile_lines,
        )
        # Three to a row rather than six across: at six, every tile is too
        # narrow to hold its own number on a laptop screen.
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=3))

        # ---- leaderboard + distribution ----
        row = QHBoxLayout()
        row.setSpacing(12)

        self.leader_card = Card(LEADERBOARD_TITLE)
        self.leader_chart = BarChart(self.palette, height=3.9)
        self.leader_card.add(self.leader_chart, 1)
        row.addWidget(self.leader_card, 3)

        self.spread_card = Card("How the pool is bunched")
        self.spread_chart = HistogramChart(self.palette, height=3.9)
        self.spread_card.add(self.spread_chart, 1)
        row.addWidget(self.spread_card, 2)
        self.layout_.addLayout(row)

        # ---- awards ----
        # Tiles sit straight on the page rather than inside another card, so
        # the section doesn't become a card of cards.
        heading_row = QHBoxLayout()
        heading_row.setSpacing(8)
        self.awards_heading = QLabel("Season superlatives")
        self.awards_heading.setObjectName("CardTitle")
        self.awards_count = QLabel("")
        self.awards_count.setObjectName("Muted")
        heading_row.addWidget(self.awards_heading)
        heading_row.addWidget(self.awards_count)
        heading_row.addStretch(1)
        self.layout_.addLayout(heading_row)

        self.awards_grid = QGridLayout()
        self.awards_grid.setSpacing(12)
        for column in range(AWARD_COLUMNS):
            self.awards_grid.setColumnStretch(column, 1)
        self.layout_.addLayout(self.awards_grid)

    def restyle(self) -> None:
        """Follow a theme change without the window rebuilding this page."""
        for chart in (self.leader_chart, self.spread_chart):
            chart.set_palette(self.palette)
        # Tables bake the palette into their models, so a refresh rebuilds them.
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        self.banner.show_messages(season.warnings)

        order = season.ordered_players()
        if not order:
            self._show_empty()
            return

        self._update_tiles(season, order)
        self._update_charts(order)
        self._fill_awards(awards_module.compute(season))

    def _show_empty(self) -> None:
        for tile in self._tiles:
            tile.update_values(self.NO_VALUE, "No data loaded")
        self.leader_card.set_title(LEADERBOARD_TITLE)
        self.leader_chart.empty("Drop this week's files into data/, then press Refresh")
        self.spread_chart.empty()
        self._fill_awards([])

    def _update_tiles(self, season: Season, order: list[Player]) -> None:
        self._update_line_tile(season)
        leader = order[0]
        tied = [p for p in order if p.wins == leader.wins]
        record = f"{leader.wins}-{leader.losses}   {leader.pct:.3f}"
        if len(tied) > 1:
            note = f"tied with {_plural(len(tied) - 1, 'other')}"
        elif len(order) > 1 and leader.wins > order[1].wins:
            gap = leader.wins - order[1].wins
            note = f"{_plural(gap, 'win')} clear of {order[1].display}"
        else:
            note = ""
        self.tile_leader.update_values(leader.display, record + (f"\n{note}" if note else ""))

        finished = len(season.final_weeks())
        detail = f"{finished} of {WEEKS_IN_SEASON} weeks final"
        if season.provisional_weeks:
            detail += f" - week {season.provisional_weeks[0]} in progress"
        self.tile_week.update_values(
            f"Week {season.current_week}" if season.current_week else self.NO_VALUE,
            detail,
        )

        # The leader's own money, not the pool's: what they have won so far
        # and how that stands against their buy-in.
        net = leader.net(season.buy_in)
        cashed = sum(1 for v in leader.weekly_winnings.values() if v and v > 0)
        self.tile_winnings.update_values(
            self.money(leader.total_winnings),
            f"{self.money(net, signed=True)} net after the {self.money(season.buy_in)} buy-in"
            f"\ncashed in {_plural(cashed, 'week')}",
            "good" if net > 0 else ("bad" if net < 0 else ""),
        )

        alive = sum(1 for p in season.players.values() if p.suicide_alive)
        self.tile_players.update_values(
            str(len(season.players)),
            f"{alive} still alive in the suicide pool",
        )

        totals = [p.wins for p in order]
        average = sum(totals) / len(totals)
        above = sum(1 for t in totals if t > average)
        below = sum(1 for t in totals if t < average)
        level = len(totals) - above - below
        self.tile_avg.update_values(
            f"{average:.1f}",
            f"{above} above the line, {below} below"
            + (f", {level} on it" if level else ""),
        )

    def _update_line_tile(self, season: Season) -> None:
        """The pool's record on the games the commissioner puts a line on.

        The single most decisive number in this pool: the favourite has to
        win by MORE than the line, and the pool takes the favourite anyway.
        """
        dogs, decided = analytics.underdog_record(season)
        if not decided:
            self.tile_lines.update_values(self.NO_VALUE, "no lined games decided yet")
            self.tile_lines.hide_bar()
            return
        records = analytics.line_records(season)
        rate = analytics.pool_line_rate(records)
        self.tile_lines.update_values(
            f"{dogs}/{decided}",
            f"lined games the underdog took\nthe pool hits {self.pct(rate, 0)} on them",
            "good" if dogs * 2 > decided else "",
        )
        # Against a half-way marker, because the pool's own average is the
        # thing being beaten, not fifty per cent.
        self.tile_lines.show_bar(rate, 0.5, "bad" if rate < 0.5 else "good", self.palette)

    def _update_charts(self, order: list[Player]) -> None:
        top = order[:LEADERBOARD_SIZE]
        self.leader_card.set_title(
            f"Top {len(top)} - season wins"
            if len(order) > LEADERBOARD_SIZE
            else f"All {_plural(len(top), 'player')} - season wins"
        )

        # The leader takes the accent, the rest a single quiet hue - colour
        # here marks position, not identity.
        best = top[0].wins
        colors = [
            self.palette.series[0] if p.wins == best else self.palette.series[2]
            for p in top
        ]
        self.leader_chart.plot(
            [p.display for p in top],
            [p.wins for p in top],
            xlabel="Wins (regular + big loser)",
            colors=colors,
            tooltips=[
                f"{p.display}\n{p.wins}-{p.losses}   {p.pct:.3f}\n"
                f"{p.games_behind:.0f} game(s) back"
                for p in top
            ],
        )
        self.spread_chart.plot([p.wins for p in order], xlabel="Season wins")

    def _fill_awards(self, awards: list[Award]) -> None:
        self.clear_layout(self.awards_grid)
        self.awards_count.setText(str(len(awards)) if awards else "")
        if not awards:
            note = QLabel("Awards appear once a few weeks have been scored.")
            note.setObjectName("Muted")
            self.awards_grid.addWidget(note, 0, 0, 1, AWARD_COLUMNS)
            return
        for i, award in enumerate(awards):
            self.awards_grid.addWidget(AwardTile(award), i // AWARD_COLUMNS, i % AWARD_COLUMNS)