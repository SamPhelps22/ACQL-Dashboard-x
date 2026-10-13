"""Hits and misses: where Deadeye's picks come good, and what each miss was.

A record says how often; it does not say where, or why. This takes every
graded game as Deadeye priced it going in (the same replay the Model Lab
runs) and asks three things:

  * Is the confidence earned? Picks sorted by how sure it was - lock,
    strong, lean, coin flip - against how often each kind came in, and how
    often its own chances said they should.
  * Where is it strongest? The same picks cut by situation: favourites and
    underdogs, home and road, the size of the line, division games, night
    games - each beside what the betting line alone did on those games.
  * What was each miss? A toss-up that fell the other way is not the same
    as a lock that was never close, and a miss the betting line shared is
    not the same as one Deadeye made by going against it.

Every row carries its number of games, and a row with few of them says so:
a 75% record over eight picks is luck until it is eighty. And a miss is one
game - its label says what kind of miss it was, never what caused it.

No Qt here.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .. import analytics
from . import evidence, luck, pricing
from ..feeds import results
from ..models import Game, Season, same_team
from .predictions import display_team, team_code

DIVISIONS = {
    "AFC East": ("buf", "mia", "ne", "nyj"), "AFC North": ("bal", "cin", "cle", "pit"),
    "AFC South": ("hou", "ind", "jax", "ten"), "AFC West": ("den", "kc", "lv", "lac"),
    "NFC East": ("dal", "nyg", "phi", "was"), "NFC North": ("chi", "det", "gb", "min"),
    "NFC South": ("atl", "car", "no", "tb"), "NFC West": ("ari", "lar", "sf", "sea"),
}
_DIVISION = {team: name for name, teams in DIVISIONS.items() for team in teams}

#: Picks a row needs before its record is worth reading.
ENOUGH = 20
#: Below this chance a pick was a toss-up, and losing it is no surprise.
COIN_FLIP = 0.55
#: A pick that lost by this many was never in the game.
NEVER_CLOSE = 17.0
#: How far (in standard deviations) a record has to sit from its own chances
#: before the confidence is called wrong.
OFF = 1.6
#: Kickoffs at these hours (UTC) are the night games: 7pm Eastern or later.
NIGHT_HOURS = (23, 0, 1, 2, 3)


@dataclass(frozen=True)
class Graded:
    """One graded game as Deadeye had it going in. Margins are from the pick's side."""

    week: int
    index: int
    matchup: str
    pick: str
    chance: float               # how likely Deadeye made the pick to be credited
    right: bool
    margin: float               # Deadeye's expected margin for the pick
    line: float | None = None   # the betting line for the pick (+ favoured, - getting points)
    line_pick: str = ""         # the side the betting line alone made likelier to be credited
    line_right: bool | None = None
    actual: float | None = None     # the final margin for the pick; None when no score was kept
    pool_line: float | None = None  # the pool's line, when the game had one
    pool_favourite: str = ""
    home_pick: bool = False
    divisional: bool = False
    night: bool | None = None

    @property
    def tier(self) -> str:
        return evidence.strength(self.chance)

    @property
    def with_line(self) -> bool | None:
        """Whether the pick was the betting line's side too (None: no line kept)."""
        return same_team(self.pick, self.line_pick) if self.line_pick else None

    @property
    def miss(self) -> float | None:
        """Points the result fell short of what was expected (negative: beat it)."""
        return None if self.actual is None else self.margin - self.actual


def same_division(home: str, away: str) -> bool:
    one, other = _DIVISION.get(team_code(home)), _DIVISION.get(team_code(away))
    return bool(one) and one == other


def at_night(kickoff: float) -> bool:
    return time.gmtime(kickoff).tm_hour in NIGHT_HOURS


def _actual(game: Game, scores) -> tuple[float | None, float | None]:
    """(final home margin, kickoff) for a slate's game, as far as either is known."""
    score, flipped = results.find(scores, game.away, game.home)
    kickoff = getattr(score, "kickoff", None) if score is not None else None
    if game.home_points is not None and game.away_points is not None:
        return float(game.home_points - game.away_points), kickoff
    if score is not None and score.final and score.home_points is not None and score.away_points is not None:
        margin = float(score.home_points - score.away_points)
        return (-margin if flipped else margin), kickoff
    return None, kickoff


KIND = "autopsy"


def _key(year: int, week: int) -> str:
    return f"{int(year)}-{int(week)}"


def kept(year: int, week: int) -> list[Graded] | None:
    """A week's games as they were written down when it finished, or None."""
    try:
        from .. import store
        found = store.get(KIND, _key(year, week), None)
        rows = found.get("games") if isinstance(found, dict) else None
        if not rows:
            return None
        names = set(Graded.__dataclass_fields__)
        return [Graded(**{k: v for k, v in row.items() if k in names}) for row in rows]
    except Exception:  # noqa: BLE001 - nothing kept is nothing kept
        return None


def keep(season: Season) -> list[int]:
    """Write down every finished week not written down yet - each game as Deadeye
    had it, and how it came out - so that nothing learned later can rewrite it.
    The scheduled job does this each night; so does opening the page. Returns
    the weeks newly kept."""
    from dataclasses import asdict
    from .. import store
    from ..version import VERSION
    year = results.season_year(season)
    fresh = None
    done = []
    for number in sorted(season.weeks):
        games = season.weeks[number].games
        if not games or not all(g.played for g in games) or kept(year, number) is not None:
            continue
        if fresh is None:
            fresh = graded(season, use_kept=False)
        rows = [asdict(g) for g in fresh if g.week == number]
        if not rows:
            continue
        try:
            store.put(KIND, _key(year, number), {"at": time.time(), "version": VERSION, "games": rows})
            done.append(number)
        except store.StoreError:
            break
    return done


def graded(season: Season, use_kept: bool = True) -> list[Graded]:
    """Every graded game of the season, each week priced with what was known
    going into it. A week already written down (keep) is read back as written."""
    year = results.season_year(season)
    out: list[Graded] = []
    for number in sorted(season.weeks):
        written = kept(year, number) if use_kept else None
        if written is not None:
            out.extend(written)
            continue
        games = sorted(season.weeks[number].games, key=lambda g: g.index)
        decided = [g for g in games if g.played and team_code(g.winner) in (team_code(g.home), team_code(g.away))]
        if not decided:
            continue
        ctx = pricing.context(season, number, games)
        prices = {p.game.index: p for p in pricing.price_week(season, number, games, ctx)}
        scores = results.load(year, number)
        for game in decided:
            price = prices.get(game.index)
            said = price.prediction() if price is not None else None
            if said is None or said.chance <= 0.5:
                continue                        # unpriced, or no side taken
            home_pick = same_team(said.pick, game.home)
            sign = 1.0 if home_pick else -1.0
            credited_home = team_code(game.winner) == team_code(game.home)
            forecast = ctx.forecasts.get(game.index)
            line = pricing.market_margin(game, forecast) if forecast is not None else None
            line_pick, line_right = "", None
            if line is not None:
                chance = luck.credited_chance(game, line, game.home)
                if chance is not None and chance != 0.5:
                    line_pick = game.home if chance > 0.5 else game.away
                    line_right = (chance > 0.5) == credited_home
            actual, kickoff = _actual(game, scores)
            out.append(Graded(
                week=number, index=game.index, matchup=game.label, pick=display_team(said.pick),
                chance=said.chance, right=home_pick == credited_home, margin=sign * price.margin,
                line=None if line is None else sign * line,
                line_pick=display_team(line_pick) if line_pick else "", line_right=line_right,
                actual=None if actual is None else sign * actual,
                pool_line=game.line if game.line_favourite else None,
                pool_favourite=display_team(game.line_favourite) if game.line_favourite else "",
                home_pick=home_pick,
                divisional=same_division(game.home, game.away),
                night=None if not kickoff else at_night(kickoff),
            ))
    return out


# ---- the record, cut every way ---------------------------------------------------------------
@dataclass(frozen=True)
class Row:
    """A set of picks: how many came in, and how many their own chances called for."""

    name: str
    picks: int = 0
    right: int = 0
    expected: float = 0.0       # the sum of the chances
    variance: float = 0.0       # ...and of chance x (1 - chance), for how far luck alone reaches
    line_games: int = 0         # of these, the games the betting line had a side in
    line_right: int = 0
    scored: int = 0             # of these, the games with a final score kept
    error: float = 0.0          # ...and the average miss on their final margin (points)

    @property
    def rate(self) -> float:
        return self.right / self.picks if self.picks else 0.0

    @property
    def expected_rate(self) -> float:
        return self.expected / self.picks if self.picks else 0.0

    @property
    def enough(self) -> bool:
        return self.picks >= ENOUGH

    @property
    def off(self) -> float:
        """How far the record sits from its own chances, in standard deviations."""
        return (self.right - self.expected) / math.sqrt(self.variance) if self.variance > 0 else 0.0

    @property
    def verdict(self) -> str:
        if not self.picks:
            return ""
        if not self.enough:
            return "too few to say"
        if self.off <= -OFF:
            return "surer than it should be"
        if self.off >= OFF:
            return "better than it said"
        return "as good as it said"


def tally(name: str, games) -> Row:
    games = list(games)
    with_line = [g for g in games if g.line_right is not None]
    known = [g for g in games if g.actual is not None]
    return Row(
        name=name, picks=len(games), right=sum(g.right for g in games),
        expected=sum(g.chance for g in games), variance=sum(g.chance * (1 - g.chance) for g in games),
        line_games=len(with_line), line_right=sum(bool(g.line_right) for g in with_line),
        scored=len(known), error=sum(abs(g.actual - g.margin) for g in known) / len(known) if known else 0.0,
    )


def tiers(games: list[Graded]) -> list[Row]:
    """The picks by how sure Deadeye was, surest first."""
    names = [name for _floor, name in evidence.STRENGTHS]
    return [tally(name, (g for g in games if g.tier == name)) for name in names]


#: Every way the picks are cut: (what is being compared, [(its name, which picks)]).
CUTS = (
    ("Favourite or underdog", (
        ("The betting favourite", lambda g: g.line is not None and g.line > 0),
        ("The betting underdog", lambda g: g.line is not None and g.line < 0),
    )),
    ("With the line or against it", (
        ("The line's side", lambda g: g.with_line is True),
        ("Against the line", lambda g: g.with_line is False),
    )),
    ("Home or road", (
        ("The home team", lambda g: g.home_pick),
        ("The road team", lambda g: not g.home_pick),
    )),
    ("Size of the betting line", (
        ("Line within 3", lambda g: g.line is not None and abs(g.line) <= 3),
        ("Line 3.5 to 6.5", lambda g: g.line is not None and 3 < abs(g.line) < 7),
        ("Line 7 or more", lambda g: g.line is not None and abs(g.line) >= 7),
    )),
    ("The pool's rules", (
        ("Pool-line games", lambda g: g.pool_line is not None),
        ("Straight-up games", lambda g: g.pool_line is None),
    )),
    ("Opponent", (
        ("Division games", lambda g: g.divisional),
        ("Outside the division", lambda g: not g.divisional),
    )),
    ("Kickoff", (
        ("Night games", lambda g: g.night is True),
        ("Day games", lambda g: g.night is False),
    )),
    ("Time of season", (
        ("Weeks 1-6", lambda g: g.week <= 6),
        ("Weeks 7-12", lambda g: 7 <= g.week <= 12),
        ("Weeks 13-18", lambda g: g.week >= 13),
    )),
)


def situations(games: list[Graded]) -> list[tuple[str, list[Row]]]:
    """The picks cut by situation: (what is being compared, its rows). Empty rows are left out."""
    out = []
    for title, parts in CUTS:
        rows = [tally(name, part) for name, part in ((n, [g for g in games if fits(g)]) for n, fits in parts) if part]
        if len(rows) > 1:               # one row alone compares nothing
            out.append((title, rows))
    return out


def matching(game: Graded) -> tuple[str, ...]:
    """The situations a game falls in - for a game still to be played as much as a graded one."""
    return tuple(name for _title, parts in CUTS for name, fits in parts if fits(game))


# ---- blind spots: where the record sits furthest under its own chances -------------------------
#: Picks a situation needs before it can be called a blind spot at all...
WATCH = 12
#: ...and how far under its own chances (standard deviations) it has to sit.
UNDER = -0.8


def blind_spots(games: list[Graded], most: int = 3) -> list[Row]:
    """The situations and confidence tiers where the picks have fallen furthest
    short of their own chances, worst first. A row under ENOUGH picks is only
    a thing to watch - its `verdict` says so."""
    rows = [row for _title, cut in situations(games) for row in cut] + tiers(games)
    weak = [r for r in rows if r.picks >= WATCH and r.off <= UNDER]
    return sorted(weak, key=lambda r: r.off)[:most]


@dataclass(frozen=True)
class Fear:
    """The situation the record is worst in, and this week's games that are in it."""

    row: Row
    games: tuple[str, ...]


def fear(history: list[Graded], coming: dict[str, tuple[str, ...]]) -> Fear | None:
    """The worst blind spot that this week's slate actually contains.
    `coming` is {matchup: the situations it falls in} (matching)."""
    for row in blind_spots(history, most=99):
        hit = tuple(game for game, names in coming.items() if row.name in names)
        if hit:
            return Fear(row, hit)
    return None


# ---- the misses ------------------------------------------------------------------------------
TOSS_UP, COVER, AGAINST, SHARED, OWN = "Toss-up", "Won, didn't cover", "Against the line", "The line missed it too", "Its own miss"
#: The order the kinds are counted and explained in.
KINDS = {
    TOSS_UP: "a pick under 55% that fell the other way - no lesson in one of these",
    COVER: "the pick won the game but not by the pool's line",
    AGAINST: "Deadeye took the other side from the betting line, and the line was right",
    SHARED: "the betting line had the same side - nothing here the market saw coming",
    OWN: "no betting line was kept to compare with",
}


@dataclass(frozen=True)
class Miss:
    game: Graded
    kind: str

    @property
    def never_close(self) -> bool:
        return self.game.actual is not None and self.game.actual <= -NEVER_CLOSE


def _kind(g: Graded) -> str:
    if g.chance < COIN_FLIP:
        return TOSS_UP
    if g.pool_line is not None and g.actual is not None and g.actual > 0 and same_team(g.pick, g.pool_favourite):
        return COVER
    if g.with_line is False:
        return AGAINST
    if g.with_line is True:
        return SHARED
    return OWN


def misses(games: list[Graded]) -> list[Miss]:
    """Every pick that wasn't credited, the surest first."""
    found = [Miss(g, _kind(g)) for g in games if not g.right]
    return sorted(found, key=lambda m: (-m.game.chance, m.game.week, m.game.index))


# ---- the whole report -------------------------------------------------------------------------
@dataclass(frozen=True)
class MarginError:
    """How far the final margins landed from what was expected, on average (points)."""

    games: int = 0
    deadeye: float = 0.0
    line: float = 0.0


def margin_error(games: list[Graded]) -> MarginError:
    scored = [g for g in games if g.actual is not None and g.line is not None]
    if not scored:
        return MarginError()
    return MarginError(
        len(scored),
        sum(abs(g.actual - g.margin) for g in scored) / len(scored),
        sum(abs(g.actual - g.line) for g in scored) / len(scored),
    )


def streaks(games: list[Graded]) -> tuple[int, int]:
    """(longest run of hits, longest run of misses), in the order the games were listed."""
    best = {True: 0, False: 0}
    run, last = 0, None
    for g in sorted(games, key=lambda g: (g.week, g.index)):
        run = run + 1 if g.right == last else 1
        last = g.right
        best[g.right] = max(best[g.right], run)
    return best[True], best[False]


@dataclass(frozen=True)
class Report:
    games: list[Graded]
    overall: Row
    tiers: list[Row]
    situations: list[tuple[str, list[Row]]]
    misses: list[Miss]
    error: MarginError
    streaks: tuple[int, int]
    blind_spots: list[Row] = ()

    @property
    def weeks(self) -> list[int]:
        return sorted({g.week for g in self.games})

    def kinds(self) -> list[tuple[str, int]]:
        """(kind of miss, how many), in KINDS' order, the empty ones left out."""
        return [(kind, n) for kind in KINDS if (n := sum(m.kind == kind for m in self.misses))]


def report(season: Season) -> Report:
    try:
        keep(season)
    except Exception:  # noqa: BLE001 - the report is worked out afresh instead
        pass
    games = graded(season)
    return Report(games, tally("Every pick", games), tiers(games), situations(games), misses(games),
                  margin_error(games), streaks(games), blind_spots(games))


def chance_text(chance: float) -> str:
    return f"{chance:.0%}"


def margin_text(points: float | None) -> str:
    """A margin from the pick's side: "by 6.5", "lost by 3", "level"."""
    if points is None:
        return ""
    if abs(points) < analytics.PICK_EM:
        return "level"
    return f"by {abs(points):g}" if points > 0 else f"lost by {abs(points):g}"
