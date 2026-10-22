"""The situation explorer (idea #31): Deadeye's record in any slice you choose.

autopsy.py answers fixed questions. This lets you ask your own - spread band,
home or road pick, pool line or not, division game, night game, a range of
weeks - and answers with the sample size always shown, a plain interval, and
a count of how many slices have been looked at, because the more slices you
try the likelier one looks special by luck alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Spread bands (absolute betting line, points): label -> (low, high], high inclusive.
BANDS = {"Any": None, "Pick'em to 3": (-0.1, 3.0), "3.5 to 6.5": (3.0, 6.5),
         "7 to 9.5": (6.5, 9.5), "10 or more": (9.5, 99.0)}
SIDES = ("Any", "Home pick", "Road pick")
YES_NO = ("Any", "Yes", "No")
#: Below this many games a slice is only something to watch.
FEW = 30


@dataclass(frozen=True)
class Slice:
    band: str = "Any"
    side: str = "Any"
    pool_line: str = "Any"
    division: str = "Any"
    night: str = "Any"
    weeks: tuple[int, int] | None = None

    def describe(self) -> str:
        bits = []
        if self.band != "Any":
            bits.append(f"line {self.band}")
        if self.side != "Any":
            bits.append(self.side.lower())
        for name, value in (("pool line", self.pool_line), ("division game", self.division), ("night game", self.night)):
            if value != "Any":
                bits.append(name if value == "Yes" else f"no {name}")
        if self.weeks:
            bits.append(f"weeks {self.weeks[0]}-{self.weeks[1]}")
        return ", ".join(bits) or "every graded game"


def _yes_no(wanted: str, value) -> bool:
    if wanted == "Any":
        return True
    if value is None:
        return False
    return bool(value) == (wanted == "Yes")


def matches(game, s: Slice) -> bool:
    band = BANDS.get(s.band)
    if band is not None:
        if game.line is None:
            return False
        low, high = band
        if not (low < abs(game.line) <= high):
            return False
    if s.side != "Any" and game.home_pick != (s.side == "Home pick"):
        return False
    if not _yes_no(s.pool_line, game.pool_line is not None):
        return False
    if not _yes_no(s.division, game.divisional):
        return False
    if not _yes_no(s.night, game.night):
        return False
    if s.weeks and not (s.weeks[0] <= game.week <= s.weeks[1]):
        return False
    return True


@dataclass(frozen=True)
class Answer:
    slice: Slice
    games: int
    right: int
    expected: float           # what Deadeye's own chances called for
    line_games: int
    line_right: int           # how the betting line's side did on the same games
    low: float                # 90% interval for the hit rate
    high: float

    @property
    def rate(self) -> float:
        return self.right / self.games if self.games else 0.0

    @property
    def few(self) -> bool:
        return self.games < FEW

    def words(self) -> str:
        if not self.games:
            return "No graded games match."
        line = (f" The betting line's side won {self.line_right} of {self.line_games}."
                if self.line_games else "")
        caution = " Too few games to read much into." if self.few else ""
        return (f"{self.slice.describe().capitalize()}: {self.right} of {self.games} right "
                f"({self.rate:.0%}, likely between {self.low:.0%} and {self.high:.0%}); "
                f"its chances called for {self.expected:.1f}.{line}{caution}")


def interval(right: int, n: int, z: float = 1.645) -> tuple[float, float]:
    """Wilson score interval (90% by default)."""
    if n == 0:
        return 0.0, 1.0
    p = right / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def ask(games, s: Slice) -> Answer:
    picked = [g for g in games if matches(g, s)]
    right = sum(1 for g in picked if g.right)
    lined = [g for g in picked if g.line_right is not None]
    low, high = interval(right, len(picked))
    return Answer(s, len(picked), right, sum(g.chance for g in picked),
                  len(lined), sum(1 for g in lined if g.line_right), low, high)
