"""Situational and environmental features: rest, travel, time zones, altitude, roof, surface, weather.

Everything except weather is known when the schedule is published. Weather
here is nflverse's game-time observation (temp, wind) - retrospective. Only
models labelled `closing_retrospective` may use it; their gain is an upper
bound on what a pre-game forecast could get from weather.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# (lat, lon, utc offset in standard time, altitude m) of each franchise's home, by era.
HOMES = {
    "ARI": (33.53, -112.26, -7, 330), "ATL": (33.76, -84.40, -5, 300), "BAL": (39.28, -76.62, -5, 10),
    "BUF": (42.77, -78.79, -5, 180), "CAR": (35.23, -80.85, -5, 230), "CHI": (41.86, -87.62, -6, 180),
    "CIN": (39.10, -84.52, -5, 150), "CLE": (41.51, -81.70, -5, 180), "DAL": (32.75, -97.09, -6, 180),
    "DEN": (39.74, -105.02, -7, 1609), "DET": (42.34, -83.05, -5, 190), "GB": (44.50, -88.06, -6, 200),
    "HOU": (29.68, -95.41, -6, 15), "IND": (39.76, -86.16, -5, 220), "JAX": (30.32, -81.64, -5, 5),
    "KC": (39.05, -94.48, -6, 270), "LA": (33.95, -118.34, -8, 30), "LAC": (33.95, -118.34, -8, 30),
    "LV": (36.09, -115.18, -8, 620), "MIA": (25.96, -80.24, -5, 5), "MIN": (44.97, -93.26, -6, 260),
    "NE": (42.09, -71.26, -5, 90), "NO": (29.95, -90.08, -6, 3), "NYG": (40.81, -74.07, -5, 5),
    "NYJ": (40.81, -74.07, -5, 5), "PHI": (39.90, -75.17, -5, 10), "PIT": (40.45, -80.02, -5, 230),
    "SEA": (47.60, -122.33, -8, 5), "SF": (37.40, -121.97, -8, 5), "TB": (27.98, -82.50, -5, 10),
    "TEN": (36.17, -86.77, -6, 130), "WAS": (38.91, -76.86, -5, 50),
}
ERAS = {  # franchise moves inside the data
    "LA": [(2015, (38.63, -90.19, -6, 140))],                 # St. Louis through 2015
    "LAC": [(2016, (32.78, -117.12, -8, 20))],               # San Diego through 2016
    "LV": [(2019, (37.75, -122.20, -8, 5))],                 # Oakland through 2019
    "SF": [(2013, (37.71, -122.39, -8, 5))],                 # Candlestick through 2013
}
ABROAD = {  # stadium keyword -> (lat, lon, utc offset, altitude)
    "Wembley": (51.56, -0.28, 0, 30), "Tottenham": (51.60, -0.07, 0, 30), "Twickenham": (51.46, -0.34, 0, 10),
    "Azteca": (19.30, -99.15, -6, 2240), "Banorte": (19.30, -99.15, -6, 2240), "Rogers Centre": (43.64, -79.39, -5, 80),
    "Allianz": (48.22, 11.62, 1, 520), "Bayern": (48.22, 11.62, 1, 520), "Deutsche Bank Park": (50.07, 8.65, 1, 110),
    "Corinthians": (-23.55, -46.47, -3, 760), "Maracana": (-22.91, -43.23, -3, 10), "Melbourne": (-37.82, 144.98, 10, 30),
    "Stade de France": (48.92, 2.36, 1, 40), "Bernabeu": (40.45, -3.69, 1, 650), "Croke": (53.36, -6.25, 0, 10),
    "Olympiastadion": (52.51, 13.24, 1, 50),
}


def home_of(team: str, season: int):
    for last, loc in ERAS.get(team, []):
        if season <= last:
            return loc
    return HOMES.get(team)


def venue(row) -> tuple | None:
    if not row.neutral:
        return home_of(row.home_team, row.season)
    name = str(row.stadium)
    for key, loc in ABROAD.items():
        if key in name:
            return loc
    return None          # a US neutral site: resolved by stadium below


def _km(a, b):
    if a is None or b is None:
        return np.nan
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


DOME_HOMES = {"ATL", "DET", "IND", "MIN", "NO", "ARI", "DAL", "HOU", "LV", "LA"}  # roofed most seasons


def build(snap, week: pd.DataFrame) -> pd.DataFrame:
    """Schedule-time features (no weather)."""
    if not len(week):
        return pd.DataFrame()
    stadium_home = {}
    if snap is not None and len(snap.games):
        sg = snap.games[snap.games["neutral"] == 0]
        stadium_home = sg.groupby("stadium")["home_team"].agg(lambda s: s.value_counts().index[0]).to_dict()
    rows = []
    for g in week.itertuples():
        v = venue(g)
        if v is None and g.stadium in stadium_home:
            v = home_of(stadium_home[g.stadium], g.season)
        hh, ah = home_of(g.home_team, g.season), home_of(g.away_team, g.season)
        kick_et = pd.Timestamp(g.kickoff).tz_convert("America/New_York")
        row = {"game_id": g.game_id,
               "rest_diff": (g.home_rest - g.away_rest) if pd.notna(g.home_rest) and pd.notna(g.away_rest) else 0.0,
               "h_short": float(pd.notna(g.home_rest) and g.home_rest <= 5),
               "a_short": float(pd.notna(g.away_rest) and g.away_rest <= 5),
               "h_bye": float(pd.notna(g.home_rest) and g.home_rest >= 13),
               "a_bye": float(pd.notna(g.away_rest) and g.away_rest >= 13),
               "a_km": _km(ah, v), "h_km": _km(hh, v),
               "a_tz": (v[2] - ah[2]) if v and ah else np.nan, "h_tz": (v[2] - hh[2]) if v and hh else np.nan,
               "altitude": (v[3] if v else np.nan),
               "dome": float(g.roof in ("dome", "closed")),
               "turf": float(isinstance(g.surface, str) and "grass" not in g.surface.lower()),
               "div_game": float(g.div_game == 1),
               "neutral": float(g.neutral),
               "early_west_away": float(ah is not None and ah[2] <= -7 and v is not None and v[2] >= -5
                                        and kick_et.hour < 14),
               "venue_known": float(v is not None)}
        row["a_tz_east"] = max(row["a_tz"], 0) if not np.isnan(row["a_tz"]) else 0.0
        row["a_tz_west"] = max(-row["a_tz"], 0) if not np.isnan(row["a_tz"]) else 0.0
        row["a_dome_team"] = float(g.away_team in DOME_HOMES)
        rows.append(row)
    return pd.DataFrame(rows)


def weather(week: pd.DataFrame) -> pd.DataFrame:
    """Observed game weather (retrospective). Domes/closed roofs read as calm 70F."""
    out = pd.DataFrame({"game_id": week["game_id"].values})
    roofed = week["roof"].isin(["dome", "closed"]).values
    temp = np.where(roofed, 70.0, week["temp"].astype(float).values)
    wind = np.where(roofed, 0.0, week["wind"].astype(float).values)
    out["weather_missing"] = np.isnan(temp).astype(float)
    out["temp"] = np.where(np.isnan(temp), 60.0, temp)
    out["wind"] = np.where(np.isnan(wind), 7.0, wind)
    out["cold"] = (out["temp"] < 35).astype(float)
    out["windy"] = (out["wind"] >= 15).astype(float)
    return out
