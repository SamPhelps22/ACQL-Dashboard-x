"""What the pool website says beyond the standings: an announcement, the
league's past champions, the archive of finished seasons behind the History
page - and the bookkeeping that lets the site update itself.

Kept apart from the GitHub details (webpublish.WebSettings): those are about
where the page goes, these are about what it says. Everything lives in the
dashboard's own store, so it survives updates and travels with a backup.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field

#: An announcement is a line or two at the top of the site, not a newsletter.
NOTE_MOST = 280
KIND = "settings"
EXTRAS_KEY = "web_extras"
PUBLISHED_KEY = "web_published"
HISTORY_KIND = "history"


def season_year(stamp: str | None = None) -> int:
    """The season a date belongs to: a season runs September to February, so
    January's games still count for the year before. `stamp` is the page's
    "2026-10-04 12:00" (now when not given)."""
    text = str(stamp or time.strftime("%Y-%m-%d"))
    m = re.match(r"(\d{4})-(\d{2})", text)
    if not m:
        return int(time.strftime("%Y"))
    year, month = int(m.group(1)), int(m.group(2))
    return year - 1 if month < 6 else year


@dataclass
class Champion:
    year: int
    names: str                      # as typed: "Line-Pony", or "Kit & Debe" for a tie
    note: str = ""


@dataclass
class Extras:
    note: str = ""
    note_posted: str = ""           # YYYY-MM-DD the announcement was written
    champions: list[Champion] = field(default_factory=list)
    auto_publish: bool = True

    @classmethod
    def load(cls) -> Extras:
        from . import store
        raw = store.get(KIND, EXTRAS_KEY, {})
        if not isinstance(raw, dict):
            return cls()
        champions = []
        for row in raw.get("champions") or []:
            try:
                year = int(row.get("year"))
            except (TypeError, ValueError, AttributeError):
                continue
            names = " ".join(str(row.get("names", "")).split())
            if names:
                champions.append(Champion(year, names, " ".join(str(row.get("note", "")).split())))
        return cls(
            note=str(raw.get("note", ""))[:NOTE_MOST],
            note_posted=str(raw.get("note_posted", "")),
            champions=sorted(champions, key=lambda c: -c.year),
            auto_publish=bool(raw.get("auto_publish", True)),
        )

    def save(self) -> None:
        from . import store
        store.put(KIND, EXTRAS_KEY, asdict(self))

    def set_note(self, text: str, today: str | None = None) -> None:
        """A new announcement gets today's date; the same words keep theirs."""
        text = " ".join(str(text or "").split())[:NOTE_MOST]
        if text != self.note:
            self.note_posted = (today or time.strftime("%Y-%m-%d")) if text else ""
        self.note = text

    def set_champions(self, rows: list[tuple[object, object, object]]) -> list[str]:
        """Replace the list from (year, names, note) rows; returns what was skipped and why."""
        kept, problems, seen = [], [], set()
        for year, names, note in rows:
            names = " ".join(str(names or "").split())
            if not str(year or "").strip() and not names:
                continue                                  # an empty row
            try:
                year = int(str(year).strip())
            except ValueError:
                problems.append(f"'{year}' isn't a year")
                continue
            if not 1950 <= year <= 2100:
                problems.append(f"{year} isn't a season")
                continue
            if not names:
                problems.append(f"{year} has no champion")
                continue
            if year in seen:
                problems.append(f"{year} is in the list twice - kept the first")
                continue
            seen.add(year)
            kept.append(Champion(year, names, " ".join(str(note or "").split())))
        self.champions = sorted(kept, key=lambda c: -c.year)
        return problems

    def page_note(self) -> dict | None:
        return {"text": self.note, "posted": self.note_posted} if self.note else None


# ---- the season archive ----------------------------------------------------------------
def season_summary(data: dict) -> dict:
    """What the History page keeps of a season, taken from the page's snapshot
    (poolpage.snapshot) so it says exactly what the site said."""
    weeks = data.get("weeks") or []
    won = Counter(n for w in weeks for n in w.get("winners") or [])
    race = data.get("race") or {}
    season_weeks = int(race.get("season_weeks") or 18)
    through = int(data.get("through_week") or 0)
    standings = []
    for p in data.get("players") or []:
        sui = p.get("suicide") or {}
        standings.append({
            "name": p.get("name", ""),
            "place": p.get("place"),
            "wins": p.get("wins", 0),
            "big_loser": p.get("big_loser", 0),
            "weeks_won": won.get(p.get("name", ""), 0),
            "net": p.get("net"),
            "suicide_out": sui.get("out"),
            "suicide_alive": bool(sui.get("alive")),
            "weekly": p.get("weekly") or {},
        })
    return {
        "year": season_year(data.get("generated")),
        "title": data.get("title", ""),
        "entrants": data.get("entrants", len(standings)),
        "through_week": through,
        "season_weeks": season_weeks,
        "complete": through >= season_weeks,
        "money": data.get("money", ""),
        "standings": standings,
        "weeks": [{"week": w.get("week"), "top": w.get("top"), "winners": list(w.get("winners") or []),
                   "average": w.get("average")} for w in weeks],
        "saved": time.strftime("%Y-%m-%d"),
    }


def archive(data: dict) -> int:
    """Keep this season's summary for the History page; returns its year."""
    from . import store
    summary = season_summary(data)
    store.put(HISTORY_KIND, str(summary["year"]), summary)
    return summary["year"]


def archived() -> dict[int, dict]:
    from . import store
    out = {}
    for key, value in (store.items(HISTORY_KIND) or {}).items():
        try:
            out[int(key)] = value
        except (TypeError, ValueError):
            continue
    return out


def page_history(current_year: int, extras: Extras | None = None) -> dict:
    """The History page's data: the champions typed in, and every archived
    season except the one being played (the page has that one live)."""
    extras = extras or Extras.load()
    seasons = [s for y, s in sorted(archived().items(), reverse=True) if y != current_year]
    return {
        "champions": [asdict(c) for c in extras.champions],
        "seasons": seasons,
    }


# ---- publishing by itself ----------------------------------------------------------
def fingerprint(data: dict, extra: object = None) -> str:
    """What the site would show, minus the time it was made: two snapshots
    with the same fingerprint make the same page."""
    stripped = {k: v for k, v in data.items() if k != "generated"}
    blob = json.dumps([stripped, extra], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def last_published() -> dict:
    from . import store
    raw = store.get(KIND, PUBLISHED_KEY, {})
    return raw if isinstance(raw, dict) else {}


def needs_publish(print_: str) -> bool:
    return last_published().get("fingerprint") != print_


def mark_published(print_: str, week: int, url: str) -> None:
    from . import store
    store.put(KIND, PUBLISHED_KEY, {"fingerprint": print_, "week": week, "url": url,
                                     "at": time.strftime("%Y-%m-%d %H:%M")})
