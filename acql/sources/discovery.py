"""Find and identify the pool's spreadsheets in the watched folders.

Filenames are unreliable - a second download of the same export arrives as
"stats (1).xls" - so every candidate is identified by looking inside it. Two
files with identical content are collapsed to one regardless of name.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..models import SourceFile

WEEK_TEXT = re.compile(r"week\s*(\d{1,2})", re.IGNORECASE)
SKIP_PREFIXES = ("~$", ".")
STATS_EXT = {".xls"}
WORKBOOK_EXT = {".xlsx", ".xlsm"}


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _stats_metadata(path: Path) -> tuple[int | None, str, str]:
    """(week, season_title, error) read from a stats.xls export."""
    try:
        import xlrd

        book = xlrd.open_workbook(str(path))
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        return None, "", f"could not open: {exc}"

    try:
        sheet = book.sheet_by_name("stats") if "stats" in book.sheet_names() else book.sheet_by_index(0)
    except Exception as exc:  # noqa: BLE001
        return None, "", f"no readable sheet: {exc}"

    season, week = "", None
    # The export self-declares its season and week in the top-left block.
    for r in range(min(sheet.nrows, 6)):
        for c in range(min(sheet.ncols, 12)):
            text = str(sheet.cell_value(r, c)).strip()
            if not text:
                continue
            if not season and re.match(r"^[A-Za-z]+\s*\d{4}$", text):
                season = text
            m = WEEK_TEXT.fullmatch(text)
            if m and week is None:
                week = int(m.group(1))
    return week, season, ""


def _workbook_metadata(path: Path) -> tuple[int | None, str, str]:
    """(current_week, season_title, error) read from the dashboard workbook."""
    try:
        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        return None, "", f"could not open: {exc}"

    week, season = None, ""
    try:
        if "Dashboard" in wb.sheetnames:
            ws = wb["Dashboard"]
            # A1 holds the week the Dashboard sheet is pointed at.
            m = WEEK_TEXT.fullmatch(str(ws["A1"].value or "").strip())
            if m:
                week = int(m.group(1))
            season = str(ws["C1"].value or "").strip()
        if week is None:
            # Fall back to the highest week sheet that has anything in it.
            weeks = [
                int(m.group(1))
                for name in wb.sheetnames
                if (m := WEEK_TEXT.fullmatch(name.strip()))
            ]
            week = max(weeks) if weeks else None
    except Exception:  # noqa: BLE001
        pass
    finally:
        wb.close()
    return week, season, ""


def classify(path: Path) -> SourceFile | None:
    """Identify one file, or return None if it is not one of ours."""
    if path.name.startswith(SKIP_PREFIXES) or not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix in STATS_EXT:
        kind, (week, season, error) = "stats", _stats_metadata(path)
    elif suffix in WORKBOOK_EXT:
        kind, (week, season, error) = "workbook", _workbook_metadata(path)
    else:
        return None

    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0

    return SourceFile(
        path=path,
        kind=kind,
        week=week,
        season=season,
        digest=_digest(path),
        modified=modified,
        error=error,
    )


def discover(search_paths: list[Path]) -> list[SourceFile]:
    """Scan folders for pool files, newest first, duplicates collapsed.

    Only the top level of each folder is scanned: dropping a whole season's
    archive into data/ should not make the app trawl nested backup folders.
    """
    found: list[SourceFile] = []
    seen_paths: set[Path] = set()
    seen_digests: set[str] = set()

    for folder in search_paths:
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            resolved = entry.resolve()
            if resolved in seen_paths:
                continue
            source = classify(entry)
            if source is None:
                continue
            seen_paths.add(resolved)
            # Same bytes under a different name: keep the first, drop the copy.
            if source.digest and source.digest in seen_digests:
                continue
            if source.digest:
                seen_digests.add(source.digest)
            found.append(source)

    found.sort(key=lambda s: (s.week or 0, s.modified), reverse=True)
    return found
