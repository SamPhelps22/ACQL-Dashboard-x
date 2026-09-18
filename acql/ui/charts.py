"""Matplotlib charts embedded in Qt.

House rules applied throughout:
  * one y-axis, never two;
  * categorical colour assigned by fixed slot, following the entity not its rank;
  * thin marks, recessive grid, no number printed on every point;
  * a legend whenever two or more series share an axes, with direct labels on
    small series counts so identity never rests on colour alone;
  * a hover tooltip on every plotted form.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QSizePolicy

from .theme import Palette, ramp_color

GRID_KW = dict(linewidth=0.7, alpha=0.9, zorder=0)
LINE_WIDTH = 2.0
MARKER_SIZE = 5.5


class Chart(FigureCanvasQTAgg):
    """Base canvas: themed surface, tight layout, and a shared hover tooltip."""

    def __init__(self, palette: Palette, height: float = 2.8, parent=None) -> None:
        self.palette = palette
        self.figure = Figure(figsize=(6, height), dpi=100, layout="constrained")
        super().__init__(self.figure)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(int(height * 100))
        self.figure.patch.set_facecolor(palette.surface)
        self._annotation = None
        self._hover_targets: list[tuple] = []
        self.mpl_connect("motion_notify_event", self._on_hover)

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
        ax.tick_params(colors=p.ink_muted, labelsize=9, length=0)
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
            loc="upper left",
            bbox_to_anchor=(0, 1.02),
            ncols=min(4, len(labels)),
            frameon=False,
            fontsize=9,
            labelcolor=self.palette.ink_secondary,
            handlelength=1.4,
            columnspacing=1.2,
        )
        options.update(kwargs)
        ax.legend(**options)

    def empty(self, message: str = "No data yet") -> None:
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
        """Attach per-element tooltip text to a plotted artist."""
        self._hover_targets.append((artist, labels))

    def _ensure_annotation(self, ax):
        if self._annotation is None:
            p = self.palette
            self._annotation = ax.annotate(
                "",
                xy=(0, 0),
                xytext=(12, 14),
                textcoords="offset points",
                fontsize=9,
                color=p.ink,
                bbox=dict(boxstyle="round,pad=0.45", fc=p.raised, ec=p.grid, lw=0.8),
                zorder=100,
                annotation_clip=False,
            )
            self._annotation.set_visible(False)
        return self._annotation

    def _on_hover(self, event) -> None:
        if event.inaxes is None or not self._hover_targets:
            if self._annotation is not None and self._annotation.get_visible():
                self._annotation.set_visible(False)
                self.draw_idle()
            return
        note = self._ensure_annotation(event.inaxes)
        for artist, labels in self._hover_targets:
            try:
                hit, info = artist.contains(event)
            except (AttributeError, TypeError):
                continue
            if not hit:
                continue
            index = None
            if "ind" in info and len(info["ind"]):
                index = int(info["ind"][0])
            elif hasattr(artist, "get_x"):
                index = 0
            if index is None or index >= len(labels):
                continue
            note.xy = (event.xdata, event.ydata)
            note.set_text(labels[index])
            note.set_visible(True)
            self.draw_idle()
            return
        if note.get_visible():
            note.set_visible(False)
            self.draw_idle()


class BarChart(Chart):
    """Horizontal bars for ranked magnitude - the default for a leaderboard."""

    def plot(
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
    ) -> None:
        if not labels:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        positions = range(len(labels))
        # Rank order reads top-to-bottom, so the axis is inverted rather than
        # the data reversed.
        bar_colors = colors or [color or p.accent] * len(labels)
        if highlight is not None:
            bar_colors = [
                c if i == highlight else p.ink_muted for i, c in enumerate(bar_colors)
            ]
        bars = ax.barh(
            list(positions), values,
            color=bar_colors, height=0.68, zorder=2,
            # A 2px surface gap keeps adjacent fills from touching.
            linewidth=1.0, edgecolor=p.surface,
        )
        ax.set_yticks(list(positions))
        ax.set_yticklabels(labels, fontsize=9.5)
        ax.invert_yaxis()
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=9)
        self.grid(ax, "x")

        # Direct-label the ends; a leaderboard is read for its numbers.
        span = max(values) - min(0, min(values)) if values else 1
        offset = span * 0.015 if span else 0.1
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_width() + offset,
                bar.get_y() + bar.get_height() / 2,
                value_format.format(value),
                va="center", ha="left",
                fontsize=9, color=p.ink_secondary,
            )
        ax.margins(x=0.13)
        self.register_hover(
            bars, tooltips or [f"{l}: {value_format.format(v)}" for l, v in zip(labels, values)]
        )
        self.draw_idle()


def money(value: float) -> str:
    """Currency with the sign ahead of the symbol: -$40, not $-40."""
    return f"{'-' if value < 0 else ''}${abs(value):,.0f}"


class DivergingBarChart(Chart):
    """Bars around zero, for a signed quantity such as money up or down."""

    def plot(
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
        colors = [p.series[0] if v >= 0 else p.series[7] for v in values]
        bars = ax.barh(
            positions, values, color=colors, height=0.68, zorder=2,
            linewidth=1.0, edgecolor=p.surface,
        )
        ax.axvline(0, color=p.baseline, linewidth=1.0, zorder=1)
        ax.set_yticks(positions)
        ax.set_yticklabels(labels, fontsize=9.5)
        ax.invert_yaxis()
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=9)
        self.grid(ax, "x")

        fmt = value_format if callable(value_format) else value_format.format
        span = (max(values) - min(values)) or 1
        for bar, value in zip(bars, values):
            inset = span * 0.015
            ax.text(
                bar.get_width() + (inset if value >= 0 else -inset),
                bar.get_y() + bar.get_height() / 2,
                fmt(value),
                va="center", ha="left" if value >= 0 else "right",
                fontsize=9, color=p.ink_secondary,
            )
        ax.margins(x=0.18)
        self.register_hover(
            bars, tooltips or [f"{l}: {fmt(v)}" for l, v in zip(labels, values)]
        )
        self.draw_idle()


class LineChart(Chart):
    """Change over time. One axis; series identity by fixed colour slot."""

    def plot(
        self,
        x: list[int],
        series: list[tuple[str, list[float | None]]],
        *,
        xlabel: str = "Week",
        ylabel: str = "",
        direct_label: bool | None = None,
        reference: tuple[str, list[float]] | None = None,
        integer_x: bool = True,
    ) -> None:
        if not x or not series:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()

        if reference is not None:
            name, values = reference
            ax.plot(
                x, values,
                color=p.ink_muted, linewidth=1.4, linestyle=(0, (4, 3)),
                zorder=2, label=name,
            )

        # Direct labels are the default at small series counts; past four the
        # legend carries identity on its own.
        if direct_label is None:
            direct_label = len(series) <= 4

        for slot, (name, values) in enumerate(series):
            color = p.series_color(slot)
            points = [(xi, v) for xi, v in zip(x, values) if v is not None]
            if not points:
                continue
            xs, ys = zip(*points)
            line, = ax.plot(
                xs, ys,
                color=color, linewidth=LINE_WIDTH,
                marker="o", markersize=MARKER_SIZE,
                markeredgecolor=p.surface, markeredgewidth=1.2,
                label=name, zorder=3 + slot,
            )
            self.register_hover(line, [f"{name}\nWeek {xi}: {v:g}" for xi, v in points])
            if direct_label:
                ax.annotate(
                    name,
                    xy=(xs[-1], ys[-1]),
                    xytext=(7, 0), textcoords="offset points",
                    color=color, fontsize=9, va="center", fontweight="600",
                )

        ax.set_xlabel(xlabel, fontsize=9)
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=9)
        if integer_x:
            ax.set_xticks(x)
        self.grid(ax, "y")
        if direct_label:
            ax.margins(x=0.13)
        self.legend(ax)
        self.draw_idle()


class RankChart(LineChart):
    """A line chart with rank 1 at the top and whole-number positions."""

    def plot(self, *args, **kwargs) -> None:  # type: ignore[override]
        super().plot(*args, **kwargs)
        ax = self.figure.axes[0] if self.figure.axes else None
        if ax is None or not ax.has_data():
            return
        from matplotlib.ticker import MaxNLocator

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

    def plot(
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
        if mean_line and values:
            mean = sum(values) / len(values)
            ax.axvline(
                mean, color=p.ink_muted, linewidth=1.4,
                linestyle=(0, (4, 3)), zorder=3,
            )
            ax.annotate(
                f"avg {mean:.1f}",
                xy=(mean, max(counts) if len(counts) else 1),
                xytext=(6, -4), textcoords="offset points",
                color=p.ink_secondary, fontsize=9,
            )
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_xticks(range(lo, hi + 1))
        self.grid(ax, "y")
        centers = [(edges_out[i] + edges_out[i + 1]) / 2 for i in range(len(counts))]
        self.register_hover(
            patches,
            [f"{int(c)} player(s) on {center:g}" for c, center in zip(counts, centers)],
        )
        self.draw_idle()


class HeatmapChart(Chart):
    """A sequential grid - one hue, light to dark, for magnitude."""

    def plot(
        self,
        row_labels: list[str],
        col_labels: list[str],
        values: list[list[float | None]],
        *,
        vmax: float | None = None,
        tooltip_fn=None,
        cell_text: bool = False,
    ) -> None:
        if not row_labels or not col_labels:
            self.empty()
            return
        p = self.palette
        ax = self.new_axes()
        top = vmax or max(
            (v for row in values for v in row if v is not None), default=1
        ) or 1

        for r, row in enumerate(values):
            for c, value in enumerate(row):
                if value is None:
                    color = p.raised
                else:
                    color = ramp_color(p, value / top if top else 0)
                # A 2px surface gap keeps neighbouring cells legible.
                ax.add_patch(
                    matplotlib.patches.Rectangle(
                        (c + 0.02, r + 0.02), 0.96, 0.96,
                        facecolor=color, edgecolor=p.surface, linewidth=1.2,
                    )
                )
                if cell_text and value is not None:
                    fraction = value / top if top else 0
                    ink = "#ffffff" if (p.name == "light") == (fraction > 0.55) else p.ink
                    ax.text(
                        c + 0.5, r + 0.5, f"{value:g}",
                        ha="center", va="center", fontsize=8.5, color=ink,
                    )

        ax.set_xlim(0, len(col_labels))
        ax.set_ylim(0, len(row_labels))
        ax.invert_yaxis()
        ax.set_xticks([i + 0.5 for i in range(len(col_labels))])
        ax.set_xticklabels(col_labels, fontsize=9)
        ax.set_yticks([i + 0.5 for i in range(len(row_labels))])
        ax.set_yticklabels(row_labels, fontsize=9)
        ax.xaxis.set_ticks_position("top")
        for side in ("left", "bottom"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=p.ink_muted, labelsize=9, length=0)

        self._heatmap = (row_labels, col_labels, values, tooltip_fn)
        self.mpl_connect("motion_notify_event", self._heat_hover)
        self.draw_idle()

    def _heat_hover(self, event) -> None:
        data = getattr(self, "_heatmap", None)
        if data is None or event.inaxes is None or event.xdata is None:
            return
        rows, cols, values, tooltip_fn = data
        c, r = int(event.xdata), int(event.ydata)
        note = self._ensure_annotation(event.inaxes)
        if 0 <= r < len(rows) and 0 <= c < len(cols):
            value = values[r][c]
            text = (
                tooltip_fn(rows[r], cols[c], value)
                if tooltip_fn
                else f"{rows[r]} - {cols[c]}: {'-' if value is None else f'{value:g}'}"
            )
            note.xy = (event.xdata, event.ydata)
            note.set_text(text)
            note.set_visible(True)
        else:
            note.set_visible(False)
        self.draw_idle()
