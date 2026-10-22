"""System readiness: every input the dashboard runs on, as a checklist (readiness.py does the checking)."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton

from ... import readiness
from ...places import READINESS as title_
from ...version import MODEL_NAME
from ..widgets import Card, IconButton, StatTile, section, tile_grid
from .base import Page

#: The mark beside each line, by its state: a tick, a dot, a warning sign, a cross.
MARKS = {readiness.OK: "✓", readiness.NOTE: "·", readiness.WARN: "⚠", readiness.BAD: "✕"}
WORDS = {readiness.OK: "fine", readiness.NOTE: "note", readiness.WARN: "look at this", readiness.BAD: "broken"}


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class ReadinessPage(Page):
    title = title_
    subtitle = "Whether everything the picks are made from is up to date - and what to look at if it isn't"
    icon = "\N{WHITE HEAVY CHECK MARK}"

    def build(self) -> None:
        head = QHBoxLayout()
        head.addWidget(section(self.title, self.subtitle), 1)
        self.again = IconButton("Check again", "refresh")
        self.again.setToolTip("Look at everything again now. Nothing is fetched: this only reads what is kept.")
        self.again.clicked.connect(self.refresh_now)
        head.addWidget(self.again, 0, Qt.AlignmentFlag.AlignTop)
        self.layout_.addLayout(head)

        self.tile_state = StatTile("System")
        self.tile_due = StatTile("Cards Due")
        self.tile_lines = StatTile("Betting Lines")
        self.tile_run = StatTile("Last Automatic Run")
        self._tiles = (self.tile_state, self.tile_due, self.tile_lines, self.tile_run)
        self.layout_.addLayout(tile_grid(list(self._tiles), per_row=4))

        self.groups: dict[str, tuple[Card, QGridLayout]] = {}
        for name in (readiness.SOURCES, readiness.CARD, readiness.AUTOMATION):
            card = Card(name)
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(8)
            grid.setColumnMinimumWidth(1, 190)
            grid.setColumnStretch(2, 1)
            card.body().addLayout(grid)
            self.layout_.addWidget(card)
            self.groups[name] = (card, grid)
        self.note = QLabel(
            "Each line is judged against the clock: a betting line twelve hours old is fine on a Monday and stale "
            "two hours before the cards are due. ✓ is fine, ⚠ wants a look, ✕ is broken, and a dot "
            "is only worth knowing. Nothing on this page fetches or changes anything."
        )
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        self.layout_.addWidget(self.note)

    def restyle(self) -> None:
        self.refresh_now()

    def refresh(self) -> None:
        season = self.season
        assert season is not None  # guaranteed by Page.refresh_now()
        found = readiness.build(season)
        self._update_tiles(found)
        p = self.palette
        colours = {readiness.OK: p.good, readiness.NOTE: p.ink_muted, readiness.WARN: p.warning,
                   readiness.BAD: p.critical}
        grouped = dict(found.grouped())
        for name, (card, grid) in self.groups.items():
            self.clear_layout(grid)
            rows = grouped.get(name, [])
            card.setVisible(bool(rows))
            wrong = sum(1 for c in rows if c.state in (readiness.WARN, readiness.BAD))
            card.set_title(f"{name} - " + (f"{_plural(wrong, 'thing')} to look at" if wrong else "all fine"))
            for r, check in enumerate(rows):
                colour = colours[check.state]
                mark = QLabel(f"<span style='font-size:17px; font-weight:800; color:{colour}'>{MARKS[check.state]}</span>")
                mark.setToolTip(WORDS[check.state])
                mark.setFixedWidth(22)
                name_label = QLabel(f"<b>{check.name}</b>")
                strong = check.state in (readiness.WARN, readiness.BAD)
                words = QLabel(
                    f"<span style='color:{colour if strong else p.ink}; font-weight:{600 if strong else 400}'>"
                    f"{check.headline}</span>"
                    + (f"<br><span style='color:{p.ink_muted}'>{check.detail}</span>" if check.detail else ""))
                words.setWordWrap(True)
                for column, label in enumerate((mark, name_label, words)):
                    label.setTextFormat(Qt.TextFormat.RichText)
                    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                    grid.addWidget(label, 2 * r, column)
                if check.fix in readiness.FIXES:
                    button = QPushButton(readiness.FIXES[check.fix])
                    button.clicked.connect(lambda _=False, key=check.fix: self._fix(key))
                    grid.addWidget(button, 2 * r, 3, Qt.AlignmentFlag.AlignTop)
                if r < len(rows) - 1:
                    rule = QFrame()
                    rule.setFixedHeight(1)
                    rule.setStyleSheet(f"background: {p.grid}; border: none;")
                    grid.addWidget(rule, 2 * r + 1, 0, 1, 4)

    def _fix(self, key: str) -> None:
        """Run one of the fixes a check offers, then look again."""
        if key == "old_sheets":
            from ...pool import picks
            picks.forget_weeks(picks.other_season_weeks())
            readiness.forget_standing(readiness.OLD_SHEETS)
        self.refresh_now()

    def _update_tiles(self, found: readiness.Readiness) -> None:
        bad, warn = found.of(readiness.BAD), found.of(readiness.WARN)
        fine = len(found.of(readiness.OK))
        self.tile_state.update_values(
            "Ready" if found.ready else found.verdict.split(",")[0],
            f"{fine} of {len(found.checks)} checks fine\n"
            + (", ".join(c.name for c in (bad + warn)[:3]) + ("…" if len(bad + warn) > 3 else "")
               if bad or warn else f"everything {MODEL_NAME} runs on is up to date"),
            "bad" if bad else "warning" if warn else "good",
        )
        if found.lock is not None:
            left = found.lock - found.now
            when = time.strftime("%a %b %d, %I:%M %p", time.localtime(found.lock)).replace(" 0", " ")
            self.tile_due.update_values(
                readiness.until(left).replace("in ", "") if left > 0 else "Locked",
                f"week {found.week} - {when}\n" + ("the odds lock then" if left > 0 else "the week is under way"),
                "warning" if 0 < left < readiness.DAY else "",
            )
        else:
            self.tile_due.update_values(self.NO_VALUE, "no week open")
        lines = next((c for c in found.checks if c.name == "Betting lines"), None)
        if lines is not None:
            age = readiness.ago(found.now - lines.at).replace(" ago", "") if lines.at else "none"
            self.tile_lines.update_values(
                age, lines.headline + ("\nold for this close to the deadline" if lines.state == readiness.WARN else ""),
                {readiness.OK: "good", readiness.WARN: "warning", readiness.BAD: "bad"}.get(lines.state, ""))
        else:
            self.tile_lines.update_values(self.NO_VALUE, "couldn't be checked")
        runs = [c for c in found.checks if c.group == readiness.AUTOMATION and c.at
                and c.name in ("The nightly run", "The game-day check", "Last automatic run")]
        latest = max(runs, key=lambda c: c.at, default=None)
        if latest is not None:
            self.tile_run.update_values(
                readiness.ago(found.now - latest.at).replace(" ago", ""),
                f"{latest.name[0].lower() + latest.name[1:]}\n{latest.headline}",
                "warning" if any(c.state in (readiness.WARN, readiness.BAD) for c in found.checks
                                 if c.group == readiness.AUTOMATION) else "good")
        else:
            self.tile_run.update_values(self.NO_VALUE, "no scheduled run on record")
