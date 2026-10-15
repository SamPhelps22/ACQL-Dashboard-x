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
    python -m acql.site.pushalerts --deadline "thu 6pm"    when picks are due each week
    python -m acql.site.pushalerts --remind 3              hours of warning before it

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


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CLOCK = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$")


def parse_deadline(text: str) -> tuple[int, int, int]:
    """'thu 6pm', 'Thursday 18:00', 'sun 12:30pm' -> (weekday, hour, minute), Monday 0."""
    parts = text.strip().lower().split(None, 1)
    if len(parts) != 2 or parts[0][:3] not in DAYS:
        raise ValueError('give a day and a time, like "thu 6pm" or "sunday 12:30pm"')
    found = CLOCK.match(parts[1].replace(" ", ""))
    if not found:
        raise ValueError(f"can't read the time {parts[1]!r} - try 6pm or 18:00")
    hour, minute, half = int(found.group(1)), int(found.group(2) or 0), found.group(3)
    if half:
        if not 1 <= hour <= 12:
            raise ValueError("with am/pm the hour is 1-12")
        hour = hour % 12 + (12 if half == "pm" else 0)
    if hour > 23 or minute > 59:
        raise ValueError("that isn't a time of day")
    return DAYS.index(parts[0][:3]), hour, minute


def set_deadline(text: str) -> None:
    from .. import store
    weekday, hour, minute = parse_deadline(text)
    store.put("settings", "deadline", {"weekday": weekday, "hour": hour, "minute": minute})


def describe_deadline() -> str:
    from ..feeds import oddslock
    weekday, hour, minute = oddslock.deadline_clock()
    clock = f"{hour % 12 or 12}:{minute:02d}{'pm' if hour >= 12 else 'am'}"
    return f"{DAYS[weekday].title()} {clock}"


def set_remind_hours(hours: float) -> None:
    from .. import store
    if not 0.25 <= hours <= 48:
        raise ValueError("the reminder goes 0.25 to 48 hours before")
    store.put(KIND, "remind_hours", hours)


def remind_before() -> float:
    """How long before the deadline the reminder goes out (seconds)."""
    from .. import store
    try:
        hours = float(store.get(KIND, "remind_hours", REMIND_BEFORE / 3600))
    except Exception:  # noqa: BLE001
        return REMIND_BEFORE
    return hours * 3600 if 0.25 <= hours <= 48 else REMIND_BEFORE


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


def deadline_due(deadline: float, now: float, before: float = REMIND_BEFORE) -> bool:
    """Inside the reminder window: close to the deadline, and not yet past it."""
    return 0 < deadline - now <= before


def remind_deadline(now: float | None = None, link: str = "") -> bool:
    """'Picks close in 2 hours', once, for the week whose picks close next."""
    from ..feeds import oddslock, results
    now = time.time() if now is None else now
    year = results.season_year()
    for week in results.calendar_weeks(year, now):
        due = oddslock.deadline(year, week)
        if deadline_due(due, now, remind_before()):
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
    parser.add_argument("--deadline", help='when picks are due each week, like "thu 6pm"')
    parser.add_argument("--remind", type=float, help="hours before the deadline to send the reminder")
    args = parser.parse_args(argv)
    if args.deadline:
        try:
            set_deadline(args.deadline)
        except ValueError as exc:
            print(f"deadline not changed: {exc}")
            return 1
    if args.remind is not None:
        try:
            set_remind_hours(args.remind)
        except ValueError as exc:
            print(f"reminder not changed: {exc}")
            return 1
    if args.off:
        set_topic("")
    elif args.topic:
        try:
            set_topic(args.topic)
        except ValueError as exc:
            print(f"not set: {exc} (for example acql-pool-k7q2m9x)")
            return 1
    name = topic()
    print(f"alerts go to {subscribe_link(name)}" if name else "alerts are off (no topic)")
    print(f"picks are due {describe_deadline()}; the reminder goes {remind_before() / 3600:g} hours before")
    if args.test and name:
        send("ACQL alerts are on", "This is a test. You'll get the picks deadline and weekly results here.",
             tags="football")
        print("test alert sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
