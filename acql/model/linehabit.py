"""The commissioner's pool-line habit, re-measured every time a sheet comes in.

Several of Deadeye's numbers lean on a guess at the line the commissioner
*will* post before he posts it - the long-run replay (backtest.pool_line),
the suicide helper (survivor.assumed_line) and "take them at 6 or less". The
guess is his measured habit: the next whole number above the betting spread,
lining only favourites of 6.5 or more (33 games, 2025 weeks 15-17 and 2026
weeks 1-3). If the habit drifts, every underdog call built on the guess
drifts with it, so this checks it against each new sheet.

For each game on the season's sheets it compares the posted line with the
betting spread for that game: the line in the week's predictions file when
there is one (what the market said midweek, when lines are set), otherwise
nflverse's closing spread (kept by feeds/starters.py). It reports how often the
current rule gives exactly the posted line, the alternative rules that
would have done better, whether he has started lining smaller favourites or
skipping big ones, and a verdict. Nothing is changed automatically: a rule
change moves the replay's numbers, so it is a decision to make, not a drift
to follow silently.

    python -m acql.model.linehabit      (prints the report for the loaded season)
"""

from __future__ import annotations

import csv
import io
import math
from collections import Counter
from dataclasses import dataclass, field

LINED_FROM = 6.5
SMALLEST_LINE = 7
#: Lined games needed before the verdict can say the habit has drifted.
JUDGE_FROM = 15
#: ...and how much better another rule must match before that is said.
CLEAR_GAIN = 0.15
#: ...or if the current rule matches fewer than this share of lined games.
MIN_SHARE = 0.5


def current_rule(spread: float) -> float | None:
    """backtest.pool_line's rule, on a favourite's spread (positive)."""
    quoted = round(abs(spread) * 2) / 2
    if quoted < LINED_FROM:
        return None
    return float(max(SMALLEST_LINE, math.floor(quoted) + 1))


#: Alternatives worth scoring against it, each a spread -> line.
RULES = {
    "next whole number above the spread (current)": lambda s: math.floor(s) + 1,
    "the spread rounded up": lambda s: math.ceil(s),
    "the spread rounded to nearest": lambda s: math.floor(s + 0.5),
    "the spread plus a point, rounded up": lambda s: math.ceil(s + 1),
    "the spread plus two, rounded down": lambda s: math.floor(s + 2),
}


@dataclass(frozen=True)
class Observation:
    week: int
    game: str
    favourite: str
    spread: float               # the favourite's betting spread (positive = favoured)
    posted: float | None        # the commissioner's line, None if he left it straight
    source: str                 # "predictions file" or "nflverse close"


@dataclass
class Habit:
    observations: list[Observation] = field(default_factory=list)
    lined: int = 0
    exact: int = 0
    rules: dict[str, float] = field(default_factory=dict)        # rule -> exact-match share
    offsets: Counter = field(default_factory=Counter)             # posted - spread, rounded to 0.5
    skipped_big: list[Observation] = field(default_factory=list)  # 6.5+ favourites left straight
    lined_small: list[Observation] = field(default_factory=list)  # lined below 6.5
    verdict: str = ""
    drifting: bool = False

    @property
    def exact_share(self) -> float | None:
        return self.exact / self.lined if self.lined else None


def _closing_spreads(year: int) -> dict[tuple[str, str], float]:
    """nflverse closing spreads from the copy qbcheck keeps: (away, home) -> home margin."""
    from .. import store
    from ..feeds import starters as qbcheck
    kept = store.get(qbcheck.KIND, "games", None)
    if not isinstance(kept, dict) or not kept.get("text"):
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(kept["text"])):
        if r.get("season") != str(year) or r.get("game_type") != "REG" or not r.get("spread_line"):
            continue
        try:
            out[(qbcheck.pool_code(r["away_team"]), qbcheck.pool_code(r["home_team"]), int(r["week"]))] = \
                float(r["spread_line"])
        except (KeyError, ValueError):
            continue
    return out


def measure(season, year: int | None = None, forecasts_by_week: dict | None = None,
            closing: dict | None = None) -> Habit:
    """Compare every game on the season's sheets with its betting spread."""
    from . import predictions
    from ..feeds import results
    from ..models import same_team
    year = year or results.season_year(season)
    forecasts_by_week = predictions.stored_weeks() if forecasts_by_week is None else forecasts_by_week
    closing = _closing_spreads(year) if closing is None else closing
    habit = Habit()
    for number, week in sorted(season.weeks.items()):
        games = sorted(week.games, key=lambda g: g.index)
        if not any(g.line is not None for g in games):
            continue                      # no sheet with lines for this week
        match = predictions.match_games(games, forecasts_by_week.get(number, []))
        for g in games:
            home_margin, source = None, ""
            f = match.by_game.get(g.index)
            if f is not None and f.market is not None:
                home_margin = -f.market if g.index in match.flipped else f.market
                source = "predictions file"
            else:
                key = (predictions.team_code(g.away), predictions.team_code(g.home), number)
                if key in closing:
                    home_margin, source = closing[key], "nflverse close"
            if home_margin is None or home_margin == 0:
                continue
            fav = g.home if home_margin > 0 else g.away
            posted = g.line
            if posted is not None and g.line_favourite and not same_team(g.line_favourite, fav):
                continue                  # he made the market underdog the favourite: not a habit case
            habit.observations.append(Observation(number, f"{g.away} @ {g.home}", fav, abs(home_margin),
                                                  posted, source))
    lined = [o for o in habit.observations if o.posted is not None]
    habit.lined = len(lined)
    # the rule's arithmetic on every lined game; lining a small favourite is reported separately
    habit.exact = sum(1 for o in lined if max(SMALLEST_LINE, math.floor(o.spread) + 1) == o.posted)
    for name, rule in RULES.items():
        if lined:
            habit.rules[name] = sum(1 for o in lined if max(SMALLEST_LINE, rule(o.spread)) == o.posted) / len(lined)
    habit.offsets = Counter(round((o.posted - o.spread) * 2) / 2 for o in lined)
    habit.skipped_big = [o for o in habit.observations if o.posted is None and o.spread >= LINED_FROM]
    habit.lined_small = [o for o in lined if o.spread < LINED_FROM]
    _judge(habit)
    return habit


def _judge(h: Habit) -> None:
    if not h.lined:
        h.verdict = "No posted pool lines with a betting spread to compare yet."
        return
    share = h.exact_share
    best_name, best = max(h.rules.items(), key=lambda kv: kv[1])
    base = (f"The commissioner's lines matched the expected habit on {h.exact} of {h.lined} lined games "
            f"({share:.0%})")
    if h.lined < JUDGE_FROM:
        h.verdict = base + f" - too few to judge a change by (needs {JUDGE_FROM})."
    elif best - share >= CLEAR_GAIN and "(current)" not in best_name:
        h.drifting = True
        h.verdict = (base + f"; '{best_name}' matched {best:.0%}. His habit looks to have shifted: "
                     "the guessed lines (replay, suicide helper, 'take them at N or less') are off by that much.")
    elif share < MIN_SHARE:
        h.drifting = True
        common = h.offsets.most_common(1)[0][0] if h.offsets else 0
        h.verdict = (base + f". His habit looks to have shifted: he now most often posts the spread "
                     f"{common:+g}, which no rule here describes - the guessed lines need re-measuring.")
    else:
        h.verdict = base + " - the habit is holding."
    if h.skipped_big:
        h.verdict += f" He left {len(h.skipped_big)} favourite(s) of 6.5+ without a line."
    if h.lined_small:
        h.verdict += f" He lined {len(h.lined_small)} favourite(s) below 6.5."


def describe(h: Habit) -> str:
    lines = [h.verdict]
    if h.rules:
        lines.append("Exact matches by rule:")
        lines += [f"  {share:5.0%}  {name}" for name, share in sorted(h.rules.items(), key=lambda kv: -kv[1])]
    if h.offsets:
        lines.append("Posted line minus spread: " + ", ".join(
            f"{k:+g}: {v}" for k, v in sorted(h.offsets.items())))
    for o in h.skipped_big:
        lines.append(f"  week {o.week} {o.game}: {o.favourite} favoured by {o.spread:g}, no line ({o.source})")
    for o in h.lined_small:
        lines.append(f"  week {o.week} {o.game}: {o.favourite} favoured by {o.spread:g}, lined at {o.posted:g}")
    return "\n".join(lines)


if __name__ == "__main__":
    from ..config import Settings
    from ..names import AliasTable
    from ..repository import load_season
    print(describe(measure(load_season(Settings(), AliasTable.load()))))
