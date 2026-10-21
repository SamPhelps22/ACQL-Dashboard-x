"""Settings shared by every part of the lab. Changing one is a new experiment."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "research_lab"
RAW = DATA / "raw"
DERIVED = DATA / "derived"
CACHE = DATA / "cache"
OUTPUTS = ROOT / "research_lab" / "outputs"        # committed backtest outputs (small)
REPORTS = ROOT / "research_lab" / "reports"
REGISTRY = ROOT / "research_lab" / "experiments" / "registry.jsonl"
SHADOW = ROOT / "research_lab" / "shadow" / "journal.jsonl"

LAB_VERSION = "0.1.0"

#: Play-by-play history starts here; the first seasons only warm models up.
FIRST_SEASON = 2006
#: First season that is scored in development.
DEV_FROM, DEV_TO = 2012, 2023
#: The frozen holdout. Scored once, after configs were frozen (see HOLDOUT_FROZEN_AT).
HOLDOUT = (2024, 2025)
#: Commit / date at which feature definitions, configs and selection rules were frozen.
HOLDOUT_FROZEN_AT = "see research_lab/experiments/freeze.json"   # written by `python -m research_lab freeze`
#: The season in progress (prospective shadow forecasting).
CURRENT_SEASON = 2026

#: Franchise moves: one identity per franchise.
TEAM_ALIASES = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA", "JAC": "JAX", "WSH": "WAS", "ARZ": "ARI"}

#: Standard deviation of NFL margins around a good forecast (points).
MARGIN_SD = 13.5

#: Information sets: what a forecast is allowed to see.
WEEK_START = "week_start"                       # Tuesday 09:00 ET, completed games only
PRE_KICKOFF = "pre_kickoff"                     # adds starters / final injury report
CLOSING_RETRO = "closing_retrospective"         # closing line / observed weather: benchmark only

SEED = 20261021


def team(code: str) -> str:
    code = (code or "").strip().upper()
    return TEAM_ALIASES.get(code, code)
