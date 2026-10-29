"""python -m acql.integrity  run | status | center | recover

    run       load the season (nothing fetched) and validate it now
    status    the last run, without running
    center    open the Integrity Center on http://127.0.0.1:8766/
    recover   reload from the files and validate again after a failed run
"""

from __future__ import annotations

import sys


def _print(d: dict) -> None:
    print(f"State: {d.get('state')}   health {d.get('health')}/100   complete: {d.get('complete')}   "
          f"through week {d.get('through_week')} (official through {d.get('official_week')})")
    for name, c in (d.get("checks") or {}).items():
        print(f"  {'ok ' if c.get('ran') else 'ERR'} {c.get('label', name)}: {c.get('verified')} verified"
              + (f" - {c['error']}" if c.get("error") else ""))
    for f in d.get("findings") or []:
        print(f"  [{f['status']}/{f['severity']}] {f['title']}")
        if f.get("detail"):
            print(f"      {f['detail']}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    what = args[0] if args else "status"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    from . import center, engine, history
    if what == "center":
        return center.main(args[1:])
    if what == "run":
        d = history.ensure(center.load_season(), force=True)
    elif what == "recover":
        d = history.recover(center.load_season)
    elif what == "status":
        d = history.last()
        if not d:
            print("The integrity checks haven't run yet: python -m acql.integrity run")
            return 1
    else:
        print(__doc__)
        return 2
    _print(d)
    gate = engine.publish_gate(d)
    if gate:
        print("\nNot verified as official: " + "; ".join(gate))
    return 0 if d.get("state") == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
