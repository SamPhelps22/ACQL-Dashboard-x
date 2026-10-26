"""RedZone mode: a frame around a stream playing underneath it.

The scores ribbon runs along the top, the pool's standings down the right,
and the middle is a real hole in the window (a mask), so RedZone playing in
Chrome or the YouTube TV app shows through it and takes the clicks. The
stream itself is never played here: those services use copy protection the
dashboard's browser cannot play.

Fed by the window's LiveFeed, like Cinema mode, so nothing is fetched twice.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from .. import places
from ..model.predictions import display_team
from ..pool import gameday as GD
from ..pool import livestate as LS
from . import icons, teamlogos
from .cinema import pulse, set_prop
from .cinema import Changes, Leaderboard, stylesheet
from .ribbon import ScoreboardRibbon

#: The standings column on the right.
SIDE_WIDTH = 300
#: The thin gold edge drawn round the hole.
EDGE = 2
#: How much of the stream window's top is tucked up behind the scores bar
#: (browser bars and the site's menu), remembered; ▲/▼ nudge it.
#: The band under the stream: at least this tall; taller when the 16:9 picture leaves more room.
BAND_MIN = 90
#: How many 'just happened' lines the band shows.
BAND_RECENT = 3
TRIM_KEY = "redzone/trim"
#: The chimes when a pick flips between winning and losing; off when muted.
MUTE_KEY = "redzone/mute"
#: The scoring banner over the bottom of the stream: how tall, how long it stays (ms).
TAKEOVER_HEIGHT, TAKEOVER_MS = 64, 4500
TRIM_DEFAULT, TRIM_STEP = 170, 20


class RedZoneWindow(QWidget):
    closed = Signal()

    def __init__(self, window, feed, palette) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.window_ = window
        self.feed = feed
        self.palette_ = palette
        self.setObjectName("Cinema")
        self.setWindowTitle(f"{places.BRAND} – RedZone")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.ribbon = ScoreboardRibbon(palette)
        self.ribbon.cinema_btn.hide()
        self.ribbon.redzone_btn.hide()
        if hasattr(self.ribbon, "lab_btn"):
            self.ribbon.lab_btn.hide()
        outer.addWidget(self.ribbon)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        middle = QVBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.hole = QWidget()              # where the stream shows through
        self.hole.setObjectName("RedZoneHole")
        middle.addWidget(self.hole, 1)
        middle.addWidget(self._build_band())
        body.addLayout(middle, 1)
        body.addWidget(self._build_side())
        outer.addLayout(body, 1)
        self.takeover = QLabel(self)
        self.takeover.setObjectName("RedZoneTakeover")
        self.takeover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.takeover.hide()
        self._takeover_timer = QTimer(self)
        self._takeover_timer.setSingleShot(True)
        self._takeover_timer.timeout.connect(self._end_takeover)
        self.restyle(palette)

    def _build_band(self) -> QWidget:
        """Under the stream: your picks as logos (green winning, red losing,
        grey to come) and the last few things that happened."""
        band = QFrame()
        band.setObjectName("RedZoneBand")
        band.setFixedHeight(BAND_MIN)
        row = QHBoxLayout(band)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.picks_head = QLabel("MY PICKS")
        self.picks_head.setObjectName("CinemaHeading")
        left.addWidget(self.picks_head)
        self.picks_row = QHBoxLayout()
        self.picks_row.setSpacing(6)
        left.addLayout(self.picks_row)
        left.addStretch(1)
        row.addLayout(left)
        row.addStretch(1)
        right = QVBoxLayout()
        right.setSpacing(4)
        head = QLabel("JUST HAPPENED")
        head.setObjectName("CinemaHeading")
        right.addWidget(head)
        self.recent = QLabel("")
        self.recent.setObjectName("RedZoneRecent")
        self.recent.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.recent, 1)
        row.addLayout(right)
        self.band = band
        self.chips: list[tuple[QLabel, QLabel]] = []
        self._hot: set[int] = set()
        self._statuses: dict[int, str] | None = None
        self._start: dict[str, int] = {}
        self._start_week = 0
        self.meters: list[QProgressBar] = []
        self._scores: dict[int, tuple] = {}
        self._you_place: int | None = None
        return band

    def _show_band(self, you, changes: Changes | None = None) -> None:
        states = sorted(self.feed.states, key=lambda s: (s.kickoff or 0, s.index))
        picked = [(st, you.picks.get(st.index, GD.NOBODY)) for st in states] if you is not None else []
        picked = [(st, side) for st, side in picked if side != GD.NOBODY]
        while len(self.chips) > len(picked):
            logo, word = self.chips.pop()
            self.meters.pop()
            logo.parentWidget().deleteLater()
        while len(self.chips) < len(picked):
            cell = QFrame()
            cell.setObjectName("RedZonePick")
            box = QVBoxLayout(cell)
            box.setContentsMargins(4, 3, 4, 3)
            box.setSpacing(1)
            logo, word = QLabel(), QLabel()
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            word.setAlignment(Qt.AlignmentFlag.AlignCenter)
            word.setObjectName("RedZonePickWord")
            box.addWidget(logo)
            box.addWidget(word)
            meter = QProgressBar()
            meter.setObjectName("RedZoneMeter")
            meter.setRange(0, 100)
            meter.setTextVisible(False)
            meter.setFixedHeight(4)
            box.addWidget(meter)
            self.meters.append(meter)
            self.picks_row.addWidget(cell)
            self.chips.append((logo, word))
        winning = losing = 0
        statuses: dict[int, str] = {}
        hot_now: set[int] = set()
        scored = changes.scores if changes else frozenset()
        for (logo, word), meter, (st, side) in zip(self.chips, self.meters, picked):
            team = st.team(side)
            pix = teamlogos.pixmap(team, 30)
            if pix is not None:
                logo.setPixmap(pix)
            else:
                logo.setText(str(team)[:3].upper())
            if st.state in ("in", "final") and st.leader != GD.NOBODY:
                status = "win" if st.leader == side else "lose"
                winning += status == "win"
                losing += status == "lose"
            elif st.state in ("in", "final"):
                status = "even"
            else:
                status = "pre"
            word.setText({"pre": (LS.kickoff_et(st.kickoff).split(" ") + [""])[1] if st.kickoff else "–",
                          "even": "EVEN"}.get(status, "FINAL" if st.state == "final" else (st.clock or "LIVE").split(" ")[0]))
            cell = logo.parentWidget()
            set_prop(cell, "status", status)
            # the chance this pick ends up credited: Deadeye before kickoff, ESPN's live odds blended in once under way
            chance = st.chance(side)
            meter.setValue(round(chance * 100))
            set_prop(meter, "level", "high" if chance >= 0.6 else "low" if chance <= 0.4 else "mid")
            statuses[st.index] = status
            # your team driving in the red zone: gold, and a pulse as it gets there
            hot = (st.state == "in" and st.red_zone
                   and st.possession == ("home" if side == GD.HOME else "away"))
            set_prop(cell, "hot", "true" if hot else "")
            if hot:
                hot_now.add(st.index)
            if (hot and st.index not in self._hot) or st.index in scored:
                pulse(cell)
            logo.parentWidget().setToolTip(f"{st.game.label} · your pick {team} · line {st.line_text()}"
                                           f" · {chance:.0%} to be credited")
        self._hot = hot_now
        self._chime(statuses)
        self.picks_head.setText(f"MY PICKS · {winning} WINNING · {losing} LOSING" if picked else
                                "MY PICKS · none on the sheet yet")
        items = list(self.feed.recent)[:BAND_RECENT]
        self.recent.setText("\n".join(f"{LS.clock_et(at)}   {text}" for at, text, _ in items) if items else
                            "Scores that change while this is open show here.")

    def _chime(self, statuses: dict[int, str]) -> None:
        """A rising chime when a pick goes from losing to winning, a low tone the
        other way. Never on the first look, never when muted."""
        before, self._statuses = self._statuses, statuses
        if before is None or self.muted():
            return
        flips = [(before.get(i), s) for i, s in statuses.items()]
        good = any(b == "lose" and s == "win" for b, s in flips)
        bad = any(b == "win" and s == "lose" for b, s in flips)
        if good or bad:
            play_tones(good, bad)

    def muted(self) -> bool:
        return str(QSettings().value(MUTE_KEY, "false")).lower() == "true"

    def toggle_mute(self) -> None:
        QSettings().setValue(MUTE_KEY, "false" if self.muted() else "true")
        self._show_mute()

    def _show_mute(self) -> None:
        self.mute_btn.setText("MUTED" if self.muted() else "SOUND ON")
        self.mute_btn.setToolTip("Chimes when one of your picks flips between winning and losing (click to switch)")

    def _size_band(self) -> None:
        """The band takes what a 16:9 picture leaves under it."""
        width = self.width() - SIDE_WIDTH
        room = self.height() - self.ribbon.sizeHint().height()
        self.band.setFixedHeight(max(BAND_MIN, room - round(width * 9 / 16)))

    def _show_moves(self, rows) -> None:
        """▲/▼ places since RedZone mode first showed this week; your row kept in view."""
        week = self.feed.week
        if week != self._start_week or not self._start:
            self._start_week = week
            self._start = {name: place for name, place, _p, _y in rows}
        you_row = None
        for name, place, _points, you in rows:
            row = self.board.rows.get(name)
            if row is None:
                continue
            moved = self._start.get(name, place) - place
            row.name.setText(name + (f"  ▲{moved}" if moved > 0 else f"  ▼{-moved}" if moved < 0 else ""))
            row.setToolTip("Places moved since RedZone mode opened this week" if moved else "")
            if you:
                you_row = row
        if you_row is not None:
            self.board_scroll.ensureWidgetVisible(you_row, 0, 60)

    def _build_side(self) -> QWidget:
        side = QFrame()
        side.setObjectName("CinemaSide")
        side.setFixedWidth(SIDE_WIDTH)
        box = QVBoxLayout(side)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        top = QHBoxLayout()
        self.title = QLabel("ACQL")
        self.title.setObjectName("RedZoneTitle")
        top.addWidget(self.title, 1)
        self.mute_btn = QPushButton()
        self.mute_btn.setObjectName("CinemaExit")
        self.mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute_btn.clicked.connect(self.toggle_mute)
        top.addWidget(self.mute_btn)
        self.exit_btn = QPushButton()
        self.exit_btn.setObjectName("CinemaExit")
        self.exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exit_btn.setToolTip("Close RedZone mode (Esc)")
        self.exit_btn.clicked.connect(self.close)
        top.addWidget(self.exit_btn)
        box.addLayout(top)
        self.fit_btn = QPushButton("FIT STREAM")
        self.fit_btn.setObjectName("CinemaExit")
        self.fit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fit_btn.setToolTip("Finds the Spectrum / RedZone window and sizes it to fill the middle")
        self.fit_btn.clicked.connect(self.fit_stream)
        fit_row = QHBoxLayout()
        fit_row.addWidget(self.fit_btn, 1)
        for text, way, tip in (("▲", 1, "Hide more of the stream's top"), ("▼", -1, "Show more of the stream's top")):
            nudge = QPushButton(text)
            nudge.setObjectName("CinemaExit")
            nudge.setFixedWidth(44)
            nudge.setToolTip(tip)
            nudge.setCursor(Qt.CursorShape.PointingHandCursor)
            nudge.clicked.connect(lambda *_, w=way: self.nudge(w))
            fit_row.addWidget(nudge)
        box.addLayout(fit_row)
        self.open_btn = QPushButton("OPEN SPECTRUM")
        self.open_btn.setObjectName("CinemaExit")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setToolTip("Opens Spectrum's live TV in a bare Chrome window and fits it into the gap")
        self.open_btn.clicked.connect(self.open_spectrum)
        box.addWidget(self.open_btn)
        self.heading = QLabel("POOL · IF IT ENDED NOW")
        self.heading.setObjectName("CinemaHeading")
        box.addWidget(self.heading)
        self.you_line = QLabel("")
        self.you_line.setObjectName("RedZoneYou")
        self.you_line.setWordWrap(True)
        box.addWidget(self.you_line)
        scroll = QScrollArea()
        scroll.setObjectName("CinemaScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.board = Leaderboard()
        scroll.setWidget(self.board)
        self.board_scroll = scroll
        box.addWidget(scroll, 1)
        self.note = QLabel("")
        self.note.setObjectName("CinemaMeta")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        return side

    def restyle(self, palette) -> None:
        self.palette_ = palette
        gold = palette.brand or palette.accent
        self.board.gold = gold
        self.ribbon.restyle(palette)
        self.setStyleSheet(stylesheet(palette) + f"""
            #RedZoneTitle {{ color: {gold}; font-size: 22px; font-weight: 800; letter-spacing: 4px; }}
            #CinemaSide {{ border-left: {EDGE}px solid {gold}; }}
            #ScoreRibbon {{ border-bottom: {EDGE}px solid {gold}; }}
            #RedZoneBand {{ border-top: {EDGE}px solid {gold}; }}
            #RedZoneRecent {{ font-size: 13px; color: {palette.ink}; }}
            #RedZonePick {{ border-radius: 6px; border: 1px solid {palette.ink_muted}; min-width: 46px; }}
            #RedZonePick[status="win"] {{ border: 2px solid #3ccf7a; background: rgba(60,207,122,0.16); }}
            #RedZonePick[status="lose"] {{ border: 2px solid #e5484d; background: rgba(229,72,77,0.16); }}
            #RedZonePick[status="even"] {{ border: 2px solid #e8b84e; }}
            #RedZonePick[hot="true"] {{ border: 2px solid {gold}; background: rgba(232,184,78,0.30); }}
            #RedZoneMeter {{ background: rgba(255,255,255,0.10); border: none; border-radius: 2px; }}
            #RedZoneMeter::chunk {{ border-radius: 2px; background: {gold}; }}
            #RedZoneMeter[level="high"]::chunk {{ background: #3ccf7a; }}
            #RedZoneMeter[level="low"]::chunk {{ background: #e5484d; }}
            #RedZoneYou {{ color: {gold}; font-size: 13px; font-weight: 700; }}
            #RedZoneTakeover {{ background: rgba(8,10,16,0.92); color: {gold}; font-size: 24px; font-weight: 800;
                                letter-spacing: 2px; border-top: 3px solid {gold}; }}
            #RedZonePickWord {{ font-size: 10px; font-weight: 700; color: {palette.ink_muted}; }}""")
        self.exit_btn.setIcon(icons.icon("cross", palette.ink, palette.ink, 16))
        self._show_mute()

    # ---- in and out ------------------------------------------------------------
    def enter(self) -> None:
        from . import extras
        screen = extras.cinema_screen(self.window_.screen())
        if screen is not None:
            self.setGeometry(screen.availableGeometry())
        self.refresh(Changes(self.feed.week))
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(300, self.fit_stream)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        super().closeEvent(event)
        self.closed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._size_band()
        self._cut_hole()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._cut_hole()

    def _cut_hole(self) -> None:
        """The window keeps only the ribbon and the side column; the middle
        is not part of it at all, so the stream underneath gets the clicks."""
        self.layout().activate()
        hole = QRect(self.hole.mapTo(self, self.hole.rect().topLeft()), self.hole.size())
        region = QRegion(self.rect()).subtracted(QRegion(hole))
        if self.takeover.isVisible():
            self.takeover.setGeometry(hole.left(), hole.bottom() + 1 - TAKEOVER_HEIGHT, hole.width(), TAKEOVER_HEIGHT)
            region = region.united(QRegion(self.takeover.geometry()))
        self.setMask(region)

    def trim(self) -> int:
        try:
            return max(0, int(QSettings().value(TRIM_KEY, TRIM_DEFAULT)))
        except (TypeError, ValueError):
            return TRIM_DEFAULT

    def nudge(self, way: int) -> None:
        QSettings().setValue(TRIM_KEY, max(0, self.trim() + way * TRIM_STEP))
        self.fit_stream()

    def open_spectrum(self) -> None:
        from . import streamfit
        if not streamfit.open_spectrum():
            self.note.setText("Chrome was not found.")
            return
        self.note.setText("Opening Spectrum… it fits itself in a few seconds.")
        QTimer.singleShot(5000, self.fit_stream)

    def fit_stream(self) -> None:
        """Size the stream's window to the gap, its title bar under the scores bar."""
        from . import streamfit
        found = streamfit.find_stream()
        if found is None:
            self.note.setText("No Spectrum / RedZone window found. Open it (not full screen), then press Fit.")
            return
        screen = self.screen()
        dpr = screen.devicePixelRatio()
        origin = screen.geometry().topLeft()
        corner = self.hole.mapToGlobal(self.hole.rect().topLeft())
        x = origin.x() + round((corner.x() - origin.x()) * dpr)
        y = origin.y() + round((corner.y() - origin.y()) * dpr)
        room = screen.geometry().height() - self.hole.height()     # Windows caps a window at the screen's height
        trim = round(min(self.trim(), max(0, room)) * dpr)
        ok = streamfit.fit(found[0], x, y - trim, round(self.hole.width() * dpr),
                           round(self.hole.height() * dpr) + trim)
        self.raise_()
        self.note.setText(f"Fitted: {found[1][:40]}. If the player goes full screen, leave it and press Fit again."
                          if ok else "Windows would not move that window.")

    # ---- what it shows ------------------------------------------------------------
    def refresh(self, changes: Changes | None = None) -> None:
        feed = self.feed
        season = self.window_.season
        self.ribbon.set_feed(feed, season, changes)
        if not feed.week:
            self.ribbon.show()          # the ribbon hides itself with no week; here it stays as the frame
        self.heading.setText(f"WEEK {feed.week} · IF IT ENDED NOW" if feed.week else "POOL STANDINGS")
        bd = None
        if feed.week and feed.states:
            from .ribbon import viewer
            try:
                bd = GD.board(season, feed.week, viewer(season), kept=feed.kept)
            except Exception:  # noqa: BLE001 - the scores still show without the standings
                bd = None
        try:
            self._show_band(bd.you.card if bd is not None and bd.you is not None else None, changes)
        except Exception:  # noqa: BLE001 - the band is extra; the frame still shows
            pass
        if bd is None or not bd.standings:
            self.board.show_rows([], LS.Movement())
            self.note.setText("Standings appear once the week's pick sheet is in.")
            return
        rows = [(s.card.name, s.place, s.total_now, s.card.you)
                for s in bd.standings if s.place is not None and s.card.name]
        self.board.show_rows(rows, LS.Movement())
        self._show_moves(rows)
        me = bd.you
        if me is not None and me.place is not None:
            words = [f"YOU: {ordinal(me.place)} NOW"]
            if me.best is not None:
                words.append("STILL CAN WIN IT" if me.best == 1 else f"BEST POSSIBLE {ordinal(me.best)}")
            if me.chance is not None and me.chance >= 0.005:
                words.append(f"{me.chance:.0%} TO WIN THE WEEK")
            self.you_line.setText(" · ".join(words))
        else:
            self.you_line.setText("")
        self._maybe_takeover(bd, changes)

    def _maybe_takeover(self, bd, changes: Changes | None) -> None:
        """A score in a game you picked: a banner over the bottom of the stream
        for a few seconds, saying what it was and what it did to your place."""
        me = bd.you
        place_before, self._you_place = self._you_place, me.place if me is not None else None
        before_scores = self._scores
        self._scores = {st.index: (st.away_points or 0, st.home_points or 0) for st in self.feed.states}
        if not changes or me is None or not before_scores:
            return
        mine = me.card.picks
        hits = [st for st in self.feed.states if st.index in changes.scores and mine.get(st.index, GD.NOBODY) != GD.NOBODY]
        if not hits:
            return
        st = hits[0]
        old = before_scores.get(st.index, (0, 0))
        new = self._scores[st.index]
        gain = max(new[0] - old[0], new[1] - old[1])
        kind = "TOUCHDOWN" if gain >= 6 else "FIELD GOAL" if gain == 3 else "SAFETY" if gain == 2 else "SCORE"
        scorer = st.game.away if new[0] - old[0] >= new[1] - old[1] else st.game.home
        line = (f"{kind} {display_team(scorer).upper()}  ·  {display_team(st.game.away)} {new[0]} – "
                f"{new[1]} {display_team(st.game.home)}")
        if place_before is not None and me.place is not None and me.place != place_before:
            way = "▲" if me.place < place_before else "▼"
            line += f"  ·  YOU {way}{abs(place_before - me.place)} TO {ordinal(me.place)}"
        self.show_takeover(line)

    def show_takeover(self, text: str) -> None:
        self.takeover.setText(text)
        self.takeover.show()
        self.takeover.raise_()
        self._cut_hole()
        self._takeover_timer.start(TAKEOVER_MS)

    def _end_takeover(self) -> None:
        self.takeover.hide()
        self._cut_hole()


def ordinal(n: int) -> str:
    suffix = "TH" if 10 <= n % 100 <= 20 else {1: "ST", 2: "ND", 3: "RD"}.get(n % 10, "TH")
    return f"{n}{suffix}"


def play_tones(good: bool, bad: bool) -> None:
    """The chimes, off the window's thread so nothing waits on them (Windows only)."""
    import sys
    import threading
    if sys.platform != "win32":
        return

    def play() -> None:
        import winsound
        try:
            if good:
                winsound.Beep(880, 110)
                winsound.Beep(1320, 170)
            if bad:
                winsound.Beep(330, 320)
        except RuntimeError:
            pass
    threading.Thread(target=play, daemon=True).start()
