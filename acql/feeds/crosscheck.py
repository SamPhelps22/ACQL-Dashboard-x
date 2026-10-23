"""A second results source (idea #46): ESPN's finals checked against nflverse's games file.

ESPN is the only place the dashboard reads scores from. The nflverse games
file (feeds/nflverse.py) also carries every final score, independently kept,
so each week's finals are compared with it: a game the two disagree on is
worth knowing before it decides anything. Only the copy already on disk is
read - refreshing it is a download, which needs Sam's yes each time - so a
week the copy doesn't have yet is said so plainly. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WeekCheck:
    week: int
    agree: int = 0
    differ: list[str] = field(default_factory=list)
    missing: int = 0            # ESPN finals the nflverse copy doesn't have


_CACHE: dict = {}


def _nflverse(year: int) -> dict[tuple[int, frozenset], tuple[str, int, int]]:
    """{(week, the two teams): (home code, home points, away points)} from the copy on disk,
    read once per copy (it is a few thousand rows)."""
    from . import nflverse
    try:
        stamp = (nflverse.FOLDER / nflverse.GAMES_FILE).stat().st_mtime_ns
    except OSError:
        return {}
    if _CACHE.get("key") != (year, stamp):
        _CACHE.update(key=(year, stamp), value=_read(year))
    return _CACHE["value"]


def _read(year: int) -> dict[tuple[int, frozenset], tuple[str, int, int]]:
    from . import nflverse, results
    from ..model.predictions import team_code
    out = {}
    try:
        rows = nflverse._rows(nflverse.GAMES_FILE)
    except Exception:  # noqa: BLE001 - no copy on disk
        return out
    for row in rows:
        try:
            if int(row["season"]) != year or row["game_type"] != "REG" or not row["home_score"]:
                continue
            home = team_code(nflverse._team(row["home_team"])) or results._code(row["home_team"])
            away = team_code(nflverse._team(row["away_team"])) or results._code(row["away_team"])
            out[(int(row["week"]), frozenset((home, away)))] = (home, int(float(row["home_score"])),
                                                                 int(float(row["away_score"])))
        except (KeyError, ValueError):
            continue
    return out


def check(year: int, weeks) -> list[WeekCheck]:
    from . import results
    other = _nflverse(year)
    out = []
    for week in weeks:
        found = WeekCheck(week)
        for s in results.load(year, week):
            if not s.final or s.home_points is None or s.away_points is None:
                continue
            theirs = other.get((week, frozenset((s.home, s.away))))
            if theirs is None:
                found.missing += 1
                continue
            home, hp, ap = theirs
            mine = (s.home_points, s.away_points) if home == s.home else (s.away_points, s.home_points)
            if mine == (hp, ap):
                found.agree += 1
            else:
                found.differ.append(f"{s.away.upper()} @ {s.home.upper()}: ESPN {s.away_points}-{s.home_points}, "
                                    f"nflverse {ap if home == s.home else hp}-{hp if home == s.home else ap}")
        if found.agree or found.differ or found.missing:
            out.append(found)
    return out
