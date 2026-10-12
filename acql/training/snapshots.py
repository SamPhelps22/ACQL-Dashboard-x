"""Each week's numbers as they stood at the pool's deadline, kept for good.

The one thing no archive has is a clock. The dashboard knows this week's
line, its moneyline and over/under, and every computer model's number - but
it keeps the newest of each, so by Monday there is no saying what a card
handed in on Thursday could have seen. Without that, a challenger can never
be tested on exactly what it would have been given.

So a snapshot freezes a week: every game with its line, where it opened, the
moneyline's chance, the total, each model's number by name, the pool's own
line - and the time each was taken, the time of the lock, and the time the
snapshot was made. One file a week in data/training/snapshots.

    taken before the lock     kept, and replaced by any later one that is
                              still before the lock - so the last look before
                              the deadline is the one that stands
    taken after the lock      kept only if the week has none, and marked
                              late: better than nothing, never mistaken for
                              the real thing

Nothing here fetches anything; it writes down what the dashboard already
has. Run it before Thursday's deadline (`python -m acql.training snapshot`).

No Qt here.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import VERSION, data

log = logging.getLogger("acql.training")

FOLDER_NAME = "snapshots"
#: What a snapshot keeps of each game, beyond every model's number.
KEPT = ("season", "week", "home", "away", "game", "locked_at", "taken_at", "line_deadline", "line_opening",
        "line_used", "used_at", "win_deadline", "total_deadline", "pool_line", "pool_favourite", "models_at",
        "deadeye_live", "deadeye_chance", "neutral")


def folder() -> Path:
    where = data.folder() / FOLDER_NAME
    where.mkdir(parents=True, exist_ok=True)
    return where


def path_for(year: int, week: int) -> Path:
    return folder() / f"{int(year)}-{int(week):02d}.json"


def read(path: Path) -> dict | None:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
        return found if isinstance(found, dict) and isinstance(found.get("games"), list) else None
    except (OSError, ValueError):
        return None


def _clean(value):
    if isinstance(value, (float, np.floating)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def take(rows: pd.DataFrame, now: float | None = None) -> list[tuple[Path, str]]:
    """Freeze every week in `rows` (data.this_season) that has no result yet.
    Returns (file, what happened) for each."""
    now = time.time() if now is None else now
    out = []
    if rows.empty:
        return out
    for (year, week), mine in rows.groupby(["season", "week"]):
        if mine["credited_home"].notna().any():
            continue                                    # a week with a result in is past freezing
        lock = float(mine["locked_at"].iloc[0])
        before = now <= lock
        path = path_for(year, week)
        held = read(path)
        if held is not None and held.get("before_deadline") and not before:
            out.append((path, "kept as it was - already frozen before the deadline"))
            continue
        if held is not None and not held.get("before_deadline") and not before:
            out.append((path, "kept as it was - a late one is already there"))
            continue
        columns = [c for c in KEPT if c in mine.columns] + data.model_columns(mine)
        games = [{k: _clean(v) for k, v in record.items() if _clean(v) is not None}
                 for record in mine[columns].to_dict("records")]
        priced = sum(1 for g in games if g.get("line_deadline") is not None or g.get("line_used") is not None)
        body = {"training": VERSION, "season": int(year), "week": int(week), "made": now, "locks": lock,
                "before_deadline": before, "games": games}
        try:
            path.write_text(json.dumps(body, indent=1), encoding="utf-8")
        except OSError as exc:
            out.append((path, f"could not be written: {exc}"))
            continue
        out.append((path, f"{len(games)} games frozen, {priced} with a line"
                          + ("" if before else " - LATE: taken after the deadline, and marked so")))
    return out


def frozen() -> pd.DataFrame:
    """Every game frozen before its deadline, one row each."""
    rows = []
    try:
        paths = sorted(folder().glob("*.json"))
    except OSError:
        return pd.DataFrame()
    for path in paths:
        found = read(path)
        if found is None or not found.get("before_deadline"):
            continue
        for game in found["games"]:
            rows.append({**game, "frozen_at": found.get("made")})
    return pd.DataFrame(rows)


def overlay(rows: pd.DataFrame) -> pd.DataFrame:
    """This season's table with each frozen game's numbers put back as they
    stood when it was frozen - whatever the dashboard has learned since."""
    kept = frozen()
    if rows.empty or kept.empty:
        return rows
    out = rows.copy()
    out["frozen_at"] = np.nan
    where = {key: i for i, key in zip(out.index, out["game"])}
    carried = [c for c in kept.columns if c not in ("season", "week", "home", "away", "game")]
    for column in carried:
        if column not in out.columns:
            out[column] = np.nan if column != "pool_favourite" else ""
    put_back = ("line_deadline", "line_opening", "win_deadline", "total_deadline", "taken_at", "models_at",
                "frozen_at")
    for record in kept.to_dict("records"):
        i = where.get(record.get("game"))
        if i is None:
            continue
        # every model's number as it was frozen: one the file has gained since is not one the card saw
        for column in list(put_back) + data.model_columns(out):
            value = record.get(column)
            out.at[i, column] = np.nan if value is None or (isinstance(value, float) and np.isnan(value)) else value
    return out
