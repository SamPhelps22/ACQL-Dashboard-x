"""The self-check: every page, drawn on the real data, photographed whole.

Changes to the dashboard are made somewhere that can't draw a Qt window,
so until now the first time anyone saw a changed page was on this computer
- which is how stretched charts and cramped cards got through. This closes
that gap from the other end: it opens every page and tab in turn, lets it
finish drawing, and saves a picture of the whole page (not just the part on
screen), plus a report of anything that looks wrong:

  * a page that failed to draw, and where;
  * content wider than the window (it would be cut off - pages don't scroll
    sideways);
  * a table that needs a sideways scroll bar inside its card;
  * a chart drawn at a strange size;
  * a page that took more than a second to draw.

Everything lands in one zip in data/selfcheck/, ready to send. Run it from
Ctrl+K ("Run self-check"), from Data & Update, or with
`ACQL Dashboard.bat --selfcheck`.
"""

from __future__ import annotations

import json
import platform
import sys
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import QElapsedTimer
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QTableView, QWidget

#: How long each page is given to finish drawing before it is photographed.
SETTLE_MS = 450
SLOW_MS = 1000
#: A chart this much taller than wide (or flatter than this) is worth a look.
CHART_TALL, CHART_FLAT = 1.4, 0.18


@dataclass
class PageReport:
    group: str
    tab: str
    title: str
    ms: int
    state: str                        # "content", "empty", "failed"
    image: str = ""
    width: int = 0
    height: int = 0
    problems: list[str] = field(default_factory=list)


def _settle(ms: int = SETTLE_MS) -> None:
    timer = QElapsedTimer()
    timer.start()
    app = QApplication.instance()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.01)


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text).strip("-").lower()


def _inspect(page, report: PageReport) -> None:
    """Heuristic look for the layout problems that have bitten before."""
    content = getattr(page, "_content", None)
    scroll = getattr(page, "_scroll", None)
    if content is not None and scroll is not None:
        view = scroll.viewport().width()
        if content.width() > view + 2:
            report.problems.append(
                f"content is {content.width()}px wide in a {view}px window - the right edge is cut off"
            )
    for table in page.findChildren(QTableView):
        if not table.isVisible():
            continue
        bar = table.horizontalScrollBar()
        if bar is not None and bar.isVisible() and bar.maximum() > 0:
            report.problems.append(
                f"a table needs a sideways scroll bar ({table.width()}px shown, "
                f"{table.width() + bar.maximum()}px wanted)"
            )
    for canvas in page.findChildren(QWidget):
        if type(canvas).__name__ != "FigureCanvasQTAgg" or not canvas.isVisible():
            continue
        w, h = canvas.width(), canvas.height()
        if w <= 0:
            continue
        ratio = h / w
        if ratio > CHART_TALL or ratio < CHART_FLAT:
            report.problems.append(f"a chart is drawn {w}x{h}px - an odd shape")
    for area in page.findChildren(QAbstractScrollArea):
        if area is scroll or isinstance(area, QTableView) or not area.isVisible():
            continue
        bar = area.horizontalScrollBar()
        if bar is not None and bar.isVisible() and bar.maximum() > 0:
            report.problems.append("a box inside the page needs a sideways scroll bar")


def _environment(window) -> dict:
    from .. import store
    try:
        from ..version import VERSION
    except Exception:  # noqa: BLE001
        VERSION = "?"
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        qt = f"PySide6 {PySide6.__version__} / Qt {qVersion()}"
    except Exception:  # noqa: BLE001
        qt = "?"
    season = getattr(window, "season", None)
    screen = QApplication.primaryScreen()
    try:
        memory = store.kinds()
    except Exception as exc:  # noqa: BLE001
        memory = {"error": str(exc)}
    return {
        "version": VERSION,
        "python": sys.version.split()[0],
        "qt": qt,
        "os": platform.platform(),
        "screen": (
            f"{screen.size().width()}x{screen.size().height()} at "
            f"{screen.devicePixelRatio():g}x" if screen else "?"
        ),
        "window": f"{window.width()}x{window.height()}",
        "theme": getattr(window.palette_, "name", "?"),
        "data_folder": str(store.data_dir()),
        "memory": memory,
        "players": len(season.players) if season else 0,
        "weeks": sorted(season.weeks) if season else [],
        "warnings": list(getattr(season, "warnings", []) or [])[:20],
    }


def run(window, folder: Path | None = None, *, say=None) -> Path:
    """Photograph every page and tab, write the report, zip it. Returns the zip."""
    from .. import store

    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = Path(folder) if folder else store.data_dir() / "selfcheck" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    start_group = window.stack.currentIndex()
    start_tabs = [g.current_index() for g in window.groups]

    reports: list[PageReport] = []
    shot = 0
    for g, group in enumerate(window.groups):
        for t, page in enumerate(group.pages):
            label = group.spec.tabs[t][0]
            if say:
                say(f"{group.title} › {label}")
            timer = QElapsedTimer()
            timer.start()
            try:
                window._select_page(g, t)
                _settle()
            except Exception as exc:  # noqa: BLE001 - the report says what broke
                reports.append(PageReport(group.title, label, page.title, 0, "failed",
                                          problems=[f"couldn't open: {exc}"]))
                continue
            ms = max(0, timer.elapsed() - SETTLE_MS)
            views = getattr(page, "_page_views", None)
            showing_content = views is None or views.currentIndex() == 0
            state = "failed" if page.failure else ("content" if showing_content else "empty")
            report = PageReport(group.title, label, page.title, ms, state)
            if page.failure:
                report.problems.append(page.failure.strip().splitlines()[-1])
            if ms > SLOW_MS:
                report.problems.append(f"took {ms} ms to draw")
            try:
                _inspect(page, report)
            except Exception as exc:  # noqa: BLE001
                report.problems.append(f"couldn't inspect the layout: {exc}")
            shot += 1
            target = page._content if showing_content and hasattr(page, "_content") else page
            try:
                picture = target.grab()
                name = f"{shot:02d}-{_safe(group.title)}-{_safe(label)}.png"
                picture.save(str(folder / name), "PNG")
                report.image, report.width, report.height = name, picture.width(), picture.height()
            except Exception as exc:  # noqa: BLE001
                report.problems.append(f"couldn't save a picture: {exc}")
            reports.append(report)

    # one of the whole window, for the frame around the pages
    try:
        window._select_page(start_group)
        for g, tab in enumerate(start_tabs):
            window.groups[g].select(tab)
        _settle(150)
        window.grab().save(str(folder / "00-window.png"), "PNG")
    except Exception:  # noqa: BLE001
        pass

    env = _environment(window)
    try:
        from .. import checks
        sums = checks.run_all()
    except Exception as exc:  # noqa: BLE001
        sums = []
        env["checks_error"] = str(exc)
    problems = sum(len(r.problems) for r in reports) + sum(1 for c in sums if not c.ok)
    lines = [
        f"ACQL Dashboard self-check - {time.strftime('%A %d %B %Y, %H:%M')}",
        f"Version {env['version']} · Python {env['python']} · {env['qt']}",
        f"{env['os']} · screen {env['screen']} · window {env['window']} · {env['theme']} theme",
        f"{env['players']} players · weeks {env['weeks']}",
        f"Memory: {env['memory']}",
        "",
        f"{len(reports)} pages, {problems} thing(s) to look at",
        "",
    ]
    for r in reports:
        mark = "OK " if not r.problems and r.state == "content" else "!! "
        lines.append(f"{mark}{r.group} > {r.tab}  ({r.state}, {r.ms} ms, {r.width}x{r.height})")
        for p in r.problems:
            lines.append(f"      - {p}")
    if sums:
        lines += ["", "The sums behind the pages:"]
        lines += [f"{'OK ' if c.ok else '!! '}{c.name}: {c.detail}" for c in sums]
    if env["warnings"]:
        lines += ["", "Warnings from loading:"] + [f"  - {w}" for w in env["warnings"]]
    (folder / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "report.json").write_text(
        json.dumps({"environment": env, "pages": [asdict(r) for r in reports],
                    "checks": [asdict(c) for c in sums]}, indent=1),
        encoding="utf-8",
    )
    try:
        from .pages.base import log_path
        log = log_path()
        if log.is_file():
            (folder / "acql-log-tail.txt").write_text(
                log.read_text(encoding="utf-8", errors="replace")[-30_000:], encoding="utf-8"
            )
    except Exception:  # noqa: BLE001
        pass

    archive = folder.parent / f"selfcheck-{stamp}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.iterdir()):
            zf.write(path, path.name)
    return archive


def summary(archive: Path) -> tuple[int, int]:
    """(pages, problems) from a finished self-check, for the message afterwards."""
    try:
        with zipfile.ZipFile(archive) as zf:
            raw = json.loads(zf.read("report.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return 0, 0
    pages = raw.get("pages", [])
    failed = sum(1 for c in raw.get("checks", []) if not c.get("ok"))
    return len(pages), sum(len(p.get("problems", [])) for p in pages) + failed
