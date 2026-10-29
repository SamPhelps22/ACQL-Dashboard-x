"""The Integrity Engine's memory: runs, issues, decisions and the accepted record.

Kept in the app's database under the kind "integrity":

    runs        the last RUNS_KEPT run summaries (when, state, health, counts)
    last        the newest full report, and `last_good` the newest complete one
    issues      every finding ever seen: first seen, last seen, resolved when
    decisions   an append-only log of what someone decided and why
    baseline    the official weekly totals accepted so far, per season

The baseline is how a changed historical record is caught. A week joins it
only after a run in which that week had no open confirmed problem; once in,
it changes only through accept_change - a named person, a note, logged. A
failed or incomplete run never touches it.

Decisions never edit a source file, a result, a pick or a money figure:

    ruling          writes the commissioner's ruling for a week (rulings.py, the
                    existing path) - "official" or "recount" stands
    accept_change   the accepted record takes the new official scores for a week
    acknowledge     a known issue: kept open, marked as seen, with a note
    correction      a proposed corrected value, logged for the commissioner to
                    enter in stats.xls or the workbook; it changes nothing here
"""

from __future__ import annotations

import time

from . import engine

KIND = "integrity"
RUNS_KEPT = 60
DECISIONS = ("ruling", "accept_change", "acknowledge", "correction")
#: A run whose inputs haven't changed is reused this long before running again anyway.
REUSE_S = 6 * 3600
#: And never more often than this, however often the inputs change (a burst of reloads).
MIN_GAP_S = 45


def _get(key: str, default):
    from .. import store
    try:
        found = store.get(KIND, key, default)
    except Exception:  # noqa: BLE001
        return default
    return default if found is None else found


def _put(key: str, value) -> None:
    from .. import store
    store.put(KIND, key, value)


def last() -> dict | None:
    return _get("last", None)


def last_good() -> dict | None:
    return _get("last_good", None)


def runs() -> list[dict]:
    return list(_get("runs", []))


def issues() -> dict:
    return dict(_get("issues", {}))


def decisions() -> list[dict]:
    return list(_get("decisions", []))


def baseline() -> dict:
    return dict(_get("baseline", {}))


def record(report: engine.Report, season=None) -> dict:
    """Keep a finished run: summary, issue log, and - only for weeks that came
    through clean on a complete run - the accepted record."""
    d = report.to_dict()
    summary = {k: d[k] for k in ("run_at", "fingerprint", "state", "health", "complete", "counts",
                                 "through_week", "official_week", "seconds")}
    _put("runs", (runs() + [summary])[-RUNS_KEPT:])
    _put("last", d)
    if report.complete:
        _put("last_good", d)

    log = issues()
    seen = set()
    acknowledged = {x["finding"] for x in decisions() if x["kind"] == "acknowledge"}
    for f in report.findings:
        seen.add(f.id)
        entry = log.get(f.id) or {"first_seen": report.run_at}
        entry.update({"last_seen": report.run_at, "title": f.title, "status": f.status, "severity": f.severity,
                      "check": f.check, "week": f.week, "resolved_at": None,
                      "acknowledged": f.id in acknowledged})
        log[f.id] = entry
    for fid, entry in log.items():
        # Only a check that actually ran can say an issue is gone.
        if fid not in seen and entry.get("resolved_at") is None and \
                (report.checks.get(entry.get("check"), {}).get("ran")):
            entry["resolved_at"] = report.run_at
    _put("issues", log)

    if season is not None and report.complete:
        _grow_baseline(report, season)
    return d


def _grow_baseline(report: engine.Report, season) -> list[int]:
    """Add weeks that aren't in the accepted record yet and came through clean."""
    base = baseline()
    year = str(report.season_year)
    accepted = dict(base.get(year) or {})
    blocked = {f.week for f in report.findings
               if f.status == engine.CONFIRMED and f.week is not None and f.check in ("weekly", "history", "records")}
    added = []
    for wk, scores in engine.official_scores(season).items():
        if wk in accepted or int(wk) in blocked:
            continue
        accepted[wk] = scores
        added.append(int(wk))
    if added:
        base[year] = accepted
        _put("baseline", base)
    return sorted(added)


# --- decisions ------------------------------------------------------------------------------

def decide(kind: str, *, by: str, note: str, finding: str = "", week: int | None = None,
           year: int | None = None, choice: str = "", value=None, season=None,
           now: float | None = None) -> dict:
    """Record a decision. `by` and `note` are required: every change to what the
    engine treats as accepted has a name and a reason on it."""
    by, note = str(by or "").strip(), str(note or "").strip()
    if kind not in DECISIONS:
        raise ValueError(f"unknown decision {kind!r}")
    if not by or not note:
        raise ValueError("a decision needs who made it and why")
    now = time.time() if now is None else now
    entry = {"kind": kind, "by": by, "note": note, "finding": finding, "week": week, "year": year,
             "choice": choice, "value": value, "at": now}
    if kind == "ruling":
        from ..pool import rulings
        if week is None or year is None or choice not in rulings.CHOICES:
            raise ValueError("a ruling needs a week, a season and 'official' or 'recount'")
        rulings.put(year, week, choice, f"{note} ({by}, Integrity Center)", now=now)
    elif kind == "accept_change":
        if week is None or year is None or season is None:
            raise ValueError("accepting a change needs the week, the season year and the loaded season")
        now_scores = engine.official_scores(season).get(str(week))
        if not now_scores:
            raise ValueError(f"week {week} has no official scores to accept")
        base = baseline()
        before = (base.get(str(year)) or {}).get(str(week))
        base.setdefault(str(year), {})[str(week)] = now_scores
        _put("baseline", base)
        entry["value"] = {"before": before, "after": now_scores}
    elif kind == "correction":
        if value in (None, ""):
            raise ValueError("a correction needs the proposed value")
        entry["status"] = "logged - enter it in the source file; nothing here was changed"
    _put("decisions", decisions() + [entry])
    return entry


# --- running ----------------------------------------------------------------------------------

def ensure(season, *, now: float | None = None, force: bool = False, make_context=None) -> dict:
    """The current report: the kept one when nothing it read has changed (and it
    isn't old), otherwise a fresh run. Cheap to call after every reload."""
    now = time.time() if now is None else now
    try:
        stamp = engine.fingerprint(season)
    except Exception:  # noqa: BLE001 - no fingerprint: run
        stamp = ""
    kept = last()
    if kept and not force:
        age = now - float(kept.get("run_at") or 0)
        if stamp and kept.get("fingerprint") == stamp and age < REUSE_S:
            return kept
        if age < MIN_GAP_S:
            return kept
    return run(season, now=now, stamp=stamp, make_context=make_context)


def run(season, *, now: float | None = None, stamp: str = "", make_context=None) -> dict:
    ctx = (make_context or engine.Context)(season, now=now or time.time(), baseline=baseline())
    report = engine.run(ctx)
    report.fingerprint = stamp or engine.fingerprint(season)
    return record(report, season)


def recover(load_season, *, now: float | None = None, make_context=None) -> dict:
    """After a failed or incomplete run: load the season afresh and validate
    again. The accepted record and every official value are left as they were;
    if the new run is still incomplete, the last complete report stays the one
    to trust and is returned beside it."""
    try:
        season = load_season()
    except Exception as exc:  # noqa: BLE001 - the season itself can't be built
        failed = engine.Report(run_at=now or time.time())
        failed.checks["load"] = {"label": "Loading the season", "ran": False, "verified": 0, "seconds": 0,
                                 "error": f"{type(exc).__name__}: {exc}"}
        failed.findings.append(engine.Finding("load", engine.UNAVAILABLE, "critical", "The season couldn't be loaded",
                                              str(exc), field="load"))
        d = record(failed)
        d["trusted"] = last_good()
        return d
    d = run(season, now=now, make_context=make_context)
    d["trusted"] = d if d.get("complete") else last_good()
    return d
