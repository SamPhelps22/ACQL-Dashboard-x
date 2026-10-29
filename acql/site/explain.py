"""Explain This: what each important number on the website is, where it came
from, how it was worked out, and whether a second count agrees.

    METRICS          the one registry: a definition, method, rules and the
                     data fields each metric is read from, for every metric
                     the site can explain. Pages never describe a metric
                     themselves - they tag a value and the panel looks it up.
    shown_in()       which parts of the website read each metric, found by
                     scanning the page's own code (so it can't go stale).
    build()          the evidence for one snapshot: source files and their
                     times, each week's independent recount, each coach's
                     official figures beside their recounts, and every gap.

Honesty rules, kept by the code and checked by tests/test_explain.py:

  * Nothing here invents a record. A value with no source says so.
  * "verified" is only written when a recount from a different input agreed:
    a week's score re-graded from the picks against ESPN's kept final scores
    (pool.reconcile.check for the games, Big Loser losses read from the same
    final scores). A recount that reuses the official file's own figures is
    called a "cross-check", never verified.
  * A recount that couldn't cover everything (a game with no ESPN final, a
    pick that couldn't be read) is "partial" or "unchecked", never a match.

Read-only: nothing here writes to a stats file, a pick sheet, a result or the
store. No Qt. Kept scores are read, never fetched.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

VERIFIED, CROSS, DIFFERS, PARTIAL, UNCHECKED = "verified", "cross-checked", "differs", "partial", "unchecked"

LINE_RULE = ("A lined game is credited to the favourite only if they win by at least the line; "
             "otherwise the underdog is credited.")
TIE_RULE = "An unlined game that ends level is credited to nobody: every pick on it is wrong."
BL_RULE = "Big Loser: three picks a week, a point each when that team loses by 15 or more."
RANK_RULE = "Equal wins share a place, shown with T- (T-9th, T-9th, T-9th), and the next place is skipped (12th)."

#: Every metric the site can explain. `reads` are the data fields the page
#: code uses for it (searched for in the page to list where it is shown).
METRICS: dict[str, dict] = {
    "weekly_score": {
        "label": "Weekly score",
        "definition": "Games a coach picked right in one week, plus that week's Big Loser points.",
        "method": ("Taken from the week's official standings export (its Total column). "
                   "Recounted independently by re-grading each pick against ESPN's final score "
                   "and counting Big Loser picks whose team lost by 15 or more."),
        "rules": [LINE_RULE, TIE_RULE, BL_RULE],
        "reads": [r"\.weekly\[", r"\bw\.scores\b", r"\.scores\.(forEach|filter|map)", r"\bs\.total\b"],
    },
    "season_wins": {
        "label": "Season wins",
        "definition": "A coach's running total: every finished week's score added up, Big Loser points included.",
        "method": ("When the page shows the season's current week, this is the standings export's season "
                   "total. Otherwise it is worked out here by adding the weekly scores shown. Cross-checked "
                   "against the sum of the weekly scores."),
        "rules": [BL_RULE],
        "reads": [r"\bp\.wins\b", r"\.wins\b"],
    },
    "place": {
        "label": "Place",
        "definition": "Where a coach stands in the pool on season wins.",
        "method": ("Ranked here on the season wins shown: coaches on the same wins share the place, "
                   "shown as T-9th, and the next coach is 12th. The standings export's own tie order is not "
                   "used. Cross-checked by ranking the weekly scores added up."),
        "rules": [RANK_RULE],
        "reads": [r"\.place\b", r"rankAll\("],
    },
    "move": {
        "label": "Rank movement",
        "definition": "Places gained (▲) or lost (▼) since the week before.",
        "method": ("The place after the week before minus the place now, both ranked the same way (shared "
                   "places for equal wins), so a tie never shows as a move. Cross-checked against the weekly "
                   "scores added up."),
        "rules": [RANK_RULE],
        "reads": [r"\.move\b"],
    },
    "h2h": {
        "label": "Head-to-head record",
        "definition": ("Two coaches week by week: weeks each scored higher, and who was right in the games "
                       "where they picked different sides."),
        "method": ("Worked out in your browser from the weekly scores and the pick-by-pick record on this "
                   "page (compare() in the page code). It has no source of its own: it is as sound as the "
                   "weekly scores it is built from."),
        "rules": ["A week with equal scores is level and counts for neither.", LINE_RULE],
        "reads": [r"\bcompare\("],
    },
    "big_loser": {
        "label": "Big Loser points",
        "definition": "Season points from the Big Loser side pool.",
        "method": ("The standings export's Big Loser total when the page shows the current week; otherwise "
                   "the weekly Big Loser points added up. Recounted independently from each week's picks "
                   "and ESPN's final margins."),
        "rules": [BL_RULE],
        "reads": [r"big_loser"],
    },
    "suicide": {
        "label": "Suicide pool status",
        "definition": "Whether a coach is still alive in the suicide pool, or the week they went out.",
        "method": ("Worked out week by week from each coach's pick and the result, with the pool's lines "
                   "applied (the same rule as the recap). A DEAD mark on a sheet means out the week before. "
                   "Compared with the files' own elimination flag."),
        "rules": ["One team a week; the coach is out the first week their team isn't credited with the game.",
                  LINE_RULE],
        "reads": [r"\.suicide\b", r"aliveNames\("],
    },
}

#: Plain names for the page's code files, for "also shown in".
PAGE_NAMES = {
    "020": "Shared helpers", "050": "Live week", "060": "Who can still win", "220": "The week's story",
    "230": "Recap", "290": "Game-day strip", "310": "Cinema mode", "340": "Standings",
    "350": "Side pools", "360": "One week", "370": "Head-to-head", "390": "Week replay",
    "410": "Blind spots", "420": "Pick twins", "440": "Coach page", "450": "Picking profile",
    "460": "Charts", "470": "Season numbers", "480": "Charts page", "490": "History",
    "500": "Trophies", "510": "Share my week", "521": "League modes", "523": "Time Machine",
    "524": "Numbers Room", "525": "Broadcast",
}
_SKIP = {"020", "521"}          # helpers, not something a reader sees


def shown_in(files: list[Path] | None = None) -> dict[str, list[str]]:
    """metric -> the parts of the website whose code reads it, by name."""
    if files is None:
        from ..ui import poolpage
        files = poolpage.parts()
    texts = {}
    for path in files:
        code = Path(path).name[:3]
        if path.suffix != ".js" or code in _SKIP or code not in PAGE_NAMES:
            continue
        texts[PAGE_NAMES[code]] = texts.get(PAGE_NAMES[code], "") + Path(path).read_text(encoding="utf-8")
    out = {}
    for key, meta in METRICS.items():
        pats = [re.compile(p) for p in meta["reads"]]
        out[key] = sorted(name for name, text in texts.items() if any(p.search(text) for p in pats))
    return out


# ---- evidence ------------------------------------------------------------------------

_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/](?:[^\\/\s'\"]+[\\/])+")


def _plain(text: object) -> str:
    """No folder paths on a public page: a file is named by its name alone."""
    text = str(text or "")
    try:
        from ..config import ROOT
        for base in sorted({str(ROOT), str(Path.home())}, key=len, reverse=True):
            for form in (base + "\\", base.replace("\\", "/") + "/"):
                text = re.sub(re.escape(form), "", text, flags=re.I)
    except Exception:  # noqa: BLE001
        pass
    return _PATH.sub("", text).strip()


def _file(name: object) -> str | None:
    """A file named by its own name, whatever folder it is in."""
    text = str(name or "").strip()
    return Path(text.replace("\\", "/")).name or None if text else None


def _when(seconds: float | None) -> str | None:
    if not seconds:
        return None
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(seconds)))


def _status(official, recount, *, independent: bool) -> str:
    if official is None or recount is None:
        return UNCHECKED
    if official != recount:
        return DIFFERS
    return VERIFIED if independent else CROSS


def _place_check(shown, key: str, totals: dict, places: dict) -> tuple[str, str]:
    """A shown place against competition ranking. The standings export gives
    tied coaches different positions (its own tie order); that is consistent
    when the shown place falls inside the tied group."""
    recount = places.get(key)
    if shown is None or recount is None:
        return UNCHECKED, ""
    if shown == recount:
        return CROSS, ""
    tied = sum(1 for v in totals.values() if v == totals[key])
    if recount <= shown <= recount + tied - 1:
        return CROSS, f"tied with {tied - 1} other(s) on {totals[key]}; the standings export's tie order puts them {shown}"
    return DIFFERS, ""


def _bl_status(shown: float, summed: float, independent: float | None) -> str:
    if shown != summed or (independent is not None and independent != shown):
        return DIFFERS
    return VERIFIED if independent is not None else CROSS


def _blown_from_espn(scores: list) -> set[str] | None:
    """Teams that lost by 15+, from ESPN's final scores alone - None unless
    every game kept is final (or called off). Deliberately not the export's
    own Big Loser list, so the recount is independent of it."""
    from ..feeds import results
    from ..model.predictions import team_code
    if not scores or not all(getattr(s, "final", False) or getattr(s, "called_off", False) for s in scores):
        return None
    out = set()
    for s in scores:
        if not s.final or s.home_points is None or s.away_points is None:
            continue
        if abs(s.home_points - s.away_points) >= results.BLOWOUT:
            out.add(team_code(s.home if s.home_points < s.away_points else s.away))
    return out


def _week_check(season, number: int, *, scores_for, sheet_for) -> tuple[dict, dict]:
    """(the week's record, coach key -> [status, recount, official, note,
    Big Loser recount or None])."""
    from ..feeds import results
    from ..model.predictions import team_code
    from ..pool import reconcile
    week = season.weeks[number]
    year = results.season_year(season)
    scores = scores_for(year, number)
    sheet = sheet_for(number)
    played = [g for g in week.games if str(g.winner or "").strip()]
    info = {
        "source": _file(week.source) if week.source else None,
        "source_time": _when(week.source.stat().st_mtime) if week.source and Path(week.source).exists() else None,
        "espn_time": _when(results.fetched_at(year, number)) if scores else None,
        "sheet": _file(getattr(sheet, "source", "")),
        "sheet_graded": bool(getattr(sheet, "graded", False)),
        "games": len(week.games),
        "played": len(played),
        "official": number not in set(getattr(season, "provisional_weeks", []) or []),
        "result_from": sorted({_plain(g.result_from) for g in week.games if getattr(g, "result_from", "")}),
        "game_diffs": [],
        "issues": [],
    }
    coaches: dict[str, list] = {}
    if not scores:
        info["checked"] = 0
        info["issues"].append("No ESPN final scores are kept for this week, so its scores could not be recounted.")
        for key, line in week.lines.items():
            coaches[key] = [UNCHECKED, None, int(line.total_wins or 0), "no ESPN scores kept", None]
        return info, coaches
    report = reconcile.check(season, number, scores=scores, year=year)
    info["checked"] = report.checked_games
    info["game_diffs"] = [{"game": g.index, "matchup": g.matchup, "on_file": g.stored, "espn": g.espn,
                           "why": g.why} for g in report.games]
    whole = report.checked_games >= len(played) and len(played) > 0
    if not whole:
        info["issues"].append(f"ESPN has a final score for {report.checked_games} of {len(played)} played games; "
                              "the other games could not be re-graded.")
    blown = _blown_from_espn(scores)
    if blown is None:
        info["issues"].append("Not every kept ESPN game is final, so Big Loser points could not be recounted.")
    diffs = {" ".join(c.name.split()).casefold(): c for c in report.coaches}
    sheet_losers = {" ".join(str(k).split()).casefold(): v for k, v in (getattr(sheet, "losers", {}) or {}).items()}
    for key, line in week.lines.items():
        player = season.players.get(key)
        name = player.display if player else line.player
        official = int(line.total_wins or 0)
        bl_file = int(line.big_loser_wins or 0)
        diff = diffs.get(" ".join(str(name).split()).casefold())
        regular = (diff.recount if diff else official) - bl_file
        unknown = diff.unknown if diff else 0
        picks = sheet_losers.get(" ".join(str(name).split()).casefold()) or list(line.big_loser_picks or [])
        bl = None
        if blown is not None and picks:
            bl = sum(1 for t in picks if team_code(t) and team_code(t) in blown)
        elif blown is not None and not bl_file:
            bl = 0                    # no Big Loser picks on file and none scored
        if unknown:
            coaches[key] = [UNCHECKED, None, official, f"{unknown} pick(s) couldn't be read", bl]
        elif not whole:
            coaches[key] = [PARTIAL, None, official, "not every game had an ESPN final", bl]
        elif bl is None:
            coaches[key] = [PARTIAL, regular, official, "picks re-graded; Big Loser points not recounted", None]
            if regular + bl_file != official:
                coaches[key] = [DIFFERS, regular + bl_file, official, "picks re-graded; Big Loser taken as on file", None]
        else:
            recount = regular + bl
            coaches[key] = [_status(official, recount, independent=True), recount, official, "", bl]
    return info, coaches


def build(season, *, weeks: list[int], players: list[dict], official: bool,
          generated: str = "", scores_for=None, sheet_for=None, files: list[Path] | None = None) -> dict:
    """The explain block of a snapshot. `players` are the rows the page shows
    (snapshot's own), so each displayed value sits beside its recount.
    `scores_for(year, week)` / `sheet_for(week)` stand in for the kept ESPN
    scores and pick sheets (tests)."""
    from ..feeds import results
    from ..pool import picks as pick_sheets
    from ..ui import poolpage, recap
    scores_for = scores_for or results.load
    sheet_for = sheet_for or pick_sheets.load
    latest = max(weeks, default=0)
    by_name = {p["name"]: p for p in players}

    out_weeks, per_coach = {}, {}
    for n in weeks:
        try:
            info, coaches = _week_check(season, n, scores_for=scores_for, sheet_for=sheet_for)
        except Exception as exc:  # noqa: BLE001 - the panel says so, the page still goes up
            info = {"issues": [f"The recount for this week failed: {_plain(type(exc).__name__)}."], "checked": 0}
            coaches = {k: [UNCHECKED, None, int(l.total_wins or 0), "recount failed", None]
                       for k, l in season.weeks[n].lines.items()}
        out_weeks[str(n)] = info
        for key, row in coaches.items():
            per_coach.setdefault(key, {})[str(n)] = row

    totals = recap._through(season, latest) if latest else {}
    before = recap._through(season, latest - 1) if latest > 1 else {}
    place_now = recap._places(totals) if totals else {}
    place_before = recap._places(before) if before else {}
    try:
        suicide = poolpage._suicide_status(season, weeks, official=False)
    except Exception:  # noqa: BLE001
        suicide = {}

    coaches = {}
    for key, person in season.players.items():
        shown = by_name.get(person.display)
        if shown is None:
            continue
        wk = per_coach.get(key, {})
        statuses = [r[0] for r in wk.values()]
        # Big Loser recount: the weeks whose scores were independently recounted
        bl_weeks = {}
        for n in weeks:
            line = season.weeks[n].lines.get(key)
            if line is not None:
                bl_weeks[str(n)] = int(line.big_loser_wins or 0)
        recount_wins = totals.get(key)
        indep = [r[4] for r in wk.values()]
        bl_indep = float(sum(indep)) if indep and all(v is not None for v in indep) else None
        move_recount = (place_before[key] - place_now[key]) if key in place_now and key in place_before else None
        files_out = person.suicide_out_week if person.suicide_out_week else None
        page_alive, page_out = suicide.get(key, (None, None))
        shown_sui = shown.get("suicide") or {}
        place_status, place_note = _place_check(shown["place"], key, totals, place_now)
        before_shown = (shown["place"] + shown["move"]) if shown["place"] is not None and shown["move"] is not None \
            else place_before.get(key)
        before_status, _ = _place_check(before_shown, key, before, place_before)
        if shown["move"] == move_recount:
            move_status, move_note = _status(shown["move"], move_recount, independent=False), ""
        elif place_status == CROSS and before_status == CROSS and shown["move"] is not None:
            move_status, move_note = CROSS, "differs from a tie-free count only because the export breaks ties"
        else:
            move_status, move_note = _status(shown["move"], move_recount, independent=False), ""
        conflicts = [{"field": c.field, "official": _plain(c.authoritative), "other": _plain(c.other),
                      "note": _plain(c.note)} for c in season.conflicts
                     if " ".join(str(c.player).split()).casefold() in (key, person.display.casefold())]
        coaches[person.display] = {
            "weeks": wk,
            "weeks_verified": statuses.count(VERIFIED),
            "weeks_total": len(statuses),
            "wins": {"shown": shown["wins"], "sum_of_weeks": recount_wins,
                     "status": _status(shown["wins"], recount_wins, independent=False),
                     "from": "standings export" if official and person.wins else "sum of weekly scores"},
            "place": {"shown": shown["place"], "recount": place_now.get(key),
                      "tied": sum(1 for v in totals.values() if v == totals.get(key)) if key in totals else None,
                      "status": place_status, "note": place_note,
                      "from": "ranked here on the wins shown"},
            "move": {"shown": shown["move"], "recount": move_recount,
                     "before": before_shown, "status": move_status, "note": move_note,
                     "from": "ranked here, ties shared"},
            "big_loser": {"shown": shown["big_loser"], "sum_of_weeks": float(sum(bl_weeks.values())),
                          "by_week": bl_weeks, "independent": bl_indep,
                          "status": _bl_status(float(shown["big_loser"] or 0), float(sum(bl_weeks.values())),
                                               bl_indep)},
            "suicide": {"alive": shown_sui.get("alive"), "out": shown_sui.get("out"),
                        "recount_alive": page_alive, "recount_out": page_out, "files_out": files_out,
                        "status": UNCHECKED if page_alive is None else
                        (CROSS if (shown_sui.get("alive"), shown_sui.get("out")) == (page_alive, page_out)
                         and (files_out or None) in (None, page_out) else DIFFERS)},
            "conflicts": conflicts,
        }

    sources = []
    for src in getattr(season, "sources", []) or []:
        sources.append({"name": _file(src.path), "kind": src.kind, "week": src.week,
                        "modified": _when(src.modified), "digest": (src.digest or "")[:10] or None,
                        "error": _plain(src.error) or None})
    try:
        where = shown_in(files)
    except Exception:  # noqa: BLE001
        where = {k: [] for k in METRICS}
    return {
        "version": 1,
        "generated": generated,
        "through_week": latest,
        "official": official,
        "year": results.season_year(season),
        "metrics": {k: {**{f: v for f, v in m.items() if f != "reads"}, "shown_in": where.get(k, [])}
                    for k, m in METRICS.items()},
        "sources": sources,
        "weeks": out_weeks,
        "coaches": coaches,
        "provisional_weeks": sorted(getattr(season, "provisional_weeks", []) or []),
        "warnings": [_plain(w) for w in (getattr(season, "warnings", []) or [])][:20],
    }
