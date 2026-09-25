"""Publishing the pool page from the dashboard: its own website, or the file
for the Claude page. The window's "Pool page" button lands here."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from .. import mailer, webpublish
from . import poolpage
from .pages.base import write_log


class WebDialog(QDialog):
    """The pool page's website: which GitHub repository, and the token. Asked once."""

    def __init__(self, settings: webpublish.WebSettings, reason: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("The pool page's website")
        self.setMinimumWidth(560)
        self._settings = settings
        layout = QVBoxLayout(self)
        intro = QLabel(
            (f"<p style='color:#d03b3b'>{reason}</p>" if reason else "")
            + "The page goes on a free GitHub website that anyone can open - no "
            "account, no sign-in. Set it up once:"
            "<ol>"
            f"<li>Make a free account at github.com, then a <a href='{webpublish.NEW_REPO_PAGE}'>new "
            "repository</a> called <b>acql-pool</b>: <b>Public</b>, and tick <i>Add a README</i>.</li>"
            f"<li>Make a <a href='{webpublish.TOKEN_PAGE}'>fine-grained token</a>: Repository access "
            "<i>Only select repositories</i> &rsaquo; acql-pool; Permissions &rsaquo; <b>Contents</b> and "
            "<b>Pages</b>: Read and write. Copy the token it shows.</li>"
            "<li>In the repository on GitHub: <b>Settings</b> &rsaquo; <b>Pages</b> &rsaquo; Source "
            "<i>Deploy from a branch</i>, Branch <b>main</b>, <b>/ (root)</b>, Save.</li>"
            "<li>Fill in the three boxes below.</li>"
            "</ol>"
            "The token can only touch that one repository. It is stored locked to your "
            "Windows account, and you can delete it on GitHub at any time."
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)

        form = QFormLayout()
        self.user = QLineEdit(settings.user)
        self.user.setPlaceholderText("your GitHub user name")
        self.repo = QLineEdit(settings.repo)
        self.token = QLineEdit("")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText(
            "saved - leave blank to keep it" if settings.sealed_token else "github_pat_..."
        )
        form.addRow("GitHub user name", self.user)
        form.addRow("Repository", self.repo)
        form.addRow("Token", self.token)
        layout.addLayout(form)
        self.link = QLabel("")
        self.link.setObjectName("Muted")
        layout.addWidget(self.link)
        self.user.textChanged.connect(self._show_link)
        self.repo.textChanged.connect(self._show_link)
        self._show_link()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_link(self, *_) -> None:
        user, repo = self.user.text().strip(), self.repo.text().strip()
        self.link.setText(f"The page's link will be {webpublish.site_url(user, repo)}" if user and repo else "")

    def result_settings(self) -> webpublish.WebSettings:
        settings = self._settings
        settings.user = self.user.text().strip()
        settings.repo = self.repo.text().strip() or "acql-pool"
        if self.token.text().strip():
            settings.set_token(self.token.text())
        return settings


def edit_settings(window, reason: str = "") -> bool:
    """Ask for the website's details; True if it is now ready to publish."""
    dialog = WebDialog(webpublish.WebSettings.load(), reason, window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    settings = dialog.result_settings()
    settings.save()
    return settings.ready


def _box(window, title: str, text: str, info: str = "", icon=None) -> QMessageBox:
    box = QMessageBox(window)
    box.setWindowTitle(title)
    box.setText(text)
    if info:
        box.setInformativeText(info)
    if icon is not None:
        box.setIcon(icon)
    return box


def save_file(window, season) -> Path | None:
    """The older way: the file you drop on the Claude page."""
    try:
        path = poolpage.export(season)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        write_log(f"pool page export failed: {exc!r}\n{traceback.format_exc()}")
        QMessageBox.warning(window, "Pool page", f"Couldn't save the pool page file: {exc}")
        return None
    window.statusBar().showMessage(f"Pool page file saved: {path}")
    box = _box(window, "Pool page file saved", f"Saved \"{path.name}\" in {path.parent.name}.",
               "Open the Claude pool page, click Update this page and choose this file.")
    show = box.addButton("Show the file", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is show:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
    return path


def publish(window, season) -> str | None:
    """The "Pool page" button: put this week on the pool's website."""
    if season is None or season.is_empty or not poolpage.finished_weeks(season):
        QMessageBox.information(
            window, "Pool page",
            "No week is finished yet, so there is nothing to put on the page. "
            + (poolpage.left_off(season) if season is not None else ""),
        )
        return None
    settings = webpublish.WebSettings.load()
    if not settings.ready:
        box = _box(window, "Pool page",
                   "Put the pool page on its own website?",
                   "A free GitHub site anyone can open - no account, no sign-in, nothing "
                   "to do with Claude. Setting it up takes about five minutes, once; after "
                   "that this button updates it in one click.")
        setup = box.addButton("Set it up", QMessageBox.ButtonRole.AcceptRole)
        old = box.addButton("Save the file for the Claude page", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is old:
            save_file(window, season)
            return None
        if box.clickedButton() is not setup or not edit_settings(window):
            return None
        settings = webpublish.WebSettings.load()

    try:
        from . import previewcard
        page = poolpage.page_html(season)
        try:
            picture = previewcard.render(poolpage.snapshot(season))
        except Exception as exc:  # noqa: BLE001 - the page goes up without its preview
            write_log(f"preview card failed: {exc!r}\n{traceback.format_exc()}")
            picture = None
    except Exception as exc:  # noqa: BLE001
        write_log(f"pool page build failed: {exc!r}\n{traceback.format_exc()}")
        QMessageBox.warning(window, "Pool page", f"Couldn't build the page: {exc}")
        return None
    week = max(poolpage.finished_weeks(season))
    window.statusBar().showMessage("Publishing the pool page…")
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        url = webpublish.publish(settings, page, message=f"After week {week}",
                                 files={poolpage.PREVIEW: picture} if picture else None)
    except webpublish.WebPublishError as exc:
        QApplication.restoreOverrideCursor()
        window.statusBar().showMessage("The pool page wasn't published.")
        box = _box(window, "Pool page", "The pool page wasn't published.", str(exc),
                   QMessageBox.Icon.Warning)
        fix = box.addButton("Website settings", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is fix and edit_settings(window, str(exc)):
            return publish(window, season)
        return None
    except Exception as exc:  # noqa: BLE001
        QApplication.restoreOverrideCursor()
        write_log(f"pool page publish failed: {exc!r}\n{traceback.format_exc()}")
        QMessageBox.warning(window, "Pool page", f"The pool page wasn't published: {exc}")
        return None
    QApplication.restoreOverrideCursor()

    # The recap email points at the website from now on, unless it was changed by hand.
    mail = mailer.MailSettings.load()
    if mail.page_link in mailer.OLD_PAGE_LINKS:
        mail.page_link = url
        mail.save()

    window.statusBar().showMessage(f"Pool page published: {url}")
    box = _box(window, "Pool page published", f"Week {week} is on the pool's website:\n{url}",
               "Anyone with the link can open it - no sign-in. The first time, GitHub "
               "takes a minute or two before the link works; after that, updates show "
               "within a minute.")
    open_it = box.addButton("Open it", QMessageBox.ButtonRole.AcceptRole)
    copy = box.addButton("Copy the link", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is open_it:
        QDesktopServices.openUrl(QUrl(url))
    elif box.clickedButton() is copy:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(url)
    return url
