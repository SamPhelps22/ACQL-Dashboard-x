"""Phone alerts for the pool, through ntfy.sh - no server of our own.

Coaches install the free ntfy app and subscribe to the pool's topic; the
scheduled runs (headless.py) post to it:

    * "Picks close in 2 hours" - once a week, when the deadline is near
    * "Week N results are in" - once a week, when the website goes up with it

Each alert is sent once: what went out is kept in the store, so a poll every
ten minutes never repeats one. With no topic set nothing is sent.

    python -m acql.site.pushalerts --topic acql-pool-xyz   set the topic
    python -m acql.site.pushalerts --test                  send a test alert
    python -m acql.site.pushalerts --off                   stop the alerts

A topic is public to anyone who knows its name, so pick one hard to guess.
"""

from __future__ import annotations

import argparse
import re
import time
import urllib.request

SERVER = "https://ntfy.sh"
KIND = "alerts"
#: The deadline reminder goes out this long before the picks close.
REMIND_BEFORE = 2 * 3600
TIMEOUT = 15
TOPIC_RULE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def topic() -> str:
    from .. import store
    try:
        found = str(store.get(KIND, "topic", "") or "")
    except Exception:  # noqa: BLE001 - no store: no alerts
        return ""
    return found if TOPIC_RULE.match(found) else ""


def set_topic(name: str) -> None:
    from .. import store
    name = name.strip()
    if name and not TOPIC_RULE.match(name):
        raise ValueError("a topic is 6-64 letters, digits, - or _")
    store.put(KIND, "topic", name)


def subscribe_link(name: str | None = None) -> str:
    name = topic() if name is None else name
    return f"{SERVER}/{name}" if name else ""


def send(title: str, message: str, *, link: str = "", tags: str = "", name: str | None = None) -> bool:
    """Post one alert. False when there is no topic; raises when ntfy refuses."""
    name = topic() if name is None else name
    if not name:
        return False
    headers = {"Title": title.encode("utf-8").decode("latin-1", "replace")}
    if link:
        headers["Click"] = link
    if tags:
        headers["Tags"] = tags
    request = urllib.request.Request(f"{SERVER}/{name}", data=message.encode("utf-8"),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
        return 200 <= reply.status < 300


def _once(key: str, title: str, message: str, **kw) -> bool:
    """Send unless this key already went out."""
    from .. import store
    if not topic() or store.get(KIND, f"sent:{key}", None):
        return False
    if send(title, message, **kw):
        store.put(KIND, f"sent:{key}", time.time())
        return True
    return False


def deadline_due(deadline: float, now: float) -> bool:
    """Inside the reminder window: under two hours to go, and not yet closed."""
    return 0 < deadline - now <= REMIND_BEFORE


def remind_deadline(now: float | None = None, link: str = "") -> bool:
    """'Picks close in 2 hours', once, for the week whose picks close next."""
    from ..feeds import oddslock, results
    now = time.time() if now is None else now
    year = results.season_year()
    for week in results.calendar_weeks(year, now):
        due = oddslock.deadline(year, week)
        if deadline_due(due, now):
            left = max(1, round((due - now) / 3600))
            clock = time.strftime("%I:%M %p", time.localtime(due)).lstrip("0")
            return _once(f"deadline:{year}:{week}", f"Week {week} picks close in {left} hour{'s' * (left > 1)}",
                         f"Cards are due at {clock}. Get yours in!", link=link, tags="alarm_clock")
    return False


def results_in(week: int, url: str = "") -> bool:
    """'Week N results are in', once a week, after the website goes up with it."""
    from ..feeds import results
    return _once(f"results:{results.season_year()}:{week}", f"Week {week} results are in",
                 "See who won the week and where you stand.", link=url, tags="trophy")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acql.site.pushalerts", description=__doc__.split("\n")[0])
    parser.add_argument("--topic", help="the ntfy topic coaches subscribe to")
    parser.add_argument("--off", action="store_true", help="stop sending alerts")
    parser.add_argument("--test", action="store_true", help="send a test alert")
    args = parser.parse_args(argv)
    if args.off:
        set_topic("")
    elif args.topic:
        set_topic(args.topic)
    name = topic()
    print(f"alerts go to {subscribe_link(name)}" if name else "alerts are off (no topic)")
    if args.test and name:
        send("ACQL alerts are on", "This is a test. You'll get the picks deadline and weekly results here.",
             tags="football")
        print("test alert sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
