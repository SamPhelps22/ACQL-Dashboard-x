"""Installing an update, undoing one, and restarting - the window's side of it.

The work is done by acql.updater, which knows nothing about Qt. This adds
the questions, the waiting and the restart: the check that the new version
starts takes a few seconds, so it runs off the window's thread.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from .. import updater


def project_root() -> Path:
    from .. import store
    return store.project_root()


def current_version() -> str:
    try:
        from ..version import VERSION
        return VERSION
    except Exception:  # noqa: BLE001
        return "?"


class _Installer(QThread):
    done = Signal(object)       # Installed, or (the reason it failed, whether rolled back cleanly)

    def __init__(self, update: updater.Update, root: Path, allow_same: bool) -> None:
        super().__init__()
        self.update_ = update
        self.root = root
        self.allow_same = allow_same
        self.log: list[str] = []

    def run(self) -> None:
        try:
            self.done.emit(updater.install(self.update_, self.root, say=self.log.append,
                                           allow_same=self.allow_same))
        except updater.RollbackIncomplete as exc:
            self.done.emit((str(exc), False))
        except updater.UpdateError as exc:
            self.done.emit((str(exc), True))
        except Exception as exc:  # noqa: BLE001 - shown, never swallowed
            self.done.emit((f"The update stopped: {exc}", True))


def restart(parent: QWidget | None = None) -> None:
    """Start the dashboard again from run.py, then close this copy."""
    root = project_root()
    try:
        subprocess.Popen([sys.executable, str(root / "run.py")], cwd=str(root))
    except OSError as exc:
        QMessageBox.warning(parent, "Restart", f"Couldn't restart by itself ({exc}). Close the "
                            "dashboard and open it again.")
        return
    QApplication.quit()


class UpdateFlow:
    """Asks which update, installs it off the main thread, offers the restart."""

    def __init__(self, parent: QWidget) -> None:
        self.parent = parent
        self._thread: _Installer | None = None

    def choose(self) -> Path | None:
        here = current_version()
        found = [(v, p) for v, p in updater.find_update_zips()
                 if updater.version_tuple(v) > updater.version_tuple(here)]
        if found:
            version, path = found[0]
            box = QMessageBox(self.parent)
            box.setWindowTitle("Install update")
            box.setText(f"Found ACQL Dashboard {version} in {path.parent.name}:\n{path.name}")
            box.setInformativeText(
                f"This copy is {here}. Your current code is backed up first, and put "
                f"back by itself if the new version won't start. Your data isn't touched."
            )
            install = box.addButton("Install it", QMessageBox.ButtonRole.AcceptRole)
            other = box.addButton("Choose another file…", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is install:
                return path
            if box.clickedButton() is not other:
                return None
        start = str(Path.home() / "Downloads")
        path, _ = QFileDialog.getOpenFileName(
            self.parent, "The update zip", start, "ACQL Dashboard update (*.zip)"
        )
        return Path(path) if path else None

    def start(self) -> None:
        if self._thread is not None:
            return
        path = self.choose()
        if path is None:
            return
        try:
            update = updater.open_update(path)
        except updater.UpdateError as exc:
            QMessageBox.warning(self.parent, "Install update", str(exc))
            return
        here = updater.installed_version(project_root()) or current_version()
        same = updater.version_tuple(update.version) <= updater.version_tuple(here)
        if same:
            answer = QMessageBox.question(
                self.parent, "Install update",
                f"That's version {update.version}, and {here} is already installed. "
                f"Install it again anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        thread = _Installer(update, project_root(), same)
        thread.done.connect(self._finished)
        thread.finished.connect(lambda t=thread: self._release(t))
        self._thread = thread
        thread.start()

    def _release(self, thread) -> None:
        if self._thread is thread:
            self._thread = None
        thread.deleteLater()

    def _finished(self, result) -> None:
        QApplication.restoreOverrideCursor()
        if isinstance(result, tuple):
            reason, clean = result
            QMessageBox.warning(
                self.parent, "The update wasn't installed",
                reason + ("\n\nNothing has changed - the dashboard is exactly as it was."
                          if clean else ""),
            )
            return
        text = f"ACQL Dashboard {result.version} is installed. It restarts to finish."
        if result.missing_own:
            text += ("\n\nThese files should be in the folder and aren't: "
                     + ", ".join(result.missing_own))
        QMessageBox.information(self.parent, "Installed", text)
        restart(self.parent)


def undo(parent: QWidget) -> None:
    record = updater.last_install(project_root())
    if not record:
        QMessageBox.information(
            parent, "Undo last update",
            "There's no update to undo - nothing has been installed with the updater yet.",
        )
        return
    answer = QMessageBox.question(
        parent, "Undo last update",
        f"Put back version {record.get('from') or 'the previous one'} "
        f"(replacing {record.get('version')})? Your data isn't touched. "
        f"The dashboard restarts afterwards.",
    )
    if answer != QMessageBox.StandardButton.Yes:
        return
    try:
        restored = updater.undo_last(project_root())
    except updater.UpdateError as exc:
        QMessageBox.warning(parent, "Undo last update", str(exc))
        return
    QMessageBox.information(parent, "Undone", f"Version {restored or 'the previous one'} is back. Restarting.")
    restart(parent)
