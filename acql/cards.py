"""Cards kept: the one you saved, the one the model made, and how both did.

Two questions need a card remembered from earlier in the week:

  * "Did anything change?" - between saving a card on Wednesday and the lock
    on Thursday or Sunday, lines move on injury news. Comparing the saved
    card with the card the same model makes now shows what to swap, and why.

  * "Should I trust it?" - the model's card for each week is kept as it stood
    before the first kickoff, then scored once the results are in, next to
    your real card and the plain likeliest-side card. After five or six weeks
    that says whether to follow it, overrule it, or only take its turns.

Kept in the app's database (store.py). Nothing here draws anything.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace

from .models import Season, same_team
from .version import MODEL_NAME

STORE_NAME = "acql-cards.json"
#: A pick whose chance moved this much (either way) since the card was
#: saved is worth mentioning, even if the card still takes it.
MOVE_WORTH_NOTING = 0.05


def _read() -> dict:
    """A private copy of everything kept here, safe to change before `_write`."""
    from . import store
    return json.loads(json.dumps(store.items("cards")))


def _write(mapping: dict) -> None:
    from . import store
    try:
        store.replace("cards", mapping)
    except store.StoreError:
        pass


# ---- a card, frozen -----------------------------------------------------------
@dataclass
class Snapshot:
    at: float
    take: dict[int, str]                      # game index -> side taken
    chance: dict[int, float]                  # chance that side lands
    label: dict[int, str]                     # "Minnesota @ Chicago"
    margin: dict[int, float] = field(default_factory=dict)   # market home margin used
    plain: dict[int, str] = field(default_factory=dict)      # the likeliest side
    planned: dict[int, str] = field(default_factory=dict)    # the planner's card
    win_odds: float | None = None
    rebuilt: bool = False                     # made after the fact, not at the time

    @classmethod
    def of(cls, brief, at: float | None = None, rebuilt: bool = False) -> Snapshot:
        return cls(
            at=time.time() if at is None else at,
            take={c.index: c.pick for c in brief.choices},
            chance={c.index: round(c.chance, 4) for c in brief.choices},
            label={c.index: c.matchup for c in brief.choices},
            margin={c.index: c.home_margin for c in brief.choices if c.home_margin is not None},
            plain={c.index: (c.other if c.turned else c.pick) for c in brief.choices},
            planned=(
                {c.index: side for c, side in zip(brief.choices, brief.plan.take)}
                if brief.plan is not None and len(brief.plan.take) == len(brief.choices)
                else {}
            ),
            win_odds=(brief.win_odds if hasattr(brief, "win_odds")
                      else brief.plan.win_odds if brief.plan is not None else None),
            rebuilt=rebuilt,
        )

    @classmethod
    def load(cls, raw: object) -> Snapshot | None:
        if not isinstance(raw, dict):
            return None
        try:
            ints = lambda d: {int(k): v for k, v in (d or {}).items()}  # noqa: E731
            return cls(
                at=float(raw.get("at", 0)),
                take=ints(raw.get("take")),
                chance={k: float(v) for k, v in ints(raw.get("chance")).items()},
                label=ints(raw.get("label")),
                margin={k: float(v) for k, v in ints(raw.get("margin")).items()},
                plain=ints(raw.get("plain")),
                planned=ints(raw.get("planned")),
                win_odds=raw.get("win_odds"),
                rebuilt=bool(raw.get("rebuilt", False)),
            )
        except (TypeError, ValueError):
            return None


def _get(week: int, slot: str) -> Snapshot | None:
    return Snapshot.load(((_read().get("weeks") or {}).get(str(week)) or {}).get(slot))


def _teams(label: object) -> tuple[str, str] | None:
    """(away code, home code) from a kept label, "Tampa Bay @ Dallas"."""
    from .predictions import team_code
    text = str(label or "")
    if " @ " not in text:
        return None
    away, home = text.split(" @ ", 1)
    a, h = team_code(away), team_code(home)
    return (a, h) if a and h and a != h else None


def aligned(snap: Snapshot, slate: list[tuple[int, str, str]]) -> Snapshot:
    """The card with its games numbered as this slate numbers them.

    A card is kept by game number, and a week's numbering can change under
    it: a week the dashboard set up from the NFL's fixtures (first kickoff
    first) is numbered again in the commissioner's order once his sheet
    arrives. So each kept game is found again by its two teams - a game the
    slate no longer has is left out - and one kept without a label keeps its
    number. `slate` is (number, away, home) for each game.
    """
    from .predictions import team_code
    where = {}
    for index, away, home in slate:
        a, h = team_code(away), team_code(home)
        if a and h:
            where[frozenset((a, h))] = (index, a)
    move: dict[int, int] = {}
    flip: set[int] = set()
    for index in set(snap.take) | set(snap.chance) | set(snap.label):
        teams = _teams(snap.label.get(index))
        if teams is None:
            move[index] = index
            continue
        found = where.get(frozenset(teams))
        if found is None:
            continue
        move[index] = found[0]
        if found[1] != teams[0]:
            flip.add(index)             # home and away the other way round now
    if not flip and all(move.get(i) == i for i in set(snap.take) | set(snap.chance) | set(snap.label)):
        return snap

    def moved(values: dict, turn: bool = False) -> dict:
        return {move[i]: (-v if turn and i in flip else v) for i, v in values.items() if i in move}

    return replace(snap, take=moved(snap.take), chance=moved(snap.chance), label=moved(snap.label),
                   margin=moved(snap.margin, True), plain=moved(snap.plain),
                   planned=moved(snap.planned))


def _slate(games) -> list[tuple[int, str, str]]:
    return [(g.index, g.away, g.home) for g in games]


def _put(week: int, slot: str, snap: Snapshot | None) -> None:
    store = _read()
    entry = store.setdefault("weeks", {}).setdefault(str(week), {})
    if snap is None:
        entry.pop(slot, None)
    else:
        entry[slot] = asdict(snap)
    _write(store)


def mine(week: int) -> Snapshot | None:
    """The card you saved for this week, if any."""
    return _get(week, "mine")


def save_mine(week: int, brief) -> Snapshot:
    snap = Snapshot.of(brief)
    _put(week, "mine", snap)
    return snap


def forget_mine(week: int) -> None:
    _put(week, "mine", None)


def before_update(week: int) -> Snapshot | None:
    """The card as it stood just before the last "Update lines"."""
    return _get(week, "before_update")


def remember_before_update(week: int, brief) -> None:
    if brief is not None and brief.choices:
        _put(week, "before_update", Snapshot.of(brief))


def model(week: int) -> Snapshot | None:
    return _get(week, "model")


def week_started(season: Season, week: int) -> bool:
    found = season.weeks.get(week)
    return bool(found and any(g.played for g in found.games))


def record_model(season: Season, week: int, brief) -> bool:
    """Keep the model's card until the week's first game kicks off - the odds
    lock (oddslock.py) - or its first result is in, whichever comes first.

    A card planned against the pool's real pick sheet isn't kept: nobody can
    see everyone's picks before handing theirs in, so grading the model on
    one would flatter it. The card from before the sheet arrived stands.
    """
    if brief is None or not brief.choices or week_started(season, week):
        return False
    from . import oddslock
    if oddslock.locked_for(season, week):
        return False                      # kicked off: the card stands as it was
    plan = getattr(brief, "plan", None)
    if plan is not None and getattr(plan, "field_known", False):
        return False
    if getattr(brief, "counted_crowd", False):
        return False                      # the crowd was counted off the real sheet
    _put(week, "model", Snapshot.of(brief))
    return True


# ---- what changed -------------------------------------------------------------
@dataclass(frozen=True)
class Change:
    index: int
    kind: str          # "swap" | "moved"
    text: str


@dataclass(frozen=True)
class Changes:
    since: Snapshot
    what: str                          # "the card you saved" / "the last update"
    items: list[Change]
    win_odds_then: float | None
    win_odds_now: float | None

    @property
    def swaps(self) -> list[Change]:
        return [c for c in self.items if c.kind == "swap"]


def _line_note(label: str, then: float | None, now: float | None) -> str:
    from .odds import BIG_MOVE, describe_margin
    if then is None or now is None or abs(now - then) < BIG_MOVE:
        return ""
    return f" - line moved {describe_margin(label, then)} → {describe_margin(label, now)}"


def compare(brief, base: Snapshot, what: str) -> Changes:
    """How the card made now differs from an earlier one."""
    items = []
    base = aligned(base, [(c.index, *(_teams(c.matchup) or ("", ""))) for c in brief.choices])
    for c in brief.choices:
        then_side = base.take.get(c.index)
        if then_side is None:
            continue
        then_chance = base.chance.get(c.index)
        # the chance of the side you had, as things stand now
        now_of_then = c.chance if same_team(then_side, c.pick) else 1 - c.chance
        note = _line_note(c.matchup, base.margin.get(c.index), c.home_margin)
        if not same_team(then_side, c.pick):
            why = (
                f"{then_side} {then_chance:.0%} → {now_of_then:.0%}"
                if then_chance is not None else f"{then_side} now {now_of_then:.0%}"
            )
            items.append(Change(
                c.index, "swap",
                f"Swap {then_side} → {c.pick} ({c.matchup}): {why}, "
                f"{c.pick} now {c.chance:.0%}"
                + (", and the card now takes it against the pool" if c.turned else "")
                + note,
            ))
        elif then_chance is not None:
            moved = c.chance - then_chance
            crossed = (then_chance >= 0.5) != (c.chance >= 0.5)
            if crossed or abs(moved) >= MOVE_WORTH_NOTING:
                items.append(Change(
                    c.index, "moved",
                    f"{c.pick} ({c.matchup}): {then_chance:.0%} → {c.chance:.0%}, "
                    f"still the card's side" + note,
                ))
    items.sort(key=lambda ch: (ch.kind != "swap", ch.index))
    return Changes(
        since=base, what=what, items=items,
        win_odds_then=base.win_odds,
        win_odds_now=(brief.win_odds if hasattr(brief, "win_odds")
                      else brief.plan.win_odds if brief.plan is not None else None),
    )


def changes(week: int, brief) -> Changes | None:
    """Against your saved card if there is one, else the card before the last update."""
    if brief is None or not brief.choices:
        return None
    saved = mine(week)
    if saved is not None:
        return compare(brief, saved, "the card you saved")
    earlier = before_update(week)
    if earlier is not None:
        return compare(brief, earlier, "the card before the last line update")
    return None


# ---- how the model's card has done ------------------------------------------
@dataclass(frozen=True)
class WeekScore:
    week: int
    games: int                  # games graded on the model's card
    model: int                  # the model's card: the likeliest side of every game
    planned: int                # the card built to finish first (the old default)
    mine: int | None            # your regular wins that week
    best: int                   # the best regular score in the pool
    model_place: int            # where the model's card would have finished
    model_tied: int             # coaches level with it
    entrants: int
    rebuilt: bool

    @property
    def model_would_win(self) -> bool:
        return self.model_place == 1


def _hits(snap_take: dict[int, str], week) -> tuple[int, int]:
    right = graded = 0
    for game in week.games:
        side = snap_take.get(game.index)
        if side is None or not game.played:
            continue
        graded += 1
        right += 1 if same_team(side, game.winner) else 0
    return right, graded


def score_week(season: Season, week_number: int, coach_key: str | None,
               snap: Snapshot) -> WeekScore | None:
    week = season.weeks.get(week_number)
    if week is None or not week.scored:
        return None
    snap = aligned(snap, _slate(week.games))
    # The model's card is the one This Week recommends: the likeliest side of
    # every game, whichever card the page happened to be showing.
    model_hits, graded = _hits(snap.plain or snap.take, week)
    if not graded:
        return None
    planned_hits, _ = _hits(snap.planned or snap.take, week)
    regular = [line.regular_wins or 0 for line in week.lines.values()]
    me = week.lines.get(coach_key) if coach_key else None
    return WeekScore(
        week=week_number, games=graded, model=model_hits, planned=planned_hits,
        mine=(me.regular_wins or 0) if me is not None else None,
        best=max(regular, default=0),
        model_place=1 + sum(1 for r in regular if r > model_hits),
        model_tied=sum(1 for r in regular if r == model_hits),
        entrants=len(regular),
        rebuilt=snap.rebuilt,
    )


def history(season: Season, coach_key: str | None, *, rebuild: bool = True) -> list[WeekScore]:
    """Every graded week's model card against yours, oldest first.

    Weeks from before this was added have no card kept; with `rebuild` they
    are made again from the stored lines and marked as rebuilt - the same
    model on the lines as they were last stored, which is usually the
    closing line, so a little kinder to it than the real Wednesday card.
    """
    out = []
    for number in sorted(season.weeks):
        week = season.weeks[number]
        if not week.scored:
            continue
        snap = model(number)
        if snap is None and rebuild:
            snap = _rebuild(season, number)
        if snap is None:
            continue
        found = score_week(season, number, coach_key, snap)
        if found is not None:
            out.append(found)
    return out


def _rebuild(season: Season, week: int) -> Snapshot | None:
    from . import briefing, predictions
    if not predictions.load(week)[0]:
        return None
    try:
        brief = briefing.build(season, week, use_sheet=False)
    except Exception:  # noqa: BLE001 - an old week that can't be priced is skipped
        return None
    if not brief.choices:
        return None
    snap = Snapshot.of(brief, rebuilt=True)
    _put(week, "model", snap)
    return snap


@dataclass(frozen=True)
class Record:
    weeks: int
    model_total: int
    planned_total: int
    mine_total: int | None
    model_wins: int             # weeks the model's card would have won outright or tied
    mine_better: int
    model_better: int

    def sentence(self, coach: str) -> str:
        if not self.weeks:
            return f"No graded weeks with a card from {MODEL_NAME} yet."
        text = (
            f"Over {self.weeks} week{'s' if self.weeks != 1 else ''} {MODEL_NAME}'s card got "
            f"{self.model_total} right; the card built to finish first {self.planned_total}"
        )
        if self.mine_total is not None:
            text += f"; {coach} {self.mine_total}"
            text += (
                f". {MODEL_NAME} beat {coach} in {self.model_better}, "
                f"{coach} beat it in {self.mine_better}"
            )
        text += (
            f". It would have had the week's best regular score "
            f"{self.model_wins} time{'s' if self.model_wins != 1 else ''}."
        )
        return text


# ---- your own calls: the games where you went against the model's card -------
@dataclass(frozen=True)
class Call:
    week: int
    index: int
    game: str                   # "Minnesota @ Chicago"
    mine: str                   # the side you took
    model: str                  # the side the model's card took
    chance: float | None        # the model's chance its side would be credited
    paid: bool                  # True when your side was the one credited
    rebuilt: bool               # the model's card was re-made after the fact


def _other_side(game, team: str) -> str:
    if same_team(team, game.home):
        return game.away
    if same_team(team, game.away):
        return game.home
    return ""


def my_calls(season: Season, coach_key: str | None, *, rebuild: bool = True) -> list[Call]:
    """Every played game where the coach's side differed from the model's
    card, oldest first. A graded sheet keeps only the right picks, so a game
    missing from the coach's line means they had the other side."""
    from .predictions import display_team
    out: list[Call] = []
    if not coach_key:
        return out
    for number in sorted(season.weeks):
        week = season.weeks[number]
        line = week.lines.get(coach_key)
        if line is None or not week.scored:
            continue
        if not line.correct_picks and not line.regular_wins:
            continue                           # no card handed in that week
        snap = model(number)
        if snap is None and rebuild:
            snap = _rebuild(season, number)
        if snap is None:
            continue
        snap = aligned(snap, _slate(week.games))
        take = snap.plain or snap.take
        for game in sorted(week.games, key=lambda g: g.index):
            side = take.get(game.index)
            if side is None or not game.played:
                continue
            model_right = same_team(side, game.winner)
            pick = line.correct_picks.get(game.index) or ""
            mine_right = same_team(pick, game.winner)
            if mine_right == model_right:
                continue                       # same side as the model
            if pick:
                mine = pick
            else:
                mine = _other_side(game, game.winner if model_right else side)
            if not mine:
                continue
            # The kept chance is for the side the page showed; the model's
            # card is the likeliest side, so turn it round where they differ.
            chance = snap.chance.get(game.index)
            if chance is not None and not same_team(snap.take.get(game.index, side), side):
                chance = 1 - chance
            out.append(Call(
                week=number, index=game.index,
                game=snap.label.get(game.index) or game.label,
                mine=display_team(mine), model=display_team(side),
                chance=chance,
                paid=mine_right, rebuilt=snap.rebuilt,
            ))
    return out


@dataclass(frozen=True)
class CallRecord:
    calls: int
    paid: int

    @property
    def cost(self) -> int:
        return self.calls - self.paid

    @property
    def net(self) -> int:
        """Wins your own calls made you against playing the model's card."""
        return self.paid - self.cost

    def sentence(self, coach: str, weeks: int) -> str:
        if not self.calls:
            return (f"{coach} has played {MODEL_NAME}'s card game for game"
                    + (f" over {weeks} week{'s' if weeks != 1 else ''}." if weeks else "."))
        net = self.net
        verdict = ("adding " + _count(net, "win") if net > 0 else
                   "costing " + _count(-net, "win") if net < 0 else "breaking even")
        return (f"{coach}'s own calls: {_count(self.calls, 'game')} against {MODEL_NAME}'s card, "
                f"{self.paid} came in and {self.cost} didn't - so far they are {verdict} "
                f"against playing its card.")


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def call_record(calls: list[Call]) -> CallRecord:
    return CallRecord(calls=len(calls), paid=sum(1 for c in calls if c.paid))


def record(scores: list[WeekScore]) -> Record:
    mine_scores = [s for s in scores if s.mine is not None]
    return Record(
        weeks=len(scores),
        model_total=sum(s.model for s in scores),
        planned_total=sum(s.planned for s in scores),
        mine_total=sum(s.mine for s in mine_scores) if mine_scores else None,
        model_wins=sum(1 for s in scores if s.model_would_win),
        mine_better=sum(1 for s in mine_scores if s.mine > s.model),
        model_better=sum(1 for s in mine_scores if s.model > s.mine),
    )
