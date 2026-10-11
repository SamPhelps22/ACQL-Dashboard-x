"""Looking back: the patterns behind the scores."""

from __future__ import annotations

import statistics
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel

from ... import analytics, crowd, luck, patterns, picks, predictions
from ...predictions import display_team

from ..charts import BarChart, DivergingBarChart, HeatmapChart, LineChart, ScatterChart
from ..widgets import Card, StatTile, section, tile_grid
from .base import Page

H2H_PLAYERS = 12
FORM_TITLE = "Form against consistency"
LUCK_TITLE = "Luck meter - wins against what the picks deserved"
#: With more coaches than this, the chart shows the luckiest and unluckiest.
LUCK_EACH_END = 8
CROWD_TITLE = "Following the crowd, against what it scores"
# Top-left, top-right, bottom-left, bottom-right - x is how chalky, y is the
# average score, so the left-hand side is where a week can be won outright.
CROWD_QUADRANTS = (
    "Contrarian and winning", "Chalky and winning",
    "Contrarian and losing", "Chalky and losing",
)
CHAOS_TITLE = "Chaos rating - how wild each week was against the lines"
MOVE_TITLE = "Who beat the line move"
SPOTS_TITLE = "Blind spots across the pool"
#: A team needs this many of the pool's picks before its record is quoted.
TEAM_PICKS = 20
QUADRANTS = ("Strong and steady", "Strong but streaky", "Steady, but short", "Feast or famine")


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class InsightsPage(Page):
    title = "The Pool"
    subtitle = "What the season's numbers say about the pool - and about luck"
    icon = "\N{LEFT-POINTING MAGNIFYING GLASS}"

    # ---- build ---------------------------------------------------------
    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))

        self.tile_home = StatTile("Home Teams")
        self.tile_momentum = StatTile("Momentum")
        self.tile_hard = StatTile("Hardest Week")
        self.tile_easy = StatTile("Easiest Week")
        self.tile_commish = StatTile("The Commissioner's Lines")
        self.tile_chalk = StatTile("Going With the Crowd")
        self._tiles = (
            self.tile_home, self.tile_momentum, self.tile_hard,
            self.tile_easy, self.tile_commish, self.tile_chalk,
        )
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=3))

        row = QHBoxLayout()
        row.setSpacing(12)
        self.form_card = Card(FORM_TITLE)
        self.form_chart = ScatterChart(self.palette, height=4.2)
        self.form_card.add(self.form_chart, 1)
        self.form_note = QLabel(
            "Up is more wins a week; right is bigger swings between weeks. "
            "The dashed lines are the pool's middle."
        )
        self.form_note.setObjectName("Muted")
        self.form_note.setWordWrap(True)
        self.form_card.add(self.form_note)
        row.addWidget(self.form_card, 1, Qt.AlignmentFlag.AlignTop)

        self.weeks_card = Card("Week by week - the best, the average and the worst")
        self.weeks_chart = LineChart(self.palette, height=4.2)
        self.weeks_card.add(self.weeks_chart, 1)
        row.addWidget(self.weeks_card, 1, Qt.AlignmentFlag.AlignTop)
        self.layout_.addLayout(row)

        self.crowd_card = Card(CROWD_TITLE)
        self.crowd_chart = ScatterChart(self.palette, height=3.6)
        self.crowd_card.add(self.crowd_chart, 1)
        self.layout_.addWidget(self.crowd_card, 1)

        # What the pick sheets have taught the app about this pool - the
        # picture the win-the-week card plans against.
        self.habits_card = Card("How this pool picks")
        self.habits_label = QLabel("")
        self.habits_label.setWordWrap(True)
        self.habits_label.setTextFormat(Qt.TextFormat.RichText)
        self.habits_card.add(self.habits_label)
        self.habits_note = QLabel("")
        self.habits_note.setObjectName("Muted")
        self.habits_note.setWordWrap(True)
        self.habits_card.add(self.habits_note)
        self.layout_.addWidget(self.habits_card)

        # Wins against what the picks deserved: who is good, who is lucky.
        self.luck_card = Card(LUCK_TITLE)
        self.luck_chart = DivergingBarChart(self.palette, height=4.4)
        self.luck_card.add(self.luck_chart, 1)
        self.luck_note = QLabel("")
        self.luck_note.setObjectName("Muted")
        self.luck_note.setWordWrap(True)
        self.luck_card.add(self.luck_note)
        self.layout_.addWidget(self.luck_card)

        # How surprising each week was, and the pool's season weighed by it.
        self.chaos_card = Card(CHAOS_TITLE)
        self.chaos_chart = BarChart(self.palette, height=3.0)
        self.chaos_card.add(self.chaos_chart, 1)
        self.chaos_note = QLabel("")
        self.chaos_note.setObjectName("Muted")
        self.chaos_note.setWordWrap(True)
        self.chaos_card.add(self.chaos_note)
        self.layout_.addWidget(self.chaos_card)

        # Picks on the side the market moved toward before kickoff: skill
        # that shows before a ball is thrown.
        self.move_card = Card(MOVE_TITLE)
        self.move_chart = DivergingBarChart(self.palette, height=4.4)
        self.move_card.add(self.move_chart, 1)
        self.move_note = QLabel("")
        self.move_note.setObjectName("Muted")
        self.move_note.setWordWrap(True)
        self.move_card.add(self.move_note)
        self.layout_.addWidget(self.move_card)

        self.spots_card = Card(SPOTS_TITLE)
        self.spots_label = QLabel("")
        self.spots_label.setWordWrap(True)
        self.spots_label.setTextFormat(Qt.TextFormat.RichText)
        self.spots_card.add(self.spots_label)
        self.spots_note = QLabel(
            "Each coach's own blind spots and strong suits are on the Player page. "
            "Every split there is measured against how the rest of the pool did in "
            "the same games, so a hard week or a trap line counts against nobody."
        )
        self.spots_note.setObjectName("Muted")
        self.spots_note.setWordWrap(True)
        self.spots_card.add(self.spots_note)
        self.layout_.addWidget(self.spots_card)

        self.h2h_card = Card("Head to head")
        self.h2h_chart = HeatmapChart(self.palette, height=6.0)
        self.h2h_card.add(self.h2h_chart, 1)
        self.h2h_note = QLabel(
            "Read across a row: the share of weeks that player outscored the "
            "player in each column, counting ties as half. Blue beats, red "
            "loses, grey is even."
        )
        self.h2h_note.setObjectName("Muted")
        self.h2h_note.setWordWrap(True)
        self.h2h_card.add(self.h2h_note)
        self.layout_.addWidget(self.h2h_card, 2)

    def restyle(self) -> None:
        for chart in (self.form_chart, self.weeks_chart, self.crowd_chart,
                      self.h2h_chart, self.luck_chart, self.chaos_chart, self.move_chart):
            chart.set_palette(self.palette)
        self.refresh_now()

    # ---- refresh -------------------------------------------------------
    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()

        self._update_home(season)
        self._update_momentum(season)
        profiles = analytics.week_profiles(season)
        self._update_week_tiles(profiles)
        self._update_weeks_chart(profiles)
        self._update_commish(season)
        self._update_chalk(season)
        self._update_form(season)
        self._update_h2h(season)
        self._update_crowd_chart(season)
        self._update_habits(season)
        self._update_luck(season)
        report = patterns.report(season)
        self._update_chaos(report)
        self._update_moves(report)
        self._update_spots(report)

    # ---- chaos, line moves, blind spots (patterns.py) --------------------------
    def _update_chaos(self, report: patterns.Report) -> None:
        weeks = report.chaos
        if not weeks:
            self.chaos_card.set_title(CHAOS_TITLE)
            self.chaos_chart.empty("Appears once a week is final and has its betting lines")
            self.chaos_note.setText("")
            return
        ramp = self.palette.sequential
        self.chaos_chart.plot(
            [f"Week {c.week}  \u00b7  {c.label}" for c in weeks],
            [c.rating for c in weeks],
            xlabel="Chaos rating: 0 every favourite came in, 10 a week like it comes once in years",
            colors=[ramp[min(len(ramp) - 1, int(c.rating / 10 * len(ramp)))] for c in weeks],
            value_format="{:.1f}",
            tooltips=[
                f"Week {c.week}: {c.rating:.1f} - {c.label}\n"
                f"{_plural(c.upsets, 'upset')}, the lines expected {c.expected:.1f}\n"
                + (f"Biggest upset: {c.biggest_text}\n" if c.biggest else "")
                + f"The pool averaged {c.pool_average:.1f}"
                for c in weeks
            ],
        )
        wild = max(weeks, key=lambda c: (c.rating, c.week))
        text = (
            f"Wildest so far: week {wild.week}, {wild.rating:.1f} - {_plural(wild.upsets, 'upset')} "
            f"where the lines expected {wild.expected:.1f}"
        )
        if wild.biggest:
            text += f"; the biggest, {wild.biggest_text}"
        text += f". The pool averaged {wild.pool_average:.1f} that week."
        climbers = sorted(report.adjusted, key=lambda a: (a.rank - a.actual_rank, a.name))
        if climbers and climbers[0].actual_rank - climbers[0].rank >= 2:
            up = climbers[0]
            text += (
                f" With every week weighed by how hard it was, {up.name} climbs most: "
                f"{self.ordinal(up.actual_rank)} as scored, {self.ordinal(up.rank)} adjusted."
            )
        storm = [a for a in report.adjusted if a.wild is not None]
        if storm:
            best = max(storm, key=lambda a: (a.wild, a.name))
            text += f" Best in wild weeks: {best.name}, {best.wild:+.1f} a week against the pool."
        self.chaos_card.set_title(f"{CHAOS_TITLE} - {_plural(len(weeks), 'week')} rated")
        self.chaos_note.setText(text)

    def _update_moves(self, report: patterns.Report) -> None:
        moves = report.moves
        if not moves:
            self.move_card.set_title(MOVE_TITLE)
            self.move_chart.empty("Appears once a graded week has a predictions file - it holds the opening lines")
            self.move_note.setText("")
            return
        shown = moves if len(moves) <= 2 * LUCK_EACH_END else moves[:LUCK_EACH_END] + moves[-LUCK_EACH_END:]
        most = max(m.moved for m in moves)
        self.move_card.set_title(
            f"{MOVE_TITLE} - {_plural(most, 'game')} where the line moved {patterns.MIN_MOVE:g}+ points"
            + ("" if len(shown) == len(moves) else f" (best and worst {LUCK_EACH_END})")
        )
        self.move_chart.plot(
            [m.name for m in shown],
            [m.gained for m in shown],
            xlabel="Wins of value gained between the opening line and kickoff",
            value_format=lambda v: f"{v:+.2f}",
            tooltips=[
                f"{m.name}\nOn the side the line moved toward {m.with_move} of {m.moved} times\n"
                f"{m.came_in} of those came in\n"
                f"{m.points:+.1f} points of movement toward their picks"
                for m in shown
            ],
        )
        steam = report.steam
        text = (
            "Between the opening line and kickoff the market moves on injury news and money. "
            "Picks that keep landing on the side it moved toward read the games the way the "
            "market came to - decided before a ball is thrown, so it is skill, not luck. "
            "Each bar is the win chance its picks gained between the two lines, added up."
        )
        if steam.games:
            text += (
                f" When a line moved {patterns.STEAM_MOVE:g}+ points, the side it moved to came in "
                f"{steam.came_in} of {steam.games} times."
            )
        self.move_note.setText(text)

    def _update_spots(self, report: patterns.Report) -> None:
        teams = [t for t in report.teams if t.picks >= TEAM_PICKS]
        if not report.spots or not teams:
            self.spots_label.setText("Appears once a week has results and its picks.")
            return
        worst, best = teams[:3], teams[::-1][:3]
        shared_blind = Counter(s.label for b in report.spots.values() for s in b.worst).most_common(1)
        shared_strong = Counter(s.label for b in report.spots.values() for s in b.best).most_common(1)
        rows = [
            "<b>Teams the pool reads worst:</b> " + ", ".join(f"{t.label} {t.record}" for t in worst),
            "<b>...and best:</b> " + ", ".join(f"{t.label} {t.record}" for t in best),
        ]
        total = len(report.spots)
        if shared_blind:
            label, count = shared_blind[0]
            rows.append(f"<b>The most shared blind spot:</b> {label[:1].lower()}{label[1:]} - {count} of {total} coaches")
        if shared_strong:
            label, count = shared_strong[0]
            rows.append(f"<b>The most shared strong suit:</b> {label[:1].lower()}{label[1:]} - {count} of {total} coaches")
        self.spots_label.setText("<br>".join(f"\u2022 {row}" for row in rows))

    @staticmethod
    def ordinal(n: int) -> str:
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def _update_luck(self, season) -> None:
        lines = luck.season_luck(season)
        if not lines:
            self.luck_card.set_title(LUCK_TITLE)
            self.luck_chart.empty("Appears once a week has results and its betting lines")
            self.luck_note.setText("")
            return
        average = luck.pool_expected(lines)
        shown = lines if len(lines) <= 2 * LUCK_EACH_END else (
            lines[:LUCK_EACH_END] + lines[-LUCK_EACH_END:]
        )
        self.luck_card.set_title(
            LUCK_TITLE if len(shown) == len(lines)
            else f"{LUCK_TITLE} (luckiest and unluckiest {LUCK_EACH_END})"
        )
        self.luck_chart.plot(
            [l.name for l in shown],
            [l.luck for l in shown],
            xlabel="Wins above (or below) what their picks deserved",
            value_format=lambda v: f"{v:+.1f}",
            tooltips=[
                f"{l.name}\nWon {l.wins} of {l.picks} priced picks\n"
                f"Their picks deserved {l.expected:.1f}\n"
                f"Luck {l.luck:+.1f}  \u00b7  pick quality {l.expected - average:+.1f} vs the average coach"
                for l in shown
            ],
        )
        best = max(lines, key=lambda l: (l.expected, l.name))
        pool_luck = sum(l.luck for l in lines) / len(lines)
        self.luck_note.setText(
            "Every pick had a chance of landing - the betting line says how likely, "
            "and the pool's line rule says what counts. Their sum is what a coach's "
            "picks deserved; the rest is luck, which evens out, while good picks last. "
            f"Best picks so far, luck aside: {best.name}, "
            f"{best.expected - average:+.1f} deserved wins above the average coach. "
            f"The whole pool is running {pool_luck:+.1f} a coach - "
            + ("favourites have come in more often than the lines said."
               if pool_luck > 0.5 else
               "the lines have been about right." if pool_luck > -0.5 else
               "upsets have come in more often than the lines said.")
        )

    def _update_habits(self, season) -> None:
        obs = crowd.observations(season)
        if not obs:
            self.habits_card.set_title("How this pool picks")
            self.habits_label.setText(
                "Appears once a week's pick sheet and that week's betting lines "
                "are both loaded - it learns from what the pool actually did."
            )
            self.habits_note.setText("")
            return
        learned = crowd.model(season)
        weeks = sorted({o.week for o in obs})
        self.habits_card.set_title(
            f"How this pool picks - learned from {len(obs)} games over "
            f"{len(weeks)} week{'s' if len(weeks) != 1 else ''}"
            + (f", and {learned.older} from older seasons' sheets" if learned.older else "")
        )
        lines = learned.habits()
        self.habits_label.setText(
            "<br>".join(f"\u2022 {line}" for line in lines) if lines
            else "Nothing stands out yet - this pool picks like a typical one."
        )
        tested = crowd.check(obs, crowd.older_sheets(season))
        using = learned.games >= crowd.MINIMUM_GAMES
        note = (
            "The win-the-week card plans against these habits"
            if using else
            f"The card switches to these habits after {crowd.MINIMUM_GAMES} games"
        )
        if tested:
            note += (
                f". Predicting a week it had not seen, it missed the pool's "
                f"real split by {tested['learned']:.0%} a game on average, against "
                f"{tested['usual']:.0%} for a typical pool's habits"
            )
        note += (
            ". Each habit starts at 'like any pool' and moves only as far as "
            "the sheets push it, so it firms up as the season goes."
        )
        self.habits_note.setText(note)

    # ---- the pool's own habits ------------------------------------------
    def _update_commish(self, season) -> None:
        """How far above the betting line the commissioner sets his numbers.

        It decides almost every lined game: the favourite has to win by at
        least the line, so a number set above the market's makes the
        underdog the better side before a ball is thrown.
        """
        gaps = []
        for number, sheet in predictions.stored_weeks().items():
            week = season.weeks.get(number)
            if week is None:
                continue
            found = predictions.match_games(
                sorted(week.games, key=lambda g: g.index), sheet
            ).by_game
            for game in week.games:
                line = getattr(game, "line", None)
                forecast = found.get(game.index)
                if line is None or forecast is None or forecast.market is None:
                    continue
                margin = predictions.home_margin(game, forecast, forecast.market)
                if margin is not None:
                    gaps.append(line - abs(margin))
        if not gaps:
            self.tile_commish.update_values(
                self.NO_VALUE, "needs a predictions file for a week with pool lines"
            )
            return
        middle = statistics.median(gaps)
        self.tile_commish.update_values(
            f"{middle:+.1f}",
            f"points above the betting line, over {_plural(len(gaps), 'lined game')}\n"
            f"at or above it, the underdog is the better side",
            "bad" if middle >= 0 else "good",
        )

    def _update_chalk(self, season) -> None:
        """How much this pool follows the crowd, and who doesn't."""
        sheets = picks.load_all()
        everyone: dict[str, list[float]] = {}
        for sheet in sheets.values():
            for coach, value in picks.chalk(sheet).items():
                everyone.setdefault(coach, []).append(value)
        if not everyone:
            self.tile_chalk.update_values(
                self.NO_VALUE, "load a pick sheet to measure it"
            )
            self.tile_chalk.hide_bar()
            return
        roster = {
            "".join(ch for ch in p.display.casefold() if ch.isalnum())
            for p in season.players.values()
        }
        if roster:
            everyone = {
                c: v for c, v in everyone.items()
                if "".join(ch for ch in c.casefold() if ch.isalnum()) in roster
            }
        if not everyone:
            self.tile_chalk.update_values(
                self.NO_VALUE, "none of the loaded sheets' coaches are in this pool"
            )
            self.tile_chalk.hide_bar()
            return
        averages = {c: sum(v) / len(v) for c, v in everyone.items()}
        pool = sum(averages.values()) / len(averages)
        odd_one = min(averages, key=averages.get)
        self.tile_chalk.update_values(
            self.pct(pool, 0),
            f"of the pool's picks are on the popular side\n"
            f"most contrarian: {odd_one} at {self.pct(averages[odd_one], 0)}",
        )
        self.tile_chalk.show_bar(pool, averages[odd_one], "warning", self.palette)

    def _update_crowd_chart(self, season) -> None:
        """Each coach's agreement with the pool, against what they score.

        The question the whole app circles: does following the crowd help?
        It helps you be right - and it is also why most of the pool finishes
        within a game of the average, where no money is.
        """
        sheets = picks.load_all()
        if not sheets:
            self.crowd_card.set_title(CROWD_TITLE)
            self.crowd_chart.empty("Load a pick sheet and this appears")
            return
        totals: dict[str, list[float]] = {}
        for sheet in sheets.values():
            for coach, value in picks.chalk(sheet).items():
                totals.setdefault(" ".join(coach.split()).casefold(), []).append(value)
        points = []
        for player in season.players.values():
            key = " ".join(player.display.split()).casefold()
            history = [v for v in player.weekly_wins.values() if v is not None]
            if key in totals and history:
                points.append((
                    player.display,
                    sum(totals[key]) / len(totals[key]),
                    sum(history) / len(history),
                ))
        if len(points) < 4:
            self.crowd_card.set_title(CROWD_TITLE)
            self.crowd_chart.empty("Not enough coaches with both a sheet and a score")
            return
        mid_x = statistics.median(x for _, x, _ in points)
        mid_y = statistics.median(y for _, _, y in points)
        leader = season.leader()
        self.crowd_card.set_title(
            f"{CROWD_TITLE} - {len(points)} coaches, the pool agrees "
            f"{self.pct(mid_x, 0)} of the time"
        )
        self.crowd_chart.plot(
            points,
            xlabel="Share of picks on the popular side",
            ylabel="Average wins a week",
            quadrants=(mid_x, mid_y),
            quadrant_labels=CROWD_QUADRANTS,
            highlight=leader.display if leader else None,
            tooltips=[
                f"{name}\nwith the crowd on {self.pct(x, 0)} of picks\n"
                f"averages {y:.1f} wins a week"
                for name, x, y in points
            ],
        )

    # ---- tiles -----------------------------------------------------------
    def _update_home(self, season) -> None:
        home, decided = analytics.home_record(season)
        if not decided:
            self.tile_home.update_values(self.NO_VALUE, "No results entered yet")
            return
        rate = home / decided
        # 9 home wins in 16 games is 56%, but so is a run of coin flips; say
        # nothing about an edge until there are enough games to mean one.
        if decided < analytics.MIN_HOME_GAMES:
            lean = "too few games yet to call an edge"
        elif rate >= 0.55:
            lean = "home teams have the edge"
        elif rate <= 0.45:
            lean = "road teams have the edge"
        else:
            lean = "no real home edge"
        self.tile_home.update_values(
            self.pct(rate, 0), f"won {home} of {_plural(decided, 'game')}\n{lean}",
        )

    def _update_momentum(self, season) -> None:
        result = analytics.momentum(season)
        if result is None:
            self.tile_momentum.update_values(
                self.NO_VALUE, "Needs a few more weeks of results to measure",
            )
            return
        r, pairs = result
        self.tile_momentum.update_values(
            f"r = {r:+.2f}",
            f"{analytics.describe_momentum(r).capitalize()}\n"
            f"beating the pool one week against the next, {_plural(pairs, 'pair')}",
            "good" if r >= 0.1 else "",
        )

    def _update_week_tiles(self, profiles: list[analytics.WeekProfile]) -> None:
        if not profiles:
            for tile in (self.tile_hard, self.tile_easy):
                tile.update_values(self.NO_VALUE, "No final weeks yet")
            return
        hard = min(profiles, key=lambda w: (w.average, w.week))
        easy = max(profiles, key=lambda w: (w.average, -w.week))
        season_avg = statistics.fmean(w.average for w in profiles)
        if len(profiles) < 2:
            only = profiles[0]
            for tile in (self.tile_hard, self.tile_easy):
                tile.update_values(f"Week {only.week}", "only one final week so far")
            return
        self.tile_hard.update_values(
            f"Week {hard.week}",
            f"pool averaged {hard.average:.1f}, "
            f"{season_avg - hard.average:.1f} under the season norm\n"
            f"best score that week: {hard.best}",
            "bad",
        )
        self.tile_easy.update_values(
            f"Week {easy.week}",
            f"pool averaged {easy.average:.1f}, "
            f"{easy.average - season_avg:.1f} over the season norm\n"
            f"best score that week: {easy.best}",
            "good",
        )

    # ---- charts ----------------------------------------------------------
    def _update_weeks_chart(self, profiles: list[analytics.WeekProfile]) -> None:
        if len(profiles) < 2:
            self.weeks_chart.empty("Appears once two weeks are final")
            return
        weeks = [w.week for w in profiles]
        # The average is the line the other two are read against, so it is
        # the dashed grey reference rather than a third colour - which would
        # otherwise land green on "Worst" and read as good.
        self.weeks_chart.plot(
            weeks,
            [
                ("Best", [w.best for w in profiles]),
                ("Worst", [w.worst for w in profiles]),
            ],
            ylabel="Wins",
            reference=("Average", [round(w.average, 1) for w in profiles]),
            direct_label=True,
        )

    def _update_form(self, season) -> None:
        points = analytics.form_profile(season)
        if len(points) < 4:
            self.form_card.set_title(FORM_TITLE)
            self.form_chart.empty("Appears once players have three weeks each")
            return
        mid_spread = statistics.median(f.spread for f in points)
        mid_average = statistics.median(f.average for f in points)
        leader = season.leader()
        steady_strong = sum(
            1 for f in points if f.average >= mid_average and f.spread <= mid_spread
        )
        self.form_card.set_title(
            f"{FORM_TITLE} - {steady_strong} of {len(points)} strong and steady"
        )
        self.form_chart.plot(
            [(f.player.display, f.spread, f.average) for f in points],
            xlabel="Week-to-week swing (± wins)",
            ylabel="Average wins a week",
            quadrants=(mid_spread, mid_average),
            quadrant_labels=QUADRANTS,
            highlight=leader.display if leader else None,
            tooltips=[
                f"{f.player.display}\n"
                f"averages {f.average:.1f} a week, give or take {f.spread:.1f}\n"
                f"over {_plural(f.weeks, 'week')}"
                for f in points
            ],
        )

    def _update_h2h(self, season) -> None:
        weeks = season.final_weeks()
        order = season.ordered_players()[:H2H_PLAYERS]
        if len(order) < 2 or len(weeks) < 2:
            self.h2h_card.set_title("Head to head")
            self.h2h_chart.empty("Appears once two weeks are final")
            return
        grid = analytics.head_to_head(order, weeks)
        values = [
            [None if m is None or not m.shared else round(m.share * 100) for m in row]
            for row in grid
        ]
        names = [p.display for p in order]
        total = len(season.players)
        self.h2h_card.set_title(
            "Head to head - "
            + (f"top {len(order)} in the standings" if total > len(order) else "every player")
        )

        def tooltip(row_name, col_name, value, grid=grid, names=names):
            if value is None:
                return f"{row_name}" if row_name == col_name else f"{row_name} v {col_name}: no shared weeks"
            m = grid[names.index(row_name)][names.index(col_name)]
            losses = m.shared - m.wins - m.ties
            return (
                f"{row_name} v {col_name}\n"
                f"{m.wins}-{losses}" + (f"-{m.ties}" if m.ties else "")
                + f" over {_plural(m.shared, 'shared week')}\n"
                f"{row_name} won {self.pct(m.share, 0)}"
            )

        self.h2h_chart.plot(
            names, names, values,
            vmin=0, vmax=100, center=50,
            cell_text=len(order) <= 14, cell_format="{:.0f}",
            key_label="% of shared weeks the row player won",
            tooltip_fn=tooltip, tick_rotation=40,
        )
