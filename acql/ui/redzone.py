"""RedZone mode: a frame around a stream playing underneath it.

The scores ribbon runs along the top, the pool's standings down the right,
and the middle is a real hole in the window (a mask), so RedZone playing in
Chrome or the YouTube TV app shows through it and takes the clicks. The
stream itself is never played here: those services use copy protection the
dashboard's browser cannot play.

Under the stream, a band: your picks, the spotlight (the game most worth
watching right now, with its drive and a queue of the others) and what just
happened. The spotlight is chosen by liveplus from the scoreboard as kept -
red zone, a score, a turnover, a close finish, your picks - and can be
overridden by hand, pinned, or switched off.

Fed by the window's LiveFeed, like Cinema mode, so nothing is fetched twice:
scores are polled from ESPN's scoreboard, never streamed.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QRect, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import places
from ..model.predictions import display_team
from ..pool import gameday as GD
from ..pool import liveplus as LP
from ..pool import livestate as LS
from . import icons, teamlogos
from .cinema import (Changes, Leaderboard, pref, priority_weights, pulse, recent_html, set_pref, set_prop,
                     stylesheet)
from .ribbon import ScoreboardRibbon
from .widgets import ElidedLabel

#: The standings column on the right.
SIDE_WIDTH = 300
#: The thin gold edge drawn round the hole.
EDGE = 2
#: The band under the stream: at least this tall; taller when the 16:9 picture leaves more room.
BAND_MIN = 132
#: How many 'just happened' lines the band shows.
BAND_RECENT = 3
#: How much of the stream window's top is tucked up behind the scores bar
#: (browser bars and the site's menu), remembered; ▲/▼ nudge it.
TRIM_KEY = "redzone/trim"
TRIM_DEFAULT, TRIM_STEP = 170, 20
#: The chimes when a pick flips between winning and losing; off when muted (shared with Cinema).
MUTE_KEY = "redzone/mute"
#: Cover the taskbar as well (the whole screen) rather than the work area.
COVER_KEY = "redzone/cover"
#: The scoring banner over the bottom of the stream: how tall, how long it stays (ms).
TAKEOVER_HEIGHT, TAKEOVER_MS = 64, 4500
#: Every few seconds: the spotlight looked at again, the stream kept in the gap.
TICK_MS = 5000
#: The controls stay this long after the mouse leaves the side column (ms).
HIDE_AFTER_MS = 3500
#: The stream window counts as moved once it is this far (physical pixels) from the gap.
DRIFT = 8
#: The other live games offered beside the spotlight.
QUEUE = 4

GREEN, RED = "#3ccf7a", "#e5484d"


class FieldBar(QWidget):
    """The drive, drawn left to right towards the end zone being attacked:
    the red zone shaded, the ball where the scoreboard says it is. With no
    field position from the scoreboard, nothing is drawn but the field."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setMinimumWidth(160)
        self.to_goal: int | None = None
        self.gold = "#e8b84e"

    def show_drive(self, to_goal: int | None) -> None:
        if to_goal != self.to_goal:
            self.to_goal = to_goal
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        end = w * 0.08
        field = QRectF(end, 2, w - 2 * end, h - 4)
        p.fillRect(QRectF(0, 2, end, h - 4), QColor(255, 255, 255, 18))
        p.fillRect(QRectF(w - end, 2, end, h - 4), QColor(self.gold).darker(250))
        p.fillRect(field, QColor(255, 255, 255, 10))
        red = QRectF(field.right() - field.width() * 0.2, 2, field.width() * 0.2, h - 4)
        p.fillRect(red, QColor(229, 72, 77, 60))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        for i in range(1, 10):
            x = field.left() + field.width() * i / 10
            p.drawLine(int(x), 4, int(x), h - 4)
        if self.to_goal is not None:
            x = field.left() + field.width() * (100 - self.to_goal) / 100
            p.setPen(QPen(QColor(self.gold), 2))
            p.drawLine(int(field.left()), h // 2, int(x), h // 2)
            p.setBrush(QColor(self.gold))
            p.drawEllipse(QRectF(x - 5, h / 2 - 5, 10, 10))
        p.end()


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
        # what the band remembers between looks
        self.chips: list[tuple[QLabel, QLabel]] = []
        self.meters: list[QProgressBar] = []
        self._hot: set[int] = set()
        self._statuses: dict[int, str] | None = None
        self._start: dict[str, tuple[int, int]] = {}
        self._start_week = 0
        self._scores: dict[int, tuple] = {}
        self._you_place: int | None = None
        self._you = None
        self._bd = None
        self._queue: list[int] = []
        # the stream window, once fitted: its handle and where it was put
        self._stream: int | None = None
        self._target: tuple[int, int, int, int] | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.ribbon = ScoreboardRibbon(palette)
        for name in ("cinema_btn", "redzone_btn", "lab_btn"):
            if hasattr(self.ribbon, name):
                getattr(self.ribbon, name).hide()
        # a matchup clicked on the ticker goes into the spotlight
        self.ribbon.game_chosen.connect(lambda _week, index: self.choose_game(index))
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
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_controls)
        self.restyle(palette)

    # ---- the band under the stream ---------------------------------------------------------
    def _build_band(self) -> QWidget:
        """Your picks, the spotlight game and what just happened."""
        band = QFrame()
        band.setObjectName("RedZoneBand")
        band.setFixedHeight(BAND_MIN)
        row = QHBoxLayout(band)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.picks_head = QLabel("MY PICKS")
        self.picks_head.setObjectName("CinemaHeading")
        left.addWidget(self.picks_head)
        self.picks_row = QHBoxLayout()
        self.picks_row.setSpacing(4)
        left.addLayout(self.picks_row)
        left.addStretch(1)
        row.addLayout(left)
        row.addStretch(1)
        row.addWidget(self._build_spot())
        right = QVBoxLayout()
        right.setSpacing(4)
        head = QLabel("JUST HAPPENED")
        head.setObjectName("CinemaHeading")
        right.addWidget(head)
        self.recent = QLabel("")
        self.recent.setObjectName("RedZoneRecent")
        self.recent.setTextFormat(Qt.TextFormat.RichText)
        self.recent.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.recent.setMinimumWidth(260)
        self.recent.setWordWrap(True)
        right.addWidget(self.recent, 1)
        row.addLayout(right)
        self.band = band
        return band

    def _build_spot(self) -> QWidget:
        spot = QFrame()
        spot.setObjectName("RedZoneSpot")
        spot.setFixedWidth(420)
        box = QVBoxLayout(spot)
        box.setContentsMargins(10, 6, 10, 6)
        box.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        cap = QLabel("SPOTLIGHT")
        cap.setObjectName("CinemaHeading")
        top.addWidget(cap)
        self.spot_reason = ElidedLabel("")
        self.spot_reason.setObjectName("RedZoneReason")
        top.addWidget(self.spot_reason, 1)
        self.pin_btn = self._small("PIN", "Keep this game in the spotlight until unpinned", self.toggle_pin)
        self.pin_btn.setCheckable(True)
        top.addWidget(self.pin_btn)
        box.addLayout(top)
        self.spot_line = ElidedLabel("")
        self.spot_line.setObjectName("RedZoneSpotLine")
        box.addWidget(self.spot_line)
        drive = QHBoxLayout()
        drive.setSpacing(8)
        self.field = FieldBar()
        drive.addWidget(self.field, 1)
        self.down = QLabel("")
        self.down.setObjectName("RedZoneDown")
        drive.addWidget(self.down)
        box.addLayout(drive)
        self.last_play = ElidedLabel("")
        self.last_play.setObjectName("RedZoneLastPlay")
        box.addWidget(self.last_play)
        queue = QHBoxLayout()
        queue.setSpacing(4)
        nxt = self.queue_cap = QLabel("QUEUE")
        nxt.setObjectName("RedZoneCaption")
        queue.addWidget(nxt)
        self.queue_btns: list[QPushButton] = []
        for _ in range(QUEUE):
            btn = self._small("", "Put this game in the spotlight", None)
            btn.clicked.connect(lambda *_, b=btn: self.choose_game(b.property("index")))
            btn.hide()
            queue.addWidget(btn)
            self.queue_btns.append(btn)
        queue.addStretch(1)
        box.addLayout(queue)
        self.spot = spot
        return spot

    def _small(self, text: str, tip: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("RedZoneBtn")
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot is not None:
            btn.clicked.connect(lambda *_: slot())
        return btn

    def _show_band(self, you, changes: Changes | None = None) -> None:
        spoil = pref("spoilers")
        states = sorted(self.feed.states, key=lambda s: (s.kickoff or 0, s.index))
        picked = [(st, you.picks.get(st.index, GD.NOBODY)) for st in states] if you is not None else []
        picked = [(st, side) for st, side in picked if side != GD.NOBODY]
        while len(self.chips) > len(picked):
            logo, _word = self.chips.pop()
            self.meters.pop()
            logo.parentWidget().deleteLater()
        while len(self.chips) < len(picked):
            cell = QFrame()
            cell.setObjectName("RedZonePick")
            cell.setFixedWidth(50)
            box = QVBoxLayout(cell)
            box.setContentsMargins(3, 3, 3, 3)
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
        counts = {"correct": 0, "incorrect": 0, "winning": 0, "losing": 0}
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
            status = LP.pick_status(st, side)
            statuses[st.index] = status
            if status in counts:
                counts[status] += 1
            clock = (st.clock or "LIVE").split(" ")[0].upper()
            kick = (LS.kickoff_et(st.kickoff).split(" ") + [""])[1] if st.kickoff else "–"
            if spoil:
                shown = "upcoming" if status == "upcoming" else "hidden"
                text = kick if status == "upcoming" else ("FINAL" if st.state == "final" else "LIVE")
            else:
                shown = status
                text = {"upcoming": kick, "correct": "✓ WON", "incorrect": "✗ LOST", "push": "PUSH",
                        "postponed": "PPD", "level": "LEVEL"}.get(status, clock)
            word.setText(text)
            cell = logo.parentWidget()
            set_prop(cell, "status", shown)
            # the chance this pick ends up credited: Deadeye before kickoff, ESPN's live odds blended in once under way
            chance = st.chance(side)
            meter.setValue(round(chance * 100))
            meter.setVisible(not spoil)
            set_prop(meter, "level", "high" if chance >= 0.6 else "low" if chance <= 0.4 else "mid")
            # your team driving in the red zone: gold, and a pulse as it gets there
            hot = (st.state == "in" and st.red_zone
                   and st.possession == ("home" if side == GD.HOME else "away"))
            set_prop(cell, "hot", "true" if hot else "")
            if hot:
                hot_now.add(st.index)
            if not spoil and ((hot and st.index not in self._hot) or st.index in scored):
                pulse(cell)
            tip = f"{st.game.label} · your pick {team}"
            if not spoil:
                tip += f" · line {st.line_text()} · {chance:.0%} to be credited · {status}"
            cell.setToolTip(tip)
        self._hot = hot_now
        self._chime(statuses, spoil)
        if not picked:
            self.picks_head.setText("MY PICKS · none on the sheet yet")
        elif spoil:
            self.picks_head.setText("MY PICKS · SPOILER-FREE")
        else:
            bits = [f"{counts['correct']} RIGHT", f"{counts['incorrect']} WRONG"]
            if counts["winning"] or counts["losing"]:
                bits += [f"{counts['winning']} WINNING", f"{counts['losing']} LOSING"]
            self.picks_head.setText("MY PICKS · " + " · ".join(bits))
        self._show_recent(spoil)

    def _show_recent(self, spoil: bool) -> None:
        items = list(self.feed.recent)
        if spoil:
            items = [i for i in items if i[2] == "state"]        # kickoffs only: no scores, no standings
        items = items[:BAND_RECENT]
        self.recent.setText(recent_html(items, self.palette_) if items else
                            "Kickoffs show here." if spoil else
                            "Scores and standings changes show here as they happen.")

    # ---- the spotlight ---------------------------------------------------------------------
    def _picks(self) -> dict:
        return self._you.picks if self._you is not None else {}

    def _show_spot(self) -> None:
        feed = self.feed
        spot = feed.spotlight
        spot.auto = pref("auto")
        ranked = LP.spotlight_rank(feed.states, self._picks(), scored_at=feed.scored_at,
                                   weights=priority_weights())
        index = spot.update(ranked, feed.states)
        feed.selected = index
        st = next((s for s in feed.states if s.index == index), None)
        self.pin_btn.setChecked(spot.pinned is not None and spot.pinned == index)
        self.pin_btn.setText("PINNED" if self.pin_btn.isChecked() else "PIN")
        self.pin_btn.setEnabled(st is not None)
        spoil = pref("spoilers")
        if st is None:
            self.spot_reason.setText("")
            self.spot_line.setText("No game on right now" if feed.week else "No week being played")
            self.field.show_drive(None)
            self.down.setText("")
            self.last_play.setText("")
        else:
            rank = next((r for r in ranked if r.index == index), None)
            why = []
            if spot.pinned == index:
                why.append("PINNED")
            elif time.time() < spot.manual_until:
                why.append("YOUR CHOICE")
            elif not spot.auto:
                why.append("AUTO OFF")
            if rank is not None and not spoil:
                why.append(LP.reason_words([r for r in rank.reasons if r != "live"]))
            self.spot_reason.setText(" · ".join(w for w in why if w))
            clock = st.clock or LS.card_state(st.state).label
            if st.state == "pre":
                clock = LS.kickoff_et(st.kickoff) if st.kickoff else "Kickoff to come"
            if spoil or not st.started:
                line = f"{display_team(st.game.away)} at {display_team(st.game.home)}"
            else:
                line = (f"{display_team(st.game.away)} {st.away_points} – {st.home_points} "
                        f"{display_team(st.game.home)}")
            self.spot_line.setText(f"{line}  ·  {clock}")
            dr = LP.drive(st, teamlogos.code_in) if not spoil else None
            self.field.show_drive(dr.to_goal if dr is not None else None)
            if dr is not None:
                holder = st.game.home if dr.team == "home" else st.game.away
                self.down.setText(f"{display_team(holder).upper()} · {dr.down_text}"
                                  + (f" · {dr.to_goal} TO GO" if dr.to_goal is not None else ""))
            else:
                self.down.setText("" if spoil or st.state != "in" else "No drive details from the scoreboard")
            self.last_play.setText("" if spoil else (st.last_play or ""))
        # the queue: the other live games, best first
        others = [r.index for r in ranked if r.index != index][:QUEUE]
        by_index = {s.index: s for s in feed.states}
        self._queue = others
        self.queue_cap.setVisible(bool(others))
        for btn, i in zip(self.queue_btns, others + [None] * QUEUE):
            if i is None:
                btn.hide()
                continue
            g = by_index[i]
            btn.setText(f"{teamlogos.code_in(g.game.away).upper() or display_team(g.game.away)[:3]}–"
                        f"{teamlogos.code_in(g.game.home).upper() or display_team(g.game.home)[:3]}")
            btn.setProperty("index", i)
            btn.setToolTip(f"{g.game.label} · put it in the spotlight")
            btn.show()

    def choose_game(self, index) -> None:
        """A game chosen by hand (ticker, queue, or handed over from Cinema): it is
        featured and held there a while before the automatic choice returns."""
        if index is None:
            return
        spot = self.feed.spotlight
        if spot.pinned is not None and spot.pinned != index:
            spot.pin(None)
        spot.choose_by_hand(int(index))
        self._show_spot()

    def toggle_pin(self) -> None:
        spot = self.feed.spotlight
        spot.pin(None if spot.pinned is not None else spot.current)
        self._show_spot()

    # ---- sound -------------------------------------------------------------------------------
    def _chime(self, statuses: dict[int, str], spoil: bool = False) -> None:
        """A rising chime when a pick goes from losing to winning, a low tone the
        other way. Never on the first look, never when muted or spoiler-free."""
        before, self._statuses = self._statuses, statuses
        if before is None or self.muted() or spoil:
            return
        flips = [(before.get(i), s) for i, s in statuses.items()]
        good = any(b in ("losing", "level") and s in ("winning", "correct") for b, s in flips)
        bad = any(b in ("winning", "level") and s in ("losing", "incorrect") for b, s in flips)
        if good or bad:
            play_tones(good, bad)

    def muted(self) -> bool:
        return pref("mute")

    def toggle_mute(self) -> None:
        set_pref("mute", not self.muted())
        self._show_mute()

    def _show_mute(self) -> None:
        self.mute_btn.setText("♪ OFF" if self.muted() else "♪ ON")
        self.mute_btn.setToolTip("Chimes when one of your picks flips between winning and losing (click to switch)")

    def _size_band(self) -> None:
        """The band takes what a 16:9 picture leaves under it."""
        width = self.width() - SIDE_WIDTH
        room = self.height() - self.ribbon.sizeHint().height()
        self.band.setFixedHeight(max(BAND_MIN, room - round(width * 9 / 16)))

    def _show_moves(self, rows) -> None:
        """▲/▼ places and +points since RedZone mode first showed this week; your row kept in view."""
        week = self.feed.week
        if week != self._start_week or not self._start:
            self._start_week = week
            self._start = {name: (place, points) for name, place, points, _y in rows}
        you_row = None
        for name, place, points, you in rows:
            row = self.board.rows.get(name)
            if row is None:
                continue
            was_place, was_points = self._start.get(name, (place, points))
            moved, gained = was_place - place, points - was_points
            marks = []
            if moved:
                marks.append(f"▲{moved}" if moved > 0 else f"▼{-moved}")
            if gained:
                marks.append(f"{gained:+d}")
            row.name.setText(name + ("  " + " ".join(marks) if marks else ""))
            row.setToolTip("Since RedZone mode opened this week: places moved, points gained" if marks else "")
            if you:
                you_row = row
        if you_row is not None:
            self.board_scroll.ensureWidgetVisible(you_row, 0, 60)

    # ---- the side column -------------------------------------------------------------------------
    def _build_side(self) -> QWidget:
        side = QFrame()
        side.setObjectName("CinemaSide")
        side.setFixedWidth(SIDE_WIDTH)
        side.installEventFilter(self)
        self.side = side
        box = QVBoxLayout(side)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.title = QLabel("ACQL")
        self.title.setObjectName("RedZoneTitle")
        top.addWidget(self.title, 1)
        self.cinema_btn = self._small("CINEMA", "Switch to Cinema mode: the whole slate (F11)", self.to_cinema)
        top.addWidget(self.cinema_btn)
        self.menu_btn = self._small("⚙", "Spotlight, alerts, sound, spoilers, stream", None)
        self.menu_btn.clicked.connect(self._open_menu)
        top.addWidget(self.menu_btn)
        self.mute_btn = self._small("", "", self.toggle_mute)
        top.addWidget(self.mute_btn)
        self.exit_btn = self._small("", "Close RedZone mode (Esc)", self.close)
        top.addWidget(self.exit_btn)
        box.addLayout(top)
        # the stream controls: hidden until the mouse comes over this column
        self.controls = QWidget()
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
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
        controls.addLayout(fit_row)
        self.open_btn = QPushButton("OPEN SPECTRUM")
        self.open_btn.setObjectName("CinemaExit")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setToolTip("Opens Spectrum's live TV in a bare Chrome window and fits it into the gap")
        self.open_btn.clicked.connect(self.open_spectrum)
        controls.addWidget(self.open_btn)
        box.addWidget(self.controls)
        self.data_tag = QLabel("")
        self.data_tag.setObjectName("RedZoneData")
        box.addWidget(self.data_tag)
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
        self.spoiler_note = QLabel("Standings hidden: spoiler-free is on (⚙ to switch it off).")
        self.spoiler_note.setObjectName("CinemaMeta")
        self.spoiler_note.setWordWrap(True)
        self.spoiler_note.hide()
        box.addWidget(self.spoiler_note)
        self.note = QLabel("")
        self.note.setObjectName("CinemaMeta")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        return side

    def _open_menu(self) -> None:
        menu = QMenu(self)

        def check(text: str, on: bool, slot) -> QAction:
            action = QAction(text, menu)
            action.setCheckable(True)
            action.setChecked(on)
            action.triggered.connect(slot)
            menu.addAction(action)
            return action

        check("Spotlight switches games by itself", pref("auto"), lambda on: (set_pref("auto", on), self._show_spot()))
        prio = menu.addMenu("Spotlight priorities")
        weights = priority_weights()
        for reason, words in (("red_zone", "Red zone"), ("scored", "Just scored"), ("turnover", "Turnovers"),
                              ("close_late", "Close late"), ("mine", "My picks")):
            action = QAction(words, prio)
            action.setCheckable(True)
            action.setChecked(reason not in weights)
            action.triggered.connect(lambda on, r=reason: (QSettings().setValue(f"live/prio/{r}", "true" if on else "false"),
                                                          self._show_spot()))
            prio.addAction(action)
        alerts = menu.addMenu("Scoring banners")
        group = QActionGroup(alerts)
        for key, words in (("mine", "My picks' games"), ("all", "Every game"), ("off", "Off")):
            action = QAction(words, alerts)
            action.setCheckable(True)
            action.setChecked(pref("alerts") == key)
            action.triggered.connect(lambda _on, k=key: set_pref("alerts", k))
            group.addAction(action)
            alerts.addAction(action)
        check("Sound", not self.muted(), lambda on: (set_pref("mute", not on), self._show_mute()))
        check("Spoiler-free (no scores, results or standings)", pref("spoilers"),
              lambda on: (set_pref("spoilers", on), self.refresh()))
        menu.addSeparator()
        check("Keep the stream fitted in the gap", pref("keepfit"), lambda on: set_pref("keepfit", on))
        check("Hide controls until the mouse comes", pref("autohide"),
              lambda on: (set_pref("autohide", on), self._show_controls()))
        check("Cover the taskbar too", self.covering(), lambda on: (QSettings().setValue(COVER_KEY, "true" if on else "false"),
                                                                    self._place()))
        menu.addSeparator()
        go = QAction("Cinema mode: the whole slate (F11)", menu)
        go.triggered.connect(self.to_cinema)
        menu.addAction(go)
        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def restyle(self, palette) -> None:
        self.palette_ = palette
        gold = palette.brand or palette.accent
        self.board.gold = gold
        self.field.gold = gold
        self.ribbon.restyle(palette)
        self.setStyleSheet(stylesheet(palette) + f"""
            #RedZoneTitle {{ color: {gold}; font-size: 22px; font-weight: 800; letter-spacing: 4px; }}
            #CinemaSide {{ border-left: {EDGE}px solid {gold}; }}
            #ScoreRibbon {{ border-bottom: {EDGE}px solid {gold}; }}
            #RedZoneBand {{ border-top: {EDGE}px solid {gold}; }}
            #RedZoneRecent {{ font-size: 13px; color: {palette.ink}; }}
            QPushButton#RedZoneBtn {{ background: transparent; color: {palette.ink}; border: 1px solid {palette.ink_muted};
                                      border-radius: 4px; padding: 4px 7px; font-size: 11px; font-weight: 700;
                                      letter-spacing: 1px; }}
            QPushButton#RedZoneBtn:hover {{ border-color: {gold}; color: {gold}; }}
            QPushButton#RedZoneBtn:checked {{ border-color: {gold}; color: {gold}; }}
            #RedZoneSpot {{ border: 1px solid {palette.ink_muted}; border-radius: 6px; }}
            #RedZoneReason {{ color: {gold}; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
            #RedZoneSpotLine {{ font-size: 15px; font-weight: 800; letter-spacing: 1px; }}
            #RedZoneDown {{ color: {palette.ink_secondary}; font-size: 11px; font-weight: 700; }}
            #RedZoneLastPlay {{ color: {palette.ink_muted}; font-size: 11px; }}
            #RedZoneCaption {{ color: {palette.ink_muted}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; }}
            #RedZoneData {{ font-size: 11px; font-weight: 700; letter-spacing: 1px; color: {palette.ink_secondary}; }}
            #RedZoneData[level="LIVE"] {{ color: {GREEN}; }}
            #RedZoneData[level="DELAYED"], #RedZoneData[level="STALE"], #RedZoneData[level="CACHED"] {{ color: {palette.warning}; }}
            #RedZoneData[level="UNAVAILABLE"] {{ color: {palette.critical}; }}
            #RedZonePick {{ border-radius: 6px; border: 1px solid {palette.ink_muted}; }}
            #RedZonePick[status="winning"] {{ border: 2px solid {GREEN}; background: rgba(60,207,122,0.12); }}
            #RedZonePick[status="correct"] {{ border: 2px solid {GREEN}; background: rgba(60,207,122,0.30); }}
            #RedZonePick[status="losing"] {{ border: 2px solid {RED}; background: rgba(229,72,77,0.12); }}
            #RedZonePick[status="incorrect"] {{ border: 2px solid {RED}; background: rgba(229,72,77,0.30); }}
            #RedZonePick[status="level"] {{ border: 2px solid {gold}; }}
            #RedZonePick[status="push"], #RedZonePick[status="postponed"] {{ border: 1px dashed {palette.ink_muted}; }}
            #RedZonePick[status="hidden"] {{ border: 1px solid {palette.ink_secondary}; }}
            #RedZonePick[hot="true"] {{ border: 2px solid {gold}; background: rgba(232,184,78,0.30); }}
            #RedZoneMeter {{ background: rgba(255,255,255,0.10); border: none; border-radius: 2px; }}
            #RedZoneMeter::chunk {{ border-radius: 2px; background: {gold}; }}
            #RedZoneMeter[level="high"]::chunk {{ background: {GREEN}; }}
            #RedZoneMeter[level="low"]::chunk {{ background: {RED}; }}
            #RedZoneYou {{ color: {gold}; font-size: 13px; font-weight: 700; }}
            #RedZoneTakeover {{ background: rgba(8,10,16,0.92); color: {gold}; font-size: 24px; font-weight: 800;
                                letter-spacing: 2px; border-top: 3px solid {gold}; }}
            #RedZonePickWord {{ font-size: 9px; font-weight: 700; color: {palette.ink_muted}; }}""")
        self.exit_btn.setIcon(icons.icon("cross", palette.ink, palette.ink, 14))
        self._show_mute()

    # ---- in and out ------------------------------------------------------------------------------
    def covering(self) -> bool:
        return str(QSettings().value(COVER_KEY, "false")).lower() == "true"

    def _place(self) -> None:
        """The work area, or the whole screen with the taskbar covered too."""
        from . import extras
        screen = extras.cinema_screen(self.window_.screen())
        if screen is not None:
            self.setGeometry(screen.geometry() if self.covering() else screen.availableGeometry())
        if self.isVisible():
            QTimer.singleShot(200, self.fit_stream)

    def enter(self) -> None:
        self._place()
        self.refresh(Changes(self.feed.week))
        self.show()
        self.raise_()
        self.activateWindow()
        self._tick.start()
        self._show_controls()
        QTimer.singleShot(300, self.fit_stream)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key == Qt.Key.Key_F11:
            self.to_cinema()
            return
        if key == Qt.Key.Key_F:
            QSettings().setValue(COVER_KEY, "false" if self.covering() else "true")
            self._place()
            return
        if key == Qt.Key.Key_P:
            self.toggle_pin()
            return
        if key == Qt.Key.Key_N and self._queue:
            self.choose_game(self._queue[0])         # next in the queue
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._tick.stop()
        super().closeEvent(event)
        self.closed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._size_band()
        self._cut_hole()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._cut_hole()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is getattr(self, "side", None):
            if event.type() == QEvent.Type.Enter:
                self._show_controls(hold=True)
            elif event.type() == QEvent.Type.Leave and pref("autohide"):
                self._hide_timer.start(HIDE_AFTER_MS)
        return super().eventFilter(obj, event)

    def _show_controls(self, hold: bool = False) -> None:
        self.controls.show()
        self._hide_timer.stop()
        if pref("autohide") and not hold:
            self._hide_timer.start(HIDE_AFTER_MS * 2)

    def _hide_controls(self) -> None:
        if pref("autohide"):
            self.controls.hide()

    def to_cinema(self) -> None:
        """Over to Cinema mode, the featured game handed across as the chosen card."""
        self.feed.selected = self.feed.spotlight.current
        window = self.window_
        self.close()
        showing = getattr(window, "cinema_showing", None)
        if showing is not None and not showing():
            window.toggle_cinema()
        cinema = getattr(window, "cinema", None)
        if cinema is not None and self.feed.selected is not None:
            cinema.selected = self.feed.selected
            cinema.refresh()

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

    # ---- the stream window ---------------------------------------------------------------------
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

    def _gap(self) -> tuple[int, int, int, int]:
        """The gap in physical pixels: left, top (with the trim tucked above), width, height."""
        screen = self.screen()
        dpr = screen.devicePixelRatio()
        origin = screen.geometry().topLeft()
        corner = self.hole.mapToGlobal(self.hole.rect().topLeft())
        x = origin.x() + round((corner.x() - origin.x()) * dpr)
        y = origin.y() + round((corner.y() - origin.y()) * dpr)
        room = screen.geometry().height() - self.hole.height()     # Windows caps a window at the screen's height
        trim = round(min(self.trim(), max(0, room)) * dpr)
        return x, y - trim, round(self.hole.width() * dpr), round(self.hole.height() * dpr) + trim

    def fit_stream(self, quiet: bool = False) -> None:
        """Size the stream's window to the gap, its title bar under the scores bar."""
        from . import streamfit
        found = streamfit.find_stream()
        if found is None:
            self._stream = None
            if not quiet:
                self.note.setText("No Spectrum / RedZone window found. Open it (not full screen), then press Fit.")
            return
        ok = streamfit.fit(found[0], *self._gap())
        self._stream = found[0] if ok else None
        self._target = streamfit.window_rect(found[0]) if ok else None
        self.raise_()
        if not quiet:
            self.note.setText(f"Fitted: {found[1][:40]}. If the player goes full screen, leave it and press Fit again."
                              if ok else "Windows would not move that window.")

    def _keep_fitted(self) -> None:
        """The stream window moved off the gap (not full screen, not closed): put it back."""
        if not pref("keepfit") or self._stream is None or self._target is None:
            return
        from . import streamfit
        now = streamfit.window_rect(self._stream)
        if now is None:
            self._stream = None
            self.note.setText("The stream window closed. OPEN SPECTRUM or FIT STREAM to bring it back.")
            return
        screen = self.screen()
        dpr = screen.devicePixelRatio()
        full = (now[2] - now[0] >= round(screen.geometry().width() * dpr)
                and now[3] - now[1] >= round(screen.geometry().height() * dpr))
        if full:
            self.note.setText("The player is full screen. Press Esc in the player to bring the frame back.")
            return
        if max(abs(a - b) for a, b in zip(now, self._target)) > DRIFT:
            self.fit_stream(quiet=True)

    def _on_tick(self) -> None:
        self._show_spot()
        self._keep_fitted()
        self._show_data()

    # ---- what it shows ------------------------------------------------------------
    def _show_data(self) -> None:
        label, words = LP.data_label(self.feed.fresh) if self.feed.week else ("", "")
        self.data_tag.setText(f"● {label} · {words}" if label else "")
        set_prop(self.data_tag, "level", label)
        self.data_tag.setToolTip("Scores are polled from ESPN's scoreboard (every 30 s with a game on), not streamed."
                                 + (f"\n{self.feed.fresh.detail()}" if self.feed.fresh is not None else ""))

    def _spoil_ribbon(self, spoil: bool) -> None:
        """Spoiler-free: the ticker keeps its games and states but loses its scores
        and its winner's bold."""
        for label in self.ribbon.findChildren(QLabel, "ChipScore"):
            label.setVisible(not spoil)
        if spoil:
            for label in self.ribbon.findChildren(QWidget, "ChipTeam"):
                set_prop(label, "faded", "")

    def refresh(self, changes: Changes | None = None) -> None:
        feed = self.feed
        season = self.window_.season
        spoil = pref("spoilers")
        self.ribbon.set_feed(feed, season, None if spoil else changes)
        self._spoil_ribbon(spoil)
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
        self._bd = bd
        self._you = bd.you.card if bd is not None and bd.you is not None else None
        if bd is not None and bd.standings:
            feed.note_pool([(s.card.key, s.card.name, s.place, s.total_now) for s in bd.standings
                            if s.place is not None], bd.you.card.key if bd.you is not None else "")
        try:
            self._show_band(self._you, changes)
        except Exception:  # noqa: BLE001 - the band is extra; the frame still shows
            pass
        self._show_spot()
        self._show_data()
        self.board_scroll.setVisible(not spoil)
        self.you_line.setVisible(not spoil)
        self.spoiler_note.setVisible(spoil)
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
            if me.worst is not None and me.worst != me.place:
                words.append(f"WORST {ordinal(me.worst)}")
            if me.chance is not None and me.chance >= 0.005:
                words.append(f"{me.chance:.0%} TO WIN THE WEEK")
            self.you_line.setText(" · ".join(words))
        else:
            self.you_line.setText("")
        self._maybe_takeover(bd, changes, spoil)

    def _maybe_takeover(self, bd, changes: Changes | None, spoil: bool = False) -> None:
        """A score in a game you picked (or any game, by the alerts setting): a
        banner over the bottom of the stream for a few seconds, saying what it
        was and what it did to your place."""
        me = bd.you
        place_before, self._you_place = self._you_place, me.place if me is not None else None
        before_scores = self._scores
        self._scores = {st.index: (st.away_points or 0, st.home_points or 0) for st in self.feed.states}
        which = pref("alerts")
        if not changes or me is None or not before_scores or spoil or which == "off":
            return
        mine = me.card.picks
        scored = [st for st in self.feed.states if st.index in changes.scores]
        hits = [st for st in scored if mine.get(st.index, GD.NOBODY) != GD.NOBODY]
        if not hits and which == "all":
            hits = scored
        if not hits:
            return
        st = hits[0]
        old = before_scores.get(st.index, (0, 0))
        new = self._scores[st.index]
        gain = max(new[0] - old[0], new[1] - old[1])
        if gain <= 0:
            return                               # a correction down is not a score
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
    return LP.GD_ordinal(n).upper()


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
