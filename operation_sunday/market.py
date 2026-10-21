"""Thursday market snapshots and pool lines, read from the dashboard (read-only).

The dashboard already fetches lines from The Odds API (acql/feeds/odds.py; the
noon "ACQL Deadeye email" task and every "Update lines" press) and keeps each
fetch with its time in `history`. For each game this takes the LAST fetch at
or before the cutoff: its time is the snapshot's `taken_at`, so the cutoff
rule in features.py can check it. Moneyline win chances are kept only as the
latest value (no history), so they are used only when that latest fetch is
itself before the cutoff; otherwise the spread is used.

The odds store is keyed by week number only, so a stored week is accepted
only if its recorded kickoffs match this season's fixtures (within a day).

Pool lines: the commissioner's real lines typed into the dashboard
(acql/feeds/lines.pool_lines) take precedence over the habit rule.

Nothing here writes to the dashboard or spends an Odds API request.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .data import FRANCHISE
from .features import MarketSnapshot


def _code(c: str) -> str:
    c = str(c).upper()
    return FRANCHISE.get(c, c)


def _game_index(week_games: pd.DataFrame) -> dict:
    return {(r.away, r.home): r for r in week_games.itertuples()}


def snapshots_from_store(store: dict, week_games: pd.DataFrame, week: int, cutoff: datetime
                         ) -> tuple[list[MarketSnapshot], list[str]]:
    notes: list[str] = []
    entry = (store.get("weeks") or {}).get(str(week))
    if not isinstance(entry, dict) or not entry.get("history"):
        return [], [f"no fetched lines stored for week {week}"]
    games = _game_index(week_games)
    kick = entry.get("kickoff") or {}
    matched_keys = {}
    for key in {k for h in entry["history"] if isinstance(h, dict) for k in (h.get("lines") or {})}:
        try:
            away, home = (_code(x) for x in key.split("@"))
        except ValueError:
            continue
        g = games.get((away, home))
        if g is None:
            continue
        ko = kick.get(key)
        if ko:
            when = pd.Timestamp(str(ko).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.tz_localize("UTC")
            if abs((when - g.kickoff_utc).total_seconds()) > 86400:
                notes.append(f"{key}: stored kickoff {ko} is not this season's game; ignored")
                continue
        matched_keys[key] = g.game_id
    cut = cutoff.timestamp()
    latest_at = float(entry.get("at") or 0)
    out = []
    for key, gid in matched_keys.items():
        before = [(float(h["at"]), h["lines"][key]) for h in entry["history"]
                  if isinstance(h, dict) and key in (h.get("lines") or {}) and float(h.get("at", 0)) <= cut]
        if not before:
            notes.append(f"{key}: no line fetched before the cutoff")
            continue
        at, spread = max(before)
        prob = (entry.get("win") or {}).get(key) if latest_at <= cut else None
        out.append(MarketSnapshot(gid, datetime.fromtimestamp(at, timezone.utc), prob, float(spread),
                                  "dashboard odds store (The Odds API median)"))
    missing = len(week_games) - len(out)
    if missing:
        notes.append(f"{missing} game(s) without a pre-cutoff market line")
    return out, notes


def from_dashboard(week_games: pd.DataFrame, week: int, cutoff: datetime):
    try:
        from acql.feeds import odds
        store = odds._read()  # read-only copy
    except Exception as exc:  # noqa: BLE001 - no dashboard database on this computer
        return [], [f"dashboard odds store unavailable ({type(exc).__name__})"]
    return snapshots_from_store(store, week_games, week, cutoff)


def pool_lines_from_dashboard(season: int, week: int) -> dict:
    """{frozenset(codes): (favourite code, points)} from the commissioner's sheet."""
    try:
        from acql.feeds import lines
        raw = lines.pool_lines(season, week)
    except Exception:  # noqa: BLE001
        return {}
    return {frozenset(_code(t) for t in k): (_code(f), float(p)) for k, (f, p) in raw.items()}
