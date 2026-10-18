"""Publishing the pool page from the dashboard: its own website, or the file
for the Claude page. The window's "Pool page" button lands here, and so does
the quiet update after new results or a new pick sheet load."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTime, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ..site import lockedpage, mailer, pushalerts, siteextras, webpublish
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


def build_site(season) -> tuple[str, dict[str, bytes], dict]:
    """The page, every file that goes beside it, and the snapshot it shows.
    The link-preview picture and the home-screen icons go along when they
    can be drawn; the page goes up without them when they can't."""
    from . import previewcard
    page, files, data = poolpage.site(season)
    try:
        files[poolpage.PREVIEW] = previewcard.render(data)
    except Exception as exc:  # noqa: BLE001 - the page goes up without its preview
        write_log(f"preview card failed: {exc!r}\n{traceback.format_exc()}")
    try:
        files.update(poolpage.app_files())
    except Exception as exc:  # noqa: BLE001 - or without its home-screen icon
        write_log(f"home-screen icon failed: {exc!r}\n{traceback.format_exc()}")
    return page, files, data


def published(data: dict, week: int, url: str) -> None:
    """After any publish: the season goes in the History archive, and the
    site is marked up to date so the quiet update knows to leave it."""
    try:
        siteextras.archive(data)
        siteextras.mark_published(poolpage.site_fingerprint(data), week, url)
    except Exception as exc:  # noqa: BLE001 - the page is up; the bookkeeping can wait
        write_log(f"after publishing: {exc!r}\n{traceback.format_exc()}")


class AutoPublisher(QThread):
    """Brings the website up to date off the UI thread: builds the page, and
    publishes only when what it shows has changed since the last publish."""

    done = Signal(str)          # the site's link
    failed = Signal(str)        # what went wrong, in words

    def __init__(self, season, settings: webpublish.WebSettings) -> None:
        super().__init__()
        self.season = season
        self.settings = settings

    def run(self) -> None:
        try:
            weeks = poolpage.finished_weeks(self.season)
            if not weeks:
                return
            page, files, data = poolpage.site(self.season)
            fingerprint = poolpage.site_fingerprint(data)
            if not siteextras.needs_publish(fingerprint):
                return
            from . import previewcard
            try:
                files[poolpage.PREVIEW] = previewcard.render(data)
            except Exception as exc:  # noqa: BLE001
                write_log(f"preview card failed: {exc!r}")
            try:
                files.update(poolpage.app_files())
            except Exception as exc:  # noqa: BLE001
                write_log(f"home-screen icon failed: {exc!r}")
            week = max(weeks)
            url = webpublish.publish(self.settings, page, message=f"After week {week} (by itself)",
                                     files=files)
            published(data, week, url)
            self.done.emit(url)
        except webpublish.WebPublishError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            write_log(f"automatic website update failed: {exc!r}\n{traceback.format_exc()}")
            self.failed.emit(f"{exc}")


def auto_publish(window, season) -> bool:
    """After a load: update the website by itself, in the background - when
    it is set up, the switch is on, and something it shows has changed.
    True when an update started."""
    if season is None or getattr(season, "is_empty", True) or not getattr(window, "auto_site", True):
        return False
    try:
        settings = webpublish.WebSettings.load()
        extras = siteextras.Extras.load()
    except Exception as exc:  # noqa: BLE001
        write_log(f"automatic website update skipped: {exc!r}")
        return False
    if not settings.ready or not extras.auto_publish:
        return False
    running = getattr(window, "_site_worker", None)
    if running is not None and running.isRunning():
        window._site_again = True          # once this one is done, look again
        return False
    worker = AutoPublisher(season, settings)
    worker.done.connect(window.site_published)
    worker.failed.connect(window.site_failed)
    worker.finished.connect(window.site_worker_finished)
    window._site_worker = worker
    window._site_again = False
    worker.start()
    return True


class ExtrasDialog(QDialog):
    """What the website says beyond the standings: an announcement at the
    top, the league's past champions, and whether it updates by itself."""

    def __init__(self, extras: siteextras.Extras, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What the website says")
        self.setMinimumWidth(620)
        self._extras = extras
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Announcement</b> - shows at the top of the website until you clear it."))
        self.note = QPlainTextEdit()
        self.note.setPlainText(extras.note)
        self.note.setPlaceholderText("e.g. Week 6 picks are due Thursday by 6pm. Payments to Kit by week 8.")
        self.note.setMaximumHeight(90)
        layout.addWidget(self.note)
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        layout.addWidget(self.count)
        self.note.textChanged.connect(self._show_count)
        self._show_count()

        layout.addWidget(QLabel("<b>Past champions</b> - for the History page. One season a row; "
                                "a tie is two names with &amp;."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Season", "Champion", "Note"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 200)
        self.table.setMinimumHeight(180)
        for champ in extras.champions:
            self._add_row(str(champ.year), champ.names, champ.note)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton("Add a season")
        add.clicked.connect(lambda: self._add_row("", "", ""))
        remove = QPushButton("Remove the selected season")
        remove.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        self.auto = QCheckBox("Update the website by itself when new results or a pick sheet are loaded")
        self.auto.setChecked(extras.auto_publish)
        layout.addWidget(self.auto)
        layout.addWidget(self._alerts_box())
        self.problems = QLabel("")
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color:#d03b3b")
        layout.addWidget(self.problems)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _alerts_box(self):
        """Phone alerts through ntfy.sh, and the weekly picks deadline they count down to."""
        from ..feeds import oddslock
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 8, 0, 0)
        form.addRow(QLabel("<b>Phone alerts</b> - coaches install the free ntfy app and subscribe "
                           "from the website's menu."))
        self.topic = QLineEdit(pushalerts.topic())
        self.topic.setPlaceholderText("e.g. acql-pool-k7q2m9x - blank for no alerts; hard to guess")
        form.addRow("ntfy topic", self.topic)
        self.text_to = QLineEdit(pushalerts.text_number())
        self.text_to.setPlaceholderText("555-123-4567, 555-987-6543 tmobile - commas between; Verizon needs no name")
        form.addRow("Text alerts to", self.text_to)
        carriers = QLabel("Texts go out from the Gmail in the email settings. Put the carrier after any "
                          "number that isn't Verizon: tmobile, metro, uscellular or googlefi. AT&T can't get them.")
        carriers.setObjectName("Muted")
        carriers.setWordWrap(True)
        form.addRow("", carriers)
        weekday, hour, minute = oddslock.deadline_clock()
        self.day = QComboBox()
        self.day.addItems(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        self.day.setCurrentIndex(weekday)
        self.time = QTimeEdit(QTime(hour, minute))
        self.time.setDisplayFormat("h:mm AP")
        due = QHBoxLayout()
        due.addWidget(self.day)
        due.addWidget(self.time)
        due.addStretch(1)
        form.addRow("Picks due", due)
        self.remind = QDoubleSpinBox()
        self.remind.setRange(0.25, 48)
        self.remind.setSingleStep(0.5)
        self.remind.setSuffix(" hours before")
        self.remind.setValue(pushalerts.remind_before() / 3600)
        form.addRow("Reminder", self.remind)
        test = QPushButton("Send a test alert")
        test.clicked.connect(self._test_alert)
        form.addRow("", test)
        note = QLabel("The deadline also freezes the week's betting lines. The reminder goes out from "
                      "the scheduled game-day check (Thu, Sun and Mon).")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow(note)
        return box

    def _test_alert(self) -> None:
        name = self.topic.text().strip()
        try:
            number = pushalerts.clean_number(self.text_to.text())
        except ValueError as exc:
            self.problems.setText(f"Fix these first: {exc}.")
            return
        if name and not pushalerts.TOPIC_RULE.match(name):
            self.problems.setText("Fix these first: a topic is 6-64 letters, digits, - or _.")
            return
        if not (name or number):
            self.problems.setText("Fix these first: fill in an ntfy topic or a number to text.")
            return
        try:
            pushalerts.send("ACQL alerts are on", "This is a test from the dashboard.", tags="football", name=name,
                            text=pushalerts.text_address(number))
        except Exception as exc:  # noqa: BLE001
            self.problems.setText(f"The test alert didn't go: {exc}")
            return
        self.problems.setText("")
        where = ([pushalerts.subscribe_link(name)] if name else []) + pushalerts.text_address(number)
        QMessageBox.information(self, "Phone alerts", f"Sent to {' and '.join(where)}.")

    def _save_alerts(self) -> str:
        """Keep the alert settings; what's wrong, in words, or ''."""
        try:
            pushalerts.set_topic(self.topic.text())
        except ValueError as exc:
            return f"ntfy topic: {exc}"
        try:
            pushalerts.set_text_number(self.text_to.text())
        except ValueError as exc:
            return f"Text alerts: {exc}"
        when = self.time.time()
        hour = when.hour()
        clock = f"{hour % 12 or 12}:{when.minute():02d}{'pm' if hour >= 12 else 'am'}"
        pushalerts.set_deadline(f"{pushalerts.DAYS[self.day.currentIndex()]} {clock}")
        pushalerts.set_remind_hours(self.remind.value())
        return ""

    def _show_count(self) -> None:
        used = len(" ".join(self.note.toPlainText().split()))
        self.count.setText(f"{used} of {siteextras.NOTE_MOST} characters"
                           + (" - the rest is cut off" if used > siteextras.NOTE_MOST else ""))

    def _add_row(self, year: str, names: str, note: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, text in enumerate((year, names, note)):
            self.table.setItem(r, c, QTableWidgetItem(text))

    def _remove_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def rows(self) -> list[tuple[str, str, str]]:
        out = []
        for r in range(self.table.rowCount()):
            cells = [self.table.item(r, c) for c in range(3)]
            out.append(tuple(cell.text() if cell is not None else "" for cell in cells))
        return out

    def _save(self) -> None:
        extras = self._extras
        problems = extras.set_champions(self.rows())
        if problems:
            self.problems.setText("Fix these first: " + "; ".join(problems) + ".")
            return
        wrong = self._save_alerts()
        if wrong:
            self.problems.setText(f"Fix these first: {wrong}.")
            return
        extras.set_note(self.note.toPlainText())
        extras.auto_publish = self.auto.isChecked()
        self.accept()

    def result_extras(self) -> siteextras.Extras:
        return self._extras


def edit_extras(window) -> bool:
    """The "What the website says" dialog; True when something was saved."""
    try:
        extras = siteextras.Extras.load()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(window, "Pool page", f"Couldn't read the website's extras: {exc}")
        return False
    dialog = ExtrasDialog(extras, window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    try:
        dialog.result_extras().save()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(window, "Pool page", f"Couldn't save: {exc}")
        return False
    window.statusBar().showMessage("Saved. The website shows it after its next update.")
    # Straight onto the site when it updates itself; the button does it otherwise.
    if auto_publish(window, getattr(window, "season", None)):
        window.statusBar().showMessage("Saved - updating the website…")
    return True


class PrivateDialog(QDialog):
    """The locked page: the card on the phone, encrypted before it leaves this computer."""

    def __init__(self, settings: lockedpage.LockedSettings, site: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Private page")
        self.setMinimumWidth(560)
        self._settings = settings
        self.take_down = False
        layout = QVBoxLayout(self)
        about = QLabel(
            "Your card, on your phone - and nobody else's. It is encrypted on this computer with your "
            "passphrase before it is uploaded, so the website and its public repository only ever hold "
            "scrambled text. Your phone's browser unlocks it when you type the passphrase.<br><br>"
            "<b>The passphrase is the only lock.</b> Use four or five unrelated words. There is no way to "
            "recover it - if you forget it, set a new one here.")
        about.setWordWrap(True)
        layout.addWidget(about)
        form = QFormLayout()
        self.first = QLineEdit()
        self.first.setEchoMode(QLineEdit.EchoMode.Password)
        self.first.setPlaceholderText("leave blank to keep the one that is set" if settings.sealed_passphrase
                                      else f"at least {lockedpage.SHORTEST} characters")
        self.again = QLineEdit()
        self.again.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Passphrase", self.first)
        form.addRow("Again", self.again)
        layout.addLayout(form)
        self.on = QCheckBox("Keep the private page up to date (with each card email and the nightly run)")
        self.on.setChecked(settings.on)
        layout.addWidget(self.on)
        where = QLabel(
            (f"Address: <b>{lockedpage.address(site)}</b><br>" if site else
             "The pool page's website isn't set up yet - do that first (Pool page website settings).<br>")
            + "Or tap the line at the very bottom of the website five times.<br>"
            + ("A passphrase is set." if settings.sealed_passphrase else "No passphrase is set: nothing is uploaded.")
            + (" Last uploaded " + _ago(settings.shown_at) + "." if settings.shown_at else ""))
        where.setWordWrap(True)
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        where.setObjectName("Muted")
        layout.addWidget(where)
        self.problems = QLabel("")
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color:#d03b3b")
        layout.addWidget(self.problems)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        remove = buttons.addButton("Take it off the website", QDialogButtonBox.ButtonRole.DestructiveRole)
        remove.setEnabled(bool(settings.shown_at))
        remove.clicked.connect(self._remove)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _remove(self) -> None:
        self.take_down = True
        self._settings.on = False
        self.accept()

    def _save(self) -> None:
        typed = self.first.text()
        if typed or self.again.text():
            if typed != self.again.text():
                self.problems.setText("The two don't match.")
                return
            problem = lockedpage.weak(typed)
            if problem:
                self.problems.setText(problem)
                return
            self._settings.set_passphrase(typed)
        self._settings.on = self.on.isChecked()
        self.first.clear()
        self.again.clear()
        self.accept()


def _ago(at: float) -> str:
    import time
    return time.strftime("%a %b %d, %I:%M %p", time.localtime(at)).replace(" 0", " ")


def edit_private(window) -> bool:
    """The "Private page" dialog; True when something was saved."""
    try:
        settings = lockedpage.LockedSettings.load()
        web = webpublish.WebSettings.load()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(window, "Private page", f"Couldn't read the settings: {exc}")
        return False
    dialog = PrivateDialog(settings, web.url if web.ready else "", window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    settings.save()
    season = getattr(window, "season", None)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        if dialog.take_down:
            gone = lockedpage.take_down()
            said = "The private page is off the website." if gone else "There was no private page on the website."
        elif not settings.ready or not web.ready:
            said = "Saved. Nothing is uploaded until a passphrase is set and the website is set up."
        elif season is None or getattr(season, "is_empty", True) or not getattr(window, "auto_site", True):
            said = "Saved. The page goes up with the next card."
        else:
            done = lockedpage.refresh(season)
            said = (f"Saved and uploaded: {done} (give the website a minute)." if done else
                    "Saved. Nothing new to upload right now; the page goes up with the next card.")
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        write_log(f"private page failed: {exc!r}")
        said = f"Saved, but the upload didn't work: {exc}"
    finally:
        QApplication.restoreOverrideCursor()
    QMessageBox.information(window, "Private page", said)
    return True


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

    # The quiet background update may be uploading right now: two at once
    # would trip over each other on GitHub.
    worker = getattr(window, "_site_worker", None)
    if worker is not None and worker.isRunning():
        window.statusBar().showMessage("The website is updating itself - waiting for that to finish…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            finished = worker.wait(20_000)
        finally:
            QApplication.restoreOverrideCursor()
        if not finished:
            QMessageBox.information(
                window, "Pool page",
                "The website is updating itself right now. Give it a minute, then press Pool page again.")
            return None

    try:
        page, files, data = build_site(season)
    except Exception as exc:  # noqa: BLE001
        write_log(f"pool page build failed: {exc!r}\n{traceback.format_exc()}")
        QMessageBox.warning(window, "Pool page", f"Couldn't build the page: {exc}")
        return None
    week = max(poolpage.finished_weeks(season))
    window.statusBar().showMessage("Publishing the pool page…")
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        url = webpublish.publish(settings, page, message=f"After week {week}",
                                 files=files or None)
        published(data, week, url)
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
    note = poolpage.LIVE_NOTE[0]
    box = _box(window, "Pool page published", f"Week {week} is on the pool's website:\n{url}"
               + (f"\n\nLive tab: {note}" if note else ""),
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
