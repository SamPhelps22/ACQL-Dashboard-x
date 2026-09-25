"""Pool lines, and the Vegas spreads typed in to predict against them.

Some games on a week sheet carry a line in row 8, under the game's column:
"(phi by 8)". The named favourite has to win by MORE than the number; a win
by exactly the line goes to the underdog, and the Result row records that
outcome (Lions 31-30 over the Saints with "(det by 8)" is recorded as a
Saints win).

The parser that builds the Season does not read these notes, so this module
reads them straight from the workbook as it loads and attaches them to each
Game. Nothing here depends on how the rest of the sheet was parsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT
from .models import Game, Season

LINE_ROW = 8
FIRST_GAME_COL = 6        # column F holds game 1
GAME_COLUMNS = 16         # F..U
#: Where older versions kept typed spreads; read in once by store.py.
SPREADS_FILE = ROOT / "acql-spreads.json"

# "(phi by 8)", "(TB by 9.5)", "(kc -7)" - an abbreviation, then the points.
NOTE = re.compile(r"([A-Za-z]{2,3})\s*(?:by|-)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)

# Every way the sheet might name each team, for matching an abbreviation to
# the home or away name written above it.
TEAMS: dict[str, tuple[str, ...]] = {
    "ari": ("arizona", "cardinals"), "atl": ("atlanta", "falcons"),
    "bal": ("baltimore", "ravens"), "buf": ("buffalo", "bills"),
    "car": ("carolina", "panthers"), "chi": ("chicago", "bears"),
    "cin": ("cincinnati", "bengals"), "cle": ("cleveland", "browns"),
    "dal": ("dallas", "cowboys"), "den": ("denver", "broncos"),
    "det": ("detroit", "lions"), "gb": ("green bay", "packers"),
    "hou": ("houston", "texans"), "ind": ("indianapolis", "colts"),
    "jax": ("jacksonville", "jaguars"), "jac": ("jacksonville", "jaguars"),
    "kc": ("kansas city", "chiefs"), "lac": ("los angeles chargers", "chargers"),
    "lar": ("los angeles rams", "rams"), "lv": ("las vegas", "raiders"),
    "mia": ("miami", "dolphins"), "min": ("minnesota", "vikings"),
    "ne": ("new england", "patriots"), "no": ("new orleans", "saints"),
    "nyg": ("new york giants", "giants"), "nyj": ("new york jets", "jets"),
    "phi": ("philadelphia", "eagles"), "pit": ("pittsburgh", "steelers"),
    "sea": ("seattle", "seahawks"), "sf": ("san francisco", "49ers"),
    "tb": ("tampa bay", "buccaneers"), "ten": ("tennessee", "titans"),
    "was": ("washington", "commanders"), "wsh": ("washington", "commanders"),
}

# Names a file or a sheet might still use for a team that has moved or been
# renamed. Ratings files in particular are decades old and some of them never
# updated; without these a team silently fails to match and its game is
# quietly dropped.
FORMER_NAMES = {
    "was": ("redskins", "washington redskins", "washington football team"),
    "lv": ("oakland", "oakland raiders"),
    "lac": ("san diego", "san diego chargers"),
    "lar": ("st louis", "st. louis", "st louis rams"),
    "ten": ("houston oilers", "oilers"),
    "ind": ("baltimore colts",),
}
for _code, _names in FORMER_NAMES.items():
    TEAMS[_code] = TEAMS[_code] + _names


def _norm(text: object) -> str:
    return " ".join(str(text or "").split()).casefold()


def parse_note(text: object) -> tuple[str, float] | None:
    """('phi', 8.0) from "(phi by 8)", or None if the cell is not a line."""
    m = NOTE.search(str(text or ""))
    if not m or m.group(1).lower() not in TEAMS:
        return None
    return m.group(1).lower(), float(m.group(2))


def names_team(abbr: str, name: str) -> bool:
    """Whether a slate name ("Los Angeles Rams", "philadelphia") is that team."""
    n = _norm(name)
    return bool(n) and any(n == w or n.startswith(w) or w in n for w in TEAMS.get(abbr, ()))


def read_notes(path: Path) -> dict[int, dict[int, object]]:
    """{week: {game index: raw note}} for every non-empty cell in row 8."""
    import openpyxl  # only needed when a workbook is loaded

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        out: dict[int, dict[int, object]] = {}
        for ws in wb.worksheets:
            m = re.fullmatch(r"\s*week\s*(\d+)\s*", ws.title, re.IGNORECASE)
            if not m:
                continue
            row = next(ws.iter_rows(
                min_row=LINE_ROW, max_row=LINE_ROW,
                min_col=FIRST_GAME_COL, max_col=FIRST_GAME_COL + GAME_COLUMNS - 1,
                values_only=True,
            ), ())
            notes = {i: v for i, v in enumerate(row, start=1) if v not in (None, "")}
            if notes:
                out[int(m.group(1))] = notes
        return out
    finally:
        wb.close()


def attach(season: Season, notes: dict[int, dict[int, object]]) -> list[str]:
    """Put each note's line on its game. Returns a warning per note skipped.

    A note belongs to the game in its own column. If the abbreviation names
    neither team in that game, the note is left off rather than guessed at,
    and reported, so a typo shows up instead of silently moving a line.
    """
    warnings: list[str] = []
    for week_no, week_notes in notes.items():
        week = season.weeks.get(week_no)
        games = {g.index: g for g in (week.games if week else [])}
        for index, raw in week_notes.items():
            parsed = parse_note(raw)
            if parsed is None:
                warnings.append(f"Week {week_no}, game {index}: can't read the line note {str(raw)!r}")
                continue
            abbr, points = parsed
            game = games.get(index)
            if game is None:
                warnings.append(f"Week {week_no}, game {index}: line note {str(raw)!r} but no game there")
                continue
            if names_team(abbr, game.home) and not names_team(abbr, game.away):
                favourite = game.home
            elif names_team(abbr, game.away) and not names_team(abbr, game.home):
                favourite = game.away
            else:
                warnings.append(
                    f"Week {week_no}, game {index}: {str(raw)!r} doesn't match "
                    f"{game.away} @ {game.home}"
                )
                continue
            game.line, game.line_favourite = points, favourite
    return warnings


def attach_from_workbook(season: Season) -> list[str]:
    """Read and attach every line in the season's workbook, if it has one."""
    if season.workbook_path is None:
        return []
    return attach(season, read_notes(Path(season.workbook_path)))


# ---- Vegas spreads typed in on the Next Week page ---------------------------
@dataclass(frozen=True)
class Spread:
    favourite: str      # "home" or "away"
    points: float


def _game_key(game: Game) -> str:
    """Identifies the matchup, so a spread never follows a game that changed."""
    return f"{_norm(game.away)}@{_norm(game.home)}"


def load_spreads(week: int, games: list[Game]) -> dict[int, Spread]:
    from . import store
    saved = store.get("spreads", str(week), {})
    if not isinstance(saved, dict):
        return {}
    out = {}
    for game in games:
        entry = saved.get(str(game.index))
        if (
            isinstance(entry, dict)
            and entry.get("match") == _game_key(game)
            and entry.get("favourite") in ("home", "away")
            and isinstance(entry.get("points"), (int, float))
        ):
            out[game.index] = Spread(entry["favourite"], float(entry["points"]))
    return out


def save_spread(week: int, game: Game, spread: Spread | None) -> None:
    """Store or clear one game's spread, leaving every other entry alone."""
    from . import store
    week_entries = dict(store.get("spreads", str(week), {}) or {})
    if spread is None:
        week_entries.pop(str(game.index), None)
    else:
        week_entries[str(game.index)] = {
            "match": _game_key(game), "favourite": spread.favourite, "points": spread.points,
        }
    try:
        if week_entries:
            store.put("spreads", str(week), week_entries)
        else:
            store.delete("spreads", str(week))
    except store.StoreError:
        pass


# ---- reading a block of odds pasted from a website -------------------------
_NUMBER = re.compile(r"(?<![\d(])([+-]?\d{1,2}(?:\.5)?)(?![\d)])")
_PLAUSIBLE_SPREAD = 25          # bigger than this is a total or a moneyline


def _mentions(name: str) -> tuple[str, ...]:
    """Everything a pasted line might call this team."""
    low = _norm(name)
    words = {low, low.split()[-1] if low else ""}
    for abbr, aliases in TEAMS.items():
        if any(low == w or low.startswith(w) or w in low for w in aliases):
            words.update(aliases)
            words.add(abbr)
    return tuple(w for w in words if w)


def parse_odds_text(text: str, games: list[Game]) -> tuple[dict[int, Spread], list[str]]:
    """Pull a favourite and spread for each game out of pasted odds text.

    Handles the shapes odds pages actually use - "Bengals -3.5 at Steelers",
    "ATL @ GB | GB -7 (-110)", "Eagles -4 at Chicago Bears" - by finding which
    two slate teams a line mentions, then the spread nearest to one of them.
    Moneylines, totals and the vig in brackets are ignored; anything it cannot
    read is reported rather than guessed at.
    """
    found: dict[int, Spread] = {}
    notes: list[str] = []
    lookup = [
        (game, {"home": _mentions(game.home), "away": _mentions(game.away)})
        for game in games
    ]
    for raw in text.splitlines():
        line = " " + _norm(raw) + " "
        if not line.strip():
            continue
        hits = []
        for game, sides in lookup:
            spots = {
                side: min(
                    (line.find(f" {w} ") for w in words if f" {w} " in line), default=-1
                )
                for side, words in sides.items()
            }
            if spots["home"] >= 0 or spots["away"] >= 0:
                hits.append((game, spots))
        if len(hits) != 1:
            if hits:
                notes.append(f"skipped an ambiguous line: {raw.strip()[:60]}")
            continue
        game, spots = hits[0]
        numbers = [
            (m.start(), float(m.group(1)), m.group(1))
            for m in _NUMBER.finditer(line)
            if abs(float(m.group(1))) <= _PLAUSIBLE_SPREAD
        ]
        if not numbers:
            notes.append(f"no spread in: {raw.strip()[:60]}")
            continue
        # A signed number is the spread; otherwise take the first plausible one.
        position, points, token = next((n for n in numbers if n[1] < 0), numbers[0])
        # "+7" is quoted from the UNDERDOG's side, so whichever team it is
        # attached to, the favourite is the other one.
        quoted_from_the_dog = token.startswith("+")
        # The favourite is whichever team the number is attached to: the one
        # closest before it ("GB -7"), or the closest after when the line
        # leads with the number. It has to be the closest MENTION, not the
        # team's first mention - "KC Chiefs @ MIA Dolphins | KC -10" names
        # both teams before the number, and the -10 belongs to the second KC.
        words = next(w for g, w in lookup if g is game)
        nearest_before = {
            side: max((line.rfind(f" {w} ", 0, position) for w in side_words), default=-1)
            for side, side_words in words.items()
        }
        nearest_after = {
            side: min(
                (p for p in (line.find(f" {w} ", position) for w in side_words) if p >= 0),
                default=len(line) + 1,
            )
            for side, side_words in words.items()
        }
        if max(nearest_before.values()) >= 0:
            side = max(nearest_before, key=lambda s: nearest_before[s])
            flip = quoted_from_the_dog                    # "Falcons +7 at GB"
        else:
            side = min(nearest_after, key=lambda s: nearest_after[s])
            flip = points > 0                            # "+7 Falcons at GB"
        if flip:
            side = "home" if side == "away" else "away"
        found[game.index] = Spread(side, abs(points))
    return found, notes
