  // ---- coach connection map: the pool as a network -----------------------------------
  // Coaches are nodes (keyed by their stable id), pairs are edges. Every pair's
  // numbers come from the head-to-head page's own compare(a, b, from, to), so the
  // two pages can't disagree. Pairs are worked out once per week range and
  // kept; choosing a coach, zooming or panning only redraws.
  var CM_TYPES = {
    h2h: { label: "Head-to-head", about: "Closest weekly rivals: the smallest average gap between their weekly scores." },
    shared: { label: "Shared picks", about: "Who most often took the same side of the same game." },
    differ: { label: "Different picks", about: "Who most often took opposite sides of the same game." },
    similar: { label: "Similar seasons", about: "Whose weekly results, measured against the pool average, track each other most closely." }
  };
  var CM_MIN = { h2h: 2, shared: 16, differ: 16, similar: 3 };   // weeks, games, games, weeks
  var cmCache = {};
  function cmWeeks() {
    return DATA.weeks.filter(function (w) { return w.scores && w.scores.length; }).map(function (w) { return w.week; }).sort(function (a, b) { return a - b; });
  }
  function cmPairs(from, to) {
    var key = from + "-" + to;
    if (cmCache[key]) return cmCache[key];
    var avg = {};
    DATA.weeks.forEach(function (w) {
      if (w.week < from || w.week > to || !w.scores || !w.scores.length) return;
      avg[w.week] = w.scores.reduce(function (a, s) { return a + s.total; }, 0) / w.scores.length;
    });
    var people = DATA.players.map(function (p) { return p.name; });
    var out = [];
    for (var i = 0; i < people.length; i++) {
      for (var j = i + 1; j < people.length; j++) {
        var a = people[i], b = people[j], c = compare(a, b, from, to);
        var n = 0, gap = 0, relGap = 0;
        c.weeks.forEach(function (row) {
          if (row.a == null || row.b == null) return;
          n++; gap += Math.abs(row.a - row.b);
          relGap += Math.abs((row.a - avg[row.week]) - (row.b - avg[row.week]));
        });
        out.push({ a: a, b: b, weeks: n, aWeeks: c.aWeeks, bWeeks: c.bWeeks, level: c.level,
          gap: n ? gap / n : null, relGap: n ? relGap / n : null,
          games: c.both, agree: c.agree, differ: c.both - c.agree, aSplit: c.aSplit, bSplit: c.bSplit });
      }
    }
    cmCache[key] = out;
    return out;
  }
  // How strong a pair is for a relationship type (higher = stronger); null when
  // there isn't enough to compare.
  function cmStrength(type, e) {
    if (type === "h2h") return e.weeks >= CM_MIN.h2h ? 1 / (1 + e.gap) : null;
    if (type === "shared") return e.games >= CM_MIN.shared ? e.agree / e.games : null;
    if (type === "differ") return e.games >= CM_MIN.differ ? e.differ / e.games : null;
    if (type === "similar") return e.weeks >= CM_MIN.similar ? 1 / (1 + e.relGap) : null;
    return null;
  }
  function cmFigure(type, e) {
    if (type === "h2h") return e.gap.toFixed(1) + " apart a week";
    if (type === "shared") return Math.round(100 * e.agree / e.games) + "% same picks";
    if (type === "differ") return e.differ + " different picks";
    return e.relGap.toFixed(1) + " apart vs average";
  }
  function cmExplain(type, e) {
    var span = "Weeks " + state.cmFrom + "–" + state.cmTo + ".";
    if (type === "h2h") return e.a + " outscored " + e.b + " in " + plural(e.aWeeks, "week") + ", " + e.b + " won " + plural(e.bWeeks, "week") +
      (e.level ? ", " + plural(e.level, "week") + " level" : "") + ". On average their weekly scores were " + e.gap.toFixed(1) +
      " wins apart over " + plural(e.weeks, "week") + " both played. Everyone in the pool meets everyone every week, so closeness - not how often they met - is what's measured. " + span;
    if (type === "shared" || type === "differ") return "Of " + plural(e.games, "game") + " both picked, they took the same side in " + e.agree +
      " (" + Math.round(100 * e.agree / e.games) + "%) and opposite sides in " + e.differ + ". When they split, " + e.a + " was right " +
      e.aSplit + " times and " + e.b + " " + e.bSplit + ". Games where either had no pick are left out. Splitting often doesn't make either the better picker. " + span;
    return "Each week's score minus that week's pool average, compared week by week: on average their results were " + e.relGap.toFixed(1) +
      " wins apart over " + plural(e.weeks, "week") + ". Small samples: a handful of weeks can make two coaches look alike by chance. It says nothing about how they pick. " + span;
  }
  // Each coach's strongest few, joined into one set of edges to draw.
  function cmEdges(type, pairs, perCoach, focus) {
    var scored = pairs.map(function (e) { return { e: e, s: cmStrength(type, e) }; }).filter(function (x) { return x.s != null; });
    var by = {};
    scored.forEach(function (x) { (by[x.e.a] = by[x.e.a] || []).push(x); (by[x.e.b] = by[x.e.b] || []).push(x); });
    var keep = [];
    Object.keys(by).forEach(function (n) {
      if (focus && n !== focus) return;
      by[n].sort(function (p, q) { return q.s - p.s; }).slice(0, focus ? Math.max(perCoach, 8) : perCoach).forEach(function (x) {
        if (keep.indexOf(x) < 0) keep.push(x);
      });
    });
    return keep.sort(function (p, q) { return q.s - p.s; });
  }
  function cmBest(type, pairs, lowest) {
    var got = pairs.filter(function (e) { return cmStrength(type, e) != null; });
    got.sort(function (p, q) { return lowest ? cmStrength(type, p) - cmStrength(type, q) : cmStrength(type, q) - cmStrength(type, p); });
    return got[0] || null;
  }
  function mapView() {
    var weeks = cmWeeks();
    var head = el("div", { class: "pagehead" }, [el("h1", { text: "Connection Map" })]);
    if (!weeks.length || DATA.players.length < 2) return el("div", { class: "view", "data-view": "connections" }, [head,
      stateMsg("Nothing to connect yet", "The map fills in once a week's scores and picks are in.")]);
    if (!state.cmFrom || weeks.indexOf(state.cmFrom) < 0) state.cmFrom = weeks[0];
    if (!state.cmTo || weeks.indexOf(state.cmTo) < 0) state.cmTo = weeks[weeks.length - 1];
    if (state.cmFrom > state.cmTo) { var t = state.cmFrom; state.cmFrom = state.cmTo; state.cmTo = t; }
    var type = CM_TYPES[state.cmType] ? state.cmType : "shared";
    var per = state.cmPer || 2;
    var pairs = cmPairs(state.cmFrom, state.cmTo);
    var focus = state.cmFocus && player(state.cmFocus) ? state.cmFocus : "";
    var edges = cmEdges(type, pairs, per, state.cmOnly ? focus : "");
    var types = el("div", { class: "seg cm-types", role: "group", "aria-label": "Relationship type" }, Object.keys(CM_TYPES).map(function (k) {
      return el("button", { type: "button", "aria-pressed": k === type ? "true" : "false", text: CM_TYPES[k].label,
        onclick: function () { state.cmType = k; state.cmEdge = null; render(); } });
    }));
    function weekSel(label, value, set) {
      return el("label", { class: "note" }, [label + " ", el("select", { class: "filter", "aria-label": label, onchange: function (e) { set(Number(e.target.value)); state.cmEdge = null; render(); } },
        weeks.map(function (w) { return el("option", { value: w, text: "Week " + w, selected: w === value }); }))]);
    }
    var all = names().slice().sort(function (x, y) { return x.localeCompare(y); });
    var search = el("input", { class: "filter", list: "cm-names", placeholder: "Find a coach", "aria-label": "Find a coach", value: focus,
      onchange: function (e) { var v = e.target.value; if (player(v)) { state.cmFocus = v; state.cmEdge = null; render(); } } });
    var tools = el("div", { class: "cm-tools" }, [
      el("span", { class: "note", text: "Season " + seasonYear() }),
      weekSel("From", state.cmFrom, function (v) { state.cmFrom = v; }), weekSel("to", state.cmTo, function (v) { state.cmTo = v; }),
      el("label", { class: "note" }, ["Links per coach ", el("select", { class: "filter", "aria-label": "Links per coach", onchange: function (e) { state.cmPer = Number(e.target.value); render(); } },
        [1, 2, 3, 5].map(function (k) { return el("option", { value: k, text: String(k), selected: k === per }); }))]),
      search, el("datalist", { id: "cm-names" }, all.map(function (n) { return el("option", { value: n }); })),
      focus ? el("label", { class: "note cm-only" }, [el("input", { type: "checkbox", checked: state.cmOnly ? true : null,
        onchange: function (e) { state.cmOnly = e.target.checked; render(); } }), " Only " + focus + "’s links"]) : null,
      el("div", { class: "seg", role: "group", "aria-label": "Show as" }, ["Map", "List"].map(function (v) {
        return el("button", { type: "button", "aria-pressed": (state.cmList ? "List" : "Map") === v ? "true" : "false", text: v,
          onclick: function () { state.cmList = v === "List"; render(); } });
      }))
    ]);
    var body = state.cmList ? cmTable(type, edges) : cmGraph(type, edges, focus);
    return el("div", { class: "view", "data-view": "connections" }, [head,
      el("p", { class: "lede", text: "How coaches are linked by this season's picks and scores. Choose a relationship, then tap a coach or a line." }),
      types, el("p", { class: "note", text: CM_TYPES[type].about }), tools,
      el("div", { class: "cm-wrap" }, [body, cmPanel(type, pairs, edges, focus)]),
      cmDiscoveries(pairs)
    ]);
  }
  function cmGraph(type, edges, focus) {
    var people = DATA.players.slice();      // official order, so the ring reads like the table
    var W = 760, H = 760, cx = W / 2, cy = H / 2, R = 270;
    var pos = {};
    people.forEach(function (p, i) {
      var a = -Math.PI / 2 + 2 * Math.PI * i / people.length;
      pos[p.name] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), a: a };
    });
    var linked = {};
    edges.forEach(function (x) { linked[x.e.a] = linked[x.e.b] = true; });
    var view = state.cmZoom || { k: 1, x: 0, y: 0 };
    var g = svgEl("g", { transform: "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")" });
    var top = edges.length ? edges[0].s : 1, low = edges.length ? edges[edges.length - 1].s : 0;
    edges.forEach(function (x) {
      var e = x.e, p = pos[e.a], q = pos[e.b];
      var on = focus && (e.a === focus || e.b === focus);
      var chosen = state.cmEdge && state.cmEdge.a === e.a && state.cmEdge.b === e.b;
      var w = 1 + 4 * (top === low ? 1 : (x.s - low) / (top - low));
      var line = svgEl("line", { x1: p.x, y1: p.y, x2: q.x, y2: q.y, class: "cm-edge cm-" + type + (on || chosen ? " on" : "") + (focus && !on ? " dim" : ""),
        "stroke-width": w, tabindex: "0", role: "button", "aria-label": e.a + " and " + e.b + ": " + cmFigure(type, e),
        onclick: function () { state.cmEdge = { a: e.a, b: e.b }; render(); },
        onkeydown: function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); state.cmEdge = { a: e.a, b: e.b }; render(); } } },
        [svgEl("title", { text: e.a + " – " + e.b + ": " + cmFigure(type, e) })]);
      g.appendChild(line);
    });
    people.forEach(function (p) {
      var at = pos[p.name], sel = p.name === focus;
      var faded = (focus && !sel && !edges.some(function (x) { return (x.e.a === focus && x.e.b === p.name) || (x.e.b === focus && x.e.a === p.name); })) || !linked[p.name];
      var right = Math.cos(at.a) >= 0;
      var lx = cx + (R + 16) * Math.cos(at.a), ly = cy + (R + 16) * Math.sin(at.a);
      g.appendChild(svgEl("g", { class: "cm-node" + (sel ? " sel" : "") + (faded ? " faded" : "") + (isMe(p.name) ? " me" : ""), tabindex: "0", role: "button",
        "aria-label": p.name + (p.place ? ", " + ordinal(p.place) + " officially" : ""),
        onclick: function () { state.cmFocus = sel ? "" : p.name; state.cmEdge = null; render(); },
        onkeydown: function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); state.cmFocus = sel ? "" : p.name; state.cmEdge = null; render(); } } }, [
        svgEl("circle", { cx: at.x, cy: at.y, r: sel ? 13 : 10 }),
        svgEl("text", { x: lx, y: ly + 4, "text-anchor": right ? "start" : "end", class: "cm-label", text: p.name }),
        svgEl("title", { text: p.name })
      ]));
    });
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, class: "cm-svg", role: "img", "aria-label": "Connection map: " + CM_TYPES[type].label + ", " + plural(edges.length, "link") }, [g]);
    // zoom and pan move the drawing only; nothing is worked out again
    function apply() { g.setAttribute("transform", "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")"); state.cmZoom = view; }
    function zoomBy(f, ox, oy) {
      var k = Math.max(0.6, Math.min(4, view.k * f));
      ox = ox == null ? W / 2 : ox; oy = oy == null ? H / 2 : oy;
      view = { k: k, x: ox - (ox - view.x) * k / view.k, y: oy - (oy - view.y) * k / view.k };
      apply();
    }
    function toSvg(ev) { var r = svg.getBoundingClientRect(); return { x: (ev.clientX - r.left) * W / r.width, y: (ev.clientY - r.top) * H / r.height }; }
    svg.addEventListener("wheel", function (ev) { ev.preventDefault(); var p = toSvg(ev); zoomBy(ev.deltaY < 0 ? 1.15 : 1 / 1.15, p.x, p.y); }, { passive: false });
    var drag = null;
    svg.addEventListener("pointerdown", function (ev) { if (ev.target.closest && ev.target.closest(".cm-node,.cm-edge")) return; drag = { p: toSvg(ev), x: view.x, y: view.y }; svg.setPointerCapture(ev.pointerId); });
    svg.addEventListener("pointermove", function (ev) { if (!drag) return; var p = toSvg(ev); view = { k: view.k, x: drag.x + p.x - drag.p.x, y: drag.y + p.y - drag.p.y }; apply(); });
    svg.addEventListener("pointerup", function () { drag = null; });
    var zoomBar = el("div", { class: "cm-zoom", role: "group", "aria-label": "Zoom" }, [
      el("button", { class: "btn", type: "button", "aria-label": "Zoom in", text: "+", onclick: function () { zoomBy(1.25); } }),
      el("button", { class: "btn", type: "button", "aria-label": "Zoom out", text: "−", onclick: function () { zoomBy(0.8); } }),
      el("button", { class: "btn", type: "button", text: "Reset", onclick: function () { view = { k: 1, x: 0, y: 0 }; apply(); } })
    ]);
    var legend = el("p", { class: "note cm-legend" }, [el("span", { class: "cm-swatch cm-" + type }), " " + CM_TYPES[type].label + " - thicker is stronger. ",
      el("span", { class: "cm-dot" }), " a coach, in official order clockwise from the top. Faded: no link shown."]);
    return el("div", { class: "cm-graph" }, [zoomBar, svg, legend]);
  }
  function cmTable(type, edges) {
    if (!edges.length) return stateMsg("No links", "Not enough shared weeks or games in this range.");
    return scroller(el("table", { id: "cm-table" }, [
      el("caption", { class: "sr-only", text: CM_TYPES[type].label + " links" }),
      el("thead", {}, [el("tr", {}, ["Coach", "Coach", "Link", "Weeks", "Games compared", "Same", "Different"].map(function (h) { return el("th", { scope: "col", text: h }); }))]),
      el("tbody", {}, edges.map(function (x) {
        var e = x.e;
        return el("tr", {}, [el("td", {}, [who(e.a)]), el("td", {}, [who(e.b)]),
          el("td", {}, [el("button", { class: "linkish", type: "button", text: cmFigure(type, e), onclick: function () { state.cmEdge = { a: e.a, b: e.b }; state.cmList = false; render(); } })]),
          el("td", { class: "num", text: String(e.weeks) }), el("td", { class: "num", text: String(e.games) }),
          el("td", { class: "num", text: String(e.agree) }), el("td", { class: "num", text: String(e.differ) })]);
      }))
    ]));
  }
  function cmPanel(type, pairs, edges, focus) {
    var kids = [];
    var chosen = state.cmEdge ? pairs.filter(function (e) { return e.a === state.cmEdge.a && e.b === state.cmEdge.b; })[0] : null;
    if (chosen) {
      kids.push(el("h2", { text: chosen.a + " & " + chosen.b }), el("p", { text: cmExplain(type, chosen) }));
      if (type === "differ" || type === "shared") {
        var c = compare(chosen.a, chosen.b, state.cmFrom, state.cmTo), rows = [];
        c.weeks.forEach(function (w) { w.splits.forEach(function (s) { rows.push([w.week, s]); }); });
        if (rows.length) kids.push(fold("cm-splits", "The " + plural(rows.length, "split") + ", game by game", [scroller(el("table", {}, [
          el("thead", {}, [el("tr", {}, ["Week", "Game", chosen.a, chosen.b].map(function (h) { return el("th", { scope: "col", text: h }); }))]),
          el("tbody", {}, rows.map(function (r) {
            return el("tr", {}, [el("td", { class: "num", text: String(r[0]) }), el("td", { text: r[1].game }),
              el("td", { class: r[1].aOk ? "cm-right" : null, text: (r[1].aTeam || "") + (r[1].aOk ? " ✓" : "") }),
              el("td", { class: r[1].aOk ? null : "cm-right", text: (r[1].bTeam || "") + (r[1].aOk ? "" : " ✓") })]);
          }))]))]));
      }
      kids.push(el("a", { class: "more-link", href: "#vs=" + encodeURIComponent(chosen.a) + "&" + encodeURIComponent(chosen.b), text: "Full head-to-head" }));
    } else if (focus) {
      var p = player(focus);
      var mine = pairs.filter(function (e) { return (e.a === focus || e.b === focus) && cmStrength(type, e) != null; })
        .sort(function (x, y) { return cmStrength(type, y) - cmStrength(type, x); }).slice(0, 5);
      kids.push(el("h2", { text: focus }),
        el("p", { class: "note", text: (p.place ? ordinal(p.place) + " in the official standings, " : "") + plural(p.wins, "win") + "." }),
        el("p", { class: "note", text: "Strongest " + CM_TYPES[type].label.toLowerCase() + " links:" }),
        mine.length ? el("ol", { class: "cm-list" }, mine.map(function (e) {
          var other = e.a === focus ? e.b : e.a;
          return el("li", {}, [el("button", { class: "linkish", type: "button", text: other, onclick: function () { state.cmEdge = { a: e.a, b: e.b }; render(); } }), " - " + cmFigure(type, e)]);
        })) : el("p", { class: "note", text: "Not enough in this range to compare." }),
        el("div", {}, [el("button", { class: "linkish", type: "button", text: "Open " + focus + "’s page", onclick: function () { openCoach(focus); } })]));
    } else {
      kids.push(el("h2", { text: "Pick a coach or a line" }),
        el("p", { class: "note", text: "Tap a coach to see their strongest links, or a line to see how it was worked out. The List view shows the same links as a table." }));
    }
    return el("aside", { class: "cm-panel box", "aria-live": "polite" }, kids);
  }
  function cmDiscoveries(pairs) {
    var items = [];
    function add(label, e, type) { if (e) items.push(el("li", {}, [el("strong", { text: label + ": " }), e.a + " & " + e.b + " - " + cmFigure(type, e) + ". ",
      el("button", { class: "linkish", type: "button", text: "Show", onclick: function () { state.cmType = type; state.cmEdge = { a: e.a, b: e.b }; state.cmList = false; render(); } })])); }
    add("Closest rivals", cmBest("h2h", pairs), "h2h");
    add("Most alike in their picks", cmBest("shared", pairs), "shared");
    add("Most often on opposite sides", cmBest("differ", pairs), "differ");
    add("Most similar seasons", cmBest("similar", pairs), "similar");
    var notes = [el("li", { class: "note", text: "Most frequent matchups: every coach is measured against every other each week, so no pair meets more often than another." }),
      el("li", { class: "note", text: "Changes across seasons: only this season is on file, so there is nothing to compare yet." })];
    return module("What stands out", "weeks " + state.cmFrom + "–" + state.cmTo, [el("ul", { class: "cm-finds" }, items.concat(notes))]);
  }
