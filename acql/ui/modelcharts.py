"""The model's own charts (showcase.py has the numbers; charts.py the house rules).

Five forms the general charts don't cover. Colour is given by the job it
does: Deadeye, the betting line and the baseline wear the three series
colours chosen for these charts (theme.model_series - every pair checked to
stay apart for colour-blind readers); a pick that came in or missed wears the
status colours and a different mark; the matrix runs from red through a
neutral grey to blue around a coin flip. Text is always in the ink colours.
"""

from __future__ import annotations

import matplotlib.patches as mpatches
from matplotlib.ticker import PercentFormatter

from .. import showcase
from .charts import LABEL_SIZE, LINE_WIDTH, Chart, _diverging_color, _ink_on
from .theme import mix, model_series

MARK = 60           # scatter marks: a little over 8px across
RING = 1.6          # the surface ring that keeps overlapping marks apart


class TrajectoryChart(Chart):
    """Who is ahead, pick by pick: games above a coin flip."""

    def _draw(self, found: showcase.Trajectory) -> None:
        if not found.picks or not found.lines:
            self.empty("Appears once a week with betting lines has been graded")
            return
        p = self.palette
        ax = self.new_axes()
        n = found.picks
        x = list(range(1, n + 1))
        colours = model_series(p)
        ends = []
        for line, colour in zip(found.lines, colours):
            (drawn,) = ax.plot(x, line.above, color=colour, linewidth=LINE_WIDTH, label=line.name, zorder=3,
                               solid_capstyle="round")
            ax.plot([n], [line.above[-1]], marker="o", markersize=7, color=colour,
                    markeredgecolor=p.surface, markeredgewidth=RING, zorder=4)
            so_far, tips = 0, []
            for i, value in enumerate(line.above, 1):
                so_far = round(value + i / 2)
                tips.append(f"{found.labels[i - 1]}\n{line.name}: {so_far} of {i} right")
            self.register_hover(drawn, tips)
            ends.append([line.above[-1], f"{line.name}  {line.right} of {line.picks} ({line.rate:.0%})"])
        # the coin flip everything is measured from
        ax.axhline(0, color=p.baseline, linewidth=0.9, zorder=1)
        low = min(min(line.above) for line in found.lines)
        high = max(max(line.above) for line in found.lines)
        span = max(high - min(low, 0.0), 2.0)
        ax.text(1, -span * 0.03, "a coin flip", color=p.ink_muted, fontsize=LABEL_SIZE, va="top")
        # the end of each line says whose it is and where it stands; nudged apart where they crowd
        ends.sort(key=lambda item: item[0])
        gap = span * 0.085
        placed = []
        for value, words in ends:
            y = value if not placed else max(value, placed[-1][0] + gap)
            placed.append((y, words))
        for y, words in placed:
            ax.text(n + n * 0.02, y, words, color=p.ink_secondary, fontsize=LABEL_SIZE, va="center")
        ax.set_xlim(0.5, n * 1.42)
        ax.set_ylim(min(low, 0.0) - span * 0.12, max(high, placed[-1][0]) + span * 0.12)
        ax.set_xticks([start for start, _week in found.weeks])
        ax.set_xticklabels([f"Wk {week}" for _start, week in found.weeks])
        ax.set_ylabel("Games above a coin flip", fontsize=LABEL_SIZE)
        self.grid(ax, "both")
        self.legend(ax)
        self.draw_idle()


class CalibrationChart(Chart):
    """What it said against what happened, band by band."""

    def _draw(self, bands: list[showcase.Band]) -> None:
        bands = [b for b in bands if b.picks]
        if not bands:
            self.empty("Appears once a week with betting lines has been graded")
            return
        p = self.palette
        ax = self.new_axes()
        colour = model_series(p)[0]
        said = [b.said * 100 for b in bands]
        rate = [b.rate * 100 for b in bands]
        low = min(45.0, min(said) - 5, min(rate) - 8)
        high = max(92.0, max(said) + 5, max(rate) + 8)
        ax.plot([low, high], [low, high], color=p.baseline, linewidth=1.0, label="Exactly as it said", zorder=1)
        # how far luck alone moves each band
        ax.errorbar(said, rate, yerr=[b.luck * 100 for b in bands], fmt="none", ecolor=p.ink_muted,
                    elinewidth=1.0, capsize=3, zorder=2)
        marks = ax.scatter(said, rate, s=MARK + 20, color=colour, edgecolors=p.surface, linewidths=RING,
                           zorder=4, label="Its picks, in bands")
        self.register_hover(marks, [
            f"Picks it called {b.label}: {b.picks}\nsaid {b.said:.0%} on average, {b.rate:.0%} came in "
            f"({b.right} of {b.picks})\nluck alone moves that about {b.luck:.0%} either way" for b in bands])
        ax.set_xlim(low, high)
        ax.set_ylim(low, high)
        ax.xaxis.set_major_formatter(PercentFormatter(100, decimals=0))
        ax.yaxis.set_major_formatter(PercentFormatter(100, decimals=0))
        ax.set_xlabel("What it said", fontsize=LABEL_SIZE)
        ax.set_ylabel("What happened", fontsize=LABEL_SIZE)
        ax.text(0.97, 0.05, "below the line: came in less often than it said", transform=ax.transAxes,
                color=p.ink_muted, fontsize=LABEL_SIZE, ha="right")
        self.grid(ax, "both")
        self.legend(ax)
        self.draw_idle()


class ScopeChart(Chart):
    """The margin it expected against the margin that happened."""

    def _draw(self, points: list[showcase.Point], label_count: int = 2) -> None:
        if not points:
            self.empty("Appears once final scores are in for a week with betting lines")
            return
        p = self.palette
        ax = self.new_axes()
        hits = [q for q in points if q.right]
        misses = [q for q in points if not q.right]
        values = [q.expected for q in points] + [q.actual for q in points]
        low, high = min(values) - 3, max(values) + 3
        ax.plot([low, high], [low, high], color=p.baseline, linewidth=1.0, label="Exactly as expected", zorder=1)
        ax.axhline(0, color=p.grid, linewidth=0.9, zorder=1)
        for group, colour, mark, name in ((hits, p.good, "o", "Pick came in"), (misses, p.critical, "X", "Pick missed")):
            if not group:
                continue
            drawn = ax.scatter([q.expected for q in group], [q.actual for q in group], s=MARK, marker=mark,
                               color=colour, edgecolors=p.surface, linewidths=RING, zorder=3, label=name)
            self.register_hover(drawn, [
                f"{q.label}\nexpected by {q.expected:+.1f}, finished {q.actual:+g} - {q.error:.1f} points off"
                for q in group])
        # only the furthest off are named; the rest are a hover away
        for n, q in enumerate(sorted(points, key=lambda q: -q.error)[:label_count]):
            ax.annotate(q.short, (q.expected, q.actual), xytext=(9, 7 if n % 2 == 0 else -13),
                        textcoords="offset points", fontsize=LABEL_SIZE, color=p.ink_secondary)
        ax.set_xlim(min(q.expected for q in points) - 2, max(q.expected for q in points) + 4)
        ax.set_ylim(low, high)
        ax.set_xlabel("Margin it expected for its pick (points)", fontsize=LABEL_SIZE)
        ax.set_ylabel("Margin that happened", fontsize=LABEL_SIZE)
        self.grid(ax, "both")
        self.legend(ax)
        self.draw_idle()


class RollingChart(Chart):
    """Its last few picks, against what its chances said and what luck alone covers."""

    def _draw(self, found: showcase.Rolling) -> None:
        if not found.picks:
            self.empty(f"Appears after {found.window} graded picks")
            return
        p = self.palette
        ax = self.new_axes()
        colour = model_series(p)[0]
        x = found.picks
        said = [v * 100 for v in found.said]
        rate = [v * 100 for v in found.rate]
        reach = [v * 100 for v in found.reach]
        ax.fill_between(x, [s - r for s, r in zip(said, reach)], [s + r for s, r in zip(said, reach)],
                        color=mix(p.ink_muted, p.surface, 0.30), linewidth=0, zorder=1,
                        label="What luck alone covers")
        ax.plot(x, said, color=p.ink_muted, linewidth=1.2, zorder=2, label="What its chances said")
        (drawn,) = ax.plot(x, rate, color=colour, linewidth=LINE_WIDTH, zorder=3,
                           label=f"Its last {found.window} picks", solid_capstyle="round")
        ax.plot([x[-1]], [rate[-1]], marker="o", markersize=7, color=colour, markeredgecolor=p.surface,
                markeredgewidth=RING, zorder=4)
        ax.annotate(f"{found.rate[-1]:.0%}", (x[-1], rate[-1]), xytext=(8, 0), textcoords="offset points",
                    fontsize=LABEL_SIZE, color=p.ink_secondary, va="center")
        self.register_hover(drawn, [
            f"Picks {end - found.window + 1}-{end}: {r:.0%} right\nits chances said {s:.0%}, "
            f"give or take {w:.0%}" for end, r, s, w in zip(x, found.rate, found.said, found.reach)])
        ax.set_xlim(x[0] - 0.5, x[-1] + max(3.0, (x[-1] - x[0]) * 0.09))
        ax.set_ylim(min(30.0, min(rate) - 6), max(90.0, max(rate) + 6))
        ax.yaxis.set_major_formatter(PercentFormatter(100, decimals=0))
        ax.set_xlabel("After this many picks", fontsize=LABEL_SIZE)
        ax.set_ylabel(f"Right, of the last {found.window}", fontsize=LABEL_SIZE)
        self.grid(ax, "y")
        self.legend(ax)
        self.draw_idle()


class ThinBars(Chart):
    """A handful of bars, thin, each with a tick for what it is measured against."""

    HEIGHT = 0.42

    def _draw(self, labels: list[str], values: list[float], *, value_format: str = "{:.0f}",
              markers: list[float | None] | None = None, marker_label: str = "",
              tooltips: list[str] | None = None, xlabel: str = "") -> None:
        if not labels:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        rows = list(range(len(labels)))
        bars = ax.barh(rows, values, color=model_series(p)[0], height=self.HEIGHT, zorder=2,
                       linewidth=1.0, edgecolor=p.surface)
        if markers:
            reach, drawn = self.HEIGHT / 2 + 0.13, False
            for row, mark in zip(rows, markers):
                if mark is None:
                    continue
                ax.plot([mark, mark], [row - reach, row + reach], color=p.ink, linewidth=2.0,
                        solid_capstyle="butt", zorder=4, label=marker_label if (marker_label and not drawn) else None)
                drawn = True
        top = max(list(values) + [m for m in (markers or []) if m is not None] + [0.0]) or 1.0
        for bar, value in zip(bars, values):
            ax.text(bar.get_width() + top * 0.02, bar.get_y() + bar.get_height() / 2, value_format.format(value),
                    va="center", ha="left", fontsize=LABEL_SIZE, color=p.ink_secondary)
        ax.set_yticks(rows)
        ax.set_yticklabels(labels, fontsize=LABEL_SIZE)
        ax.set_ylim(len(labels) - 0.4, -0.6)                # the first bar on top, with air above and below
        ax.set_xlim(0, top * 1.16)
        if "%" in value_format:
            ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=LABEL_SIZE)
        self.grid(ax, "x")
        if markers and marker_label:
            handles, names = ax.get_legend_handles_labels()
            ax.legend(handles, names, loc="lower left", bbox_to_anchor=(0, 1.01), frameon=False,
                      fontsize=LABEL_SIZE, labelcolor=p.ink_secondary, handlelength=1.2)
        self.register_hover(bars, tooltips or [f"{label}: {value_format.format(v)}" for label, v in zip(labels, values)])
        self.draw_idle()


class MatrixChart(Chart):
    """Where it does well and badly: each kind of game, as a row of shaded rates."""

    COLUMNS = ("Deadeye", "The line", "It said")
    LOW, CENTRE, HIGH = 25.0, 50.0, 80.0

    def _draw(self, kinds: list[showcase.Kind], model: str = "Deadeye") -> None:
        if not kinds:
            self.empty("Appears once a week with betting lines has been graded")
            return
        p = self.palette
        ax = self.new_axes()
        columns = (model,) + self.COLUMNS[1:]
        cells, tips = [], []
        for r, kind in enumerate(kinds):
            for c, value in enumerate((kind.rate, kind.line, kind.said)):
                if value is None:
                    colour, words = p.raised, "–"
                else:
                    colour = _diverging_color(p, value * 100, self.LOW, self.CENTRE, self.HIGH)
                    words = f"{value:.0%}"
                patch = mpatches.Rectangle((c + 0.03, r + 0.06), 0.94, 0.88, facecolor=colour,
                                           edgecolor=p.surface, linewidth=1.2)
                ax.add_patch(patch)
                ax.text(c + 0.5, r + 0.5, words, ha="center", va="center", fontsize=LABEL_SIZE,
                        color=_ink_on(colour) if value is not None else p.ink_muted)
                cells.append(patch)
                tips.append(
                    f"{kind.name}: too few picks to shade ({kind.picks})" if value is None else
                    f"{kind.name} - {columns[c]}: {value:.0%}\n{kind.right} of {kind.picks} picks came in")
            ax.text(len(columns) + 0.5, r + 0.5, f"{kind.right} of {kind.picks}", va="center", ha="center",
                    fontsize=LABEL_SIZE, color=p.ink_secondary)
        self.register_hover(cells, tips)
        ax.set_xlim(0, len(columns) + 1.0)
        ax.set_ylim(0, len(kinds) + 1.0)
        ax.invert_yaxis()
        ax.set_xticks([i + 0.5 for i in range(len(columns))] + [len(columns) + 0.5])
        ax.set_xticklabels(list(columns) + ["Record"], fontsize=LABEL_SIZE)
        ax.xaxis.set_ticks_position("top")
        ax.set_yticks([i + 0.5 for i in range(len(kinds))])
        ax.set_yticklabels([k.name for k in kinds], fontsize=LABEL_SIZE)
        for side in ("left", "bottom"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=p.ink_muted, labelsize=LABEL_SIZE, length=0)
        # the key: a coin flip in the middle, worse to the left, better to the right
        y = len(kinds) + 0.55
        steps = ((30, "30%"), (40, ""), (50, "50%"), (62, ""), (75, "75%"))
        wide = 3.0 / len(steps)
        for i, (value, words) in enumerate(steps):
            colour = _diverging_color(p, value, self.LOW, self.CENTRE, self.HIGH)
            ax.add_patch(mpatches.Rectangle((0.03 + i * wide, y - 0.2), wide - 0.04, 0.4, facecolor=colour,
                                            edgecolor=p.surface, linewidth=1.0))
            if words:
                ax.text(0.03 + i * wide + (wide - 0.04) / 2, y, words, ha="center", va="center",
                        fontsize=LABEL_SIZE - 1, color=_ink_on(colour))
        ax.text(len(columns) + 0.5, y, "right", ha="center", va="center", fontsize=LABEL_SIZE, color=p.ink_muted)
        self.draw_idle()
