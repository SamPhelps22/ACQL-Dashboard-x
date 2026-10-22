"""The scouting report for one game, as a window (scouting.py gathers it)."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..model import evidence, radar, scouting
from ..version import MODEL_NAME
from .theme import Palette
from .widgets import Card, StatTile, section, tile_grid

MOST_HURT = 7       # injuries listed for a team before "and N more"


def _text(words: str, muted: bool = False) -> QLabel:
    label = QLabel(words)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if muted:
        label.setObjectName("Muted")
    return label


def _ordinal(n: int) -> str:
    return scouting._ordinal(n)


class ScoutingDialog(QDialog):
    """Everything known about one game: the plan, both teams, the factors, the risks."""

    def __init__(self, report: scouting.Report, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Scouting report – {report.matchup}")
        self.resize(1040, 780)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(16)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        r, p = report, palette
        about = " · ".join(filter(None, [f"Week {r.week}", r.kickoff, r.weather]))
        layout.addWidget(section(r.matchup, about))

        take = StatTile("Card Takes")
        take.update_values(r.pick, f"{r.chance:.0%} to be credited · {r.tier}"
                           + (f"\npool line: {r.pool_line}" if r.pool_line else "\nstraight up"),
                           "good" if r.chance >= 0.65 else "warning" if r.chance < 0.55 else "")
        score = StatTile("Projected")
        if r.score is not None:
            score.update_values(f"{r.score[1]}–{r.score[0]}",
                                f"{r.away.team} {r.score[1]}, {r.home.team} {r.score[0]}\n"
                                f"{MODEL_NAME}: {r.favourite} by {r.margin:.1f} · over/under {r.total:g}")
        else:
            score.update_values(f"by {r.margin:.1f}", f"{MODEL_NAME} has {r.favourite} ahead\nno over/under kept, so no score")
        line = StatTile("Betting Line")
        line.update_values(r.line or "—", f"upset {r.upset:.0%} · within 3 {r.close:.0%}\n"
                                               f"by {radar.ROUT} or more {r.rout:.0%}")
        hard = StatTile("Hard To Call")
        hard.update_values(f"{r.hard:.0f}", "of 100 - where to trust the pick least\n"
                           + ("one of the week's hardest" if r.hard >= 55 else "about ordinary" if r.hard >= 35 else "one of the clearer ones"),
                           "warning" if r.hard >= 55 else "")
        layout.addLayout(tile_grid([take, score, line, hard], per_row=4))

        plan = Card("The game plan")
        plan.add(_text(escape(r.plan)))
        if r.made:
            plan.add(_text("How the number was made: " + escape(r.made), muted=True))
        layout.addWidget(plan)
        if r.steps:
            layout.addWidget(self._waterfall(r, p))

        teams = QHBoxLayout()
        teams.setSpacing(16)
        for side in (r.away, r.home):
            teams.addWidget(self._team(side, p), 1)
        layout.addLayout(teams)

        factors = Card("The three biggest factors")
        if r.factors:
            for signal in r.factors:
                factors.add(_text(self._signal(signal, p)))
            if r.also:
                factors.add(_text("Also on file: " + escape("; ".join(f"{s.name.lower()} - {s.headline}" for s in r.also)), muted=True))
        else:
            factors.add(_text("Nothing on file beyond the numbers above.", muted=True))
        layout.addWidget(factors)

        risks = Card("What would make it wrong")
        if r.risks:
            risks.add(_text("<br>".join(f"•&nbsp; {escape(line[0].upper() + line[1:])}" for line in r.risks)))
        else:
            risks.add(_text("Nothing in particular - the ordinary run of the game.", muted=True))
        risks.add(_text("These are the ways a pick like this usually loses, likeliest first - not a forecast that it will.", muted=True))
        layout.addWidget(risks)
        layout.addStretch(1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.setContentsMargins(24, 0, 24, 0)
        row.addStretch(1)
        row.addWidget(close)
        outer.addLayout(row)

    @staticmethod
    def _waterfall(r: scouting.Report, p: Palette) -> Card:
        """The margin's arithmetic, one line a step, home side (#23)."""
        card = Card(f"How {MODEL_NAME} got its number · {r.home.team} margin")
        rows = []
        for s in r.steps:
            if s.kind == "move":
                colour = p.good if s.points > 0 else p.critical if s.points < 0 else p.ink_muted
                value = f"<span style='color:{colour}'>{s.points:+.1f}</span>"
            else:
                value = f"<b>{s.points:+.1f}</b>"
            rows.append(f"<tr><td style='padding:3px 14px 3px 0'>{'<b>' if s.kind != 'move' else ''}"
                        f"{escape(s.label)}{'</b>' if s.kind != 'move' else ''}</td>"
                        f"<td align='right' style='padding:3px 14px 3px 0'>{value}</td>"
                        f"<td style='color:{p.ink_muted}'>{escape(s.note)}</td></tr>")
        card.add(_text("<table>" + "".join(rows) + "</table>"))
        card.add(_text(f"Positive favours {escape(r.home.team)}. The last line is the margin the card's "
                       f"chance of {r.chance:.0%} is worked out from.", muted=True))
        return card

    @staticmethod
    def _signal(signal: evidence.Signal, p: Palette) -> str:
        tag, colour = {evidence.FOR: ("FOR", p.good), evidence.AGAINST: ("AGAINST", p.critical)}.get(
            signal.verdict, ("NOTE", p.ink_muted))
        detail = f"<br><span style='color:{p.ink_muted}'>{escape(signal.detail)}</span>" if signal.detail else ""
        return (f"<span style='color:{colour};font-weight:700'>{tag}</span> &nbsp;<b>{escape(signal.name)}</b> "
                f"&nbsp;{escape(signal.headline)}{detail}")

    @staticmethod
    def _team(side: scouting.Side, p: Palette) -> Card:
        card = Card(f"{side.team} · {'home' if side.home else 'road'} · {side.record}")
        lines = []
        if side.games:
            lines.append(f"Scores <b>{side.scored:.1f}</b> a game ({_ordinal(side.scored_rank)}) · "
                         f"allows <b>{side.allowed:.1f}</b> ({_ordinal(side.allowed_rank)} fewest) · "
                         f"over {side.games} game{'' if side.games == 1 else 's'}")
        ratings = []
        if side.market is not None:
            ratings.append(f"market rating <b>{side.market:+.1f}</b> ({_ordinal(side.market_rank)})")
        if side.own is not None:
            ratings.append(f"own rating <b>{side.own:+.1f}</b>")
        if ratings:
            lines.append((" · ".join(ratings)).capitalize() if not ratings[0].startswith("market") else
                         "Market rating" + " · ".join(ratings)[len("market rating"):])
        if side.last:
            lines.append(f"Last time out: {escape(side.last)}")
        card.add(_text("<br>".join(lines) if lines else "No games played yet."))
        for title, items, colour in (("Strengths", side.strengths, p.good), ("Weaknesses", side.weaknesses, p.critical)):
            if items:
                card.add(_text(f"<span style='color:{colour};font-weight:700'>{title}</span><br>"
                               + "<br>".join(f"•&nbsp; {escape(i[0].upper() + i[1:])}" for i in items)))
        if side.hurt:
            shown = list(side.hurt[:MOST_HURT])
            more = len(side.hurt) - len(shown)
            card.add(_text(
                f"<b>Injuries</b> · {len(side.hurt)} listed, {side.missing} not expected to play<br>"
                + "<br>".join(escape(h) for h in shown) + (f"<br>and {more} more" if more > 0 else ""), muted=True))
        else:
            card.add(_text("Nobody on the injury report (or it hasn't been read yet).", muted=True))
        return card
