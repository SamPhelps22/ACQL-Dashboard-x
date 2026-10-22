"""Pro Football Mania's team ratings, collected as dated snapshots.

PFM (profootballmania.com) publishes a Team Score for every club, built from
seven weighted grades (QB Stability 25%, Roster Strength 20%, Coaching
Direction 15%, Recent Performance 15%, Offense 10%, Defense 10%, Franchise
Direction 5%), plus an Explosiveness grade that is not in the score. It says
itself that the score "is not a betting line, a game prediction or a precise
playoff probability". Whether it adds anything to Deadeye is measured apart,
in acql/training/pfm.py; nothing here changes a pick.

What the site gives, and from when (audited 2026-10-18):

    ratings table    /nfl-team-rankings/: all 32 teams, the score and six of
                     the seven grades to two or three decimals, the record,
                     and the date of the update (a <time datetime> tag)
    explosiveness    /nfl-team-explosiveness-rankings/: the eighth grade
    changes          /nfl-ranking-changes/: each update's score before and
                     after, by date - only the newest two updates are kept
    team pages       /nfl-team-dashboards/<team>/: the score after every week
                     so far (BASELINE, W1, W2, ...), one decimal, no dates
    methodology      /pfm-methodology/: the weights and the version history

The score began on 2026-06-25, so there is no earlier season to test on.
Past grades are not published, only past scores. robots.txt allows
everything, there is no terms-of-use page and no API, and every page carries
the site's copyright notice. So the numbers are kept on this computer only
(data/pfm/, never committed - the repository is public) and never shown on
the pool's website. Sam approved a first pull and weekly pulls on 2026-10-18.

Each pull is one snapshot file, never overwritten. A pull that finds the same
numbers as the newest snapshot writes no new file, only a line in the import
log. A failed pull keeps the last good snapshot, and `freshness` says how old
it is. Every value in a snapshot comes from the site as published, except
what sits under "derived", which the app worked out itself.

Nothing here knows about Qt, and nothing here is read by the pricing.
"""

from __future__ import annotations

import hashlib
import html as htmllib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SOURCE = "Pro Football Mania"
SITE = "https://profootballmania.com"
RANKINGS_URL = SITE + "/nfl-team-rankings/"
EXPLOSIVE_URL = SITE + "/nfl-team-explosiveness-rankings/"
CHANGES_URL = SITE + "/nfl-ranking-changes/"
METHOD_URL = SITE + "/pfm-methodology/"
TEAM_URL = SITE + "/nfl-team-dashboards/{slug}/"

#: How the snapshot files are laid out; raise it if the layout changes.
SCHEMA = 1
TIMEOUT = 40
#: Tries for each page, and the wait between them (seconds, doubled each time).
TRIES = 3
BACKOFF = 4.0
#: Seconds between one page and the next: the site is small and independent.
PAUSE = 2.0
#: PFM updates once a week (Tuesdays in the season). An update older than
#: this is shown as stale.
STALE_DAYS = 9
#: The public score worked out again from the grades (the published formula)
#: may be this far from the published one before the two are called a contradiction.
FORMULA_SLACK = 0.15

#: The grades, by the name kept here: (heading on the ratings table, weight in the score).
GRADES = {
    "qb_stability": ("QB Stability", 0.25),
    "roster_strength": ("Roster Strength", 0.20),
    "coaching_direction": ("Coaching Direction", 0.15),
    "recent_performance": ("Recent Performance", 0.15),
    "offense_strength": ("Offense", 0.10),
    "defense_strength": ("Defense", 0.10),
    "franchise_direction": ("Franchise Direction", 0.05),
}
#: Graded by PFM but not part of the score.
EXTRA_GRADES = ("explosiveness",)
FIELDS = ("score",) + tuple(GRADES) + EXTRA_GRADES
#: PFM's abbreviations where they differ from the dashboard's codes.
ABBR = {"wsh": "was", "jac": "jax", "la": "lar", "lvr": "lv", "arz": "ari"}


class PfmError(Exception):
    """A page could not be fetched or read, in words fit to show."""


# ---- where things are kept ------------------------------------------------------------------------
def folder() -> Path:
    from ..store import data_dir
    where = data_dir() / "pfm"
    (where / "snapshots").mkdir(parents=True, exist_ok=True)
    ignore = where / ".gitignore"
    if not ignore.is_file():
        # the repository is public and these are someone else's numbers
        ignore.write_text("# PFM snapshots: this computer's own, never committed\n*\n", encoding="utf-8")
    return where


# ---- reading the pages ----------------------------------------------------------------------------
_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td\b([^>]*)>(.*?)</td>", re.S | re.I)
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
_TAG = re.compile(r"<[^>]+>")
_TIME = re.compile(r'<time\b[^>]*\bdatetime="(\d{4}-\d{2}-\d{2})"', re.I)


def _text(fragment: str) -> str:
    return " ".join(htmllib.unescape(_TAG.sub(" ", fragment)).split())


def _float(text: object) -> float | None:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if value == value else None


def _cells(row: str) -> dict[str, tuple[str, str]]:
    """data-label -> (data-sort-value, text) for one table row."""
    out = {}
    for attributes, inner in _CELL.findall(row):
        found = {k.lower(): htmllib.unescape(v).strip() for k, v in _ATTR.findall(attributes)}
        if "data-label" in found:
            out[found["data-label"]] = (found.get("data-sort-value", ""), _text(inner))
    return out


def effective_date(page: str) -> str | None:
    """The update date the page states (its first <time datetime>), as YYYY-MM-DD."""
    found = _TIME.search(page or "")
    return found.group(1) if found else None


def team_code(name: str) -> str:
    from ..model.predictions import team_code as code
    return code(name)


def parse_rankings(page: str) -> dict[str, dict]:
    """The ratings table: team code -> name, rank, record, score and the seven grades."""
    out: dict[str, dict] = {}
    for row in _ROW.findall(page or ""):
        cells = _cells(row)
        if "Team" not in cells or "PFM Score" not in cells:
            continue
        name = cells["Team"][0] or cells["Team"][1]
        entry = {"name": name, "code": team_code(name),
                 "rank": _float(cells.get("Rank", ("", ""))[0]),
                 "record": cells.get("Record", ("", ""))[1],
                 "score": _float(cells["PFM Score"][0])}
        for key, (heading, _) in GRADES.items():
            entry[key] = _float(cells.get(heading, ("", ""))[0])
        slug = re.search(r'href="[^"]*/nfl-team-dashboards/([a-z0-9-]+)/"', row)
        entry["slug"] = slug.group(1) if slug else ""
        key = entry["code"] or name                 # a name the app cannot place stays visible to validate
        if key in out:
            out[key]["duplicates"] = out[key].get("duplicates", 0) + 1
        else:
            out[key] = entry
    return out


def parse_explosiveness(page: str) -> dict[str, float | None]:
    """The explosiveness table: team code -> grade."""
    out: dict[str, float | None] = {}
    for row in _ROW.findall(page or ""):
        cells = _cells(row)
        if "Team" in cells and "Explosiveness" in cells:
            code = team_code(cells["Team"][0] or cells["Team"][1])
            if code:
                out[code] = _float(cells["Explosiveness"][0])
    return out


_POINT = re.compile(r'<g class="pfm-chart-point">(.*?)</g>', re.S)
_VALUE = re.compile(r'class="pfm-chart-value"[^>]*>([^<]*)<', re.S)
_LABEL = re.compile(r'class="pfm-chart-x-label"[^>]*>([^<]*)<', re.S)


def parse_history(page: str) -> list[tuple[str, float]]:
    """A team page's score history: [("BASELINE", 87.8), ("W1", 88.5), ...].
    Only the chart that says it is the score history is read."""
    start = (page or "").find("PFM score history line chart")
    if start < 0:
        return []
    end = page.find("</svg>", start)
    out = []
    for point in _POINT.findall(page[start:end if end > 0 else None]):
        value, label = _VALUE.search(point), _LABEL.search(point)
        number = _float(value.group(1)) if value else None
        if label and number is not None:
            out.append((_text(label.group(1)).upper(), number))
    return out


def parse_changes(page: str) -> list[dict]:
    """The ranking-changes page's update log: one entry per team per update date."""
    found = re.search(r'<script[^>]*>\s*(\{"groups".*?)</script>', page or "", re.S)
    if not found:
        return []
    try:
        groups = json.loads(found.group(1)).get("groups", [])
    except ValueError:
        return []
    out = []
    for group in groups if isinstance(groups, list) else []:
        for event in group.get("events", []) if isinstance(group, dict) else []:
            if not isinstance(event, dict):
                continue
            out.append({"date": str(event.get("date", "")), "code": team_code(str(event.get("name", ""))),
                        "abbr": str(event.get("abbr", "")),
                        "previous_score": _float(event.get("previous_score")),
                        "current_score": _float(event.get("current_score")),
                        "previous_rank": _float(event.get("previous_rank")),
                        "current_rank": _float(event.get("current_rank")),
                        "change_type": str(event.get("change_type", "")),
                        "components": [str(c) for c in event.get("components", []) if isinstance(c, str)]})
    return out


_WEIGHT = re.compile(r"(\d{1,2})%\s*(QB Stability|Roster Strength|Coaching Direction|Recent Performance|"
                     r"Offense Strength|Defense Strength|Franchise Direction)")
_HISTORY = re.compile(r"((?:January|February|March|April|May|June|July|August|September|October|November|"
                      r"December) \d{1,2}, \d{4}):")


def parse_methodology(page: str) -> dict:
    """The weights the methodology page states and its newest history date (the version)."""
    text = _text(page or "")
    weights = {name: int(share) / 100 for share, name in _WEIGHT.findall(text)}
    dates = []
    for found in _HISTORY.findall(text):
        try:
            dates.append(datetime.strptime(found, "%B %d, %Y").date().isoformat())
        except ValueError:
            continue
    return {"version": max(dates) if dates else None, "weights": weights}


# ---- the published formula, worked out again (derived, not source values) -----------------------
def public_score(grades: dict) -> float | None:
    """The public PFM score from the seven grades, as the methodology page gives
    the formula. None when any grade is missing."""
    raw = 0.0
    for key, (_, weight) in GRADES.items():
        value = grades.get(key)
        if value is None:
            return None
        raw += weight * float(value)
    adjusted = raw + 0.5 * max(raw - 80.0, 0.0)
    return max(60.0, min(95.0, 79.0 + (adjusted - 79.0) * 1.08))


# ---- checking a snapshot --------------------------------------------------------------------------
def _issue(level: str, code: str, detail: str) -> dict:
    return {"level": level, "code": code, "detail": detail}


def validate(snapshot: dict) -> list[dict]:
    """What is wrong with a snapshot, worst first. 'error' means it must not be
    used for anything; 'warning' means some values are missing or doubtful."""
    issues: list[dict] = []
    teams = snapshot.get("teams") or {}
    known = set(KNOWN_CODES)
    if not snapshot.get("effective_date"):
        issues.append(_issue("error", "no date", "the ratings page states no update date"))
    if len(teams) != 32:
        issues.append(_issue("error", "teams", f"{len(teams)} teams on the ratings table, not 32"))
    unknown = sorted(c for c in teams if c not in known)
    if unknown:
        issues.append(_issue("error", "names", f"names the dashboard cannot place: {', '.join(unknown)}"))
    for code, entry in sorted(teams.items()):
        if entry.get("duplicates"):
            issues.append(_issue("error", "duplicate", f"{code} is on the ratings table more than once"))
        for key in FIELDS:
            value = entry.get(key)
            if value is None:
                issues.append(_issue("warning", "missing", f"{code}: no {key}"))
            elif not 0.0 <= float(value) <= 100.0 or (key == "score" and not 60.0 <= float(value) <= 95.0):
                issues.append(_issue("error", "range", f"{code}: {key} {value} is outside the scale"))
        gap = (snapshot.get("derived", {}).get("formula_gap") or {}).get(code)
        if gap is not None and abs(gap) > FORMULA_SLACK:
            issues.append(_issue("warning", "contradiction",
                                 f"{code}: the published score is {gap:+.2f} from the score its own grades give"))
        history = entry.get("history")
        if history is None:
            issues.append(_issue("warning", "no history", f"{code}: the team page was not read"))
        elif history and abs(history[-1][1] - float(entry.get("score") or 0)) > 0.051:
            issues.append(_issue("warning", "contradiction",
                                 f"{code}: the team page's newest score {history[-1][1]} is not the table's "
                                 f"{entry.get('score')}"))
    # the newest update's "before" score should be the team page's score one week earlier
    for event in snapshot.get("changes") or []:
        code = event.get("code")
        entry = teams.get(code)
        if entry is None:
            issues.append(_issue("warning", "names", f"the changes page names {event.get('abbr')}, not on the table"))
            continue
        if event.get("abbr") and ABBR.get(event["abbr"].lower(), event["abbr"].lower()) != code:
            issues.append(_issue("error", "names", f"the changes page's {event['abbr']} is not {code}"))
        history = entry.get("history") or []
        if (event.get("date") == snapshot.get("effective_date") and len(history) >= 2
                and event.get("previous_score") is not None
                and abs(history[-2][1] - event["previous_score"]) > 0.051):
            issues.append(_issue("warning", "contradiction",
                                 f"{code}: the changes page's earlier score {event['previous_score']} is not the "
                                 f"team page's {history[-2][0]} {history[-2][1]}"))
    weights = (snapshot.get("methodology") or {}).get("weights") or {}
    if weights and any(abs(weights.get(METHOD_NAMES[k], -1) - w) > 1e-9 for k, (_, w) in GRADES.items()):
        issues.append(_issue("warning", "method", "the methodology page's weights are not the ones coded here"))
    return sorted(issues, key=lambda i: (i["level"] != "error", i["code"], i["detail"]))


#: The grades as the methodology page names them.
METHOD_NAMES = {"qb_stability": "QB Stability", "roster_strength": "Roster Strength",
                "coaching_direction": "Coaching Direction", "recent_performance": "Recent Performance",
                "offense_strength": "Offense Strength", "defense_strength": "Defense Strength",
                "franchise_direction": "Franchise Direction"}


def status_of(issues: list[dict], wanted_pages: int, got_pages: int) -> str:
    if any(i["level"] == "error" for i in issues):
        return "failed"
    if got_pages < wanted_pages or any(i["code"] in ("missing", "no history") for i in issues):
        return "partial"
    return "ok"


#: The dashboard's 32 team codes (predictions.team_code); a PFM name must land on one of them.
KNOWN_CODES = ("ari", "atl", "bal", "buf", "car", "chi", "cin", "cle", "dal", "den", "det", "gb", "hou", "ind",
               "jax", "kc", "lac", "lar", "lv", "mia", "min", "ne", "no", "nyg", "nyj", "phi", "pit", "sea", "sf",
               "tb", "ten", "was")


# ---- fetching ---------------------------------------------------------------------------------------
def _get(url: str, opener=None, sleep=time.sleep) -> tuple[str, dict]:
    """One page and its provenance. Raises PfmError after TRIES attempts."""
    request = urllib.request.Request(url, headers={"User-Agent": "ACQL-Dashboard (personal, weekly)",
                                                   "Accept": "text/html"})
    open_url = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    wait, last = BACKOFF, None
    for attempt in range(TRIES):
        try:
            with open_url(request) as reply:
                body = reply.read()
                status = getattr(reply, "status", 200)
            if status != 200:
                raise PfmError(f"{url} answered {status}")
            text = body.decode("utf-8", "replace")
            return text, {"url": url, "status": status, "bytes": len(body), "fetched_at": time.time(),
                          "sha256": hashlib.sha256(body).hexdigest()}
        except (urllib.error.URLError, OSError, PfmError) as exc:
            last = exc
            if attempt + 1 < TRIES:
                sleep(wait)
                wait *= 2
    raise PfmError(f"Couldn't read {url} ({getattr(last, 'reason', last)}).")


def collect(*, opener=None, sleep=time.sleep, now: float | None = None, team_pages: bool | None = None,
            previous: dict | None = None) -> dict:
    """Read the pages and build a snapshot (not yet saved). Pages that fail are
    named in the snapshot's quality; the ratings table failing raises
    PfmError, because without it there is nothing to keep.

    The 32 team pages (the score history) are read when `team_pages` is True,
    or - by default - when there is no `previous` snapshot or the update date
    has moved on since it; otherwise the history is carried over from
    `previous`, whose update date is the same."""
    now = time.time() if now is None else now
    pages: list[dict] = []
    failed: list[str] = []

    def page(url: str) -> str | None:
        if pages or failed:
            sleep(PAUSE)
        try:
            text, about = _get(url, opener=opener, sleep=sleep)
        except PfmError as exc:
            failed.append(url)
            log.warning("PFM: %s", exc)
            return None
        pages.append(about)
        return text

    table = page(RANKINGS_URL)
    if table is None:
        raise PfmError("The PFM ratings table could not be read; the last snapshot stands.")
    teams = parse_rankings(table)
    stated = effective_date(table)
    if team_pages is None:
        team_pages = previous is None or previous.get("effective_date") != stated
    wanted = 4 + (32 if team_pages else 0)
    explosive = page(EXPLOSIVE_URL)
    if explosive is not None:
        found = parse_explosiveness(explosive)
        for code, entry in teams.items():
            entry["explosiveness"] = found.get(code)
    changes_page = page(CHANGES_URL)
    changes = parse_changes(changes_page) if changes_page is not None else []
    method_page = page(METHOD_URL)
    methodology = parse_methodology(method_page) if method_page is not None else {}
    if team_pages:
        for code, entry in sorted(teams.items()):
            text = page(TEAM_URL.format(slug=entry.get("slug") or "")) if entry.get("slug") else None
            entry["history"] = parse_history(text) if text is not None else None
    else:
        same = previous is not None and previous.get("effective_date") == stated
        for code, entry in teams.items():
            entry["history"] = ((previous or {}).get("teams", {}).get(code, {}).get("history") if same else None)
    snapshot = build(teams, stated, changes, methodology, pages, now)
    if not team_pages and previous is not None:
        # provenance of the carried history: kept outside the values, so it does not make a new snapshot
        snapshot["history_from"] = previous.get("file") or previous.get("collected")
    snapshot["quality"]["failed_pages"] = failed
    snapshot["quality"]["status"] = status_of(snapshot["quality"]["issues"], wanted, len(pages))
    return snapshot


def build(teams: dict, stated: str | None, changes: list[dict], methodology: dict, pages: list[dict],
          now: float) -> dict:
    """A snapshot from what was read. Separate from collect so tests can build one from fixtures."""
    for entry in teams.values():
        for key in FIELDS:
            entry.setdefault(key, None)
        entry.setdefault("history", None)
    gaps = {}
    for code, entry in teams.items():
        worked = public_score(entry)
        if worked is not None and entry.get("score") is not None:
            gaps[code] = round(float(entry["score"]) - worked, 3)
    snapshot = {
        "schema": SCHEMA, "source": SOURCE, "source_url": RANKINGS_URL,
        "collected_at": float(now), "collected": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "effective_date": stated, "methodology": methodology or {},
        "pages": pages, "teams": teams, "changes": changes,
        "derived": {"formula_gap": gaps,
                    "about": "worked out by the app, not published by PFM: the published score less the "
                             "score the published formula gives from the published grades"},
        "quality": {"status": "", "issues": []},
    }
    snapshot["content_key"] = content_key(snapshot)
    snapshot["quality"]["issues"] = validate(snapshot)
    return snapshot


def content_key(snapshot: dict) -> str:
    """What makes two snapshots the same: the source values and the stated date, not when they were read."""
    kept = {"effective_date": snapshot.get("effective_date"), "teams": snapshot.get("teams"),
            "changes": snapshot.get("changes"), "methodology": snapshot.get("methodology")}
    return hashlib.sha256(json.dumps(kept, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# ---- keeping ------------------------------------------------------------------------------------
def _log_import(entry: dict, where: Path | None = None) -> None:
    where = where or folder()
    with (where / "imports.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(entry, sort_keys=True) + "\n")


def save(snapshot: dict, where: Path | None = None) -> tuple[Path | None, str]:
    """Keep a snapshot. Returns (file, what happened): 'saved', 'unchanged' (the
    newest snapshot already has these numbers - nothing written) or 'refused'
    (it failed its checks - nothing written, the last good one stands)."""
    where = where or folder()
    (where / "snapshots").mkdir(parents=True, exist_ok=True)
    status = snapshot.get("quality", {}).get("status", "")
    entry = {"at": snapshot.get("collected_at"), "status": status, "effective_date": snapshot.get("effective_date"),
             "content_key": snapshot.get("content_key"), "pages": len(snapshot.get("pages") or []),
             "failed_pages": snapshot.get("quality", {}).get("failed_pages", []),
             "issues": len(snapshot.get("quality", {}).get("issues", []))}
    if status == "failed":
        # kept apart for a look, never read as a snapshot
        (where / "refused").mkdir(exist_ok=True)
        stamp = datetime.fromtimestamp(float(snapshot["collected_at"]), timezone.utc).strftime("%Y%m%d-%H%M%S")
        (where / "refused" / f"{stamp}.json").write_text(json.dumps(snapshot, indent=1, sort_keys=True),
                                                         encoding="utf-8")
        entry["what"] = "refused"
        _log_import(entry, where)
        return None, "refused"
    newest = latest(where)
    if newest is not None and newest.get("content_key") == snapshot.get("content_key"):
        entry["what"] = "unchanged"
        _log_import(entry, where)
        return None, "unchanged"
    stamp = datetime.fromtimestamp(float(snapshot["collected_at"]), timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = where / "snapshots" / f"{stamp}-{snapshot['content_key'][:8]}.json"
    if path.exists():                       # never overwrite what was kept
        entry["what"] = "unchanged"
        _log_import(entry, where)
        return path, "unchanged"
    temp = path.with_suffix(".part")
    temp.write_text(json.dumps(snapshot, indent=1, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    entry["what"], entry["file"] = "saved", path.name
    _log_import(entry, where)
    return path, "saved"


def snapshots(where: Path | None = None) -> list[dict]:
    """Every kept snapshot, oldest first. A damaged file is skipped."""
    where = where or folder()
    out = []
    for path in sorted((where / "snapshots").glob("*.json")):
        try:
            found = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("PFM: %s could not be read - skipped", path.name)
            continue
        if isinstance(found, dict) and found.get("schema") == SCHEMA:
            found["file"] = path.name
            out.append(found)
    return sorted(out, key=lambda s: float(s.get("collected_at") or 0))


def latest(where: Path | None = None) -> dict | None:
    kept = snapshots(where)
    return kept[-1] if kept else None


def imports(where: Path | None = None) -> list[dict]:
    """The import log, oldest first."""
    try:
        lines = ((where or folder()) / "imports.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _day(text: str | None) -> date | None:
    try:
        return date.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def as_of(when: float, kept: list[dict] | None = None) -> dict | None:
    """The newest snapshot that was actually on this computer at `when` - read
    no later than that, and stating an update no later than that day. None
    when there was none. This is the only way a prediction may see PFM."""
    moment = datetime.fromtimestamp(float(when), timezone.utc).date()
    usable = [s for s in (kept if kept is not None else snapshots())
              if float(s.get("collected_at") or 0) <= float(when)
              and (_day(s.get("effective_date")) or date.max) <= moment
              and s.get("quality", {}).get("status") in ("ok", "partial")]
    return usable[-1] if usable else None


def freshness(snapshot: dict | None, now: float | None = None) -> dict:
    """How old a snapshot is, in words and days: never shown as current when it is not."""
    now = time.time() if now is None else now
    if snapshot is None:
        return {"state": "none", "days": None, "words": "No PFM snapshot has been taken."}
    stated = _day(snapshot.get("effective_date"))
    today = datetime.fromtimestamp(now, timezone.utc).date()
    days = (today - stated).days if stated else None
    read = (now - float(snapshot.get("collected_at") or 0)) / 86400
    state = "stale" if days is None or days > STALE_DAYS else snapshot.get("quality", {}).get("status") or "ok"
    words = (f"PFM update of {stated.isoformat() if stated else 'no stated date'}, read {read:.1f} days ago"
             + (f" - stale ({days} days since the update)" if state == "stale" and days is not None else "")
             + (" - some values missing" if state == "partial" else ""))
    return {"state": state, "days": days, "read_days": read, "words": words}


def revisions(kept: list[dict] | None = None) -> list[dict]:
    """Past weekly scores that changed from one snapshot to the next - PFM
    rewriting its own history. Empty until there are two snapshots."""
    kept = kept if kept is not None else snapshots()
    out = []
    for before, after in zip(kept, kept[1:]):
        for code, entry in (after.get("teams") or {}).items():
            old = dict((before.get("teams", {}).get(code, {}).get("history") or []))
            for label, value in entry.get("history") or []:
                if label in old and abs(old[label] - value) > 0.051:
                    out.append({"code": code, "label": label, "was": old[label], "now": value,
                                "seen": after.get("collected")})
    return out


def refresh(*, opener=None, sleep=time.sleep, now: float | None = None, team_pages: bool | None = None) -> dict:
    """Collect and keep a snapshot. The 32 team pages are read when asked, or
    by default when the update date has moved on (that is the only time
    their history can have grown). Returns what happened, for the log."""
    newest = latest()
    try:
        snapshot = collect(opener=opener, sleep=sleep, now=now, team_pages=team_pages, previous=newest)
    except PfmError as exc:
        _log_import({"at": time.time() if now is None else now, "status": "failed", "what": "refused",
                     "detail": str(exc)})
        return {"what": "failed", "detail": str(exc), "freshness": freshness(newest, now)}
    path, what = save(snapshot)
    issues = snapshot["quality"]["issues"]
    return {"what": what, "status": snapshot["quality"]["status"], "file": path.name if path else None,
            "effective_date": snapshot.get("effective_date"), "teams": len(snapshot.get("teams") or {}),
            "pages": len(snapshot.get("pages") or []), "issues": issues,
            "freshness": freshness(latest(), now)}
