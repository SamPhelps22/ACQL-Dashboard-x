  // ---- charts ------------------------------------------------------------------------
  // Drawn after the page is on screen, at the width they actually have, so
  // the text stays the size it should be on a phone. Every chart is the same
  // form: one coach in gold - the viewer, or whoever is chosen - and everyone
  // else in grey, with the few that matter labelled at the end of their line.
  var charts = [];
  function chartBox(id, height, draw) {
    var box = el("div", { class: "chart", "data-chart": id, style: "min-height:" + height + "px" });
    charts.push({ node: box, draw: draw });
    return box;
  }
  function drawCharts() {
    charts.forEach(function (c) {
      if (!c.node.isConnected) return;
      var w = Math.max(260, Math.floor(c.node.clientWidth || 600));
      c.node.textContent = "";
      var out = c.draw(w);
      if (out) c.node.appendChild(out);
    });
  }
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { var f = focusKey(); drawCharts(); edges(); refocus(f); }, 150);
  });
  function niceMax(v) {
    if (v <= 5) return 5;
    var steps = [10, 20, 25, 40, 50, 60, 80, 100, 150, 200, 250, 400, 500, 1000];
    for (var i = 0; i < steps.length; i++) if (v <= steps[i]) return steps[i];
    return Math.ceil(v / 500) * 500;
  }
  function ticksFor(min, max, count_) {
    var span = max - min, raw = span / (count_ || 4);
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; }).filter(function (s) { return s >= raw; })[0] || raw;
    var out = [];
    for (var v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Math.round(v * 100) / 100);
    return out;
  }

  // A line chart over the weeks. `lines`: [{name, values, role: "me"|"strong"|"ctx", label}]
  // opts: xs (week numbers), height, min, max, invert (0 at the top), fmt (a value for
  // tooltips and ticks), title (what it shows, for screen readers), zero (draw the 0 line).
  function lineChart(width, lines, opts) {
    var H = opts.height || 240, narrow = width < 520;
    var padL = 40, padR = narrow ? 84 : 112, padT = 12, padB = 28;
    var xs = opts.xs, n = xs.length;
    var lo = opts.min != null ? opts.min : 0, hi = opts.max != null ? opts.max : 1;
    if (hi === lo) hi = lo + 1;
    var fmt = opts.fmt || function (v) { return String(v); };
    function X(i) { return padL + (n > 1 ? i * (width - padL - padR) / (n - 1) : (width - padL - padR) / 2); }
    function Y(v) {
      var f = (v - lo) / (hi - lo);
      return opts.invert ? padT + f * (H - padT - padB) : H - padB - f * (H - padT - padB);
    }
    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + H, width: width, height: H, role: "img", "aria-label": opts.title || "" });
    var grid = svgEl("g", { class: "grid" });
    ticksFor(lo, hi, 4).forEach(function (v) {
      grid.appendChild(svgEl("line", { x1: padL, x2: width - padR + 8, y1: Y(v), y2: Y(v) }));
      grid.appendChild(svgEl("text", { x: padL - 6, y: Y(v) + 4, "text-anchor": "end", text: fmt(v) }));
    });
    svg.appendChild(grid);
    if (opts.zero && lo < 0 && hi > 0) svg.appendChild(svgEl("line", { class: "zero", x1: padL, x2: width - padR + 8, y1: Y(0), y2: Y(0) }));
    var every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((width - padL - padR) / 42))));
    xs.forEach(function (wk, i) {
      if (i % every && i !== n - 1) return;
      svg.appendChild(svgEl("text", { x: X(i), y: H - 8, "text-anchor": "middle", text: (i === 0 && !narrow ? "Wk " : "") + wk }));
    });
    function path(values) {
      var d = "", pen = false;
      values.forEach(function (v, i) {
        if (v == null || isNaN(v)) { pen = false; return; }
        d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1);
        pen = true;
      });
      return d;
    }
    var order = { ctx: 0, strong: 1, me: 2 };
    lines.slice().sort(function (a, b) { return order[a.role] - order[b.role]; }).forEach(function (ln) {
      svg.appendChild(svgEl("path", { class: "ln " + ln.role, d: path(ln.values) }));
    });
    // end labels: the viewer first, then the others; one that would collide is left to the tooltip
    var taken = [];
    lines.filter(function (ln) { return ln.label; }).sort(function (a, b) { return order[b.role] - order[a.role]; }).forEach(function (ln) {
      var i = ln.values.length - 1;
      while (i >= 0 && ln.values[i] == null) i--;
      if (i < 0) return;
      var yy = Y(ln.values[i]);
      svg.appendChild(svgEl("circle", { class: "end " + ln.role, cx: X(i), cy: yy, r: 4.5 }));
      if (taken.some(function (t) { return Math.abs(t - yy) < 14; })) return;
      taken.push(yy);
      var text = ln.name.length > (narrow ? 11 : 16) ? ln.name.slice(0, narrow ? 10 : 15) + "…" : ln.name;
      svg.appendChild(svgEl("text", { class: "lbl" + (ln.role === "me" ? " me" : ""), x: X(i) + 9, y: yy + 4, text: text + " " + fmt(ln.values[i]) }));
    });
    return withCrosshair(svg, width, H, padT, padB, n, X, function (i) {
      var shown = lines.filter(function (ln) { return ln.role !== "ctx" && ln.values[i] != null; })
        .sort(function (a, b) { return order[b.role] - order[a.role] || (opts.invert ? a.values[i] - b.values[i] : b.values[i] - a.values[i]); });
      return { title: (opts.tipTitle || function (i) { return "After week " + xs[i]; })(i),
        rows: shown.map(function (ln) { return { name: ln.name, value: fmt(ln.values[i]), me: ln.role === "me" }; }) };
    });
  }
  // The hover and keyboard layer: a hairline that snaps to the nearest week,
  // and one readout listing every labelled line there.
  function withCrosshair(svg, width, H, padT, padB, n, X, readout) {
    var wrap = el("div", { style: "position:relative" });
    var cross = svgEl("line", { class: "cross", y1: padT, y2: H - padB, x1: 0, x2: 0, visibility: "hidden" });
    svg.appendChild(cross);
    var tip = el("div", { class: "tip", hidden: true });
    var current = -1;
    function show(i) {
      if (i < 0 || i >= n) return;
      current = i;
      cross.setAttribute("x1", X(i));
      cross.setAttribute("x2", X(i));
      cross.setAttribute("visibility", "visible");
      var r = readout(i);
      tip.textContent = "";
      tip.appendChild(el("span", { class: "t", text: r.title }));
      r.rows.forEach(function (row) {
        tip.appendChild(el("span", { class: "ln" }, [el("i", { class: row.me ? "me" : "" }), el("b", { text: row.value }), el("span", { text: row.name })]));
      });
      tip.hidden = false;
      var left = X(i) + 14;
      tip.style.top = (padT + 4) + "px";
      tip.style.left = left + "px";
      if (left + tip.offsetWidth > width) tip.style.left = Math.max(0, X(i) - 14 - tip.offsetWidth) + "px";
    }
    function hide() { tip.hidden = true; cross.setAttribute("visibility", "hidden"); }
    function nearest(evt) {
      var box = svg.getBoundingClientRect();
      var px = (evt.clientX - box.left) * (width / box.width);
      var best = 0, dist = Infinity;
      for (var i = 0; i < n; i++) { var d = Math.abs(X(i) - px); if (d < dist) { dist = d; best = i; } }
      return best;
    }
    var hit = svgEl("rect", { class: "hit", x: 0, y: 0, width: width, height: H, tabindex: "0",
      onpointermove: function (e) { show(nearest(e)); }, onpointerdown: function (e) { show(nearest(e)); },
      onpointerleave: hide, onblur: hide, onfocus: function () { show(current >= 0 ? current : n - 1); },
      onkeydown: function (e) {
        if (e.key === "ArrowLeft") { show(Math.max(0, current - 1)); e.preventDefault(); }
        if (e.key === "ArrowRight") { show(Math.min(n - 1, current + 1)); e.preventDefault(); }
      } });
    svg.appendChild(hit);
    wrap.appendChild(svg);
    wrap.appendChild(tip);
    return wrap;
  }
  // The numbers behind a chart, for anyone who'd rather read them.
  function tableView(key, head, rows) {
    return fold("table:" + key, "Show the numbers", [scroller(el("table", {}, [
      el("thead", {}, [el("tr", {}, head.map(function (h, i) { return el("th", { class: i ? "n" : null, text: h }); }))]),
      el("tbody", {}, rows.map(function (r) {
        return el("tr", { class: isMe(r[0]) || r[0] === highlighted() ? "me" : null }, r.map(function (v, i) { return el("td", { class: i ? "n num" : "coach", text: String(v) }); }));
      }))
    ]))], "tableview");
  }
  function legend(items) {
    return el("div", { class: "legend" }, items.map(function (it) { return el("span", {}, [el("i", { class: it[0] }), it[1]]); }));
  }

