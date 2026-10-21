"""Raw data: the nflverse schedule and play-by-play, fetched and fingerprinted.

Sources (see challenger/docs/DATA_SOURCES.md for coverage and caveats):

    schedule   nflverse-data release "schedules/games.csv": every game since
               1999 with kickoff date/time (US Eastern), teams, scores,
               venue, roof, surface, and - for the evaluation baselines only -
               the closing spread, total and moneylines.
    pbp        nflverse-data release "pbp/play_by_play_<season>.parquet":
               nflfastR play-by-play with EPA, success, dropbacks, sacks...

Every download is recorded in data/challenger/manifest.json with its URL,
UTC retrieval time, byte count and SHA-256, and each backtest copies the
manifest entries it used next to its predictions. Nothing is filled in: a
game without a score is unplayed, a missing kickoff time is recorded as
missing and given 13:00 ET only for ordering (flagged in `kickoff_assumed`).

Column groups matter for independence and leakage:

    OUTCOME_COLUMNS  known only after the game (scores, observed weather,
                     the QB who actually started)
    MARKET_COLUMNS   betting lines; never a feature of the market-free model
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CACHE

log = logging.getLogger("challenger.data")

RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
SCHEDULE_URL = f"{RELEASES}/schedules/games.csv"
PBP_URL = RELEASES + "/pbp/play_by_play_{season}.parquet"

#: Relocated franchises keep one identity (ratings carry across the move).
FRANCHISE = {"STL": "LA", "SD": "LAC", "OAK": "LV", "LAR": "LA", "JAC": "JAX", "WSH": "WAS", "ARZ": "ARI"}

OUTCOME_COLUMNS = (
    "home_score", "away_score", "result", "total", "overtime", "temp", "wind",
    "home_qb_id", "away_qb_id", "home_qb_name", "away_qb_name", "home_win",
)
MARKET_COLUMNS = (
    "spread_line", "home_moneyline", "away_moneyline", "total_line",
    "home_spread_odds", "away_spread_odds", "under_odds", "over_odds",
)


def franchise(code: object) -> str:
    text = str(code).strip().upper()
    return FRANCHISE.get(text, text)


# ---- fetching ---------------------------------------------------------------------
def _manifest_path() -> Path:
    return CACHE / "manifest.json"


def manifest() -> dict:
    try:
        return json.loads(_manifest_path().read_text())
    except (OSError, ValueError):
        return {}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _download(url: str, dest: Path, retries: int = 4) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=300) as response, open(part, "wb") as out:
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
            part.replace(dest)
            return
        except OSError as exc:  # network trouble: back off and retry
            log.warning("download failed (%s), attempt %d: %s", url, attempt + 1, exc)
            time.sleep(2 ** (attempt + 1))
    raise OSError(f"could not download {url}")


def _record(name: str, url: str, path: Path) -> dict:
    entry = {
        "url": url,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    book = manifest()
    book[name] = entry
    _manifest_path().parent.mkdir(parents=True, exist_ok=True)
    _manifest_path().write_text(json.dumps(book, indent=1, sort_keys=True))
    return entry


def schedule_path() -> Path:
    return CACHE / "raw" / "games.csv"


def pbp_path(season: int) -> Path:
    return CACHE / "raw" / "pbp" / f"play_by_play_{season}.parquet"


def fetch_schedule(force: bool = True) -> dict:
    """Download the schedule (always re-fetched by default: it carries new results)."""
    path = schedule_path()
    if force or not path.exists():
        _download(SCHEDULE_URL, path)
    return _record("schedule", SCHEDULE_URL, path)


def fetch_pbp(seasons, refresh: tuple[int, ...] = ()) -> list[dict]:
    """Download pbp for `seasons`; seasons in `refresh` are fetched even if cached."""
    out = []
    for season in seasons:
        path = pbp_path(season)
        url = PBP_URL.format(season=season)
        if season in refresh or not path.exists():
            _download(url, path)
            out.append(_record(f"pbp_{season}", url, path))
        elif f"pbp_{season}" not in manifest():
            out.append(_record(f"pbp_{season}", url, path))
    return out


# ---- loading ----------------------------------------------------------------------
def _kickoffs(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Kickoff in UTC from the Eastern date and time; 13:00 ET where the time is missing."""
    assumed = frame["gametime"].isna()
    clock = frame["gametime"].fillna("13:00")
    local = pd.to_datetime(frame["gameday"] + " " + clock, format="%Y-%m-%d %H:%M")
    eastern = local.dt.tz_localize("America/New_York", ambiguous=True, nonexistent="shift_forward")
    return eastern.dt.tz_convert("UTC"), assumed


def load_games(path: Path | None = None, frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """The schedule, one row a game, in kickoff order, with franchise codes.

    `home_win` is 1/0 for decided games, NaN for ties and unplayed games.
    """
    raw = frame if frame is not None else pd.read_csv(path or schedule_path(), low_memory=False)
    g = raw.copy()
    g["home_team_raw"], g["away_team_raw"] = g["home_team"], g["away_team"]
    g["home"] = g["home_team"].map(franchise)
    g["away"] = g["away_team"].map(franchise)
    g["kickoff_utc"], g["kickoff_assumed"] = _kickoffs(g)
    g["neutral"] = (g["location"].astype(str).str.lower() == "neutral").astype(int)
    g["completed"] = g["home_score"].notna() & g["away_score"].notna()
    margin = g["home_score"] - g["away_score"]
    g["home_win"] = np.where(~g["completed"] | (margin == 0), np.nan, (margin > 0).astype(float))
    g["playoff"] = (g["game_type"] != "REG").astype(int)
    g = g.sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)
    return g


def without_outcomes(games: pd.DataFrame) -> pd.DataFrame:
    """The schedule with every postgame column removed (what a forecast may see)."""
    return games.drop(columns=[c for c in OUTCOME_COLUMNS if c in games.columns])


def implied_chance(american) -> np.ndarray:
    """American odds to the implied chance (bookmaker margin still in)."""
    a = np.asarray(american, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(a < 0, -a / (-a + 100.0), 100.0 / (a + 100.0))


def available_pbp_seasons() -> list[int]:
    folder = CACHE / "raw" / "pbp"
    if not folder.exists():
        return []
    return sorted(int(p.stem.rsplit("_", 1)[1]) for p in folder.glob("play_by_play_*.parquet"))
