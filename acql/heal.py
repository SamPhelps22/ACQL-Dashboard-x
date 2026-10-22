"""Catch up scheduled jobs that were missed while the computer was off (idea #63).

When the dashboard opens, any job that is safe to run late and is overdue gets
started through Task Scheduler itself (`schtasks /Run`), so it runs exactly as
it would on schedule. Jobs whose point is their timing are left alone: the card
email after the deadline would be stale, the game-day poll off a game day does
nothing, and the Sunday brief belongs to Sunday.
"""

from __future__ import annotations

import time

from . import readiness

#: The jobs it is safe to run late.
CATCH_UP = ("ACQL Daily", "ACQL Training")
#: A job started here is not started again for this long.
RETRY = 12 * 3600


def overdue(states: dict[str, dict] | None, now: float) -> list[str]:
    """The catch-up jobs that are set up but haven't run within their limit."""
    if not states:
        return []
    limits = {name: limit for name, _what, limit in readiness.TASKS}
    out = []
    for name in CATCH_UP:
        found = states.get(name) or {}
        if not found.get("found"):
            continue
        last, coming = found.get("last"), found.get("next")
        if last is None:
            late = coming is None or coming - now > limits[name]   # never ran and not about to
        else:
            late = now - last > limits[name]
        if late:
            out.append(name)
    return out


def catch_up(states: dict[str, dict] | None = None, now: float | None = None, run=None) -> list[str]:
    """Start each overdue catch-up job (not one started in the last 12 hours).
    `run(name)` starts it; by default Task Scheduler does. Returns what was started."""
    from . import store
    now = time.time() if now is None else now
    if states is None:
        states = readiness.task_states()
    try:
        tried = dict(store.get("heal", "started", {}) or {})
    except Exception:  # noqa: BLE001
        tried = {}
    started = []
    for name in overdue(states, now):
        if now - float(tried.get(name, 0) or 0) < RETRY:
            continue
        try:
            (run or _schtasks)(name)
        except Exception as exc:  # noqa: BLE001 - one job not starting must not stop the rest
            _log(f"catch-up: {name} not started: {exc}")
            continue
        tried[name] = now
        started.append(name)
        last = (states.get(name) or {}).get("last")
        _log(f"catch-up: {name} was overdue ({readiness.ago(now - last) if last else 'never ran'}) - started it")
    if started:
        try:
            store.put("heal", "started", tried)
        except Exception:  # noqa: BLE001
            pass
    return started


def _schtasks(name: str) -> None:
    import subprocess
    done = subprocess.run(["schtasks", "/Run", "/TN", name], capture_output=True, text=True, timeout=15,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0:
        raise OSError((done.stderr or done.stdout).strip() or f"schtasks exit {done.returncode}")


def _log(text: str) -> None:
    try:
        from .ui.pages.base import write_log
        write_log(text)
    except Exception:  # noqa: BLE001
        pass
