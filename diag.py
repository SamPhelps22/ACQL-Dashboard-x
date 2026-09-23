"""Why is a coach on zero?

Drop this next to run.py, in the Code x folder, and run it:

    python diag.py

It loads the season exactly as the dashboard does and then says, for every
coach, where their numbers came from - which file mentions them, which weeks
they have, and what each week of the workbook actually gave them. Nothing is
written; it only reads and prints.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from acql.config import Settings           # noqa: E402
from acql.names import AliasTable          # noqa: E402
from acql.repository import load_season    # noqa: E402
from acql import picks                     # noqa: E402


def main() -> int:
    aliases = AliasTable.load()
    season = load_season(Settings.load(), aliases)
    try:
        picks.attach(season, key_for=aliases.key)
    except Exception as exc:                          # noqa: BLE001
        print(f"(pick sheets not attached: {exc})")

    print(f"\nFILES FOUND ({len(season.sources)})")
    for s in season.sources:
        print(f"    {s.path.name:<34} kind={s.kind!r} week={s.week} {s.error or ''}")

    print(f"\nWEEKS ({len(season.weeks)})")
    for number in sorted(season.weeks):
        week = season.weeks[number]
        scores = [l.total_wins for l in week.lines.values()]
        decided = sum(1 for g in week.games if str(getattr(g, "winner", "") or "").strip())
        print(f"    week {number:<2} {len(week.lines):>2} coaches  "
              f"{len(week.games):>2} games ({decided} with a result)  "
              f"scores {min(scores) if scores else '-'}..{max(scores) if scores else '-'}  "
              f"source={'workbook' if getattr(week, 'source', None) else 'pick sheet'}")

    zero = [p for p in season.players.values() if not p.wins]
    print(f"\nCOACHES: {len(season.players)} total, {len(zero)} on zero wins")

    print("\nEVERY COACH")
    print(f"    {'name':<20} {'wins':>5} {'pos':>4}  weeks       sources")
    for person in sorted(season.players.values(), key=lambda p: (-p.wins, p.display.lower())):
        weeks = ",".join(str(w) for w in sorted(person.weekly_wins)) or "-"
        where = ", ".join(sorted(person.sources)) or "NOWHERE"
        print(f"    {person.display:<20} {person.wins:>5} {str(person.pos):>4}  "
              f"{weeks:<11} {where}")

    if zero:
        print("\nTHE FIRST FEW ON ZERO, IN DETAIL")
        for person in zero[:5]:
            print(f"\n  {person.display!r}  key={person.key!r}")
            print(f"      sources      : {sorted(person.sources) or 'none'}")
            print(f"      weekly_wins  : {dict(sorted(person.weekly_wins.items())) or 'empty'}")
            print(f"      provisional  : {dict(sorted(person.provisional_wins.items())) or 'empty'}")
            for number in sorted(season.weeks):
                line = season.weeks[number].lines.get(person.key)
                if line is not None:
                    print(f"      week {number:<2} line : total={line.total_wins} "
                          f"regular={line.regular_wins} picks_kept={len(line.correct_picks)} "
                          f"big_losers={line.big_loser_wins}")
            for number in sorted(season.weeks):
                keys = season.weeks[number].lines
                if person.key not in keys and keys:
                    near = [k for k in keys if person.display.casefold()[:4] in k]
                    if near:
                        print(f"      week {number}: not under this key, but {near} look close")

    print(f"\nprovisional weeks : {season.provisional_weeks or 'none'}")
    print(f"computed winnings : {getattr(season, 'computed_winnings', []) or 'none'}")
    print(f"current week      : {season.current_week}")
    if season.warnings:
        print(f"\nWARNINGS ({len(season.warnings)})")
        for w in season.warnings[:12]:
            print(f"    - {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
