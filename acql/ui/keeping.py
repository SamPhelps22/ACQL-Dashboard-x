"""Keeping the website current with nobody at the computer.

The dashboard already does the work by itself while it runs: it asks ESPN
for results while games are on, reads a pick sheet the moment it lands in the
folder, and puts the website up whenever what it shows has changed. All of
that stops when the window is closed. So:

* In the tray: closing the window leaves the dashboard running out of sight,
  with an icon by the clock to open it again, check now, or quit.
* Start with Windows: it starts in the tray when Windows does, so the site
  keeps itself up to date from the moment the computer is on.

The computer still has to be on and awake; nothing here can change that.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

TRAY_KEY = "background/tray"
TOLD_KEY = "background/told"
#: Windows' list of programs to start at sign-in, for this account only.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "ACQL Dashboard"
BACKGROUND_FLAG = "--background"


def tray_wanted() -> bool:
    return QSettings().value(TRAY_KEY, False, type=bool) is True


def set_tray_wanted(on: bool) -> None:
    QSettings().setValue(TRAY_KEY, bool(on))


def tray_available() -> bool:
    try:
        return QSystemTrayIcon.isSystemTrayAvailable() is True
    except Exception:  # noqa: BLE001
        return False


def startup_command(root: Path | None = None, executable: str | None = None) -> str:
    """What Windows runs at sign-in: the windowless Python beside this one,
    on run.py, starting in the tray."""
    from .. import store
    root = Path(root) if root else store.project_root()
    exe = Path(executable or sys.executable)
    quiet = exe.with_name("pythonw.exe")
    if exe.name.lower() == "python.exe" and quiet.exists():
        exe = quiet
    return f'"{exe}" "{root / "run.py"}" {BACKGROUND_FLAG}'


def _registry():
    if sys.platform != "win32":
        return None
    import winreg
    return winreg


def startup_enabled() -> bool:
    reg = _registry()
    if reg is None:
        return False
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = reg.QueryValueEx(key, RUN_NAME)
        return bool(value)
    except OSError:
        return False


def set_startup(on: bool) -> str:
    """Start with Windows, or stop; "" when done, else why not, in words."""
    reg = _registry()
    if reg is None:
        return "Starting with the computer is only for Windows."
    try:
        with reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if on:
                reg.SetValueEx(key, RUN_NAME, 0, reg.REG_SZ, startup_command())
            else:
                try:
                    reg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
        return ""
    except OSError as exc:
        return f"Windows wouldn't change its start-up list ({exc})."


class Tray:
    """The icon by the clock while the dashboard runs out of sight."""

    def __init__(self, window) -> None:
        self.window = window
        self.icon = QSystemTrayIcon(window)
        from .. import config
        icon_file = getattr(config, "ICON_FILE", None)
        if icon_file is not None and Path(icon_file).is_file():
            self.icon.setIcon(QIcon(str(icon_file)))
        else:
            self.icon.setIcon(window.windowIcon())
        self.icon.setToolTip("ACQL Dashboard - keeping the website up to date")
        menu = QMenu(window)
        for text, run in (("Open the dashboard", self.open),
                          ("Check for results now", window.check_results_now),
                          ("Update the website now", window.update_site),
                          (None, None),
                          ("Quit", self.quit)):
            if text is None:
                menu.addSeparator()
                continue
            action = QAction(text, menu)
            action.triggered.connect(lambda *_a, run=run: run())
            menu.addAction(action)
        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        self.icon.show()

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open()

    def open(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        if getattr(self.window, "_pending_update", None):
            from . import updatecheck
            updatecheck.offer(self.window)

    def quit(self) -> None:
        self.window.quit_for_real()

    def say_once(self) -> None:
        """The first time the window goes to the tray, say where it went."""
        settings = QSettings()
        if settings.value(TOLD_KEY, False, type=bool) is True:
            return
        settings.setValue(TOLD_KEY, True)
        self.icon.showMessage(
            "Still running",
            "The dashboard is keeping the website up to date from the tray. "
            "Right-click its icon to open it or quit.",
        )

    def hide(self) -> None:
        self.icon.hide()


# ---- one dashboard at a time ---------------------------------------------------------------
# With the dashboard in the tray, a double-click on its shortcut would start a
# second copy - two windows reading and writing the same database and both
# putting the website up. Instead the second one rings the first, which shows
# itself, and leaves.
DOORBELL = "acql-dashboard-doorbell"


def _doorbell_name() -> str:
    import getpass
    try:
        who = getpass.getuser()
    except Exception:  # noqa: BLE001
        who = "me"
    return f"{DOORBELL}-{''.join(ch for ch in who if ch.isalnum()) or 'me'}"


def hand_over(show: bool = True) -> bool:
    """True when another dashboard is already running here (and has been
    asked to show its window, unless `show` is False)."""
    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError:
        return False
    socket = QLocalSocket()
    socket.connectToServer(_doorbell_name())
    if not socket.waitForConnected(400):
        return False
    socket.write(b"show" if show else b"stay")
    socket.flush()
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()
    return True


def listen(window):
    """Answer the doorbell: a second launch brings this window forward."""
    try:
        from PySide6.QtNetwork import QLocalServer
    except ImportError:
        return None
    name = _doorbell_name()
    QLocalServer.removeServer(name)            # a doorbell left by a copy that crashed
    server = QLocalServer(window)
    if not server.listen(name):
        return None

    def answer() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            conn.waitForReadyRead(400)
            if bytes(conn.readAll()).startswith(b"show"):
                window.showNormal()
                window.raise_()
                window.activateWindow()
            conn.disconnectFromServer()

    server.newConnection.connect(answer)
    return server
