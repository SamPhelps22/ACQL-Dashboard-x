"""Game data: load, normalise, validate, version.

Source: nflverse games.csv (one row per game, kickoff in US Eastern wall
time). Every column is classified by WHEN it is known, because that decides
whether it may feed a Thursday forecast:

  schedule-known (published before the season): teams, date, kickoff, site,
      division game, stadium roof type.
  result (known only after the game): scores.
  closing market (known only at kickoff): spread_line, total_line, moneylines.
      Benchmark-only. A Thursday forecast may use a market snapshot only if
      its own timestamp is at or before the cutoff (see features.MarketSnapshot).
  game-day observations: starting QB names, temperature, wind, whether a
      retractable roof was closed. Never features; QB names are used only to
      SLICE retrospective reports.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .tz import get_zone

#: relocated franchises keep one code so their history carries over
FRANCHISE = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA", "JAC": "JAX", "WSH": "WAS"}
NFLVERSE_ZONE = "America/New_York"
POSTSEASON = {"WC", "DIV", "CON", "SB", "POST"}

COLUMNS = [
    "game_id", "season", "week", "game_type", "kickoff_utc", "kickoff_time_known",
    "home", "away", "home_score", "away_score", "neutral", "div_game", "roof",
    "status", "close_spread", "close_total", "home_ml", "away_ml",
    "home_qb", "away_qb",
]


@dataclass
class Dataset:
    games: pd.DataFrame
    version: str
    source: str
    loaded_at: datetime
    warnings: list = field(default_factory=list)


def _kickoffs(day: pd.Series, clock: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Eastern wall time -> UTC. A missing clock becomes 00:00 local (the
    earliest it could be), flagged, so a deadline built on it errs early."""
    zone = get_zone(NFLVERSE_ZONE)
    known = clock.notna() & clock.astype(str).str.match(r"^\d{1,2}:\d{2}$")
    out = []
    for d, c, k in zip(day.astype(str), clock.astype(str), known):
        local = datetime.strptime(f"{d} {c if k else '00:00'}", "%Y-%m-%d %H:%M")
        out.append(local.replace(tzinfo=zone).astimezone(get_zone("UTC")))
    return pd.Series(pd.to_datetime(out, utc=True), index=day.index), known


def normalise_nflverse(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(index=raw.index)
    df["game_id"] = raw["game_id"].astype(str)
    df["season"] = raw["season"].astype(int)
    df["week"] = raw["week"].astype(int)
    df["game_type"] = raw["game_type"].astype(str)
    df["kickoff_utc"], df["kickoff_time_known"] = _kickoffs(raw["gameday"], raw["gametime"])
    df["home"] = raw["home_team"].astype(str).replace(FRANCHISE)
    df["away"] = raw["away_team"].astype(str).replace(FRANCHISE)
    df["home_score"] = pd.to_numeric(raw["home_score"], errors="coerce")
    df["away_score"] = pd.to_numeric(raw["away_score"], errors="coerce")
    df["neutral"] = raw.get("location", pd.Series("Home", index=raw.index)).astype(str).eq("Neutral")
    df["div_game"] = pd.to_numeric(raw["div_game"], errors="coerce").fillna(0).astype(int) if "div_game" in raw else 0
    roof = raw.get("roof", pd.Series(np.nan, index=raw.index)).astype(object)
    # closed/open is decided on game day: schedule-known fact is only "retractable"
    df["roof"] = roof.map({"dome": "dome", "outdoors": "outdoors", "closed": "retractable",
                           "open": "retractable"}).fillna("unknown")
    if "stadium_id" in raw:
        # the stadium's roof TYPE is fixed and known in advance; fill upcoming games from history
        known = df["roof"].where(df["roof"] != "unknown")
        by_stadium = known.groupby(raw["stadium_id"]).agg(lambda s: s.mode().iloc[0] if s.notna().any() else np.nan)
        fill = raw["stadium_id"].map(by_stadium)
        df["roof"] = np.where(df["roof"] == "unknown", fill.fillna("unknown"), df["roof"])
    df["close_spread"] = pd.to_numeric(raw["spread_line"], errors="coerce") if "spread_line" in raw else np.nan
    df["close_total"] = pd.to_numeric(raw["total_line"], errors="coerce") if "total_line" in raw else np.nan
    df["home_ml"] = pd.to_numeric(raw["home_moneyline"], errors="coerce") if "home_moneyline" in raw else np.nan
    df["away_ml"] = pd.to_numeric(raw["away_moneyline"], errors="coerce") if "away_moneyline" in raw else np.nan
    df["home_qb"] = raw.get("home_qb_name")
    df["away_qb"] = raw.get("away_qb_name")
    played = df["home_score"].notna() & df["away_score"].notna()
    df["status"] = np.where(played, "final", "scheduled")
    return df[COLUMNS].reset_index(drop=True)


def validate(games: pd.DataFrame, now: datetime | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Drop what can't be trusted and say so. Returns (clean games, warnings)."""
    warnings: list[str] = []
    g = games.copy()
    dup = g.duplicated("game_id", keep="last")
    if dup.any():
        warnings.append(f"duplicate game_id rows dropped (kept last): {sorted(g.loc[dup, 'game_id'])[:10]}")
        g = g[~dup]
    pair = g.duplicated(["season", "week", "home", "away"], keep="last")
    if pair.any():
        warnings.append(f"same matchup listed twice in one week, kept last: {int(pair.sum())} rows")
        g = g[~pair]
    same = g["home"] == g["away"]
    if same.any():
        warnings.append(f"games with the same team on both sides dropped: {int(same.sum())}")
        g = g[~same]
    neg = (g["home_score"] < 0) | (g["away_score"] < 0)
    if neg.any():
        warnings.append(f"negative scores dropped: {int(neg.sum())}")
        g = g[~neg]
    unknown = ~g["kickoff_time_known"].astype(bool) & (g["season"] >= 2006)
    if unknown.any():
        warnings.append(f"{int(unknown.sum())} games have no kickoff clock; treated as 00:00 local (deadline errs early)")
    # kickoffs should fall in season order; a week whose games straddle >9 days is suspicious
    span = g.groupby(["season", "week", g["game_type"].isin(POSTSEASON)])["kickoff_utc"].agg(lambda s: (s.max() - s.min()).days)
    wide = span[span > 9]
    if len(wide):
        warnings.append(f"weeks spanning more than 9 days (postponement or bad kickoff?): {list(wide.index[:5])}")
    if now is not None:
        stale = (g["status"] == "scheduled") & (g["kickoff_utc"] < pd.Timestamp(now) - pd.Timedelta(days=7))
        if stale.any():
            g.loc[stale, "status"] = "canceled"
            warnings.append(f"{int(stale.sum())} games >7 days past kickoff with no score marked canceled")
        future_final = (g["status"] == "final") & (g["kickoff_utc"] > pd.Timestamp(now))
        if future_final.any():
            warnings.append(f"{int(future_final.sum())} games have a score but kick off in the future; scores ignored")
            g.loc[future_final, ["home_score", "away_score"]] = np.nan
            g.loc[future_final, "status"] = "scheduled"
    g = g.sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)
    return g, warnings


def version_of(games: pd.DataFrame) -> str:
    cols = ["game_id", "kickoff_utc", "home", "away", "home_score", "away_score", "status"]
    buf = games[cols].astype(str).to_csv(index=False).encode()
    return "ds-" + hashlib.sha256(buf).hexdigest()[:12]


def load_csv(path: str | Path, now: datetime | None = None) -> Dataset:
    raw = pd.read_csv(path, low_memory=False)
    games, warnings = validate(normalise_nflverse(raw), now)
    mtime = datetime.fromtimestamp(Path(path).stat().st_mtime, get_zone("UTC"))
    return Dataset(games, version_of(games), str(path), mtime, warnings)


def load_snapshots(path: str | Path):
    """Market snapshots CSV: game_id, taken_at (ISO with zone), and home_prob
    and/or home_spread (+ = home favoured), optional source. A row without a
    zone on its timestamp is rejected - its cutoff status could not be known."""
    from .features import MarketSnapshot
    from .tz import parse_utc
    df = pd.read_csv(path)
    out = []
    for r in df.to_dict("records"):
        hp = r.get("home_prob")
        hs = r.get("home_spread")
        out.append(MarketSnapshot(str(r["game_id"]), parse_utc(r["taken_at"]),
                                  None if hp is None or pd.isna(hp) else float(hp),
                                  None if hs is None or pd.isna(hs) else float(hs), str(r.get("source", ""))))
    return out


def fetch(url: str, dest: Path, timeout: float = 60.0) -> Path:
    """Download games.csv to dest (atomically). Raises on any failure."""
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - fixed https source
        body = resp.read()
    pd.read_csv(io.BytesIO(body), nrows=5)  # must parse before it replaces the cache
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    return dest


# ---- a labelled synthetic league, for tests and offline demos --------------------
def synthetic_games(seasons=range(2101, 2109), teams: int = 16, seed: int = 7) -> pd.DataFrame:
    """SYNTHETIC - NOT REAL NFL. Teams SYN01..; seasons 2101+.

    Each season: `teams-1` weeks of a round robin, Sunday 13:00 Eastern, with
    a Thursday 20:15 game each week. True strengths drift, so models that
    learn from results have something real to find."""
    rng = np.random.default_rng(seed)
    names = [f"SYN{i:02d}" for i in range(1, teams + 1)]
    strength = rng.normal(0, 4, teams)
    rows = []
    zone = get_zone(NFLVERSE_ZONE)
    for season in seasons:
        strength = 0.6 * strength + rng.normal(0, 2.5, teams)
        sep1 = datetime(season - 100 + 0, 9, 1)  # calendar year = season - 100 (real calendar)
        start = sep1
        while start.weekday() != 6:
            start += timedelta(days=1)
        order = list(range(teams))
        for week in range(1, teams):
            sunday = start + timedelta(weeks=week)
            for k in range(teams // 2):
                h, a = order[k], order[teams - 1 - k]
                if (week + k) % 2:
                    h, a = a, h
                margin = strength[h] - strength[a] + 2.0 + rng.normal(0, 13)
                total = 44 + rng.normal(0, 10)
                hs = max(0, int(round((total + margin) / 2)))
                as_ = max(0, int(round((total - margin) / 2)))
                when = (sunday - timedelta(days=3)).replace(hour=20, minute=15) if k == 0 else sunday.replace(hour=13)
                spread = round((strength[h] - strength[a] + 2.0 + rng.normal(0, 1.5)) * 2) / 2
                rows.append({
                    "game_id": f"{season}_{week:02d}_{names[a]}_{names[h]}", "season": season, "week": week,
                    "game_type": "REG", "kickoff_utc": pd.Timestamp(when.replace(tzinfo=zone)).tz_convert("UTC"),
                    "kickoff_time_known": True, "home": names[h], "away": names[a],
                    "home_score": float(hs), "away_score": float(as_), "neutral": False,
                    "div_game": int((h // 4) == (a // 4)), "roof": "outdoors", "status": "final",
                    "close_spread": spread, "close_total": 44.0, "home_ml": np.nan, "away_ml": np.nan,
                    "home_qb": f"QB {names[h]}", "away_qb": f"QB {names[a]}",
                })
                strength[h] += rng.normal(0, 0.3)
            order = [order[0]] + [order[-1]] + order[1:-1]
    return pd.DataFrame(rows)[COLUMNS]
