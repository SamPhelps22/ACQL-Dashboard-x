"""Where games are played: stadium coordinates and time zones.

Challenger's own table, keyed by the nflverse `stadium_id`. Coordinates are
approximate (to about a kilometre), which is far finer than any travel effect
needs. A stadium not listed here gives NaN travel, never a guess.

A team's home base in a season is the stadium where it played most of its
non-neutral home games that season - known from the schedule before the
season starts, so it is usable pregame.
"""

from __future__ import annotations

import math

# stadium_id: (latitude, longitude, IANA time zone)
STADIUMS: dict[str, tuple[float, float, str]] = {
    "ATL00": (33.758, -84.401, "America/New_York"),
    "ATL97": (33.755, -84.401, "America/New_York"),
    "BAL00": (39.278, -76.623, "America/New_York"),
    "BOS00": (42.091, -71.264, "America/New_York"),
    "BOS99": (42.091, -71.264, "America/New_York"),
    "BRG00": (30.412, -91.184, "America/Chicago"),
    "BUF00": (42.774, -78.787, "America/New_York"),
    "BUF01": (43.641, -79.389, "America/Toronto"),
    "CAR00": (35.226, -80.853, "America/New_York"),
    "CHI98": (41.862, -87.617, "America/Chicago"),
    "CHI99": (40.099, -88.236, "America/Chicago"),
    "CIN00": (39.095, -84.516, "America/New_York"),
    "CIN99": (39.097, -84.507, "America/New_York"),
    "CLE00": (41.506, -81.700, "America/New_York"),
    "DAL00": (32.748, -97.093, "America/Chicago"),
    "DAL99": (32.840, -96.911, "America/Chicago"),
    "DEN00": (39.744, -105.020, "America/Denver"),
    "DEN99": (39.744, -105.021, "America/Denver"),
    "DET00": (42.340, -83.046, "America/Detroit"),
    "DET99": (42.646, -83.255, "America/Detroit"),
    "FRA00": (50.069, 8.646, "Europe/Berlin"),
    "GER00": (48.219, 11.625, "Europe/Berlin"),
    "GNB00": (44.501, -88.062, "America/Chicago"),
    "HOU00": (29.685, -95.411, "America/Chicago"),
    "IND00": (39.760, -86.164, "America/Indiana/Indianapolis"),
    "IND99": (39.763, -86.164, "America/Indiana/Indianapolis"),
    "JAX00": (30.324, -81.637, "America/New_York"),
    "KAN00": (39.049, -94.484, "America/Chicago"),
    "LAX01": (33.953, -118.339, "America/Los_Angeles"),
    "LAX97": (33.864, -118.261, "America/Los_Angeles"),
    "LAX99": (34.014, -118.288, "America/Los_Angeles"),
    "LON00": (51.556, -0.280, "Europe/London"),
    "LON01": (51.456, -0.342, "Europe/London"),
    "LON02": (51.604, -0.066, "Europe/London"),
    "MAD01": (40.453, -3.688, "Europe/Madrid"),
    "MEL00": (-37.820, 144.983, "Australia/Melbourne"),
    "MEX00": (19.303, -99.150, "America/Mexico_City"),
    "MIA00": (25.958, -80.239, "America/New_York"),
    "MIN00": (44.974, -93.258, "America/Chicago"),
    "MIN01": (44.974, -93.258, "America/Chicago"),
    "MIN98": (44.976, -93.225, "America/Chicago"),
    "MUN01": (48.219, 11.625, "Europe/Berlin"),
    "NAS00": (36.166, -86.771, "America/Chicago"),
    "NOR00": (29.951, -90.081, "America/Chicago"),
    "NYC00": (40.813, -74.074, "America/New_York"),
    "NYC01": (40.814, -74.074, "America/New_York"),
    "OAK00": (37.752, -122.201, "America/Los_Angeles"),
    "PAR00": (48.924, 2.360, "Europe/Paris"),
    "PHI00": (39.901, -75.168, "America/New_York"),
    "PHI99": (39.906, -75.171, "America/New_York"),
    "PHO00": (33.528, -112.263, "America/Phoenix"),
    "PHO99": (33.426, -111.933, "America/Phoenix"),
    "PIT00": (40.447, -80.016, "America/New_York"),
    "PIT99": (40.447, -80.013, "America/New_York"),
    "RIO00": (-22.912, -43.230, "America/Sao_Paulo"),
    "SAN00": (29.417, -98.479, "America/Chicago"),
    "SAO00": (-23.545, -46.474, "America/Sao_Paulo"),
    "SDG00": (32.783, -117.120, "America/Los_Angeles"),
    "SEA00": (47.595, -122.332, "America/Los_Angeles"),
    "SEA98": (47.595, -122.332, "America/Los_Angeles"),
    "SEA99": (47.650, -122.302, "America/Los_Angeles"),
    "SFO00": (37.714, -122.386, "America/Los_Angeles"),
    "SFO01": (37.403, -121.970, "America/Los_Angeles"),
    "STL00": (38.633, -90.188, "America/Chicago"),
    "TAM00": (27.976, -82.503, "America/New_York"),
    "VEG00": (36.091, -115.184, "America/Los_Angeles"),
    "WAS00": (38.908, -76.864, "America/New_York"),
}


def distance_km(a: str | None, b: str | None) -> float:
    """Great-circle distance between two stadiums, NaN if either is unknown."""
    if a not in STADIUMS or b not in STADIUMS:
        return float("nan")
    la1, lo1, _ = STADIUMS[a]
    la2, lo2, _ = STADIUMS[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def utc_offset_hours(stadium: str | None, when) -> float:
    """The stadium's UTC offset (hours) at a moment, NaN if unknown."""
    from zoneinfo import ZoneInfo

    if stadium not in STADIUMS:
        return float("nan")
    tz = ZoneInfo(STADIUMS[stadium][2])
    stamp = when.to_pydatetime() if hasattr(when, "to_pydatetime") else when
    offset = stamp.astimezone(tz).utcoffset()
    return offset.total_seconds() / 3600 if offset is not None else float("nan")
