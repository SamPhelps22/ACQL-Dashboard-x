"""Every number the Lab shows, from what the app already keeps.

Rules this file keeps:

  * Nothing is fetched and nothing is written. Every function reads the
    forecast log (acql.db, read-only), stored scores and lines, the nflverse
    files in data/nflverse, or the raw odds archive.
  * A forecast is only ever shown as it was recorded. Calibration, the
    confidence distribution and the postmortem research summary use
    "eligible" forecasts only - ones the forecast log can prove were made
    before the week's cutoff. Forecasts recorded after kickoff ("postgame")
    are listed, marked, and never scored.
  * Missing data is said to be missing (a `missing` list, or None), never
    filled in.

Each public function returns plain JSON-able dicts, so the server, the tests
and the assistant's tools all read the same thing.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "acql.db"
NFLVERSE = ROOT / "data" / "nflverse"

DIVISIONS = {
    "AFC East": ("buf", "mia", "ne", "nyj"), "AFC North": ("bal", "cin", "cle", "pit"),
    "AFC South": ("hou", "ind", "jax", "ten"), "AFC West": ("den", "kc", "lv", "lac"),
    "NFC East": ("dal", "nyg", "phi", "was"), "NFC North": ("chi", "det", "gb", "min"),
    "NFC South": ("atl", "car", "no", "tb"), "NFC West": ("ari", "lar", "sf", "sea"),
}
DIVISION_OF = {t: d for d, teams in DIVISIONS.items() for t in teams}
TEAMS = tuple(sorted(DIVISION_OF))
#: nflverse spells a few teams its own way.
_NFLVERSE = {"la": "lar", "oak": "lv", "sd": "lac", "stl": "lar"}

DEADEYE = "deadeye"
MARKET_ML = "market-moneyline"
MARKET_SPREAD = "market-spread"


def code(raw: object) -> str:
    text = str(raw or "").strip().casefold()
    return _NFLVERSE.get(text, text)


def name(team: str) -> str:
    from ..model.predictions import display_team
    return display_team(team) or team.upper()


def _year() -> int:
    from ..feeds import results
    return results.season_year()


# ---- the forecast log ---------------------------------------------------------------
def connect(path: Path | None = None) -> sqlite3.Connection:
    """The database, read-only: nothing in the Lab can change a forecast."""
    conn = sqlite3.connect(f"file:{(path or DB).as_posix()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return made if made.tzinfo else made.replace(tzinfo=timezone.utc)


def forecasts(conn: sqlite3.Connection, model: str | None = None, *, season: int | None = None,
              statuses: tuple[str, ...] | None = ("eligible",)) -> list[dict]:
    """Each recorded forecast with its game, as stored. A model with two forecasts
    under the same status for one game has that game left out (as the forecast
    log's own scorecard does) - never one of them quietly chosen."""
    where, params = [], []
    if model:
        where.append("p.model_id = ?")
        params.append(model)
    if season is not None:
        where.append("g.season = ?")
        params.append(season)
    if statuses:
        where.append(f"p.eligibility_status IN ({','.join('?' * len(statuses))})")
        params += list(statuses)
    rows = conn.execute(
        f"""SELECT p.prediction_id, p.model_id, p.model_version, p.home_win_probability, p.predicted_winner,
                   p.source_published_at_utc, p.retrieved_at_utc, p.recorded_at_utc, p.eligibility_status,
                   p.data_quality_note, p.source_reference, p.raw_payload_json, g.game_id, g.season, g.week,
                   g.kickoff_utc, g.away_team, g.home_team, g.away_score, g.home_score
            FROM lab_predictions p JOIN lab_games g ON g.game_id = p.game_id
            {'WHERE ' + ' AND '.join(where) if where else ''}
            ORDER BY g.kickoff_utc, g.game_id, p.model_id, p.retrieved_at_utc""", params).fetchall()
    seen: dict[tuple, int] = {}
    for r in rows:
        seen[(r["model_id"], r["game_id"], r["eligibility_status"])] = seen.get(
            (r["model_id"], r["game_id"], r["eligibility_status"]), 0) + 1
    out = []
    for r in rows:
        if seen[(r["model_id"], r["game_id"], r["eligibility_status"])] != 1:
            continue
        p = r["home_win_probability"]
        played = r["home_score"] is not None and r["away_score"] is not None
        margin = (r["home_score"] - r["away_score"]) if played else None
        kick, made = _parse(r["kickoff_utc"]), _parse(r["retrieved_at_utc"])
        try:
            payload = json.loads(r["raw_payload_json"] or "{}")
        except ValueError:
            payload = {}
        out.append({
            "id": r["prediction_id"], "model": r["model_id"], "version": r["model_version"] or "not recorded",
            "game": r["game_id"], "season": r["season"], "week": r["week"], "kickoff": r["kickoff_utc"],
            "away": code(r["away_team"]), "home": code(r["home_team"]),
            "home_prob": None if p is None else float(p),
            "made": r["retrieved_at_utc"], "published": r["source_published_at_utc"],
            "hours_before": None if not (kick and made) else round((kick - made).total_seconds() / 3600, 1),
            "status": r["eligibility_status"], "note": r["data_quality_note"] or "",
            "source": r["source_reference"] or "",
            "margin_forecast": payload.get("margin") if isinstance(payload, dict) else None,
            "away_score": r["away_score"], "home_score": r["home_score"], "home_margin": margin,
            "home_won": None if margin in (None, 0) else margin > 0, "tie": margin == 0,
        })
    return out


def _wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _favoured(f: dict) -> tuple[float, bool] | None:
    """(chance the forecast gave the side it favoured, whether that side won)."""
    p = f["home_prob"]
    if p is None or f["home_won"] is None:
        return None
    return (p, f["home_won"]) if p >= 0.5 else (1 - p, not f["home_won"])


def _horizon(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    return "over 48h" if hours > 48 else "24-48h" if hours > 24 else "under 24h"


def model_list(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""SELECT m.model_id, m.display_name, m.model_type,
        SUM(p.eligibility_status = 'eligible') AS eligible, COUNT(p.prediction_id) AS total
        FROM lab_models m LEFT JOIN lab_predictions p ON p.model_id = m.model_id
        GROUP BY m.model_id ORDER BY m.model_type DESC, m.display_name""").fetchall()
    return [{"id": r["model_id"], "name": r["display_name"], "type": r["model_type"],
             "eligible": r["eligible"] or 0, "total": r["total"] or 0} for r in rows]


def calibration(conn: sqlite3.Connection, model: str = DEADEYE, *, season: int | None = None,
                team: str | None = None, version: str | None = None, horizon: str | None = None,
                width: float = 0.1) -> dict:
    """Predicted chance against how often it happened, on eligible forecasts of
    finished games. Each forecast is read from the side it favoured, so the bins
    run from 50% to 100%. Ties have no winner and are left out (counted)."""
    every = [f for f in forecasts(conn, model, season=season) if f["home_score"] is not None]
    if team:
        every = [f for f in every if team in (f["home"], f["away"])]
    versions = sorted({f["version"] for f in every})
    if version:
        every = [f for f in every if f["version"] == version]
    if horizon:
        every = [f for f in every if _horizon(f["hours_before"]) == horizon]
    ties = sum(f["tie"] for f in every)
    graded = [(f, *_favoured(f)) for f in every if _favoured(f)]
    edges = [round(0.5 + i * width, 4) for i in range(int(round(0.5 / width)) + 1)]
    bins = []
    for lo, hi in zip(edges, edges[1:]):
        inside = [(f, p, won) for f, p, won in graded if lo <= p < hi or (hi >= 1 and p == 1)]
        n = len(inside)
        hits = sum(won for _, _, won in inside)
        bins.append({"lo": lo, "hi": hi, "n": n, "hits": hits,
                     "predicted": statistics.mean(p for _, p, _ in inside) if n else None,
                     "observed": hits / n if n else None, "interval": _wilson(hits, n),
                     "games": [f["game"] for f, _, _ in inside]})
    probs = [f["home_prob"] for f, _, _ in graded]
    outcomes = [int(f["home_won"]) for f, _, _ in graded]
    eps = 1e-6
    n = len(graded)
    return {
        "model": model, "season": season, "team": team, "version": version, "horizon": horizon,
        "versions": versions, "games": n, "ties_left_out": ties,
        "brier": sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / n if n else None,
        "log_loss": -sum(o * math.log(max(eps, p)) + (1 - o) * math.log(max(eps, 1 - p))
                         for p, o in zip(probs, outcomes)) / n if n else None,
        # how often the favoured side won - a different question from calibration
        "accuracy": sum(won for _, _, won in graded) / n if n else None,
        "expected_wins": sum(p for _, p, _ in graded), "actual_wins": sum(won for _, _, won in graded),
        "bins": bins,
        "postgame_left_out": len([f for f in forecasts(conn, model, season=season, statuses=("postgame",))]),
        "warning": None if n >= 100 else
        f"Only {n} eligible forecast{'s' if n != 1 else ''} on finished games. Calibration needs hundreds; "
        "treat every bin as a rough look, not a finding.",
    }


def distribution(conn: sqlite3.Connection, model: str = DEADEYE, *, season: int | None = None,
                 week: int | None = None, team: str | None = None, width: float = 0.05) -> dict:
    """How the model spread its chances over the slate (eligible forecasts, played
    or not), beside the moneyline's no-margin chance on the same games where one
    was fetched before the cutoff. Not the ACQL confidence points."""
    rows = forecasts(conn, model, season=season)
    market = {f["game"]: f for f in forecasts(conn, MARKET_ML, season=season)}
    if week:
        rows = [f for f in rows if f["week"] == week]
    if team:
        rows = [f for f in rows if team in (f["home"], f["away"])]
    items = []
    for f in rows:
        if f["home_prob"] is None:
            continue
        fav_home = f["home_prob"] >= 0.5
        p = f["home_prob"] if fav_home else 1 - f["home_prob"]
        m = market.get(f["game"])
        mp = None if not m or m["home_prob"] is None else (m["home_prob"] if fav_home else 1 - m["home_prob"])
        won = None if f["home_won"] is None else (f["home_won"] == fav_home)
        items.append({"game": f["game"], "week": f["week"], "favoured": f["home"] if fav_home else f["away"],
                      "against": f["away"] if fav_home else f["home"], "home": f["home"], "p": round(p, 4),
                      "market": None if mp is None else round(mp, 4), "won": won})
    edges = [round(0.5 + i * width, 4) for i in range(int(round(0.5 / width)) + 1)]
    bins = []
    for lo, hi in zip(edges, edges[1:]):
        inside = [i for i in items if lo <= i["p"] < hi or (hi >= 1 and i["p"] == 1)]
        done = [i for i in inside if i["won"] is not None]
        bins.append({"lo": lo, "hi": hi, "n": len(inside), "share": len(inside) / len(items) if items else 0,
                     "decided": len(done), "won": sum(i["won"] for i in done),
                     "market_n": sum(i["market"] is not None for i in inside), "games": inside})
    weeks = sorted({f["week"] for f in forecasts(conn, model, season=season)})
    return {"model": model, "season": season, "week": week, "team": team, "games": len(items),
            "weeks": weeks, "bins": bins}


# ---- scores, lines and teams --------------------------------------------------------
def _scores(year: int) -> dict[int, list]:
    from ..feeds import results
    return {w: results.load(year, w) for w in range(1, 19)}


def _stored_lines(week: int):
    from ..feeds import odds
    try:
        return odds.stored(week)
    except Exception:  # noqa: BLE001 - lines are extra; a page stands without them
        return None


def schedule(year: int | None = None) -> list[dict]:
    """Every game the scoreboard has been seen with this season, from stored scores."""
    year = year or _year()
    out = []
    for week, games in _scores(year).items():
        lines = _stored_lines(week)
        for s in games:
            key = f"{s.away}@{s.home}"
            out.append({
                "week": week, "away": s.away, "home": s.home, "state": s.state, "final": s.final,
                "detail": s.detail, "kickoff": s.kickoff, "away_points": s.away_points,
                "home_points": s.home_points, "called_off": s.called_off,
                "line": None if not lines or key not in lines.latest else lines.latest[key],
                "win": None if not lines else lines.win.get(key),
                "total": None if not lines else lines.total.get(key),
                "espn_spread": s.home_spread,
            })
    return out


def _deadeye_by_game(conn: sqlite3.Connection) -> dict[str, dict]:
    """The one forecast to show beside a game: the eligible one if any, else the
    recorded one marked with its status."""
    out: dict[str, dict] = {}
    for f in forecasts(conn, DEADEYE, statuses=("postgame", "late", "eligible")):
        if f["game"] not in out or f["status"] == "eligible":
            out[f["game"]] = f
    return out


def _game_id(year: int, week: int, away: str, home: str) -> str:
    return f"{year}-W{week:02d}-{away.upper()}@{home.upper()}"


def teams(conn: sqlite3.Connection, year: int | None = None) -> list[dict]:
    """A row for each of the 32 teams: identity, record, every game seen."""
    year = year or _year()
    sched = schedule(year)
    dead = _deadeye_by_game(conn)
    out = []
    for team in TEAMS:
        games, w, l, t = [], 0, 0, 0
        for g in sched:
            if team not in (g["away"], g["home"]):
                continue
            home = g["home"] == team
            mine, theirs = (g["home_points"], g["away_points"]) if home else (g["away_points"], g["home_points"])
            result = None
            if g["final"] and mine is not None and theirs is not None:
                result = "W" if mine > theirs else "L" if mine < theirs else "T"
                w, l, t = w + (result == "W"), l + (result == "L"), t + (result == "T")
            f = dead.get(_game_id(year, g["week"], g["away"], g["home"]))
            games.append({**g, "opponent": g["away"] if home else g["home"], "at_home": home,
                          "points_for": mine, "points_against": theirs, "result": result,
                          "line_for": None if g["line"] is None else (g["line"] if home else -g["line"]),
                          "deadeye": None if not f else {
                              "p": f["home_prob"] if home else (None if f["home_prob"] is None else 1 - f["home_prob"]),
                              "status": f["status"], "made": f["made"], "version": f["version"]}})
        out.append({"code": team, "name": name(team), "division": DIVISION_OF[team],
                    "record": f"{w}-{l}" + (f"-{t}" if t else ""), "games": games})
    return out


def team_record(conn: sqlite3.Connection, team: str, year: int | None = None) -> dict:
    """How Deadeye's eligible forecasts did on one team's games."""
    rows = [f for f in forecasts(conn, DEADEYE, season=year) if team in (f["home"], f["away"])]
    graded = [(_favoured(f), f) for f in rows if _favoured(f)]
    return {"team": team, "forecasts": len(rows), "decided": len(graded),
            "right": sum(g[0][1] for g in graded),
            "brier": (sum((f["home_prob"] - int(f["home_won"])) ** 2 for _, f in graded) / len(graded))
            if graded else None}


@lru_cache(maxsize=4)
def _strength(year: int, stamp: int) -> dict:
    from ..model import teamstrength
    from ..pool import survivor
    sched = schedule(year)
    played = sorted({g["week"] for g in sched if g["final"]})
    last = (max(played) if played else 0) + 1
    weeks = list(range(1, min(18, last) + 1))
    own, market, form = {t: [] for t in TEAMS}, {t: [] for t in TEAMS}, {t: [] for t in TEAMS}
    for w in weeks:
        s = teamstrength.before(None, w, year)
        rated = {}
        try:
            rated = survivor.ratings(survivor._lines_so_far(w))
        except Exception:  # noqa: BLE001 - a week with no lines stored yet
            rated = {}
        for t in TEAMS:
            own[t].append(None if t not in s.teams else round(s.teams[t], 2))
            market[t].append(None if t not in rated else round(float(rated[t]), 2))
    for t in TEAMS:
        pf, pa = [], []
        for w in weeks:
            g = next((g for g in sched if g["week"] == w and t in (g["home"], g["away"]) and g["final"]), None)
            if g:
                home = g["home"] == t
                pf.append(g["home_points"] if home else g["away_points"])
                pa.append(g["away_points"] if home else g["home_points"])
                result = (pf[-1] > pa[-1]) - (pf[-1] < pa[-1])
            else:
                result = None
            recent_f, recent_a = pf[-4:], pa[-4:]
            form[t].append({"result": result, "for": pf[-1] if g else None, "against": pa[-1] if g else None,
                            "rolling_for": round(statistics.mean(recent_f), 1) if recent_f else None,
                            "rolling_against": round(statistics.mean(recent_a), 1) if recent_a else None})
    return {"year": year, "weeks": weeks, "own": own, "market": market, "form": form}


def strength(year: int | None = None) -> dict:
    """Two existing ratings, entering each week, for every team - plus scoring form.

    own     Deadeye's own results-only rating (model/teamstrength.py): points
            better than an average team, from final scores before that week.
    market  the rating the season's stored betting lines imply
            (pool/survivor.ratings), lines through that week.
    form    points for and against, and their last-four average. Descriptive,
            not a rating: no offence or defence rating exists in the app.
    """
    year = year or _year()
    from ..feeds import results
    stamp = int((results.fetched_at(year, 1) or 0) + sum(results.fetched_at(year, w) or 0 for w in range(1, 19)))
    made = dict(_strength(year, stamp))
    made["method"] = {
        "own": "Deadeye's results-only rating (acql/model/teamstrength.py, same rules as backtest.rate): "
               "each result moves both teams by a share of the rating's error; seasons start part-way back "
               "to average. 2011-2025 it picked about 65% of winners straight up (closing line ~66%).",
        "market": "Least-squares ratings solved from every stored betting line through the week "
                  "(acql/pool/survivor.ratings), gently pulled toward zero.",
        "form": "Points scored and allowed from stored final scores; rolling = last four games. Descriptive only.",
        "limits": "No separate offensive or defensive rating exists in the app, so none is shown. "
                  "Both ratings are in points against an average team and are not the same scale as a win chance.",
        "version": "teamstrength as of the installed app; nothing here is fitted to the games it is shown on.",
    }
    return made


# ---- sportsbooks (raw odds archive) ---------------------------------------------------
def _american(price) -> float | None:
    if isinstance(price, bool) or not isinstance(price, (int, float)) or abs(price) < 100:
        return None
    return -price / (-price + 100) if price < 0 else 100 / (price + 100)


def snapshots() -> list[dict]:
    from .. import rawarchive
    return [{"at": r.get("at"), "file": r.get("file"), "size": r.get("size")}
            for r in rawarchive.index("odds")]


def books(at: float | None = None, *, now: float | None = None) -> dict:
    """Every bookmaker's prices from one archived Odds API answer (the latest, or
    the latest at or before `at`). These are the books' own numbers as they came;
    the consensus columns are worked out here and marked as derived."""
    from .. import rawarchive
    from ..model.predictions import team_code
    now = time.time() if now is None else now
    rows = rawarchive.index("odds")
    if at is not None:
        rows = [r for r in rows if r.get("at", 0) <= at]
    if not rows:
        return {"available": False, "reason": "No archived odds answer on this computer yet.", "games": []}
    row = rows[-1]
    try:
        events = json.loads(rawarchive.read(row) or b"[]")
    except ValueError:
        events = None
    if not isinstance(events, list):
        return {"available": False, "reason": "The archived odds answer could not be read.", "games": []}
    games = []
    for e in events:
        if not isinstance(e, dict):
            continue
        home, away = team_code(e.get("home_team")), team_code(e.get("away_team"))
        if not home or not away:
            continue
        lines = []
        for b in e.get("bookmakers") or []:
            line = {"book": b.get("title") or b.get("key"), "key": b.get("key"), "updated": b.get("last_update")}
            for m in b.get("markets") or []:
                outs = {str(o.get("name")): o for o in m.get("outcomes") or []}
                if m.get("key") == "h2h":
                    h = (outs.get(e.get("home_team")) or {}).get("price")
                    a = (outs.get(e.get("away_team")) or {}).get("price")
                    line.update(ml_home=h, ml_away=a)
                    ih, ia = _american(h), _american(a)
                    if ih and ia:
                        line.update(nv_home=round(ih / (ih + ia), 4), hold=round(ih + ia - 1, 4))
                elif m.get("key") == "spreads":
                    h = outs.get(e.get("home_team")) or {}
                    a = outs.get(e.get("away_team")) or {}
                    line.update(spread_home=h.get("point"), spread_home_price=h.get("price"),
                                spread_away=a.get("point"), spread_away_price=a.get("price"))
                elif m.get("key") == "totals":
                    o, u = outs.get("Over") or {}, outs.get("Under") or {}
                    line.update(total=o.get("point"), over_price=o.get("price"), under_price=u.get("price"))
            lines.append(line)

        def med(key):
            vals = [x[key] for x in lines if isinstance(x.get(key), (int, float))]
            return statistics.median(vals) if vals else None

        def best(key):
            vals = [(x[key], x["book"]) for x in lines if isinstance(x.get(key), (int, float))]
            return max(vals) if vals else None   # the highest American price pays the most

        spreads = [x["spread_home"] for x in lines if isinstance(x.get("spread_home"), (int, float))]
        totals = [x["total"] for x in lines if isinstance(x.get("total"), (int, float))]
        stamps = [_parse(x.get("updated")) for x in lines]
        newest = max((s for s in stamps if s), default=None)
        games.append({
            "away": away, "home": home, "kickoff": e.get("commence_time"), "books": len(lines), "lines": lines,
            "consensus": {"spread_home": med("spread_home"), "total": med("total"), "ml_home": med("ml_home"),
                          "ml_away": med("ml_away"), "nv_home": med("nv_home")},
            "best": {"ml_home": best("ml_home"), "ml_away": best("ml_away"),
                     "spread_home_price": best("spread_home_price"), "spread_away_price": best("spread_away_price"),
                     "over": best("over_price"), "under": best("under_price")},
            "spread_range": [min(spreads), max(spreads)] if spreads else None,
            "total_range": [min(totals), max(totals)] if totals else None,
            "newest_update": newest.isoformat() if newest else None,
        })
    return {"available": True, "fetched": row.get("at"), "age_minutes": round((now - row.get("at", now)) / 60),
            "snapshots": snapshots(), "games": games,
            "books_seen": sorted({x["book"] for g in games for x in g["lines"]}),
            "coverage": "Only the bookmakers The Odds API's US region returned in this answer - not the whole market.",
            "method": "No-margin chance: each book's two moneyline chances scaled to add to 100% (its hold "
                      "taken out proportionally); consensus = median across books. Best price = highest "
                      "American price on that side."}


# ---- team statistics (nflverse) ---------------------------------------------------------
def _nflverse_rows(name_: str) -> list[dict]:
    path = NFLVERSE / name_
    if not path.is_file():
        return []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(text) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


@lru_cache(maxsize=8)
def _team_stats(season: int, stamp: float) -> list[dict]:
    week_rows = _nflverse_rows(f"stats_team_week_{season}.csv.gz")
    games = {g["game_id"]: g for g in _nflverse_rows("games.csv.gz") if g.get("season") == str(season)}
    mine = {}
    for r in week_rows:
        if r.get("season_type") != "REG":
            continue
        plays = _num(r["attempts"]) + _num(r["sacks_suffered"]) + _num(r["carries"])
        yards = _num(r["passing_yards"]) - _num(r["sack_yards_lost"]) + _num(r["rushing_yards"])
        mine[(r["game_id"], code(r["team"]))] = {
            "plays": plays, "yards": yards, "epa": _num(r["passing_epa"]) + _num(r["rushing_epa"]),
            "turnovers": _num(r["passing_interceptions"]) + _num(r["sack_fumbles_lost"])
            + _num(r["rushing_fumbles_lost"]) + _num(r["receiving_fumbles_lost"]),
            "pass_yards": _num(r["passing_yards"]) - _num(r["sack_yards_lost"]), "rush_yards": _num(r["rushing_yards"]),
            "dropbacks": _num(r["attempts"]) + _num(r["sacks_suffered"]), "carries": _num(r["carries"]),
            "sacks": _num(r["sacks_suffered"]), "penalty_yards": _num(r["penalty_yards"]),
            "week": int(r["week"]), "opp": code(r["opponent_team"]),
        }
    out = []
    for (gid, team), me in mine.items():
        them = mine.get((gid, me["opp"]))
        g = games.get(gid, {})
        home = code(g.get("home_team")) == team
        pf = g.get("home_score" if home else "away_score")
        pa = g.get("away_score" if home else "home_score")
        row = {"season": season, "week": me["week"], "team": team, "opp": me["opp"], "home": home,
               "points_for": _num(pf) if pf not in (None, "") else None,
               "points_against": _num(pa) if pa not in (None, "") else None,
               "plays": me["plays"], "yards": me["yards"], "epa": round(me["epa"], 2),
               "turnovers": me["turnovers"], "pass_yards": me["pass_yards"], "rush_yards": me["rush_yards"],
               "dropbacks": me["dropbacks"], "carries": me["carries"], "sacks": me["sacks"],
               "penalty_yards": me["penalty_yards"]}
        if them:
            row.update(opp_plays=them["plays"], opp_yards=them["yards"], opp_epa=round(them["epa"], 2),
                       takeaways=them["turnovers"])
        out.append(row)
    return sorted(out, key=lambda r: (r["week"], r["team"]))


STAT_DEFINITIONS = {
    "points_for": "Points scored (nflverse games file).",
    "points_against": "Points allowed.",
    "ypp": "Yards a play: net passing yards (sack yards taken off) plus rushing yards, over dropbacks plus carries.",
    "epa_play": "Expected points added a play: nflverse's passing EPA plus rushing EPA, over plays. "
                "Offence only as nflverse sums it per team; defence is the opponent's figure against you.",
    "def_ypp": "Yards a play allowed (the opponent's yards a play).",
    "def_epa_play": "EPA a play allowed (the opponent's EPA a play).",
    "turnovers": "Interceptions thrown plus fumbles lost (sacks, carries, catches).",
    "takeaways": "The opponent's turnovers.",
    "pass_ypd": "Net passing yards a dropback.",
    "rush_ypc": "Rushing yards a carry.",
    "sack_rate": "Sacks taken a dropback.",
}
STATS_MISSING = [
    "Third-down and red-zone rates, and success rate: these need nflverse play-by-play files, which were "
    "never downloaded (about 30 MB a season).",
    "Player statistics: needs nflverse player_stats files (not downloaded).",
]


def stats(season: int | None = None) -> dict:
    """Team-game rows from the nflverse weekly team file, and what they cover."""
    season = season or _year()
    path = NFLVERSE / f"stats_team_week_{season}.csv.gz"
    stamp = path.stat().st_mtime if path.is_file() else 0.0
    rows = _team_stats(season, stamp)
    available = sorted({int(p.name.split("_")[-1][:4]) for p in NFLVERSE.glob("stats_team_week_*.csv.gz")})
    return {"season": season, "rows": rows, "through_week": max((r["week"] for r in rows), default=0),
            "file_date": datetime.fromtimestamp(stamp).strftime("%Y-%m-%d") if stamp else None,
            "seasons": available, "definitions": STAT_DEFINITIONS, "missing": STATS_MISSING,
            "source": "nflverse-data stats_team_week and games files (github.com/nflverse/nflverse-data), "
                      "downloaded by hand into data/nflverse. Not refreshed automatically."}


# ---- postmortems ---------------------------------------------------------------------------
@lru_cache(maxsize=2)
def _starters(season: int, stamp: float) -> dict[tuple[int, str], str]:
    out = {}
    for g in _nflverse_rows("games.csv.gz"):
        if g.get("season") != str(season) or g.get("game_type") != "REG":
            continue
        out[(int(g["week"]), code(g["home_team"]))] = g.get("home_qb_name") or ""
        out[(int(g["week"]), code(g["away_team"]))] = g.get("away_qb_name") or ""
    return out


def _qb_change(season: int, week: int, team: str) -> dict | None:
    path = NFLVERSE / "games.csv.gz"
    starters = _starters(season, path.stat().st_mtime if path.is_file() else 0.0)
    now = starters.get((week, team))
    before = next((starters[(w, team)] for w in range(week - 1, 0, -1) if (w, team) in starters), None)
    if not now:
        return None
    return {"starter": now, "previous": before, "changed": bool(before and before != now)}


def postmortems(conn: sqlite3.Connection, season: int | None = None) -> dict:
    """Every Deadeye forecast on a finished game, with what was known beside it."""
    season = season or _year()
    market_ml = {f["game"]: f for f in forecasts(conn, MARKET_ML, season=season)}
    market_sp = {f["game"]: f for f in forecasts(conn, MARKET_SPREAD, season=season)}
    items = []
    for f in forecasts(conn, DEADEYE, season=season, statuses=("eligible", "postgame", "late")):
        if f["home_score"] is None or f["home_prob"] is None:
            continue
        fav_home = f["home_prob"] >= 0.5
        p = f["home_prob"] if fav_home else 1 - f["home_prob"]
        m = market_ml.get(f["game"]) if f["status"] == "eligible" else None
        mp = None if not m or m["home_prob"] is None else (m["home_prob"] if fav_home else 1 - m["home_prob"])
        s = market_sp.get(f["game"]) if f["status"] == "eligible" else None
        won = None if f["tie"] else f["home_won"] == fav_home
        outcome = None if won is None else int(won)
        lines = _stored_lines(f["week"])
        key = f"{f['away']}@{f['home']}"
        made_at = _parse(f["made"])
        made_s = made_at.timestamp() if made_at else None
        moves = [] if not lines else [{"at": at, "line": ls[key], "after_forecast": made_s is not None and at > made_s}
                                      for at, ls in lines.history if key in ls]
        flags = []
        if f["status"] != "eligible":
            flags.append(f"Recorded {f['status']}: not a locked pregame forecast, never scored.")
        if f["status"] == "eligible" and mp is None:
            flags.append("No eligible moneyline forecast for this game in the log.")
        if f["version"] == "not recorded":
            flags.append("Model version not recorded.")
        items.append({
            **{k: f[k] for k in ("game", "week", "away", "home", "kickoff", "made", "hours_before", "version",
                                 "status", "note", "source", "away_score", "home_score", "home_margin")},
            "favoured": f["home"] if fav_home else f["away"], "underdog": f["away"] if fav_home else f["home"],
            "p": round(p, 4), "market_p": None if mp is None else round(mp, 4),
            "market_line_home": None if not s else s.get("margin_forecast"),
            "disagreement": None if mp is None else round(p - mp, 4),
            "right": won, "tie": f["tie"],
            "brier": None if outcome is None else round((p - outcome) ** 2, 4),
            "surprise": None if outcome is None else round(-math.log(max(1e-6, p if won else 1 - p)), 3),
            "margin_forecast": f["margin_forecast"],
            "margin_error": None if f["margin_forecast"] is None else round(f["home_margin"] - f["margin_forecast"], 1),
            "line_moves": moves,
            "qb": {"home": _qb_change(season, f["week"], f["home"]), "away": _qb_change(season, f["week"], f["away"]),
                   "note": "Starting quarterbacks from nflverse's games file: known at kickoff, NOT at the Thursday "
                           "lock. Shown for review only."},
            "injuries": None, "weather": None, "flags": flags,
        })
    return {"season": season, "games": items, "summary": research_summary(items),
            "missing": ["Pregame injury reports for 2026 are not on this computer (nflverse injuries_2026.csv "
                        "was not downloaded).",
                        "Weather at forecast time is not kept per forecast, so no weather history is shown."]}


def research_summary(items: list[dict]) -> dict:
    """Patterns across eligible, decided forecasts - with sample sizes, and with
    the one test that tells variance from a lean: are the wins in line with the
    chances given?"""
    done = [i for i in items if i["status"] == "eligible" and i["right"] is not None]
    n = len(done)
    if not n:
        return {"games": 0, "findings": [], "note": "No eligible forecast on a finished game yet."}
    expected = sum(i["p"] for i in done)
    actual = sum(i["right"] for i in done)
    sd = math.sqrt(sum(i["p"] * (1 - i["p"]) for i in done))
    z = (actual - expected) / sd if sd else 0.0
    findings = [{
        "kind": "established" if abs(z) < 2 else "worth testing",
        "text": f"The favoured side won {actual} of {n}; the forecasts expected {expected:.1f} "
                f"(spread ±{sd:.1f}). That is {abs(z):.1f} standard deviations "
                f"{'above' if z > 0 else 'below'} - " + ("within ordinary luck." if abs(z) < 2 else
                                                         "outside ordinary luck; worth a closer look."),
    }]
    high = [i for i in done if i["p"] >= 0.65]
    if high:
        findings.append({"kind": "hypothesis" if n < 100 else "established",
                         "text": f"High-confidence picks (65%+): {sum(i['right'] for i in high)} of {len(high)} right, "
                                 f"expected {sum(i['p'] for i in high):.1f}."})
    both = [i for i in done if i["market_p"] is not None]
    if both:
        d_brier = statistics.mean(i["brier"] for i in both)
        m_brier = statistics.mean((i["market_p"] - int(i["right"])) ** 2 for i in both)
        findings.append({"kind": "hypothesis" if len(both) < 200 else "established",
                         "text": f"On the {len(both)} games with an eligible moneyline beside it, Deadeye's Brier "
                                 f"score was {d_brier:.3f} against the market's {m_brier:.3f} "
                                 f"({'better' if d_brier < m_brier else 'worse'}; lower is better). "
                                 "Far too few games to say either is sharper."})
        apart = [i for i in both if abs(i["disagreement"]) >= 0.05]
        if apart:
            findings.append({"kind": "hypothesis",
                             "text": f"Deadeye and the market were 5+ points apart on {len(apart)} games; the side "
                                     f"Deadeye favoured won {sum(i['right'] for i in apart)}."})
    under = [i for i in done if not i["right"]]
    home_fav = sum(i["favoured"] == i["home"] for i in under)
    if under:
        findings.append({"kind": "hypothesis",
                         "text": f"Of the {len(under)} misses, {home_fav} had the home side favoured. "
                                 "Needs many more games before it means anything."})
    return {"games": n, "expected": round(expected, 2), "actual": actual, "z": round(z, 2), "findings": findings,
            "note": "A miss is not evidence of a flaw by itself: a 70% pick should lose three times in ten."}


def experiments(conn: sqlite3.Connection) -> dict:
    """What the app has recorded about model experiments, as stored."""
    from ..model import forecastlog
    try:
        card = forecastlog.scorecard(conn)
    except Exception as exc:  # noqa: BLE001
        card, err = [], str(exc)
    else:
        err = ""
    # The training ground's bench file, read as a file: nothing outside acql/training
    # may import it (tests/test_training.py, Apart), and importing it makes its folder.
    try:
        found = json.loads((ROOT / "data" / "training" / "bench.json").read_text(encoding="utf-8"))
        plans = found.get("plans", []) if isinstance(found, dict) else []
        bench = [h for h in plans if isinstance(h, dict)]
    except (OSError, ValueError):
        bench = []
    return {"scorecard": [{k: r.get(k) for k in ("model_id", "model_name", "games", "hit_rate", "avg_miss",
                                                    "beat_line", "lost_to_line", "line_edge")} for r in card],
            "bench": bench, "error": err,
            "note": "The scorecard grades eligible forecasts on margin and winner. No experiment in the app "
                    "records out-of-sample log loss by itself; the Lab's calibration page computes log loss for "
                    "any model in the forecast log."}
