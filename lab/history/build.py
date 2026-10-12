"""Build the historical dataset from pinned raw inputs.

    python -m lab.history.build            fetch, build, verify, report
    python -m lab.history.build fetch      only download / extract the raw inputs
    python -m lab.history.build build      rebuild lab/data/history.db from them
    python -m lab.history.build verify     rebuild every record and compare
    python -m lab.history.build report     rewrite lab/reports/coverage.md

    --nflverse-file PATH   use a local copy of games.csv (must match the pinned sha256)

Raw inputs are never overwritten: a download that already matches its pin is
kept, and the app's database is copied out into an extract named by its own
hash, read through a read-only connection (never through acql.store, which can
rewrite the database in a fresh checkout - see CLAUDE.md).
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acql import lines, oddslock, predictions  # noqa: E402 - read-only reuse

from . import asof, schema  # noqa: E402

LAB_DATA = ROOT / "lab" / "data"
RAW = LAB_DATA / "raw"
DB_FILE = LAB_DATA / "history.db"
LOCK_FILE = Path(__file__).with_name("sources.lock.json")
REPORT_FILE = ROOT / "lab" / "reports" / "coverage.md"
STORE_DB = ROOT / "data" / "acql.db"
SCORES_CSV = ROOT / "acql" / "data" / "nfl_scores_2010_2026.csv"
PT_DROP = RAW / "predictiontracker"     # archived Prediction Tracker files, by hand
PT_SEASONS = PT_DROP / "seasons"        # its season archives, nfl10.csv ... nfl26.csv
PT_ARCHIVE_URL = "https://www.thepredictiontracker.com/{name}"
#: The season archives call the models' median "linemed"; the weekly files
#: (and acql.predictions) call it "linemedian". Renamed on reading, so the
#: same columns count as models whichever file a game came from.
PT_ARCHIVE_RENAMES = {"linemed": "linemedian"}
#: Bumped when the extract takes more from the store, so an older extract is
#: kept as it was rather than overwritten.
EXTRACT_VERSION = 2

# nflverse writes a few teams by an older or shorter code than the app does.
NFLVERSE_CODES = {"LA": "lar", "OAK": "lv", "SD": "lac", "STL": "lar"}
SCORES_CODES = {"AZ": "ari", "JAC": "jax", "OAK": "lv", "SD": "lac", "STL": "lar", "LAR": "lar"}

#: A store slate is taken for a season when it shares at least this share of
#: its games with that season's week and no other season comes close.
SEASON_MATCH_SHARE = 0.6
SEASON_MATCH_LEAST = 4

LINE_RULE_EVIDENCE = (
    "acql/analytics.py line_need: \"(sf by 13)\", 49ers 37-24, credited to San Francisco "
    "on the graded 2025 week 15 sheet; the rule as Sam states it")


# ---- small helpers ------------------------------------------------------------------
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def number(value: object) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text or text.upper() == "NA":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def schedule_code(abbr: str) -> str:
    code = NFLVERSE_CODES.get(abbr, abbr.lower())
    if code not in predictions.DISPLAY:
        raise ValueError(f"unknown team abbreviation in schedule: {abbr!r}")
    return code


def eastern_to_utc(day: str, clock: str) -> float:
    """A kickoff written in Eastern time, as seconds since 1970 UTC, with the
    app's own daylight-saving rule (oddslock._eastern_hours)."""
    date = dt.date.fromisoformat(day)
    hour, minute = (int(p) for p in clock.split(":")[:2])
    return float(calendar.timegm((date.year, date.month, date.day,
                                  hour + oddslock._eastern_hours(date), minute, 0, 0, 0, 0)))


def short_id(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def insert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    keys = list(row)
    conn.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                 [row[k] for k in keys])


# ---- raw inputs -------------------------------------------------------------------------
def load_lock() -> dict:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


def fetch_nflverse(local: Path | None = None, *, raw: Path = RAW, opener=None) -> Path:
    """games.csv at its pinned bytes, kept in lab/data/raw. Returns its path."""
    pin = load_lock()["nflverse_games"]
    dest = raw / "nflverse_games.csv"
    meta_path = raw / "nflverse_games.csv.meta.json"
    if dest.exists() and sha256(dest) == pin["sha256"] and meta_path.exists():
        return dest
    if dest.exists():
        raise SystemExit(f"{rel(dest)} exists but does not match its pin; move it aside first "
                         f"(raw inputs are never overwritten)")
    raw.mkdir(parents=True, exist_ok=True)
    if local is not None:
        data = Path(local).read_bytes()
        retrieved, basis = None, f"copied from a local file ({local}); when that was downloaded is not known"
    else:
        open_url = opener or urllib.request.urlopen
        with open_url(pin["url"], timeout=120) as response:
            data = response.read()
        retrieved, basis = time.time(), "downloaded by lab.history.build fetch at this time"
    found = hashlib.sha256(data).hexdigest()
    if found != pin["sha256"]:
        raise SystemExit(f"games.csv does not match its pin ({found[:12]} != {pin['sha256'][:12]})")
    dest.write_bytes(data)
    meta_path.write_text(json.dumps({"url": pin["url"], "sha256": found, "bytes": len(data),
                                     "retrieved_at": retrieved, "retrieved_at_basis": basis},
                                    indent=1, sort_keys=True), encoding="utf-8")
    return dest


def read_store(db_path: Path) -> dict:
    """The parts of the app's database this dataset uses, read-only.

    Left out on purpose: settings (sealed tokens), the Odds API key, and the
    coaches' own picks - only each sheet's games and line notes are taken.
    """
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        def kind(name: str) -> dict:
            return {k: json.loads(v) for k, v in
                    conn.execute("SELECT key, value FROM docs WHERE kind = ?", (name,))}
        odds = kind("odds")
        picks = {}
        for key, sheet in kind("picks").items():
            if isinstance(sheet, dict):
                picks[key] = {
                    "source": sheet.get("source", ""),
                    "imported": sheet.get("imported"),
                    "games": [{"away": g.get("away", ""), "home": g.get("home", ""),
                               "note": g.get("note", "")}
                              for g in sheet.get("games") or [] if isinstance(g, dict)],
                }
        return {
            "forecasts": kind("forecasts"),
            "odds_weeks": odds.get("weeks") or {},
            "spreads": kind("spreads"),
            "picks": picks,
            "weights": kind("weights"),
        }
    finally:
        conn.close()


def extract_store(db_path: Path = STORE_DB, *, raw: Path = RAW) -> Path:
    """Copy the store's relevant parts to raw/, named by the database's hash."""
    digest = sha256(db_path)
    dest = raw / f"store_extract-v{EXTRACT_VERSION}-{digest[:16]}.json"
    if dest.exists():
        return dest
    raw.mkdir(parents=True, exist_ok=True)
    body = {"database": rel(db_path), "database_sha256": digest, "store": read_store(db_path)}
    dest.write_text(json.dumps(body, indent=1, sort_keys=True), encoding="utf-8")
    return dest


def default_pt_files() -> list[Path]:
    found = sorted(ROOT.glob("nflpredictions*.csv"))
    if PT_DROP.is_dir():
        found += sorted(PT_DROP.glob("*.csv"))
    return found


@dataclass
class Inputs:
    games_csv: Path
    games_meta: dict
    store_extract: Path | None
    scores_csv: Path | None
    pt_files: list[Path] = field(default_factory=list)
    pt_archives: list[Path] = field(default_factory=list)


def default_pt_archives() -> list[Path]:
    return sorted(p for p in PT_SEASONS.glob("nfl*.csv") if archive_season(p) is not None) \
        if PT_SEASONS.is_dir() else []


def default_inputs() -> Inputs:
    games_csv = RAW / "nflverse_games.csv"
    meta = json.loads((RAW / "nflverse_games.csv.meta.json").read_text(encoding="utf-8"))
    digest = sha256(STORE_DB)
    extract = RAW / f"store_extract-v{EXTRACT_VERSION}-{digest[:16]}.json"
    return Inputs(games_csv, meta, extract if extract.exists() else None,
                  SCORES_CSV if SCORES_CSV.exists() else None, default_pt_files(),
                  default_pt_archives())


# ---- importers ----------------------------------------------------------------------------
class Slates:
    """(season, week, pair of team codes) -> game, for matching other sources."""

    def __init__(self, conn: sqlite3.Connection):
        self.by_key: dict[tuple[int, int, frozenset], dict] = {}
        self.weeks: dict[tuple[int, int], set[frozenset]] = {}
        for game in asof.games(conn):
            pair = frozenset((game["home_code"], game["away_code"]))
            self.by_key[(game["season"], game["week"], pair)] = game
            self.weeks.setdefault((game["season"], game["week"]), set()).add(pair)

    def find(self, season: int, week: int, away: str, home: str) -> tuple[dict | None, bool]:
        """(game, flipped) - flipped when the source has home and away swapped."""
        game = self.by_key.get((season, week, frozenset((away, home))))
        if game is None:
            return None, False
        return game, game["home_code"] != home

    def infer_season(self, week: int, pairs: set[frozenset]) -> tuple[int | None, int]:
        """The one season whose week this slate is, and how many games matched."""
        pairs = {p for p in pairs if len(p) == 2 and all(p)}
        if not pairs:
            return None, 0
        scores = sorted(((len(pairs & slate), season) for (season, wk), slate in self.weeks.items()
                         if wk == week), reverse=True)
        if not scores:
            return None, 0
        best, season = scores[0]
        runner = scores[1][0] if len(scores) > 1 else 0
        need = max(min(SEASON_MATCH_LEAST, len(pairs)), int(len(pairs) * SEASON_MATCH_SHARE))
        if best >= need and runner < best / 2:
            return season, best
        return None, best


def import_schedule(conn, inputs: Inputs) -> int:
    meta = inputs.games_meta
    insert(conn, "sources", {
        "source_id": "nflverse_games", "kind": "schedule+results+undated_lines",
        "description": "nflverse nfldata games.csv (pinned commit)", "location": meta["url"],
        "sha256": sha256(inputs.games_csv), "bytes": inputs.games_csv.stat().st_size,
        "retrieved_at": meta.get("retrieved_at"), "retrieved_at_basis": meta["retrieved_at_basis"],
        "note": "The repository does not say when its lines were taken."})
    count = 0
    with open(inputs.games_csv, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["game_type"] != "REG":
                continue
            day, clock = row.get("gameday") or "", row.get("gametime") or ""
            known = bool(day and clock and clock != "NA" and day != "NA")
            gid = row["game_id"]
            insert(conn, "games", {
                "game_id": gid, "season": int(row["season"]), "week": int(row["week"]),
                "gameday": day or None, "gametime_et": clock if known else None,
                "away_team": row["away_team"], "home_team": row["home_team"],
                "away_code": schedule_code(row["away_team"]), "home_code": schedule_code(row["home_team"]),
                "neutral": int(row.get("location") == "Neutral"),
                "kickoff_utc": eastern_to_utc(day, clock) if known else None,
                "kickoff_basis": ("nflverse gameday + gametime (Eastern), DST by acql.oddslock"
                                  if known else "nflverse has no kickoff time for this game"),
                "source_id": "nflverse_games"})
            count += 1
            undated = ("nflverse does not say when its lines were taken")
            for market, home_value, away_value in (
                ("spread", number(row.get("spread_line")), None),
                ("total", number(row.get("total_line")), None),
                ("moneyline", number(row.get("home_moneyline")), number(row.get("away_moneyline"))),
            ):
                if home_value is None:
                    continue
                insert(conn, "odds_snapshots", {
                    "snapshot_id": f"nflverse:{gid}:{market}", "game_id": gid, "market": market,
                    "home_value": home_value, "away_value": away_value, "timing": "unspecified",
                    "as_of": None, "available_at": None, "available_at_basis": undated,
                    "orientation": "as_source", "source_id": "nflverse_games",
                    "raw": json.dumps({k: row.get(k) for k in (
                        "spread_line", "total_line", "home_moneyline", "away_moneyline")})})
    return count


def import_outcomes(conn, inputs: Inputs) -> dict:
    """Final scores from the schedule, each checked against the repo's own file."""
    theirs: dict[tuple, tuple[int, int]] = {}
    if inputs.scores_csv is not None:
        insert(conn, "sources", {
            "source_id": "repo_scores", "kind": "results_crosscheck",
            "description": "the repo's own scores file (used only to cross-check)",
            "location": rel(inputs.scores_csv), "sha256": sha256(inputs.scores_csv),
            "bytes": inputs.scores_csv.stat().st_size, "retrieved_at": None,
            "retrieved_at_basis": "committed to the repo; its origin is not recorded", "note": ""})
        with open(inputs.scores_csv, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                week = (row.get("Week") or "").strip()
                if (row.get("GameStatus") or "").strip() != "FINAL" or not week.startswith("WEEK "):
                    continue
                away = SCORES_CODES.get(row["AwayTeam"], row["AwayTeam"].lower())
                home = SCORES_CODES.get(row["HomeTeam"], row["HomeTeam"].lower())
                try:
                    theirs[(int(row["Season"]), int(week.split()[1]), away, home)] = (
                        int(float(row["AwayScore"])), int(float(row["HomeScore"])))
                except (TypeError, ValueError):
                    continue
    tally = {"agree": 0, "disagree": 0, "absent": 0}
    with open(inputs.games_csv, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["game_type"] != "REG":
                continue
            away_score, home_score = number(row["away_score"]), number(row["home_score"])
            if away_score is None or home_score is None:
                continue
            key = (int(row["season"]), int(row["week"]), schedule_code(row["away_team"]),
                   schedule_code(row["home_team"]))
            other = theirs.get(key)
            check = ("absent" if other is None else
                     "agree" if other == (int(away_score), int(home_score)) else "disagree")
            tally[check] += 1
            insert(conn, "outcomes", {
                "game_id": row["game_id"], "away_score": int(away_score), "home_score": int(home_score),
                "home_margin": int(home_score - away_score), "source_id": "nflverse_games",
                "crosscheck": check})
    return tally


def read_pt_models(path: Path, renames: dict[str, str] | None = None) -> list[dict]:
    """A Prediction Tracker file row by row, keeping each model's column name.

    The same columns as acql.predictions.read_csv counts as models: every
    "line..." column that is not the market or a summary. (That includes
    "linemidweek", which is the site's midweek market line, not a model -
    production counts it among the models, and so does this, so the lab
    prices a game the way production does. It is also kept as a line.)
    """
    out = []
    skip = predictions.MARKET_COLUMNS + predictions.SUMMARY_COLUMNS
    renames = renames or {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            row = {}
            for k, v in raw.items():
                key = (k or "").strip().casefold()
                row[renames.get(key, key)] = v
            road, home = str(row.get("road") or "").strip(), str(row.get("home") or "").strip()
            if not road or not home:
                continue
            models = [(k, number(v)) for k, v in row.items()
                      if k.startswith("line") and k not in skip and number(v) is not None]
            week = number(row.get("week"))
            out.append({"road": road, "home": home, "line": number(row.get("line")),
                        "lineopen": number(row.get("lineopen")),
                        "linemidweek": number(row.get("linemidweek")),
                        "week": None if week is None else int(week), "models": models})
    return out


def archive_season(path: Path) -> int | None:
    """nfl99.csv -> 1999, nfl10.csv -> 2010; None for any other name."""
    found = re.fullmatch(r"nfl(\d{2})\.csv", Path(path).name, flags=re.IGNORECASE)
    if not found:
        return None
    two = int(found.group(1))
    return 1900 + two if two >= 90 else 2000 + two


def _same_file(entry: dict, path: Path) -> bool:
    """Whether a stored predictions entry is exactly this file's content."""
    fresh = [(f.road, f.home, f.market, f.opening, list(f.opinions)) for f in predictions.read_csv(path)]
    stored = [(g.get("road"), g.get("home"), g.get("market"), g.get("opening"), list(g.get("opinions") or []))
              for g in entry.get("games", [])]
    return bool(fresh) and fresh == stored


def import_forecasts(conn, inputs: Inputs, slates: Slates, store: dict, notes: list[str]) -> dict[str, int]:
    """Prediction Tracker files (models + their market columns) and the store's typed lines."""
    seasons: dict[str, int] = {}          # store week key -> season, for the other store kinds
    stored = store.get("forecasts", {}) if store else {}
    linked: set[str] = set()
    for path in inputs.pt_files:
        rows = read_pt_models(path)
        week = predictions.week_in_name(path)
        meta_path = path.with_name(path.name + ".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        week = int(meta.get("week", week or 0)) or None
        pairs = {frozenset((predictions.team_code(r["road"]), predictions.team_code(r["home"]))) for r in rows}
        season = meta.get("season")
        if season is None and week is not None:
            season, _ = slates.infer_season(week, pairs)
        if season is None or week is None:
            notes.append(f"{rel(path)}: season/week not established - not imported")
            continue
        entry = stored.get(str(week))
        retrieved, basis = None, "not recorded"
        if isinstance(entry, dict) and float(entry.get("imported") or 0) > 0 and _same_file(entry, path):
            retrieved = float(entry["imported"])
            basis = ("the app's import time for identical content (data/acql.db forecasts); "
                     "the file was downloaded at or before it")
            linked.add(str(week))
            seasons[str(week)] = int(season)
        elif meta.get("retrieved_at") is not None:
            retrieved, basis = float(meta["retrieved_at"]), "recorded in the file's .meta.json"
        published = meta.get("published_at")
        source_id = f"pt:{path.name}"
        insert(conn, "sources", {
            "source_id": source_id, "kind": "model_forecasts+market",
            "description": f"The Prediction Tracker weekly file, {season} week {week}",
            "location": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size,
            "retrieved_at": retrieved, "retrieved_at_basis": basis,
            "note": "Publication time is not in the file." if published is None else ""})
        for index, row in enumerate(rows, start=1):
            away, home = predictions.team_code(row["road"]), predictions.team_code(row["home"])
            game, flipped = slates.find(int(season), week, away, home)
            if game is None:
                notes.append(f"{rel(path)} row {index}: {row['road']} @ {row['home']} not on the "
                             f"{season} week {week} schedule - not imported")
                continue
            sign, orientation = (-1.0, "flipped") if flipped else (1.0, "as_source")
            gid = game["game_id"]
            for column, timing in (("line", "file_market"), ("lineopen", "file_opening")):
                if row[column] is None:
                    continue
                insert(conn, "odds_snapshots", {
                    "snapshot_id": f"{source_id}:{gid}:{column}", "game_id": gid, "market": "spread",
                    "home_value": sign * row[column], "away_value": None, "timing": timing,
                    "as_of": None, "available_at": retrieved, "available_at_basis": basis,
                    "orientation": orientation, "source_id": source_id,
                    "raw": json.dumps({"road": row["road"], "home": row["home"], column: row[column]})})
            for model, margin in row["models"]:
                insert(conn, "model_forecasts", {
                    "forecast_id": f"{source_id}:{gid}:{model}", "game_id": gid, "model": model,
                    "home_margin": sign * margin, "published_at": published,
                    "published_at_basis": "not stated in the file" if published is None
                    else "recorded in the file's .meta.json",
                    "retrieved_at": retrieved, "retrieved_at_basis": basis,
                    "available_at": retrieved, "orientation": orientation, "source_id": source_id})

    # Store weeks with no file behind them: typed lines, or a file no longer on disk.
    for key, entry in sorted(stored.items(), key=lambda kv: int(kv[0])):
        if key in linked or not isinstance(entry, dict):
            continue
        games = [g for g in entry.get("games", []) if isinstance(g, dict)]
        pairs = {frozenset((predictions.team_code(g.get("road")), predictions.team_code(g.get("home"))))
                 for g in games}
        season, _ = slates.infer_season(int(key), pairs)
        if season is None:
            notes.append(f"store forecasts week {key}: season not established - not imported")
            continue
        seasons[key] = season
        if any(g.get("opinions") for g in games):
            notes.append(f"store forecasts week {key}: has model numbers but no source file with "
                         f"their names - models not imported")
        imported = float(entry.get("imported") or 0) or None
        source_id = f"store:forecasts:{key}"
        typed = "typed" in str(entry.get("source", "")).lower()
        insert(conn, "sources", {
            "source_id": source_id, "kind": "market",
            "description": f"data/acql.db forecasts week {key}: {entry.get('source', '')}",
            "location": "data/acql.db (kind forecasts)", "sha256": None, "bytes": None,
            "retrieved_at": imported,
            "retrieved_at_basis": "the app's import time" if imported else "no time recorded (imported = 0)",
            "note": ""})
        for g in games:
            away, home = predictions.team_code(g.get("road")), predictions.team_code(g.get("home"))
            game, flipped = slates.find(season, int(key), away, home)
            if game is None or g.get("market") is None:
                continue
            sign, orientation = (-1.0, "flipped") if flipped else (1.0, "as_source")
            insert(conn, "odds_snapshots", {
                "snapshot_id": f"{source_id}:{game['game_id']}", "game_id": game["game_id"],
                "market": "spread", "home_value": sign * float(g["market"]), "away_value": None,
                "timing": "typed" if typed else "file_market", "as_of": None,
                "available_at": imported,
                "available_at_basis": "the app's import time" if imported else "no time recorded",
                "orientation": orientation, "source_id": source_id,
                "raw": json.dumps({"road": g.get("road"), "home": g.get("home"), "market": g.get("market")})})
    return seasons


def _archive_codes(slates: Slates, season: int, week: int, road: str, home: str) -> tuple[str, str]:
    """Team codes for an archive row. A name that fits two teams ("Los Angeles"
    in 2016) is settled by the schedule: the opponent the other team actually
    played that week, if its full name starts with the name given."""
    away, home_code = predictions.team_code(road), predictions.team_code(home)
    if bool(away) == bool(home_code):
        return away, home_code
    known, name = (away, home) if away else (home_code, road)
    words = predictions._words(name)
    opponents = [code for pair in slates.weeks.get((season, week), set()) if known in pair
                 for code in pair if code != known]
    if len(opponents) == 1 and words and \
            predictions._words(predictions.DISPLAY.get(opponents[0], "")).startswith(words):
        return (known, opponents[0]) if away else (opponents[0], known)
    return away, home_code


def import_pt_archives(conn, inputs: Inputs, slates: Slates, notes: list[str]) -> dict[int, int]:
    """The Prediction Tracker's season archives (nflYY.csv): every model's
    number for every game, plus the site's opening, midweek and latest lines.

    None of it is dated. The files do not say when each number was published
    or whether it was revised later, and the `line` column of a finished
    week is updated after the week's own download (checked against 2026
    week 3: `linemidweek` matched the weekly file's line, `line` had moved).
    So every row goes in with no `available_at`: it can never fill a
    verified field of a record. Its lines carry their own timings
    (asof.ARCHIVE_TIMINGS), which the records' quarantined fields leave out
    too, so a backtest has to opt in to them by name.
    Returns season -> games imported.
    """
    counts: dict[int, int] = {}
    for path in inputs.pt_archives:
        season = archive_season(path)
        if season is None:
            notes.append(f"{rel(path)}: not a season archive name (nflYY.csv) - not imported")
            continue
        meta_path = path.with_name(path.name + ".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        retrieved = meta.get("retrieved_at")
        basis = meta.get("retrieved_at_basis") or "not recorded"
        source_id = f"ptarchive:{path.name}"
        insert(conn, "sources", {
            "source_id": source_id, "kind": "model_forecasts+market",
            "description": f"The Prediction Tracker season archive, {season}",
            "location": meta.get("url") or PT_ARCHIVE_URL.format(name=path.name),
            "sha256": sha256(path), "bytes": path.stat().st_size,
            "retrieved_at": retrieved, "retrieved_at_basis": basis,
            "note": "Undated: publication times are not in the file, and lines may be later "
                    "updates. " + str(meta.get("note") or "")})
        seen: set[str] = set()
        for index, row in enumerate(read_pt_models(path, PT_ARCHIVE_RENAMES), start=2):
            week = row["week"]
            if week is None:
                notes.append(f"{rel(path)} line {index}: {row['road']} @ {row['home']} has no week - "
                             f"not imported")
                continue
            away, home = _archive_codes(slates, season, week, row["road"], row["home"])
            game, flipped = slates.find(season, week, away, home)
            if game is None:
                if (season, week) in slates.weeks:     # past the regular season: expected, not noted
                    notes.append(f"{rel(path)} line {index}: {row['road']} @ {row['home']} not on the "
                                 f"{season} week {week} schedule - not imported")
                continue
            gid = game["game_id"]
            if gid in seen:
                notes.append(f"{rel(path)} line {index}: {gid} appears twice - second row not imported")
                continue
            seen.add(gid)
            counts[season] = counts.get(season, 0) + 1
            sign, orientation = (-1.0, "flipped") if flipped else (1.0, "as_source")
            undated = "season archive: when this number was posted is not in the file"
            for column, timing in (("line", "archive_latest"), ("linemidweek", "archive_midweek"),
                                   ("lineopen", "archive_opening")):
                if row[column] is None:
                    continue
                insert(conn, "odds_snapshots", {
                    "snapshot_id": f"{source_id}:{gid}:{column}", "game_id": gid, "market": "spread",
                    "home_value": sign * row[column], "away_value": None, "timing": timing,
                    "as_of": None, "available_at": None, "available_at_basis": undated,
                    "orientation": orientation, "source_id": source_id,
                    "raw": json.dumps({"road": row["road"], "home": row["home"], column: row[column]})})
            for model, margin in row["models"]:
                insert(conn, "model_forecasts", {
                    "forecast_id": f"{source_id}:{gid}:{model}", "game_id": gid, "model": model,
                    "home_margin": sign * margin, "published_at": None,
                    "published_at_basis": "not stated in the season archive",
                    "retrieved_at": retrieved, "retrieved_at_basis": basis,
                    "available_at": None, "orientation": orientation, "source_id": source_id})
    return counts


def import_app_odds(conn, slates: Slates, store: dict, notes: list[str]) -> None:
    """The Odds API lines the app fetched, each update at the moment it was fetched."""
    weeks = store.get("odds_weeks", {}) if store else {}
    if not weeks:
        return
    insert(conn, "sources", {
        "source_id": "store:odds", "kind": "market",
        "description": "The Odds API spreads fetched by the app (median over bookmakers)",
        "location": "data/acql.db (kind odds, key weeks)", "sha256": None, "bytes": None,
        "retrieved_at": None, "retrieved_at_basis": "each snapshot carries its own fetch time",
        "note": "Spreads only; no moneylines or totals are stored."})
    for key, week in sorted(weeks.items(), key=lambda kv: int(kv[0])):
        history = [h for h in (week or {}).get("history", []) if isinstance(h, dict)]
        pairs = {frozenset(k.split("@")) for h in history for k in (h.get("lines") or {})}
        season, _ = slates.infer_season(int(key), pairs)
        if season is None:
            notes.append(f"store odds week {key}: season not established - not imported")
            continue
        for snap in history:
            at = float(snap["at"])
            for matchup, value in sorted((snap.get("lines") or {}).items()):
                road, home = matchup.split("@")
                game, flipped = slates.find(season, int(key), road, home)
                if game is None or value is None:
                    notes.append(f"store odds week {key}: {matchup} not on the schedule")
                    continue
                insert(conn, "odds_snapshots", {
                    "snapshot_id": f"odds:{game['game_id']}:{at:.3f}", "game_id": game["game_id"],
                    "market": "spread", "home_value": (-1.0 if flipped else 1.0) * float(value),
                    "away_value": None, "timing": "snapshot", "as_of": at, "available_at": at,
                    "available_at_basis": "fetched by the app from The Odds API at this time",
                    "orientation": "flipped" if flipped else "as_source", "source_id": "store:odds",
                    "raw": json.dumps({matchup: value})})


def import_typed_spreads(conn, slates: Slates, store: dict, seasons: dict[str, int], notes: list[str]) -> None:
    """Spreads Sam typed into the Next Week page. No time is kept for them."""
    spreads = store.get("spreads", {}) if store else {}
    if not spreads:
        return
    insert(conn, "sources", {
        "source_id": "store:spreads", "kind": "market",
        "description": "spreads typed in by hand on the Next Week page",
        "location": "data/acql.db (kind spreads)", "sha256": None, "bytes": None,
        "retrieved_at": None, "retrieved_at_basis": "the store keeps no time for typed spreads",
        "note": "Season taken from the store's predictions for the same week."})
    for key, typed in sorted(spreads.items(), key=lambda kv: int(kv[0])):
        season = seasons.get(key)
        if season is None:
            notes.append(f"store spreads week {key}: season not established - not imported")
            continue
        for index, spread in sorted((typed or {}).items()):
            road_name, _, home_name = str(spread.get("match", "")).partition("@")
            game, flipped = slates.find(season, int(key), predictions.team_code(road_name),
                                        predictions.team_code(home_name))
            if game is None or spread.get("favourite") not in ("home", "away"):
                notes.append(f"store spreads week {key} game {index}: {spread.get('match')!r} is not on "
                             f"the {season} week {key} schedule - not imported")
                continue
            margin = float(spread["points"]) * (1 if spread["favourite"] == "home" else -1)
            insert(conn, "odds_snapshots", {
                "snapshot_id": f"typed:{game['game_id']}", "game_id": game["game_id"],
                "market": "spread", "home_value": -margin if flipped else margin, "away_value": None,
                "timing": "typed", "as_of": None, "available_at": None,
                "available_at_basis": "no time is kept for typed spreads",
                "orientation": "flipped" if flipped else "as_source", "source_id": "store:spreads",
                "raw": json.dumps(spread)})


def import_pool_sheets(conn, slates: Slates, store: dict, notes: list[str]) -> None:
    """The commissioner's lines, from the pool's own pick sheets."""
    for key, sheet in sorted((store.get("picks", {}) if store else {}).items(), key=lambda kv: int(kv[0])):
        games = sheet.get("games") or []
        pairs = {frozenset((predictions.team_code(g["away"]), predictions.team_code(g["home"]))) for g in games}
        season, matched = slates.infer_season(int(key), pairs)
        if season is None:
            notes.append(f"pick sheet week {key}: season not established - not imported")
            continue
        source_id = f"picks:{key}:{Path(str(sheet.get('source', ''))).name}"
        imported = number(sheet.get("imported"))
        insert(conn, "sources", {
            "source_id": source_id, "kind": "pool_lines",
            "description": f"the pool's pick sheet, {season} week {key}",
            "location": f"data/acql.db (kind picks, key {key}); originally {sheet.get('source', '')}",
            "sha256": None, "bytes": None, "retrieved_at": imported,
            "retrieved_at_basis": "the app's import time (after the week)" if imported else "not recorded",
            "note": "The sheet does not say when the commissioner posted each line."})
        sheet_id = source_id
        insert(conn, "pool_sheets", {
            "sheet_id": sheet_id, "season": season, "week": int(key), "games_on_sheet": len(games),
            "games_matched": matched, "season_match": "unique" if matched == len(pairs) else "partial",
            "imported_at": imported, "source_id": source_id})
        for index, g in enumerate(games, start=1):
            away, home = predictions.team_code(g["away"]), predictions.team_code(g["home"])
            game, _ = slates.find(season, int(key), away, home)
            if game is None:
                notes.append(f"pick sheet {season} week {key}: {g['away']} @ {g['home']} not on the schedule")
                continue
            found, problem = lines.line_from_note(g.get("note"), g["away"], g["home"])
            favourite = points = home_line = None
            if found is not None:
                favourite = predictions.team_code(found[0])
                points = float(found[1])
                home_line = points if favourite == game["home_code"] else -points
            insert(conn, "pool_lines", {
                "pool_line_id": f"{sheet_id}:{game['game_id']}", "game_id": game["game_id"],
                "sheet_id": sheet_id, "raw_note": str(g.get("note") or ""),
                "favourite_code": favourite, "points": points, "home_line": home_line,
                "problem": problem, "posted_at": None,
                "posted_at_basis": "not recorded on the sheet"})


def import_weights(conn, store: dict, notes: list[str]) -> None:
    """The model weight production priced each week with (pricing.week_weight).

    Production fits it on the weeks before the one being priced and holds it
    from that week's first kickoff, so it is information Deadeye had at the
    lock. The store keeps no time for when it was noted.
    """
    weights = store.get("weights", {}) if store else {}
    if not weights:
        return
    insert(conn, "sources", {
        "source_id": "store:weights", "kind": "production_state",
        "description": "the model weight each week was priced with",
        "location": "data/acql.db (kind weights)", "sha256": None, "bytes": None,
        "retrieved_at": None, "retrieved_at_basis": "the store keeps no time for these notes",
        "note": "Fitted on earlier weeks only (pricing.model_weight(before=week))."})
    for key, held in sorted(weights.items()):
        found = re.fullmatch(r"(\d{4})-(\d{1,2})", str(key))
        if not found or not isinstance(held, dict) or not isinstance(held.get("weight"), (int, float)):
            notes.append(f"store weights {key!r}: not understood - not imported")
            continue
        insert(conn, "production_weights", {
            "season": int(found.group(1)), "week": int(found.group(2)), "weight": float(held["weight"]),
            "fit": json.dumps(held.get("fit"), sort_keys=True), "source_id": "store:weights",
            "basis": "fitted by production on the weeks before this one; held from the first kickoff"})


def insert_rules(conn) -> None:
    for row in (
        {"rule_id": asof.LINED_RULE, "applies_to": "games carrying a pool line",
         "description": "The pool's favourite must win by at least the line; a win by exactly a "
                        "whole-number line goes to the favourite (acql.analytics.line_need).",
         "status": "verified", "evidence": LINE_RULE_EVIDENCE,
         "verified_from_season": 2025, "verified_from_week": 15},
        {"rule_id": asof.STRAIGHT_RULE, "applies_to": "games without a pool line",
         "description": "The winner is credited.", "status": "verified",
         "evidence": "graded pool sheets from 2025 week 15 (acql/data/pool_weeks.json source)",
         "verified_from_season": 2025, "verified_from_week": 15},
        {"rule_id": "tie_handling", "applies_to": "a tied game",
         "description": "How a tie is graded is not recorded anywhere in the repo.",
         "status": "unknown", "evidence": "none", "verified_from_season": None, "verified_from_week": None},
        {"rule_id": "old_rule", "applies_to": "unknown",
         "description": "acql/data/pool_weeks.json carries an 'old_rule' score per week; nothing "
                        "says what that earlier rule was.",
         "status": "unknown", "evidence": "acql/data/pool_weeks.json", "verified_from_season": None,
         "verified_from_week": None},
    ):
        insert(conn, "pool_rules", row)


# ---- build / verify ----------------------------------------------------------------------------
def build(inputs: Inputs, dest: Path = DB_FILE) -> dict:
    """Build the dataset into `dest` (replaced only once complete)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(suffix=".db", dir=dest.parent)
    os.close(handle)
    tmp = Path(tmp_name)
    tmp.unlink()
    notes: list[str] = []
    conn = sqlite3.connect(tmp)
    try:
        schema.create(conn)
        games = import_schedule(conn, inputs)
        crosscheck = import_outcomes(conn, inputs)
        slates = Slates(conn)
        store = {}
        if inputs.store_extract is not None:
            extract = json.loads(inputs.store_extract.read_text(encoding="utf-8"))
            store = extract["store"]
            insert(conn, "sources", {
                "source_id": "store_extract", "kind": "app_store_extract",
                "description": "read-only extract of the app's database (forecasts, odds, spreads, "
                               "pick-sheet notes)",
                "location": rel(inputs.store_extract), "sha256": sha256(inputs.store_extract),
                "bytes": inputs.store_extract.stat().st_size, "retrieved_at": None,
                "retrieved_at_basis": "entries carry the app's own times",
                "note": f"from {extract['database']} sha256 {extract['database_sha256']}"})
        seasons = import_forecasts(conn, inputs, slates, store, notes)
        archived = import_pt_archives(conn, inputs, slates, notes)
        import_app_odds(conn, slates, store, notes)
        import_typed_spreads(conn, slates, store, seasons, notes)
        import_pool_sheets(conn, slates, store, notes)
        import_weights(conn, store, notes)
        insert_rules(conn)
        for record in asof.all_records(conn):
            insert(conn, "prediction_records", record)
        conn.execute("CREATE TABLE build_notes (n INTEGER PRIMARY KEY, note TEXT NOT NULL)")
        conn.executemany("INSERT INTO build_notes (note) VALUES (?)", [(n,) for n in notes])
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, dest)
    return {"games": games, "crosscheck": crosscheck, "notes": notes, "archived": archived}


def verify(path: Path = DB_FILE) -> tuple[int, list[str]]:
    """Rebuild every record from the tables and compare: (records, mismatches)."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        cur = conn.execute("SELECT * FROM prediction_records ORDER BY record_id")
        stored = {r[0]: dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()}
        rebuilt = {r["record_id"]: r for r in asof.all_records(conn)}
    finally:
        conn.close()
    problems = [rid for rid in sorted(set(stored) | set(rebuilt)) if stored.get(rid) != rebuilt.get(rid)]
    return len(stored), problems


def main(argv: list[str]) -> int:
    local = None
    if "--nflverse-file" in argv:
        local = Path(argv[argv.index("--nflverse-file") + 1])
    steps = [a for a in argv if a in ("fetch", "build", "verify", "report")] or \
        ["fetch", "build", "verify", "report"]
    if "fetch" in steps:
        print("games.csv:", rel(fetch_nflverse(local)))
        print("store extract:", rel(extract_store()))
    if "build" in steps:
        result = build(default_inputs())
        print(f"built {rel(DB_FILE)}: {result['games']} games; scores cross-check {result['crosscheck']}; "
              f"{len(result['notes'])} import notes")
    if "verify" in steps:
        count, problems = verify()
        print(f"verified {count} records: {'all reproduce' if not problems else f'{len(problems)} DIFFER'}")
        if problems:
            print("\n".join(problems[:20]))
            return 1
    if "report" in steps:
        from . import report
        report.write(DB_FILE, REPORT_FILE)
        print("report:", rel(REPORT_FILE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
