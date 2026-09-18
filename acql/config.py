"""Filesystem layout and user settings.

Settings live next to the data rather than in the user's home directory so a
portable copy of the app (a USB stick, a shared drive) keeps its configuration.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path


def resource_root() -> Path:
    """Where bundled read-only assets live.

    PyInstaller unpacks datas into a temporary folder named by sys._MEIPASS;
    from a source checkout the package directory's parent serves the same role.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent


def app_root() -> Path:
    """The directory the app treats as its home.

    For a PyInstaller build this is the folder holding the executable, so the
    data/ folder sits beside the .exe the way a user expects. For a source
    checkout it is the repository root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = app_root()
DATA_DIR = ROOT / "data"
BACKUP_DIR = ROOT / "backups"
SETTINGS_FILE = ROOT / "acql-settings.json"
ICON_FILE = resource_root() / "packaging" / "icon.png"
ALIASES_FILE = ROOT / "aliases.json"

DEFAULT_BUY_IN = 40.0
WEEKS_IN_SEASON = 18
GAMES_PER_WEEK = 16
BIG_LOSER_PICKS = 3


@dataclass
class Settings:
    """User preferences, persisted to acql-settings.json."""

    data_dirs: list[str] = field(default_factory=list)
    theme: str = "dark"
    buy_in: float = DEFAULT_BUY_IN
    backup_before_write: bool = True
    last_week_viewed: int = 1
    warn_on_unmatched_players: bool = True

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.is_file():
            try:
                raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                known = {f for f in cls.__dataclass_fields__}
                return cls(**{k: v for k, v in raw.items() if k in known})
            except (OSError, ValueError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        try:
            SETTINGS_FILE.write_text(
                json.dumps(asdict(self), indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def search_paths(self) -> list[Path]:
        """Folders scanned for workbooks, most specific first.

        data/ and the app root are always included so the app works the moment
        it is unzipped, with no configuration step.
        """
        paths: list[Path] = []
        for raw in self.data_dirs:
            p = Path(os.path.expanduser(raw))
            if p.is_dir():
                paths.append(p.resolve())
        for default in (DATA_DIR, ROOT):
            if default.is_dir() and default.resolve() not in paths:
                paths.append(default.resolve())
        return paths
