"""Parser for the weekly stats.xls standings export.

Layout of the "stats" sheet, established by inspecting the real exports:

    row 0  col 5   season title, e.g. "ACQL 2026"
    row 2  col 5   "Week N" - the week this snapshot covers
    row 2  col 31  max regular points      col 32  max big-loser points
    row 3  col 30  "Week-->" then week numbers at cols 31, 33, 35, ...
    row 4          column headers
    rows 5..39     one row per player
    row 42         "Big Losers week N" followed by that week's big-loser teams

The sheet is really several independently sorted tables side by side, so each
block is keyed by its own coach column rather than by row position:

    cols 0-13   main standings      (keyed by col 1)
    cols 15-17  big loser pool      (keyed by col 15)
    col  18     suicide pool survivors
    cols 25-29  rank movement/trend (aligned with col 1)
    cols 30+    per-week R/BL grid  (keyed by col 30)
"""

from __future__ import annotations

import re
from ..config import WEEKS_IN_SEASON
from ..models import Player, SourceFile
from ..names import AliasTable

# Main standings block.
C_POS, C_COACH, C_W, C_L, C_PCT, C_GB = 0, 1, 2, 3, 4, 5
C_NEG_PTS, C_POS_PTS, C_NET_PTS, C_CUR_WK_WINS = 6, 7, 8, 9
C_LINE_GAMES = 13
# Side pools.
C_BL_COACH, C_BL_POINTS = 15, 17
C_SUICIDE_COACH = 18
# Movement/trend block.
C_PREV_POS, C_CUR_POS, C_3WK, C_TOTAL_WINS = 25, 26, 27, 28
# Weekly grid.
C_GRID_COACH, C_GRID_FIRST = 30, 31

HEADER_ROW = 4
FIRST_DATA_ROW = 5
BIG_LOSER_ROW_TEXT = re.compile(r"big\s+losers?\s+week\s*(\d+)", re.IGNORECASE)


def _num(value: object) -> float | None:
    """Coerce a cell to a number, treating blanks and placeholders as unknown."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _int(value: object) -> int | None:
    n = _num(value)
    return int(round(n)) if n is not None else None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_stats(
    source: SourceFile,
    aliases: AliasTable,
    players: dict[str, Player] | None = None,
) -> dict:
    """Read one stats.xls snapshot.

    Returns a dict with the players it found plus the snapshot's metadata.
    `players` is updated in place when given, so several weekly snapshots can
    be layered to rebuild a season's history.
    """
    import xlrd

    result: dict = {
        "players": players if players is not None else {},
        "week": source.week,
        "season": source.season,
        "max_regular": 16,
        "max_big_loser": 3,
        "big_losers": {},
        "warnings": [],
    }
    people: dict[str, Player] = result["players"]

    book = xlrd.open_workbook(str(source.path))
    names = book.sheet_names()
    sheet = book.sheet_by_name("stats") if "stats" in names else book.sheet_by_index(0)

    def cell(r: int, c: int) -> object:
        if 0 <= r < sheet.nrows and 0 <= c < sheet.ncols:
            return sheet.cell_value(r, c)
        return None

    week = source.week
    max_regular = _int(cell(2, C_GRID_FIRST)) or 16
    max_big_loser = _int(cell(2, C_GRID_FIRST + 1)) or 3
    result["max_regular"] = max_regular
    result["max_big_loser"] = max_big_loser

    def player_for(raw: object) -> Player | None:
        display = _text(raw)
        if not display or display.lower() in {"coach", "pos", "total"}:
            return None
        key = aliases.key(display)
        if not key:
            return None
        person = people.get(key)
        if person is None:
            person = Player(key=key, display=display)
            people[key] = person
        elif len(display) > len(person.display):
            # Prefer the fuller spelling for display purposes.
            person.display = display
        person.sources.add(source.path.name)
        return person

    # Map the weekly R/BL grid columns to week numbers from the header row.
    grid_columns: dict[int, int] = {}
    for c in range(C_GRID_FIRST, min(sheet.ncols, C_GRID_FIRST + WEEKS_IN_SEASON * 2)):
        n = _int(cell(3, c))
        if n and 1 <= n <= WEEKS_IN_SEASON:
            grid_columns[n] = c

    last_row = min(sheet.nrows, 200)
    alive_this_snapshot: set[str] = set()
    for r in range(FIRST_DATA_ROW, last_row):
        # --- the trailing big-loser teams row --------------------------------
        # Checked first: it occupies the coach column and must not be mistaken
        # for a player.
        label = _text(cell(r, C_COACH))
        m = BIG_LOSER_ROW_TEXT.search(label) if label else None
        if m:
            wk = int(m.group(1))
            teams = [
                _text(cell(r, c))
                for c in range(C_W, min(sheet.ncols, C_W + 12))
                if _text(cell(r, c))
            ]
            if teams:
                result["big_losers"][wk] = teams
            continue

        # --- main standings ------------------------------------------------
        person = player_for(cell(r, C_COACH))
        if person is not None:
            pos = _int(cell(r, C_POS))
            if pos is not None:
                person.pos = pos
            for attr, col, conv in (
                ("wins", C_W, _int),
                ("losses", C_L, _int),
                ("pct", C_PCT, _num),
                ("games_behind", C_GB, _num),
                ("net_points", C_NET_PTS, _num),
                ("points_won", C_POS_PTS, _num),
                ("points_paid", C_NEG_PTS, _num),
                ("current_week_wins", C_CUR_WK_WINS, _int),
                ("line_game_pct", C_LINE_GAMES, _num),
            ):
                value = conv(cell(r, col))
                if value is not None:
                    setattr(person, attr, value)

            prev_pos = _int(cell(r, C_PREV_POS))
            if prev_pos is not None:
                person.prev_pos = prev_pos
            cur_pos = _int(cell(r, C_CUR_POS))
            if cur_pos is not None:
                person.pos = cur_pos
            three = _int(cell(r, C_3WK))
            if three is not None:
                person.three_week_wins = three

        # --- big loser pool -------------------------------------------------
        bl_person = player_for(cell(r, C_BL_COACH))
        if bl_person is not None:
            points = _num(cell(r, C_BL_POINTS))
            if points is not None:
                bl_person.big_loser_points = points

        # --- suicide pool ---------------------------------------------------
        suicide = player_for(cell(r, C_SUICIDE_COACH))
        if suicide is not None:
            # Presence in this column means still alive at this snapshot.
            alive_this_snapshot.add(suicide.key)

        # --- per-week R/BL grid ---------------------------------------------
        grid_person = player_for(cell(r, C_GRID_COACH))
        if grid_person is not None:
            for wk, col in grid_columns.items():
                regular = _int(cell(r, col))
                big_loser = _int(cell(r, col + 1))
                if regular is None and big_loser is None:
                    continue
                regular = regular or 0
                big_loser = big_loser or 0
                grid_person.weekly_regular[wk] = regular
                grid_person.weekly_big_loser[wk] = big_loser
                grid_person.weekly_wins[wk] = regular + big_loser

    # Survivor status reflects the newest snapshot only: a player eliminated
    # later must not stay alive because an earlier file listed them.
    for key, person in people.items():
        person.suicide_alive = key in alive_this_snapshot

    if week is None and people:
        # No explicit "Week N": infer from the furthest week carrying results.
        played = [w for p in people.values() for w in p.weekly_wins]
        week = max(played) if played else None
        result["week"] = week

    if not people:
        result["warnings"].append(
            f"{source.path.name}: no player rows recognised - the layout may have changed."
        )
    return result
