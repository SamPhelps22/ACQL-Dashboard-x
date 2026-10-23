"""The strategy lab's locked forecasts: written once before the deadline, never rewritten.

The backtest can say what each strategy *would* have said. Only a forecast
written down before the games, and never touched again, can say what it
*did* say. So each week, before the pool's Thursday deadline, every strategy
the newest lab run sent to its final test (and the market and Deadeye beside
them) prices that week's games, and the lot is written to

    data/training/lab/locked/<season>-w<week>.json

and its fingerprint appended to locked/chain.jsonl, each entry carrying the
fingerprint of the one before it. Rules:

    one file a week   opened with exclusive create: a second lock for the same
                      week is refused, whatever it would say
    before the lock   a lock at or after the deadline is refused
    read-only         the file is marked read-only once written
    checkable         `verify` re-reads every file against the chain; a file
                      changed, removed or added outside the chain is reported

Retraining, new data or a new lab run never reach a locked file - they can
only write next week's. Scoring a locked week (`score`) only reads.

No Qt here.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, strategylab as lab

CHAIN = "chain.jsonl"
#: The weekly job (Tue/Wed/Thu 12:30) locks only this close to the deadline, so the
#: Thursday run - with the freshest line - is the one that locks.
LOCK_WINDOW_S = 12 * 3600


class LockRefused(RuntimeError):
    pass


def folder(root: Path | None = None) -> Path:
    where = Path(root) if root is not None else lab.folder() / "locked"
    where.mkdir(parents=True, exist_ok=True)
    return where


def path_for(season: int, week: int, root: Path | None = None) -> Path:
    return folder(root) / f"{int(season)}-w{int(week):02d}.json"


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=lab._json).encode("utf-8")


def _chain(root: Path | None = None) -> list[dict]:
    from .journal import read
    return read(folder(root) / CHAIN)


def _entry_mark(entry: dict) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in entry.items() if k != "mark"})).hexdigest()


def lock(season: int, week: int, deadline: float, forecasts: list[dict], about: dict | None = None, *,
         now: float | None = None, root: Path | None = None) -> Path:
    """Write a week's forecasts for good. Refused after the deadline or if the week is already locked."""
    now = time.time() if now is None else now
    if not deadline or now >= float(deadline):
        raise LockRefused(f"{season} week {week}: the deadline has passed - too late to lock")
    if not forecasts:
        raise LockRefused(f"{season} week {week}: nothing to lock")
    path = path_for(season, week, root)
    body = {"season": int(season), "week": int(week), "deadline": float(deadline), "locked_at": float(now),
            "locked_utc": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(now)), "about": about or {},
            "forecasts": forecasts}
    raw = json.dumps(body, indent=1, sort_keys=True, default=lab._json).encode("utf-8")
    try:
        with open(path, "xb") as handle:            # exclusive: never over an existing lock
            handle.write(raw)
    except FileExistsError:
        raise LockRefused(f"{season} week {week} is already locked ({path.name}) - a lock is never rewritten")
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass
    chain = _chain(root)
    entry = {"season": int(season), "week": int(week), "file": path.name,
             "sha256": hashlib.sha256(raw).hexdigest(), "locked_at": float(now),
             "previous": chain[-1]["mark"] if chain else ""}
    entry["mark"] = _entry_mark(entry)
    with open(folder(root) / CHAIN, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return path


def verify(root: Path | None = None) -> list[str]:
    """Every problem with the locked record; an empty list means every lock is as it was written."""
    problems, previous = [], ""
    chain = _chain(root)
    named = set()
    for entry in chain:
        named.add(entry.get("file"))
        if entry.get("previous", "") != previous:
            problems.append(f"{entry.get('file')}: the chain is broken before it")
        if _entry_mark(entry) != entry.get("mark"):
            problems.append(f"{entry.get('file')}: its chain entry was edited")
        previous = entry.get("mark", "")
        path = folder(root) / str(entry.get("file"))
        if not path.exists():
            problems.append(f"{entry.get('file')}: locked, now missing")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
            problems.append(f"{entry.get('file')}: changed since it was locked")
        else:
            body = json.loads(path.read_bytes())
            if body.get("locked_at", 0) >= body.get("deadline", 0):
                problems.append(f"{entry.get('file')}: locked after its deadline")
    for path in folder(root).glob("*-w*.json"):
        if path.name not in named:
            problems.append(f"{path.name}: not in the chain - written outside the lock")
    return problems


def read(season: int, week: int, root: Path | None = None) -> dict | None:
    try:
        return json.loads(path_for(season, week, root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---- the week's forecasts ----------------------------------------------------------------------------
def two_tracks(results: dict) -> bool:
    """A strategy-lab-2 run: one set of finalists per track."""
    return "tracks" in results and isinstance(results.get("finalists"), dict)


def _specs_from(results: dict, track: str | None = None) -> list[lab.Spec]:
    """The newest run's finalists (for `track`, on a two-track run), every strategy they are
    built from, and the two baselines."""
    if two_tracks(results):
        tr = results["tracks"][track]
        primary, finalists = tr["timings"][results["primary_timing"]]["specs"], tr["finalists"]
    else:
        primary = results["timings"][results["protocol"]["primary_timing"]]["specs"]
        finalists = results["finalists"]
    made = {i: lab.Spec(d["spec"]["family"], d["spec"]["name"], d["spec"]["params"], tuple(d["spec"]["inputs"]),
                        tuple(d["spec"]["members"]), d["spec"]["round"], d["spec"]["baseline"])
            for i, d in primary.items()}
    want, todo = set(), list(finalists) + [lab.MARKET_SPEC.id, lab.DEADEYE_SPEC.id]
    while todo:
        i = todo.pop()
        if i in want or i not in made:
            continue
        want.add(i)
        todo.extend(made[i].members)
    return [made[i] for i in made if i in want]


def _schedule_facts(rows: pd.DataFrame) -> pd.DataFrame:
    """Rest and division from nflverse's schedule (known long before the game)."""
    try:
        verse = data.nflverse_games()
    except Exception:  # noqa: BLE001
        return rows
    verse = verse.assign(game=[data.game_key(s, w, a, h) for s, w, a, h in
                               zip(verse["season"], verse["week"], verse["away"], verse["home"])])
    facts = verse.set_index("game")[["rest", "division"]]
    for col in ("rest", "division"):
        rows[col] = rows["game"].map(facts[col]) if col not in rows or rows[col].isna().all() else rows[col]
    return rows


def forecasts(season: int, week: int, results: dict | None = None) -> tuple[list[dict], dict]:
    """Every finalist's chance for each game of the week, priced as of now from
    the line taken nearest before the deadline. (forecasts, about)."""
    from . import study
    results = results or json.loads((lab.folder() / "latest" / "results.json").read_text(encoding="utf-8"))
    if two_tracks(results):
        return _forecasts2(season, week, results)
    specs = _specs_from(results)
    notes = data.Notes()
    history = data.check(data.history(notes=notes), notes)
    books = study.load_books(notes, frozen=False)
    if books.empty:
        return [], {"why": "this season's records could not be read"}
    week_rows = books[(books["season"] == season) & (books["week"] == week)].copy()
    week_rows["game"] = [data.game_key(s, w, a, h) for s, w, a, h in
                         zip(week_rows["season"], week_rows["week"], week_rows["away"], week_rows["home"])]
    priced = week_rows[week_rows["line_deadline"].notna()].copy()
    skipped = sorted(set(week_rows["game"]) - set(priced["game"]))
    if priced.empty:
        return [], {"why": "no line for any game of the week yet", "skipped": skipped}
    priced["line_midweek"] = priced["line_deadline"]
    for col in ("actual", "home_points", "away_points", "credited_home"):
        priced[col] = np.nan                    # nothing about the result goes near a forecast
    priced = _schedule_facts(priced)
    timing = results["protocol"]["primary_timing"]
    past = history[history["season"] < season]
    combined = pd.concat([past, priced], ignore_index=True)
    graded = books[books["home_points"].notna() & (books["week"] < week)]
    universe = lab.results_universe(past, extra=graded)
    frame = lab.table(combined, timing, universe=universe)
    chances, _ = lab.walk(frame, specs)
    live = (frame["season"] == season).to_numpy()
    out = []
    for i in np.flatnonzero(live):
        row = frame.iloc[i]
        said = {s.id: (None if np.isnan(chances.at[frame.index[i], s.id]) else
                       round(float(chances.at[frame.index[i], s.id]), 6)) for s in specs}
        out.append({"game": row["game"], "home": row["home"], "away": row["away"], "line": float(row["market"]),
                    "pool_line": None if pd.isna(row["pool_line"]) else float(row["pool_line"]),
                    "pool_favourite": row["pool_favourite"] or "",
                    "models": int(row["n_models"]) if not pd.isna(row["n_models"]) else 0,
                    "chances": said})
    taken = priced["taken_at"].dropna()
    about = {"run": results["run"], "protocol": results["protocol"]["id"], "lab": lab.LAB_VERSION,
             "finalists": results["finalists"], "names": {s.id: s.name for s in specs},
             "line_taken_latest": float(taken.max()) if len(taken) else None, "skipped": skipped,
             "note": "home side's chance of being credited under the pool's rules"}
    return out, about


def _week_inputs(season: int, week: int) -> tuple[pd.DataFrame, pd.DataFrame, list[str], pd.DataFrame] | None:
    """(past seasons, this week's rows priced from the deadline line with every answer blanked,
    games without a line yet, results universe) - or None when there is nothing to price."""
    from . import study
    notes = data.Notes()
    history = data.check(data.history(notes=notes), notes)
    books = study.load_books(notes, frozen=False)
    if books.empty:
        return None
    week_rows = books[(books["season"] == season) & (books["week"] == week)].copy()
    week_rows["game"] = [data.game_key(s, w, a, h) for s, w, a, h in
                         zip(week_rows["season"], week_rows["week"], week_rows["away"], week_rows["home"])]
    priced = week_rows[week_rows["line_deadline"].notna()].copy()
    skipped = sorted(set(week_rows["game"]) - set(priced["game"]))
    priced["line_midweek"] = priced["line_deadline"]
    for col in ("actual", "home_points", "away_points", "credited_home"):
        priced[col] = np.nan                    # nothing about the result goes near a forecast
    priced = _schedule_facts(priced)
    past = history[history["season"] < season]
    graded = books[books["home_points"].notna() & (books["week"] < week)]
    return past, priced, skipped, lab.results_universe(past, extra=graded)


def _forecasts2(season: int, week: int, results: dict) -> tuple[list[dict], dict]:
    """strategy-lab-2: each track's finalists price the week on that track's own question."""
    got = _week_inputs(season, week)
    if got is None:
        return [], {"why": "this season's records could not be read"}
    past, priced, skipped, universe = got
    if priced.empty:
        return [], {"why": "no line for any game of the week yet", "skipped": skipped}
    timing = results["primary_timing"]
    combined = pd.concat([past, priced], ignore_index=True)
    by_game: dict[str, dict] = {}
    names: dict[str, str] = {}
    for track, about in lab.TRACKS.items():
        specs = _specs_from(results, track)
        names.update({s.id: s.name for s in specs})
        frame = lab.table(combined, timing, universe=universe, target=about["target"])
        chances, _ = lab.walk(frame, specs)
        for i in np.flatnonzero((frame["season"] == season).to_numpy()):
            row = frame.iloc[i]
            f = by_game.setdefault(row["game"], {
                "game": row["game"], "home": row["home"], "away": row["away"], "line": float(row["market"]),
                "pool_line": None if pd.isna(row["pool_line"]) else float(row["pool_line"]),
                "pool_favourite": row["pool_favourite"] or "",
                "models": int(row["n_models"]) if not pd.isna(row["n_models"]) else 0, "tracks": {}})
            f["tracks"][track] = {s.id: (None if np.isnan(chances.at[frame.index[i], s.id]) else
                                         round(float(chances.at[frame.index[i], s.id]), 6)) for s in specs}
    taken = priced["taken_at"].dropna()
    about = {"run": results["run"], "protocol": results["protocol"]["id"], "lab": lab.LAB_VERSION,
             "finalists": results["finalists"], "names": names,
             "line_taken_latest": float(taken.max()) if len(taken) else None, "skipped": skipped,
             "tracks": {t: a["chance"] for t, a in lab.TRACKS.items()}}
    return list(by_game.values()), about


def current_week(now: float | None = None) -> tuple[int | None, int | None]:
    """The next week whose deadline is still ahead, from the books."""
    from . import study
    now = time.time() if now is None else now
    books = study.load_books(data.Notes(), frozen=False)
    if books.empty or "locked_at" not in books:
        return None, None
    ahead = books[books["locked_at"] > now]
    if ahead.empty:
        return None, None
    first = ahead.sort_values("locked_at").iloc[0]
    return int(first["season"]), int(first["week"])


def deadline_for(season: int, week: int) -> float | None:
    from . import study
    books = study.load_books(data.Notes(), frozen=False)
    rows = books[(books["season"] == season) & (books["week"] == week)]
    kept = rows["locked_at"].dropna() if "locked_at" in rows else pd.Series(dtype=float)
    return float(kept.min()) if len(kept) else None


def lock_week(season: int, week: int, *, now: float | None = None, window: float | None = LOCK_WINDOW_S) -> str:
    """Lock this week if it is time (within `window` of the deadline) and not done. Says what happened."""
    now = time.time() if now is None else now
    if path_for(season, week).exists():
        return f"{season} week {week} is already locked"
    deadline = deadline_for(season, week)
    if deadline is None:
        return f"{season} week {week}: no deadline on the books - not locked"
    if now >= deadline:
        return f"{season} week {week}: the deadline has passed - not locked"
    if window is not None and deadline - now > window:
        return f"{season} week {week}: {(deadline - now) / 3600:.0f}h before the deadline - too early, not locked"
    made, about = forecasts(season, week)
    if not made:
        return f"{season} week {week}: nothing to lock ({about.get('why')})"
    path = lock(season, week, deadline, made, about, now=now)
    return f"locked {len(made)} games in {path.name}" + (f"; {len(about['skipped'])} without a line yet"
                                                        if about.get("skipped") else "")


def score(root: Path | None = None) -> dict:
    """Each locked week against the results that came in. Reads only."""
    from . import study
    books = study.load_books(data.Notes(), frozen=False)
    books = books.assign(game=[data.game_key(s, w, a, h) for s, w, a, h in
                               zip(books["season"], books["week"], books["away"], books["home"])])
    came = books.set_index("game")["credited_home"]
    totals: dict[str, dict] = {}
    weeks = []
    for path in sorted(folder(root).glob("*-w*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        if body["forecasts"] and "tracks" in body["forecasts"][0]:
            continue                            # a two-track lock: see judge()
        graded = [f for f in body["forecasts"] if f["game"] in came.index and not pd.isna(came[f["game"]])]
        if not graded:
            continue
        weeks.append(path.stem)
        for f in graded:
            y = float(came[f["game"]])
            for sid, p in f["chances"].items():
                if p is None:
                    continue
                t = totals.setdefault(sid, {"games": 0, "loss": 0.0, "right": 0})
                q = min(max(p, 0.01), 0.99)
                t["games"] += 1
                t["loss"] -= y * np.log(q) + (1 - y) * np.log(1 - q)
                t["right"] += int((p > 0.5) == (y > 0.5) and p != 0.5)
    return {"weeks": weeks, "strategies": {k: {**v, "logloss": v["loss"] / v["games"]} for k, v in totals.items()}}


# ---- strategy-lab-2: the locked weeks judged, a track at a time --------------------------------------
def locked_rows(root: Path | None = None, books: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Every graded game in a two-track lock, per track: the lock's week, the answer to that
    track's question, and every strategy's locked chance. Reads only."""
    if books is None:
        from . import study
        books = study.load_books(data.Notes(), frozen=False)
    out: dict[str, list] = {t: [] for t in lab.TRACKS}
    if books is None or books.empty:
        return {t: pd.DataFrame() for t in lab.TRACKS}
    books = books.assign(game=[data.game_key(s, w, a, h) for s, w, a, h in
                               zip(books["season"], books["week"], books["away"], books["home"])])
    idx = books.drop_duplicates("game", keep="last").set_index("game")
    credited = idx["credited_home"] if "credited_home" in idx else pd.Series(np.nan, index=idx.index)
    margin = idx["home_points"].astype(float) - idx["away_points"].astype(float)
    for path in sorted(folder(root).glob("*-w*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        for f in body.get("forecasts", []):
            if "tracks" not in f or f["game"] not in idx.index:
                continue
            for track, said in f["tracks"].items():
                if track not in out:
                    continue
                y = credited[f["game"]] if track == "acql" else lab.home_won(np.array([margin[f["game"]]]))[0]
                if y is None or pd.isna(y):
                    continue
                out[track].append({"game": f["game"], "week": path.stem, "y": float(y), **said})
    return {t: pd.DataFrame(v) for t, v in out.items()}


def judge_rows(rows: dict[str, pd.DataFrame], results: dict) -> dict:
    """Each track's frozen finalists on the locked weeks, against the gates PROTOCOL_2 wrote down."""
    p2 = lab.PROTOCOL_2
    alpha, mk, de = p2["alpha"], lab.MARKET_SPEC.id, lab.DEADEYE_SPEC.id
    clean = (results.get("faulty_share") or 0.0) < 0.01
    out = {}
    for track in lab.TRACKS:
        prob = track == "probability"
        df = rows.get(track)
        df = pd.DataFrame() if df is None else df
        finalists = list(results["finalists"][track])
        dev_specs = results["tracks"][track]["timings"][results["primary_timing"]]["specs"]
        leak = (results.get("leak") or {}).get(track)
        scored: dict[str, dict] = {}
        for sid in finalists:
            if df.empty or not {sid, mk, de} <= set(df.columns):
                scored[sid] = {"games": 0}
                continue
            m = df[[sid, mk, de]].notna().all(axis=1).to_numpy()
            if m.sum() < 2:
                scored[sid] = {"games": int(m.sum())}
                continue
            p, pm, pd_ = (df.loc[m, c].to_numpy(dtype=float) for c in (sid, mk, de))
            y, weeks = df.loc[m, "y"].to_numpy(dtype=float), df.loc[m, "week"].to_numpy()
            row = {**lab.metrics(p, y), "deadeye_calibration": lab.metrics(pd_, y)["calibration"],
                   "vs_deadeye": lab.paired(p, pd_, y, weeks), "vs_market": lab.paired(p, pm, y, weeks)}
            if not prob:
                row["picks_vs_deadeye"] = lab.picks_paired(p, pd_, y, weeks)
            scored[sid] = row
        key = "vs_deadeye" if prob else "picks_vs_deadeye"
        adjusted = lab.holm({s: r[key]["p"] for s, r in scored.items() if key in r}, len(finalists))
        nominee = None
        for sid, r in scored.items():
            dev = (dev_specs.get(sid) or {}).get("dev") or {}
            dev_edge = (dev.get(lab._key(track, "deadeye")) or {}).get("edge") or 0.0
            enough = (r.get("games", 0) >= p2["min_test_games"]
                      and (r.get("vs_deadeye") or {}).get("weeks", 0) >= p2["min_test_weeks"])
            test = r.get(key) or {}
            beats = adjusted.get(sid, 1.0) < alpha and (test.get("edge") or 0.0) > 0
            if prob:
                g = {"development: ahead of Deadeye": dev_edge > 0,
                     "locked: 150+ games over 10+ weeks": enough,
                     "locked: better than Deadeye (Holm)": beats,
                     "locked: better than the market": ((r.get("vs_market") or {}).get("p", 1.0) < alpha
                                                        and ((r.get("vs_market") or {}).get("edge") or 0.0) > 0),
                     "locked: calibration no worse": (r.get("calibration") is not None and
                                                      r["calibration"] <= r["deadeye_calibration"]
                                                      + p2["calibration_slack"]),
                     "leak check passed": bool(leak and leak[0]), "data clean": clean}
            else:
                g = {"development: ahead of Deadeye on picks": dev_edge > 0,
                     "locked: 150+ games over 10+ weeks": enough,
                     "locked: more picks than Deadeye (Holm)": beats,
                     "locked: credited log loss not clearly worse": ((r.get("vs_deadeye") or {}).get("high")
                                                                     is not None and r["vs_deadeye"]["high"] >= 0),
                     "leak check passed": bool(leak and leak[0]), "data clean": clean}
            r["holm_vs_deadeye"], r["gates"] = adjusted.get(sid), g
            if all(g.values()) and (nominee is None or test["edge"] > scored[nominee][key]["edge"]):
                nominee = sid
        games = int(len(df))
        weeks_n = int(df["week"].nunique()) if games else 0
        if nominee:
            why = f"passed every gate on {games} locked games over {weeks_n} weeks - a nomination for the owner"
        elif not games:
            why = "no locked week has been scored yet - only forecasts locked before the deadline can earn a nomination"
        else:
            why = (f"{games} locked games over {weeks_n} weeks scored; no finalist has passed every gate "
                   f"(the first is {p2['min_test_games']}+ games over {p2['min_test_weeks']}+ weeks)")
        out[track] = {"games": games, "weeks": weeks_n, "finalists": scored, "nominee": nominee, "why": why}
    return out


def judge(root: Path | None = None, results: dict | None = None, *, write: bool = False) -> dict | None:
    """The locked weeks against the newest two-track run's gates; `write` updates champions.json.
    None when the newest run is not a two-track run."""
    if results is None:
        try:
            results = json.loads((lab.folder() / "latest" / "results.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    if not two_tracks(results):
        return None
    found = judge_rows(locked_rows(root), results)
    if write:
        lab.write_champions(results["run"], results["finalists"], found)
    return found
