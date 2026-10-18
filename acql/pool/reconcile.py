"""Does a week add up? The stored results against ESPN, and the pool's official
totals against a recount under the coded rules.

Two kinds of difference, kept apart because they mean different things:

    games     a game whose stored winner (or score) is not what ESPN's final
              score gives under the pool's rules - the line rule included
    coaches   a coach whose official total is not what their picks score
              against those results

A game difference is usually a typo on the graded sheet or a line read
wrongly; a coach difference with every game agreeing is the pool's own
scoring (a hand correction, a rule applied differently) and only the
commissioner can say which is right. This only reports: it changes nothing.

ESPN's scores come from what is already kept (results.load); `fetch=True`
asks ESPN again first, which is free - it is the same scoreboard the
dashboard reads all week. Nothing here knows about Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..feeds import results
from ..model.predictions import display_team, team_code
from ..models import Season
from . import picks as pick_sheets


@dataclass(frozen=True)
class GameDiff:
    index: int
    matchup: str
    stored: str           # the winner on file ("" none)
    espn: str             # the side ESPN's final score credits ("" no final)
    why: str


@dataclass(frozen=True)
class CoachDiff:
    name: str
    official: int
    recount: int
    unknown: int          # games whose pick couldn't be read, counted as misses

    @property
    def off_by(self) -> int:
        return self.official - self.recount


@dataclass
class Report:
    week: int
    games: list[GameDiff] = field(default_factory=list)
    coaches: list[CoachDiff] = field(default_factory=list)
    checked_games: int = 0
    checked_coaches: int = 0

    @property
    def clean(self) -> bool:
        return not self.games and not self.coaches

    def text(self) -> str:
        lines = [f"Week {self.week}: {self.checked_games} games and {self.checked_coaches} coaches checked."]
        if self.clean:
            return lines[0] + " Everything adds up."
        if self.games:
            lines.append("Games that don't match ESPN:")
            lines += [f"  #{g.index} {g.matchup}: on file {g.stored or '-'}, ESPN gives {g.espn or '-'} ({g.why})"
                      for g in self.games]
        if self.coaches:
            lines.append("Coaches whose official total isn't the recount:")
            lines += [f"  {c.name}: official {c.official}, recount {c.recount} ({c.off_by:+d})"
                      + (f", {c.unknown} pick(s) unreadable" if c.unknown else "") for c in self.coaches]
        return "\n".join(lines)


def _same(a: str, b: str) -> bool:
    if a == results.TIE or b == results.TIE:
        return a == b
    return bool(team_code(a)) and team_code(a) == team_code(b)


def check(season: Season, number: int, *, scores: list | None = None, fetch: bool = False,
          year: int | None = None) -> Report:
    """The week's report. `scores` stands in for ESPN's (tests); otherwise the kept ones."""
    report = Report(number)
    week = season.weeks.get(number)
    if week is None:
        return report
    year = results.season_year(season) if year is None else year
    if scores is None:
        scores = results.fetch(year, number) if fetch else results.load(year, number)

    credited: dict[int, str] = {}
    for game in week.games:
        score, _ = results.find(scores, game.away, game.home)
        matchup = f"{display_team(game.away)} @ {display_team(game.home)}"
        stored = str(game.winner or "").strip()
        if score is None or not score.final:
            if stored:
                report.games.append(GameDiff(game.index, matchup, stored, "", "no final score from ESPN"))
            continue
        both = results.points(game, score)
        if both is None:
            continue
        report.checked_games += 1
        side = results.credited(game, *both)
        credited[game.index] = side
        if not stored:
            report.games.append(GameDiff(game.index, matchup, "", side, "no winner on file"))
        elif not _same(stored, side):
            why = f"final {score.away_points}-{score.home_points}"
            if game.line is not None and game.line_favourite:
                why += f", {display_team(game.line_favourite)} by {game.line:g} needed"
            report.games.append(GameDiff(game.index, matchup, stored, side, why))
        elif (game.home_points, game.away_points) not in ((None, None), both):
            report.games.append(GameDiff(game.index, matchup, stored, side,
                                         f"score on file {game.away_points}-{game.home_points}, "
                                         f"ESPN {both[1]}-{both[0]}"))

    sheet = pick_sheets.load(number)
    on_sheet = {" ".join(n.split()).casefold(): n for n in (sheet.coaches if sheet else [])}
    for key, line in week.lines.items():
        player = season.players.get(key)
        name = player.display if player else line.player
        sheet_name = on_sheet.get(" ".join(str(name).split()).casefold()) \
            or on_sheet.get(" ".join(str(line.player).split()).casefold())
        right = unknown = 0
        for game in week.games:
            side = credited.get(game.index)
            if side is None:
                continue
            took = line.correct_picks.get(game.index) or ""
            if not took and sheet is not None and sheet_name:
                row = sheet.game_for(game.away, game.home)
                took = row.picks.get(sheet_name, "") if row else ""
            if not took and game.index not in line.correct_picks:
                unknown += sheet is None or not sheet_name
            right += bool(took) and _same(took, side)
        recount = right + int(line.big_loser_wins or 0)
        report.checked_coaches += 1
        official = int(line.total_wins or 0)
        if official != recount:
            report.coaches.append(CoachDiff(name, official, recount, unknown))
    report.coaches.sort(key=lambda c: (-abs(c.off_by), c.name.casefold()))
    return report


def season_report(season: Season, *, fetch: bool = False) -> list[Report]:
    """Every week with results on file, oldest first."""
    return [check(season, n, fetch=fetch) for n in sorted(season.weeks)
            if any(str(g.winner or "").strip() for g in season.weeks[n].games)]


def main(argv: list[str] | None = None) -> int:
    """python -m acql.pool.reconcile [week ...] [--fetch]"""
    import sys
    from ..config import Settings
    from ..names import AliasTable
    from ..repository import load_season
    args = sys.argv[1:] if argv is None else argv
    fetch = "--fetch" in args
    season = load_season(Settings.load(), AliasTable.load())
    weeks = [int(a) for a in args if a.isdigit()]
    found = [check(season, n, fetch=fetch) for n in weeks] if weeks else season_report(season, fetch=fetch)
    print("\n\n".join(r.text() for r in found) or "No weeks with results yet.")
    return 0 if all(r.clean for r in found) else 1


if __name__ == "__main__":
    raise SystemExit(main())
