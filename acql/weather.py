"""Game-day weather, for the games played outdoors.

Wind and rain pull scoring down and tilt a game toward the run; the betting
total has it priced in within minutes of the forecast changing. So this is
not a signal to pick by - it is the reason a total is low, or a favourite's
blowout a little less likely, shown next to the pick.

Where a game is played, and whether there is a roof over it, comes with
ESPN's scoreboard (results.Score.city / indoor), so a game in London or
Munich is forecast for London or Munich. The forecast itself is Open-Meteo's
(open-meteo.com): free, no key, hourly. A city is looked up once and kept.

Kept in the app's database; nothing here knows about Qt.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 20
KIND = "weather"
#: How often a week's forecasts are fetched again.
EVERY = 6 * 3600
#: Forecasts only reach this far ahead.
AHEAD = 14 * 86400
#: What counts as weather worth a line under a pick.
WINDY = 15.0            # mph, sustained
GUSTY = 28.0            # mph
WET = 50                # % chance of rain or snow
COLD, HOT = 25.0, 92.0  # Fahrenheit


class WeatherError(Exception):
    """A forecast that couldn't be fetched, in words fit to log."""


@dataclass(frozen=True)
class Forecast:
    temperature: float      # Fahrenheit
    wind: float             # mph
    gust: float             # mph
    wet: int                # % chance of precipitation
    city: str = ""

    @property
    def notable(self) -> bool:
        return (self.wind >= WINDY or self.gust >= GUSTY or self.wet >= WET
                or self.temperature <= COLD or self.temperature >= HOT)

    def words(self) -> str:
        """"18 mph wind, gusts to 31, 60% chance of rain, 41°F"."""
        parts = []
        if self.wind >= WINDY or self.gust >= GUSTY:
            parts.append(f"{self.wind:.0f} mph wind" + (f", gusts to {self.gust:.0f}" if self.gust >= GUSTY else ""))
        if self.wet >= WET:
            parts.append(f"{self.wet}% chance of {'snow' if self.temperature <= 33 else 'rain'}")
        parts.append(f"{self.temperature:.0f}°F")
        return ", ".join(parts)


def _get(url: str, params: dict, opener=None) -> dict:
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": "ACQL-Dashboard", "Accept": "application/json"})
    open_url = opener or (lambda r: urllib.request.urlopen(r, timeout=TIMEOUT))
    try:
        with open_url(request) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise WeatherError(f"couldn't reach the forecast ({getattr(exc, 'reason', exc)})") from exc


def _kept() -> dict:
    try:
        from . import store
        return dict(store.items(KIND))
    except Exception:  # noqa: BLE001
        return {}


def locate(city: str, opener=None) -> tuple[float, float] | None:
    """(latitude, longitude) for "Orchard Park, NY" - looked up once and kept."""
    from . import store
    city = " ".join(str(city or "").split())
    if not city:
        return None
    places = _kept().get("places") or {}
    if city in places:
        found = places[city]
        return (float(found[0]), float(found[1])) if found else None
    name = city.split(",")[0].strip()
    data = _get(GEOCODE, {"name": name, "count": 5, "language": "en", "format": "json"}, opener)
    hits = data.get("results") or []
    region = city.split(",")[1].strip().casefold() if "," in city else ""
    best = next((h for h in hits if region and region in (
        str(h.get("admin1", "")).casefold(), str(h.get("admin1_code", "")).casefold(),
        str(h.get("country", "")).casefold(), str(h.get("country_code", "")).casefold())), None)
    best = best or (hits[0] if hits else None)
    places = dict(places)
    places[city] = [best["latitude"], best["longitude"]] if best else None
    try:
        store.put(KIND, "places", places)
    except store.StoreError:
        pass
    return (float(best["latitude"]), float(best["longitude"])) if best else None


def _at(where: tuple[float, float], kickoff: float, city: str, opener=None) -> Forecast | None:
    day = time.strftime("%Y-%m-%d", time.gmtime(kickoff))
    end = time.strftime("%Y-%m-%d", time.gmtime(kickoff + 4 * 3600))
    data = _get(FORECAST, {
        "latitude": f"{where[0]:.4f}", "longitude": f"{where[1]:.4f}",
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "GMT",
        "start_date": day, "end_date": end,
    }, opener)
    hourly = data.get("hourly") or {}
    hours = hourly.get("time") or []
    first = time.strftime("%Y-%m-%dT%H:00", time.gmtime(kickoff))
    if first not in hours:
        return None
    span = range(hours.index(first), min(len(hours), hours.index(first) + 4))     # the game, about

    def over(name, pick):
        values = [hourly.get(name, [None] * len(hours))[i] for i in span]
        values = [v for v in values if isinstance(v, (int, float))]
        return pick(values) if values else 0.0

    return Forecast(
        temperature=over("temperature_2m", lambda v: sum(v) / len(v)),
        wind=over("wind_speed_10m", max), gust=over("wind_gusts_10m", max),
        wet=int(over("precipitation_probability", max)), city=city,
    )


def due(year: int, week: int, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return now - float((_kept().get(f"{year}-{week}") or {}).get("at") or 0) >= EVERY


def refresh(year: int, week: int, *, opener=None, now: float | None = None) -> int:
    """Fetch the forecast for every outdoor game of a week still to kick off.
    Returns how many were forecast."""
    from . import results, store
    now = time.time() if now is None else now
    games, problems = {}, 0
    for s in results.load(year, week):
        if s.state != "pre" or not s.kickoff or not (now < s.kickoff < now + AHEAD):
            continue
        key = f"{s.away}@{s.home}"
        if getattr(s, "indoor", None):
            games[key] = {"indoor": True, "city": getattr(s, "city", "")}
            continue
        city = getattr(s, "city", "")
        try:
            where = locate(city, opener)
            found = _at(where, s.kickoff, city, opener) if where else None
        except WeatherError:
            problems += 1
            continue
        if found is not None:
            games[key] = {"temperature": found.temperature, "wind": found.wind, "gust": found.gust,
                          "wet": found.wet, "city": city}
    if not games and problems:
        raise WeatherError("the forecast couldn't be reached")
    try:
        store.put(KIND, f"{year}-{week}", {"at": now, "games": games})
    except store.StoreError:
        pass
    return sum(1 for g in games.values() if not g.get("indoor"))


def game(year: int, week: int, away: str, home: str) -> Forecast | None:
    """The forecast kept for a game (either way round), or None - indoors, or not fetched."""
    from .predictions import team_code
    a, h = team_code(away), team_code(home)
    kept = (_kept().get(f"{year}-{week}") or {}).get("games") or {}
    row = kept.get(f"{a}@{h}") or kept.get(f"{h}@{a}")
    if not isinstance(row, dict) or row.get("indoor") or "wind" not in row:
        return None
    return Forecast(float(row.get("temperature", 0)), float(row.get("wind", 0)), float(row.get("gust", 0)),
                    int(row.get("wet", 0)), str(row.get("city", "")))


def indoors(year: int, week: int, away: str, home: str) -> bool:
    from .predictions import team_code
    a, h = team_code(away), team_code(home)
    kept = (_kept().get(f"{year}-{week}") or {}).get("games") or {}
    row = kept.get(f"{a}@{h}") or kept.get(f"{h}@{a}")
    return bool(isinstance(row, dict) and row.get("indoor"))
