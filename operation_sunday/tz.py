"""Time zones without assuming a fixed UTC offset.

zoneinfo is used when the system (or the tzdata package) has the tables.
Windows usually has neither, so the four mainland US zones fall back to the
US daylight-saving rule (second Sunday of March 2:00 to first Sunday of
November 2:00, local time) - the same rule acql/feeds/oddslock.py works out by
hand. Any other zone without tables is an error, never a silent guess.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo

_US_STANDARD = {
    "America/New_York": -5,
    "US/Eastern": -5,
    "America/Chicago": -6,
    "US/Central": -6,
    "America/Denver": -7,
    "US/Mountain": -7,
    "America/Los_Angeles": -8,
    "US/Pacific": -8,
}


def _nth_sunday(year: int, month: int, n: int) -> date:
    day = date(year, month, 1)
    while day.weekday() != 6:
        day += timedelta(days=1)
    return day + timedelta(weeks=n - 1)


class USRuleZone(tzinfo):
    """A mainland US zone by rule (post-2007 DST rule)."""

    def __init__(self, name: str, standard_hours: int):
        self.name = name
        self.std = timedelta(hours=standard_hours)

    def _dst_on(self, dt: datetime) -> bool:
        naive = dt.replace(tzinfo=None)
        start = datetime.combine(_nth_sunday(naive.year, 3, 2), datetime.min.time()) + timedelta(hours=2)
        end = datetime.combine(_nth_sunday(naive.year, 11, 1), datetime.min.time()) + timedelta(hours=1)
        return start <= naive < end

    def utcoffset(self, dt):  # noqa: D401
        if dt is None:
            return self.std
        return self.std + self.dst(dt)

    def dst(self, dt):
        if dt is None:
            return timedelta(0)
        return timedelta(hours=1) if self._dst_on(dt) else timedelta(0)

    def tzname(self, dt):
        return self.name

    def fromutc(self, dt):
        # standard -> local, then check DST at that local standard time
        local_std = (dt.replace(tzinfo=None) + self.std)
        summer = self._dst_on(local_std)
        return (local_std + (timedelta(hours=1) if summer else timedelta(0))).replace(tzinfo=self)


def get_zone(name: str) -> tzinfo:
    """The zone called `name`: zoneinfo's, or the US rule fallback."""
    if name in ("UTC", "Etc/UTC"):
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - no tables on this machine
        if name in _US_STANDARD:
            return USRuleZone(name, _US_STANDARD[name])
        raise ValueError(
            f"No time-zone tables for {name!r} on this computer. Install the 'tzdata' "
            "package or configure one of: " + ", ".join(sorted(_US_STANDARD)))


def to_utc(local_naive: datetime, zone: str) -> datetime:
    """A wall-clock time in `zone` as an aware UTC datetime."""
    if local_naive.tzinfo is not None:
        return local_naive.astimezone(timezone.utc)
    return local_naive.replace(tzinfo=get_zone(zone)).astimezone(timezone.utc)


def parse_utc(value) -> datetime:
    """Parse an ISO timestamp that MUST carry a zone; return it in UTC."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without a time zone: {value!r}")
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return parse_utc(dt).isoformat(timespec="seconds")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
