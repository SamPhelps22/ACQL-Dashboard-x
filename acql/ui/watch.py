"""Notice when a spreadsheet lands in (or changes in) a watched folder.

The dashboard already reads everything in the folder when Refresh is
pressed. This removes the pressing: drop a pick sheet or a predictions CSV
in, save the workbook, and the app reloads by itself a moment later.

Three things make that trickier than it sounds, and each has a rule here:

* Excel saves in several steps - a temporary file, a rename, a lock file
  beside it - and OneDrive touches files as it syncs them. Raw folder
  events therefore fire in bursts, and several fire for files that did not
  change at all. So events only *start a timer*; when it runs out, the
  folder is compared against a snapshot of names, sizes and modified
  times, and only a real difference counts.
* Only the file types the dashboard reads count. Excel's `~$` lock files,
  the app's own json stores and everything else are ignored, so the app
  cannot trigger itself in a loop.
* File-system events are not guaranteed - network drives and some sync
  clients drop them - so the same comparison also runs once a minute as a
  fallback. Comparing a few dozen file sizes costs nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

#: The files the dashboard reads. Nothing else in a folder triggers a reload.
WATCHED_SUFFIXES = frozenset({".xls", ".xlsx", ".xlsm", ".csv"})
#: Quiet time after the last event before the folder is compared.
SETTLE_MS = 1500
#: How often the folder is compared even when no event has arrived.
POLL_MS = 60_000

Snapshot = dict[str, tuple[int, int]]      # path -> (modified ns, size)


def is_watched(path: Path) -> bool:
    """Whether a file is one the dashboard would read.

    Excel's lock file for an open workbook is "~$ACQL Dashboard.xlsx", and
    LibreOffice's is ".~lock.ACQL Dashboard.xlsx#": both look like
    spreadsheets by suffix and neither is one.
    """
    name = path.name
    if name.startswith(("~$", ".", "~")):
        return False
    return path.suffix.casefold() in WATCHED_SUFFIXES


def snapshot(folders: Iterable[Path]) -> Snapshot:
    """Name, modified time and size of every watched file in the folders.

    Unreadable folders and files that vanish mid-scan are skipped rather than
    raised - a sync client can delete and recreate a file between listing a
    folder and asking about it.
    """
    seen: Snapshot = {}
    for folder in folders:
        try:
            entries = list(Path(folder).iterdir())
        except OSError:
            continue
        for entry in entries:
            if not is_watched(entry):
                continue
            try:
                info = entry.stat()
            except OSError:
                continue
            if not entry.is_file():
                continue
            seen[str(entry)] = (info.st_mtime_ns, info.st_size)
    return seen


def changes(before: Snapshot, after: Snapshot) -> list[str]:
    """File names that were added, changed or removed, for a status message."""
    names = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            names.append(Path(path).name)
    return names


def describe(names: list[str]) -> str:
    """"picks (4).xls", "picks (4).xls and 1 other", "3 files"."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and 1 other"
    return f"{len(names)} files"


class FolderWatcher(QObject):
    """Emits `changed` with the names of files that really changed."""

    changed = Signal(list)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        settle_ms: int = SETTLE_MS,
        poll_ms: int = POLL_MS,
    ) -> None:
        super().__init__(parent)
        self._folders: list[Path] = []
        self._baseline: Snapshot = {}
        self._enabled = True

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._poke)
        self._watcher.fileChanged.connect(self._poke)

        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(settle_ms)
        self._settle.timeout.connect(self.check)

        self._poll = QTimer(self)
        self._poll.setInterval(poll_ms)
        self._poll.timeout.connect(self.check)
        self._poll.start()

    # ---- setup ---------------------------------------------------------
    def watch(self, folders: Iterable[Path | str]) -> None:
        """Watch exactly these folders (missing ones are skipped)."""
        wanted: list[Path] = []
        for folder in folders:
            path = Path(folder).expanduser()
            if path.is_dir() and path not in wanted:
                wanted.append(path)
        added = [f for f in wanted if f not in self._folders]
        removed = {str(f) for f in self._folders if f not in wanted}
        self._folders = wanted
        # A folder that has just started being watched is not a change: its
        # files join the baseline as they are, or the first check would
        # report every one of them as new and reload for nothing.
        if added:
            self._baseline.update(snapshot(added))
        if removed:
            self._baseline = {
                path: stamp for path, stamp in self._baseline.items()
                if str(Path(path).parent) not in removed
            }
        self._rewatch()

    def settle(self) -> None:
        """Take the folders as they are now as the new normal.

        Called when a load starts: whatever the loader is about to read is,
        by definition, not a change it has missed.
        """
        self._baseline = snapshot(self._folders)
        self._rewatch()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self._poll.start()
        else:
            self._poll.stop()
            self._settle.stop()

    @property
    def folders(self) -> list[Path]:
        return list(self._folders)

    # ---- events --------------------------------------------------------
    def _poke(self, _path: str = "") -> None:
        if self._enabled:
            self._settle.start()      # restarting pushes the check back

    def check(self) -> list[str]:
        """Compare the folders with the baseline; emit and return what changed."""
        if not self._enabled or not self._folders:
            return []
        now = snapshot(self._folders)
        different = changes(self._baseline, now)
        # Replacing a file (how Excel saves) drops the watch on it; put it back.
        self._rewatch(now)
        if not different:
            return []
        self._baseline = now
        self.changed.emit(different)
        return different

    def _rewatch(self, current: Snapshot | None = None) -> None:
        files = list((current if current is not None else self._baseline).keys())
        wanted = {str(f) for f in self._folders} | set(files)
        have = set(self._watcher.directories()) | set(self._watcher.files())
        stale = sorted(have - wanted)
        fresh = sorted(wanted - have)
        if stale:
            self._watcher.removePaths(stale)
        if fresh:
            self._watcher.addPaths(fresh)
