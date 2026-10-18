"""Betting patterns from outside, checked against our own seasons.

The first ones come from Loutsch (2020), "Using the Home-Underdog Theory to
Test the Efficiency of the NFL Sports Gambling Market": over ten seasons
(about 2010-2019) home underdogs on Sundays covered 57.7% in September and
53.5% when getting under 3 points, against the 52.4% that -110 needs.

This only counts. It teaches nothing, changes no pick, and the dashboard
does not import it. Each pattern is reported three ways: every season we
have, the paper's own seasons, and the seasons after the paper was written -
the only part of the record the paper could not have seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, lgamma, log

import numpy as np
import pandas as pd

from . import data

#: What a -110 bet has to win to break even.
BREAK_EVEN = 110 / 210
#: The paper's seasons, and the ones it could not have seen.
PAPER = (2010, 2019)
AFTER = 2020
#: The regular season (week 18 since 2021); playoff games are left out, as in the paper.
LAST_WEEK = 18


@dataclass
class Pattern:
    name: str
    note: str
    pick: object        # frame -> boolean mask


def _eastern(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["kickoff"], unit="s", utc=True).dt.tz_convert("America/New_York")


def home_dogs(history: pd.DataFrame, sunday_only: bool = True) -> pd.DataFrame:
    """Regular-season games where the home side got points at the close.
    `line_closing` is how much the home side is favoured by, so it is below 0
    for a home underdog; `points` is what that underdog was getting."""
    frame = history[(history["week"] <= LAST_WEEK) & ~history["neutral"].astype(bool)
                    & history["line_closing"].notna() & history["actual"].notna()
                    & history["kickoff"].notna()].copy()
    frame = frame[frame["line_closing"] < 0]
    frame["points"] = -frame["line_closing"]
    when = _eastern(frame)
    frame["month"] = when.dt.month
    frame["sunday"] = when.dt.dayofweek == 6
    frame["night"] = when.dt.hour >= 19
    if sunday_only:     # the paper left Thursday and Monday games out, and Sunday night in
        frame = frame[frame["sunday"]]
    frame["covered"] = np.sign(frame["actual"] + frame["points"])     # 1 cover, 0 push, -1 not
    return frame


PATTERNS = [
    Pattern("All home underdogs", "the paper: 51.2%, a loss", lambda f: f["points"] > 0),
    Pattern("September", "the paper: 57.7% (156 games)", lambda f: f["month"] == 9),
    Pattern("Under 3 points", "the paper: 53.5% (355 games)", lambda f: f["points"] < 3),
    Pattern("September and under 3", "both at once - not in the paper", lambda f: (f["month"] == 9) & (f["points"] < 3)),
    Pattern("Not September", "what is left when September is taken out", lambda f: f["month"] != 9),
]


def _p_at_least(wins: int, games: int, chance: float = BREAK_EVEN) -> float:
    """How likely this many covers or more would be from a bet that only breaks even."""
    def term(k: int) -> float:
        return exp(lgamma(games + 1) - lgamma(k + 1) - lgamma(games - k + 1)
                   + k * log(chance) + (games - k) * log(1 - chance))
    return min(1.0, sum(term(k) for k in range(wins, games + 1)))


def tally(frame: pd.DataFrame) -> dict:
    wins = int((frame["covered"] > 0).sum())
    losses = int((frame["covered"] < 0).sum())
    games = wins + losses
    rate = wins / games if games else float("nan")
    by_season = frame[frame["covered"] != 0].groupby("season")["covered"].apply(lambda c: float((c > 0).mean()))
    return {
        "wins": wins, "losses": losses, "pushes": int((frame["covered"] == 0).sum()), "games": games,
        "rate": rate,
        "units": wins * (100 / 110) - losses,          # to a 1-unit risk at -110
        "good_seasons": int((by_season > BREAK_EVEN).sum()), "seasons": int(len(by_season)),
        "p": _p_at_least(wins, games) if games else float("nan"),
    }


def spans(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    first, last = int(frame["season"].min()), int(frame["season"].max())
    return {
        f"All seasons {first}-{last}": frame,
        f"The paper's {PAPER[0]}-{PAPER[1]}": frame[frame["season"].between(*PAPER)],
        f"Since the paper {AFTER}-{last}": frame[frame["season"] >= AFTER],
    }


def study(history: pd.DataFrame | None = None, sunday_only: bool = True) -> list[tuple[Pattern, dict[str, dict]]]:
    if history is None:
        history = data.check(data.history(notes=data.Notes()), data.Notes())
    dogs = home_dogs(history, sunday_only)
    return [(pattern, {span: tally(part[pattern.pick(part)]) for span, part in spans(dogs).items()})
            for pattern in PATTERNS]


def write_up(found: list[tuple[Pattern, dict[str, dict]]], sunday_only: bool = True) -> str:
    lines = ["# Home-underdog patterns against our seasons", "",
             f"Closing lines, regular season, {'Sunday games only (as in the paper)' if sunday_only else 'every day'}, "
             f"neutral sites left out. Break-even at -110 is {BREAK_EVEN:.1%}. Units are to a 1-unit risk; "
             "\"chance by luck\" is how often a bet that only breaks even would do this well or better.", ""]
    for pattern, by_span in found:
        lines += [f"## {pattern.name}", f"_{pattern.note}_", "",
                  "| Seasons | Covered | Record | Units | Seasons above break-even | Chance by luck |",
                  "|---|---|---|---|---|---|"]
        for span, t in by_span.items():
            if not t["games"]:
                lines.append(f"| {span} | - | no games | | | |")
                continue
            lines.append(f"| {span} | {t['rate']:.1%} | {t['wins']}-{t['losses']}-{t['pushes']} | "
                         f"{t['units']:+.1f} | {t['good_seasons']} of {t['seasons']} | {t['p']:.0%} |")
        lines.append("")
    return "\n".join(lines)


def run(sunday_only: bool = True) -> tuple[str, object]:
    found = study(sunday_only=sunday_only)
    text = write_up(found, sunday_only)
    where = data.folder() / "patterns"
    where.mkdir(parents=True, exist_ok=True)
    path = where / ("home-underdogs.md" if sunday_only else "home-underdogs-every-day.md")
    path.write_text(text, encoding="utf-8")
    return text, path
