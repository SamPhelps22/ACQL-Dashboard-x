"""Three looks at the picks that the scores alone don't give.

* Blind spots - each coach's record picking each team, picking against it,
  and by kind of game: home or road, favourite or underdog, a big favourite,
  a close game, a line game. A split well under the coach's own usual rate
  is a blind spot; well over it, a strong suit.
* The line move - between the opening line and the last one before kickoff
  the market moves on injury news and money. A coach whose picks keep
  landing on the side it moved toward reads games the way the market came
  to, and that is decided before a ball is thrown - the surest sign of
  skill rather than luck there is.
* Chaos - how surprising each week's results were against the lines, from
  0 (every favourite came in) to 10 (a week like it comes once in years),
  and each coach's average adjusted for it: a 10 in a week the pool
  averaged 8 is worth more than a 10 in a week it averaged 11.

"Right" is always the pool's own: the workbook's result row already has the
pool's line applied, so on a line game the right side is the one credited.

No Qt here, like analytics.py: the pages and the website only lay it out.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, replace

from . import luck
from . import picks as pick_sheets
from .models import Game, Season, same_team
from .predictions import display_team, team_code

#: A split needs this many picks before it can be called anything.
MIN_PICKS = 3
#: ...and has to be this many games off the coach's own usual rate.
MIN_GAP = 1.5
#: A line has to move this far, in points, to count as moving.
MIN_MOVE = 1.0
#: A move this big is "the line moved" in the pool-wide record.
STEAM_MOVE = 2.0
BIG_FAVOURITE = 7.0
CLOSE_GAME = 3.0
#: A week needs this many priced, decided games to be rated.
MIN_RATED_GAMES = 8
#: Chaos ratings at or above this are wild weeks; under CALM, calm ones.
WILD = 6.0
CALM = 4.0
CHAOS_LABELS = ((2.0, "Chalk"), (4.0, "Calm"), (6.0, "Normal"), (8.0, "Wild"), (10.1, "Chaos"))


# ---- every coach's picks, right and wrong ----------------------------------------
@dataclass(frozen=True)
class Pick:
    week: int
    game: Game
    side: str               # "home" or "away"

    @property
    def team(self) -> str:
        return self.game.home if self.side == "home" else self.game.away

    @property
    def opponent(self) -> str:
        return self.game.away if self.side == "home" else self.game.home

    @property
    def right(self) -> bool:
        return same_team(self.team, self.game.winner)


def _plain(name: object) -> str:
    return "".join(c for c in str(name or "").casefold() if c.isalnum())


def _side(game: Game, team: object) -> str:
    code = team_code(str(team or ""))
    if not code:
        return ""
    if code == team_code(game.home):
        return "home"
    if code == team_code(game.away):
        return "away"
    return ""


def _decided(game: Game) -> bool:
    """A result naming one of the two sides (a tie credits nobody)."""
    return game.played and bool(_side(game, game.winner))


def week_cards(season: Season, number: int) -> dict[str, list[Pick]]:
    """Every coach's side in every decided game of a week.

    The pick sheet as it went out has every pick, right and wrong, so it
    comes first. The workbook's line is next: before grading it holds every
    pick, after grading only the right ones - so where a line looks graded
    (every pick left on it right, some games blank) a blank is a miss, and
    the miss is the other side.
    """
    week = season.weeks.get(number)
    if week is None or not week.lines:
        return {}
    games = [g for g in sorted(week.games, key=lambda g: g.index) if _decided(g)]
    if not games:
        return {}
    sheet = None
    if number not in pick_sheets.other_season_weeks():
        sheet = pick_sheets.load(number)
    on_sheet = {_plain(n): n for n in (sheet.coaches if sheet else [])}
    rows = {g.index: sheet.game_for(g.away, g.home) if sheet else None for g in games}
    out: dict[str, list[Pick]] = {}
    for key, line in week.lines.items():
        player = season.players.get(key)
        name = (on_sheet.get(_plain(player.display if player else ""))
                or on_sheet.get(_plain(line.player)))
        shown = {g.index: _side(g, line.correct_picks.get(g.index)) for g in games}
        shown = {i: s for i, s in shown.items() if s}
        by_index = {g.index: g for g in games}
        graded = bool(shown) and len(shown) < len(games) and all(
            same_team(by_index[i].home if s == "home" else by_index[i].away, by_index[i].winner)
            for i, s in shown.items()
        )
        card = []
        for game in games:
            row = rows[game.index]
            side = _side(game, row.picks.get(name)) if name and row is not None else ""
            side = side or shown.get(game.index, "")
            if not side and graded:
                side = "away" if same_team(game.winner, game.home) else "home"
            if side:
                card.append(Pick(number, game, side))
        if card:
            out[key] = card
    return out


def season_cards(season: Season, weeks=None) -> dict[str, list[Pick]]:
    """Every coach's picks across the season (or just `weeks`), oldest week first."""
    out: dict[str, list[Pick]] = {}
    for number in sorted(season.weeks if weeks is None else set(weeks) & set(season.weeks)):
        for key, card in week_cards(season, number).items():
            out.setdefault(key, []).extend(card)
    return out


# ---- the betting line before each game ----------------------------------------
@dataclass(frozen=True)
class Market:
    opening: float | None    # home margin when the line opened
    close: float             # home margin, the last line before kickoff


def markets(season: Season) -> dict[int, dict[int, Market]]:
    """Week -> game index -> the line it opened at and closed at.

    The close is the market number the rest of the app prices with, which
    never includes a line taken after kickoff (odds.stored).
    """
    from . import predictions, pricing
    out: dict[int, dict[int, Market]] = {}
    for number, week in season.weeks.items():
        forecasts, _ = predictions.load(number)
        if not forecasts:
            continue
        games = sorted(week.games, key=lambda g: g.index)
        by_index = {g.index: g for g in games}
        for index, forecast in predictions.match_games(games, forecasts).by_game.items():
            game = by_index.get(index)
            close = pricing.market_margin(game, forecast) if game else None
            if close is None:
                continue
            opening = None
            if forecast.opening is not None and forecast.market is not None:
                opening = predictions.home_margin(game, forecast, forecast.opening)
            out.setdefault(number, {})[index] = Market(opening, close)
    return out


def _chance(pick: Pick, margin: float) -> float | None:
    """The chance a pick is credited, given the home margin."""
    return luck.credited_chance(pick.game, margin, pick.team)


# ---- blind spots -------------------------------------------------------------------
@dataclass(frozen=True)
class Split:
    label: str
    right: int
    picks: int
    expected: float = 0.0       # what the rest of the pool got right in the same games

    @property
    def wrong(self) -> int:
        return self.picks - self.right

    @property
    def rate(self) -> float:
        return self.right / self.picks if self.picks else 0.0

    @property
    def gap(self) -> float:
        """Games better (+) or worse (-) than the rest of the pool in the same games."""
        return self.right - self.expected

    @property
    def record(self) -> str:
        return f"{self.right}-{self.wrong}"

    @property
    def field_rate(self) -> float:
        """How often the rest of the pool was right in the same games."""
        return self.expected / self.picks if self.picks else 0.0


@dataclass(frozen=True)
class BlindSpots:
    key: str
    name: str
    overall: Split
    kinds: tuple[Split, ...]
    teams: tuple[Split, ...]        # picking each team
    against: tuple[Split, ...]      # picking against each team

    def _counted(self) -> list[Split]:
        return [s for s in (*self.teams, *self.against, *self.kinds) if s.picks >= MIN_PICKS]

    def _off_usual(self, split: Split) -> float:
        """How far a split is from this coach's own usual edge over the pool.

        A coach well ahead of the pool is ahead in most splits, and one well
        behind is behind in most: neither is a strong suit or a blind spot,
        just their standing. A split counts when it is off the field *and*
        off what this coach usually does against it.
        """
        usual = self.overall.gap / self.overall.picks if self.overall.picks else 0.0
        return split.gap - usual * split.picks

    @property
    def worst(self) -> list[Split]:
        """Blind spots, worst first."""
        return sorted(
            (s for s in self._counted() if s.gap <= -MIN_GAP and self._off_usual(s) <= -MIN_GAP),
            key=lambda s: (s.gap, -s.picks, s.label),
        )

    @property
    def best(self) -> list[Split]:
        """Strong suits, strongest first."""
        return sorted(
            (s for s in self._counted() if s.gap >= MIN_GAP and self._off_usual(s) >= MIN_GAP),
            key=lambda s: (-s.gap, -s.picks, s.label),
        )

    def team_extremes(self, each: int = 2) -> tuple[list[Split], list[Split]]:
        """(worst teams, best teams) with enough picks, however mild - picking
        a team or picking against it, leaving out any already a blind spot or
        strong suit."""
        listed = {s.label for s in (*self.worst, *self.best)}
        teams = [s for s in (*self.teams, *self.against)
                 if s.picks >= MIN_PICKS and s.label not in listed]
        low = sorted((s for s in teams if s.gap < 0 and s.right < s.wrong),
                     key=lambda s: (s.gap, -s.picks, s.label))
        high = sorted((s for s in teams if s.gap > 0 and s.right > s.wrong),
                      key=lambda s: (-s.gap, -s.picks, s.label))
        return low[:each], high[:each]


def _kinds(pick: Pick, market: Market | None) -> list[str]:
    out = ["Home teams" if pick.side == "home" else "Road teams"]
    if pick.game.line is not None:
        out.append("Line games")
    if market is not None:
        margin = market.close if pick.side == "home" else -market.close
        if margin > 0:
            out.append("Favourites")
            if margin >= BIG_FAVOURITE:
                out.append(f"Big favourites ({BIG_FAVOURITE:g}+)")
        elif margin < 0:
            out.append("Underdogs")
        if abs(margin) < CLOSE_GAME:
            out.append(f"Close games (under {CLOSE_GAME:g})")
    return out


def _tally(groups: dict[str, list[tuple[bool, float]]]) -> tuple[Split, ...]:
    splits = [
        Split(label, sum(r for r, _ in hits), len(hits), sum(e for _, e in hits))
        for label, hits in groups.items()
    ]
    return tuple(sorted(splits, key=lambda s: (-s.picks, s.label)))


def blind_spots(season: Season, cards: dict[str, list[Pick]] | None = None,
                market: dict[int, dict[int, Market]] | None = None) -> dict[str, BlindSpots]:
    """Player key -> their blind spots and strong suits.

    Each pick is set against how the rest of the pool did in that same
    game, so a split measures the coach and not the games: a 4-10 record on
    big favourites is no blind spot when the pool's lines sank everyone's
    big favourites alike.
    """
    cards = season_cards(season) if cards is None else cards
    market = markets(season) if market is None else market
    field: dict[tuple[int, int], list[int]] = {}        # (week, game) -> [right, picks]
    for card in cards.values():
        for pick in card:
            tally = field.setdefault((pick.week, pick.game.index), [0, 0])
            tally[0] += pick.right
            tally[1] += 1
    out = {}
    for key, card in cards.items():
        player = season.players.get(key)
        kinds: dict[str, list[tuple[bool, float]]] = {}
        teams: dict[str, list[tuple[bool, float]]] = {}
        against: dict[str, list[tuple[bool, float]]] = {}
        every: list[tuple[bool, float]] = []
        for pick in card:
            right, picks = field[(pick.week, pick.game.index)]
            others = (right - pick.right) / (picks - 1) if picks > 1 else float(pick.right)
            entry = (pick.right, others)
            every.append(entry)
            for label in _kinds(pick, market.get(pick.week, {}).get(pick.game.index)):
                kinds.setdefault(label, []).append(entry)
            teams.setdefault(f"Picking {display_team(pick.team)}", []).append(entry)
            against.setdefault(f"Against {display_team(pick.opponent)}", []).append(entry)
        out[key] = BlindSpots(
            key=key,
            name=player.display if player else key,
            overall=_tally({"Every pick": every})[0],
            kinds=_tally(kinds),
            teams=_tally(teams),
            against=_tally(against),
        )
    return out


def pool_teams(cards: dict[str, list[Pick]]) -> tuple[Split, ...]:
    """The whole pool's record picking each team, the team it reads worst first."""
    groups: dict[str, list[tuple[bool, float]]] = {}
    for card in cards.values():
        for pick in card:
            groups.setdefault(display_team(pick.team), []).append((pick.right, 0.0))
    return tuple(sorted(_tally(groups), key=lambda s: (s.rate, -s.picks, s.label)))


# ---- who beat the line move -----------------------------------------------------------
@dataclass(frozen=True)
class LineMove:
    key: str
    name: str
    moved: int              # their picks in games whose line moved MIN_MOVE or more
    with_move: int          # ...on the side it moved toward
    came_in: int            # of those with the move, how many were right
    points: float           # points moved toward their side, all moved picks
    gained: float           # chance gained between open and close, summed: wins of value

    @property
    def rate(self) -> float:
        return self.with_move / self.moved if self.moved else 0.0


def _moved(pick: Pick, market: Market | None) -> float | None:
    """Points the line moved toward this pick's side (negative: away from it)."""
    if market is None or market.opening is None:
        return None
    toward_home = market.close - market.opening
    return toward_home if pick.side == "home" else -toward_home


def line_moves(season: Season, cards: dict[str, list[Pick]] | None = None,
               market: dict[int, dict[int, Market]] | None = None) -> list[LineMove]:
    """Every coach's record against the line move, the best reader first."""
    cards = season_cards(season) if cards is None else cards
    market = markets(season) if market is None else market
    out = []
    for key, card in cards.items():
        moved = with_move = came_in = 0
        points = gained = 0.0
        for pick in card:
            m = market.get(pick.week, {}).get(pick.game.index)
            move = _moved(pick, m)
            if move is None or abs(move) < MIN_MOVE:
                continue
            before, after = _chance(pick, m.opening), _chance(pick, m.close)
            if before is None or after is None:
                continue
            moved += 1
            points += move
            gained += after - before
            if move > 0:
                with_move += 1
                came_in += pick.right
        if moved:
            player = season.players.get(key)
            out.append(LineMove(key, player.display if player else key,
                                moved, with_move, came_in, points, gained))
    out.sort(key=lambda m: (-m.gained, -m.rate, m.name.casefold()))
    return out


@dataclass(frozen=True)
class Steam:
    games: int              # decided games whose line moved STEAM_MOVE or more
    came_in: int            # how often the side it moved toward was credited
    weeks: tuple[int, ...]


def steam(season: Season, market: dict[int, dict[int, Market]] | None = None) -> Steam:
    """When the line moved a lot, how often the side it moved to came in."""
    market = markets(season) if market is None else market
    games = came_in = 0
    weeks = set()
    for number, by_game in market.items():
        week = season.weeks.get(number)
        for game in (g for g in (week.games if week else []) if _decided(g)):
            m = by_game.get(game.index)
            if m is None or m.opening is None or abs(m.close - m.opening) < STEAM_MOVE:
                continue
            games += 1
            weeks.add(number)
            toward = game.home if m.close > m.opening else game.away
            came_in += same_team(toward, game.winner)
    return Steam(games, came_in, tuple(sorted(weeks)))


# ---- chaos ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WeekChaos:
    week: int
    rating: float           # 0..10: the share of normal weeks calmer than this one, x10
    upsets: int             # results the lines (and the pool's rules) had under 50%
    expected: float         # upsets the lines expected
    games: int              # priced, decided games
    biggest: Game | None    # the least likely result
    biggest_chance: float
    pool_average: float     # the pool's average score
    winner_side: str = ""   # the biggest upset's credited team

    @property
    def label(self) -> str:
        return next(name for top, name in CHAOS_LABELS if self.rating < top)

    @property
    def biggest_text(self) -> str:
        """"Chicago over Philadelphia, a 34% chance" - "" when nothing was an upset."""
        game = self.biggest
        if game is None:
            return ""
        loser = game.away if same_team(self.winner_side, game.home) else game.home
        text = f"{display_team(self.winner_side)} over {display_team(loser)}"
        if game.line is not None:
            text += " on the pool's line"
        return f"{text}, a {self.biggest_chance:.0%} chance"


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def week_chaos(season: Season, number: int,
               market: dict[int, dict[int, Market]] | None = None) -> WeekChaos | None:
    """How surprising a finished week was. None until every game is decided.

    Each result's surprise is how unlikely it was: -ln(its chance). Added
    up over the week and set against what a week of these exact games
    normally adds up to, it says how wild the week was - a rating of 7 means
    seven weeks in ten with these games would have been calmer.
    """
    week = season.weeks.get(number)
    if week is None or not week.games or not all(g.played for g in week.games):
        return None
    market = markets(season) if market is None else market
    by_game = market.get(number, {})
    surprise = mean = var = 0.0
    upsets, expected, counted = 0, 0.0, 0
    biggest, biggest_chance, biggest_side = None, 1.0, ""
    for game in (g for g in week.games if _decided(g)):
        m = by_game.get(game.index)
        if m is None:
            continue
        p = luck.credited_chance(game, m.close, game.winner)
        if p is None:
            continue
        p = min(max(p, 0.01), 0.99)
        q = max(p, 1 - p)                       # the favourite's chance
        counted += 1
        surprise += -math.log(p)
        mean += -(q * math.log(q) + (1 - q) * math.log(1 - q))
        var += q * (1 - q) * math.log(q / (1 - q)) ** 2
        expected += 1 - q
        if p < 0.5:
            upsets += 1
        if p < biggest_chance:
            biggest, biggest_chance, biggest_side = game, p, game.winner
    if counted < MIN_RATED_GAMES:
        return None
    z = (surprise - mean) / math.sqrt(var) if var > 0 else 0.0
    scores = [l.total_wins for l in week.lines.values() if l.total_wins]
    return WeekChaos(
        week=number,
        rating=round(10 * _phi(z), 1),
        upsets=upsets,
        expected=expected,
        games=counted,
        biggest=biggest if biggest_chance < 0.5 else None,
        biggest_chance=biggest_chance,
        pool_average=statistics.fmean(scores) if scores else 0.0,
        winner_side=biggest_side if biggest_chance < 0.5 else "",
    )


def season_chaos(season: Season, market: dict[int, dict[int, Market]] | None = None,
                 weeks=None) -> list[WeekChaos]:
    market = markets(season) if market is None else market
    numbers = sorted(season.weeks if weeks is None else set(weeks) & set(season.weeks))
    out = [week_chaos(season, n, market) for n in numbers]
    return [c for c in out if c is not None]


@dataclass(frozen=True)
class Adjusted:
    key: str
    name: str
    weeks: int
    average: float          # wins a week, as scored
    adjusted: float         # wins a week, every week weighed by how hard it was
    wild: float | None      # wins above the pool average in wild weeks
    calm: float | None      # ...and in calm ones
    rank: int = 0           # by the adjusted average
    actual_rank: int = 0    # by the average as scored


def adjusted_standings(season: Season, chaos: list[WeekChaos] | None = None,
                       weeks=None) -> list[Adjusted]:
    """Each coach's season with every week weighed by how hard it was.

    A week's score is measured against that week's field - how far above
    its average, in that week's own spread of scores - and put back into
    wins a week at the season's usual average and spread. A coach who keeps
    scoring well in weeks that sink the pool climbs; one who only scores
    when everybody does falls back.
    """
    chaos = season_chaos(season, weeks=weeks) if chaos is None else chaos
    rating = {c.week: c.rating for c in chaos}
    if weeks is None:
        weeks = season.final_weeks() or season.played_weeks()
    fields: dict[int, tuple[float, float]] = {}
    for number in weeks:
        scores = [p.weekly_wins[number] for p in season.players.values()
                  if p.weekly_wins.get(number) is not None]
        if len(scores) >= 5 and statistics.pstdev(scores) > 0:
            fields[number] = (statistics.fmean(scores), statistics.pstdev(scores))
    if not fields:
        return []
    usual_mean = statistics.fmean(m for m, _ in fields.values())
    usual_sd = statistics.fmean(s for _, s in fields.values())
    out = []
    for key, player in season.players.items():
        mine = [(n, player.weekly_wins[n]) for n in fields if player.weekly_wins.get(n) is not None]
        if not mine:
            continue
        zs = [(wins - fields[n][0]) / fields[n][1] for n, wins in mine]
        wild = [wins - fields[n][0] for n, wins in mine if rating.get(n, -1) >= WILD]
        calm = [wins - fields[n][0] for n, wins in mine if 0 <= rating.get(n, -1) < CALM]
        out.append(Adjusted(
            key=key, name=player.display, weeks=len(mine),
            average=statistics.fmean(w for _, w in mine),
            adjusted=usual_mean + statistics.fmean(zs) * usual_sd,
            wild=statistics.fmean(wild) if wild else None,
            calm=statistics.fmean(calm) if calm else None,
        ))
    by_actual = sorted(out, key=lambda a: (-a.average, a.name.casefold()))
    actual = {a.key: i + 1 for i, a in enumerate(by_actual)}
    out.sort(key=lambda a: (-a.adjusted, a.name.casefold()))
    return [
        replace(a, rank=i + 1, actual_rank=actual[a.key])
        for i, a in enumerate(out)
    ]


# ---- everything at once, for the pages and the website ----------------------------
@dataclass(frozen=True)
class Report:
    spots: dict[str, BlindSpots]
    moves: list[LineMove]
    steam: Steam
    chaos: list[WeekChaos]
    adjusted: list[Adjusted]
    teams: tuple[Split, ...]        # the pool's record picking each team

    def move_for(self, key: str) -> LineMove | None:
        return next((m for m in self.moves if m.key == key), None)

    def adjusted_for(self, key: str) -> Adjusted | None:
        return next((a for a in self.adjusted if a.key == key), None)

    def chaos_for(self, week: int) -> WeekChaos | None:
        return next((c for c in self.chaos if c.week == week), None)


_kept: tuple[tuple, Report] | None = None


def report(season: Season, weeks=None) -> Report:
    """All three, worked out once per load and shared by every page that asks.
    `weeks` keeps to those weeks - the website shows finished weeks only."""
    global _kept
    from . import odds, predictions
    key = (id(season), tuple(sorted(weeks)) if weeks is not None else None,
           predictions.store_stamp(), odds.stamp(), pick_sheets._store_stamp())
    if _kept is not None and _kept[0] == key:
        return _kept[1]
    cards = season_cards(season, weeks)
    market = markets(season)
    chaos = season_chaos(season, market, weeks)
    made = Report(
        spots=blind_spots(season, cards, market),
        moves=line_moves(season, cards, market),
        steam=steam(season, market),
        chaos=chaos,
        adjusted=adjusted_standings(season, chaos, weeks),
        teams=pool_teams(cards),
    )
    _kept = (key, made)
    return made
