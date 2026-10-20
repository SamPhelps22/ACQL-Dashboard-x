"""The PFM check, read off disk for the Model Lab.

The training ground measures Pro Football Mania's ratings against Deadeye
(acql/training/pfm.py) and leaves one file, data/training/pfm/latest.json.
This reads it and lays it out as rows, the way challengers.py does for the
weekly training verdict. The dashboard never imports the training package,
never runs the study, and nothing here reaches a pick: the shadow chance
shown beside the card is labelled as such everywhere it appears.

A missing, damaged or half-written file is no answer, never an error. No Qt here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from ..store import data_dir

WHERE = ("training", "pfm", "latest.json")
#: Older than this, the study is shown as stale.
STALE_S = 9 * 86400
HEADERS = ["Version", "Games", "Log loss", "Brier", "Against Deadeye", "Could be from", "Reading"]
WEEK_HEADERS = ["Game", "PFM road · home", "PFM gap", "Deadeye: home", "Line alone: home", "PFM shadow: home",
                "Shift"]
#: The variants the card lists; a one-grade variant is listed only once it has been taught at all.
SHOWN = ("A ", "B ", "C ", "C2 ", "C3 ", "E ", "F ")


@dataclass
class Check:
    call: str = ""
    why: str = ""
    made: float = 0.0
    games: int = 0
    freshness: str = ""
    fresh_state: str = ""
    rows: list[list] = field(default_factory=list)
    better: set[int] = field(default_factory=set)
    worse: set[int] = field(default_factory=set)
    week: int | None = None
    week_rows: list[list] = field(default_factory=list)
    sealed: bool | None = None
    revisions: int = 0
    #: C's newest taught weight on the PFM gap (standardised, logit a spread): minus fades PFM's favourite.
    weight: float | None = None

    def stale(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) - self.made > STALE_S


def _signed(value, none: str = "-") -> str:
    return none if value is None else f"{value:+.4f}"


def _pct(value) -> str:
    return "-" if value is None else f"{value:.0%}"


def reading(mark: dict) -> str:
    if mark["name"].startswith("A "):
        return "the rule in use"
    if mark["name"].startswith("B "):
        return "line only, no PFM"
    if not mark.get("taught"):
        return "not taught yet"
    low, high = mark.get("low"), mark.get("high")
    if high is not None and high < 0:
        return "better, beyond luck - a reason to look"
    if low is not None and low > 0:
        return "worse, beyond luck"
    return "can't tell from luck yet"


def read(path=None) -> Check | None:
    """The newest PFM check on disk, or None."""
    try:
        found = json.loads((path or data_dir().joinpath(*WHERE)).read_text(encoding="utf-8"))
        out = Check(call=str(found["call"]), why=str(found.get("why", "")), made=float(found.get("made", 0.0)),
                    games=int(found.get("games", 0)),
                    freshness=str((found.get("freshness") or {}).get("words", "")),
                    fresh_state=str((found.get("freshness") or {}).get("state", "")),
                    revisions=len(found.get("revisions") or []))
        seals = found.get("seals") or []
        out.sealed = all(s.get("ok") for s in seals) if seals else None
        for mark in found.get("marks") or []:
            name = str(mark["name"])
            if not (name.startswith(SHOWN) or mark.get("taught")):
                continue
            r = len(out.rows)
            out.rows.append([name, mark.get("games", 0),
                             "-" if mark.get("logloss") is None else f"{mark['logloss']:.4f}",
                             "-" if mark.get("brier") is None else f"{mark['brier']:.4f}",
                             "-" if name.startswith("A ") or not (mark.get("taught") or name.startswith("B "))
                             else _signed(mark.get("vs_a")),
                             "-" if name.startswith("A ") or mark.get("low") is None
                             or not (mark.get("taught") or name.startswith("B "))
                             else f"{_signed(mark['low'])} to {_signed(mark['high'])}",
                             reading(mark)])
            if mark.get("high") is not None and mark["high"] < 0 and not name.startswith("A "):
                out.better.add(r)
            if mark.get("low") is not None and mark["low"] > 0 and not name.startswith("A "):
                out.worse.add(r)
        taught = (found.get("weights") or {}).get("C Deadeye + PFM score") or {}
        if taught:
            newest = taught[max(taught, key=int)]
            out.weight = float(newest[0]) if newest else None
        from .predictions import display_matchup
        for game in found.get("upcoming") or []:
            out.week = int(game.get("week") or 0) or out.week
            shadow, card = game.get("shadow"), game.get("deadeye")
            shift = None if shadow is None or card is None else shadow - card
            pfm = ("-" if game.get("pfm_home") is None or game.get("pfm_away") is None
                   else f"{game['pfm_away']:.1f} · {game['pfm_home']:.1f}")
            out.week_rows.append([display_matchup(game["away"], game["home"]), pfm,
                                  "-" if game.get("score_diff") is None else f"{game['score_diff']:+.1f}",
                                  _pct(card), _pct(game.get("market")), _pct(shadow),
                                  "-" if shift is None else f"{shift * 100:+.1f} pts"])
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return None
