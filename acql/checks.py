"""Quick checks that the arithmetic still adds up on this computer.

The self-check photographs the pages; this checks the sums behind them - a
different numpy, a Python upgrade or a damaged file shows up here as a named
failure instead of as a quietly wrong chance on a page. Nothing here touches
the real data: the database checks run on a scratch copy in a temp folder.

    python -m acql.checks        (from the project folder)
"""

from __future__ import annotations

import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    detail: str = ""


def _check_chances() -> str:
    from . import analytics
    three, seven, ten = (analytics.win_chance(x) for x in (3, 7, 10))
    assert 0.58 < three < 0.64, f"3-point favourite {three:.3f}"
    assert 0.71 < seven < 0.78, f"7-point favourite {seven:.3f}"
    assert 0.78 < ten < 0.85, f"10-point favourite {ten:.3f}"
    assert analytics.cover_chance(7, 8) < analytics.cover_chance(7, 7) < analytics.cover_chance(7, 4)
    return f"3 {three:.1%}, 7 {seven:.1%}, 10 {ten:.1%}"


def _check_pool_line() -> str:
    from . import luck
    # the favourite has to win by MORE than the line: an 8-point line on a
    # 7-point favourite makes the underdog the likelier side
    fav = luck.favourite_covers(7.0, 8.0)
    assert fav < 0.5, f"favourite covers an 8-point line {fav:.3f}"
    # the market's underdog, made the pool's favourite, is a long shot to cover
    long_shot = luck.favourite_covers(-3.0, 7.0)
    assert long_shot < 0.3, f"market underdog covering a 7-point pool line {long_shot:.3f}"
    return f"7-point favourite against a pool line of 8: {fav:.1%}"


def _check_store() -> str:
    from . import store
    folder = Path(tempfile.mkdtemp(prefix="acql-check-"))
    # Held throughout, so nothing else in the app (a reload on its own
    # thread) can read or write while the store points at the scratch copy.
    with store._LOCK:
        previous = store._OVERRIDE
        try:
            store.use(folder / "check.db")
            store.put("check", "a", {"x": 1})
            store.replace("check", {"a": {"x": 2}, "b": [1, 2]})
            assert store.get("check", "a") == {"x": 2}
            assert sorted(store.items("check")) == ["a", "b"]
            store.delete("check", "b")
            assert list(store.items("check")) == ["a"]
        finally:
            store.use(previous)
    return "save, replace, read and delete on a scratch database"


def _check_pricing() -> str:
    from . import lines, predictions, pricing
    from .models import Game
    game = Game(1, "Kansas City", "Denver")
    forecast = predictions.Forecast("Denver", "Kansas City", market=6.5, opening=5.5,
                                    opinions=(9.0, 8.5, 8.0, 9.5, 8.0, 9.0))
    ctx = pricing.Context(1, {1: forecast}, 0.0, 1.0, predictions.CONSENSUS_WEIGHT)
    plain = pricing.price(game, ctx)
    assert plain.base == 6.5 and plain.margin > 6.5, (plain.base, plain.margin)
    typed = pricing.price(game, ctx, lines.Spread("home", 3.0), typed=True)
    assert typed.base == 3.0, typed.base
    alone = pricing.price(game, pricing.Context(1), lines.Spread("away", 2.5))
    assert alone.margin == -2.5 and alone.source == "Vegas"
    return (f"market 6.5 + models -> {plain.margin:.2f}; a typed 3 wins -> "
            f"{typed.margin:.2f}; no file -> {alone.margin:+.1f}")


def _check_planner() -> str:
    from . import weekplan
    choices = [
        weekplan.Choice(f"G{i}", f"A{i}", f"B{i}", 0.5 + 0.02 * (i % 10), 0.55 + 0.03 * (i % 12))
        for i in range(16)
    ]
    plan = weekplan.plan_week(choices, coaches=34, sims=4000)
    assert plan is not None and len(plan.take) == 16
    assert plan.win_odds >= plan.plain_win_odds - 0.01, (plan.win_odds, plan.plain_win_odds)
    assert len(plan.flip_odds) == 16
    return f"finishes first {plan.win_odds:.1%} against {plan.plain_win_odds:.1%} straight"


def _check_suicide_rules() -> str:
    from . import survivor
    unlined = survivor.survive_chance(6.0, survivor.assumed_line(6.0), True)
    lined = survivor.survive_chance(10.0, survivor.assumed_line(10.0), True)
    assert unlined > 0.66 and lined < 0.55, (unlined, lined)
    return f"6-point favourite {unlined:.0%}, 10-point favourite under a line {lined:.0%}"


def _check_first_place() -> str:
    from . import backtest
    alone = backtest.chance_first(10, [0.5] * 16, others=0)
    assert abs(alone - 1.0) < 1e-9, alone
    tie = backtest.chance_first(16, [1.0] * 16, others=1)
    assert abs(tie - 0.5) < 1e-9, tie
    return "a lone card always wins; a two-way tie pays half"


def _check_updater() -> str:
    from . import updater
    assert updater.version_tuple("2.10.0") > updater.version_tuple("2.9.9")
    assert updater.UPDATE_NAME.search("ACQL-Dashboard-2.0.0-update.zip")
    return "version order and update file names"


CHECKS = (
    ("Win chances by the spread", _check_chances),
    ("The pool's line rule", _check_pool_line),
    ("The app's database", _check_store),
    ("Pricing a game", _check_pricing),
    ("The win-the-week planner", _check_planner),
    ("The suicide pool rules", _check_suicide_rules),
    ("Finishing first, ties shared", _check_first_place),
    ("The updater", _check_updater),
)


def run_all() -> list[Result]:
    out = []
    for name, check in CHECKS:
        try:
            out.append(Result(name, True, check()))
        except Exception as exc:  # noqa: BLE001 - every failure is a result
            where = traceback.extract_tb(exc.__traceback__)[-1]
            out.append(Result(name, False, f"{type(exc).__name__}: {exc} "
                                           f"({Path(where.filename).name}, line {where.lineno})"))
    return out


if __name__ == "__main__":
    results = run_all()
    for r in results:
        print(f"  {'ok ' if r.ok else 'FAIL'} {r.name}: {r.detail}")
    failed = sum(not r.ok for r in results)
    print(f"\n  {len(results) - failed} of {len(results)} checks passed")
    raise SystemExit(1 if failed else 0)
