"""The window's side of automatic updates (acql.autoupdate): looking off the
main thread, offering what it found, and the settings."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from .. import autoupdate
from .pages.base import write_log


def current_version() -> str:
    from .updating import current_version as here
    return here()


class _Checker(QThread):
    """Asks the repository what's newest and, if it's newer, downloads it."""

    done = Signal(object)       # (Available | None, the zip | None, what went wrong)

    def __init__(self, settings: autoupdate.UpdateSettings, here: str) -> None:
        super().__init__()
        self.settings, self.here = settings, here

    def run(self) -> None:
        try:
            found = autoupdate.latest(self.settings)
            autoupdate.note_checked()
            if not autoupdate.newer(found, self.here):
                self.done.emit((found, None, ""))
                return
            from .. import store
            path = autoupdate.download(self.settings, found, store.data_dir() / "updates")
            self.done.emit((found, path, ""))
        except autoupdate.UpdateCheckError as exc:
            self.done.emit((None, None, str(exc)))
        except Exception as exc:  # noqa: BLE001 - a missed look is no matter
            self.done.emit((None, None, f"The look for updates stopped: {exc}"))


def check(window, *, by_hand: bool = False) -> None:
    """Look for an update; by hand, say what happened either way."""
    if getattr(window, "_update_checker", None) is not None:
        return
    settings = autoupdate.UpdateSettings.load()
    if not settings.ready:
        if by_hand:
            QMessageBox.information(
                window, "Check for updates",
                "Updates come from the dashboard's private GitHub repository, which needs "
                "its name and a token that can read it. Set them up next.")
            edit_settings(window)
        return
    thread = _Checker(settings, current_version())
    thread.done.connect(lambda result: _finished(window, result, by_hand))
    thread.finished.connect(lambda t=thread: _release(window, t))
    window._update_checker = thread
    if by_hand:
        window.statusBar().showMessage("Looking for an update…", 5000)
    thread.start()


def _release(window, thread) -> None:
    if getattr(window, "_update_checker", None) is thread:
        window._update_checker = None
    thread.deleteLater()


def _finished(window, result, by_hand: bool) -> None:
    found, path, why = result
    if why:
        write_log(f"update check: {why}")
        if by_hand:
            QMessageBox.warning(window, "Check for updates", why)
        return
    if path is None:
        if by_hand:
            QMessageBox.information(window, "Check for updates",
                                    f"This is the newest version ({current_version()}).")
        return
    window._pending_update = (found, path)
    if window.isVisible():
        offer(window)
    else:
        tray = getattr(window, "_tray", None)
        if tray is not None:
            tray.icon.showMessage("Update ready",
                                  f"ACQL Dashboard {found.version} is downloaded. Open the dashboard to install it.")


def offer(window) -> None:
    """Ask once whether to install the update that's waiting."""
    pending = getattr(window, "_pending_update", None)
    if not pending:
        return
    found, path = pending
    window._pending_update = None
    box = QMessageBox(window)
    box.setWindowTitle("Update ready")
    box.setText(f"ACQL Dashboard {found.version} is ready to install (this is {current_version()}).")
    notes = found.notes.strip()
    box.setInformativeText(
        (notes[:900] + ("…" if len(notes) > 900 else "") + "\n\n" if notes else "")
        + "Your current code is backed up first and put back by itself if the new version "
          "won't start. Your data isn't touched. The dashboard restarts to finish.")
    install = box.addButton("Install and restart", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is install:
        from .updating import UpdateFlow
        window._update_flow = UpdateFlow(window)
        window._update_flow.start(path)
    else:
        window.statusBar().showMessage(
            f"Update {found.version} is waiting - Data & Update > Check for updates installs it.", 10000)


def edit_settings(window) -> bool:
    """Where updates come from: the repository and the token."""
    settings = autoupdate.UpdateSettings.load()
    owner, _, _ = settings.resolved()
    dialog = QDialog(window)
    dialog.setWindowTitle("Updates from GitHub")
    layout = QVBoxLayout(dialog)
    intro = QLabel(
        "New versions are published to the dashboard's private GitHub repository. "
        "Leave the token blank to use the website's - then on GitHub give that token "
        "read access to this repository's Contents too.")
    intro.setWordWrap(True)
    layout.addWidget(intro)
    form = QFormLayout()
    owner_box = QLineEdit(settings.owner or owner)
    repo_box = QLineEdit(settings.repo)
    token_box = QLineEdit()
    token_box.setEchoMode(QLineEdit.EchoMode.Password)
    token_box.setPlaceholderText("kept" if settings.sealed_token else "blank: the website's token")
    auto_box = QCheckBox("Look for updates by itself (twice a day)")
    auto_box.setChecked(settings.automatic)
    form.addRow("GitHub user", owner_box)
    form.addRow("Repository", repo_box)
    form.addRow("Token", token_box)
    layout.addLayout(form)
    layout.addWidget(auto_box)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    settings.owner = owner_box.text().strip()
    settings.repo = repo_box.text().strip() or autoupdate.DEFAULT_REPO
    if token_box.text().strip():
        settings.set_token(token_box.text())
    settings.automatic = auto_box.isChecked()
    settings.save()
    return True
