"""Pool lines, and the Vegas spreads typed in to predict against them.

Some games on a week sheet carry a line in row 8, under the game's column:
"(phi by 8)". The named favourite has to win by at least the number - a win
by exactly the line goes to the favourite ("(sf by 13)", 49ers 37-24, was
graded a 49ers pick) - and the Result row records that outcome (Lions 31-30
over the Saints with "(det by 8)" is recorded as a Saints win).

The parser that builds the Season does not read these notes, so this module
reads them straight from the workbook as it loads and attaches them to each
Game. Nothing here depends on how the rest of the sheet was parsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT
from ..models import Game, Season, Week

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


# ---- the line straight off the pick sheet -------------------------------------
# The pick sheet carries the same note on its second row, written by hand:
# "(det by 8)", "(cincy by 8)", "(SF -3.5)". Anything without a number in it
# ("|", "TNF", "London") is not a line and says nothing.
SHEET_NOTE = re.compile(r"([A-Za-z0-9][A-Za-z0-9.']*)\s*(?:by|-)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
#: What a commissioner might write for a team that is neither its code nor its name.
NOTE_WORDS = {
    "cincy": "cin", "cinci": "cin", "philly": "phi", "jags": "jax", "pats": "ne",
    "bucs": "tb", "niners": "sf", "9ers": "sf", "wash": "was", "commies": "was",
    "skins": "was", "az": "ari", "zona": "ari", "cards": "ari", "hawks": "sea",
    "fins": "mia", "phins": "mia", "pack": "gb", "bolts": "lac", "vegas": "lv",
    "nyg": "nyg", "nyj": "nyj", "gmen": "nyg", "boys": "dal", "dawgs": "cle",
    "noles": "no", "aints": "no", "bengels": "cin", "steelers": "pit",
}


def _match(word: str, name: str) -> int:
    """How surely a word from a line note means the team a slate name is:
    2 for its code or a name for it ("hou", "jags"), 1 for the start of one
    ("cincy", "phil"), 0 for neither. Only the team's present names count:
    "hou" is Houston, never the Tennessee that was once the Houston Oilers."""
    from ..model.predictions import team_code
    code = team_code(name)
    if not code:
        return 0
    w = re.sub(r"[.']", "", word.casefold())
    if not w:
        return 0
    if NOTE_WORDS.get(w) == code or team_code(w) == code:
        return 2
    former = FORMER_NAMES.get(code, ())
    spellings = tuple(s for s in TEAMS.get(code, ()) if s not in former) + (code,)
    if len(w) >= 3 and any(s.startswith(w) or any(part.startswith(w) for part in s.split()) for s in spellings):
        return 1
    # "cincy", "philly": the code and then more
    return 1 if len(code) == 3 and len(w) > 3 and w.startswith(code) else 0


def line_from_note(note: object, away: str, home: str) -> tuple[tuple[str, float] | None, str]:
    """((favourite as the slate writes it, points), problem) from a sheet's note.

    No line and no problem for a note that holds no number. A note with a
    number that names neither team (or both) comes back as a problem to show,
    never as a guess - a line on the wrong side would credit the wrong team.
    """
    text = str(note or "").strip()
    if not re.search(r"\d", text):
        return None, ""
    found = SHEET_NOTE.search(text)
    if not found:
        return None, f"can't read the line {text!r}"
    word, points = found.group(1), float(found.group(2))
    home_hit, away_hit = _match(word, home), _match(word, away)
    if home_hit == away_hit:
        return None, f"{text!r} doesn't say which of {away} and {home} is the favourite"
    return ((home if home_hit > away_hit else away), points), ""


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
    #: When it was typed (seconds since 1970). 0 for one kept before that was
    #: recorded; None for a number on screen that hasn't been kept yet.
    at: float | None = None


def _game_key(game: Game) -> str:
    """Identifies the matchup, so a spread never follows a game that changed."""
    return f"{_norm(game.away)}@{_norm(game.home)}"


def _same_game(match: object, game: Game) -> bool:
    """Whether a kept "away@home" is this game, whichever way round."""
    from ..model.predictions import team_code
    away, _, home = str(match or "").partition("@")
    a, h = team_code(away), team_code(home)
    return bool(a and h) and {a, h} == {team_code(game.away), team_code(game.home)}


def load_spreads(week: int, games: list[Game]) -> dict[int, Spread]:
    """The spreads typed in for a week's games. Each is found again by its
    two teams, so it stays with its game when the week is numbered again (a
    week set up from the fixtures gets the commissioner's order once his
    sheet arrives) or has home and away the other way round."""
    from .. import store
    from ..model.predictions import team_code
    saved = store.get("spreads", str(week), {})
    if not isinstance(saved, dict):
        return {}
    where = {}
    for game in games:
        a, h = team_code(game.away), team_code(game.home)
        if a and h:
            where[frozenset((a, h))] = (game, a)
    out = {}
    for index, entry in saved.items():
        if not (isinstance(entry, dict) and entry.get("favourite") in ("home", "away")
                and isinstance(entry.get("points"), (int, float))):
            continue
        away, _, home = str(entry.get("match", "")).partition("@")
        a, h = team_code(away), team_code(home)
        found = where.get(frozenset((a, h))) if a and h else None
        if found is None:
            # kept before teams could be read from it: only its own game
            game = next((g for g in games if str(g.index) == str(index)), None)
            if game is None or entry.get("match") != _game_key(game):
                continue
            found = (game, team_code(game.away))
        game, game_away = found
        side = entry["favourite"]
        if a and game_away != a:
            side = "home" if side == "away" else "away"
        out[game.index] = Spread(side, float(entry["points"]), float(entry.get("at") or 0.0))
    return out


def save_spread(week: int, game: Game, spread: Spread | None) -> None:
    """Store or clear one game's spread, leaving every other entry alone."""
    from .. import store
    week_entries = dict(store.get("spreads", str(week), {}) or {})
    # the game's own entry, whatever number it was kept under
    for index, entry in list(week_entries.items()):
        if isinstance(entry, dict) and _same_game(entry.get("match"), game):
            week_entries.pop(index)
    if spread is None:
        week_entries.pop(str(game.index), None)
    else:
        import time
        week_entries[str(game.index)] = {
            "match": _game_key(game), "favourite": spread.favourite, "points": spread.points,
            "at": time.time(),
        }
    try:
        if week_entries:
            store.put("spreads", str(week), week_entries)
        else:
            store.delete("spreads", str(week))
    except store.StoreError:
        pass


# ---- the pool's line games, typed in on the Next Week page ------------------
#: Store kind: the week's line games as the dashboard was told them, by
#: "YEAR-WEEK", for the days before the commissioner's pick sheet says them.
POOL_KIND = "pool-lines"
#: "(kc by 10)", "Chiefs -10", "Green Bay by 3.5" - a team, then the points.
POOL_LINE = re.compile(r"^\W*(.+?)\s*(?:\bby\b|-)\s*(\d+(?:\.\d+)?)\W*$", re.IGNORECASE)


def _pair(away: object, home: object) -> frozenset:
    from ..model.predictions import team_code
    return frozenset((team_code(away), team_code(home)))


def pool_lines(year: int, week: int) -> dict[frozenset, tuple[str, float]]:
    """{the two teams' codes: (favourite's code, points)} as typed in."""
    from .. import store
    try:
        raw = store.get(POOL_KIND, f"{year}-{week}", [])
    except store.StoreError:
        return {}
    out = {}
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        teams, fav, points = row.get("teams"), row.get("favourite"), row.get("points")
        if (isinstance(teams, list) and len(teams) == 2 and fav in teams
                and isinstance(points, (int, float)) and points > 0):
            out[frozenset(teams)] = (str(fav), float(points))
    return out


def save_pool_lines(year: int, week: int, found: dict[frozenset, tuple[str, float]]) -> None:
    """Keep the week's line games - all of them: what isn't listed is straight up."""
    from .. import store
    rows = [{"teams": sorted(pair), "favourite": fav, "points": points}
            for pair, (fav, points) in sorted(found.items(), key=lambda kv: sorted(kv[0]))]
    if rows:
        store.put(POOL_KIND, f"{year}-{week}", rows)
    else:
        store.delete(POOL_KIND, f"{year}-{week}")


def pool_line_weeks(year: int) -> list[int]:
    """The weeks of a season with line games typed in."""
    from .. import store
    try:
        keys = store.items(POOL_KIND)
    except store.StoreError:
        return []
    out = []
    for key in keys:
        found = re.fullmatch(r"(\d{4})-(\d{1,2})", str(key))
        if found and int(found.group(1)) == int(year):
            out.append(int(found.group(2)))
    return sorted(out)


def _team_in(phrase: str, games: list[Game]) -> tuple[Game | None, str, str]:
    """(the game, the team as the slate writes it, a problem) for the words in
    front of a line: a code, a name, a nickname, or the start of one."""
    from ..model.predictions import team_code
    words = phrase.strip(" ()[]:,.")
    code = team_code(words) or NOTE_WORDS.get(re.sub(r"[.']", "", words.casefold()), "")
    hits = []
    for game in games:
        for side in (game.away, game.home):
            if code and team_code(side) == code:
                hits.append((2, game, side))
            elif not code:
                strength = max((_match(word, side) for word in words.split()), default=0)
                if strength:
                    hits.append((strength, game, side))
    if not hits:
        return None, "", (f"{words!r} isn't playing this week" if code
                          else f"can't tell which team {words!r} is")
    best = max(h[0] for h in hits)
    top = [h for h in hits if h[0] == best]
    if len({team_code(h[2]) for h in top}) > 1:
        return None, "", f"{words!r} could be {' or '.join(sorted({h[2] for h in top}))}"
    return top[0][1], top[0][2], ""


def parse_pool_lines(text: str, games: list[Game]) -> tuple[dict[frozenset, tuple[str, float]], list[str]]:
    """The week's line games from typed or pasted text, one a line (or split
    by commas): "(kc by 10)", "Chiefs -10", "Green Bay by 3.5". Returns
    ({pair: (favourite code, points)}, what couldn't be read)."""
    from ..model.predictions import team_code
    found: dict[frozenset, tuple[str, float]] = {}
    problems: list[str] = []
    for chunk in re.split(r"[\n;,]+", text or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = POOL_LINE.match(chunk)
        if not match:
            problems.append(f"can't read {chunk!r} - write it like (kc by 10)")
            continue
        game, side, problem = _team_in(match.group(1), games)
        if game is None:
            problems.append(problem)
            continue
        points = float(match.group(2))
        if not 0 < points <= 40:
            problems.append(f"{chunk!r}: {points:g} points isn't a line")
            continue
        found[_pair(game.away, game.home)] = (team_code(side), points)
    return found, problems


def pool_lines_text(year: int, week: int) -> str:
    """The week's line games as the sheet writes them, one a line."""
    return "\n".join(f"({fav} by {points:g})" for fav, points in
                     sorted(pool_lines(year, week).values()))


def apply_pool_lines(week: Week, typed: dict[frozenset, tuple[str, float]]) -> None:
    """Put typed line games on a week's games, and take the line off any game
    not among them: the list is the whole week's."""
    from ..model.predictions import team_code
    for game in week.games:
        found = typed.get(_pair(game.away, game.home))
        if found is None:
            game.line, game.line_favourite = None, ""
            continue
        fav, points = found
        game.line_favourite = game.home if team_code(game.home) == fav else game.away
        game.line = points


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
