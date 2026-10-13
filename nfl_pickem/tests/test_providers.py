import pandas as pd
import pytest

from nflpickem.ingest.providers import ProviderUnavailable, TheOddsApiProvider, get_odds_provider


def test_odds_api_requires_key(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    p = TheOddsApiProvider(api_key="")
    assert p.available()[0] is False
    with pytest.raises(ProviderUnavailable):
        p.fetch(pd.DataFrame())


def test_odds_api_parse_matches_games():
    games = pd.DataFrame([{"game_id": "2024_01_BAL_KC", "home_team": "KC", "away_team": "BAL",
                           "kickoff_utc": pd.Timestamp("2024-09-06 00:20")}])
    events = [{"home_team": "Kansas City Chiefs", "away_team": "Baltimore Ravens",
               "commence_time": "2024-09-06T00:20:00Z",
               "bookmakers": [{"key": "bookA", "last_update": "2024-09-05T12:00:00Z", "markets": [
                   {"key": "h2h", "outcomes": [{"name": "Kansas City Chiefs", "price": -142},
                                               {"name": "Baltimore Ravens", "price": 120}]},
                   {"key": "spreads", "outcomes": [{"name": "Kansas City Chiefs", "point": -3.0, "price": -110},
                                                   {"name": "Baltimore Ravens", "point": 3.0, "price": -110}]}]}]},
              {"home_team": "Unknown", "away_team": "Team", "commence_time": "2024-09-06T00:20:00Z", "bookmakers": []}]
    df = TheOddsApiProvider.parse(events, games, pd.Timestamp("2024-09-05 13:00").to_pydatetime())
    assert len(df) == 1
    r = df.iloc[0]
    assert r.game_id == "2024_01_BAL_KC" and r.home_moneyline == -142 and r.away_moneyline == 120
    assert r.home_spread == -3.0 and r.provider == "the_odds_api:bookA"


def test_unknown_provider():
    with pytest.raises(ValueError):
        get_odds_provider("nope")
