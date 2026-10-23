"""Which of this week's picks move your chance of winning the season.

The week planner (weekplan.py) aims at first place in one week, because the
weekly pot only pays first. The season is a different race. What counts there
is the gap to the coaches above you, and a game only moves that gap when you
and they are on different sides. Taking the same side as the leader in a game
can't gain you a thing on them, however sure it is. So when you are behind,
the picks that can close the gap are where the people above you are likely to
be, and you are not.

This plays the rest of the season out many times and asks, for each game this
week: what are your title (and top-3) odds with the side Deadeye likes, and
with the other side?

    this week     each game lands with Deadeye's chance; every other coach's
                  card is their real one once the pick sheet is in, and until
                  then is drawn from how the pool splits on that game
                  (pricing.crowd_share). Big Loser points are a draw from each
                  coach's own weeks.
    after it      each coach scores one of their own past weeks, picked at
                  random and blended with the pool's - the same way the
                  Projections tab works out the title odds (analytics.simulate).

Every card is scored against the same simulated seasons, so the difference
between two cards is the cards and not the dice. The "chase card" turns over
whichever game most raises the odds, one at a time, until nothing helps. As in
weekplan, it is chosen on one batch of seasons and priced on another, so its
odds aren't flattered by having been picked for luck.

It never changes the card. The page shows the numbers; the card stays yours.
No Qt here: ui/pages/leverage.py lays it out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np

from .. import analytics
from ..models import Season
from ..model import predictions
from . import briefing, me, picks

#: Seasons simulated to choose the chase card, and again to price it.
SIMULATIONS = 20_000
SEED = 2026
#: A flip must raise the odds by at least this much (a tenth of a point) to be
#: kept: smaller gains are the simulation's own noise.
MIN_GAIN = 0.001
#: Most games the chase card will turn over.
MAX_FLIPS = 6
#: Coaches listed as the ones to watch.
WATCH = 5
#: Below these title odds, the title is too far off to chase and the chase
#: card aims at the top three instead (unless that is already settled).
TITLE_FLOOR = 0.01
#: A coach's own weeks outweigh the pool's after about this many (as analytics).
SHRINKAGE_WEEKS = analytics.SHRINKAGE_WEEKS

TITLE, TOP3 = "title", "top3"
AIM_NAMES = {TITLE: "the title", TOP3: "a top-3 finish"}


@dataclass(frozen=True)
class Pick:
    """One game this week, and what each side does for your season."""

    label: str
    pick: str                 # the side Deadeye likes
    other: str
    chance: float             # chance `pick` comes in
    crowd: float              # share of the pool on `pick` (real once the sheet is in)
    title: float              # your title odds with `pick` (rest of the card as Deadeye's)
    title_flipped: float      # ... with `other` instead
    top3: float
    top3_flipped: float
    #: For each coach to watch, the chance they're on `other` (1/0 once known).
    split: dict[str, float] = field(default_factory=dict)
    in_chase: bool = False    # the chase card takes `other` here
    decided: bool = False     # already played: nothing to choose

    def worth(self, aim: str) -> float:
        """Points of season odds the other side is worth over Deadeye's (+ means flip helps)."""
        return (self.title_flipped - self.title) if aim == TITLE else (self.top3_flipped - self.top3)


@dataclass(frozen=True)
class Rival:
    name: str
    wins: int
    gap: int                  # their wins minus yours (+ = ahead of you)
    title: float              # their title odds with your Deadeye card
    differ: float             # games this week they're expected to be on the other side from you


@dataclass(frozen=True)
class Report:
    week: int
    me: str
    wins: int
    place: int
    weeks_left: int           # this week included
    aim: str                  # TITLE or TOP3: what the chase card aims at
    title: float              # your odds with Deadeye's card
    top3: float
    chase_title: float        # ... with the chase card
    chase_top3: float
    card_hits: float          # expected games right, Deadeye's card
    chase_hits: float         # ... the chase card
    picks: list[Pick]
    rivals: list[Rival]
    field_known: bool         # the other cards are the real pick sheet
    simulations: int

    @property
    def flips(self) -> list[Pick]:
        return [p for p in self.picks if p.in_chase]

    @property
    def gain(self) -> float:
        """What the chase card adds to the odds it aims at."""
        return (self.chase_title - self.title) if self.aim == TITLE else (self.chase_top3 - self.top3)


def _plain(name: object) -> str:
    return "".join(c for c in str(name or "").casefold() if c.isalnum())


# ---- the simulation -------------------------------------------------------------------
class _Seasons:
    """One batch of simulated seasons: everyone else's final totals, and the
    pieces of yours that don't depend on your card."""

    def __init__(self, chance, cards, known, crowd, base, weekly, bl, mine_i, sims, rng):
        n, games = cards.shape[0], len(chance)
        # 0 = Deadeye's side came in, 1 = the other side did.
        self.results = (rng.random((sims, games)) >= chance).astype(np.int8)
        # Everyone's cards this week: real rows where known, drawn afresh per season otherwise.
        drawn = (rng.random((sims, n, games)) >= crowd).astype(np.int8)
        field_cards = np.where(known[None, :, :], cards[None, :, :], drawn)
        week = (field_cards == self.results[:, None, :]).sum(axis=2).astype(np.float32)
        week += np.stack([_draw(v, rng, sims, 1)[:, 0] for v in bl], axis=1)
        rest = np.stack([_draw(v, rng, sims, weekly[1]).sum(axis=1) for v in weekly[0]], axis=1)
        totals = base[None, :] + week + rest                       # (sims, coaches)
        self.my_fixed = base[mine_i] + rest[:, mine_i] + (week[:, mine_i]
                                                          - (field_cards[:, mine_i, :] == self.results).sum(axis=1))
        others = np.delete(totals, mine_i, axis=1)
        self.others = others
        self.best = others.max(axis=1)
        self.at_best = (others == self.best[:, None]).sum(axis=1)
        k = min(3, others.shape[1])
        self.third = -np.partition(-others, k - 1, axis=1)[:, k - 1] if k else np.full(sims, -np.inf)

    def scores(self, bits: np.ndarray) -> np.ndarray:
        return self.my_fixed + (bits[None, :] == self.results).sum(axis=1)

    def odds(self, bits: np.ndarray) -> tuple[float, float]:
        return self._odds(self.scores(bits))

    def _odds(self, mine: np.ndarray) -> tuple[float, float]:
        title = np.where(mine > self.best, 1.0, np.where(mine == self.best, 1.0 / (self.at_best + 1), 0.0))
        return float(title.mean()), float((mine >= self.third).mean())

    def flipped(self, bits: np.ndarray) -> list[tuple[float, float]]:
        """Odds with each single game turned over, the rest kept."""
        mine = self.scores(bits)
        hit = (bits[None, :] == self.results)
        return [self._odds(mine + np.where(hit[:, g], -1, 1)) for g in range(len(bits))]

    def rival_title(self, bits: np.ndarray) -> np.ndarray:
        """Each other coach's title odds, given your card."""
        mine = self.scores(bits)
        best = np.maximum(self.best, mine)
        on_top = self.others == best[:, None]
        ties = on_top.sum(axis=1) + (mine == best)
        return (on_top / ties[:, None]).mean(axis=0)


def _draw(pair, rng, sims, weeks):
    """`weeks` weeks of one coach's scores, bootstrapped and shrunk to the pool's."""
    own, pool = pair
    if weeks <= 0:
        return np.zeros((sims, 0), dtype=np.float32)
    shape = (sims, weeks)
    pooled = pool[rng.integers(pool.size, size=shape)] if pool.size else np.zeros(shape)
    if own.size:
        mine = own[rng.integers(own.size, size=shape)]
        pooled = np.where(rng.random(shape) < own.size / (own.size + SHRINKAGE_WEEKS), mine, pooled)
    return pooled.astype(np.float32)


# ---- putting it together -----------------------------------------------------------------
#: The last few answers, by the season object they came from: the page and the
#: warm-up (ui/workers.py) ask the same question and share the answer.
_MEMO: dict[tuple, tuple] = {}


def report(season: Season, week: int | None = None, *, sims: int = SIMULATIONS,
           seed: int = SEED) -> Report | None:
    """This week's leverage on the season, or None when there is nothing to say
    (no owner in the data, no priced games, or the season is over)."""
    week = week or analytics.upcoming_week(season)
    key = (id(season), week, sims, seed)
    held = _MEMO.get(key)
    if held is not None and held[0] is season:
        return held[1]
    found = _work_out(season, week, sims, seed)
    if len(_MEMO) >= 4:
        _MEMO.pop(next(iter(_MEMO)))
    _MEMO[key] = (season, found)
    return found


def _work_out(season: Season, week: int, sims: int, seed: int) -> Report | None:
    mine_key = me.key(season)
    if not mine_key or not season.players:
        return None
    remaining = analytics.weeks_remaining(season)
    if remaining <= 0:
        return None
    brief = briefing.build(season, week, briefing.STYLE_STRAIGHT)
    choices = brief.choices
    if not choices:
        return None

    found = season.weeks.get(week)
    by_index = {g.index: g for g in (found.games if found else [])}
    chance, crowd, decided = [], [], []
    for c in choices:
        mark = briefing.graded(by_index.get(c.index), c.pick)
        decided.append(bool(mark))
        chance.append(1.0 if mark == briefing.RIGHT else 0.0 if mark == briefing.WRONG
                      else 0.5 if mark else c.chance)
        crowd.append(c.crowd if c.crowd is not None else 0.7)

    players = sorted(season.players.values(), key=lambda p: p.key)
    keys = [p.key for p in players]
    mine_i = keys.index(mine_key)
    cards, known = _sheet_cards(week, players, choices, by_index)
    base = np.array([analytics.current_wins(p) for p in players], dtype=np.float32)
    pool_weeks = np.array([v for p in players for v in analytics.history(p)], dtype=np.float32)
    pool_bl = np.array([v for p in players for v in p.weekly_big_loser.values() if v is not None], dtype=np.float32)
    weekly = ([(np.array(analytics.history(p), dtype=np.float32), pool_weeks) for p in players], remaining - 1)
    bl = [(np.array([v for v in p.weekly_big_loser.values() if v is not None], dtype=np.float32), pool_bl)
          for p in players]

    return _report(season, week, tuple(chance), tuple(crowd), tuple(decided), choices, players, mine_i,
                   cards, known, base, weekly, bl, remaining, sims, seed)


def _sheet_cards(week, players, choices, by_index):
    """(cards, known): each coach's side in each game (0 = Deadeye's), and
    whether it's their real pick. Unknown until the week's sheet is in."""
    n, g = len(players), len(choices)
    cards = np.zeros((n, g), dtype=np.int8)
    known = np.zeros((n, g), dtype=bool)
    sheet = picks.load(week)
    if sheet is None:
        return cards, known
    row = {_plain(p.display): i for i, p in enumerate(players)}
    row.update({_plain(p.key): i for i, p in enumerate(players)})
    for j, c in enumerate(choices):
        game = by_index.get(c.index)
        col = sheet.game_for(game.away, game.home) if game is not None else None
        if col is None:
            continue
        want = predictions.team_code(c.pick)
        for name, team in col.picks.items():
            i = row.get(_plain(name))
            code = predictions.team_code(team)
            if i is not None and code:
                cards[i, j] = 0 if code == want else 1
                known[i, j] = True
    return cards, known


def _best_pair(seasons: _Seasons, card: np.ndarray, open_games: list[int], aim: int,
               now: float) -> tuple[float, tuple[int, int]]:
    """The two open games that, turned together, most raise the odds (and by how much)."""
    found = (0.0, (-1, -1))
    for x, g in enumerate(open_games):
        for h in open_games[x + 1:]:
            trial = card.copy()
            trial[[g, h]] = 1
            gain = seasons.odds(trial)[aim] - now
            if gain > found[0]:
                found = (gain, (g, h))
    return found


def _report(season, week, chance, crowd, decided, choices, players, mine_i, cards, known,
            base, weekly, bl, remaining, sims, seed) -> Report:
    chance_a = np.array(chance)
    crowd_a = np.array(crowd)[None, :]
    games = len(chance)
    args = (chance_a, cards, known, crowd_a, base, weekly, bl, mine_i, sims)
    choose = _Seasons(*args, np.random.default_rng(seed))
    price = _Seasons(*args, np.random.default_rng(seed + 1))

    deadeye = np.zeros(games, dtype=np.int8)
    title, top3 = price.odds(deadeye)
    # A top-3 finish is only the aim when the title is out of reach and the top three isn't settled.
    aim = TITLE if title >= TITLE_FLOOR or top3 >= 0.99 else TOP3
    pick_aim = 0 if aim == TITLE else 1

    # The chase card: turn over whichever open game helps most, until none does.
    chase = deadeye.copy()
    best = choose.odds(chase)[pick_aim]
    for _ in range(MAX_FLIPS):
        trials = choose.flipped(chase)
        gains = [(t[pick_aim] - best, g) for g, t in enumerate(trials) if not decided[g] and not chase[g]]
        if not gains:
            break
        gain, g = max(gains)
        if gain >= MIN_GAIN:
            chase[g] = 1
            best += gain
            continue
        # No one game helps - two behind, say, where only two turned games can
        # draw level. Try them in pairs before giving up.
        pair_gain, pair = _best_pair(choose, chase, [g for _, g in gains], pick_aim, best)
        if pair_gain < MIN_GAIN:
            break
        chase[list(pair)] = 1
        best += pair_gain
    chase_title, chase_top3 = price.odds(chase)

    # Who to watch: the coaches most likely to take the title from you, and
    # anyone level or just ahead.
    rival_odds = price.rival_title(deadeye)
    others = [i for i in range(len(players)) if i != mine_i]
    watch_order = sorted(others, key=lambda i: (-rival_odds[others.index(i)], -base[i], players[i].display.lower()))
    watched = watch_order[:WATCH]
    rivals, split_of = [], {}
    for i in watched:
        on_other = np.where(known[i], cards[i].astype(float), 1.0 - np.array(crowd))
        on_other = np.where(np.array(decided), 0.0, on_other)
        split_of[players[i].display] = on_other
        rivals.append(Rival(players[i].display, int(base[i]), int(base[i] - base[mine_i]),
                            float(rival_odds[others.index(i)]), float(on_other.sum())))

    flips = price.flipped(deadeye)
    pool_on = [float(known[:, g].sum() and cards[known[:, g], g].tolist().count(0) / known[:, g].sum())
               if known[:, g].any() else crowd[g] for g in range(games)]
    out = []
    for g, c in enumerate(choices):
        out.append(Pick(
            label=c.matchup, pick=c.pick, other=c.other, chance=chance[g], crowd=pool_on[g],
            title=title, title_flipped=flips[g][0], top3=top3, top3_flipped=flips[g][1],
            split={name: float(v[g]) for name, v in split_of.items()},
            in_chase=bool(chase[g]), decided=decided[g],
        ))

    place = 1 + sum(1 for i in range(len(players)) if base[i] > base[mine_i])
    hits = sum(chance)
    chase_hits = sum((1 - p) if chase[g] else p for g, p in enumerate(chance))
    return Report(
        week=week, me=players[mine_i].display, wins=int(base[mine_i]), place=place,
        weeks_left=remaining, aim=aim, title=title, top3=top3,
        chase_title=chase_title, chase_top3=chase_top3, card_hits=hits, chase_hits=chase_hits,
        picks=out, rivals=rivals, field_known=bool(known.any()), simulations=sims,
    )
