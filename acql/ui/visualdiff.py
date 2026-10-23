"""What moved on each page since the last release (idea #4).

The self-check photographs every page. This compares each photograph with
the same page from the last release's self-check and draws red boxes around
the regions that changed, with a change score per page, so a stretched chart
or a cramped card shows up without reading every picture side by side.

Baselines live beside the self-checks: data/selfcheck/baseline-<version>/.
Each run compares against the newest baseline from a different version (the
last release) and then keeps its own pictures as this version's baseline.

Pillow only; no Qt.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

#: A pixel whose colour moved by more than this (0-255, any channel) has changed:
#: below it is font smoothing and the like.
TOLERANCE = 40
#: The page is looked at in squares this size; a square counts as changed when
#: more than this share of its pixels did.
CELL, CELL_SHARE = 24, 0.02
#: A page whose change score is under this is reported as unchanged.
QUIET = 0.002


@dataclass
class PageDiff:
    key: str                         # the page's picture name without its running number
    score: float                     # share of the page's squares that changed
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    size_note: str = ""
    picture: str = ""                # the marked-up picture written beside the run's


def key_of(name: str) -> str:
    """'07-Results-Standings.png' -> 'Results-Standings.png'."""
    head, _, rest = name.partition("-")
    return rest if head.isdigit() and rest else name


def changed_cells(old, new) -> tuple[list[tuple[int, int]], int, int]:
    """Squares that changed between two same-size images: ([(col, row)], cols, rows)."""
    from PIL import ImageChops
    diff = ImageChops.difference(old.convert("RGB"), new.convert("RGB")).convert("L")
    mask = diff.point(lambda v: 255 if v > TOLERANCE else 0)
    width, height = mask.size
    cols, rows = (width + CELL - 1) // CELL, (height + CELL - 1) // CELL
    out = []
    for r in range(rows):
        for c in range(cols):
            box = (c * CELL, r * CELL, min(width, (c + 1) * CELL), min(height, (r + 1) * CELL))
            area = (box[2] - box[0]) * (box[3] - box[1])
            lit = mask.crop(box).histogram()[255]
            if area and lit / area > CELL_SHARE:
                out.append((c, r))
    return out, cols, rows


def boxes(cells: list[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """Touching changed squares joined into rectangles (pixel boxes)."""
    left = set(cells)
    out = []
    while left:
        start = left.pop()
        group, todo = {start}, [start]
        while todo:
            c, r = todo.pop()
            for nc, nr in ((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1), (c + 1, r + 1), (c - 1, r - 1),
                           (c + 1, r - 1), (c - 1, r + 1)):
                if (nc, nr) in left:
                    left.discard((nc, nr))
                    group.add((nc, nr))
                    todo.append((nc, nr))
        cs = [c for c, _ in group]
        rs = [r for _, r in group]
        out.append((min(cs) * CELL, min(rs) * CELL, (max(cs) + 1) * CELL, (max(rs) + 1) * CELL))
    return sorted(out, key=lambda b: (b[1], b[0]))


def compare(old_path: Path, new_path: Path, out_path: Path | None = None) -> PageDiff:
    from PIL import Image, ImageDraw
    old, new = Image.open(old_path), Image.open(new_path)
    note = ""
    if old.size != new.size:
        note = f"size changed from {old.size[0]}x{old.size[1]} to {new.size[0]}x{new.size[1]}"
        w, h = min(old.width, new.width), min(old.height, new.height)
        old, new = old.crop((0, 0, w, h)), new.crop((0, 0, w, h))
    cells, cols, rows = changed_cells(old, new)
    found = PageDiff(key_of(new_path.name), len(cells) / max(1, cols * rows), boxes(cells), note)
    if out_path is not None and (found.boxes or note):
        marked = Image.open(new_path).convert("RGB")
        draw = ImageDraw.Draw(marked)
        for b in found.boxes:
            draw.rectangle(b, outline=(230, 40, 40), width=3)
        marked.save(out_path)
        found.picture = out_path.name
    return found


def baseline_for(root: Path, version: str) -> Path | None:
    """The newest baseline kept by a different version - the last release's."""
    others = [p for p in root.glob("baseline-*") if p.is_dir() and p.name != f"baseline-{version}"]
    return max(others, key=lambda p: p.stat().st_mtime) if others else None


def run(folder: Path, version: str) -> tuple[str | None, list[PageDiff]]:
    """Compare a self-check's pictures with the last release's; keep them as this
    version's baseline. (the version compared against, or None; each page's diff)."""
    root = folder.parent
    base = baseline_for(root, version)
    found: list[PageDiff] = []
    pictures = sorted(p for p in folder.glob("*.png") if not p.name.startswith(("diff-", "00-")))
    if base is not None:
        kept = {key_of(p.name): p for p in base.glob("*.png")}
        for new in pictures:
            old = kept.get(key_of(new.name))
            if old is None:
                found.append(PageDiff(key_of(new.name), 1.0, size_note="new page"))
                continue
            try:
                found.append(compare(old, new, folder / f"diff-{new.name}"))
            except Exception as exc:  # noqa: BLE001 - one picture that can't be read leaves the rest
                found.append(PageDiff(key_of(new.name), 0.0, size_note=f"couldn't compare: {exc}"))
    mine = root / f"baseline-{version}"
    try:
        if mine.exists():
            shutil.rmtree(mine)
        mine.mkdir(parents=True)
        for p in pictures:
            shutil.copy2(p, mine / p.name)
    except OSError:
        pass
    return (base.name.removeprefix("baseline-") if base else None), found


def lines(against: str | None, found: list[PageDiff]) -> list[str]:
    """The report's section."""
    if against is None:
        return ["", "What moved since the last release: no earlier release's pictures yet - this run is "
                    "kept to compare the next version against."]
    moved = sorted((d for d in found if d.score >= QUIET or d.size_note), key=lambda d: -d.score)
    out = ["", f"What moved since {against} ({len(moved)} of {len(found)} pages changed; red boxes in the "
               "diff- pictures):"]
    for d in moved:
        out.append(f"  {d.score:6.1%}  {d.key}" + (f"  - {d.size_note}" if d.size_note else "")
                   + (f"  ({len(d.boxes)} region{'s' if len(d.boxes) != 1 else ''})" if d.boxes else ""))
    if not moved:
        out.append("  Nothing moved.")
    return out
