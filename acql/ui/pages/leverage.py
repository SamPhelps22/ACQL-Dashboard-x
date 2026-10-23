"""Leverage: what each of this week's picks does for your season (pool/leverage.py works it out)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout

from ...places import LEVERAGE as title_
from ...pool import leverage
from ...version import MODEL_NAME
from ..widgets import Card, StatTile, TableModel, make_table, section, tile_grid
from .base import Page

GAME_HEADERS = ["Game", f"{MODEL_NAME} takes", "Chance", "Pool on it", "Other side: title", "Other side: top 3",
                "Leader", "Chase card"]
(COL_GAME, COL_PICK, COL_CHANCE, COL_POOL, COL_TITLE, COL_TOP3, COL_LEADER, COL_CHASE) = range(8)
RIVAL_HEADERS = ["Coach", "Wins", "Gap", "Title odds", "Games on the other side"]
#: A flip that moves the odds less than this (in points of 0..1) reads as "no difference".
NOTICE = 0.0005


def _pts(value: float) -> str:
    """Points of odds, signed: "+0.4 pts", "−1.2 pts"."""
    pts = value * 100
    if abs(pts) < NOTICE * 100:
        return "0.0 pts"
    sign = "+" if pts > 0 else "−"
    return f"{sign}{abs(pts):.1f} pts"


def _odds(value: float) -> str:
    return "<0.1%" if 0 < value < 0.001 else f"{value:.1%}"


class LeveragePage(Page):
    title = title_
    subtitle = ("What each pick this week does for your chance of winning the season - "
                "where the coaches above you are likely to be, and you're not")
    icon = "\N{SCALES}"

    def build(self) -> None:
        self.layout_.addWidget(section(self.title, self.subtitle))
        self.tile_title = StatTile("Title Odds")
        self.tile_top3 = StatTile("Top-3 Odds")
        self.tile_chase = StatTile("Chase Card")
        self.tile_lever = StatTile("Biggest Lever")
        self._tiles = (self.tile_title, self.tile_top3, self.tile_chase, self.tile_lever)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.games_card = Card("Every game, by what it does for your season")
        self.games_box = QVBoxLayout()
        self.games_card.body().addLayout(self.games_box)
        self.games_note = self._note()
        self.games_card.add(self.games_note)
        self.layout_.addWidget(self.games_card)

        self.rivals_card = Card("Who to watch")
        self.rivals_box = QVBoxLayout()
        self.rivals_card.body().addLayout(self.rivals_box)
        self.rivals_note = self._note()
        self.rivals_card.add(self.rivals_note)
        self.layout_.addWidget(self.rivals_card)

    @staticmethod
    def _note() -> QLabel:
        label = QLabel("")
        label.setObjectName("Muted")
        label.setWordWrap(True)
        return label

    def restyle(self) -> None:
        self.refresh_now()

    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        found = leverage.report(season)
        self.clear_layout(self.games_box)
        self.clear_layout(self.rivals_box)
        if found is None:
            for tile in self._tiles:
                tile.update_values(self.NO_VALUE, "once the week has priced games and you're in the standings")
            self.games_note.setText("Nothing to weigh yet: the week needs betting lines (Update lines on My picks), "
                                    "and the season needs a scored week.")
            self.rivals_note.setText("")
            return
        self._tiles_for(found)
        self._games_for(found)
        self._rivals_for(found)

    # ---- the tiles ---------------------------------------------------------------------------
    def _tiles_for(self, r: leverage.Report) -> None:
        leader = next((v for v in r.rivals if v.gap > 0), None)
        behind = max((v.gap for v in r.rivals), default=0)
        where = (f"{r.wins} wins, {self._ordinal(r.place)}"
                 + (f", {behind} behind {leader.name}" if leader and behind > 0 else ", in front"))
        self.tile_title.update_values(_odds(r.title), f"with {MODEL_NAME}'s card\n{where}",
                                      "good" if r.place == 1 else "")
        self.tile_top3.update_values(_odds(r.top3), f"with {MODEL_NAME}'s card\n{r.weeks_left} weeks to play, this one included")
        aim = leverage.AIM_NAMES[r.aim]
        if not r.flips:
            self.tile_chase.update_values(
                f"{MODEL_NAME}'s card",
                f"no game turned over adds anything to your odds of {aim}\n"
                + ("with this many weeks left, steady points are worth more" if r.weeks_left > 6 else
                   "the coaches above you are already on your sides"))
        else:
            cost = r.card_hits - r.chase_hits
            names = ", ".join(p.other for p in r.flips)
            self.tile_chase.update_values(
                f"Turn {len(r.flips)}",
                f"{names}: {_pts(r.gain)} on {aim}\nfor {cost:.1f} fewer games expected right",
                "good" if r.gain >= 0.005 else "")
        open_games = [p for p in r.picks if not p.decided]
        if open_games:
            lever = max(open_games, key=lambda p: abs(p.worth(r.aim)))
            self.tile_lever.update_values(
                lever.label,
                f"the other side would be {_pts(lever.worth(r.aim))} on {aim}\n"
                f"{MODEL_NAME} takes {lever.pick} at {lever.chance:.0%}; the pool is {lever.crowd:.0%} on it")
        else:
            self.tile_lever.update_values("None", "every game this week is already decided")

    @staticmethod
    def _ordinal(n: int) -> str:
        return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"

    # ---- the games ---------------------------------------------------------------------------
    def _games_for(self, r: leverage.Report) -> None:
        leader = next((v.name for v in r.rivals if v.gap > 0), r.rivals[0].name if r.rivals else "")
        # The cheapest flips first: those are the ones worth a thought.
        games = sorted(r.picks, key=lambda p: (p.decided, -p.worth(r.aim)))
        rows, tones, tips = [], {}, {}
        for i, p in enumerate(games):
            on_other = p.split.get(leader)
            rows.append([
                p.label, p.pick, f"{p.chance:.0%}" if not p.decided else ("won" if p.chance else "lost"),
                f"{p.crowd:.0%}",
                "played" if p.decided else _pts(p.title_flipped - p.title),
                "played" if p.decided else _pts(p.top3_flipped - p.top3),
                "" if on_other is None or p.decided else
                ("other side" if on_other == 1 else "same side") if r.field_known else f"{on_other:.0%} other",
                p.other if p.in_chase else "",
            ])
            for col, worth in ((COL_TITLE, p.title_flipped - p.title), (COL_TOP3, p.top3_flipped - p.top3)):
                if not p.decided:
                    tones[(i, col)] = "good" if worth >= NOTICE else "muted" if abs(worth) < 0.002 else ""
            if p.in_chase:
                tones[(i, COL_CHASE)] = "good"
            tips[(i, COL_POOL)] = ("Counted off this week's pick sheet" if r.field_known
                                   else "Expected, from how this pool usually splits on a game like it")
            tips[(i, COL_TITLE)] = f"Your title odds with {p.other} instead, the rest of the card kept: " \
                                   f"{_odds(p.title_flipped)} (now {_odds(p.title)})"
            if on_other is not None:
                tips[(i, COL_LEADER)] = (f"{leader} took {p.other}" if on_other == 1 else
                                         f"{leader} took {p.pick}" if on_other == 0 else
                                         f"Chance {leader} takes {p.other}")
        model = TableModel(
            GAME_HEADERS, rows, palette=self.palette,
            numeric_columns={COL_CHANCE, COL_POOL, COL_TITLE, COL_TOP3, COL_LEADER},
            sort_values={COL_TITLE: [p.title_flipped - p.title for p in games],
                         COL_TOP3: [p.top3_flipped - p.top3 for p in games],
                         COL_CHANCE: [p.chance for p in games], COL_POOL: [p.crowd for p in games],
                         COL_LEADER: [p.split.get(leader, -1) for p in games]},
            tones=tones, tooltips=tips, bold_columns={COL_PICK},
        )
        view, _ = make_table(model, stretch_column=COL_GAME, row_height=28)
        self.games_box.addWidget(view)
        self.games_card.set_title(f"Every game, by what it does for your season - week {r.week}")
        source = ("everyone's real picks from this week's sheet" if r.field_known
                  else "everyone else's picks drawn from how this pool usually splits")
        self.games_note.setText(
            f"The two 'Other side' columns are how your odds change if you take the other team in that game "
            f"and keep the rest of {MODEL_NAME}'s card. A game where you and the leader are on the same side "
            f"can't change the gap between you, however it goes. Worked out from {r.simulations:,} simulated "
            f"seasons: this week from {MODEL_NAME}'s chances and {source}, the weeks after from each coach's own "
            f"scores (as Projections does). The chase card turns over whichever game helps most, one at a time, "
            f"until none does. It never changes your card.")

    # ---- the rivals --------------------------------------------------------------------------
    def _rivals_for(self, r: leverage.Report) -> None:
        rows, tones = [], {}
        for i, v in enumerate(r.rivals):
            gap = "level" if v.gap == 0 else f"{v.gap} ahead" if v.gap > 0 else f"{-v.gap} behind"
            rows.append([v.name, str(v.wins), gap, _odds(v.title), f"{v.differ:.1f}"])
            tones[(i, 2)] = "bad" if v.gap > 0 else "good" if v.gap < 0 else ""
        model = TableModel(RIVAL_HEADERS, rows, palette=self.palette, numeric_columns={1, 3, 4},
                           sort_values={1: [v.wins for v in r.rivals], 2: [v.gap for v in r.rivals],
                                        3: [v.title for v in r.rivals], 4: [v.differ for v in r.rivals]},
                           tones=tones, bold_columns={0})
        view, _ = make_table(model, stretch_column=0, row_height=28)
        self.rivals_box.addWidget(view)
        self.rivals_note.setText(
            f"The coaches most likely to take the title from you, with your card as {MODEL_NAME}'s. "
            f"'Games on the other side' is how many of this week's picks they're "
            + ("on the other side of yours, from the pick sheet." if r.field_known else
               "expected to be on the other side of yours. Only those games can change the gap."))
