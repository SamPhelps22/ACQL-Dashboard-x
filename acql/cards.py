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
from dataclasses import asdict, dataclass, field

from .models import Season, same_team

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
    """Keep the model's card, until the week's first result locks it.

    A card planned against the pool's real pick sheet isn't kept: nobody can
    see everyone's picks before handing theirs in, so grading the model on
    one would flatter it. The card from before the sheet arrived stands.
    """
    if brief is None or not brief.choices or week_started(season, week):
        return False
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
    model: int
    plain: int                  # the likeliest side of every game
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
    # The model's card is the planner's, whichever card the page was showing.
    model_hits, graded = _hits(snap.planned or snap.take, week)
    if not graded:
        return None
    plain_hits, _ = _hits(snap.plain or snap.take, week)
    regular = [line.regular_wins or 0 for line in week.lines.values()]
    me = week.lines.get(coach_key) if coach_key else None
    return WeekScore(
        week=week_number, games=graded, model=model_hits, plain=plain_hits,
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
    plain_total: int
    mine_total: int | None
    model_wins: int             # weeks the model's card would have won outright or tied
    mine_better: int
    model_better: int

    def sentence(self, coach: str) -> str:
        if not self.weeks:
            return "No graded weeks with a model card yet."
        text = (
            f"Over {self.weeks} week{'s' if self.weeks != 1 else ''} the model's card got "
            f"{self.model_total} right; the likeliest-side card {self.plain_total}"
        )
        if self.mine_total is not None:
            text += f"; {coach} {self.mine_total}"
            text += (
                f". The model beat {coach} in {self.model_better}, "
                f"{coach} beat it in {self.mine_better}"
            )
        text += (
            f". It would have had the week's best regular score "
            f"{self.model_wins} time{'s' if self.model_wins != 1 else ''}."
        )
        return text


def record(scores: list[WeekScore]) -> Record:
    mine_scores = [s for s in scores if s.mine is not None]
    return Record(
        weeks=len(scores),
        model_total=sum(s.model for s in scores),
        plain_total=sum(s.plain for s in scores),
        mine_total=sum(s.mine for s in mine_scores) if mine_scores else None,
        model_wins=sum(1 for s in scores if s.model_would_win),
        mine_better=sum(1 for s in mine_scores if s.mine > s.model),
        model_better=sum(1 for s in mine_scores if s.model > s.mine),
    )
