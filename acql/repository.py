"""Load every discovered source and merge them into one Season.

Merge policy, per the pool's own conventions:

  * stats.xls is authoritative for standings (position, W/L, PCT, GB, net
    points, every week's score) and for the Big Loser and Suicide pools.
  * The commissioner's pick sheets supply what stats.xls does not carry:
    the game slates, the pool's lines and every coach's picks. Results come
    from his graded copy of the sheet, or from the final scores the
    dashboard fetches itself (results.py) with the pool's lines applied.
  * The ACQL Dashboard workbook is optional. Any week it has results for
    is its own and is left as it typed it; the sheets only check it.
  * Where both describe the same number and disagree, the stats.xls value is
    kept and the disagreement is recorded as a Conflict rather than discarded,
    so data-entry slips surface instead of hiding.
  * Several weekly stats.xls snapshots layer oldest-first, so a season's
    history rebuilds itself as files accumulate in data/.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import Settings
from .models import Conflict, Game, Player, Season, SourceFile, Week
from . import analytics
from .feeds import lines, results
from .pool import picks
from .names import AliasTable
from .model.predictions import team_code
from .sources import discover, parse_stats, parse_workbook

# A name this long that reads as a football team is a football team. Shorter
# ones are left alone deliberately: "tb" is a coach in this pool as well as a
# way of writing Tampa Bay.
TEAM_NAME_LENGTH = 3


def load_season(settings: Settings, aliases: AliasTable | None = None, *,
                online: bool = True, force: bool = False, fetcher=None,
                now: float | None = None) -> Season:
    """Discover, parse and merge every source into a single Season.

    `online` lets the load ask ESPN for results it doesn't have yet
    (results.py), and `force` asks about every unfinished week whatever the
    time; `fetcher` stands in for the scoreboard in tests.
    """
    aliases = aliases or AliasTable.load()
    sources = discover(settings.search_paths())
    season = Season(buy_in=settings.buy_in, sources=sources)

    readable = [s for s in sources if not s.error]
    for bad in (s for s in sources if s.error):
        season.warnings.append(f"{bad.path.name}: {bad.error}")

    # A raw pick sheet is not a standings export, whatever the file name made
    # the discovery step think. Read as one it yields a column of team names
    # and percentages where the coaches should be - which is where the pool
    # briefly acquired two dozen players called "Atlanta" and "0.857".
    # They are not worth a warning: the loader reads pick sheets from the
    # same folders on its own, and the Data page lists each file and what it
    # was used for. Saying so on every load only buried the notes that matter.
    # A pick sheet saved as .xlsx is taken for a workbook the same way.
    misread = [s for s in readable if s.kind in ("stats", "workbook") and _looks_like_picks(s.path)]
    readable = [s for s in readable if s not in misread]

    stats_files = sorted(
        (s for s in readable if s.kind == "stats"),
        key=lambda s: (s.week or 0, s.modified),
    )
    workbooks = sorted(
        (s for s in readable if s.kind == "workbook"),
        key=lambda s: (s.week or 0, s.modified),
    )

    players: dict[str, Player] = {}

    # --- stats.xls snapshots, oldest first so the newest wins on overlap ---
    latest_stats: dict | None = None
    for source in stats_files:
        try:
            parsed = parse_stats(source, aliases, players)
        except Exception as exc:  # noqa: BLE001 - a bad file must not kill the app
            season.warnings.append(f"{source.path.name}: could not be read ({exc})")
            continue
        season.warnings.extend(parsed["warnings"])
        season.big_losers_by_week.update(parsed["big_losers"])
        latest_stats = parsed
        if parsed["season"]:
            season.title = parsed["season"]

    if latest_stats:
        season.current_week = latest_stats["week"] or season.current_week
        season.max_regular_points = latest_stats["max_regular"]
        season.max_big_loser_points = latest_stats["max_big_loser"]
    # The weeks stats.xls scored are the pool's official ones.
    for person in players.values():
        person.official_weeks = set(person.weekly_wins)

    # Snapshot the authoritative numbers before the workbook is layered on,
    # so any disagreement can be reported.
    authoritative = {
        key: {
            "wins": p.wins,
            "weekly_wins": dict(p.weekly_wins),
        }
        for key, p in players.items()
    }

    # --- the dashboard workbook ---------------------------------------------
    latest_workbook: dict | None = None
    for source in workbooks:
        try:
            parsed = parse_workbook(source, aliases, players)
        except Exception as exc:  # noqa: BLE001
            season.warnings.append(f"{source.path.name}: could not be read ({exc})")
            continue
        season.warnings.extend(parsed["warnings"])
        season.weeks.update(parsed["weeks"])
        latest_workbook = parsed
        season.workbook_path = source.path
        if parsed["buy_in"]:
            season.buy_in = parsed["buy_in"]
        if parsed["season_title"] and not latest_stats:
            season.title = parsed["season_title"]

    if latest_workbook and not season.current_week:
        season.current_week = latest_workbook["current_week"] or 0

    season.players = players
    _merge_duplicates(season)
    _drop_phantoms(season)
    # Pool lines the workbook keeps in notes its parser doesn't read.
    try:
        season.warnings.extend(lines.attach_from_workbook(season))
    except Exception as exc:  # noqa: BLE001 - a note is a warning, not a failed load
        season.warnings.append(f"Couldn't read the pool lines: {exc}")
    _take_pick_sheets(season, settings, aliases, online=online, force=force, fetcher=fetcher, now=now)
    season.conflicts = _reconcile(season, authoritative)
    _fill_week_lines(season)
    _fill_player_weeks(season)
    # The workbook holds its money as formulas and caches no results, so it
    # reads as blank from outside Excel. The scores are known, and the pool's
    # payout rule is arithmetic on the scores, so any week the files have not
    # priced is worked out here rather than shown as nothing.
    season.computed_winnings = analytics.fill_winnings(season)
    season.warnings.extend(_coverage_warnings(season, sources))

    if not season.current_week:
        played = season.played_weeks()
        season.current_week = played[-1] if played else 0

    _split_provisional(season)
    _resolve_suicide_pool(season, (latest_stats or {}).get("week") or 0)
    _restart_suicide_pool(season, (latest_stats or {}).get("week") or 0,
                          (latest_stats or {}).get("suicide_round"))
    _rank_weeks(season)
    return season


def workbook_note(season) -> str:
    """What the old workbook is still used for - and that nothing needs typing
    into it any more, and why typing results into it gets in the way."""
    typed = sorted(
        n for n, w in season.weeks.items()
        if getattr(w, "source", None) is not None
        and any(g.played and getattr(g, "result_from", "") in ("", "workbook") for g in w.games)
    )
    if len(typed) > 1:
        which = "weeks " + ", ".join(str(n) for n in typed[:-1]) + f" and {typed[-1]}"
    else:
        which = f"week {typed[0]}" if typed else ""
    return (
        "Nothing needs typing into your ACQL Dashboard workbook any more. Each week is set up "
        "from the NFL's schedule - put the pool's line games in on Deadeye Picks \u203a My picks "
        "\u203a Line games\u2026 (or drop in the commissioner's sheet) - and the results come in "
        "from ESPN as the games finish. "
        + (f"The results typed into it for {which} are still used. " if which else "")
        + "A week with results typed in here stays as typed and ESPN's aren't used for it, so "
        "leave the rest blank. The workbook does no harm left in the folder."
    )


def _rank_weeks(season: Season) -> None:
    """Each coach's place in each week, counted from the scores the pages show.

    The workbook keeps a rank column, but it was worked out from its own
    scores - which stats.xls may since have corrected (a coach typed in with
    nothing, say, who really had 8) - and a week built from a pick sheet has
    none at all. So every week's places are counted again from the week's
    totals; coaches level on the week share a place.
    """
    for number, week in season.weeks.items():
        totals = sorted((line.total_wins for line in week.lines.values() if line.total_wins), reverse=True)
        place = {score: totals.index(score) + 1 for score in set(totals)}
        for key, line in week.lines.items():
            line.rank = place.get(line.total_wins) if line.total_wins else None
            person = season.players.get(key)
            if person is None:
                continue
            if line.rank:
                person.weekly_rank[number] = line.rank
            else:
                person.weekly_rank.pop(number, None)


#: A file whose name begins like this is the commissioner's raw pick sheet.
#: Deliberately anchored at the start: "stats" and "ACQL Dashboard" never
#: begin with it, and a coach's own file called "my picks notes" is not in
#: the data folder.
PICKS_NAME = re.compile(r"^\s*picks\b", re.IGNORECASE)


def _looks_like_picks(path: Path) -> bool:
    return bool(PICKS_NAME.match(Path(path).stem))


def _sheet_folders(settings: Settings) -> list[Path]:
    """Where pick sheets are looked for beyond the usual places: every
    watched folder and the app's own data folder."""
    from .config import DATA_DIR
    folders = [Path(p) for p in settings.search_paths()]
    folders.append(Path(DATA_DIR))
    return folders


def _take_pick_sheets(season: Season, settings: Settings, aliases: AliasTable, *,
                      online: bool, force: bool, fetcher, now: float | None) -> None:
    """Every week the pick sheets can give, graded against the results.

    New sheets in the folders are read in; the scoreboard is asked about any
    week still being played (only when online); then each week is built
    from its sheet. Nothing here can fail the load - a problem is a warning.
    """
    try:
        picks.refresh_from_disk(season.workbook_path, _sheet_folders(settings))
    except Exception as exc:  # noqa: BLE001
        season.warnings.append(f"Couldn't read the pool's pick sheets: {exc}")
    year = results.season_year(season, now)
    season.results_year = year
    if season.title in ("", "ACQL"):
        season.title = f"ACQL {year}"
    if online:
        weeks = set(picks.load_all(every_season=True))
        # a workbook week with no results in it is the sheet's to score
        weeks |= {
            n for n, w in season.weeks.items()
            if not any(str(g.winner or "").strip() for g in w.games)
        }
        # this week and next, sheet or not: their first kickoffs lock the odds,
        # and the dashboard sets them up itself until a sheet arrives
        weeks |= set(results.calendar_weeks(year, now)) | set(lines.pool_line_weeks(year))
        try:
            got, problems = results.refresh(year, weeks, now=now, force=force, fetcher=fetcher)
        except Exception as exc:  # noqa: BLE001
            got, problems = [], [f"Couldn't check for results: {exc}"]
        season.results_fetched = got
        season.warnings.extend(problems)
    try:
        graded = picks.attach(season, key_for=aliases.key,
                              results_for=lambda number: results.load(year, number))
    except Exception as exc:  # noqa: BLE001
        season.warnings.append(f"Couldn't build the weeks from the pick sheets: {exc}")
        return
    season.sheet_weeks = sorted(set(graded.built) | set(graded.filled))
    if graded.other_season:
        season.warnings.append(
            "Stored pick sheets from another season were ignored ("
            + ", ".join(f"week {n}" for n in graded.other_season)
            + "). Their games are not this season's - clear them from "
            "Data & Update."
        )
    season.warnings.extend(graded.problems)
    season.warnings.extend(graded.disagreements)
    try:
        season.warnings.extend(_weeks_without_sheets(season, year, now))
    except Exception as exc:  # noqa: BLE001 - a week not set up is a warning
        season.warnings.append(f"Couldn't set up the weeks without a pick sheet: {exc}")


def _weeks_without_sheets(season: Season, year: int, now: float | None) -> list[str]:
    """Set up the weeks no pick sheet has built - so nothing has to be typed
    into the workbook.

    The week being played and the next one by the calendar, any week given
    line games on Next Week, and any workbook week with no results in it
    get their games from the NFL's own fixtures (the scoreboard as last
    read, else the schedule), the line games typed in on Next Week, and
    every result the scoreboard has. So This Week has a card to make before
    the commissioner's sheet goes out, and the results are in as the games
    finish. Nobody's picks are in such a week until the sheet arrives and
    builds it properly.

    A week the workbook has results in stays the workbook's, and a week a
    sheet built keeps the sheet's lines; a line game typed in here that
    differs from them is pointed out. Returns those notes.
    """
    notes: list[str] = []
    sheets = set(season.sheet_weeks)
    wanted = set(results.calendar_weeks(year, now)) | set(lines.pool_line_weeks(year))
    wanted |= {n for n, w in season.weeks.items() if w.games and n not in sheets}
    for number in sorted(n for n in wanted if 1 <= n <= 18):
        typed = lines.pool_lines(year, number)
        week = season.weeks.get(number)
        if number in sheets:
            notes += _line_differences(week, typed, "the pick sheet")
            continue
        if (week is not None and getattr(week, "source", None) is not None
                and any(g.played for g in week.games)):
            notes += _line_differences(week, typed, "the workbook")
            continue
        kept = results.load(year, number)
        if week is None or not week.games:
            games = _fixtures(year, number, kept)
            if not games:
                continue
            week = season.weeks.get(number) or Week(number=number)
            week.games = games
            season.weeks[number] = week
            season.fixture_weeks.append(number)
        if typed:
            lines.apply_pool_lines(week, typed)
        for game in week.games:
            results.apply(game, kept)
    return notes


def _fixtures(year: int, number: int, kept: list) -> list[Game]:
    """A week's games from the scoreboard as last read (first kickoff first),
    else from the schedule when it is this season's."""
    from .feeds import schedule
    from .model.predictions import DISPLAY

    def name(code: str) -> str:
        return DISPLAY.get(code.lower(), code)

    listed = sorted((s for s in kept if s.away and s.home),
                    key=lambda s: (s.kickoff or 0, s.home))
    if listed:
        return [Game(index, name(s.home), name(s.away)) for index, s in enumerate(listed, start=1)]
    if getattr(schedule, "SCHEDULE_YEAR", None) == year:
        return schedule.slate(number)
    return []


def _line_differences(week, typed: dict, where: str) -> list[str]:
    """A line game typed in on Next Week that the week's own source says
    otherwise about - that source's line is the one used."""
    from .model.predictions import DISPLAY, team_code
    if week is None or not typed:
        return []
    out = []
    for game in week.games:
        found = typed.get(frozenset((team_code(game.away), team_code(game.home))))
        if found is None:
            continue
        fav, points = found
        theirs = ((team_code(game.line_favourite), float(game.line))
                  if game.line is not None and game.line_favourite else None)
        if theirs != (fav, points):
            said = (f"{DISPLAY.get(theirs[0], theirs[0])} by {theirs[1]:g}" if theirs
                    else "no line")
            out.append(
                f"Week {week.number}, {game.label}: the line game typed in here is "
                f"{DISPLAY.get(fav, fav)} by {points:g}, but {where} has {said} - "
                f"{where}'s is used")
    return out


def _same_person(display: str) -> str:
    """A coach's name reduced to what cannot vary between files.

    "Bob h", "Bob H." and "BOB  H" are one man. Case, spacing and punctuation
    are exactly what differs between a hand-typed workbook, an exported
    stats.xls and a pick sheet, so none of them decide identity here.
    """
    return "".join(c for c in str(display).casefold() if c.isalnum())


def _merge_duplicates(season: Season) -> None:
    """Fold coaches who are the same person under two spellings into one.

    Each file names its own coaches, and the alias table reconciles the
    spellings it has been told about. Anything it has not been told about
    arrives as a second coach with the same name, splitting one man's season
    across two rows - half his weeks under each, the pool counted larger than
    it is, and every pool-wide average taken over a field that does not exist.

    The fuller record wins, and the thinner one is emptied into it rather than
    dropped, so nothing is lost on the way.
    """
    groups: dict[str, list[str]] = {}
    for key, person in season.players.items():
        groups.setdefault(_same_person(person.display), []).append(key)

    weekly = (
        "weekly_wins", "weekly_regular", "weekly_big_loser", "weekly_winnings",
        "weekly_rank", "provisional_wins", "suicide_picks", "weekly_pie",
    )
    totals = (
        "wins", "losses", "pct", "games_behind", "net_points", "points_won",
        "points_paid", "big_loser_points", "current_week_wins",
        "three_week_wins", "line_game_pct", "pie_splits",
    )
    # The workbook is the pool's own roster, so its spelling of a name is the
    # one the coach should be called by - an export that shouts "BOB H." does
    # not get to rename him. Failing that, the record that knows the most.
    book = season.workbook_path.name if season.workbook_path else ""

    def rank(key: str) -> tuple:
        person = season.players[key]
        return (
            0 if book and book in person.sources else 1,
            -len(person.sources),
            -len(person.weekly_wins),
            key,
        )

    for keys in groups.values():
        if len(keys) < 2:
            continue
        keys.sort(key=rank)
        primary, main = keys[0], season.players[keys[0]]
        for other in keys[1:]:
            extra = season.players.pop(other, None)
            if extra is None:
                continue
            official = set(getattr(extra, "official_weeks", ())) - set(getattr(main, "official_weeks", ()))
            for field in weekly:
                target = getattr(main, field)
                for week, value in getattr(extra, field).items():
                    if week in official and field in ("weekly_wins", "weekly_regular", "weekly_big_loser"):
                        target[week] = value            # the export's number is the official one
                    else:
                        target.setdefault(week, value)
            main.official_weeks = set(getattr(main, "official_weeks", ())) | official
            for field in totals:
                if not getattr(main, field) and getattr(extra, field):
                    setattr(main, field, getattr(extra, field))
            main.sources |= extra.sources
            if main.pos is None:
                main.pos = extra.pos
            if main.prev_pos is None:
                main.prev_pos = extra.prev_pos
            main.suicide_alive = main.suicide_alive or extra.suicide_alive
            if main.suicide_out_week is None:
                main.suicide_out_week = extra.suicide_out_week
            # The weeks filed under the other spelling move across too.
            for week in season.weeks.values():
                line = week.lines.pop(other, None)
                if line is not None and primary not in week.lines:
                    week.lines[primary] = line


def _is_phantom(display: str) -> bool:
    """A name that is really a number or a football team, not a coach."""
    text = display.strip()
    if not text:
        return True
    plain = text.replace(",", "").replace("$", "").replace("%", "")
    try:
        float(plain)
    except ValueError:
        pass
    else:
        return True
    return len(text) > TEAM_NAME_LENGTH and bool(team_code(text))


def _drop_phantoms(season: Season) -> None:
    """Remove coaches who are really spreadsheet debris.

    Pasting a raw pick sheet a row or two out of place brings its team row and
    its row of picked-home percentages down into the coach column, and every
    cell of those two rows then becomes a player. They match nothing, but they
    are counted in the pool size, they dilute every pool-wide average, and
    they set the alias check off as names missing from the other file.

    This is done quietly. The entries are unmistakably not people, so there is
    no judgement call to hand back and nothing for anyone to decide.

    Doing it here rather than in one parser means it holds for stats.xls, the
    workbook and anything added later, whichever of them the debris came in on.
    """
    gone = [
        key for key, person in season.players.items()
        if _is_phantom(person.display)
    ]
    for key in gone:
        season.players.pop(key, None)
        for week in season.weeks.values():
            week.lines.pop(key, None)


def _resolve_suicide_pool(season: Season, stats_week: int | None = None) -> None:
    """Decide who is still alive from the most recent week that says so.

    stats.xls lists survivors as of the week it covers. The workbook's suicide
    column runs ahead of it and writes a DEAD marker once someone is knocked
    out, so a later week is newer information rather than a contradiction -
    the freshest week carrying any suicide data wins.
    """
    weeks_with_data = sorted(
        w for w, week in season.weeks.items()
        if any(l.suicide_pick or l.suicide_out for l in week.lines.values())
    )
    if not weeks_with_data:
        return
    latest = weeks_with_data[-1]
    covered = season.current_week if stats_week is None else stats_week
    if covered and latest <= covered:
        # stats.xls already covers this week and stays authoritative.
        return
    week = season.weeks[latest]
    for key, person in season.players.items():
        line = week.lines.get(key)
        if line is None:
            continue
        if line.suicide_out:
            # DEAD on this week's sheet: out the week before, at the latest.
            person.suicide_alive = False
            if person.suicide_out_week is None:
                person.suicide_out_week = max(latest - 1, 1)
        elif line.suicide_pick:
            # In this week; out of it if the pick has already lost.
            game = next(
                (g for g in week.games if g.played
                 and team_code(line.suicide_pick) in (team_code(g.home), team_code(g.away))),
                None,
            )
            lost = game is not None and team_code(game.winner) != team_code(line.suicide_pick)
            person.suicide_alive = not lost
            if lost and person.suicide_out_week is None:
                person.suicide_out_week = latest


def _restart_suicide_pool(season: Season, stats_week: int = 0,
                          from_stats: dict | None = None) -> None:
    """Start the suicide pool again from the week the dashboard was told it did
    (survivor.start_again): somebody won it, so everyone is back in.

    Until the standings export covers that week it still lists the last
    round's survivors, so the new round is worked out here - everyone alive,
    then each week's picks from the new start on. Once the export has caught
    up, its survivors are the new round's and stay as they are.

    The export says so itself once it has a "Suicide Pool #2" column
    (`from_stats`); a later start told to the dashboard still wins.
    """
    from .pool import survivor
    found = survivor.rounds(season.results_year or results.season_year(season))
    if from_stats and (not found or found[-1]["week"] < from_stats["start"]):
        found = found + [{"week": from_stats["start"], "winners": from_stats["winners"]}]
    if not found:
        return
    season.suicide_rounds = [dict(r) for r in found]
    start = season.suicide_restart = found[-1]["week"]
    season.suicide_winners = list(found[-1].get("winners") or [])
    if stats_week >= start:
        for person in season.players.values():
            if (person.suicide_out_week or start) < start:
                person.suicide_out_week = None
        return
    for person in season.players.values():
        person.suicide_alive, person.suicide_out_week = True, None
    for number in sorted(n for n in season.weeks if n >= start):
        week = season.weeks[number]
        for key, line in week.lines.items():
            person = season.players.get(key)
            if person is None or not person.suicide_alive:
                continue
            if line.suicide_out:
                person.suicide_alive, person.suicide_out_week = False, max(number - 1, start)
            elif line.suicide_pick:
                code = team_code(line.suicide_pick)
                game = next((g for g in week.games if g.played
                             and code in (team_code(g.home), team_code(g.away))), None)
                if game is not None and team_code(game.winner) != code:
                    person.suicide_alive, person.suicide_out_week = False, number


def _split_provisional(season: Season) -> None:
    """Quarantine weeks beyond the official standings snapshot.

    stats.xls states the week it covers. A later week may already be
    half-populated in the workbook (matchups typed in, a placeholder score
    against every player); counting that as a real result would drag every
    season average down. Such weeks stay visible on the Weekly page but are
    held out of the season statistics until the export catches up.
    """
    cutoff = season.current_week
    if not cutoff:
        return
    # A week with nobody's picks in it yet (set up from the fixtures) has no
    # scores to hold out.
    provisional = sorted(w for w in season.weeks if w > cutoff and season.weeks[w].lines)
    if not provisional:
        return
    season.provisional_weeks = provisional
    for person in season.players.values():
        for week in provisional:
            if week in person.weekly_wins:
                person.provisional_wins[week] = person.weekly_wins.pop(week)
            person.weekly_regular.pop(week, None)
            person.weekly_big_loser.pop(week, None)
    plural = "s" if len(provisional) > 1 else ""
    weeks = ", ".join(str(w) for w in provisional)
    season.warnings.append(
        f"Week{plural} {weeks} {'are' if plural else 'is'} not covered by the "
        f"latest stats.xls (which reports through week {cutoff}), so "
        f"{'they are' if plural else 'it is'} shown as in-progress and left "
        "out of season averages."
    )


def _reconcile(season: Season, authoritative: dict) -> list[Conflict]:
    """Compare workbook-derived numbers against the authoritative snapshot."""
    conflicts: list[Conflict] = []
    for key, person in season.players.items():
        snapshot = authoritative.get(key) or {}
        # The export's own weeks, under whichever spelling the coach ended up.
        official_weeks = {
            w: person.weekly_wins[w] for w in getattr(person, "official_weeks", ()) if w in person.weekly_wins
        }
        official_weeks = official_weeks or dict(snapshot.get("weekly_wins", {}))
        if not official_weeks:
            continue
        for week, wk in season.weeks.items():
            line = wk.lines.get(key)
            if line is None or not line.total_wins:
                continue
            # A week still being played can't agree with a finished count yet.
            if wk.source is None and not all(g.played for g in wk.games):
                continue
            official = official_weeks.get(week)
            if official is None or official == line.total_wins:
                continue
            conflicts.append(
                Conflict(
                    player=person.display,
                    field=f"week {week} wins",
                    authoritative=official,
                    other=line.total_wins,
                    note="stats.xls kept; the workbook differs" if wk.source is not None
                    else "stats.xls kept; the pick sheet and results give this",
                )
            )
            # ...and kept it is: every page reads the week from these lines.
            regular = person.weekly_regular.get(week)
            big_loser = person.weekly_big_loser.get(week)
            if regular is not None and big_loser is not None and regular + big_loser == official:
                line.regular_wins, line.big_loser_wins = regular, big_loser
            line.total_wins = official
    conflicts.sort(key=lambda c: (c.player.lower(), c.field))
    return conflicts


def _fill_week_lines(season: Season) -> None:
    """Backfill per-week totals from stats.xls for weeks the workbook lacks."""
    for week_no, week in season.weeks.items():
        for key, person in season.players.items():
            line = week.lines.get(key)
            official = person.weekly_wins.get(week_no)
            if line is None or official is None:
                continue
            if not line.total_wins:
                line.total_wins = official
                line.regular_wins = person.weekly_regular.get(week_no, official)
                line.big_loser_wins = person.weekly_big_loser.get(week_no, 0)


def _fill_player_weeks(season: Season) -> None:
    """Carry each week's scores back onto the coaches, where nothing else has.

    `_fill_week_lines` runs the other way: it takes stats.xls's authoritative
    weekly totals and puts them on the week. This is for the case stats.xls
    does not cover - a week the workbook holds, or one built from a pick
    sheet - where the score exists on the week and the coach's own record
    still says nothing.

    It matters more than it sounds, because the workbook's Season tab is a
    grid of formulas with no saved results: read from outside Excel it is
    blank, so without this every coach's season reads as nought however many
    weeks they have played. A value already on the player is never replaced.
    """
    for number, week in season.weeks.items():
        for key, line in week.lines.items():
            person = season.players.get(key)
            if person is None or not line.total_wins:
                continue
            if number not in person.weekly_wins:
                person.weekly_wins[number] = line.total_wins
            if number not in person.weekly_regular:
                person.weekly_regular[number] = line.regular_wins or line.total_wins
            if number not in person.weekly_big_loser and line.big_loser_wins:
                person.weekly_big_loser[number] = line.big_loser_wins

    # stats.xls fills the standings columns. Without it they stay at zero
    # while the weekly record says otherwise, which is the same story the
    # Overview histogram was telling: a pool of coaches all on no wins.
    games = {w: len(wk.games) for w, wk in season.weeks.items()}
    for person in season.players.values():
        if person.wins or not person.weekly_wins:
            continue
        played = sum(games.get(w, 0) for w in person.weekly_wins)
        person.wins = person.season_wins
        person.losses = max(0, played - person.wins)
        person.pct = person.wins / played if played else 0.0
    if not any(p.pos for p in season.players.values()):
        order = sorted(season.players.values(), key=lambda p: (-p.wins, p.display))
        for place, person in enumerate(order, start=1):
            person.pos = place


def _coverage_warnings(season: Season, sources: list[SourceFile]) -> list[str]:
    """Flag players who appear in only one source, so nobody vanishes quietly."""
    warnings: list[str] = []
    if not sources and not getattr(season, "sheet_weeks", None):
        warnings.append(
            "No spreadsheets found. Drop this week's pick sheet and stats.xls "
            "into the data folder - they are read as soon as they land."
        )
        return warnings

    have_stats = any(s.kind == "stats" and not s.error for s in sources)
    have_workbook = any(
        s.kind == "workbook" and not s.error and not _looks_like_picks(s.path) for s in sources
    )
    have_sheets = bool(getattr(season, "sheet_weeks", None))
    if have_stats and have_workbook:
        lonely = [
            p.display
            for p in season.players.values()
            if len(p.sources) == 1
        ]
        if lonely:
            shown = ", ".join(sorted(lonely)[:8])
            more = f" (+{len(lonely) - 8} more)" if len(lonely) > 8 else ""
            warnings.append(
                f"{len(lonely)} player(s) appear in only one file and may be "
                f"spelled differently between them: {shown}{more}. "
                "Add a mapping in aliases.json if these are the same person."
            )
    if not have_stats:
        warnings.append(
            "No stats.xls found - the standings below are the dashboard's own count "
            "from the pick sheets and the results, not the pool's official table."
            if have_sheets else
            "No stats.xls found - standings, Big Loser and Suicide pools are unavailable."
        )
    if not have_workbook and not have_sheets:
        warnings.append(
            "No pick sheets yet - drop the week's picks file (the one the commissioner "
            "sends) into the data folder or Downloads, and the week builds itself."
        )
    return warnings
