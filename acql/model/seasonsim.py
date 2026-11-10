"""The season, simulated a week at a time: Deadeye's card for every week, made
with only what was known going into it, then marked against what happened.

The Model Lab replays the weeks the dashboard has numbers stored for. This
walks the whole season whether or not it does, taking each week's numbers
from the best place that has them, in this order, and saying which it used:

    stored        the predictions the dashboard kept for the week (lines, and
                  the computer models when their file was read in)
    a file        a Prediction Tracker file for the week still sitting in the
                  project folder ("nflpredictions week 5.csv")
    closing line  nflverse's closing line (data/nflverse/games.csv.gz). Later
                  than a Thursday card ever sees, so a week priced this way
                  flatters every recipe a little and is marked

A week the pool has no sheet for is laid out from nflverse's results, every
game straight up, and marked: the pool's own lines for it are not known.

Each week is priced the way pricing.py prices it - the same price() - with
the share of the models' say fitted on the weeks before it only. Beside
Deadeye's card every week:

    the line      the same recipe with none of the models' say: the market's side
    the pool      the coaches' average and best, and where Deadeye would have placed

and every game where Deadeye left the line's side, with how it came out.
Those are the only games where it is doing anything the line is not.

Nothing is stored, nothing is published, and no pick changes: this reads.

    python -m acql.model.seasonsim              the season so far, week by week
    python -m acql.model.seasonsim --games      every game, not only the weeks
    python -m acql.model.seasonsim --write FILE the report as Markdown
    python -m acql.model.seasonsim --fetch      get nflverse's games file first (goes online)

No Qt here.
"""

from __future__ import annotations

import csv
import gzip
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

from .. import analytics
from ..config import ROOT
from ..feeds import lines
from ..models import Game, Season, same_team
from ..version import MODEL_NAME
from . import predictions, pricing
from .predictions import display_team, team_code

STORED, FILE, CLOSING = "stored", "a file", "closing line"
NFLVERSE_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
#: nflverse's abbreviations where team_code does not already know them.
VERSE_CODES = {"OAK": "lv", "SD": "lac", "STL": "lar", "LA": "lar"}


# ---- what one week is priced from --------------------------------------------------------------
def _verse_file() -> Path:
    from ..feeds import nflverse
    return nflverse.FOLDER / nflverse.GAMES_FILE


def _verse_team(code: str) -> str:
    found = VERSE_CODES.get(code.strip().upper()) or team_code(code)
    return predictions.DISPLAY.get(found, code)


def _american(price: str) -> float | None:
    """A moneyline as the chance it implies, the bookmaker's margin still in it."""
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if not value:
        return None
    return 100 / (value + 100) if value > 0 else -value / (-value + 100)


@dataclass(frozen=True)
class Closing:
    """One game as nflverse has it."""

    week: int
    away: str
    home: str
    spread: float | None            # the closing line, home side (+ favoured)
    win: float | None               # the closing moneylines' chance the home side wins
    total: float | None
    away_points: int | None
    home_points: int | None
    neutral: bool = False


def closing_lines(year: int, path: Path | None = None) -> dict[int, list[Closing]]:
    """Week -> every regular-season game of a season in nflverse's file ({} without it)."""
    path = path or _verse_file()
    if not path.is_file():
        return {}
    opener = gzip.open if path.suffix == ".gz" else open
    out: dict[int, list[Closing]] = {}
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("season") != str(year) or row.get("game_type") != "REG":
                continue

            def number(key: str) -> float | None:
                try:
                    return float(row.get(key) or "")
                except ValueError:
                    return None

            ours, theirs = _american(row.get("home_moneyline", "")), _american(row.get("away_moneyline", ""))
            home, away = number("home_score"), number("away_score")
            week = int(row["week"])
            out.setdefault(week, []).append(Closing(
                week=week, away=_verse_team(row["away_team"]), home=_verse_team(row["home_team"]),
                spread=number("spread_line"),
                win=ours / (ours + theirs) if ours and theirs else None,
                total=number("total_line"),
                away_points=None if away is None else int(away), home_points=None if home is None else int(home),
                neutral=(row.get("location") or "").strip().casefold() == "neutral",
            ))
    return out


def fetch(path: Path | None = None) -> Path:
    """nflverse's games file, downloaded and kept where the dashboard reads it. Goes online."""
    import urllib.request
    from ..config import write_atomic_bytes
    path = path or _verse_file()
    request = urllib.request.Request(NFLVERSE_URL, headers={"User-Agent": "acql-dashboard"})
    with urllib.request.urlopen(request, timeout=60) as answer:     # noqa: S310 - a fixed https address
        body = answer.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic_bytes(path, gzip.compress(body))
    return path


def week_files(folder: Path | None = None) -> dict[int, Path]:
    """Week -> the newest predictions file in the project folder that names that week."""
    out: dict[int, Path] = {}
    folder = folder or ROOT
    for path in sorted(folder.glob("*.csv"), key=lambda p: p.stat().st_mtime):
        week = predictions.week_in_name(path)
        if week and predictions._LOOKS_RIGHT.search(path.stem):
            out[week] = path
    return out


def _from_closing(found: list[Closing]) -> list[predictions.Forecast]:
    return [predictions.Forecast(road=c.away, home=c.home, market=c.spread, neutral=c.neutral,
                                 market_win=c.win, total=c.total)
            for c in found if c.spread is not None]


def _slate_from(found: list[Closing]) -> list[Game]:
    """A week nobody kept a sheet for, from its results: every game straight up."""
    games = []
    for index, c in enumerate(found, start=1):
        winner = ""
        if c.home_points is not None and c.away_points is not None:
            winner = c.home if c.home_points > c.away_points else c.away if c.away_points > c.home_points else "Tie"
        games.append(Game(index=index, home=c.home, away=c.away, winner=winner,
                          home_points=c.home_points, away_points=c.away_points, result_from="nflverse"))
    return games


# ---- one week, simulated -----------------------------------------------------------------------
@dataclass(frozen=True)
class Call:
    """One game as it was priced going in, and how it came out."""

    index: int
    matchup: str
    lined: bool                 # the pool put a line on it
    line_pick: str              # the market's side: the recipe with none of the models' say
    line_chance: float
    pick: str                   # Deadeye's side
    chance: float
    credited: str               # the side the pool credited ("" if not played)
    models: int = 0             # computer models that priced it

    @property
    def graded(self) -> bool:
        return bool(self.credited)

    @property
    def right(self) -> bool:
        return self.graded and same_team(self.pick, self.credited)

    @property
    def line_right(self) -> bool:
        return self.graded and same_team(self.line_pick, self.credited)

    @property
    def left_the_line(self) -> bool:
        return not same_team(self.pick, self.line_pick)


def _surprise(chance: float, right: bool) -> float:
    chance = min(max(chance, 1e-6), 1 - 1e-6)
    return -math.log(chance if right else 1 - chance)


@dataclass(frozen=True)
class SimWeek:
    number: int
    source: str                         # STORED, FILE or CLOSING
    share: float                        # the models' share it was priced with
    calls: list[Call] = field(default_factory=list)
    no_sheet: bool = False              # laid out from results: the pool's lines are not known
    unpriced: int = 0                   # games nothing had a number for
    field: tuple[tuple[str, int], ...] = ()     # (coach, regular picks credited), when the sheet has them

    @property
    def field_scores(self) -> tuple[int, ...]:
        return tuple(score for _, score in self.field)

    @property
    def graded(self) -> list[Call]:
        return [c for c in self.calls if c.graded]

    @property
    def right(self) -> int:
        return sum(c.right for c in self.graded)

    @property
    def line_right(self) -> int:
        return sum(c.line_right for c in self.graded)

    @property
    def surprise(self) -> float:
        return sum(_surprise(c.chance, c.right) for c in self.graded)

    @property
    def line_surprise(self) -> float:
        return sum(_surprise(c.line_chance, c.line_right) for c in self.graded)

    @property
    def expected(self) -> float:
        """How many it should have got right, by its own chances."""
        return sum(c.chance for c in self.graded)

    @property
    def pool_average(self) -> float | None:
        return sum(self.field_scores) / len(self.field_scores) if self.field_scores else None

    @property
    def pool_best(self) -> int | None:
        return max(self.field_scores) if self.field_scores else None

    @property
    def place(self) -> int | None:
        """Where its regular picks would have finished among the coaches' (1 = best or level with it)."""
        if not self.field_scores or not self.graded:
            return None
        return 1 + sum(1 for score in self.field_scores if score > self.right)

    @property
    def flips(self) -> list[Call]:
        return [c for c in self.graded if c.left_the_line]


@dataclass(frozen=True)
class Simulation:
    year: int
    weeks: list[SimWeek] = field(default_factory=list)
    skipped: tuple[str, ...] = ()       # weeks left out, each with why

    @property
    def played(self) -> list[SimWeek]:
        return [w for w in self.weeks if w.graded]

    def total(self, what: str) -> float:
        return sum(getattr(w, what) for w in self.played)

    @property
    def games(self) -> int:
        return sum(len(w.graded) for w in self.played)

    @property
    def flips(self) -> list[tuple[int, Call]]:
        return [(w.number, c) for w in self.played for c in w.flips]

    def standing(self) -> tuple[int, int] | None:
        """(place, coaches) over the weeks the pool's sheets cover: Deadeye's regular picks
        against every coach's own, the same weeks for both."""
        weeks = [w for w in self.played if w.field]
        if not weeks:
            return None
        ours = sum(w.right for w in weeks)
        # a coach who missed a week scored nothing in it, as on the pool's own table
        totals: dict[str, int] = {}
        for w in weeks:
            for coach, score in w.field:
                totals[coach] = totals.get(coach, 0) + score
        return 1 + sum(1 for t in totals.values() if t > ours), len(totals)


def _credited(game: Game) -> str:
    if not game.played:
        return ""
    return display_team(game.winner) if team_code(game.winner) in (team_code(game.home), team_code(game.away)) \
        else str(game.winner)           # a tie: nobody's pick


def simulate_week(number: int, games: list[Game], forecasts: list[predictions.Forecast], share: float,
                  source: str, *, typed: dict | None = None, market_at: float = 0.0) -> SimWeek:
    """One week priced by pricing.price at `share`, and by the same recipe at none."""
    games = sorted(games, key=lambda g: g.index)
    found = predictions.match_games(games, forecasts)
    totals = sorted(f.total for f in found.by_game.values() if f.total)
    ctx = pricing.Context(
        week=number, forecasts=dict(found.by_game), lean=predictions.home_lean(forecasts),
        typical=predictions.typical_disagreement(forecasts), weight=share, market_at=market_at,
        typical_total=totals[len(totals) // 2] if totals else 0.0,
    )
    typed = typed or {}
    calls, unpriced = [], 0
    for game in games:
        spread = typed.get(game.index)
        ours = pricing.price(game, ctx, spread, typed=game.index in typed).prediction()
        market = pricing.price(game, replace(ctx, weight=0.0), spread, typed=game.index in typed).prediction()
        if ours is None or market is None:
            unpriced += 1
            continue
        forecast = found.by_game.get(game.index)
        calls.append(Call(
            index=game.index, matchup=game.label, lined=game.line is not None,
            line_pick=display_team(market.pick), line_chance=market.chance,
            pick=display_team(ours.pick), chance=ours.chance, credited=_credited(game),
            models=len(forecast.opinions) if forecast is not None else 0,
        ))
    return SimWeek(number, source, share, calls, unpriced=unpriced)


def run(season: Season, *, year: int | None = None, folder: Path | None = None,
        verse: Path | None = None, use_store: bool = True) -> Simulation:
    """The season walked a week at a time, each priced on the weeks before it."""
    from ..feeds import results
    year = year or results.season_year(season)
    closing = closing_lines(year, verse)
    files = week_files(folder)
    stored = predictions.stored_weeks() if use_store else {}
    numbers = sorted(set(season.weeks) | {n for n, found in closing.items()
                                           if any(c.home_points is not None for c in found)})
    weeks: list[SimWeek] = []
    replays: list[predictions.WeekReplay] = []
    skipped = []
    for number in numbers:
        week = season.weeks.get(number)
        games = sorted(week.games, key=lambda g: g.index) if week is not None else []
        no_sheet = not games
        if no_sheet:
            games = _slate_from(closing.get(number, []))
        if not games:
            skipped.append(f"week {number}: no slate")
            continue
        if stored.get(number):
            forecasts, source = list(stored[number]), STORED
        elif number in files:
            forecasts, source = predictions.read_csv(files[number]), FILE
        else:
            forecasts, source = _from_closing(closing.get(number, [])), CLOSING
        if not forecasts:
            skipped.append(f"week {number}: no line kept for it anywhere")
            continue
        fit = predictions.fit_from(replays) if replays else None
        share = fit.weight if fit is not None else predictions.CONSENSUS_WEIGHT
        typed = lines.load_spreads(number, games) if use_store and source == STORED else {}
        found = simulate_week(number, games, forecasts, share, source, typed=typed,
                              market_at=predictions.market_time(number) if typed else 0.0)
        scores = tuple((key, int(line.regular_wins or 0)) for key, line in week.lines.items()) \
            if week is not None and week.scored else ()
        found = replace(found, no_sheet=no_sheet, field=scores)
        weeks.append(found)
        if any(g.played for g in games):
            replays.append(predictions.replay_week(number, games, forecasts))
    return Simulation(year, weeks, tuple(skipped))


# ---- the report --------------------------------------------------------------------------------
def _signed(value: float, places: int = 0) -> str:
    return f"{value:+.{places}f}" if round(value, places) else "level"


def report(found: Simulation, *, every_game: bool = False) -> str:
    """The simulation as Markdown: a row a week, the games Deadeye left the line on, the totals."""
    name = MODEL_NAME
    out = [f"# {name}'s {found.year} season, simulated week by week", ""]
    played = found.played
    if not played:
        return "\n".join(out + ["Nothing to simulate: no week has both a result and a line."])
    out += [
        f"Each week priced with only what was known going into it; the share of the computer models' say "
        f"is fitted on the weeks before. \"The line\" is the same recipe with none of the models' say.", "",
        f"| Week | Priced from | Models' share | Games | {name} | The line | Expected | Pool average | Pool best | Would place |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for w in played:
        mark = " †" if w.no_sheet else ""
        place = f"{w.place} of {len(w.field_scores) + 1}" if w.place else "-"
        average = f"{w.pool_average:.1f}" if w.pool_average is not None else "-"
        out.append(
            f"| {w.number}{mark} | {w.source} | {w.share:.0%} | {len(w.graded)} | {w.right} | {w.line_right} | "
            f"{w.expected:.1f} | {average} | {w.pool_best if w.pool_best is not None else '-'} | {place} |")
    games = found.games
    right, line_right = int(found.total("right")), int(found.total("line_right"))
    out += [
        f"| **Season** | | | **{games}** | **{right}** | **{line_right}** | **{found.total('expected'):.1f}** | | | |", "",
    ]
    if any(w.no_sheet for w in played):
        out += ["† No pick sheet for the week: laid out from the results, every game straight up. "
                "The pool's own lines for it are not known.", ""]
    if any(w.source == CLOSING for w in played):
        out += ["Weeks priced from the closing line saw a later number than a Thursday card does, "
                "so they flatter both columns a little.", ""]
    out += ["## The season in one paragraph", ""]
    surprise, line_surprise = found.total("surprise") / games, found.total("line_surprise") / games
    summary = (f"{name} had {right} of {games} ({right / games:.1%}); the line alone had {line_right} "
               f"({line_right / games:.1%}). By its own chances {name} should have had about "
               f"{found.total('expected'):.0f}. Surprise a pick (log loss, lower is better): "
               f"{name} {surprise:.4f}, the line {line_surprise:.4f}.")
    standing = found.standing()
    if standing:
        covered = [w for w in played if w.field_scores]
        summary += (f" Over the {len(covered)} weeks the pool's sheets cover, its regular picks would stand "
                    f"{_ordinal(standing[0])} among {standing[1] + 1} (the coaches and itself), Big Losers left out.")
    out += [summary, ""]
    flips = found.flips
    out += [f"## Where {name} left the line's side", ""]
    if not flips:
        out += [f"Nowhere: on every graded game {name} took the side the line alone takes. "
                f"The models' say moved how sure it was, never which side.", ""]
    else:
        won = sum(c.right for _, c in flips)
        out += [f"{len(flips)} of {games} games, and {won} of them came in "
                f"({_signed(won - (len(flips) - won))} against the line on those games). "
                f"A count this small is a count, not a rate.", "",
                f"| Week | Game | The line | {name} | Credited | |", "|---:|---|---|---|---|---|"]
        for number, c in flips:
            out.append(f"| {number} | {c.matchup} | {c.line_pick} {c.line_chance:.0%} | {c.pick} {c.chance:.0%} | "
                       f"{c.credited} | {'right' if c.right else 'wrong'} |")
        out.append("")
    out += ["## How sure it was, and how that came out", "",
            "| Called | Picks | Came in | Its chances said |", "|---|---:|---:|---:|"]
    for low, high, label in ((0.0, 0.55, "under 55%"), (0.55, 0.65, "55-65%"), (0.65, 0.75, "65-75%"),
                             (0.75, 1.01, "75% and up")):
        band = [c for w in played for c in w.graded if low <= c.chance < high]
        if band:
            out.append(f"| {label} | {len(band)} | {sum(c.right for c in band) / len(band):.0%} | "
                       f"{sum(c.chance for c in band) / len(band):.0%} |")
    out.append("")
    if every_game:
        for w in played:
            out += [f"## Week {w.number}", "", f"| Game | {name} | The line | Credited | |", "|---|---|---|---|---|"]
            for c in w.graded:
                lined = " (pool line)" if c.lined else ""
                out.append(f"| {c.matchup}{lined} | {c.pick} {c.chance:.0%} | {c.line_pick} {c.line_chance:.0%} | "
                           f"{c.credited} | {'right' if c.right else 'wrong'} |")
            out.append("")
    if found.skipped:
        out += ["## Left out", ""] + [f"- {reason}" for reason in found.skipped] + [""]
    return "\n".join(out)


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import warnings
    parser = argparse.ArgumentParser(prog="python -m acql.model.seasonsim", description=__doc__.split("\n\n")[0])
    parser.add_argument("--games", action="store_true", help="list every game, not only the weeks")
    parser.add_argument("--write", metavar="FILE", help="write the report here as well as printing it")
    parser.add_argument("--fetch", action="store_true", help="download nflverse's games file first (goes online)")
    args = parser.parse_args(argv)
    if args.fetch:
        print(f"nflverse games file kept at {fetch()}")
    from .. import config, repository
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        season = repository.load_season(config.Settings.load() if hasattr(config.Settings, "load") else config.Settings())
    text = report(run(season), every_game=args.games)
    print(text)
    if args.write:
        Path(args.write).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
