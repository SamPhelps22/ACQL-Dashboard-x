"""Domain model for the ACQL pool.

These dataclasses are the contract between the parsers (acql.sources) and the
UI. Parsers never hand raw spreadsheet rows to a widget; they build these.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .config import BIG_LOSER_PICKS


@dataclass
class Game:
    """One matchup on a week's slate."""

    index: int                      # 1-based position on the slate
    home: str = ""
    away: str = ""
    winner: str = ""                # blank until the result is entered
    is_big_loser: bool = False

    @property
    def label(self) -> str:
        if self.home and self.away:
            return f"{self.away} @ {self.home}"
        return self.home or self.away or f"Game {self.index}"

    @property
    def played(self) -> bool:
        return bool(str(self.winner).strip())

    def winner_is_home(self) -> bool | None:
        if not self.played:
            return None
        w = str(self.winner).strip().casefold()
        if w == str(self.home).strip().casefold():
            return True
        if w == str(self.away).strip().casefold():
            return False
        return None


@dataclass
class PlayerWeek:
    """One player's line on one week's sheet."""

    player: str
    week: int
    correct_picks: dict[int, str] = field(default_factory=dict)  # game index -> team
    regular_wins: int = 0
    total_wins: int = 0          # regular + big-loser
    big_loser_picks: list[str] = field(default_factory=list)
    # The three big-loser cells exactly as the sheet holds them, slot by slot.
    # A correct pick is stored as "1" in place of the team, so the raw values
    # are what an editor must round-trip; big_loser_picks is the readable view.
    big_loser_raw: list[str] = field(default_factory=lambda: ["", "", ""])
    big_loser_wins: int = 0
    suicide_pick: str = ""
    suicide_out: bool = False      # the sheet marked this player eliminated
    rank: int | None = None
    games_behind: float = 0.0
    win_pct: float = 0.0
    winnings: float = 0.0

    @property
    def picked_home_count(self) -> int:
        return sum(1 for v in self.correct_picks.values() if v)


@dataclass
class Week:
    """A full week: the slate plus every player's line."""

    number: int
    games: list[Game] = field(default_factory=list)
    lines: dict[str, PlayerWeek] = field(default_factory=dict)   # canonical key -> line
    game_count: int = 0
    source: Path | None = None

    @property
    def has_results(self) -> bool:
        return any(g.played for g in self.games)

    @property
    def scored(self) -> bool:
        """True once player results exist, whether or not the slate was filled."""
        return any(l.total_wins for l in self.lines.values())

    def top_score(self) -> int:
        return max((l.total_wins for l in self.lines.values()), default=0)

    def winners(self) -> list[str]:
        top = self.top_score()
        if not top:
            return []
        return sorted(k for k, l in self.lines.items() if l.total_wins == top)

    def correct_count(self, game_index: int) -> int:
        """How many players got this game right - the 'trap game' signal."""
        return sum(1 for l in self.lines.values() if l.correct_picks.get(game_index))


@dataclass
class Player:
    """A pool entrant, assembled from every source that mentions them."""

    key: str                       # canonical normalized key
    display: str                   # nicest spelling seen
    weekly_wins: dict[int, int] = field(default_factory=dict)      # week -> wins
    weekly_regular: dict[int, int] = field(default_factory=dict)
    weekly_big_loser: dict[int, int] = field(default_factory=dict)
    weekly_winnings: dict[int, float] = field(default_factory=dict)
    weekly_rank: dict[int, int] = field(default_factory=dict)
    # Weeks past the official standings snapshot: shown, but kept out of
    # season averages so a half-entered week cannot distort them.
    provisional_wins: dict[int, int] = field(default_factory=dict)

    # Straight from stats.xls, which is authoritative for standings.
    pos: int | None = None
    prev_pos: int | None = None
    wins: int = 0
    losses: int = 0
    pct: float = 0.0
    games_behind: float = 0.0
    net_points: float = 0.0
    points_won: float = 0.0
    points_paid: float = 0.0
    current_week_wins: int = 0
    three_week_wins: int = 0
    line_game_pct: float = 0.0

    big_loser_points: float = 0.0
    suicide_alive: bool = False
    suicide_picks: dict[int, str] = field(default_factory=dict)
    suicide_out_week: int | None = None

    sources: set[str] = field(default_factory=set)

    # ---- derived season statistics -------------------------------------
    @property
    def weeks_played(self) -> list[int]:
        return sorted(w for w, v in self.weekly_wins.items() if v is not None)

    @property
    def season_wins(self) -> int:
        return sum(self.weekly_wins.values())

    @property
    def best_week(self) -> int:
        return max(self.weekly_wins.values(), default=0)

    @property
    def worst_week(self) -> int:
        return min(self.weekly_wins.values(), default=0)

    @property
    def average_wins(self) -> float:
        vals = list(self.weekly_wins.values())
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def consistency(self) -> float:
        """Standard deviation of weekly wins; lower is steadier."""
        vals = list(self.weekly_wins.values())
        return statistics.pstdev(vals) if len(vals) > 1 else 0.0

    @property
    def total_winnings(self) -> float:
        return sum(self.weekly_winnings.values())

    def net(self, buy_in: float) -> float:
        return self.total_winnings - buy_in

    @property
    def rank_movement(self) -> int | None:
        """Positive means climbed (a numerically smaller position)."""
        if self.pos is None or self.prev_pos is None:
            return None
        return self.prev_pos - self.pos

    @property
    def big_loser_wins(self) -> int:
        return sum(self.weekly_big_loser.values())

    def trend(self, window: int = 3) -> float:
        """Average wins across the most recent `window` weeks played."""
        weeks = self.weeks_played[-window:]
        if not weeks:
            return 0.0
        return sum(self.weekly_wins[w] for w in weeks) / len(weeks)


@dataclass
class SourceFile:
    """A file discovered in a watched folder."""

    path: Path
    kind: str                  # "stats" | "workbook"
    week: int | None = None
    season: str = ""
    digest: str = ""
    modified: float = 0.0
    error: str = ""

    @property
    def label(self) -> str:
        wk = f"week {self.week}" if self.week else "week unknown"
        return f"{self.path.name} ({self.kind}, {wk})"


@dataclass
class Conflict:
    """A disagreement between sources, surfaced rather than silently resolved."""

    player: str
    field: str
    authoritative: object
    other: object
    note: str = ""


@dataclass
class Season:  # noqa: D101
    """Everything the dashboard knows, after merging all sources."""

    title: str = "ACQL"
    players: dict[str, Player] = field(default_factory=dict)
    weeks: dict[int, Week] = field(default_factory=dict)
    current_week: int = 0
    buy_in: float = 40.0
    max_regular_points: int = 16
    max_big_loser_points: int = BIG_LOSER_PICKS
    big_losers_by_week: dict[int, list[str]] = field(default_factory=dict)
    sources: list[SourceFile] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    workbook_path: Path | None = None
    provisional_weeks: list[int] = field(default_factory=list)

    # ---- convenience accessors -----------------------------------------
    def ordered_players(self) -> list[Player]:
        """Standings order: explicit position if known, else wins descending."""
        def sort_key(p: Player) -> tuple:
            return (p.pos if p.pos is not None else 9_999, -p.wins, p.display.lower())

        return sorted(self.players.values(), key=sort_key)

    def by_display(self, display: str) -> Player | None:
        for p in self.players.values():
            if p.display == display:
                return p
        return None

    def played_weeks(self) -> list[int]:
        """Weeks with any scoring, provisional ones included."""
        return sorted(w for w, wk in self.weeks.items() if wk.scored)

    def final_weeks(self) -> list[int]:
        """Weeks covered by the official standings export."""
        return [w for w in self.played_weeks() if w not in self.provisional_weeks]

    def pot_total(self) -> float:
        return self.buy_in * len(self.players)

    def leader(self) -> Player | None:
        order = self.ordered_players()
        return order[0] if order else None

    @property
    def is_empty(self) -> bool:
        return not self.players
