"""Commissioner Import Workbench: check a new stats.xls / ACQL Dashboard.xlsx
before it becomes part of the official record.

Local only - this runs on the commissioner's computer, beside the files. The
website is static (GitHub Pages) and never sees it: no upload, no filesystem
access and no credentials go anywhere near public browser code.

    python -m acql.pool.importbench check FILE         steps 1-3: detect, validate, preview
    python -m acql.pool.importbench approve ID --by NAME [--accept-serious]
    python -m acql.pool.importbench apply ID           step 5: copy in, reload, verify
    python -m acql.pool.importbench undo ID            put the folder back as it was
    python -m acql.pool.importbench history            step 6: every import and its checks

How it fits the existing pipeline: the app reads every stats.xls / workbook in
the data folder through repository.load_season, and the newest stats.xls is
authoritative. So a file is applied the only way the pipeline takes one - it
is copied into the data folder - and the season is then reloaded with the
same load_season the dashboard and website use. Nothing here scores a week or
writes a standing: there is no second scoring engine.

Because the pipeline takes a file whole, approval is for the whole file. A
file with serious changes (an official week's score changing, money changing,
a coach disappearing, a week going backwards) can only be approved with
--accept-serious, by name, and every serious item is listed in the approval.
Conflicts are never resolved automatically.

Safety: before applying, every stats/workbook file in the data folder is
copied to backups/imports/<id>/ and `undo` restores exactly that set. A file
whose content (SHA-256) was already imported, or is already in the data
folder, is refused as a duplicate. History is kept in
data/import-history.json (local; shared history across computers would need a
server with sign-in, which the project doesn't have).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

from .. import config

HISTORY = "import-history.json"
SERIOUS, NOTICE, HARMLESS = "serious", "check", "harmless"


# ---- where things live (overridable in tests) ------------------------------------------
def data_dir() -> Path:
    return Path(config.DATA_DIR)


def backup_root() -> Path:
    return Path(config.BACKUP_DIR) / "imports"


def staging_dir() -> Path:
    return data_dir() / "import-staging"


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _history_path() -> Path:
    return data_dir() / HISTORY


def history() -> list[dict]:
    try:
        return json.loads(_history_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_history(items: list[dict]) -> None:
    config.write_atomic(_history_path(), json.dumps(items, indent=1))


def _entry(import_id: str) -> dict:
    for e in history():
        if e["id"] == import_id:
            return e
    raise KeyError(f"no import {import_id!r}")


def _update(entry: dict) -> None:
    items = [e for e in history() if e["id"] != entry["id"]] + [entry]
    items.sort(key=lambda e: e["id"])
    _save_history(items)


# ---- step 1: detect ----------------------------------------------------------------------
def detect(path: Path) -> dict:
    from ..sources.discovery import classify
    found = classify(Path(path))
    if found is None:
        return {"file": Path(path).name, "kind": None, "error": "not a stats export or dashboard workbook"}
    return {"file": found.path.name, "kind": found.kind, "week": found.week, "season": found.season,
            "error": found.error, "records": "standings, weekly scores, Big Loser, suicide" if found.kind == "stats"
            else "weekly picks, season grid, winnings"}


# ---- the records a file gives, and the ones on file now ----------------------------------
def _records(players) -> dict:
    out = {}
    for key, p in players.items():
        out[key] = {
            "name": p.display,
            "weekly": {int(w): int(v) for w, v in (p.weekly_wins or {}).items()},
            "wins": int(p.wins or 0), "pos": p.pos, "net": round(float(p.net_points or 0), 2),
            "won": round(float(p.points_won or 0), 2), "paid": round(float(p.points_paid or 0), 2),
            "big_loser": float(p.big_loser_points or 0), "suicide_alive": bool(getattr(p, "suicide_alive", False)),
        }
    return out


def candidate(path: Path) -> tuple[dict, dict]:
    """(records, meta) read from the one file, with the pipeline's own parsers."""
    from ..sources.discovery import classify
    from ..sources import parse_stats, parse_workbook
    from ..names import AliasTable
    source = classify(Path(path))
    aliases = AliasTable.load()
    if source is None or source.error:
        raise ValueError(source.error if source else "not a file the pool reads")
    parsed = (parse_stats if source.kind == "stats" else parse_workbook)(source, aliases, {})
    meta = {"kind": source.kind, "week": source.week or parsed.get("week") or parsed.get("current_week"),
            "max_week_score": int(parsed.get("max_regular") or config.GAMES_PER_WEEK) + int(parsed.get("max_big_loser") or config.BIG_LOSER_PICKS),
            "warnings": list(parsed.get("warnings") or [])}
    return _records(parsed["players"]), meta


def current(settings=None) -> tuple[dict, int]:
    """The official records as the dashboard loads them now (offline)."""
    from ..repository import load_season
    settings = settings or config.Settings.load()
    season = load_season(settings, online=False)
    official = {k: v for k, v in _records(season.players).items()}
    for k, p in season.players.items():   # only weeks stats.xls made official
        weeks = getattr(p, "official_weeks", None)
        if weeks:
            official[k]["weekly"] = {w: s for w, s in official[k]["weekly"].items() if w in weeks}
    return official, int(season.current_week or 0)


# ---- step 2 and 3: validate and preview --------------------------------------------------
def compare(new: dict, old: dict, meta: dict, old_week: int) -> list[dict]:
    """Every difference between the file and the record, each with a
    severity: serious (needs --accept-serious), check, or harmless."""
    changes: list[dict] = []

    def add(kind, severity, coach, field, before, after, why):
        changes.append({"n": len(changes) + 1, "kind": kind, "severity": severity, "coach": coach,
                        "field": field, "before": before, "after": after, "why": why})

    week = meta.get("week") or 0
    if old_week and week and week < old_week:
        add("conflict", SERIOUS, "", "week", old_week, week, "the file is older than the record on file")
    top = meta.get("max_week_score") or 99
    by_name: dict[str, list[str]] = {}
    for key, r in new.items():
        by_name.setdefault(r["name"].casefold(), []).append(key)
        for w, v in r["weekly"].items():
            if v < 0 or v > top:
                add("invalid", SERIOUS, r["name"], f"week {w}", None, v, f"outside 0-{top}")
    for name, keys in by_name.items():
        if len(keys) > 1:
            add("duplicate", SERIOUS, name, "coach", None, len(keys), "the same coach appears more than once")
    for key, o in old.items():
        if key not in new:
            add("missing", SERIOUS if meta["kind"] == "stats" else NOTICE, o["name"], "coach", "on record", "absent",
                "a coach on record isn't in the file")
    for key, r in new.items():
        o = old.get(key)
        if o is None:
            add("addition", NOTICE, r["name"], "coach", None, "new", "a coach not on record - check the spelling (aliases.json)")
            continue
        if o["name"] != r["name"]:
            add("rename", HARMLESS, r["name"], "spelling", o["name"], r["name"], "same coach, spelled differently")
        for w in sorted(set(r["weekly"]) | set(o["weekly"])):
            a, b = o["weekly"].get(w), r["weekly"].get(w)
            if a == b:
                continue
            if a is None:
                add("addition", HARMLESS, r["name"], f"week {w}", None, b, "a new result")
            elif b is None:
                add("removal", SERIOUS if meta["kind"] == "stats" else NOTICE, r["name"], f"week {w}", a, None,
                    "an official score would no longer be in the file")
            else:
                add("update", SERIOUS, r["name"], f"week {w}", a, b, "an official score changes - investigate before approving")
        if meta["kind"] == "stats":
            for field in ("won", "paid", "net"):
                a, b = o[field], r[field]
                if a != b and (a or b):
                    later = week and old_week and week > old_week
                    add("money", NOTICE if later else SERIOUS, r["name"], field, a, b,
                        "money moves with the new week" if later else "money changes with no new week")
            if o["pos"] != r["pos"] and r["pos"] is not None:
                add("update", HARMLESS if week > old_week else NOTICE, r["name"], "place", o["pos"], r["pos"], "the table moves")
    return changes


def check(path: Path, settings=None, now: float | None = None) -> dict:
    """Steps 1-3. Records a 'checked' entry in history and returns it."""
    path = Path(path)
    now = time.time() if now is None else now
    found = detect(path)
    entry = {"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + _digest(path)[:6] if path.is_file() else "",
             "file": path.name, "source": str(path.resolve()), "digest": _digest(path) if path.is_file() else "",
             "detected": found, "status": "checked", "checked_at": now, "changes": [], "problems": [], "verify": None}
    if not found.get("kind") or found.get("error"):
        entry["status"] = "rejected"
        entry["problems"].append(found.get("error") or "not a file the pool reads")
        return entry
    dupes = [e for e in history() if e.get("digest") == entry["digest"] and e.get("status") == "applied"]
    on_disk = [p.name for p in data_dir().glob("*") if p.is_file() and p.suffix.lower() in (".xls", ".xlsx")
               and p.resolve() != path.resolve() and _digest(p) == entry["digest"]]
    if dupes or on_disk:
        entry["status"] = "duplicate"
        entry["problems"].append("already imported" + (f" ({dupes[0]['id']})" if dupes else f" ({on_disk[0]} is in the data folder)"))
    try:
        new, meta = candidate(path)
        old, old_week = current(settings)
    except Exception as exc:  # noqa: BLE001 - reported, nothing applied
        entry["status"] = "rejected"
        entry["problems"].append(f"could not be read: {exc}")
        _update(entry)
        return entry
    entry["meta"] = meta
    entry["record_week"] = old_week
    entry["records_examined"] = sum(len(r["weekly"]) for r in new.values()) + len(new)
    entry["changes"] = compare(new, old, meta, old_week)
    entry["problems"] += meta["warnings"]
    _update(entry)
    return entry


# ---- step 4: approve ---------------------------------------------------------------------
def approve(import_id: str, by: str, accept_serious: bool = False, now: float | None = None) -> dict:
    entry = _entry(import_id)
    if entry["status"] != "checked":
        raise PermissionError(f"import {import_id} is {entry['status']}, not waiting for approval")
    if not by.strip():
        raise PermissionError("say who is approving (--by)")
    serious = [c for c in entry["changes"] if c["severity"] == SERIOUS]
    if serious and not accept_serious:
        raise PermissionError(f"{len(serious)} serious change(s) - review them, then approve with --accept-serious")
    entry.update(status="approved", approved_by=by.strip(), approved_at=time.time() if now is None else now,
                 accepted_serious=[c["n"] for c in serious])
    _update(entry)
    return entry


# ---- step 5: apply and verify ------------------------------------------------------------
def _ours(folder: Path) -> list[Path]:
    return [p for p in folder.glob("*") if p.is_file() and p.suffix.lower() in (".xls", ".xlsx")]


def apply(import_id: str, settings=None) -> dict:
    entry = _entry(import_id)
    if entry["status"] != "approved":
        raise PermissionError(f"import {import_id} is {entry['status']}; approve it first")
    source = Path(entry["source"])
    if not source.is_file() or _digest(source) != entry["digest"]:
        raise RuntimeError("the file changed since it was checked - check it again")
    backup = backup_root() / import_id
    backup.mkdir(parents=True, exist_ok=True)
    kept = []
    for p in _ours(data_dir()):
        shutil.copy2(p, backup / p.name)
        kept.append(p.name)
    target = data_dir() / source.name
    if target.exists() and _digest(target) != entry["digest"]:
        target = data_dir() / (source.stem + f" import {import_id}" + source.suffix)   # never overwrite a file on record
    shutil.copy2(source, target)
    entry.update(status="applied", applied_to=target.name, backup=str(backup), backed_up=kept)
    # verify through the same loader the dashboard and site use
    new, meta = candidate(target)
    old, week = current(settings)
    mismatched = [new[k]["name"] for k in new if k in old and meta["kind"] == "stats"
                  and any(old[k]["weekly"].get(w) != v for w, v in new[k]["weekly"].items() if w in old[k]["weekly"])]
    entry["verify"] = {"record_week": week, "coaches": len(old),
                       "matches_file": not mismatched, "mismatched": mismatched[:10],
                       "passed": not mismatched}
    _update(entry)
    return entry


def undo(import_id: str) -> dict:
    """Put the data folder's files back exactly as they were before the import."""
    entry = _entry(import_id)
    if entry["status"] != "applied":
        raise PermissionError(f"import {import_id} is {entry['status']}; only an applied import can be undone")
    backup = Path(entry["backup"])
    applied = data_dir() / entry["applied_to"]
    if applied.exists() and applied.name not in entry["backed_up"]:
        applied.unlink()
    for name in entry["backed_up"]:
        shutil.copy2(backup / name, data_dir() / name)
    entry["status"] = "undone"
    entry["undone_at"] = time.time()
    _update(entry)
    return entry


# ---- step 6: the report ------------------------------------------------------------------
def report(entry: dict) -> str:
    d = entry.get("detected") or {}
    lines = [f"Import {entry['id']}: {entry['file']} - {entry['status'].upper()}",
             f"  detected: {d.get('kind')} week {d.get('week')} {d.get('season') or ''}".rstrip(),
             f"  records examined: {entry.get('records_examined', 0)} (record on file: week {entry.get('record_week')})"]
    for p in entry.get("problems") or []:
        lines.append(f"  ! {p}")
    groups = {SERIOUS: [], NOTICE: [], HARMLESS: []}
    for c in entry.get("changes") or []:
        groups[c["severity"]].append(c)
    for sev, label in ((SERIOUS, "SERIOUS - investigate"), (NOTICE, "Check"), (HARMLESS, "Harmless")):
        rows = groups[sev]
        lines.append(f"  {label}: {len(rows)}")
        for c in rows[:40]:
            lines.append(f"    #{c['n']:<4} {c['kind']:<9} {c['coach'][:22]:<22} {c['field']:<9} "
                         f"{str(c['before']):>10}  ->  {str(c['after']):<10} {c['why']}")
        if len(rows) > 40:
            lines.append(f"    ... {len(rows) - 40} more (full list in {HISTORY})")
    if entry.get("approved_by"):
        lines.append(f"  approved by {entry['approved_by']}" + (f", serious accepted: {entry['accepted_serious']}" if entry.get("accepted_serious") else ""))
    if entry.get("verify"):
        v = entry["verify"]
        lines.append(f"  verify: {'PASSED' if v['passed'] else 'FAILED'} - reloaded {v['coaches']} coaches, record now week {v['record_week']}"
                     + ("" if v["passed"] else f"; differs for {', '.join(v['mismatched'])}"))
        lines.append(f"  backup: {entry['backup']} (undo restores it)")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m acql.pool.importbench", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").add_argument("file")
    a = sub.add_parser("approve"); a.add_argument("id"); a.add_argument("--by", required=True); a.add_argument("--accept-serious", action="store_true")
    sub.add_parser("apply").add_argument("id")
    sub.add_parser("undo").add_argument("id")
    sub.add_parser("history")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            print(report(check(Path(args.file))))
        elif args.cmd == "approve":
            print(report(approve(args.id, args.by, args.accept_serious)))
        elif args.cmd == "apply":
            print(report(apply(args.id)))
        elif args.cmd == "undo":
            print(report(undo(args.id)))
        else:
            for e in history():
                print(f"{e['id']}  {e['status']:<10} {e['file']}  changes {len(e.get('changes') or [])}")
    except (PermissionError, KeyError, RuntimeError) as exc:
        print(f"Not done: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
