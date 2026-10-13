"""Configuration loading: config.toml merged with settings.local.json overrides."""

from __future__ import annotations

import copy
import json
import os
import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.toml"
LOCAL_OVERRIDES = PROJECT_ROOT / "settings.local.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from .env into os.environ without overriding."""
    path = path or PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_config(path: Path | None = None, overrides: dict | None = None,
                use_local: bool = True) -> dict[str, Any]:
    """Return the merged configuration dictionary."""
    with open(path or DEFAULT_CONFIG, "rb") as fh:
        cfg = tomllib.load(fh)
    if use_local and LOCAL_OVERRIDES.exists():
        cfg = _deep_merge(cfg, json.loads(LOCAL_OVERRIDES.read_text()))
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    load_env()
    if os.environ.get("NFLPICKEM_DB_PATH"):
        cfg["data"]["db_path"] = os.environ["NFLPICKEM_DB_PATH"]
    validate_config(cfg)
    return cfg


def save_local_overrides(overrides: dict) -> None:
    existing = json.loads(LOCAL_OVERRIDES.read_text()) if LOCAL_OVERRIDES.exists() else {}
    LOCAL_OVERRIDES.write_text(json.dumps(_deep_merge(existing, overrides), indent=2))


def resolve_path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else PROJECT_ROOT / p


def validate_config(cfg: dict) -> None:
    """Raise ValueError with a readable message for invalid settings."""
    b = cfg["blend"]
    if not 0.0 <= float(b["market_weight"]) <= 1.0:
        raise ValueError("blend.market_weight must be between 0 and 1")
    if b["mode"] not in {"fixed", "learned"}:
        raise ValueError("blend.mode must be 'fixed' or 'learned'")
    if b["space"] not in {"probability", "logit"}:
        raise ValueError("blend.space must be 'probability' or 'logit'")
    if any(float(w) < 0 for w in b["ml_weights"].values()):
        raise ValueError("blend.ml_weights must be non-negative")
    p = cfg["pool"]
    if p["tie_rule"] not in {"zero", "half", "full"}:
        raise ValueError("pool.tie_rule must be zero, half or full")
    if p["postponed_rule"] not in {"void", "loss"}:
        raise ValueError("pool.postponed_rule must be void or loss")
    if p["points_mode"] not in {"1_to_n", "custom"}:
        raise ValueError("pool.points_mode must be 1_to_n or custom")
    if p["cutoff_mode"] not in {"slate", "per_game"}:
        raise ValueError("pool.cutoff_mode must be slate or per_game")
    if cfg["models"].get("pick_model", "blend") not in {"blend", "market", "elo", "logistic", "gbm", "residual"}:
        raise ValueError("models.pick_model must be blend, market, elo, logistic or gbm")
    if cfg["models"]["calibration"] not in {"none", "platt", "isotonic", "auto"}:
        raise ValueError("models.calibration must be none, platt, isotonic or auto")
