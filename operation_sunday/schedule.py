"""The weekly calendar: when each week's forecasts are due.

For every (season, week) the deadline is worked out from that week's own
fixtures, never from a fixed offset:

    nominal   = the week's deadline weekday (Thursday) at the configured local
                time, in the configured zone - DST is resolved for that date;
    first     = the earliest kickoff of a game that counts (not canceled),
                minus the configured margin;
    lock      = min(nominal, first).

So a Wednesday opener, Thanksgiving's early game, a Christmas game or a
Thursday international game moves the lock earlier, and a postponed game that
leaves the week drops out. The "Thursday" of a week is the one before the
week's main Sunday (the date most of its games are played on), so a
Saturday/Monday-heavy late-season week still anchors correctly.

Stages of the weekly job (pipeline.py runs them):
    1 ingest  2 validate  3 features  4 train  5 validate_models  6 select
    7 forecast  8 verify  9 lock  10 record_results (after the games)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from .config import Settings
from .tz import get_zone, to_utc

STAGES = ("ingest", "validate", "features", "train", "validate_models",
          "select", "forecast", "verify", "lock", "record_results")


@dataclass(frozen=True)
class WeekDeadline:
    season: int
    week: int
    game_type: str
    nominal_utc: datetime
    first_kickoff_utc: datetime | None
    lock_utc: datetime
    run_due_utc: datetime
    reason: str
    games: int

    def as_dict(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in self.__dict__.items()}


def week_key(game_type: str, week: int) -> tuple:
    return ("POST" if game_type != "REG" else "REG", int(week))


def _main_sunday(kickoffs_local: list[datetime]) -> date:
    """The Sunday of the NFL week (weeks run Tuesday to Monday) holding the
    day most of the week's games are played on."""
    days = pd.Series([k.date() for k in kickoffs_local])
    main = days.mode().sort_values().iloc[0]
    wd = main.weekday()
    return main - timedelta(days=1) if wd == 0 else main + timedelta(days=(6 - wd) % 7)


def deadline_for(games: pd.DataFrame, season: int, week: int, settings: Settings,
                 game_type: str = "REG") -> WeekDeadline:
    sel = games[(games["season"] == season) & (games["week"] == week)]
    sel = sel[(sel["game_type"] == "REG") if game_type == "REG" else (sel["game_type"] != "REG")]
    sel = sel[sel["status"] != "canceled"]
    if sel.empty:
        raise ValueError(f"no scheduled games for {season} week {week} ({game_type})")
    zone = get_zone(settings.timezone)
    local = [k.to_pydatetime().astimezone(zone) for k in sel["kickoff_utc"]]
    sunday = _main_sunday(local)
    back = (6 - settings.deadline_weekday) % 7
    nominal_day = sunday - timedelta(days=back)
    nominal = to_utc(datetime(nominal_day.year, nominal_day.month, nominal_day.day,
                              settings.deadline_hour, settings.deadline_minute), settings.timezone)
    first = sel["kickoff_utc"].min().to_pydatetime() - timedelta(minutes=settings.kickoff_margin_minutes)
    if first < nominal:
        lock, why = first, "first kickoff comes before the Thursday deadline"
    else:
        lock, why = nominal, "Thursday deadline"
    return WeekDeadline(season, week, game_type, nominal, first, lock,
                        lock - timedelta(hours=settings.run_lead_hours), why, len(sel))


def season_calendar(games: pd.DataFrame, season: int, settings: Settings) -> list[WeekDeadline]:
    out = []
    sg = games[games["season"] == season]
    for (gt, wk), _ in sg.groupby([sg["game_type"].eq("REG").map({True: "REG", False: "POST"}), "week"]):
        try:
            out.append(deadline_for(games, season, int(wk), settings, gt))
        except ValueError:
            continue
    return sorted(out, key=lambda d: d.lock_utc)


@dataclass(frozen=True)
class Timing:
    status: str        # "early", "on_time", "late_start", "late"
    alert: str | None


def timing(deadline: WeekDeadline, now: datetime) -> Timing:
    """How a run starting now relates to the week's deadline. Never backdates."""
    if now >= deadline.lock_utc:
        return Timing("late", f"LATE RUN: {deadline.season} week {deadline.week} locked at "
                              f"{deadline.lock_utc.isoformat()} and this run started {now.isoformat()}. "
                              "Forecasts will be labelled late and not counted as on-time.")
    if now >= deadline.run_due_utc:
        return Timing("late_start", f"Run due {deadline.run_due_utc.isoformat()} started late at "
                                    f"{now.isoformat()}; still before the lock.")
    return Timing("on_time", None)


def next_week(games: pd.DataFrame, now: datetime, settings: Settings) -> WeekDeadline | None:
    """The first week whose lock is still ahead, or the week in progress if
    its games have not all finished (a late run)."""
    seasons = sorted(games.loc[games["kickoff_utc"] >= pd.Timestamp(now) - pd.Timedelta(days=10), "season"].unique())
    for s in seasons:
        for d in season_calendar(games, int(s), settings):
            sel = games[(games["season"] == d.season) & (games["week"] == d.week)]
            if ((sel["status"] == "scheduled") & (sel["kickoff_utc"] > pd.Timestamp(now))).any():
                return d
    return None
