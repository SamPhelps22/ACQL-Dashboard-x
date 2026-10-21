"""Since you were last here: what the scheduled runs did while the window was closed.

Most of the work happens with nobody watching - the 3 am run, the game-day
polls, the emails - and what each did is only in data/acql-log.txt. On
opening, this reads the log back to the last time the window was open and
says, in a few lines, what is worth knowing: results read, the website
updated, picks that changed side, alerts sent, anything that failed, and
days with no run at all.

No Qt here; the window shows the lines (app.py).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$")
MOST = 6


@dataclass(frozen=True)
class Item:
    rank: int        # 0 first: problems, then changes, then routine
    text: str


def _entries(log: Path, since: float) -> list[tuple[float, str]]:
    out = []
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines[-4000:]:
        found = _LINE.match(line)
        if not found:
            continue
        try:
            at = time.mktime(time.strptime(found.group(1), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            continue
        if at > since:
            out.append((at, found.group(2)))
    return out


def gather(since: float, now: float | None = None, log: Path | None = None) -> list[Item]:
    """What happened between `since` and now, most important first, at most MOST lines."""
    from .config import DATA_DIR
    now = time.time() if now is None else now
    if since <= 0 or now - since < 3600:
        return []
    entries = [(at, text[len("headless: "):]) for at, text in _entries(log or Path(DATA_DIR) / "acql-log.txt", since)
               if text.startswith("headless: ")]
    items: list[Item] = []
    problems = [t for _, t in entries if re.search(r"failed|not sent|can't be reached|couldn't|error", t, re.I)
                and not t.startswith("note:")]
    if problems:
        items.append(Item(0, f"{len(problems)} problem{'' if len(problems) == 1 else 's'} in the scheduled runs - "
                             f"latest: {problems[-1][:140]}"))
    for prefix in ("card check:", "sources disagree, ", "pick changed side:", "deadline guardian:"):
        hits = [t for _, t in entries if t.startswith(prefix)]
        if hits:
            items.append(Item(1, hits[-1] if len(hits) == 1 else f"{hits[-1]} (and {len(hits) - 1} more)"))
    reads = [re.findall(r"\d+", group) for _, t in entries
             for group in re.findall(r"ESPN results for week\(s\) \[([\d, ]+)\]", t)]
    if reads:
        weeks = sorted({int(n) for n in reads[-1]})          # the latest run's weeks
        items.append(Item(2, f"Results read for week{'s' if len(weeks) > 1 else ''} {', '.join(map(str, weeks))}"))
    published = [at for at, t in entries if t.startswith("website updated")]
    if published:
        items.append(Item(2, f"The website was updated {len(published)} time{'' if len(published) == 1 else 's'}, "
                             f"last {time.strftime('%a %I:%M %p', time.localtime(published[-1])).replace(' 0', ' ')}"))
    emailed = [t for _, t in entries if t.startswith(("card email sent", "sunday brief sent", "alert emailed"))]
    if emailed:
        items.append(Item(2, f"{len(emailed)} email{'' if len(emailed) == 1 else 's'} sent"))
    quiet = _quiet_days(since, now, [at for at, _ in entries])
    if quiet:
        items.append(Item(0, f"No scheduled run on {', '.join(quiet)} - the computer may have been off"))
    return sorted(items, key=lambda i: i.rank)[:MOST]


def _quiet_days(since: float, now: float, times: list[float]) -> list[str]:
    """Whole days between `since` and `now` with no run at all."""
    ran = {time.strftime("%Y-%m-%d", time.localtime(t)) for t in times}
    out = []
    day = time.mktime(time.strptime(time.strftime("%Y-%m-%d", time.localtime(since)), "%Y-%m-%d")) + 86400
    while day + 86400 <= now:
        key = time.strftime("%Y-%m-%d", time.localtime(day))
        if key not in ran:
            out.append(time.strftime("%a %b %d", time.localtime(day)).replace(" 0", " "))
        day += 86400 + 3600        # step past a clock change, then
        day = time.mktime(time.strptime(time.strftime("%Y-%m-%d", time.localtime(day)), "%Y-%m-%d"))
    return out[-4:]
