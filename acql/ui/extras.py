"""Small window-level conveniences (ideas #2, #6, #76, #77, #80, #92, #93).

* phase_place - which place the week's rhythm opens on (#2)
* plain words - chances said as words, for showing the screen to someone (#93)
* density - Glance hides a page's analyst cards (#6)
* cinema_screen - the monitor Cinema mode opens on (#76)
* jump commands - coaches and this week's games in Ctrl+K (#77)
* Tray - a tray icon whose colour says what's going on (#80)
* pins - cards pinned to "My board" (#92)

Each setting lives in QSettings; every one defaults to how the app behaved before.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

PHASE_KEY = "window/phase_open"
PLAIN_KEY = "view/plain_words"
DENSITY_KEY = "view/glance/"
SCREEN_KEY = "cinema/screen"
TRAY_KEY = "window/tray"
PINS_KEY = "board/pins"


def _on(key: str, default: bool) -> bool:
    value = QSettings().value(key, default)
    return value in (True, "true", "1", 1)


# ---- #2 the opening page follows the week ------------------------------------------------
def phase_place(season, now: float | None = None) -> tuple[str, str] | None:
    """(place title, why) for the moment of the week, or None to keep the remembered place.
    Games on: Game Day. Card-building days before the deadline: the picks. The day after
    the week's last game: the report card."""
    from .. import analytics, places
    from ..feeds import oddslock, results
    if season is None or not _on(PHASE_KEY, True):
        return None
    now = time.time() if now is None else now
    try:
        year = results.season_year(season, now)
        week = analytics.upcoming_week(season)
        lock = oddslock.lock_time(year, week)
        playing = results.calendar_weeks(year, now)
        scores = results.load(year, playing[0]) if playing else []
    except Exception:  # noqa: BLE001
        return None
    if any(s.state == "in" for s in scores):
        return places.GAME_DAY, "games are on"
    if 0 < lock - now < 2 * 86400:
        return places.THIS_WEEK, "the card locks within two days"
    weekday = time.localtime(now).tm_wday              # Monday 0
    if weekday in (0, 1) and scores and all(s.final or s.called_off for s in scores):
        return places.MODEL, "last week is over: time for the report card"
    return None


# ---- #93 plain words ---------------------------------------------------------------------
def plain_words() -> bool:
    return _on(PLAIN_KEY, False)


def chance_words(p: float) -> str:
    """A chance said as words: 'about 3 in 5', 'a coin flip', 'very likely (9 in 10)'."""
    if 0.47 <= p <= 0.53:
        return "a coin flip"
    for den in (2, 3, 4, 5, 10):
        num = round(p * den)
        if 0 < num < den and abs(num / den - p) <= 0.035:
            word = "likely" if p > 0.5 else "unlikely"
            return f"{word}, about {num} in {den}"
    return f"{'likely' if p > 0.5 else 'unlikely'}, about {round(p * 10)} in 10"


# ---- #6 density --------------------------------------------------------------------------
def glance(page_title: str) -> bool:
    return _on(DENSITY_KEY + page_title, False)


def apply_density(page) -> None:
    """Hide or show a page's analyst cards (`page.analyst_cards()`), per its remembered choice."""
    cards = getattr(page, "analyst_cards", lambda: [])()
    hide = glance(page.title)
    for card in cards:
        if card is not None:
            card.setProperty("glance_hidden", hide)
            if hide:
                card.hide()


def toggle_density(page) -> str:
    on = not glance(page.title)
    QSettings().setValue(DENSITY_KEY + page.title, on)
    page.refresh_now()
    apply_density(page)
    return "Glance: the answer and the main numbers" if on else "Analyst: everything"


# ---- #76 Cinema's screen --------------------------------------------------------------------
def cinema_screen(fallback):
    from PySide6.QtWidgets import QApplication
    name = QSettings().value(SCREEN_KEY, "")
    for screen in QApplication.screens():
        if name and screen.name() == name:
            return screen
    return fallback


# ---- #77 jumps in Ctrl+K ---------------------------------------------------------------------
def jump_commands(window, command_type) -> list:
    """'Coach: Jules' opens Player; 'Scout: New England @ Chicago' opens the scouting window."""
    from .. import analytics
    from .pages.player import PlayerPage
    season = window.season
    out = []
    if season is None:
        return out
    try:
        place, tab = window_group_of(PlayerPage)
    except KeyError:
        place = None
    if place is not None:
        for player in sorted(season.players.values(), key=lambda p: p.display.casefold()):
            def go(name=player.display):
                window._select_page(place, tab)
                page = window.groups[place].current_page()
                if hasattr(page, "select"):
                    page.select(name)
            out.append(command_type(f"Coach: {player.display}", "", go))
    week = analytics.upcoming_week(season)
    found = season.weeks.get(week)
    for game in sorted(found.games if found else [], key=lambda g: g.index):
        def scout(index=game.index, wk=week):
            from ..model import scouting
            from .scouting import ScoutingDialog
            report = scouting.report(season, index, wk)
            if report is not None:
                dialog = ScoutingDialog(report, window.palette_, window)
                dialog.exec()
                dialog.deleteLater()
        out.append(command_type(f"Scout: {game.label}", "", scout))
    return out


def window_group_of(cls):
    from .app import group_of
    return group_of(cls)


# ---- #80 tray ---------------------------------------------------------------------------------
COLOURS = {"live": "#45a3ff", "deadline": "#d6aa47", "trouble": "#e3a33a", "quiet": "#6b7280"}


def _dot(colour: str) -> QIcon:
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(colour))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 24, 24)
    p.end()
    return QIcon(pix)


def tray_state(window, now: float | None = None) -> tuple[str, str]:
    """(state, words) for the tray: live games, a deadline near, a scheduled job in trouble, or quiet."""
    from .. import analytics, readiness
    from ..feeds import oddslock, results
    now = time.time() if now is None else now
    season = window.season
    if season is None:
        return "quiet", "Nothing loaded"
    try:
        year = results.season_year(season, now)
        playing = results.calendar_weeks(year, now)
        if playing and any(s.state == "in" for s in results.load(year, playing[0])):
            return "live", "Games are on"
        week = analytics.upcoming_week(season)
        left = oddslock.lock_time(year, week) - now
        if 0 < left < 86400:
            return "deadline", f"Week {week} locks {readiness.until(left)}"
        last = readiness._last_run(now)
        if last is not None and last.state != readiness.OK:
            return "trouble", "The last scheduled run had a problem"
    except Exception:  # noqa: BLE001
        pass
    return "quiet", "All quiet"


class Tray:
    """The tray icon (#80): blue while games are on, gold the day the card locks, amber when a
    scheduled run had a problem. A notification when the state changes. Off unless chosen."""

    def __init__(self, window) -> None:
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        self.window = window
        self.icon = QSystemTrayIcon(_dot(COLOURS["quiet"]), window)
        menu = QMenu(window)
        menu.addAction("Open", lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
        menu.addAction("Cinema mode", window.toggle_cinema)
        menu.addAction("Hide the tray icon", lambda: set_tray(window, False))
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(lambda _r: (window.showNormal(), window.raise_(), window.activateWindow()))
        self.state = ""
        self.timer = QTimer(window)
        self.timer.timeout.connect(self.update)
        self.timer.start(60_000)
        self.icon.show()
        self.update()

    def update(self) -> None:
        state, words = tray_state(self.window)
        self.icon.setIcon(_dot(COLOURS[state]))
        self.icon.setToolTip(f"Operation Sunday - {words}")
        if self.state and state != self.state and state != "quiet":
            self.icon.showMessage("Operation Sunday", words)
        self.state = state

    def close(self) -> None:
        self.timer.stop()
        self.icon.hide()


def set_tray(window, on: bool) -> None:
    QSettings().setValue(TRAY_KEY, on)
    tray = getattr(window, "_tray", None)
    if on and tray is None:
        window._tray = Tray(window)
    elif not on and tray is not None:
        tray.close()
        window._tray = None


def start_tray(window) -> None:
    from PySide6.QtWidgets import QSystemTrayIcon
    if _on(TRAY_KEY, False) and QSystemTrayIcon.isSystemTrayAvailable():
        window._tray = Tray(window)


# ---- #92 My board ------------------------------------------------------------------------------
def pins() -> list[dict]:
    import json
    raw = QSettings().value(PINS_KEY, "[]")
    try:
        found = json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        found = []
    return [p for p in found if isinstance(p, dict) and p.get("card")]


def pin(place: int, tab: int, page_title: str, card_title: str) -> None:
    import json
    kept = [p for p in pins() if not (p.get("page") == page_title and p.get("card") == card_title)]
    kept.append({"place": place, "tab": tab, "page": page_title, "card": card_title})
    QSettings().setValue(PINS_KEY, json.dumps(kept[-20:]))


def unpin(page_title: str, card_title: str) -> None:
    import json
    QSettings().setValue(PINS_KEY, json.dumps(
        [p for p in pins() if not (p.get("page") == page_title and p.get("card") == card_title)]))


def go_to_card(window, entry: dict) -> None:
    """Open the pinned card's page and scroll it into view."""
    from .widgets import Card
    window._select_page(int(entry["place"]), int(entry.get("tab", 0)))
    page = window.groups[int(entry["place"])].current_page()
    for card in page.findChildren(Card):
        label = getattr(card, "title_label", None)
        if label is not None and label.text().startswith(entry["card"]) and card.isVisible():
            QTimer.singleShot(150, lambda c=card: page._scroll.ensureWidgetVisible(c, 0, 40))
            return
