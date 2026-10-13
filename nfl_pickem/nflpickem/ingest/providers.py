"""Provider interfaces for odds and injuries, with a registry used by the CLI/UI.

Adding a provider: subclass OddsProvider / InjuryProvider, implement fetch(),
and register it in ODDS_PROVIDERS / INJURY_PROVIDERS.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import pandas as pd
import requests

from ..teams import normalize_team

log = logging.getLogger(__name__)


class ProviderUnavailable(RuntimeError):
    """Raised when a provider is not configured or cannot be reached."""


class OddsProvider(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(is_configured, human-readable reason)."""

    @abstractmethod
    def fetch(self, games: pd.DataFrame) -> pd.DataFrame:
        """Return rows in odds_snapshots layout for the given upcoming games."""


class NflverseOddsProvider(OddsProvider):
    """Lines come bundled with the nflverse schedule; ingest_schedule stores them."""

    name = "nflverse"

    def available(self) -> tuple[bool, str]:
        return True, "Bundled with nflverse games.csv (closing lines for past games, current lines for upcoming)"

    def fetch(self, games: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame()  # handled by ingest_schedule


class TheOddsApiProvider(OddsProvider):
    """The Odds API v4 (https://the-odds-api.com/liveapi/guides/v4/). Requires ODDS_API_KEY."""

    name = "the_odds_api"
    URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"

    def __init__(self, api_key: str | None = None, regions: str | None = None,
                 bookmakers: str | None = None, session: requests.Session | None = None):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY", "")
        self.regions = regions or os.environ.get("ODDS_API_REGIONS", "us")
        self.bookmakers = bookmakers if bookmakers is not None else os.environ.get("ODDS_API_BOOKMAKERS", "")
        self.session = session or requests.Session()

    def available(self) -> tuple[bool, str]:
        if not self.api_key or self.api_key.startswith("your-"):
            return False, "ODDS_API_KEY not set"
        return True, "configured"

    def fetch(self, games: pd.DataFrame) -> pd.DataFrame:
        ok, reason = self.available()
        if not ok:
            raise ProviderUnavailable(reason)
        params = {"apiKey": self.api_key, "regions": self.regions, "markets": "h2h,spreads",
                  "oddsFormat": "american", "dateFormat": "iso"}
        if self.bookmakers:
            params["bookmakers"] = self.bookmakers
        resp = self.session.get(self.URL, params=params, timeout=30)
        if resp.status_code != 200:
            raise ProviderUnavailable(f"The Odds API HTTP {resp.status_code}: {resp.text[:200]}")
        return self.parse(resp.json(), games, datetime.now(timezone.utc).replace(tzinfo=None))

    @staticmethod
    def parse(events: list[dict], games: pd.DataFrame, captured_at: datetime) -> pd.DataFrame:
        """Match API events to our games by (home, away, kickoff within 36h)."""
        rows = []
        g = games.copy()
        for ev in events:
            home, away = normalize_team(ev.get("home_team")), normalize_team(ev.get("away_team"))
            ko = pd.to_datetime(ev.get("commence_time"), utc=True).tz_localize(None)
            cand = g[(g.home_team == home) & (g.away_team == away)
                     & ((g.kickoff_utc - ko).abs() < pd.Timedelta(hours=36))]
            if cand.empty:
                log.debug("Unmatched odds event %s @ %s", away, home)
                continue
            gid = cand.iloc[0].game_id
            for bk in ev.get("bookmakers", []):
                rec = {"game_id": gid, "captured_at": captured_at,
                       "provider": f"the_odds_api:{bk.get('key')}",
                       "home_moneyline": None, "away_moneyline": None, "home_spread": None,
                       "source_timestamp": pd.to_datetime(bk.get("last_update"), utc=True).tz_localize(None),
                       "is_closing": False}
                for mk in bk.get("markets", []):
                    for oc in mk.get("outcomes", []):
                        team = normalize_team(oc.get("name"))
                        if mk.get("key") == "h2h":
                            rec["home_moneyline" if team == home else "away_moneyline"] = oc.get("price")
                        elif mk.get("key") == "spreads" and team == home:
                            rec["home_spread"] = oc.get("point")
                rows.append(rec)
        return pd.DataFrame(rows)


ODDS_PROVIDERS: dict[str, type[OddsProvider]] = {
    "nflverse": NflverseOddsProvider,
    "the_odds_api": TheOddsApiProvider,
}


def get_odds_provider(name: str) -> OddsProvider:
    if name not in ODDS_PROVIDERS:
        raise ValueError(f"Unknown odds provider {name!r}; choose from {list(ODDS_PROVIDERS)}")
    return ODDS_PROVIDERS[name]()
