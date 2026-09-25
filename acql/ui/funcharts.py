"""The Charts tab's own chart types, built on charts.Chart and its house rules:
themed surface, recessive grid, direct labels for the few lines that matter,
a hover tooltip on every mark, and redraw-in-place on a theme change."""

from __future__ import annotations

from matplotlib.ticker import MaxNLocator, PercentFormatter

from .charts import LABEL_SIZE, LINE_WIDTH, Chart

MUTED_ALPHA = 0.28


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


class RaceChart(Chart):
    """Every coach's place after each week: the pack in grey, a few in colour."""

    def _draw(self, weeks: list[int], series: list[tuple[str, list[int]]], *,
              highlight: str = "", named: int = 3) -> None:
        if not weeks or not series:
            self.empty("The race appears once a week is finished")
            return
        p = self.palette
        ax = self.new_axes()
        entrants = len(series)
        coloured = {name: p.series_color(i) for i, (name, _) in enumerate(series[:named])}
        if highlight and any(n == highlight for n, _ in series):
            coloured[highlight] = p.accent if highlight not in coloured else coloured[highlight]
        # the pack first, underneath
        for name, places in series:
            if name in coloured:
                continue
            line, = ax.plot(weeks, places, color=p.ink_muted, alpha=MUTED_ALPHA,
                            linewidth=1.0, marker="o", markersize=2.5, zorder=2)
            self.register_hover(line, [f"{name}\nafter week {w}: {_ordinal(pl)}" for w, pl in zip(weeks, places)])
        ends = []
        for name, places in series:
            if name not in coloured:
                continue
            mine = name == highlight
            line, = ax.plot(weeks, places, color=coloured[name],
                            linewidth=LINE_WIDTH + (1.2 if mine else 0), marker="o",
                            markersize=6 if mine else 4.5, markeredgecolor=p.surface,
                            markeredgewidth=1.0, zorder=6 if mine else 5)
            self.register_hover(line, [f"{name}\nafter week {w}: {_ordinal(pl)}" for w, pl in zip(weeks, places)])
            ends.append((name, places[-1], coloured[name], mine))
        # direct labels at the right, nudged apart
        ends.sort(key=lambda e: e[1])
        min_gap = max(1.0, entrants / 22)
        placed = []
        for name, y, color, mine in ends:
            spot = y if not placed else max(y, placed[-1] + min_gap)
            placed.append(spot)
            ax.annotate(f"{name}  {_ordinal(y)}", xy=(weeks[-1], y), xytext=(weeks[-1] + 0.25, spot),
                        color=color, fontsize=LABEL_SIZE, fontweight="bold" if mine else "normal",
                        va="center", annotation_clip=False)
        ax.set_ylim(entrants + 0.8, 0.2)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))
        ax.set_xticks(weeks)
        ax.set_xlim(weeks[0] - 0.3, weeks[-1] + max(1.6, len(weeks) * 0.28))
        ax.set_xlabel("Week", fontsize=LABEL_SIZE)
        ax.set_ylabel("Place", fontsize=LABEL_SIZE)
        self.grid(ax, "y")
        self.draw_idle()


class LandedChart(Chart):
    """One week: every coach's score as a dot, stacked where scores are equal."""

    def _draw(self, scores: list[tuple[str, int]], *, winners: list[str] = (),
              average: float | None = None, highlight: str = "", week: int | None = None) -> None:
        if not scores:
            self.empty("No scores for this week yet")
            return
        p = self.palette
        ax = self.new_axes()
        stacks: dict[int, list[str]] = {}
        for name, total in sorted(scores, key=lambda s: s[0].casefold()):
            stacks.setdefault(total, []).append(name)
        xs, ys, colors, sizes, labels = [], [], [], [], []
        winners = set(winners)
        for total, names in stacks.items():
            # winners and the highlighted coach sit at the bottom of their stack
            names.sort(key=lambda n: (n not in winners, n != highlight, n.casefold()))
            for level, name in enumerate(names):
                xs.append(total)
                ys.append(level + 1)
                if name == highlight:
                    colors.append(p.accent); sizes.append(120)
                elif name in winners:
                    colors.append(p.warning); sizes.append(95)
                else:
                    colors.append(p.ink_muted); sizes.append(60)
                labels.append(f"{name}: {total} wins" + ("  ★ won the week" if name in winners else ""))
        dots = ax.scatter(xs, ys, s=sizes, c=colors, edgecolors=p.surface, linewidths=1.0, zorder=4)
        self.register_hover(dots, labels)
        tallest = max(len(v) for v in stacks.values())
        if average is not None:
            ax.axvline(average, color=p.baseline, linestyle=(0, (4, 3)), linewidth=1.2, zorder=1)
            ax.text(average, tallest + 1.2, f"average {average:.1f}", ha="center", va="bottom",
                    color=p.ink_muted, fontsize=LABEL_SIZE)
        if highlight:
            mine = [(x, y) for x, y, lab in zip(xs, ys, labels) if lab.startswith(highlight + ":")]
            if mine:
                x, y = mine[0]
                ax.annotate(highlight, xy=(x, y), xytext=(0, 12), textcoords="offset points",
                            ha="center", color=p.accent, fontsize=LABEL_SIZE, fontweight="bold")
        top = max(stacks)
        ax.annotate("★ " + ", ".join(sorted(winners)), xy=(top, len(stacks[top])),
                    xytext=(0, 12 if highlight not in winners else 26), textcoords="offset points",
                    ha="right" if top - min(stacks) > 4 else "center", color=p.warning, fontsize=LABEL_SIZE)
        ax.set_ylim(0.3, tallest + 2.4)
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlim(min(stacks) - 1, max(stacks) + 1)
        ax.set_xlabel(f"Wins in week {week}" if week else "Wins", fontsize=LABEL_SIZE)
        self.grid(ax, "x")
        self.draw_idle()


class FunnelChart(Chart):
    """The suicide pool shrinking: who was left, and who fell, week by week."""

    def _draw(self, rows: list) -> None:
        if not rows:
            self.empty("The suicide pool appears once a week is finished")
            return
        p = self.palette
        ax = self.new_axes()
        weeks = [r.week for r in rows]
        left = [r.left for r in rows]
        knocked = [r.knocked for r in rows]
        stay = ax.bar(weeks, left, color=p.accent, width=0.62, zorder=3)
        fell = ax.bar(weeks, knocked, bottom=left, color=p.serious, width=0.62, zorder=3, alpha=0.85)
        tips = []
        for r in rows:
            teams = ", ".join(f"{t} {n}" for t, n in r.teams) or "nobody"
            tips.append(f"Week {r.week}: {r.alive_before} in, {r.knocked} out ({teams}), {r.left} left")
        self.register_hover(stay, tips)
        self.register_hover(fell, tips)
        for r in rows:
            if r.knocked:
                team = r.teams[0][0] if r.teams else ""
                short = team.split()[-1] if team else ""
                ax.text(r.week, r.alive_before + 0.3, f"−{r.knocked}" + (f" {short}" if short else ""),
                        ha="center", va="bottom", color=p.serious, fontsize=LABEL_SIZE)
            ax.text(r.week, r.left / 2, str(r.left), ha="center", va="center",
                    color=p.surface, fontsize=LABEL_SIZE, fontweight="bold")
        ax.set_xticks(weeks)
        ax.set_xlabel("Week", fontsize=LABEL_SIZE)
        ax.set_ylabel("Coaches", fontsize=LABEL_SIZE)
        ax.set_ylim(0, max(r.alive_before for r in rows) * 1.15 + 1)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        self.grid(ax, "y")
        self.draw_idle()


class CrowdChart(Chart):
    """Every game of the season: how much of the pool had the side credited."""

    UPSET = 0.30

    def _draw(self, games: list, *, highlight_week: int | None = None, named: int = 5) -> None:
        if not games:
            self.empty("Games appear once a week is finished")
            return
        p = self.palette
        ax = self.new_axes()
        by_week: dict[int, list] = {}
        for g in games:
            by_week.setdefault(g.week, []).append(g)
        xs, ys, colors, labels, placed = [], [], [], [], []
        for week, rows in by_week.items():
            rows.sort(key=lambda g: g.share)
            for i, g in enumerate(rows):
                # spread each week's games across a narrow band so none hide
                xs.append(week + (i - (len(rows) - 1) / 2) * min(0.045, 0.7 / max(1, len(rows))))
                ys.append(g.share)
                placed.append((xs[-1], g.share, g))
                upset = g.share < self.UPSET
                faded = highlight_week is not None and g.week != highlight_week
                base = p.serious if upset else p.accent
                colors.append(base if not faded else p.ink_muted)
                labels.append(f"Week {g.week}: {g.matchup}\ncredited to {g.winner}"
                              + (f" (pool line {g.line})" if g.line else "")
                              + f"\n{g.right} of {g.entrants} had it")
        dots = ax.scatter(xs, ys, c=colors, s=46, edgecolors=p.surface, linewidths=0.8, zorder=4)
        self.register_hover(dots, labels)
        ax.axhspan(0, self.UPSET, color=p.serious, alpha=0.07, zorder=0)
        ax.text(1.0, self.UPSET + 0.015, "upsets: under 30% had it", transform=ax.get_yaxis_transform(),
                ha="right", va="bottom", color=p.serious, fontsize=LABEL_SIZE - 1)
        for x, y, g in sorted(placed, key=lambda t: t[1])[:named]:
            ax.annotate(g.winner.split()[-1], xy=(x, y), xytext=(6, -2), textcoords="offset points",
                        color=p.ink_secondary, fontsize=LABEL_SIZE - 1)
        ax.set_ylim(-0.04, 1.04)
        ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        ax.set_xticks(sorted(by_week))
        ax.set_xlim(min(by_week) - 0.6, max(by_week) + 0.6)
        ax.set_xlabel("Week", fontsize=LABEL_SIZE)
        ax.set_ylabel("Share of the pool that had it", fontsize=LABEL_SIZE)
        self.grid(ax, "y")
        self.draw_idle()
