#!/usr/bin/env python3
"""Is the pool website keeping up? A check that runs away from the PC.

The website is published from Sam's computer - by the dashboard while it is
open and by the scheduled runs. When that computer is off, nothing on it can
say so: on Monday 2026-10-19 there was no run at all. This runs on GitHub's
machines on a schedule (.github/workflows/heartbeat.yml), reads the published
page's own build time and ESPN's scoreboard, and says the site is behind
when NFL games finished well before now but after the page was last built.

    python packaging/heartbeat.py              print the verdict; exit 1 when behind
    python packaging/heartbeat.py --json       the same, as JSON (for the workflow)

Standard library only. It reads two public pages and sends nothing; the
workflow turns "behind" into a GitHub issue, which GitHub emails to the
repository's owner, and closes it once the site catches up.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

SITE = "https://samphelps22.github.io/ACQL---Pool/"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
#: The page's build time is written on the publishing computer's clock (US Central).
SITE_ZONE = "America/Chicago"
#: A game is over about this long after kickoff...
GAME_LENGTH = timedelta(hours=3, minutes=30)
#: ...and the site has this long after that to show it before it is called behind.
GRACE = timedelta(hours=8)


def _get(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ACQL-heartbeat"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return reply.read()


def built_at(page: str) -> datetime | None:
    """The page's "generated" time, as UTC."""
    found = re.search(r'"generated"\s*:\s*"(\d{4}-\d\d-\d\d \d\d:\d\d)"', page)
    if not found:
        return None
    local = datetime.strptime(found.group(1), "%Y-%m-%d %H:%M")
    try:
        from zoneinfo import ZoneInfo
        return local.replace(tzinfo=ZoneInfo(SITE_ZONE)).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001 - no zone data: assume Central daylight time
        return (local + timedelta(hours=5)).replace(tzinfo=timezone.utc)


def finished_games(board: dict) -> list[tuple[datetime, str]]:
    """(kickoff, "AWAY @ HOME") for every final game on the scoreboard."""
    out = []
    for event in board.get("events", []):
        status = ((event.get("status") or {}).get("type") or {})
        if not status.get("completed"):
            continue
        try:
            kickoff = datetime.strptime(event["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        out.append((kickoff, str(event.get("shortName") or event.get("name") or "")))
    return out


def verdict(page: str, board: dict, now: datetime) -> dict:
    built = built_at(page)
    games = finished_games(board)
    if built is None:
        return {"behind": False, "why": "the page carries no build time - nothing to judge", "built": None}
    due = [(k, name) for k, name in games if k + GAME_LENGTH > built and k + GAME_LENGTH + GRACE < now]
    if not due:
        return {"behind": False, "why": "the site has every finished game it should have", "built": built.isoformat()}
    last = max(due)
    return {"behind": True, "built": built.isoformat(),
            "why": (f"The pool website was last built {built:%a %b %d %H:%M} UTC, but {len(due)} game(s) "
                    f"finished after that and more than {GRACE.seconds // 3600} hours ago (latest: {last[1]}, "
                    f"kicked off {last[0]:%a %b %d %H:%M} UTC). The computer that publishes the site may be "
                    "off or asleep, or its scheduled jobs may have stopped.")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        page = _get(SITE).decode("utf-8", "replace")
        board = json.loads(_get(SCOREBOARD))
    except Exception as exc:  # noqa: BLE001 - can't look: say so, don't cry wolf
        found = {"behind": False, "why": f"couldn't look ({exc})", "built": None}
    else:
        found = verdict(page, board, datetime.now(timezone.utc))
    print(json.dumps(found) if args.json else found["why"])
    return 1 if found["behind"] else 0


if __name__ == "__main__":
    sys.exit(main())
