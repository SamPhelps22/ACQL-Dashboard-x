"""Deadeye's own record: the cards it saved before each deadline, scored on both of the lab's questions.

The lab rebuilds Deadeye from the archive (recipes.deadeye_margins). That is a
reconstruction: the weight, the line and the models file are today's idea of
what the week had. The dashboard also kept what Deadeye actually said:

    the card      cards.model(week): each game's side, its chance of being
                  credited, and the market line it was priced from, with the
                  time it was saved. Marked rebuilt when it was made later.
    the ledger    ledger.py: every recipe's home margin, Deadeye's included,
                  written once when the week locked, each game marked
                  before or after its kickoff.

Each week's card is put in one of three piles - "record" (saved before the
lock, not rebuilt), "saved after the deadline", "rebuilt" - and only the
first is the record. Two tracks, as strategy-lab-2 has them:

    acql          the card's own credited chance against the market line it
                  used, on the pool's curve - and how far the books' re-priced
                  Deadeye (data.py, today's code) sits from the card
    probability   the ledger's Deadeye margin and betting line on the
                  straight-up curve (the card keeps no home-win chance, so this
                  is the lab's curve read off the recorded margins)

A card whose market line sits more than MISMATCH_POINTS from the game's own
line at the deadline is flagged: it was priced from another game's number
(week 5 of 2026 has several). It stays in the record - it is what Deadeye
said - and is also scored with those games left out.

Reads the app's database only; writes data/training/record/latest.json.
Nothing here changes a pick. No Qt here.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, strategylab as lab

RECORD, LATE, REBUILT = "record", "saved after the deadline", "rebuilt"

#: A card's market line this far from the game's own line at the deadline was taken
#: from another game (or a misprint): the card is still the record, but it is flagged.
MISMATCH_POINTS = 2.5
#: Week-clustered ranges mean little on fewer weeks than this; they are left out.
MIN_WEEKS_FOR_RANGE = 5


def card_status(saved_at: float | None, lock: float | None, rebuilt: bool) -> str:
    if rebuilt:
        return REBUILT
    if saved_at is None or lock is None or not saved_at < lock:
        return LATE
    return RECORD


def _ledger(year: int, week: int) -> dict:
    from .. import store
    try:
        kept = store.get("ledger", f"{year}-{week}")
    except Exception:  # noqa: BLE001 - no ledger is no ledger
        return {}
    games = (kept or {}).get("games") or []
    games = games.values() if isinstance(games, dict) else games
    return {(g.get("road"), g.get("home")): g for g in games if isinstance(g, dict)}


def gather(year: int, books: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row a game of every week with a kept card: what the card and ledger said, and how it ended."""
    from ..feeds import oddslock
    from ..model.predictions import team_code
    from ..pool import cards
    from . import study
    if books is None:
        books = study.load_books(data.Notes(), frozen=False)
    books = books.assign(game=[data.game_key(s, w, a, h) for s, w, a, h in
                               zip(books["season"], books["week"], books["away"], books["home"])])
    books = books[books["season"] == year].drop_duplicates("game", keep="last").set_index("game")
    rows = []
    for week in range(1, 23):
        snap = cards.model(week)
        if snap is None:
            continue
        try:
            lock = float(oddslock.lock_time(year, week))
        except Exception:  # noqa: BLE001
            lock = None
        status = card_status(snap.at, lock, bool(snap.rebuilt))
        ledger = _ledger(year, week)
        for index, label in snap.label.items():
            teams = cards._teams(label)
            if teams is None or index not in snap.chance:
                continue
            away, home = teams
            game = data.game_key(year, week, away, home)
            take = team_code(snap.take.get(index, ""))
            chance = float(snap.chance[index])
            kept = ledger.get((away, home)) or {}
            margins = kept.get("margins") or {}
            b = books.loc[game] if game in books.index else None
            rows.append({
                "week": week, "game": game, "home": home, "away": away, "status": status,
                "saved_at": snap.at, "lock": lock,
                "card_home_credited": chance if take == home else 1 - chance,
                "card_market": snap.margin.get(index),
                "ledger_before": bool(kept.get("before")) if kept else None,
                "ledger_deadeye": margins.get("Deadeye"), "ledger_market": margins.get("Betting line only"),
                "pool_line": np.nan if b is None else b.get("pool_line"),
                "pool_favourite": "" if b is None else (b.get("pool_favourite") or ""),
                "line_deadline": np.nan if b is None else b.get("line_deadline"),
                "win_deadline": np.nan if b is None else b.get("win_deadline"),
                "replay_home_credited": np.nan if b is None else b.get("deadeye_chance"),
                "credited": np.nan if b is None else b.get("credited_home"),
                "actual": np.nan if b is None else b.get("actual"),
            })
    return pd.DataFrame(rows)


def _num(frame: pd.DataFrame, col: str) -> np.ndarray:
    return pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype=float) if col in frame else \
        np.full(len(frame), np.nan)


def chances(frame: pd.DataFrame) -> pd.DataFrame:
    """Each track's Deadeye and market chances, and its answer, beside every row."""
    out = frame.copy()
    line, fav = _num(out, "pool_line"), out["pool_favourite"].fillna("").tolist()
    none, blank = np.full(len(out), np.nan), [""] * len(out)
    out["acql_deadeye"] = _num(out, "card_home_credited")
    out["acql_market"] = lab.curve_chance(_num(out, "card_market"), line, fav)
    out["acql_y"] = _num(out, "credited")
    out["prob_deadeye"] = lab.curve_chance(_num(out, "ledger_deadeye"), none, blank)
    out["prob_market"] = lab.curve_chance(_num(out, "ledger_market"), none, blank)
    out["prob_y"] = lab.home_won(_num(out, "actual"))
    off = np.abs(_num(out, "card_market") - _num(out, "line_deadline"))
    out["line_mismatch"] = off > MISMATCH_POINTS          # nan compares False: unchecked is not flagged
    out["line_checked"] = ~np.isnan(off)
    return out


def _score(dead: np.ndarray, mkt: np.ndarray, y: np.ndarray, weeks: np.ndarray, picks: bool) -> dict:
    m = ~np.isnan(dead) & ~np.isnan(mkt) & ~np.isnan(y)
    if m.sum() < 2:
        return {"games": int(m.sum())}
    d, k, yy, w = dead[m], mkt[m], y[m], weeks[m]
    n_weeks = int(len(set(w.tolist())))
    out = {"games": int(m.sum()), "weeks": n_weeks, "deadeye": lab.metrics(d, yy),
           "market": lab.metrics(k, yy), "deadeye_vs_market": lab.paired(d, k, yy, w)}
    if picks:
        out["picks_deadeye_vs_market"] = lab.picks_paired(d, k, yy, w)
    if n_weeks < MIN_WEEKS_FOR_RANGE:
        for key in ("deadeye_vs_market", "picks_deadeye_vs_market"):
            if key in out:
                out[key].update({"low": None, "high": None, "se": None, "p": None,
                                 "range": f"left out: {n_weeks} week(s), {MIN_WEEKS_FOR_RANGE}+ needed"})
    return out


def score(frame: pd.DataFrame) -> dict:
    """Both tracks, the record apart from everything else; and how far the books' re-pricing drifts."""
    c = chances(frame) if len(frame) else frame
    out: dict = {"weeks": {}, "tracks": {}}
    if not len(c):
        return out
    for week, rows in c.groupby("week"):
        out["weeks"][int(week)] = {"status": rows["status"].iloc[0], "games": int(len(rows)),
                                   "graded": int(rows["acql_y"].notna().sum()),
                                   "ledger_before": int((rows["ledger_before"] == True).sum()),  # noqa: E712
                                   "line_checked": int(rows["line_checked"].sum()),
                                   "line_mismatch": sorted(rows.loc[rows["line_mismatch"], "game"].tolist())}
    piles = [(s, c[c["status"] == s]) for s in (RECORD, LATE, REBUILT)]
    piles.append((RECORD + ", lines matching", c[(c["status"] == RECORD) & ~c["line_mismatch"]]))
    for status, part in piles:
        if not len(part):
            continue
        weeks = part["week"].to_numpy()
        acql = _score(part["acql_deadeye"].to_numpy(), part["acql_market"].to_numpy(),
                      part["acql_y"].to_numpy(), weeks, True)
        before = part[part["ledger_before"] == True]  # noqa: E712 - only margins written before kickoff
        prob = _score(before["prob_deadeye"].to_numpy(), before["prob_market"].to_numpy(),
                      before["prob_y"].to_numpy(), before["week"].to_numpy(), False)
        out["tracks"][status] = {"acql": acql, "probability": prob}
    rec = c[c["status"] == RECORD]
    gap = np.abs(_num(rec, "replay_home_credited") - _num(rec, "card_home_credited"))
    gap = gap[~np.isnan(gap)]
    turned = ((_num(rec, "replay_home_credited") > 0.5) != (_num(rec, "card_home_credited") > 0.5))
    turned &= ~np.isnan(_num(rec, "replay_home_credited"))
    out["replay_drift"] = {"games": int(len(gap)), "mean": float(gap.mean()) if len(gap) else None,
                           "largest": float(gap.max()) if len(gap) else None, "other_side": int(turned.sum()),
                           "note": "the books' Deadeye (today's code and data) against the card it saved"}
    return out


def folder() -> Path:
    where = data.folder() / "record"
    where.mkdir(parents=True, exist_ok=True)
    return where


def run(year: int = 2026, write: bool = True) -> dict:
    found = {"year": year, "made": time.time(), **score(gather(year))}
    if write:
        (folder() / "latest.json").write_text(json.dumps(found, indent=1, default=lab._json), encoding="utf-8")
    return found
