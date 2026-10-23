  // ---- the season's numbers, week by week --------------------------------------------------
  function seasonWeeks() { return DATA.weeks.map(function (w) { return w.week; }).sort(function (a, b) { return a - b; }); }
  function totalsByWeek() {
    var weeks = seasonWeeks(), out = {};
    DATA.players.forEach(function (p) {
      var run = 0;
      out[p.name] = weeks.map(function (n) { var v = p.weekly[String(n)]; if (v != null) run += v; return run; });
    });
    return out;
  }
  function highlighted() {
    var h = state.chartMe && player(state.chartMe) ? state.chartMe : (hasMe() ? state.me : "");
    return h;
  }
  function raceChart(width, focus) {
    var weeks = seasonWeeks(), totals = totalsByWeek();
    var leadBy = weeks.map(function (n, i) { return Math.max.apply(null, Object.keys(totals).map(function (k) { return totals[k][i]; })); });
    var behind = {};
    Object.keys(totals).forEach(function (k) { behind[k] = totals[k].map(function (v, i) { return leadBy[i] - v; }); });
    var top = DATA.players.slice(0, 3).map(function (p) { return p.name; });
    var lines = Object.keys(behind).map(function (k) {
      var role = k === focus ? "me" : top.indexOf(k) >= 0 ? "strong" : "ctx";
      return { name: k, values: behind[k], role: role, label: role !== "ctx" };
    });
    var worst = Math.max.apply(null, lines.map(function (l) { return Math.max.apply(null, l.values); }).concat([4]));
    return lineChart(width, lines, { xs: weeks, height: width < 520 ? 240 : 300, min: 0, max: Math.ceil(worst), invert: true,
      fmt: function (v) { return v === 0 ? "lead" : "−" + v; }, title: "Wins behind the leader after each week" });
  }
  function titleChart(width, focus) {
    var T = DATA.title_by_week || {};
    var weeks = T.weeks || [], odds = T.odds || {};
    var latest = Object.keys(odds).sort(function (a, b) { return (odds[b][odds[b].length - 1] || 0) - (odds[a][odds[a].length - 1] || 0); });
    var top = latest.slice(0, 4);
    var lines = Object.keys(odds).map(function (k) {
      var role = k === focus ? "me" : top.indexOf(k) >= 0 ? "strong" : "ctx";
      return { name: k, values: odds[k], role: role, label: role !== "ctx" };
    });
    var peak = Math.max.apply(null, lines.map(function (l) { return Math.max.apply(null, l.values.map(function (v) { return v || 0; })); }).concat([10]));
    return lineChart(width, lines, { xs: weeks, height: width < 520 ? 240 : 300, min: 0, max: niceMax(peak),
      fmt: function (v) { return v < 1 && v > 0 ? "<1%" : Math.round(v) + "%"; }, title: "Chance of the title after each week" });
  }
  function moneyChart(width, focus, alone) {
    var M = DATA.money_by_week || {}, weeks = seasonWeeks();
    var lines = Object.keys(M).filter(function (k) { return !alone || k === focus; }).map(function (k) {
      return { name: k, values: M[k], role: k === focus ? "me" : "ctx", label: k === focus };
    });
    if (!alone) {
      var ends = Object.keys(M).sort(function (a, b) { return M[b][M[b].length - 1] - M[a][M[a].length - 1]; });
      [ends[0], ends[ends.length - 1]].forEach(function (k) {
        lines.forEach(function (l) { if (l.name === k && l.role !== "me") { l.role = "strong"; l.label = true; } });
      });
    }
    var all = lines.reduce(function (a, l) { return a.concat(l.values); }, [0]);
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    var pad = Math.max(5, (hi - lo) * 0.08);
    return lineChart(width, lines, { xs: weeks, height: alone ? 160 : (width < 520 ? 240 : 300), min: Math.floor(lo - pad), max: Math.ceil(hi + pad), zero: true,
      fmt: function (v) { return dollars(v); }, title: "Money after each week" });
  }
  // Every week's scores: the pool from lowest to highest, its average, and one coach.
  function spreadChart(width, focus) {
    var weeks = DATA.weeks.slice().sort(function (a, b) { return a.week - b.week; });
    var H = width < 520 ? 220 : 260, padL = 40, padR = 20, padT = 12, padB = 28, n = weeks.length;
    var hi = Math.max.apply(null, weeks.map(function (w) { return w.top; }).concat([10]));
    hi = Math.ceil(hi / 2) * 2 + 2;
    function X(i) { return padL + (n > 1 ? (i + 0.5) * (width - padL - padR) / n : (width - padL - padR) / 2); }
    function Y(v) { return H - padB - (v / hi) * (H - padT - padB); }
    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + H, width: width, height: H, role: "img",
      "aria-label": "Every week’s scores, low to high, with the average" + (focus ? " and " + focus + "’s score" : "") });
    var grid = svgEl("g", { class: "grid" });
    ticksFor(0, hi, 4).forEach(function (v) {
      grid.appendChild(svgEl("line", { x1: padL, x2: width - padR, y1: Y(v), y2: Y(v) }));
      grid.appendChild(svgEl("text", { x: padL - 6, y: Y(v) + 4, "text-anchor": "end", text: String(v) }));
    });
    svg.appendChild(grid);
    var every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((width - padL - padR) / 34))));
    weeks.forEach(function (w, i) {
      var lo = Math.min.apply(null, w.scores.map(function (s) { return s.total; }));
      svg.appendChild(svgEl("line", { class: "rng", x1: X(i), x2: X(i), y1: Y(lo), y2: Y(w.top) }));
      svg.appendChild(svgEl("line", { class: "avgtick", x1: X(i) - 9, x2: X(i) + 9, y1: Y(w.average), y2: Y(w.average) }));
      var mine = focus ? w.scores.filter(function (s) { return s.name === focus; })[0] : null;
      if (mine) svg.appendChild(svgEl("circle", { class: "medot", cx: X(i), cy: Y(mine.total), r: 5.5 }));
      if (!(i % every) || i === n - 1) svg.appendChild(svgEl("text", { x: X(i), y: H - 8, "text-anchor": "middle", text: String(w.week) }));
    });
    return withCrosshair(svg, width, H, padT, padB, n, X, function (i) {
      var w = weeks[i];
      var lo = Math.min.apply(null, w.scores.map(function (s) { return s.total; }));
      var mine = focus ? w.scores.filter(function (s) { return s.name === focus; })[0] : null;
      var rows = [{ name: "best: " + listNames(w.winners, 2), value: String(w.top) }, { name: "the pool’s average", value: w.average.toFixed(1) },
        { name: "lowest", value: String(lo) }];
      if (mine) rows.unshift({ name: focus, value: String(mine.total), me: true });
      return { title: "Week " + w.week, rows: rows };
    });
  }
  function weekScoreChart(p, width) { return spreadChart(width, p.name); }
  // The viewer's chance of winning the week, each time this phone checked.
  function sparkChart(points, width) {
    var H = 150, padL = 40, padR = 20, padT = 10, padB = 24, n = points.length;
    var t0 = points[0][0], t1 = points[n - 1][0], span = Math.max(1, t1 - t0);
    function X(i) { return padL + (points[i][0] - t0) / span * (width - padL - padR); }
    function Y(v) { return H - padB - v * (H - padT - padB); }
    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + H, width: width, height: H, role: "img", "aria-label": "Your chance of winning the week over time" });
    var grid = svgEl("g", { class: "grid" });
    [0, 0.25, 0.5, 0.75, 1].forEach(function (v) {
      grid.appendChild(svgEl("line", { x1: padL, x2: width - padR, y1: Y(v), y2: Y(v) }));
      grid.appendChild(svgEl("text", { x: padL - 6, y: Y(v) + 4, "text-anchor": "end", text: Math.round(v * 100) + "%" }));
    });
    svg.appendChild(grid);
    svg.appendChild(svgEl("text", { x: padL, y: H - 6, text: clock(new Date(t0)) }));
    svg.appendChild(svgEl("text", { x: width - padR, y: H - 6, "text-anchor": "end", text: clock(new Date(t1)) }));
    var d = points.map(function (pt, i) { return (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(pt[1]).toFixed(1); }).join("");
    svg.appendChild(svgEl("path", { class: "ln me", d: d }));
    svg.appendChild(svgEl("circle", { class: "end me", cx: X(n - 1), cy: Y(points[n - 1][1]), r: 4.5 }));
    return withCrosshair(svg, width, H, padT, padB, n, X, function (i) {
      return { title: clock(new Date(points[i][0])), rows: [{ name: "to win the week", value: pct(points[i][1]), me: true }] };
    });
  }

