"""Load every discovered source and merge them into one Season.

Merge policy, per the pool's own conventions:

  * stats.xls is authoritative for standings (position, W/L, PCT, GB, net
    points) and is the only source for the Big Loser and Suicide pools.
  * The workbook supplies what stats.xls does not carry: the game slates,
    individual picks, and the Winnings sheet.
  * Where both describe the same number and disagree, the stats.xls value is
    kept and the disagreement is recorded as a Conflict rather than discarded,
    so data-entry slips surface instead of hiding.
  * Several weekly stats.xls snapshots layer oldest-first, so a season's
    history rebuilds itself as files accumulate in data/.
"""

from __future__ import annotations

from .config import Settings
from .models import Conflict, Player, Season, SourceFile
from .names import AliasTable
from .sources import discover, parse_stats, parse_workbook


def load_season(settings: Settings, aliases: AliasTable | None = None) -> Season:
    """Discover, parse and merge every source into a single Season."""
    aliases = aliases or AliasTable.load()
    sources = discover(settings.search_paths())
    season = Season(buy_in=settings.buy_in, sources=sources)

    readable = [s for s in sources if not s.error]
    for bad in (s for s in sources if s.error):
        season.warnings.append(f"{bad.path.name}: {bad.error}")

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
    season.conflicts = _reconcile(season, authoritative)
    _fill_week_lines(season)
    season.warnings.extend(_coverage_warnings(season, sources))

    if not season.current_week:
        played = season.played_weeks()
        season.current_week = played[-1] if played else 0

    _split_provisional(season)
    _resolve_suicide_pool(season)
    return season


def _resolve_suicide_pool(season: Season) -> None:
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
    if latest <= season.current_week:
        # stats.xls already covers this week and stays authoritative.
        return
    for key, person in season.players.items():
        line = season.weeks[latest].lines.get(key)
        if line is None:
            continue
        if line.suicide_out:
            person.suicide_alive = False
            if person.suicide_out_week is None:
                person.suicide_out_week = latest
        elif line.suicide_pick:
            person.suicide_alive = True


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
    provisional = sorted(w for w in season.weeks if w > cutoff)
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
        snapshot = authoritative.get(key)
        if not snapshot:
            continue
        for week, line in (
            (w, wk.lines.get(key)) for w, wk in season.weeks.items()
        ):
            if line is None or not line.total_wins:
                continue
            official = snapshot["weekly_wins"].get(week)
            if official is None or official == line.total_wins:
                continue
            conflicts.append(
                Conflict(
                    player=person.display,
                    field=f"week {week} wins",
                    authoritative=official,
                    other=line.total_wins,
                    note="stats.xls kept; workbook differs",
                )
            )
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


def _coverage_warnings(season: Season, sources: list[SourceFile]) -> list[str]:
    """Flag players who appear in only one source, so nobody vanishes quietly."""
    warnings: list[str] = []
    if not sources:
        warnings.append(
            "No spreadsheets found. Drop this week's stats.xls and "
            "ACQL Dashboard.xlsx into the data/ folder, then press Refresh."
        )
        return warnings

    have_stats = any(s.kind == "stats" and not s.error for s in sources)
    have_workbook = any(s.kind == "workbook" and not s.error for s in sources)
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
        warnings.append("No stats.xls found - standings, Big Loser and Suicide pools are unavailable.")
    if not have_workbook:
        warnings.append("No ACQL Dashboard.xlsx found - game slates and picks are unavailable.")
    return warnings
