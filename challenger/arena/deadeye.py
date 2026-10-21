"""Deadeye's forecasts, captured through Deadeye's own code (read-only).

Three Deadeye sources exist, and none is a record written at the time:

  deadeye_proxy        Deadeye's own historical stand-in (acql.model.backtest):
                       a rating model on past scores only, its chances widened
                       15% (backtest.home_wins). Its constants were fitted on
                       2011-2019 and checked on 2020-2025, so 2011-2019 is
                       in-sample for it. Read at each week's start
                       (backtest.rate's week snapshots) - the same deadline as
                       Challenger - not with the same-week updates Deadeye's
                       own replay uses.
  deadeye_core_closing Deadeye's margin curve (acql.analytics.cover_chance,
                       sd 8.7) applied to the nflverse CLOSING spread, with no
                       computer-model nudge: Deadeye's live engine with the
                       consensus share at zero. Closing lines are later than
                       the ACQL deadline, which flatters it.
  deadeye_live         Deadeye's live rule in full (acql.model.pricing.price:
                       market + a share of the Prediction Tracker consensus,
                       widened by model disagreement) run on the weekly
                       Prediction Tracker files kept in the repository - only
                       2026 weeks 3, 4, 5 and 7 exist. The share is the default
                       25% (the live app refits it from its own database,
                       which is not in the repository). Weeks 3-5's files were
                       first committed after that week's first kickoff, so
                       those are retrospective reconstructions; week 7's was
                       committed before its kickoff.

Nothing here changes Deadeye; every call is a read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

from ..config import ROOT
from ..data import franchise


def _home_win_chance(margin: float, sd: float) -> float:
    """Chance the home side wins outright from a Deadeye home margin, a tie counted as half.

    The same arithmetic as acql.model.backtest.home_wins, at a chosen width.
    """
    from acql import analytics

    if margin >= 0:
        win = analytics.cover_chance(margin, 1, sd)
        tie = analytics.cover_chance(margin, 0, sd) - win
        return win + tie / 2
    win = analytics.cover_chance(-margin, 1, sd)
    tie = analytics.cover_chance(-margin, 0, sd) - win
    return 1 - (win + tie / 2)


def _key(season, week, home, away) -> tuple:
    return int(season), int(week), franchise(home), franchise(away)


def _game_index(games: pd.DataFrame) -> dict:
    reg = games[games["game_type"] == "REG"]
    return {_key(r.season, r.week, r.home, r.away): r.game_id for r in reg.itertuples()}


def proxy(games: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Deadeye's backtest proxy, read at each week's start, for every game it rates."""
    from acql.model import backtest

    hist = backtest.load_games()
    rated, snapshots = backtest.rate(hist)
    index = _game_index(games)
    rows, missed, dupes = [], 0, 0
    seen = set()
    for g in rated:
        ratings = snapshots.get((g.season, g.week))
        if ratings is None:
            continue
        margin = ratings.margin(g.home, g.away)
        gid = index.get(_key(g.season, g.week, g.home, g.away))
        if gid is None:
            missed += 1
            continue
        if gid in seen:
            dupes += 1
            continue
        seen.add(gid)
        rows.append({"model": "deadeye_proxy", "game_id": gid, "deadeye_margin": margin,
                     "deadeye_margin_inweek": g.rated, "p_home": backtest.home_wins(margin)})
    out = pd.DataFrame(rows)
    return out, {"rated": len(rated), "matched": len(out), "unmatched": missed, "duplicates": dupes,
                 "seasons": f"{min(g.season for g in rated)}-{max(g.season for g in rated)}"}


def core_closing(games: pd.DataFrame) -> pd.DataFrame:
    """Deadeye's margin curve on the closing spread (no model nudge)."""
    from acql import analytics

    g = games[games["spread_line"].notna()]
    p = [_home_win_chance(float(s), analytics.SPREAD_SD) for s in g["spread_line"]]
    return pd.DataFrame({"model": "deadeye_core_closing", "game_id": g["game_id"].to_numpy(),
                         "deadeye_margin": g["spread_line"].to_numpy(), "p_home": p})


LIVE_FILES = {3: "nflpredictions week 3.csv", 4: "nflpredictions week 4.csv",
              5: "nflpredictions week 5.csv", 7: "nflpredictions week 7.csv"}


def _first_commit(path: Path) -> pd.Timestamp | None:
    try:
        out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%cI", "--", path.name], cwd=path.parent,
                             capture_output=True, text=True, timeout=20).stdout.strip().splitlines()
        return pd.Timestamp(out[-1]).tz_convert("UTC") if out else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _nflverse_code(code: str) -> str:
    return franchise({"lar": "LA"}.get(code, code.upper()))


def live(games: pd.DataFrame, season: int = 2026, files: dict[int, str] | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Deadeye's live pricing rule on each weekly Prediction Tracker file in the repo."""
    from acql.model import predictions, pricing

    files = files or LIVE_FILES
    index = _game_index(games)
    kick = games.set_index("game_id")["kickoff_utc"]
    rows, notes = [], []
    for week, name in sorted(files.items()):
        path = ROOT / name
        if not path.exists():
            continue
        forecasts = predictions.read_csv(path)
        slate = predictions.slate_from(forecasts)
        totals = sorted(f.total for f in forecasts if getattr(f, "total", None))
        ctx = pricing.Context(
            week=week, forecasts={g.index: f for g, f in zip(slate, forecasts)},
            lean=predictions.home_lean(forecasts), typical=predictions.typical_disagreement(forecasts),
            weight=predictions.CONSENSUS_WEIGHT, typical_total=totals[len(totals) // 2] if totals else 0.0)
        committed = _first_commit(path)
        matched = 0
        for game, f in zip(slate, forecasts):
            price = pricing.price(game, ctx)
            if price.margin is None:
                continue
            gid = index.get(_key(season, week, _nflverse_code(f.home_code), _nflverse_code(f.road_code)))
            if gid is None:
                continue
            matched += 1
            pregame = committed is not None and committed < kick[gid]
            rows.append({"model": "deadeye_live", "game_id": gid, "deadeye_margin": price.margin,
                         "deadeye_sd": price.sd, "p_home": _home_win_chance(price.margin, price.sd),
                         "source_file": name, "file_first_committed_utc": committed,
                         "provably_pregame": bool(pregame)})
        first_kick = games[(games["season"] == season) & (games["week"] == week)]["kickoff_utc"].min()
        notes.append({"week": week, "file": name, "games": len(forecasts), "matched": matched,
                      "file_first_committed_utc": str(committed), "week_first_kickoff_utc": str(first_kick),
                      "committed_before_first_kickoff": bool(committed is not None and committed < first_kick),
                      "consensus_weight": predictions.CONSENSUS_WEIGHT})
    return pd.DataFrame(rows), notes


def pool_line(home_margin: float) -> float | None:
    """The commissioner's measured habit for posting a pool line (acql.model.backtest.pool_line)."""
    from acql.model import backtest

    return backtest.pool_line(home_margin)


def credited_home_proxy(home_margin: float, line: float | None, line_home_fav: bool | None) -> float:
    """Deadeye proxy's chance the home side is credited under a given pool line."""
    from acql.model import backtest

    if line is None:
        return backtest.home_wins(home_margin)
    fav_margin = home_margin if line_home_fav else -home_margin
    p_fav = backtest.favourite_credited(fav_margin, line)
    return p_fav if line_home_fav else 1 - p_fav


def credited_home_curve(home_margin: float, sd: float, line: float | None, line_home_fav: bool | None) -> float:
    """Deadeye's live curve: chance the home side is credited (analytics.predict_margin's arithmetic)."""
    from acql import analytics

    if line is None:
        return _home_win_chance(home_margin, sd)
    need = analytics.line_need(line)
    fav_margin = home_margin if line_home_fav else -home_margin
    if fav_margin >= 0:
        p_fav = analytics.cover_chance(fav_margin, need, sd)
    else:
        p_fav = 1 - analytics.cover_chance(-fav_margin, -need + 1, sd)
    return p_fav if line_home_fav else 1 - p_fav


def team_code(name: str) -> str:
    """A pick-sheet team name ('cincy', 'NEW ENGLAND') to an nflverse franchise code."""
    from acql.model import predictions

    code = predictions.team_code(name)
    return _nflverse_code(code) if code else ""
