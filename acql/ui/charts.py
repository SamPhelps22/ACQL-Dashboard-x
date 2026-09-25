"""Matplotlib charts embedded in Qt.

House rules applied throughout:
  * one y-axis, never two;
  * categorical colour assigned by fixed slot, following the entity not its rank;
  * thin marks, recessive grid, no number printed on every point;
  * a legend whenever two or more series share an axes, with direct labels on
    small series counts so identity never rests on colour alone;
  * a hover tooltip on every plotted form, and a crosshair on the time series.

Two structural rules make the rest of the file work:

`plot()` and `empty()` record the call, so `set_palette()` can redraw the same
chart in the other theme without the page being rebuilt around it. Subclasses
therefore implement `_draw()`, not `plot()`.

Hover is resolved through `_hover_at()` rather than one handler per chart.
Every canvas connects exactly one motion handler, in `Chart.__init__`; a
subclass that needs different hit-testing overrides `_hover_at`. Connecting a
second handler inside `plot()` would add another on every redraw, and the two
would then fight over the same annotation.
"""

from __future__ import annotations

import statistics

import matplotlib

matplotlib.use("QtAgg")

import matplotlib.patches as mpatches
import matplotlib.transforms as mtransforms
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.cm import ScalarMappable
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, PercentFormatter
from PySide6.QtWidgets import QSizePolicy

from .theme import Palette, mix, ramp_color, ramp_direction

GRID_KW = dict(linewidth=0.7, alpha=0.9, zorder=0)
LINE_WIDTH = 2.0
MARKER_SIZE = 6.0        # ~8px at 100 dpi, the floor for a hit target
BAR_HEIGHT = 0.68
LABEL_SIZE = 9
TICK_SIZE = 9
MAX_X_TICKS = 14         # past this, thin the ticks rather than overprint them
# What a chart shrinks to when it has nothing to draw: enough for the line
# that says why, and no more.
#: A chart may grow to this multiple of its designed height, and no further.
CHART_GROWTH = 1.5
EMPTY_HEIGHT = 96
# Fewest columns a heatmap reserves room for, however few it has to show.
MIN_GRID_COLUMNS = 8
# Past this many columns, label every second one instead.
MAX_GRID_LABELS = 12
# Qt's own "no maximum". Spelled out rather than imported, because which
# module exports QWIDGETSIZE_MAX has moved between Qt bindings and a wrong
# guess is an ImportError at startup rather than a chart that looks odd.
NO_MAX_HEIGHT = 16_777_215


def money(value: float) -> str:
    """Currency with the sign ahead of the symbol: -$40, not $-40."""
    return f"{'-' if value < 0 else ''}${abs(value):,.0f}"


def _ink_on(fill: str) -> str:
    """Black or white, whichever the given fill can actually carry.

    Text inside a heatmap cell sits on a ramp step, not on the page, so the
    theme cannot decide its colour: on either surface the ramp runs from very
    pale to very dark, and the right answer flips partway along it. This
    measures the step itself (WCAG relative luminance) and picks the side with
    more contrast.
    """
    hexed = fill.lstrip("#")
    channels = [int(hexed[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#111111" if luminance > 0.36 else "#ffffff"


class Chart(FigureCanvasQTAgg):
    """Base canvas: themed surface, tight layout, and a shared hover tooltip."""

    def __init__(self, palette: Palette, height: float = 2.8, parent=None) -> None:
        self.palette = palette
        self.figure = Figure(figsize=(6, height), dpi=100, layout="constrained")
        super().__init__(self.figure)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._full_height = int(height * 100)
        self.setMinimumHeight(self._full_height)
        self.setMaximumHeight(int(self._full_height * CHART_GROWTH))
        self.figure.patch.set_facecolor(palette.surface)
        self._annotation = None
        self._hover_targets: list[tuple] = []
        self._replay: tuple[str, tuple, dict] | None = None
        # What the tooltip is currently saying, and where. Moving a mouse
        # across a chart fires a motion event every few pixels, and redrawing
        # the figure for each one - a heatmap is several hundred patches -
        # made the whole window feel heavy whenever the pointer crossed a
        # chart. A redraw now happens when the tooltip actually changes.
        self._shown: tuple | None = None
        self.mpl_connect("motion_notify_event", self._on_hover)
        self.mpl_connect("figure_leave_event", lambda _event: self._hide_hover())

    # ---- public surface --------------------------------------------------
    def plot(self, *args, **kwargs) -> None:
        """Draw, remembering the call so the chart can be re-themed in place."""
        self._replay = ("_draw", args, kwargs)
        self._shown = None
        # Room to breathe, but not without limit: set beside a 35-row table
        # a chart used to be handed the whole table's height and drew a
        # histogram 1,100 pixels tall.
        self.setMaximumHeight(int(self._full_height * CHART_GROWTH))
        self.setMinimumHeight(self._full_height)
        self._draw(*args, **kwargs)

    def empty(self, message: str = "No data yet") -> None:
        self._replay = ("_draw_empty", (message,), {})
        self._shown = None
        # A chart with nothing in it does not need the room a chart needs. Held
        # at full height it leaves a hand-span of empty card with one line of
        # grey text adrift in the middle of it, which reads as something
        # broken rather than something not ready yet.
        self.setMinimumHeight(EMPTY_HEIGHT)
        self.setMaximumHeight(EMPTY_HEIGHT)
        self._draw_empty(message)

    def set_palette(self, palette: Palette) -> None:
        """Re-theme in place by replaying the last draw against new colours.

        Colours are baked in at draw time, so a palette change has to redraw.
        Replaying is cheaper than rebuilding the page around the canvas, and
        it keeps whatever the chart was showing.
        """
        if palette is self.palette:
            return
        self.palette = palette
        self.figure.patch.set_facecolor(palette.surface)
        name, args, kwargs = self._replay or ("_draw_empty", (), {})
        getattr(self, name)(*args, **kwargs)

    def _draw(self, *args, **kwargs) -> None:
        """Subclasses draw here. `plot()` is the entry point."""
        raise NotImplementedError

    # ---- shared styling --------------------------------------------------
    def new_axes(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        self.style_axes(ax)
        self._hover_targets = []
        self._annotation = None
        return ax

    def style_axes(self, ax) -> None:
        p = self.palette
        ax.set_facecolor(p.surface)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(p.baseline)
            ax.spines[side].set_linewidth(0.8)
        ax.tick_params(colors=p.ink_muted, labelsize=TICK_SIZE, length=0)
        ax.xaxis.label.set_color(p.ink_secondary)
        ax.yaxis.label.set_color(p.ink_secondary)
        ax.set_axisbelow(True)

    def grid(self, ax, axis: str = "y") -> None:
        ax.grid(axis=axis, color=self.palette.grid, **GRID_KW)

    def legend(self, ax, **kwargs) -> None:
        """A legend is present whenever two or more series share the axes."""
        handles, labels = ax.get_legend_handles_labels()
        if len(labels) < 2:
            return
        options = dict(
            # Anchored by its lower edge just above the plot, so it sits in
            # the margin instead of hanging down over the top of the data -
            # which is exactly where a leader's line or a peak tends to be.
            loc="lower left",
            bbox_to_anchor=(0, 1.01),
            ncols=min(4, len(labels)),
            frameon=False,
            fontsize=LABEL_SIZE,
            labelcolor=self.palette.ink_secondary,
            handlelength=1.4,
            columnspacing=1.2,
        )
        options.update(kwargs)
        ax.legend(**options)

    def _draw_empty(self, message: str = "No data yet") -> None:
        ax = self.new_axes()
        ax.axis("off")
        ax.text(
            0.5, 0.5, message,
            ha="center", va="center",
            color=self.palette.ink_muted, fontsize=11,
            transform=ax.transAxes,
        )
        self.draw_idle()

    # ---- hover -----------------------------------------------------------
    def register_hover(self, artist, labels: list[str]) -> None:
        """Attach per-element tooltip text to a plotted artist.

        A bar or histogram hands back a BarContainer, which is a tuple of
        patches and not an artist, so it has no `contains` of its own and
        would never report a hit. Containers and plain sequences are unpacked
        into their individual patches here, each carrying its own label.
        """
        items = getattr(artist, "patches", None)
        if items is None and isinstance(artist, (list, tuple)):
            items = artist
        if items is None:
            self._hover_targets.append((artist, list(labels)))
            return
        for item, label in zip(items, labels):
            self._hover_targets.append((item, [label]))

    def _ensure_annotation(self, ax):
        if self._annotation is None:
            p = self.palette
            self._annotation = ax.annotate(
                "",
                xy=(0, 0),
                xytext=(12, 14),
                textcoords="offset points",
                fontsize=LABEL_SIZE,
                color=p.ink,
                bbox=dict(boxstyle="round,pad=0.45", fc=p.raised, ec=p.grid, lw=0.8),
                zorder=100,
                annotation_clip=False,
            )
            self._annotation.set_visible(False)
        return self._annotation

    def _hover_at(self, event) -> tuple[str, tuple[float, float]] | None:
        """Text and anchor for the point under the cursor, or None."""
        for artist, labels in self._hover_targets:
            try:
                hit, info = artist.contains(event)
            except (AttributeError, TypeError):
                continue
            if not hit:
                continue
            index = 0
            if isinstance(info, dict) and len(info.get("ind", ())):
                index = int(info["ind"][0])
            if index >= len(labels):
                continue
            return labels[index], (event.xdata, event.ydata)
        return None

    def _hide_extras(self) -> None:
        """Hook for anything a subclass shows alongside the tooltip."""

    def _hide_hover(self) -> None:
        self._shown = None
        changed = False
        if self._annotation is not None and self._annotation.get_visible():
            self._annotation.set_visible(False)
            changed = True
        self._hide_extras()
        if changed:
            self.draw_idle()

    def _place(self, note, ax, x: float, y: float) -> None:
        """Offset the tooltip away from whichever edge it is nearest."""
        left, right = sorted(ax.get_xlim())
        low, high = sorted(ax.get_ylim())
        dx = 12 if (x - left) < (right - x) else -12
        dy = 14 if (y - low) < (high - y) else -14
        note.set_ha("left" if dx > 0 else "right")
        note.set_va("bottom" if dy > 0 else "top")
        note.set_position((dx, dy))

    def _on_hover(self, event) -> None:
        if event.inaxes is None or event.xdata is None:
            self._hide_hover()
            return
        found = self._hover_at(event)
        if found is None:
            self._hide_hover()
            return
        text, (x, y) = found
        note = self._ensure_annotation(event.inaxes)
        # Same tooltip, same place, already on screen: nothing to redraw.
        if self._shown == (text, x, y) and note.get_visible():
            return
        self._shown = (text, x, y)
        note.xy = (x, y)
        self._place(note, event.inaxes, x, y)
        note.set_text(text)
        note.set_visible(True)
        self.draw_idle()


class BarChart(Chart):
    """Horizontal bars for ranked magnitude - the default for a leaderboard."""

    def _draw(
        self,
        labels: list[str],
        values: list[float],
        *,
        xlabel: str = "",
        color: str | None = None,
        colors: list[str] | None = None,
        value_format: str = "{:.0f}",
        tooltips: list[str] | None = None,
        highlight: int | None = None,
        markers: list[float | None] | None = None,
        marker_label: str = "",
    ) -> None:
        if not labels:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        positions = list(range(len(labels)))
        # Rank order reads top-to-bottom, so the axis is inverted rather than
        # the data reversed.
        bar_colors = list(colors or [color or p.accent] * len(labels))
        if highlight is not None:
            bar_colors = [
                c if i == highlight else p.ink_muted for i, c in enumerate(bar_colors)
            ]
        bars = ax.barh(
            positions, values,
            color=bar_colors, height=BAR_HEIGHT, zorder=2,
            # A 2px surface gap keeps adjacent fills from touching.
            linewidth=1.0, edgecolor=p.surface,
        )
        ax.set_yticks(positions)
        ax.set_yticklabels(labels, fontsize=9.5)
        ax.invert_yaxis()
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=LABEL_SIZE)
        self.grid(ax, "x")
        # A tick across a bar marks what the bar is being measured against -
        # "it said 55%" on a bar of "it happened 73%" - so the gap is read
        # off the chart rather than guessed from a colour.
        if markers:
            reach = BAR_HEIGHT / 2 + 0.12
            drawn = False
            for position, mark in zip(positions, markers):
                if mark is None:
                    continue
                ax.plot(
                    [mark, mark], [position - reach, position + reach],
                    color=p.ink, linewidth=2.2, solid_capstyle="butt", zorder=4,
                    label=marker_label if (marker_label and not drawn) else None,
                )
                drawn = True
            if drawn and marker_label:
                self.legend(ax, loc="lower right")

        # Direct-label the ends; a leaderboard is read for its numbers, and on
        # the light palette some slots sit under 3:1 against the surface, so a
        # readable label is what carries the value rather than the fill.
        span = (max(values) - min(0, min(values))) or 1
        offset = span * 0.015
        for bar, value in zip(bars, values):
            negative = value < 0
            ax.text(
                bar.get_width() + (-offset if negative else offset),
                bar.get_y() + bar.get_height() / 2,
                value_format.format(value),
                va="center", ha="right" if negative else "left",
                fontsize=LABEL_SIZE, color=p.ink_secondary,
            )
        ax.margins(x=0.16 if any(v < 0 for v in values) else 0.13)
        # Labels formatted as a percentage mean the axis must be too, or the
        # bar reads "19.7%" against a scale that says 0.2.
        if "%" in value_format:
            ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        self.register_hover(
            bars,
            tooltips or [
                f"{label}: {value_format.format(v)}"
                for label, v in zip(labels, values)
            ],
        )
        self.draw_idle()


class DivergingBarChart(Chart):
    """Bars around zero, for a signed quantity such as money up or down."""

    def _draw(
        self,
        labels: list[str],
        values: list[float],
        *,
        xlabel: str = "",
        value_format=money,
        tooltips: list[str] | None = None,
    ) -> None:
        if not labels:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        positions = list(range(len(labels)))
        # Two poles with a neutral zero line: up is the cool pole, down warm.
        colors = [p.series_color(0) if v >= 0 else p.series_color(7) for v in values]
        bars = ax.barh(
            positions, values, color=colors, height=BAR_HEIGHT, zorder=2,
            linewidth=1.0, edgecolor=p.surface,
        )
        ax.axvline(0, color=p.baseline, linewidth=1.0, zorder=1)
        ax.set_yticks(positions)
        ax.set_yticklabels(labels, fontsize=9.5)
        ax.invert_yaxis()
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=LABEL_SIZE)
        self.grid(ax, "x")

        fmt = value_format if callable(value_format) else value_format.format
        span = (max(values) - min(values)) or 1
        inset = span * 0.015
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_width() + (inset if value >= 0 else -inset),
                bar.get_y() + bar.get_height() / 2,
                fmt(value),
                va="center", ha="left" if value >= 0 else "right",
                fontsize=LABEL_SIZE, color=p.ink_secondary,
            )
        ax.margins(x=0.18)
        self.register_hover(
            bars,
            tooltips or [f"{label}: {fmt(v)}" for label, v in zip(labels, values)],
        )
        self.draw_idle()


class LineChart(Chart):
    """Change over time. One axis; series identity by fixed colour slot.

    Hovering snaps to the nearest week and reads every series at once, with a
    guide line down the plot, because comparing players at one week is the
    question this chart exists to answer.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._columns: dict[float, list[tuple[str, float]]] = {}
        self._guide = None

    def _draw(
        self,
        x: list[int],
        series: list[tuple[str, list[float | None]]],
        *,
        xlabel: str = "Week",
        ylabel: str = "",
        direct_label: bool | None = None,
        reference: tuple[str, list[float]] | None = None,
        integer_x: bool = True,
        zero_baseline: bool = False,
    ) -> None:
        if not x or not series:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        self._columns = {}
        self._guide = None

        if reference is not None:
            name, values = reference
            ax.plot(
                x, values,
                color=p.ink_muted, linewidth=1.4, linestyle=(0, (4, 3)),
                zorder=2, label=name,
            )
            for xi, v in zip(x, values):
                if v is not None:
                    self._columns.setdefault(xi, []).append((name, v))

        # Direct labels are the default at small series counts; past four the
        # legend carries identity on its own.
        if direct_label is None:
            direct_label = len(series) <= 4

        ends: list[tuple[str, float, float, str]] = []   # name, x, y, colour
        for slot, (name, values) in enumerate(series):
            color = p.series_color(slot)
            points = [(xi, v) for xi, v in zip(x, values) if v is not None]
            if not points:
                continue
            # Missing weeks stay in the sequence as NaN so the line breaks
            # there. Dropping them would draw a straight segment across the
            # gap, which reads as data the player does not have.
            xs = list(x)
            ys = [float("nan") if v is None else v for v in values]
            ax.plot(
                xs, ys,
                color=color, linewidth=LINE_WIDTH,
                marker="o", markersize=MARKER_SIZE,
                # A 2px surface ring keeps overlapping markers readable.
                markeredgecolor=p.surface, markeredgewidth=1.2,
                label=name, zorder=3 + slot,
            )
            for xi, v in points:
                self._columns.setdefault(xi, []).append((name, v))
            # Anchored to the last week the player actually has, not to the
            # end of the axis, which may be a gap for them.
            ends.append((name, points[-1][0], points[-1][1], color))

        # The guide is created once per draw and simply moved on hover.
        self._guide = ax.axvline(
            x[0], color=p.baseline, linewidth=1.0, zorder=1, visible=False,
        )

        ax.set_xlabel(xlabel, fontsize=LABEL_SIZE)
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=LABEL_SIZE)
        if integer_x:
            ax.set_xticks(self._thin(x))
        # Wins, ranks and counts are whole numbers; a -2.5 tick on them
        # describes a value no one can have.
        plotted = [v for _, values in series for v in values if v is not None]
        if reference is not None:
            plotted += [v for v in reference[1] if v is not None]
        if plotted and all(float(v).is_integer() for v in plotted):
            ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
        # For a count of something (players left, say), an axis that starts
        # partway up makes a small number look like none at all.
        if zero_baseline and plotted and min(plotted) >= 0:
            ax.set_ylim(bottom=0)
        self.grid(ax, "y")
        if direct_label:
            ax.margins(x=0.13)
            # A reference line (a pool average, a buy-in) is usually the one
            # the chart is read against, so it is named at its end too.
            if reference is not None:
                ref_points = [(xi, v) for xi, v in zip(x, reference[1]) if v is not None]
                if ref_points:
                    ends.append((reference[0], *ref_points[-1], p.ink_muted))
            self._label_ends(ax, ends)
        self.legend(ax)
        self.draw_idle()

    def _label_ends(self, ax, ends: list[tuple[str, float, float, str]]) -> None:
        """Name each line at its end, nudging labels apart where they'd collide.

        Lines in a close race finish at nearly the same value, and labels
        placed exactly at each end then print on top of one another. Labels
        are pushed apart to a minimum spacing and joined back to their line by
        a short connector in the line's colour.

        The text itself is ink, not the series colour: on the light palette
        several slots sit under 3:1 against the surface, too faint to read as
        text. The connector and the line end carry identity instead.
        """
        if not ends:
            return
        ax.relim()
        ax.autoscale_view()
        low, high = sorted(ax.get_ylim())
        gap = (high - low) * 0.075 or 1.0

        # Top to bottom, each label at least `gap` below the one above it.
        ordered = sorted(ends, key=lambda e: -e[2])
        placed: list[float] = []
        for _, _, y, _ in ordered:
            placed.append(y if not placed else min(y, placed[-1] - gap))
        # If the stack ran off the bottom, lift it back inside the axes.
        deficit = (low + gap * 0.5) - placed[-1]
        if deficit > 0:
            placed = [min(y + deficit, high) for y in placed]

        text_space = mtransforms.offset_copy(
            ax.transData, fig=self.figure, x=9, units="points"
        )
        for (name, x, y, color), label_y in zip(ordered, placed):
            # A label level with its line gets a short dash; a nudged one gets
            # a slanted connector back to where its line actually ends.
            ax.annotate(
                name,
                xy=(x, y),
                xytext=(x, label_y),
                textcoords=text_space,
                color=self.palette.ink_secondary,
                fontsize=LABEL_SIZE, va="center", fontweight="semibold",
                arrowprops=dict(
                    arrowstyle="-", color=color, linewidth=1.2,
                    shrinkA=3, shrinkB=2,
                ),
                annotation_clip=False,
            )

    @staticmethod
    def _thin(values: list[int]) -> list[int]:
        """Every week if they fit, otherwise every nth, always keeping the last."""
        if len(values) <= MAX_X_TICKS:
            return list(values)
        step = -(-len(values) // MAX_X_TICKS)   # ceiling division
        kept = values[::step]
        if values[-1] not in kept:
            kept.append(values[-1])
        return kept

    # ---- hover -----------------------------------------------------------
    def _hover_at(self, event):
        # `_on_hover` screens these out, but `_hover_at` is also a hook a
        # subclass or a test may call directly.
        if not self._columns or event.xdata is None or event.ydata is None:
            return None
        nearest = min(self._columns, key=lambda xi: abs(xi - event.xdata))
        # Snap only within half a step, so the tooltip is not sticky off the end.
        keys = sorted(self._columns)
        step = min((b - a for a, b in zip(keys, keys[1:])), default=1.0) or 1.0
        if abs(nearest - event.xdata) > step * 0.5:
            return None
        rows = self._columns[nearest]
        text = "\n".join(
            [f"Week {nearest:g}"] + [f"{name}: {value:g}" for name, value in rows]
        )
        closest = min(rows, key=lambda row: abs(row[1] - event.ydata))[1]
        if self._guide is not None:
            self._guide.set_xdata([nearest, nearest])
            self._guide.set_visible(True)
        return text, (nearest, closest)

    def _hide_extras(self) -> None:
        if self._guide is not None and self._guide.get_visible():
            self._guide.set_visible(False)
            self.draw_idle()


class RankChart(LineChart):
    """A line chart with rank 1 at the top and whole-number positions."""

    def _draw(self, *args, **kwargs) -> None:
        super()._draw(*args, **kwargs)
        ax = self.figure.axes[0] if self.figure.axes else None
        if ax is None or not ax.has_data():
            return
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
        lo, hi = ax.get_ylim()
        # An unchanged position collapses the axis onto one value; give it room.
        if abs(hi - lo) < 1.5:
            middle = (hi + lo) / 2
            ax.set_ylim(middle - 1.5, middle + 1.5)
        ax.invert_yaxis()
        self.draw_idle()


class HistogramChart(Chart):
    """Distribution of a single measure across the pool."""

    def _draw(
        self,
        values: list[float],
        *,
        xlabel: str = "",
        ylabel: str = "Players",
        bins: list[float] | None = None,
        mean_line: bool = True,
    ) -> None:
        if not values:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        lo, hi = int(min(values)), int(max(values))
        edges = bins or [i - 0.5 for i in range(lo, hi + 2)]
        counts, edges_out, patches = ax.hist(
            values, bins=edges, color=p.accent, zorder=2,
            linewidth=1.0, edgecolor=p.surface,
        )
        tallest = max(counts) if len(counts) else 1
        if mean_line:
            mean = sum(values) / len(values)
            ax.axvline(
                mean, color=p.ink_muted, linewidth=1.4,
                linestyle=(0, (4, 3)), zorder=3,
            )
            # Headroom above the tallest bar for the label, and a backing
            # the colour of the chart, so "avg 20.4" never sits on top of a
            # bar where it could not be read.
            top = tallest * 1.22
            ax.set_ylim(0, top)
            ax.annotate(
                f"avg {mean:.1f}",
                xy=(mean, top),
                xytext=(5, -3), textcoords="offset points", va="top",
                color=p.ink_secondary, fontsize=LABEL_SIZE, zorder=5,
                bbox=dict(boxstyle="round,pad=0.25", fc=p.surface, ec="none", alpha=0.92),
            )
        ax.set_xlabel(xlabel, fontsize=LABEL_SIZE)
        ax.set_ylabel(ylabel, fontsize=LABEL_SIZE)
        ticks = list(range(lo, hi + 1))
        # A wide spread would otherwise print a tick per unit and overlap them.
        if len(ticks) > MAX_X_TICKS:
            ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=MAX_X_TICKS))
        else:
            ax.set_xticks(ticks)
        # Whole players, so never a half-player tick on the count axis.
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
        self.grid(ax, "y")
        centers = [(edges_out[i] + edges_out[i + 1]) / 2 for i in range(len(counts))]
        self.register_hover(
            patches,
            [
                f"{int(c)} player{'' if c == 1 else 's'} on {center:g}"
                for c, center in zip(counts, centers)
            ],
        )
        self.draw_idle()


def _neutral(p: Palette) -> str:
    """The grey at the middle of a diverging scale: visible, but claiming nothing."""
    return mix(p.ink, p.surface, 0.14)


def _diverging_color(p: Palette, value: float, low: float, center: float, high: float) -> str:
    """Two poles around a neutral grey - blue above the centre, red below.

    The same pair the diverging bar chart uses, so "above" and "below" read
    the same way everywhere in the app.
    """
    if value >= center:
        span, pole = (high - center) or 1, p.series_color(0)
        fraction = (value - center) / span
    else:
        span, pole = (center - low) or 1, p.series_color(7)
        fraction = (center - value) / span
    return mix(pole, _neutral(p), max(0.0, min(1.0, fraction)))


class HeatmapChart(Chart):
    """A grid of values - sequential for magnitude, diverging around a centre.

    Pass `center` when the value has a meaningful middle (a 50% head-to-head
    record, zero net) and the grid switches to two hues around a neutral
    grey: then "above" and "below" read at a glance, which one ramp from pale
    to dark cannot show.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._heatmap: tuple | None = None

    def _draw(
        self,
        row_labels: list[str],
        col_labels: list[str],
        values: list[list[float | None]] | None = None,
        *,
        vmax: float | None = None,
        tooltip_fn=None,
        cell_text: bool = False,
        key_label: str = "",
        center: float | None = None,
        vmin: float | None = None,
        cell_format: str = "{:g}",
        tick_rotation: float = 0,
    ) -> None:
        # A grid with no rows, no columns or no numbers in it is an empty
        # grid, not a crash: early in a season a page can reach here with
        # nothing to show yet, and it should say so.
        if not row_labels or not col_labels or not values:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        present = [v for row in values for v in row if v is not None]
        top = vmax or max(present, default=1) or 1
        bottom = vmin if vmin is not None else min(present, default=0)
        # What the key should say: the real lowest value, not the shading floor.
        key_low = bottom
        if center is None and vmin is None and top > bottom:
            # Shade from a hair below the floor, so the lowest score still
            # takes a step of colour rather than coming out as bare surface.
            bottom -= (top - bottom) * 0.15
        span = (top - bottom) or 1

        for r, row in enumerate(values):
            for c, value in enumerate(row):
                if value is None:
                    # On a diverging grid a gap is usually structural (a player
                    # against themselves), so it drops back to the surface.
                    color = p.surface if center is not None else p.raised
                elif center is not None:
                    color = _diverging_color(p, value, bottom, center, top)
                else:
                    # Measured from the lowest value present, not from zero.
                    # Nobody in this pool scores under seven of sixteen, so a
                    # ramp anchored at zero spends its whole bottom half on
                    # scores that cannot happen and paints every real one the
                    # same pale blue. Anchored at the floor, seven is dark,
                    # fourteen is pale, and the grid says something.
                    color = ramp_color(p, (value - bottom) / span)
                # A 2px surface gap keeps neighbouring cells legible.
                ax.add_patch(
                    mpatches.Rectangle(
                        (c + 0.02, r + 0.02), 0.96, 0.96,
                        facecolor=color, edgecolor=p.surface, linewidth=1.2,
                    )
                )
                if cell_text and value is not None:
                    ax.text(
                        c + 0.5, r + 0.5, cell_format.format(value),
                        ha="center", va="center", fontsize=8.5,
                        color=_ink_on(color),
                    )

        # The axis always holds room for at least this many columns, so two
        # weeks against twenty-four coaches gives cells a sane width instead of
        # one a hand across - at which point the grid stops reading as a grid.
        # The empty space to the right is the rest of the season, which is
        # honest: it is where the next sixteen weeks will go. A full season
        # fills it and nothing is padded at all.
        ax.set_xlim(0, max(len(col_labels), MIN_GRID_COLUMNS))
        ax.set_ylim(0, len(row_labels))
        ax.invert_yaxis()
        # A full season's worth of week labels overprint each other on a
        # narrow card; every second one still says which column is which.
        step = 1 if len(col_labels) <= MAX_GRID_LABELS else 2
        ax.set_xticks([i + 0.5 for i in range(0, len(col_labels), step)])
        ax.set_xticklabels(
            col_labels[::step], fontsize=LABEL_SIZE, rotation=tick_rotation,
            ha="left" if tick_rotation else "center",
            rotation_mode="anchor" if tick_rotation else "default",
        )
        ax.set_yticks([i + 0.5 for i in range(len(row_labels))])
        ax.set_yticklabels(row_labels, fontsize=LABEL_SIZE)
        ax.xaxis.set_ticks_position("top")
        for side in ("left", "bottom"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=p.ink_muted, labelsize=LABEL_SIZE, length=0)

        self._colour_key(ax, top, key_label, low=bottom, center=center, label_low=key_low)
        self._heatmap = (row_labels, col_labels, values, tooltip_fn)
        self.draw_idle()

    def _colour_key(
        self, ax, top: float, key_label: str,
        *, low: float = 0.0, center: float | None = None,
        label_low: float | None = None,
    ) -> None:
        """A shaded strip saying which end of the scale means more.

        Without it the grid asks the reader to guess whether the pale cells or
        the strong ones are the high scores, and the answer flips with theme.
        """
        p = self.palette
        if center is not None:
            # Three steps either side of the neutral middle.
            below = [
                _diverging_color(p, center - (center - low) * f, low, center, top)
                for f in (1.0, 2 / 3, 1 / 3)
            ]
            above = [
                _diverging_color(p, center + (top - center) * f, low, center, top)
                for f in (1 / 3, 2 / 3, 1.0)
            ]
            steps = below + [_neutral(p)] + above
            bounds = [low + i * (top - low) / len(steps) for i in range(len(steps) + 1)]
            ticks = [low, center, top]
        else:
            steps = list(p.sequential) or [p.accent]
            bounds = [low + i * (top - low) / len(steps) for i in range(len(steps) + 1)]
            ticks = [low if label_low is None else label_low, top]
        mappable = ScalarMappable(
            norm=BoundaryNorm(bounds, len(steps)), cmap=ListedColormap(steps)
        )
        bar = self.figure.colorbar(
            mappable, ax=ax, orientation="horizontal",
            fraction=0.05, pad=0.04, aspect=40,
        )
        bar.outline.set_visible(False)
        bar.ax.tick_params(colors=p.ink_muted, labelsize=8.5, length=0)
        bar.set_ticks(ticks)
        # "9" rather than "9.00": these scales count games, money and weeks,
        # and a trailing .00 on a key is noise pretending to be precision.
        bar.set_ticklabels([f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
                            for v in ticks])
        bar.ax.set_xlabel(
            key_label or f"{ramp_direction(p)} is more",
            fontsize=8.5, color=p.ink_muted,
        )

    def _hover_at(self, event):
        if self._heatmap is None or event.xdata is None or event.ydata is None:
            return None
        rows, cols, values, tooltip_fn = self._heatmap
        c, r = int(event.xdata), int(event.ydata)
        if not (0 <= r < len(rows) and 0 <= c < len(cols)):
            return None
        value = values[r][c]
        text = (
            tooltip_fn(rows[r], cols[c], value)
            if tooltip_fn
            else f"{rows[r]} - {cols[c]}: {'-' if value is None else f'{value:g}'}"
        )
        # Anchored to the cell, not the cursor: within one cell the tooltip is
        # then unchanged, and the chart is left alone until the pointer
        # crosses into the next one.
        return text, (c + 0.5, r + 0.5)


class ScatterChart(Chart):
    """Two measures per entity, one dot each, optionally split into quadrants.

    Every dot is the same colour: position carries the meaning, and a colour
    per player would repeat the names in a code nobody can hold in their head
    across twenty dots. Identity comes from direct labels on the dots worth
    naming (the ones furthest from the pack) and from hover on every dot.
    """

    def _draw(
        self,
        points: list[tuple[str, float, float]],
        *,
        xlabel: str = "",
        ylabel: str = "",
        quadrants: tuple[float, float] | None = None,
        quadrant_labels: tuple[str, str, str, str] | None = None,
        label_count: int = 6,
        highlight: str | None = None,
        tooltips: list[str] | None = None,
    ) -> None:
        """`quadrant_labels` run top-left, top-right, bottom-left, bottom-right."""
        if not points:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        names = [name for name, _, _ in points]
        xs = [x for _, x, _ in points]
        ys = [y for _, _, y in points]

        colors = [
            p.series_color(1) if highlight and name == highlight else p.accent
            for name in names
        ]
        dots = ax.scatter(
            xs, ys, s=64, c=colors, zorder=3,
            # A 2px surface ring keeps overlapping dots apart.
            edgecolors=p.surface, linewidths=1.2,
        )
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=LABEL_SIZE)
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=LABEL_SIZE)
        self.grid(ax, "both")
        ax.margins(0.12)

        if quadrants is not None:
            qx, qy = quadrants
            divider = dict(color=p.baseline, linewidth=1.0, linestyle=(0, (4, 3)), zorder=1)
            ax.axvline(qx, **divider)
            ax.axhline(qy, **divider)
            if quadrant_labels:
                corners = ((0.02, 0.98, "left", "top"), (0.98, 0.98, "right", "top"),
                           (0.02, 0.02, "left", "bottom"), (0.98, 0.02, "right", "bottom"))
                for text, (cx, cy, ha, va) in zip(quadrant_labels, corners):
                    ax.text(cx, cy, text, transform=ax.transAxes, ha=ha, va=va,
                            fontsize=8.5, color=p.ink_muted, style="italic")

        self._label_outliers(ax, points, label_count, highlight)
        self.register_hover(
            dots,
            tooltips or [f"{n}\n{xlabel}: {x:.2f}\n{ylabel}: {y:.2f}" for n, x, y in points],
        )
        self.draw_idle()

    def _label_outliers(self, ax, points, count: int, highlight: str | None) -> None:
        """Name the dots furthest from the middle of the pack.

        Distance is measured in units of each axis's own spread, so a measure
        that runs to 12 does not drown out one that runs to 3.
        """
        if count <= 0 or len(points) < 2:
            return
        xs = [x for _, x, _ in points]
        ys = [y for _, _, y in points]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        sx = statistics.pstdev(xs) or 1.0
        sy = statistics.pstdev(ys) or 1.0
        ranked = sorted(
            points,
            key=lambda pt: -(((pt[1] - mx) / sx) ** 2 + ((pt[2] - my) / sy) ** 2),
        )
        chosen = {name for name, _, _ in ranked[:count]}
        if highlight:
            chosen.add(highlight)
        for name, x, y in points:
            if name in chosen:
                ax.annotate(
                    name, xy=(x, y), xytext=(6, 5), textcoords="offset points",
                    fontsize=8.5, color=self.palette.ink_secondary,
                    fontweight="semibold" if name == highlight else "normal",
                )