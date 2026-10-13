"""The pool's lines (ACQL rule): a favourite of 6.5+ must win by at least the line.

Rule, as the commissioner grades it: a game with a pool line credits the
favourite only if it wins by at least the line (a win by exactly the line
counts; a half-point line needs the next whole number). Otherwise the
underdog is credited. A straight-up game credits the winner.

Lines come from two places:
  * entered  - the commissioner's posted line, typed in (CLI ``lines`` or the
               Weekly Picks page). Always wins.
  * estimated - before he posts, his measured habit applied to the betting
               spread: favourites of ``lined_from`` (6.5) or more get the next
               whole number above the spread, at least ``smallest_line`` (7).
               Flagged POOL_LINE_ESTIMATED so you know to enter the real one.

P(credited) uses a normal margin model (sd 13.45, half-point continuity
correction). Its centre is anchored to the real betting spread when there is
one - the line the commissioner sets his pool line from - shifted only by how
far the pick model's probability differs from the market's:
    mean = -home_spread + 13.45 * (Phi^-1(p_model) - Phi^-1(p_market)).
Without a spread it is 13.45 * Phi^-1(p_model). (Converting a de-vigged
moneyline straight to a margin overstates big favourites by ~2 points, which
matters most exactly on lined games.)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import NormalDist

import numpy as np
import pandas as pd

from .teams import normalize_team

SD = 13.45
_N = NormalDist()

DDL = """CREATE TABLE IF NOT EXISTS pool_lines (
    season INTEGER NOT NULL, week INTEGER NOT NULL, game_id VARCHAR NOT NULL,
    favourite_team VARCHAR NOT NULL, line DOUBLE NOT NULL, entered_at TIMESTAMP,
    PRIMARY KEY (season, week, game_id))"""


def need(line: float) -> int:
    """Points the favourite must win by: a whole-number line needs that many, 6.5 needs 7."""
    return math.ceil(line - 1e-9)


def estimate(home_spread: float | None, lined_from: float = 6.5, smallest: float = 7.0) -> tuple[str, float] | None:
    """('home'|'away', line) from the commissioner's habit, or None for a straight game."""
    if home_spread is None or (isinstance(home_spread, float) and math.isnan(home_spread)):
        return None
    quoted = round(abs(home_spread) * 2) / 2
    if quoted < lined_from:
        return None
    return ("home" if home_spread < 0 else "away"), float(max(smallest, math.floor(quoted) + 1))


def expected_margin(p_home: float) -> float:
    p = min(max(float(p_home), 1e-4), 1 - 1e-4)
    return SD * _N.inv_cdf(p)


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def credited_home_probability(p_home: float, fav_side: str | None, line: float | None,
                              home_spread: float | None = None, p_market: float | None = None) -> float:
    """P(home is credited) under the pool rule, from the model's home-win probability."""
    if p_home is None or (isinstance(p_home, float) and math.isnan(p_home)):
        return float("nan")
    if fav_side is None or line is None or (isinstance(line, float) and math.isnan(line)):
        return float(p_home)
    if _ok(home_spread) and _ok(p_market):
        mu_home = -float(home_spread) + expected_margin(p_home) - expected_margin(p_market)
    else:
        mu_home = expected_margin(p_home)
    mu_fav = mu_home if fav_side == "home" else -mu_home
    p_fav = 1 - _N.cdf((need(line) - 0.5 - mu_fav) / SD)
    return p_fav if fav_side == "home" else 1 - p_fav


def credited_side(home_score, away_score, fav_side: str | None, line: float | None) -> str | None:
    """'home', 'away' or None (a straight game that ended level)."""
    margin = float(home_score) - float(away_score)
    if fav_side is None or line is None or (isinstance(line, float) and math.isnan(line)):
        return None if margin == 0 else ("home" if margin > 0 else "away")
    fav_margin = margin if fav_side == "home" else -margin
    covered = fav_margin >= need(line)
    return fav_side if covered else ("away" if fav_side == "home" else "home")


# ---------------------------------------------------------------- storage
def ensure_table(con) -> None:
    con.execute(DDL)


def set_lines(con, season: int, week: int, entries: list[tuple[str, float]]) -> list[str]:
    """Store posted lines, each (favourite team, line). Returns the game_ids set.
    A line of 0 clears a game's entered line (back to straight / estimated)."""
    ensure_table(con)
    games = con.execute("SELECT game_id, home_team, away_team FROM games WHERE season=? AND week=?",
                        [season, week]).df()
    done = []
    for team, line in entries:
        code = normalize_team(team)
        row = games[(games.home_team == code) | (games.away_team == code)]
        if row.empty:
            raise ValueError(f"{team!r} has no game in {season} week {week}")
        gid = row.iloc[0].game_id
        if float(line) <= 0:
            con.execute("DELETE FROM pool_lines WHERE season=? AND week=? AND game_id=?", [season, week, gid])
        else:
            con.execute("INSERT OR REPLACE INTO pool_lines VALUES (?, ?, ?, ?, ?, ?)",
                        [season, week, gid, code, float(line),
                         datetime.now(timezone.utc).replace(tzinfo=None)])
        done.append(gid)
    return done


def entered(con, season: int, week: int) -> pd.DataFrame:
    """Lines typed in for a week (works on read-only connections; empty if none yet)."""
    try:
        return con.execute("SELECT * FROM pool_lines WHERE season=? AND week=?", [int(season), int(week)]).df()
    except Exception:  # noqa: BLE001 - table not created yet on an old database
        return pd.DataFrame(columns=["season", "week", "game_id", "favourite_team", "line", "entered_at"])


def lines_for_slate(con, slate: pd.DataFrame, pool_cfg: dict) -> pd.DataFrame:
    """Per game: pool_line_team, pool_line, line_source ('entered', 'estimated' or 'none')."""
    rows = []
    posted = {}
    if con is not None and len(slate):
        for (s, w), _ in slate.groupby(["season", "week"]):
            for r in entered(con, int(s), int(w)).itertuples():
                posted[r.game_id] = (r.favourite_team, r.line)
    for r in slate.itertuples():
        if r.game_id in posted:
            team, line = posted[r.game_id]
            rows.append((r.game_id, team, float(line), "entered"))
            continue
        est = estimate(getattr(r, "market_home_spread", np.nan), float(pool_cfg.get("lined_from", 6.5)),
                       float(pool_cfg.get("smallest_line", 7))) if pool_cfg.get("estimate_lines", True) else None
        if est is None:
            rows.append((r.game_id, None, np.nan, "none"))
        else:
            side, line = est
            rows.append((r.game_id, r.home_team if side == "home" else r.away_team, line, "estimated"))
    return pd.DataFrame(rows, columns=["game_id", "pool_line_team", "pool_line", "line_source"])


def apply(frame: pd.DataFrame, prob_col: str) -> pd.Series:
    """credited_home_probability for each row (needs home_team, pool_line_team, pool_line)."""
    nan = pd.Series([np.nan] * len(frame), index=frame.index)
    teams = frame["pool_line_team"] if "pool_line_team" in frame else pd.Series([None] * len(frame), index=frame.index)
    lines = frame["pool_line"] if "pool_line" in frame else nan
    spread = frame["market_home_spread"] if "market_home_spread" in frame else nan
    market = next((frame[c] for c in ("market_home_prob", "market_home_probability", "market") if c in frame), nan)
    out = []
    for p, home, team, line, sp, pm in zip(frame[prob_col], frame["home_team"], teams, lines, spread, market):
        fav = ("home" if team == home else "away") if isinstance(team, str) and team else None
        out.append(credited_home_probability(p, fav, line, sp, pm))
    return pd.Series(out, index=frame.index)
