"""Player-name reconciliation across source files.

The two workbooks spell some players differently ("SaleeNmd " carries a
trailing space; nicknames drift between seasons). Everything downstream keys
off a normalized form, and genuine nickname differences are resolved through an
editable aliases.json so a rename never silently drops a player from standings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import ALIASES_FILE

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize(name: object) -> str:
    """Collapse a display name to a stable matching key.

    Case, surrounding whitespace, internal runs of whitespace and punctuation
    are all discarded: "MayeDay! MayeDay!" and "mayeday mayeday" agree.
    """
    if name is None:
        return ""
    text = str(name).replace(" ", " ").strip()
    if not text:
        return ""
    text = _PUNCT.sub(" ", text)
    return _SPACE.sub(" ", text).strip().lower()


class AliasTable:
    """Maps normalized spellings onto a single canonical player key."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        # Stored as {alias_normalized: canonical_normalized}.
        self._map: dict[str, str] = {}
        self._display: dict[str, str] = {}
        for alias, canonical in (mapping or {}).items():
            self.add(alias, canonical)

    @classmethod
    def load(cls, path: Path | None = None) -> "AliasTable":
        path = path or ALIASES_FILE
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    aliases = raw.get("aliases", raw)
                    return cls({str(k): str(v) for k, v in aliases.items()})
            except (OSError, ValueError, TypeError):
                pass
        return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or ALIASES_FILE
        payload = {
            "_comment": (
                "Map an alternate spelling to the canonical name. "
                "Both sides are matched case- and punctuation-insensitively."
            ),
            "aliases": {a: self._display.get(c, c) for a, c in self._map.items()},
        }
        try:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def add(self, alias: str, canonical: str) -> None:
        a, c = normalize(alias), normalize(canonical)
        if a and c and a != c:
            self._map[a] = c
            self._display[c] = str(canonical).strip()

    def key(self, name: object) -> str:
        """Canonical key for a raw name, following at most one alias hop."""
        n = normalize(name)
        return self._map.get(n, n)

    def __len__(self) -> int:
        return len(self._map)
