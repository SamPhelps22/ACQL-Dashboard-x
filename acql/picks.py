"""The pool's raw pick sheet - everyone's picks for a week, before grading.

This is the file the commissioner publishes each week and that gets pasted
into the workbook: a column per game, a row per coach, and at the end each
coach's three Big Loser picks and their Suicide pick. The sheet it comes on
looks like this:

    row 1                         ACQL WEEK 2 ...
    row 2                         (phi by 8)          the pool's line
    row 3   cleveland             new orleans         the road team
    row 5   TAMPA BAY             BALTIMORE           the home team
    row 7+  Phelpy   TAMPA BAY    BALTIMORE  ...      one row a coach

Nothing here grades anything. What it is for is the one number that cannot
be worked out from anywhere else: how much of the pool is on each side. A
pick that is right and popular wins nothing; the whole of the gain on the
field is in being right where the others are wrong, and until this file is
loaded that share has to be estimated from a curve.

The week is read from the sheet's own title rather than the file name,
because the files are numbered by something other than the week.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import ROOT
from .models import Game, Player, PlayerWeek, Season, Week
from .predictions import DISPLAY, team_code

PICKS_FILE = ROOT / "acql-picks.json"
# Marks a player as known only from a raw pick sheet, so a later workbook
# load can be told apart from this one and left in charge of the standings.
SHEET_SOURCE = "pick sheet: "

FIRST_PLAYER_ROW = 7
AWAY_ROW, HOME_ROW, NOTE_ROW = 3, 5, 2
TITLE = re.compile(r"WEEK\s*(\d+)", re.IGNORECASE)
LOSER_HEADER = re.compile(r"LOSER\s*(\d)", re.IGNORECASE)
SUICIDE_HEADER = re.compile(r"SUICIDE", re.IGNORECASE)
# Rows at the bottom that summarise rather than pick.
SUMMARY_ROW = re.compile(r"^\s*(picked|total|average|avg)\b", re.IGNORECASE)


class Unreadable(Exception):
    """The file could not be opened at all - the message says what to do."""


def _grid(path: str | Path) -> list[list[str]]:
    """The sheet as rows of strings, from either .xlsx or an older .xls.

    openpyxl reads the modern format; the old one needs xlrd, which is not
    always installed. Saying so plainly beats a traceback about magic bytes.
    """
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError as problem:            # pragma: no cover
            raise Unreadable("openpyxl isn't installed, so no spreadsheet can be read") from problem
        book = openpyxl.load_workbook(path, data_only=True)
        sheet = book["picks"] if "picks" in book.sheetnames else book.worksheets[0]
        return [
            ["" if cell.value is None else str(cell.value).strip() for cell in row]
            for row in sheet.iter_rows()
        ]
    try:
        import xlrd
    except ImportError as problem:
        raise Unreadable(
            f"{path.name} is in the old .xls format, which needs the xlrd package. "
            f"Either run \"pip install xlrd\", or open the file and save it again "
            f"as .xlsx - both work."
        ) from problem
    book = xlrd.open_workbook(path)
    names = book.sheet_names()
    sheet = book.sheet_by_name("picks" if "picks" in names else names[0])
    return [
        [str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]
        for r in range(sheet.nrows)
    ]


def _cell(rows: list[list[str]], row: int, col: int) -> str:
    """1-based, and off the end of the sheet is simply empty."""
    if 1 <= row <= len(rows) and 1 <= col <= len(rows[row - 1]):
        return rows[row - 1][col - 1]
    return ""


@dataclass(frozen=True)
class GamePicks:
    """One game, and who took which side."""

    away: str
    home: str
    note: str                       # the pool's line, as written on the sheet
    picks: dict[str, str] = field(default_factory=dict)     # coach -> team picked

    @property
    def counted(self) -> int:
        return sum(1 for team in self.picks.values() if team_code(team))

    def share_on(self, team: str) -> float | None:
        """The fraction of the pool that took this team, or None if nobody did."""
        wanted = team_code(team)
        if not wanted or not self.counted:
            return None
        return sum(
            1 for pick in self.picks.values() if team_code(pick) == wanted
        ) / self.counted


@dataclass(frozen=True)
class WeekPicks:
    """Everyone's card for one week."""

    week: int
    games: list[GamePicks] = field(default_factory=list)
    losers: dict[str, list[str]] = field(default_factory=dict)    # coach -> 3 teams
    suicide: dict[str, str] = field(default_factory=dict)         # coach -> team
    source: str = ""

    @property
    def coaches(self) -> list[str]:
        names = {name for game in self.games for name in game.picks}
        return sorted(names | set(self.losers) | set(self.suicide))

    def game_for(self, away: str, home: str) -> GamePicks | None:
        """The sheet's row for a matchup, whichever way round it is written."""
        want = {team_code(away), team_code(home)}
        if "" in want or len(want) != 2:
            return None
        for game in self.games:
            if {team_code(game.away), team_code(game.home)} == want:
                return game
        return None

    def loser_counts(self) -> list[tuple[str, int]]:
        """How many coaches took each Big Loser, most popular first."""
        tally = Counter(
            team_code(team) for picks in self.losers.values() for team in picks
            if team_code(team)
        )
        return tally.most_common()

    def loser_share(self, team: str) -> float:
        """The fraction of coaches with this team among their three."""
        wanted = team_code(team)
        if not wanted or not self.losers:
            return 0.0
        return sum(
            1 for picks in self.losers.values()
            if any(team_code(t) == wanted for t in picks)
        ) / len(self.losers)


def chalk(week: WeekPicks) -> dict[str, float]:
    """How much each coach went with the crowd, 0..1, over one week.

    A coach's figure is the average share of the pool that was on the same
    side as them, game by game. Around 0.8 is this pool's habit; well under
    it is a coach who takes unpopular sides, which is the only way anyone
    finishes a week clear of the field.
    """
    totals: dict[str, list[float]] = {}
    for game in week.games:
        # Each pick is resolved to a team once, and the sides counted once.
        # Asking the game for `share_on` per coach re-counted every card for
        # every coach - thirty-five times the work, times sixteen games,
        # times a team lookup on each - which is what made the pages that
        # read this crawl.
        codes = {coach: team_code(team) for coach, team in game.picks.items()}
        tally = Counter(code for code in codes.values() if code)
        counted = sum(tally.values())
        if not counted:
            continue
        for coach, code in codes.items():
            if code:
                totals.setdefault(coach, []).append(tally[code] / counted)
    return {
        coach: sum(shares) / len(shares)
        for coach, shares in totals.items() if shares
    }


def load_all() -> dict[int, WeekPicks]:
    """Every stored week, reading the file once."""
    out: dict[int, WeekPicks] = {}
    for key in _read_store():
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        sheet = load(number)
        if sheet is not None:
            out[number] = sheet
    return out


def read_file(path: str | Path) -> WeekPicks:
    """Parse a pick sheet. Raises Unreadable if it isn't one."""
    rows = _grid(path)
    if not rows:
        raise Unreadable(f"{Path(path).name} has nothing in it")

    found = TITLE.search(" ".join(rows[0]))
    if not found:
        raise Unreadable(
            f"{Path(path).name} doesn't say which week it is - the top row of a "
            f"pick sheet reads something like \"ACQL WEEK 2\""
        )
    week = int(found.group(1))

    width = max(len(row) for row in rows)
    losers: dict[int, int] = {}          # column -> which of the three
    suicide_col = 0
    games: list[tuple[int, str, str, str]] = []
    for col in range(1, width + 1):
        header = _cell(rows, HOME_ROW, col)
        if LOSER_HEADER.search(header):
            losers[col] = int(LOSER_HEADER.search(header).group(1))
            continue
        if SUICIDE_HEADER.search(header):
            suicide_col = col
            continue
        away = _cell(rows, AWAY_ROW, col)
        if away and header and team_code(away) and team_code(header):
            games.append((col, away, header, _cell(rows, NOTE_ROW, col)))
    if not games:
        raise Unreadable(
            f"{Path(path).name} has no games in it - a pick sheet has the road "
            f"team on row {AWAY_ROW} and the home team on row {HOME_ROW}"
        )

    picks: dict[int, dict[str, str]] = {col: {} for col, *_ in games}
    loser_picks: dict[str, list[str]] = {}
    suicide: dict[str, str] = {}
    for number in range(FIRST_PLAYER_ROW, len(rows) + 1):
        name = _cell(rows, number, 1)
        if not name or SUMMARY_ROW.match(name):
            continue
        # A coach is a row with picks on it. Separators, notes and whatever
        # else is typed down the left-hand column are not coaches, and
        # counting them makes every share in the pool come out too small.
        chosen = {col: _cell(rows, number, col) for col, *_ in games}
        if not any(team_code(team) for team in chosen.values()):
            continue
        for col, team in chosen.items():
            if team:
                picks[col][name] = team
        losing = [_cell(rows, number, col) for col in sorted(losers, key=losers.get)]
        if any(losing):
            loser_picks[name] = losing
        if suicide_col:
            pick = _cell(rows, number, suicide_col)
            if pick:
                suicide[name] = pick

    return WeekPicks(
        week=week,
        games=[GamePicks(away, home, note, picks[col]) for col, away, home, note in games],
        losers=loser_picks,
        suicide=suicide,
        source=str(path),
    )


def summary(week: WeekPicks) -> str:
    """One line about a sheet, for the page to show."""
    alive = sum(1 for pick in week.suicide.values() if team_code(pick))
    parts = [_plural(len(week.coaches), "coach", "coaches")]
    if week.losers:
        parts.append(f"{len(week.losers)} big-loser cards")
    if week.suicide:
        parts.append(f"{alive} alive in the suicide pool")
    return " \u00b7 ".join(parts)


def _plural(count: int, word: str, many: str = "") -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"


# ---- grading a week from the raw sheet --------------------------------------
@dataclass(frozen=True)
class Graded:
    """What attaching the pick sheets did to a season."""

    built: list[int] = field(default_factory=list)       # weeks created from a sheet
    filled: list[int] = field(default_factory=list)      # weeks whose picks were filled in
    checked: list[int] = field(default_factory=list)     # weeks compared against the sheet
    disagreements: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def touched(self) -> list[int]:
        return sorted(set(self.built) | set(self.filled) | set(self.checked))


def _decided(game: Game) -> bool:
    return bool(str(getattr(game, "winner", "") or "").strip())


def grade_week(week: Week, sheet: WeekPicks) -> dict[str, int]:
    """Each coach's correct picks for a week, from the raw sheet and the results.

    The workbook records the winner with the pool's line already applied, so
    grading against it needs no knowledge of the line - a pick is right when
    it names the team in the result row.
    """
    scores: dict[str, int] = {}
    for game in week.games:
        if not _decided(game):
            continue
        found = sheet.game_for(game.away, game.home)
        if found is None:
            continue
        winner = team_code(game.winner)
        for coach, team in found.picks.items():
            scores[coach] = scores.get(coach, 0) + (team_code(team) == winner)
    return scores


def _sync_players(season: Season, week: Week, source: str) -> None:
    """Give the season a coach for every name on a week it took from a sheet.

    Scoring a week fills `week.lines`, which is what the weekly pages read.
    Everything else in the dashboard - standings, form, head to head, the
    crowd chart - reads `season.players`, so without this a season loaded
    from pick sheets alone knows all 35 cards and none of the 35 coaches.

    Only weeks the sheet built or filled come through here, so nothing the
    workbook entered is ever written over.

    A week with no results yet is deliberately left out of everyone's record.
    Grading an unplayed week gives all 35 coaches nought, and nought is not a
    score - carried into the season it would drag every average down and put
    the whole pool level at the bottom of the standings.
    """
    scored = any(_decided(game) for game in week.games)
    tag = f"{SHEET_SOURCE}{source or 'pick sheet'}"
    for key, line in week.lines.items():
        person = season.players.get(key)
        if person is None:
            person = Player(key=key, display=line.player or key)
            season.players[key] = person
        person.sources.add(tag)
        if not scored:
            continue
        person.weekly_wins[week.number] = line.total_wins
        person.weekly_regular[week.number] = line.regular_wins
        if line.suicide_pick:
            person.suicide_picks[week.number] = line.suicide_pick


def sheet_only(season: Season) -> set[str]:
    """Coaches who exist because a pick sheet was loaded, and nowhere else.

    Ownership has to be read off the player rather than remembered, because
    sheets are attached again every time one is added or a result arrives.
    A coach the workbook has touched carries that file's name among their
    sources, and from then on their record is the workbook's to keep.
    """
    return {
        key for key, person in season.players.items()
        if person.sources and all(s.startswith(SHEET_SOURCE) for s in person.sources)
    }


def _rank_players(season: Season, ours: set[str]) -> None:
    """Standings for coaches the workbook has never seen.

    `wins`, `pos` and the rest are normally read straight out of stats.xls,
    which is authoritative and stays that way: a coach the workbook knows is
    left exactly as the workbook left them. A coach who exists only because
    a pick sheet was loaded has no such row, so their record is added up from
    the weeks that are scored - and positions are only handed out when the
    workbook has given out none, so the two numbering systems never mix.
    """
    if not ours:
        return
    games = {w: len(wk.games) for w, wk in season.weeks.items()}
    for key in ours:
        person = season.players.get(key)
        if person is None:
            continue
        played = sum(games.get(w, 0) for w in person.weekly_wins)
        person.wins = person.season_wins
        person.losses = max(0, played - person.wins)
        person.pct = person.wins / played if played else 0.0
    if any(p.pos for p in season.players.values() if p.key not in ours):
        return            # the workbook is running the standings; leave them be
    order = sorted(season.players.values(), key=lambda p: (-p.wins, p.display))
    for place, person in enumerate(order, start=1):
        person.pos = place


def _plain(name: str) -> str:
    """A coach's name reduced to what cannot vary between files.

    Case, spacing and punctuation are exactly what differs between a pick
    sheet and the workbook - "Jim T" against "JimT" - so none of them decide
    who somebody is.
    """
    return "".join(c for c in str(name).casefold() if c.isalnum())


def _coach_key(season: Season, key_for=None):
    """How to file a coach from a pick sheet so they land on their own row.

    The workbook keys coaches through the alias table, and the pool spells
    names differently between the two files - "MayeDay! MayeDay!" on the pick
    sheet against whatever the workbook has. Filing a sheet under a key of its
    own would give that coach two rows: half their weeks under each, and every
    pool-wide average taken over a pool twice its real size.

    So an existing coach is matched first, by name with case, spacing and
    punctuation set aside. Only a coach nobody has seen before gets a new key,
    and that key comes from the same alias table the workbook uses whenever
    one is to hand.

    Once the pool has a roster, a name that matches nobody on it is not one of
    the pool's coaches and comes back empty. Pick sheets are downloaded a file
    at a time and they are not all this pool's: a folder of them brought in
    two dozen strangers - Blitzburgh, Frosted Flaccos, Mac Daddy Jones - each
    filed as a coach on no wins, and thirty-five became fifty-nine. The
    workbook says who is in the pool; a sheet only says what they picked.
    """
    known = {_plain(person.display): key for key, person in season.players.items()}
    roster = bool(known)

    def resolve(coach: str) -> str:
        plain = _plain(coach)
        if plain in known:
            return known[plain]
        if roster:
            return ""                # not one of ours
        if key_for is not None:
            try:
                made = key_for(coach)
            except Exception:                    # noqa: BLE001 - never fail a load
                made = ""
            if made:
                known[plain] = made
                return made
        known[plain] = plain
        return plain

    return resolve


def attach(
    season: Season,
    sheets: dict[int, WeekPicks] | None = None,
    *,
    key_for=None,
) -> Graded:
    """Put the pool's raw pick sheets into a season, without overwriting it.

    Three things happen, and only ever these three:

    * A week the workbook has nothing for is built from the sheet - the
      slate, everyone's picks, and their scores against whatever results
      are known. That is the week you no longer have to paste in by hand.
    * A week the workbook has, but with no coaches on it, has them filled in.
    * A week the workbook has already scored is left exactly as it is, and
      the sheet is used to check it. Anywhere the two disagree is reported
      rather than corrected, because the workbook is what the pool settles
      on and a difference is worth looking at by eye.

    Big-loser points are not computed: a big loser has to lose by more than
    14 and the workbook records who won, not by how much.
    """
    out = Graded()
    key_of = _coach_key(season, key_for)
    for number, sheet in sorted((sheets or load_all()).items()):
        week = season.weeks.get(number)
        fresh = week is None
        if fresh:
            week = Week(number=number)
            season.weeks[number] = week
        if not week.games:
            week.games = [
                Game(index=index, home=game.home, away=game.away)
                for index, game in enumerate(sheet.games, start=1)
            ]
            out.notes.append(
                f"week {number}: the slate came from {Path(sheet.source).name or 'a pick sheet'}"
            )
        scores = grade_week(week, sheet)
        # A week that came from a pick sheet rather than the workbook is
        # re-graded every time, so results arriving later are picked up. A
        # week the workbook owns is never touched.
        from_workbook = getattr(week, "source", None) is not None
        if not week.lines or not from_workbook:
            week.lines.clear()
            outsiders = 0
            for coach in sheet.coaches:
                key = key_of(coach)
                if not key:
                    # On this sheet but not in this pool. Their picks still
                    # count towards what the crowd did - that is read from the
                    # sheet itself - but they are not given a coach's row.
                    outsiders += 1
                    continue
                line = PlayerWeek(player=coach, week=number)
                line.suicide_pick = sheet.suicide.get(coach, "")
                line.big_loser_picks = [t for t in sheet.losers.get(coach, []) if t]
                for game in week.games:
                    found = sheet.game_for(game.away, game.home)
                    if found is None:
                        continue
                    team = found.picks.get(coach, "")
                    if team and _decided(game) and team_code(team) == team_code(game.winner):
                        line.correct_picks[game.index] = team
                line.regular_wins = line.total_wins = scores.get(coach, 0)
                week.lines[key] = line
            _sync_players(season, week, Path(sheet.source).name)
            if outsiders:
                one = outsiders == 1
                out.notes.append(
                    f"week {number}: {outsiders} name{'' if one else 's'} on "
                    f"{Path(sheet.source).name or 'the sheet'} "
                    f"{'is' if one else 'are'} not in this pool and "
                    f"{'was' if one else 'were'} left out of the standings"
                )
            (out.built if fresh else out.filled).append(number)
            continue

        out.checked.append(number)
        # The comparison is done game by game rather than player by player.
        # One wrong cell in the result row makes every single coach's total
        # disagree, which as a list of thirty-five names says nothing; as one
        # line naming the game, it says exactly what to go and fix.
        for game in week.games:
            if not _decided(game):
                continue
            kept = Counter(
                team_code(line.correct_picks[game.index])
                for line in week.lines.values()
                if game.index in line.correct_picks
                and team_code(line.correct_picks[game.index])
            )
            if not kept:
                continue
            winner = team_code(game.winner)
            if winner in kept:
                continue
            # Every pick the commissioner kept names a team other than the
            # one in the result row: the two disagree about who won.
            named, held = kept.most_common(1)[0]
            out.disagreements.append(
                f"week {number} game {game.index} ({game.away} @ {game.home}): "
                f"the result row says {game.winner}, but all {held} picks left "
                f"standing name {DISPLAY.get(named, named)} - one of the two is wrong"
            )
    _rank_players(season, sheet_only(season))
    return out


# ---- keeping them between runs ---------------------------------------------
# The parsed store, kept between calls. Pages ask for the pick sheets on
# every refresh - the standings table reads them for its chalk column, the
# insights page for two of its cards - and each of those calls was re-reading
# and re-parsing the whole file, once for the index and once more per week.
# The file only changes when this module writes it, so it is read when its
# timestamp moves and not otherwise.
_STORE: dict | None = None
_STORE_STAMP: tuple[float, int] | None = None


def _store_stamp() -> tuple[float, int] | None:
    try:
        info = PICKS_FILE.stat()
    except OSError:
        return None
    return (info.st_mtime, info.st_size)


def _read_store() -> dict:
    global _STORE, _STORE_STAMP
    stamp = _store_stamp()
    if _STORE is not None and stamp == _STORE_STAMP:
        return _STORE
    try:
        raw = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
        _STORE = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        _STORE = {}
    _STORE_STAMP = stamp
    return _STORE


def forget_store() -> None:
    """Drop the cache, for a test that points PICKS_FILE somewhere else."""
    global _STORE, _STORE_STAMP
    _STORE = _STORE_STAMP = None


def save(week: WeekPicks) -> None:
    # The cached copy is mutated and then written, so the two agree without
    # depending on the file's timestamp moving - which on a fast save, and on
    # a filesystem with coarse timestamps, it may not.
    store = dict(_read_store())
    store[str(week.week)] = {
        "source": week.source,
        "imported": time.time(),
        "games": [asdict(game) for game in week.games],
        "losers": week.losers,
        "suicide": week.suicide,
    }
    global _STORE, _STORE_STAMP
    try:
        PICKS_FILE.write_text(json.dumps(store, indent=1), encoding="utf-8")
    except OSError:
        pass
    _STORE, _STORE_STAMP = store, _store_stamp()


def load(week: int) -> WeekPicks | None:
    entry = _read_store().get(str(week))
    if not isinstance(entry, dict):
        return None
    games = []
    for row in entry.get("games", []):
        if isinstance(row, dict):
            games.append(GamePicks(
                away=str(row.get("away", "")), home=str(row.get("home", "")),
                note=str(row.get("note", "")), picks=dict(row.get("picks") or {}),
            ))
    if not games:
        return None
    return WeekPicks(
        week=week, games=games,
        losers={k: list(v) for k, v in (entry.get("losers") or {}).items()},
        suicide=dict(entry.get("suicide") or {}),
        source=str(entry.get("source", "")),
    )


def search_folders(workbook: str | Path | None = None) -> list[Path]:
    """Where a downloaded pick sheet is likely to be."""
    from .predictions import search_folders as folders
    return folders(workbook)


def find_files(workbook: str | Path | None = None) -> list[Path]:
    """Every pick sheet in the usual folders, newest first.

    The file name carries a number that is not the week, so the week has to
    be read out of each one; they are all offered and the caller sorts it out.
    """
    found: list[tuple[float, Path]] = []
    for folder in search_folders(workbook):
        for pattern in ("picks*.xls", "picks*.xlsx", "*picks*.xls", "*picks*.xlsx"):
            for path in folder.glob(pattern):
                try:
                    found.append((path.stat().st_mtime, path))
                except OSError:
                    continue
    seen, out = set(), []
    for _, path in sorted(found, reverse=True):
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def refresh_from_disk(workbook: str | Path | None = None) -> list[int]:
    """Read any pick sheet that isn't stored yet. Returns the weeks read."""
    store = _read_store()
    added = []
    for path in find_files(workbook):
        try:
            when = path.stat().st_mtime
        except OSError:
            continue
        # Skip a file that has already been read, unless it has changed.
        already = [
            entry for entry in store.values()
            if isinstance(entry, dict) and entry.get("source") == str(path)
            and float(entry.get("imported") or 0) >= when
        ]
        if already:
            continue
        try:
            week = read_file(path)
        except (Unreadable, OSError, ValueError):
            continue
        save(week)
        store = _read_store()
        added.append(week.week)
    return sorted(set(added))