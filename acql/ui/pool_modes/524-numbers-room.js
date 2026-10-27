  // ---- The Numbers Room: the league's data, to explore ---------------------------------
  // Dense on purpose: sortable tables, charts that answer one question each,
  // and every worked-out figure explained. All of it reads the shared engine
  // above, over one season and one run of weeks chosen at the top.
  // The sections, grouped by the question they answer (the third item is the
  // group a section opens, shown as a small heading in the rail).
  var NR_TABS = [
    ["home", "Command center", "Overview"],
    ["coaches", "Coaches", "Coaches"], ["consistency", "Consistency"], ["distribution", "Score spread"], ["ranks", "Rank movement"], ["h2h", "Head-to-head"],
    ["picks", "Team picks", "Picks"], ["games", "NFL games"],
    ["records", "Record book", "League"], ["pools", "Side pools"],
    ["studio", "Chart studio", "Tools"], ["tables", "Data tables"], ["glossary", "Glossary"]
  ];
  // What each worked-out figure means - shown in table headings and in the glossary.
  var NR_DEFS = {
    total: ["Total", "Wins over the chosen weeks: each week's official total (games right plus Big Loser points) added up."],
    weeks: ["Weeks", "Weeks with a recorded card in the chosen run. Averages are over these, so a coach with fewer weeks is judged on fewer."],
    avg: ["Average", "Total ÷ weeks with a card."],
    vsAvg: ["vs pool", "Average of (the coach's score − that week's official pool average). Positive: better than the pool's typical card."],
    sd: ["Std dev", "Population standard deviation of the coach's weekly scores: how far a typical week sits from their own average. Lower is steadier - not the same as better."],
    abovePct: ["Above avg", "Share of weeks scoring above the pool's average."],
    best: ["Best", "Highest weekly score in the run (the week in brackets)."],
    worst: ["Worst", "Lowest weekly score in the run."],
    wins: ["Wk wins", "Weeks among the official weekly winners; a shared week counts for each."],
    pctPossible: ["% of max", "Wins ÷ the most a card could score in those weeks (games plus Big Loser picks allowed). Evens out weeks with byes."],
    bestPlace: ["Best place", "Highest place in the season standings after any week of the run."],
    atTop: ["Wks 1st", "Weeks finishing in first place in the season standings (a tie counts)."],
    vol: ["Volatility", "Average places moved per week (up or down) in the season standings. Says how much a coach moved, not why."],
    aboveRun: ["Best run", "Longest run of weeks in a row above the pool's average."],
    place: ["Place", "Season standings after the last week of the run; equal totals share a place."],
    bigLoser: ["Big Loser", "Big Loser points in the run's official weekly totals."]
  };
  function nrDef(k) { return NR_DEFS[k] ? NR_DEFS[k][1] : ""; }

  function nrView() {
    var s = lmSeasonNow();
    if (!s) return el("div", { class: "lm-body nr" }, [stateMsg("No numbers yet", "The Numbers Room opens up once a week has been graded.")]);
    var C = lmCheckpoints(s);
    if (!C.cps.length) return el("div", { class: "lm-body nr" }, [nrHead(s, C), stateMsg("Only a final table for " + s.year, "Week-by-week totals weren't archived for this season, so there is nothing to analyse week by week.")]);
    var tab = NR_TABS.some(function (t) { return t[0] === LM.nr.tab; }) ? LM.nr.tab : "home";
    LM.nr.tab = tab;
    var R = lmRange(s), st = lmStats(s, R.from, R.to), main;
    var current = !!s.current;
    switch (tab) {
      case "coaches": main = nrCoaches(s, st); break;
      case "distribution": main = nrDistribution(s, C, st); break;
      case "consistency": main = nrConsistency(s, st); break;
      case "picks": main = current ? nrPicks(s, st) : nrNoPicks(s); break;
      case "games": main = current ? nrGames(s, st) : nrNoPicks(s); break;
      case "h2h": main = nrH2H(s, st); break;
      case "ranks": main = nrRanks(s, C, st); break;
      case "records": main = nrRecords(); break;
      case "pools": main = nrPools(s, st); break;
      case "studio": main = nrStudio(s, C, st); break;
      case "tables": main = nrTables(s, C, st); break;
      case "glossary": main = nrGlossary(); break;
      default: main = nrHome(s, C, st);
    }
    return el("div", { class: "lm-body nr" }, [
      nrHead(s, C),
      el("div", { class: "nr-wrap" }, [
        el("nav", { class: "nr-rail", "aria-label": "Numbers Room sections", "data-keep-scroll": "nr-rail" }, [].concat.apply([], NR_TABS.map(function (t) {
          return [t[2] ? el("span", { class: "nr-group", "aria-hidden": "true", text: t[2] }) : null,
            el("button", { type: "button", "aria-current": t[0] === tab ? "page" : null, onclick: function () { LM.nr.tab = t[0]; lmDraw({ top: true }); }, text: t[1] })];
        }))),
        el("div", { class: "nr-main" }, [main])
      ])
    ]);
  }
  function nrHead(s, C) {
    var R = C.cps.length ? lmRange(s) : { from: 0, to: 0 };
    function wkSel(label, value, set) {
      return el("label", { class: "lm-pick" }, [el("span", { text: label }),
        el("select", { onchange: function (e) { set(Number(e.target.value)); lmDraw(); } }, C.weeks.map(function (k) {
          return el("option", { value: String(k), selected: k === value, text: "Week " + k });
        }))]);
    }
    return el("div", { class: "nr-head" }, [
      el("div", { class: "tm-when" }, [el("span", { class: "k", text: s.year + " season" }),
        el("b", { text: C.cps.length ? (R.from === R.to ? "Week " + R.from : "Weeks " + R.from + "–" + R.to) : "Final table" })]),
      lmSeasonPicker(),
      C.cps.length ? wkSel("From", R.from, function (v) { LM.sel.from = v; }) : null,
      C.cps.length ? wkSel("To", R.to, function (v) { LM.sel.to = v; }) : null,
      C.cps.length && (R.from !== C.weeks[0] || R.to !== C.last) ? el("button", { class: "lm-btn txt", type: "button", onclick: function () { LM.sel.from = LM.sel.to = 0; lmDraw(); }, text: "All weeks" }) : null,
      el("span", { class: "note nr-n", text: C.cps.length ? plural(lmStats(s, R.from, R.to).weeks.length, "week") + " · " + plural(s.standings.length, "coach", "coaches") : "" })
    ]);
  }
  function nrNoPicks(s) {
    return stateMsg("No pick-by-pick record for " + s.year, "Past seasons are archived as weekly totals only: which teams were picked wasn't kept, and isn't guessed.");
  }
  function nrCard(title, kids, aside) {
    return el("section", { class: "lm-card" }, [el("div", { class: "nr-ch" }, [el("h3", { text: title }), aside || null])].concat(kids));
  }
  function nrGoTab(tab, extra) { return function () { if (extra) Object.keys(extra).forEach(function (k) { LM.sel[k] = extra[k]; }); LM.nr.tab = tab; lmDraw({ top: true }); }; }

  // A sortable, searchable table; `cols`: {key, label, get, cell?, num?, derived?, title?}.
  function nrTable(key, cols, rows, opts) {
    opts = opts || {};
    var sort = LM.nr.sort[key] || opts.sort || { col: cols[0].key, dir: 1 };
    var col = cols.filter(function (c) { return c.key === sort.col; })[0] || cols[0];
    var q = (LM.nr.q || "").toLowerCase().trim();
    var shown = rows.filter(function (r) { return !q || !opts.search || opts.search(r).toLowerCase().indexOf(q) >= 0; });
    shown.sort(function (a, b) {
      var x = col.get(a), y = col.get(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      if (typeof x === "string" || typeof y === "string") return sort.dir * String(x).localeCompare(String(y));
      return sort.dir * (x - y);
    });
    var limit = opts.limit && !LM.nr["all-" + key] ? opts.limit : Infinity;
    var head = el("tr", {}, cols.map(function (c) {
      var on = c.key === col.key;
      return el("th", { class: c.num ? "num" : "", "aria-sort": on ? (sort.dir > 0 ? "ascending" : "descending") : null, title: c.title || nrDef(c.key) || null }, [
        el("button", { type: "button", class: "nr-sort", onclick: function () {
          LM.nr.sort[key] = { col: c.key, dir: on ? -sort.dir : (c.num ? -1 : 1) };
          lmDraw();
        } }, [c.label, c.derived ? el("sup", { title: "Worked out from official records", text: "†" }) : null, on ? (sort.dir > 0 ? " ▲" : " ▼") : ""])
      ]);
    }));
    var body = el("tbody", {}, shown.slice(0, limit).map(function (r) {
      return el("tr", { class: opts.rowClass ? opts.rowClass(r) || "" : "" }, cols.map(function (c) {
        var v = c.cell ? c.cell(r) : c.fmt ? c.fmt(r) : c.get(r);
        return el("td", { class: c.num ? "num" : "" }, [v == null ? "–" : v]);
      }));
    }));
    return el("div", { class: "nr-table" }, [
      opts.search ? el("div", { class: "nr-tools" }, [
        el("input", { type: "search", class: "nr-q", placeholder: opts.placeholder || "Search", value: LM.nr.q || "", "aria-label": "Search the table", "data-focus": "nr-q",
          oninput: function (e) { LM.nr.q = e.target.value; clearTimeout(LM.nr.qt); LM.nr.qt = setTimeout(lmDrawKeepFocus, 180); } })
      ]) : null,
      scroller(el("table", { class: "lm-table dense" }, [el("thead", {}, [head]), body])),
      el("div", { class: "nr-foot" }, [
        el("span", { class: "note", text: shown.length + " of " + plural(rows.length, "row") + (shown.length > limit ? " · first " + limit + " shown" : "") +
          (cols.some(function (c) { return c.derived; }) ? " · † worked out from official records" : "") }),
        shown.length > limit ? el("button", { class: "lm-btn txt", type: "button", onclick: function () { LM.nr["all-" + key] = true; lmDraw(); }, text: "Show all" }) : null,
        opts.csv ? el("button", { class: "lm-btn txt", type: "button", onclick: function () {
          lmDownload(opts.csv + ".csv", lmCsv(cols, shown));
        } }, [lmGlyph("down"), " CSV of these rows"]) : null
      ])
    ]);
  }
  // Redraw, keeping the typing in the search box where it was.
  function lmDrawKeepFocus() {
    var a = document.activeElement, key = a && a.getAttribute && a.getAttribute("data-focus"), at = key ? a.selectionStart : 0;
    lmDraw();
    if (key && LM.node) {
      var b = LM.node.querySelector('[data-focus="' + key + '"]');
      if (b) { b.focus({ preventScroll: true }); try { b.setSelectionRange(at, at); } catch (e) { /* not a text box */ } }
    }
  }
  function nrCoachCols(s) {
    var cols = [
      { key: "place", label: "#", num: true, derived: true, get: function (r) { return r.place; }, cell: function (r) { return lmPlace(r); } },
      { key: "name", label: "Coach", get: function (r) { return r.name; }, cell: function (r) { return nrName(r.name); } },
      { key: "total", label: "Total", num: true, derived: true, get: function (r) { return r.total; } },
      { key: "weeks", label: "Weeks", num: true, get: function (r) { return r.weeks; } },
      { key: "avg", label: "Avg", num: true, derived: true, get: function (r) { return r.avg; }, fmt: function (r) { return lmFix(r.avg, 2); } },
      { key: "vsAvg", label: "vs pool", num: true, derived: true, get: function (r) { return r.vsAvg; }, fmt: function (r) { return lmSigned(r.vsAvg, 2); } },
      { key: "sd", label: "Std dev", num: true, derived: true, get: function (r) { return r.sd; }, fmt: function (r) { return lmFix(r.sd, 2); } },
      { key: "abovePct", label: "Above avg", num: true, derived: true, get: function (r) { return r.abovePct; }, fmt: function (r) { return r.abovePct == null ? null : Math.round(r.abovePct * 100) + "%"; } },
      { key: "best", label: "Best", num: true, get: function (r) { return r.best; }, fmt: function (r) { return r.best == null ? null : r.best + " (" + r.bestWeeks.join(",") + ")"; } },
      { key: "worst", label: "Worst", num: true, get: function (r) { return r.worst; }, fmt: function (r) { return r.worst == null ? null : r.worst + " (" + r.worstWeeks.join(",") + ")"; } },
      { key: "wins", label: "Wk wins", num: true, get: function (r) { return r.wins; } },
      { key: "pctPossible", label: "% of max", num: true, derived: true, get: function (r) { return r.pctPossible; }, fmt: function (r) { return r.pctPossible == null ? null : (r.pctPossible * 100).toFixed(1) + "%"; } },
      { key: "bestPlace", label: "Best place", num: true, derived: true, get: function (r) { return r.bestPlace; } },
      { key: "atTop", label: "Wks 1st", num: true, derived: true, get: function (r) { return r.atTop; } },
      { key: "vol", label: "Volatility", num: true, derived: true, get: function (r) { return r.vol; }, fmt: function (r) { return lmFix(r.vol, 2); } },
      { key: "aboveRun", label: "Best run", num: true, derived: true, get: function (r) { return r.aboveRun; } }
    ];
    if (s.current) cols.push({ key: "bigLoser", label: "Big Loser", num: true, get: function (r) { return r.bigLoser; } });
    return cols;
  }
  function nrName(name) {
    return el("button", { type: "button", class: "lm-who" + (name === LM.sel.a ? " sel" : "") + (isMe(name) ? " me" : ""), title: "Choose " + name + " across the Numbers Room",
      onclick: function () { LM.sel.a = name; lmDraw(); }, text: name });
  }

  // ---- command center ----
  function nrHome(s, C, st) {
    var end = C.byWeek[st.to], second = end.rows.filter(function (r) { return r.place > 1; })[0];
    var full = st.rows.filter(function (r) { return r.weeks === st.weeks.length && st.weeks.length; });
    var hot = full.slice().sort(function (a, b) { return b.vsAvg - a.vsAvg; })[0];
    var steady = full.filter(function (r) { return r.sd != null; }).sort(function (a, b) { return a.sd - b.sd; })[0];
    var riser = end.rows.filter(function (r) { return r.move != null && r.move > 0; }).sort(function (a, b) { return b.move - a.move; })[0];
    var hi = st.rows.filter(function (r) { return r.best != null; }).sort(function (a, b) { return b.best - a.best; })[0];
    var rec = lmWeekRec(s, st.to) || {};
    var tiles = [
      nrTile("Leader after week " + st.to, listNames(end.leaders, 2), second ? (end.lead - second.total ? "by " + plural(end.lead - second.total, "win") + " over " + second.name : "level with " + second.name) : "", "calc", nrGoTab("ranks")),
      nrTile("Week " + st.to, end.winners.length ? listNames(end.winners, 2) + " won" : "No winner on record", end.top != null ? "top " + end.top + " · average " + lmFix(end.average, 2) : "", "official", nrGoTab("distribution", { week: st.to })),
      hot ? nrTile("Best against the pool", hot.name, lmSigned(hot.vsAvg, 2) + " wins a week vs the average", "calc", nrGoTab("consistency", { a: hot.name })) : null,
      steady ? nrTile("Steadiest weeks", steady.name, "std dev " + lmFix(steady.sd, 2) + " · avg " + lmFix(steady.avg, 2), "calc", nrGoTab("consistency", { a: steady.name })) : null,
      riser ? nrTile("Biggest climb, week " + st.to, riser.name, "up " + plural(riser.move, "place") + " to " + ordinal(riser.place), "calc", nrGoTab("ranks")) : null,
      hi ? nrTile("Best week in the run", hi.name, plural(hi.best, "win") + " in week " + hi.bestWeeks.join(", "), "official", nrGoTab("records")) : null,
      s.current && rec.suicide ? nrTile("Suicide pool", (rec.suicide.left != null ? rec.suicide.left : "?") + " still in", "after week " + st.to + (rec.suicide.killer ? " · " + rec.suicide.killer + " cost the most" : ""), "official", nrGoTab("pools")) : null,
      s.current ? (function () {
        var g = lmGames(st.from, st.to), right = 0, cards = 0;
        g.forEach(function (x) { right += x.right; cards += x.cards; });
        return cards ? nrTile("The pool's picks", Math.round(100 * right / cards) + "% right", plural(g.length, "game") + ", " + cards + " picks graded", "calc", nrGoTab("games")) : null;
      })() : null
    ];
    var trend = lmChart(200, function (width) {
      var xs = st.weeks, lines = [
        { name: "Pool average", role: "strong", label: true, values: xs.map(function (k) { return C.byWeek[k].average; }) },
        { name: "Top score", role: "ctx", label: false, values: xs.map(function (k) { return C.byWeek[k].top; }) }
      ];
      var a = lmCoach(s);
      lines.push({ name: a, role: "me", label: true, values: xs.map(function (k) { var r = C.byWeek[k].by[a]; return r ? r.score : null; }) });
      var hi2 = Math.max.apply(null, xs.map(function (k) { return C.byWeek[k].top || 0; }).concat([5]));
      var wrap = lineChart(width, lines, { xs: xs, height: 200, min: 0, max: Math.ceil(hi2 / 2) * 2 + 2, title: "Weekly scores", fmt: function (v) { return lmFix(v, v % 1 ? 1 : 0); } });
      return lmClickWeeks(wrap, width, xs, function (k) { lmGo("timemachine", { week: k }); });
    }, "Pool average by week");
    return el("div", { class: "nr-stack" }, [
      el("div", { class: "nr-tiles" }, tiles.filter(Boolean)),
      nrCard("Weekly scores across the run", [el("p", { class: "note", text: "The pool's average (official), and " + lmCoach(s) + "'s score each week. Click a week to open it in the Time Machine." }), trend]),
      nrCard("Standings after week " + st.to, [nrTable("home-top", nrCoachCols(s).slice(0, 7), st.rows, { sort: { col: "place", dir: 1 }, limit: 10, rowClass: function (r) { return r.name === LM.sel.a ? "focus" : ""; } })],
        el("button", { class: "lm-btn txt", type: "button", onclick: nrGoTab("coaches"), text: "Every coach, every column" }))
    ]);
  }
  function nrTile(k, big, small, kind, go_) {
    return el("button", { type: "button", class: "nr-tile", onclick: go_ }, [el("span", { class: "k" }, [k, " ", lmSrc(kind)]), el("b", { text: big }), el("span", { class: "note", text: small })]);
  }

  // ---- coaches ----
  function nrCoaches(s, st) {
    var full = LM.nr.fullOnly;
    var rows = full ? st.rows.filter(function (r) { return r.weeks === st.weeks.length; }) : st.rows;
    return el("div", { class: "nr-stack" }, [nrCard("Every coach over weeks " + st.from + "–" + st.to, [
      el("p", { class: "note", text: "Click a heading to sort, hover it for how it's worked out. A name chooses that coach everywhere in the Numbers Room. Coaches with fewer weeks are judged on fewer weeks." }),
      el("label", { class: "lm-check" }, [el("input", { type: "checkbox", checked: !!full, onchange: function (e) { LM.nr.fullOnly = e.target.checked; lmDraw(); } }),
        " Only coaches with a card every week (" + st.rows.filter(function (r) { return r.weeks === st.weeks.length; }).length + ")"]),
      nrTable("coaches", nrCoachCols(s), rows, { sort: { col: "place", dir: 1 }, search: function (r) { return r.name; }, placeholder: "Find a coach",
        csv: "acql-" + s.year + "-coaches-weeks-" + st.from + "-" + st.to, rowClass: function (r) { return r.name === LM.sel.a ? "focus" : isMe(r.name) ? "me" : ""; } })
    ])]);
  }

  // ---- score spread ----
  function nrDistribution(s, C, st) {
    var wk = LM.sel.week && C.byWeek[LM.sel.week] ? LM.sel.week : st.to, cp = C.byWeek[wk], a = lmCoach(s);
    var scores = cp.rows.map(function (r) { return r.score; }).filter(function (v) { return v != null; }).sort(function (x, y) { return x - y; });
    var mine = cp.by[a] ? cp.by[a].score : null;
    var below = mine == null ? 0 : scores.filter(function (v) { return v < mine; }).length;
    var same = mine == null ? 0 : scores.filter(function (v) { return v === mine; }).length - 1;
    var hist = lmChart(240, function (width) { return nrHistogram(width, scores, { mark: mine, avg: cp.average, label: "Week " + wk + " scores" }); }, "Histogram of week " + wk);
    var box = lmChart(260, function (width) { return nrBoxes(width, C, st, a, wk); }, "Every week's spread");
    return el("div", { class: "nr-stack" }, [
      nrCard("Week " + wk + ": how the pool scored", [
        el("div", { class: "lm-row-picks" }, [el("label", { class: "lm-pick" }, [el("span", { text: "Week" }),
          el("select", { onchange: function (e) { LM.sel.week = Number(e.target.value); lmDraw(); } }, C.weeks.map(function (k) { return el("option", { value: String(k), selected: k === wk, text: "Week " + k }); }))]),
          lmPicker(s, a, function (v) { LM.sel.a = v; lmDraw(); }, "Coach")]),
        hist,
        el("p", {}, mine == null ? [a + " has no card on record for week " + wk + "."] :
          [el("b", { text: a }), " scored " + mine + ": more than " + below + " of the other " + (scores.length - 1) + " cards" + (same ? ", level with " + same : "") +
            " (" + Math.round(100 * below / Math.max(1, scores.length - 1)) + "th percentile). The pool's average was " + lmFix(cp.average, 2) +
            ", the middle card " + lmFix(lmQuantile(scores, 0.5), 1) + ", the top " + cp.top + "." + (cp.most ? " The most possible: " + cp.most + "." : "")]),
        el("div", { class: "lm-links" }, [el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("timemachine", { week: wk, tab: "week" }); }, text: "Week " + wk + " in the Time Machine" }),
          s.current ? el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("broadcast", { week: wk, kind: "recap" }); }, text: "Week " + wk + " broadcast recap" }) : null])
      ], lmSrc("official")),
      nrCard("Every week's spread", [el("p", { class: "note", text: "Each box: the middle half of the pool's cards (the line inside is the median), whiskers to the lowest and highest, a gold dot for " + a + ", a diamond for the average. Click a week to look at it." }), box], lmSrc("official"))
    ]);
  }
  function nrHistogram(width, scores, opts) {
    var H = 220, padL = 34, padR = 12, padT = 14, padB = 30;
    if (!scores.length) return stateMsg("No scores in these weeks", "Choose a run of weeks with graded cards.");
    var lo = Math.min.apply(null, scores), hi = Math.max.apply(null, scores), counts = {};
    scores.forEach(function (v) { counts[v] = (counts[v] || 0) + 1; });
    var top = Math.max.apply(null, Object.keys(counts).map(function (k) { return counts[k]; }));
    var n = hi - lo + 1, bw = (width - padL - padR) / n;
    function X(v) { return padL + (v - lo) * bw; }
    function Y(c) { return H - padB - c / top * (H - padT - padB); }
    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + H, width: width, height: H, role: "img", "aria-label": opts.label + ": " + scores.length + " cards" });
    var g = svgEl("g", { class: "grid" });
    ticksFor(0, top, Math.min(4, top)).forEach(function (c) {
      g.appendChild(svgEl("line", { x1: padL, x2: width - padR, y1: Y(c), y2: Y(c) }));
      g.appendChild(svgEl("text", { x: padL - 6, y: Y(c) + 4, "text-anchor": "end", text: String(c) }));
    });
    svg.appendChild(g);
    for (var v = lo; v <= hi; v++) {
      var c = counts[v] || 0;
      // like every chart's points: the value on hover, and on focus for keyboard and touch
      var rect = svgEl("rect", { class: "nr-bar" + (v === opts.mark ? " me" : ""), x: X(v) + 2, y: Y(c), width: Math.max(1, bw - 4), height: H - padB - Y(c),
        tabindex: c ? "0" : null, "aria-label": c ? plural(c, "card") + " scored " + v : null });
      rect.appendChild(svgEl("title", { text: plural(c, "card") + " scored " + v }));
      svg.appendChild(rect);
      if (bw > 16 || v % 2 === 0) svg.appendChild(svgEl("text", { class: "ax", x: X(v) + bw / 2, y: H - 12, "text-anchor": "middle", text: String(v) }));
    }
    if (opts.avg != null) {
      var ax = X(opts.avg) + bw / 2;
      svg.appendChild(svgEl("line", { class: "nr-avg", x1: ax, x2: ax, y1: padT - 4, y2: H - padB }));
      svg.appendChild(svgEl("text", { class: "ax", x: ax + 4, y: padT + 6, text: "avg " + lmFix(opts.avg, 1) }));
    }
    svg.appendChild(svgEl("text", { class: "ax", x: width - padR, y: H - 1, "text-anchor": "end", text: "wins that week →" }));
    return svg;
  }
  function nrBoxes(width, C, st, a, wk) {
    var H = 240, padL = 34, padR = 12, padT = 12, padB = 28, cps = st.cps, n = cps.length;
    var hi = Math.max.apply(null, cps.map(function (c) { return c.top || 0; }).concat([4])) + 1;
    var lo = Math.max(0, Math.min.apply(null, cps.map(function (c) { return c.low == null ? 0 : c.low; })) - 1);
    function X(i) { return padL + (i + 0.5) * (width - padL - padR) / n; }
    function Y(v) { return H - padB - (v - lo) / (hi - lo) * (H - padT - padB); }
    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + H, width: width, height: H, role: "img", "aria-label": "Each week's scores as box plots" });
    var g = svgEl("g", { class: "grid" });
    ticksFor(lo, hi, 4).forEach(function (v) {
      g.appendChild(svgEl("line", { x1: padL, x2: width - padR, y1: Y(v), y2: Y(v) }));
      g.appendChild(svgEl("text", { x: padL - 6, y: Y(v) + 4, "text-anchor": "end", text: String(v) }));
    });
    svg.appendChild(g);
    var bw = Math.min(30, (width - padL - padR) / n * 0.5);
    cps.forEach(function (c, i) {
      var sc = c.rows.map(function (r) { return r.score; }).filter(function (v) { return v != null; }).sort(function (x, y) { return x - y; });
      if (!sc.length) return;
      var q1 = lmQuantile(sc, 0.25), q2 = lmQuantile(sc, 0.5), q3 = lmQuantile(sc, 0.75), x = X(i);
      var grp = svgEl("g", { class: "nr-box" + (c.week === wk ? " on" : ""), tabindex: "0", role: "button", "aria-label": "Week " + c.week,
        onclick: function () { LM.sel.week = c.week; lmDraw(); }, onkeydown: function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); LM.sel.week = c.week; lmDraw(); } } });
      grp.appendChild(svgEl("title", { text: "Week " + c.week + ": low " + sc[0] + ", quartiles " + lmFix(q1) + " / " + lmFix(q2) + " / " + lmFix(q3) + ", high " + sc[sc.length - 1] + ", average " + lmFix(c.average, 2) + " (" + sc.length + " cards)" }));
      grp.appendChild(svgEl("rect", { class: "hit", x: x - bw, y: padT, width: bw * 2, height: H - padT - padB }));
      grp.appendChild(svgEl("line", { class: "wh", x1: x, x2: x, y1: Y(sc[0]), y2: Y(sc[sc.length - 1]) }));
      grp.appendChild(svgEl("rect", { class: "bx", x: x - bw / 2, y: Y(q3), width: bw, height: Math.max(1, Y(q1) - Y(q3)) }));
      grp.appendChild(svgEl("line", { class: "md", x1: x - bw / 2, x2: x + bw / 2, y1: Y(q2), y2: Y(q2) }));
      if (c.average != null) grp.appendChild(svgEl("path", { class: "av", d: "M" + x + " " + (Y(c.average) - 4) + "l4 4-4 4-4-4z" }));
      var r = c.by[a];
      if (r && r.score != null) grp.appendChild(svgEl("circle", { class: "medot", cx: x + bw / 2 + 6, cy: Y(r.score), r: 4 }));
      grp.appendChild(svgEl("text", { class: "ax", x: x, y: H - 10, "text-anchor": "middle", text: String(c.week) }));
      svg.appendChild(grp);
    });
    return svg;
  }

  // ---- consistency ----
  function nrConsistency(s, st) {
    var a = lmCoach(s), b = lmRival(s, a), minW = Math.max(2, Math.ceil(st.weeks.length * 0.75));
    var pts = st.rows.filter(function (r) { return r.weeks >= minW && r.sd != null; });
    var scatter = lmChart(320, function (width) { return nrScatter(width, pts, a); }, "Average against standard deviation");
    var C = lmCheckpoints(s), xs = st.weeks;
    function rolling(name) {
      return xs.map(function (k, i) {
        var win = xs.slice(Math.max(0, i - 2), i + 1).map(function (w) { var r = C.byWeek[w].by[name]; return r ? r.score : null; }).filter(function (v) { return v != null; });
        return i >= 2 && win.length === 3 ? lmMean(win) : null;
      });
    }
    var roll = lmChart(240, function (width) {
      var poolRoll = xs.map(function (k, i) { if (i < 2) return null; return lmMean(xs.slice(i - 2, i + 1).map(function (w) { return C.byWeek[w].average; })); });
      var lines = [{ name: a, role: "me", label: true, values: rolling(a) }, { name: b, role: "strong", label: true, values: rolling(b) }, { name: "Pool", role: "ctx", label: true, values: poolRoll }];
      var hi = Math.max.apply(null, lines.map(function (l) { return Math.max.apply(null, l.values.map(function (v) { return v || 0; })); }).concat([5]));
      return lineChart(width, lines, { xs: xs, height: 240, min: 0, max: Math.ceil(hi) + 1, title: "Three-week rolling average", fmt: function (v) { return lmFix(v, 1); } });
    }, "Rolling average");
    return el("div", { class: "nr-stack" }, [
      nrCard("Good, steady, both or neither", [
        el("p", { class: "note", text: "Across: average weekly score. Up: standard deviation (how much a coach's weeks vary). Steady isn't the same as good: a low line can be steadily low. Coaches with at least " + minW + " of the " + st.weeks.length + " weeks (" + pts.length + "). Click a dot to choose that coach." }),
        el("div", { class: "lm-row-picks" }, [lmPicker(s, a, function (v) { LM.sel.a = v; lmDraw(); }, "Coach")]),
        scatter
      ], lmSrc("calc")),
      nrCard("Form: three-week rolling average", [
        el("div", { class: "lm-row-picks" }, [lmPicker(s, b, function (v) { LM.sel.b = v; lmDraw(); }, "Against")]),
        el("p", { class: "note", text: "Each point averages that week and the two before; the first two weeks have none. " + (xs.length < 3 ? "Needs three weeks." : "") }),
        roll
      ], lmSrc("calc")),
      nrCard("Streaks and spread", [nrTable("consistency", [
        { key: "name", label: "Coach", get: function (r) { return r.name; }, cell: function (r) { return nrName(r.name); } },
        { key: "weeks", label: "Weeks", num: true, get: function (r) { return r.weeks; } },
        { key: "avg", label: "Avg", num: true, derived: true, get: function (r) { return r.avg; }, fmt: function (r) { return lmFix(r.avg, 2); } },
        { key: "sd", label: "Std dev", num: true, derived: true, get: function (r) { return r.sd; }, fmt: function (r) { return lmFix(r.sd, 2); } },
        { key: "abovePct", label: "Above avg", num: true, derived: true, get: function (r) { return r.abovePct; }, fmt: function (r) { return r.abovePct == null ? null : Math.round(r.abovePct * 100) + "%"; } },
        { key: "aboveRun", label: "Best run", num: true, derived: true, get: function (r) { return r.aboveRun; } },
        { key: "range", label: "Best−worst", num: true, derived: true, title: "Gap between the coach's best and worst week.", get: function (r) { return r.best == null ? null : r.best - r.worst; } }
      ], st.rows, { sort: { col: "sd", dir: 1 }, search: function (r) { return r.name; }, csv: "acql-" + s.year + "-consistency", rowClass: function (r) { return r.name === a ? "focus" : ""; } })])
    ]);
  }
  function nrScatter(width, pts, focus) {
    var H = width < 520 ? 280 : 320, padL = 40, padR = 16, padT = 14, padB = 34;
    if (!pts.length) return stateMsg("Not enough weeks yet", "Each coach needs two graded weeks in the run to be placed here.");
    var xs = pts.map(function (r) { return r.avg; }), ys = pts.map(function (r) { return r.sd; });
    var x0 = Math.floor(Math.min.apply(null, xs) - 0.3), x1 = Math.ceil(Math.max.apply(null, xs) + 0.3);
    var y0 = Math.max(0, Math.floor(Math.min.apply(null, ys) - 0.3)), y1 = Math.ceil(Math.max.apply(null, ys) + 0.3);
    function X(v) { return padL + (v - x0) / (x1 - x0) * (width - padL - padR); }
    function Y(v) { return H - padB - (v - y0) / (y1 - y0) * (H - padT - padB); }
    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + H, width: width, height: H, role: "img", "aria-label": "Each coach's average against their standard deviation" });
    var g = svgEl("g", { class: "grid" });
    ticksFor(y0, y1, 4).forEach(function (v) { g.appendChild(svgEl("line", { x1: padL, x2: width - padR, y1: Y(v), y2: Y(v) })); g.appendChild(svgEl("text", { x: padL - 6, y: Y(v) + 4, "text-anchor": "end", text: String(v) })); });
    ticksFor(x0, x1, 5).forEach(function (v) { g.appendChild(svgEl("text", { x: X(v), y: H - 16, "text-anchor": "middle", text: String(v) })); });
    svg.appendChild(g);
    var mx = lmQuantile(xs.slice().sort(function (a, b) { return a - b; }), 0.5), my = lmQuantile(ys.slice().sort(function (a, b) { return a - b; }), 0.5);
    svg.appendChild(svgEl("line", { class: "nr-mid", x1: X(mx), x2: X(mx), y1: padT, y2: H - padB }));
    svg.appendChild(svgEl("line", { class: "nr-mid", x1: padL, x2: width - padR, y1: Y(my), y2: Y(my) }));
    svg.appendChild(svgEl("text", { class: "ax", x: width - padR, y: H - 2, "text-anchor": "end", text: "average weekly score →" }));
    svg.appendChild(svgEl("text", { class: "ax", x: padL + 4, y: padT + 2, text: "↑ more up and down" }));
    pts.slice().sort(function (a, b) { return (a.name === focus) - (b.name === focus); }).forEach(function (r) {
      var on = r.name === focus;
      var c = svgEl("circle", { class: "nr-dot" + (on ? " me" : isMe(r.name) ? " mine" : ""), cx: X(r.avg), cy: Y(r.sd), r: on ? 7 : 5, tabindex: "0", role: "button",
        "aria-label": r.name + ": average " + lmFix(r.avg, 2) + ", std dev " + lmFix(r.sd, 2),
        onclick: function () { LM.sel.a = r.name; lmDraw(); }, onkeydown: function (e) { if (e.key === "Enter") { LM.sel.a = r.name; lmDraw(); } } });
      c.appendChild(svgEl("title", { text: r.name + " - average " + lmFix(r.avg, 2) + ", std dev " + lmFix(r.sd, 2) + " over " + plural(r.weeks, "week") }));
      svg.appendChild(c);
      if (on) svg.appendChild(svgEl("text", { class: "lbl me", x: X(r.avg) + 10, y: Y(r.sd) + 4, text: r.name }));
    });
    return svg;
  }

  // ---- team picks ----
  function nrPicks(s, st) {
    var T = lmTeamPicks(st.from, st.to), order = lmCheckpoints(s).byWeek[st.to].rows.map(function (r) { return r.name; });
    var teams = Object.keys(T.teams).sort();
    if (!teams.length) return nrCard("Team picks", [el("p", { class: "note", text: "No graded picks in these weeks." })]);
    var max = 0;
    order.forEach(function (n) { teams.forEach(function (t) { var c = (T.cells[n] || {})[t]; if (c && c.n > max) max = c.n; }); });
    var a = lmCoach(s);
    var heat = el("table", { class: "nr-heat", "aria-label": "Times each coach picked each team" }, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Coach" })].concat(teams.map(function (t) { return el("th", { class: "rot", title: t }, [el("span", { text: codeOf(t) ? codeOf(t).toUpperCase() : t.slice(0, 3) })]); })))]),
      el("tbody", {}, order.map(function (n) {
        return el("tr", { class: n === a ? "focus" : "" }, [el("th", {}, [nrName(n)])].concat(teams.map(function (t) {
          var c = (T.cells[n] || {})[t], k = c ? c.n / max : 0;
          return el("td", { style: c ? "--k:" + k.toFixed(2) : null, title: c ? n + " picked " + t + " " + plural(c.n, "time") + ", right " + c.ok : n + " never picked " + t, text: c ? String(c.n) : "" });
        })));
      }))]);
    var fav = Object.keys(T.fav).map(function (n) { var f = T.fav[n]; return { name: n, f: f }; });
    return el("div", { class: "nr-stack" }, [
      nrCard("Who picks whom", [el("p", { class: "note", text: "Times each coach took each team in the graded games of weeks " + st.from + "–" + st.to + " (darker: more). Read from the pick sheets' graded cards; a game with no recorded card is left out, never guessed." }),
        scroller(heat)], lmSrc("official")),
      nrCard("Teams: how the pool's picks went", [nrTable("teams", [
        { key: "team", label: "Team", get: function (r) { return r.team; }, cell: function (r) { return teamTag ? teamTag(r.team) : r.team; } },
        { key: "n", label: "Times picked", num: true, get: function (r) { return r.n; } },
        { key: "ok", label: "Right", num: true, get: function (r) { return r.ok; } },
        { key: "pct", label: "Right %", num: true, derived: true, get: function (r) { return r.ok / r.n; }, fmt: function (r) { return Math.round(100 * r.ok / r.n) + "%"; } }
      ], teams.map(function (t) { return { team: t, n: T.teams[t].n, ok: T.teams[t].ok }; }), { sort: { col: "n", dir: -1 }, search: function (r) { return r.team; }, placeholder: "Find a team", csv: "acql-" + s.year + "-team-picks" })]),
      nrCard("Favourites or underdogs", [el("p", { class: "note", text: "Only games with an archived betting favourite count (the line as kept with the week's results). How often each coach sided with the favourite, and how each kind of pick went. Descriptive only - it says nothing about skill." }),
        nrTable("fav", [
          { key: "name", label: "Coach", get: function (r) { return r.name; }, cell: function (r) { return nrName(r.name); } },
          { key: "games", label: "Games", num: true, get: function (r) { return r.f.games; } },
          { key: "favPct", label: "Took fav.", num: true, derived: true, get: function (r) { return r.f.fav / r.f.games; }, fmt: function (r) { return Math.round(100 * r.f.fav / r.f.games) + "%"; } },
          { key: "favOk", label: "Fav. right", num: true, derived: true, get: function (r) { return r.f.fav ? r.f.favOk / r.f.fav : null; }, fmt: function (r) { return r.f.fav ? Math.round(100 * r.f.favOk / r.f.fav) + "% of " + r.f.fav : null; } },
          { key: "dogOk", label: "Dog right", num: true, derived: true, get: function (r) { return r.f.dog ? r.f.dogOk / r.f.dog : null; }, fmt: function (r) { return r.f.dog ? Math.round(100 * r.f.dogOk / r.f.dog) + "% of " + r.f.dog : null; } }
        ], fav, { sort: { col: "favPct", dir: -1 }, search: function (r) { return r.name; }, csv: "acql-" + s.year + "-favourites" })], lmSrc("calc"))
    ]);
  }

  // ---- NFL games ----
  function nrGames(s, st) {
    var games = lmGames(st.from, st.to);
    var divided = games.slice().sort(function (a, b) { return b.split - a.split; }).slice(0, 5);
    var costly = games.slice().sort(function (a, b) { return a.pct - b.pct; }).slice(0, 5);
    function gameLine(g) {
      return el("li", {}, [el("button", { type: "button", class: "lm-wk", onclick: function () { lmClose(false); state.week = g.week; go("weeks"); }, text: "Wk " + g.week }),
        " " + g.matchup + " - " + g.winner + " won; " + g.right + " of " + g.cards + " cards right"]);
    }
    return el("div", { class: "nr-stack" }, [
      el("div", { class: "cols even" }, [
        nrCard("Split the pool most", [el("ul", { class: "lm-list" }, divided.map(gameLine))], lmSrc("calc")),
        nrCard("Fewest cards right", [el("ul", { class: "lm-list" }, costly.map(gameLine))], lmSrc("calc"))
      ]),
      nrCard("Every graded game", [el("p", { class: "note", text: "Results and pool lines as the week's recap records them; the betting favourite and spread where archived. A week links to its page on the site." }),
        nrTable("games", [
          { key: "week", label: "Wk", num: true, get: function (r) { return r.week; }, cell: function (r) { return el("button", { type: "button", class: "lm-wk", onclick: function () { lmClose(false); state.week = r.week; go("weeks"); }, text: String(r.week) }); } },
          { key: "matchup", label: "Game", get: function (r) { return r.matchup; } },
          { key: "winner", label: "Winner", get: function (r) { return r.winner; } },
          { key: "fav", label: "Bet fav.", get: function (r) { return r.fav ? r.fav + (r.spread != null ? " −" + r.spread : "") : null; } },
          { key: "upset", label: "Upset", get: function (r) { return r.fav ? (r.upset ? "yes" : "no") : null; } },
          { key: "cards", label: "Cards", num: true, get: function (r) { return r.cards; } },
          { key: "right", label: "Right", num: true, get: function (r) { return r.right; } },
          { key: "pct", label: "Right %", num: true, derived: true, get: function (r) { return r.pct; }, fmt: function (r) { return r.pct == null ? null : Math.round(r.pct * 100) + "%"; } }
        ], games, { sort: { col: "week", dir: 1 }, search: function (r) { return r.matchup + " " + r.winner; }, placeholder: "Find a team", csv: "acql-" + s.year + "-games-weeks-" + st.from + "-" + st.to })])
    ]);
  }

  // ---- head-to-head ----
  function nrH2H(s, st) {
    var a = lmCoach(s), b = lmRival(s, a), v = lmVs(s, a, b, st.from, st.to), ra = st.by[a], rb = st.by[b], C = lmCheckpoints(s);
    var xs = st.weeks;
    var gapChart = lmChart(220, function (width) {
      var vals = xs.map(function (k) { var x = C.byWeek[k].by[a], y = C.byWeek[k].by[b]; return x && y ? x.total - y.total : null; });
      var lo = Math.min.apply(null, vals.concat([0])), hi = Math.max.apply(null, vals.concat([0]));
      var pad = Math.max(2, (hi - lo) * 0.1);
      var wrap = lineChart(width, [{ name: a + " vs " + b, role: "me", label: true, values: vals }], { xs: xs, height: 220, min: Math.floor(lo - pad), max: Math.ceil(hi + pad), zero: true,
        title: "Season total gap", fmt: function (v) { return v > 0 ? "+" + Math.round(v) : String(Math.round(v)); } });
      return lmClickWeeks(wrap, width, xs, function (k) { lmGo("timemachine", { week: k }); });
    }, "Gap between the two");
    function line(k, x, y, fmt) {
      return el("tr", {}, [el("td", { class: "num", text: fmt(x) }), el("th", { text: k, title: nrDef(k === "Average" ? "avg" : k === "Std dev" ? "sd" : "") }), el("td", { class: "num", text: fmt(y) })]);
    }
    return el("div", { class: "nr-stack" }, [
      nrCard("Head-to-head, weeks " + st.from + "–" + st.to, [
        el("div", { class: "lm-row-picks" }, [lmPicker(s, a, function (x) { LM.sel.a = x; lmDraw(); }, "Coach"), lmPicker(s, b, function (x) { LM.sel.b = x; lmDraw(); }, "against")]),
        el("div", { class: "nr-vs" }, [
          el("div", { class: "side" }, [el("b", { text: a }), el("span", { class: "big", text: String(v.aw) })]),
          el("div", { class: "mid" }, [el("span", { text: "weeks outscored" }), v.ties ? el("span", { class: "note", text: plural(v.ties, "week") + " level" }) : null]),
          el("div", { class: "side" }, [el("b", { text: b }), el("span", { class: "big", text: String(v.bw) })])
        ]),
        ra && rb ? el("table", { class: "lm-table nr-tale" }, [el("tbody", {}, [
          line("Place now", ra, rb, function (r) { return lmPlace(r); }),
          line("Total", ra, rb, function (r) { return String(r.total); }),
          line("Average", ra, rb, function (r) { return lmFix(r.avg, 2); }),
          line("Std dev", ra, rb, function (r) { return lmFix(r.sd, 2); }),
          line("Weekly wins", ra, rb, function (r) { return String(r.wins); }),
          line("Best week", ra, rb, function (r) { return r.best == null ? "–" : String(r.best); }),
          line("Weeks in 1st", ra, rb, function (r) { return String(r.atTop); })
        ])]) : null,
        v.shared ? el("p", {}, ["Same side in ", el("b", { text: v.shared.same + " of " + v.shared.games }), " graded games (" + (v.shared.games ? Math.round(100 * v.shared.same / v.shared.games) : 0) + "%)."]) : el("p", { class: "note", text: "Picks weren't archived for this season, so shared picks can't be counted." }),
        el("div", { class: "lm-links" }, [s.current && DATA.weeks.some(function (w) { return w.picks; }) ? el("a", { class: "lm-link", href: "#vs=" + encodeURIComponent(a) + "&" + encodeURIComponent(b),
          onclick: function (e) { e.preventDefault(); lmClose(false); setPair(a, b); go("h2h"); }, text: "Pick by pick on the site" }) : null])
      ], lmSrc("calc")),
      nrCard("Season total gap (" + a + " minus " + b + ")", [el("p", { class: "note", text: "Above the line, " + a + " is ahead on the season. Click a week to open it in the Time Machine. Every week's scores and the games they split are on the site's head-to-head page." }), gapChart])
    ]);
  }

  // ---- rank movement ----
  function nrRanks(s, C, st) {
    var a = lmCoach(s), end = C.byWeek[st.to], xs = st.weeks;
    var weekly = st.cps.filter(function (c) { return c.rows.some(function (r) { return r.move != null; }); }).map(function (c) {
      var mv = c.rows.filter(function (r) { return r.move != null; });
      var up = Math.max.apply(null, mv.map(function (r) { return r.move; })), dn = Math.min.apply(null, mv.map(function (r) { return r.move; }));
      return { week: c.week, up: up, upWho: mv.filter(function (r) { return r.move === up; }).map(function (r) { return r.name; }),
        dn: dn, dnWho: mv.filter(function (r) { return r.move === dn; }).map(function (r) { return r.name; }), leaders: c.leaders };
    });
    var changes = lmEvents(s).filter(function (e) { return e.kind === "lead" && e.week >= st.from && e.week <= st.to; });
    var matrix = el("table", { class: "nr-matrix", "aria-label": "Each coach's place after each week" }, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Coach" })].concat(xs.map(function (k) { return el("th", { text: "W" + k }); })))]),
      el("tbody", {}, end.rows.map(function (r0) {
        return el("tr", { class: r0.name === a ? "focus" : "" }, [el("th", {}, [nrName(r0.name)])].concat(xs.map(function (k) {
          var r = C.byWeek[k].by[r0.name];
          if (!r) return el("td", { text: "" });
          var cls = r.move == null ? "" : r.move > 0 ? "up" : r.move < 0 ? "dn" : "";
          return el("td", { class: cls + (r.place === 1 ? " top" : ""), style: r.move ? "--k:" + Math.min(1, Math.abs(r.move) / 8).toFixed(2) : null,
            title: r0.name + " after week " + k + ": " + ordinal(r.place) + (r.tied ? " (tied)" : "") + (r.move ? ", " + (r.move > 0 ? "up " : "down ") + Math.abs(r.move) : ""), text: lmPlace(r) });
        })));
      }))]);
    return el("div", { class: "nr-stack" }, [
      el("div", { class: "cols even" }, [
        nrCard("Biggest climb and drop each week", [nrTable("movers", [
          { key: "week", label: "Wk", num: true, get: function (r) { return r.week; } },
          { key: "up", label: "Climb", num: true, get: function (r) { return r.up; }, fmt: function (r) { return r.up > 0 ? "+" + r.up + " " + listNames(r.upWho, 2) : "–"; } },
          { key: "dn", label: "Drop", num: true, get: function (r) { return r.dn; }, fmt: function (r) { return r.dn < 0 ? "−" + Math.abs(r.dn) + " " + listNames(r.dnWho, 2) : "–"; } }
        ], weekly, { sort: { col: "week", dir: 1 } })], lmSrc("calc")),
        nrCard("Time at the top", [nrTable("attop", [
          { key: "name", label: "Coach", get: function (r) { return r.name; }, cell: function (r) { return nrName(r.name); } },
          { key: "atTop", label: "Weeks 1st", num: true, derived: true, get: function (r) { return r.atTop; } },
          { key: "topRun", label: "Longest spell", num: true, derived: true, get: function (r) { return r.topRun; } },
          { key: "vol", label: "Volatility", num: true, derived: true, get: function (r) { return r.vol; }, fmt: function (r) { return lmFix(r.vol, 2); } }
        ], st.rows.filter(function (r) { return r.atTop; }), { sort: { col: "atTop", dir: -1 } }),
        el("p", { class: "note", text: plural(changes.length, "change") + " at the top in these weeks" + (changes.length ? ": " + changes.map(function (e) { return "wk " + e.week + " " + listNames(e.who, 2); }).join(" · ") : "") + "." })], lmSrc("calc"))
      ]),
      el("div", { class: "lm-links" }, [el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("timemachine", { tab: "race" }); },
        text: "Places as a chart: the title race in the Time Machine" })]),
      nrCard("The movement matrix", [el("p", { class: "note", text: "Each coach's place after each week, shaded green for a climb and red for a drop that week (stronger: more places). It shows what moved, not which game moved it." }), scroller(matrix)], lmSrc("calc"))
    ]);
  }

  // ---- record book ----
  function nrRecords() {
    var recs = lmRecords(), seasons = lmSeasons();
    var champs = typeof championsByYear === "function" ? championsByYear(seasons) : {};
    var titles = {};
    Object.keys(champs).forEach(function (y) { splitNames(champs[y].names).forEach(function (n) { (titles[n] = titles[n] || []).push(y); }); });
    var holders = Object.keys(titles).sort(function (x, y) { return titles[y].length - titles[x].length; });
    return el("div", { class: "nr-stack" }, [
      nrCard("The record book", [el("p", { class: "note", text: "Across " + plural(seasons.length, "season") + " on record (" + seasons.map(function (s) { return s.year + (s.current ? " so far" : ""); }).join(", ") +
        "). Only records the archive can support; each names its week and coach - click one to travel there." }),
        el("div", { class: "nr-records" }, recs.map(function (r) {
          return el("div", { class: "nr-rec" }, [
            el("span", { class: "k" }, [r.label, " ", lmSrc(r.kind)]),
            el("b", { text: (r.id === "margin" ? "+" + lmFix(r.value, 2) : r.value) + " " + lmUnit(r.value, r.unit) }),
            el("div", { class: "who" }, r.holders.slice(0, 4).map(function (h) {
              return el("button", { type: "button", class: "lm-wk", title: "Open in the Time Machine", onclick: function () {
                lmGo("timemachine", { season: String(h.year), week: h.week || 0, a: h.name, tab: h.week ? "standings" : "coach" });
              }, text: h.name + " · " + h.year + (h.week ? " wk " + h.week : "") });
            }).concat(r.holders.length > 4 ? [el("span", { class: "note", text: "+" + (r.holders.length - 4) + " more" })] : [])),
            el("span", { class: "note", text: r.calc })
          ]);
        }))]),
      nrCard("Championships", [holders.length ? el("ul", { class: "lm-list" }, holders.map(function (n) { return el("li", { text: n + ": " + titles[n].join(", ") }); }))
        : el("p", { class: "note", text: "No champion on record yet: titles appear when a season finishes or one is typed into the dashboard's champions list." })], lmSrc("official"))
    ]);
  }

  // ---- side pools ----
  function nrPools(s, st) {
    if (!s.current) {
      var out = (s.standings || []).filter(function (x) { return x.suicide_out; }).sort(function (a, b) { return a.suicide_out - b.suicide_out; });
      return nrCard("Side pools in " + s.year, [el("p", { class: "note", text: "The archive keeps when each coach went out of the suicide pool, and the Big Loser totals." }),
        nrTable("arch-pools", [
          { key: "name", label: "Coach", get: function (r) { return r.name; } },
          { key: "out", label: "Suicide: out in week", num: true, get: function (r) { return r.suicide_out || null; } },
          { key: "bl", label: "Big Loser", num: true, get: function (r) { return r.big_loser; } }
        ], s.standings, { sort: { col: "bl", dir: -1 } })], lmSrc("official"));
    }
    var weeks = st.cps.map(function (c) { var w = weekData(c.week) || {}; return { week: c.week, su: w.suicide || {}, bl: (w.scores || []).filter(function (x) { return x.big_loser; }) }; });
    var surv = lmChart(200, function (width) {
      var xs = weeks.map(function (w) { return w.week; });
      return lineChart(width, [{ name: "Still in", role: "me", label: true, values: weeks.map(function (w) { return w.su.left != null ? w.su.left : null; }) }],
        { xs: xs, height: 200, min: 0, max: niceMax(Math.max.apply(null, weeks.map(function (w) { return w.su.left || 0; }).concat([5]))), title: "Suicide pool survivors", fmt: function (v) { return String(Math.round(v)); } });
    }, "Survivors by week");
    var rounds = DATA.suicide_rounds || [];
    return el("div", { class: "nr-stack" }, [
      el("div", { class: "cols even" }, [
        nrCard("Suicide pool", [el("p", { class: "note", text: "Coaches still in after each week, as each week's recap records it. Each restart of the pool is its own round." }), surv,
          el("ul", { class: "lm-list" }, weeks.filter(function (w) { return w.su.killed; }).map(function (w) {
            return el("li", { text: "Week " + w.week + ": " + plural(w.su.killed, "coach", "coaches") + " out" + (w.su.killer ? ", most on " + w.su.killer : "") + (w.su.left != null ? " · " + w.su.left + " left" : "") });
          })),
          rounds.length ? el("p", { class: "note", text: "Finished rounds: " + rounds.map(function (r) { return "weeks " + r.start + "–" + r.end + (r.winners && r.winners.length ? " won by " + listNames(r.winners, 2) : ""); }).join("; ") + "." }) : null,
          el("p", {}, [plural(aliveNames().length, "coach", "coaches") + " alive now: ", listNames(aliveNames(), 6) || "none"])
        ], lmSrc("official")),
        nrCard("Big Loser", [el("p", { class: "note", text: "Points from Big Loser picks, as the official weekly totals record them. The season column is the pool's own running total." }),
          nrTable("bigloser", [
            { key: "name", label: "Coach", get: function (r) { return r.name; }, cell: function (r) { return nrName(r.name); } },
            { key: "run", label: "Wks " + st.from + "–" + st.to, num: true, get: function (r) { return st.by[r.name] ? st.by[r.name].bigLoser : null; } },
            { key: "season", label: "Season", num: true, get: function (r) { return r.big_loser; } }
          ], DATA.players, { sort: { col: "season", dir: -1 }, limit: 12, csv: "acql-" + s.year + "-big-loser" })], lmSrc("official"))
      ]),
      el("div", { class: "lm-links" }, [el("button", { class: "lm-link", type: "button", onclick: function () { lmClose(false); go("pools"); }, text: "The side pools page on the site" })])
    ]);
  }

  // ---- chart studio ----
  // Only pairings the data can honestly draw: a measure over the weeks is a
  // line; one week's measure across coaches is bars or a histogram; two
  // per-coach measures against each other are a scatter.
  var NR_SETS = {
    score: { label: "Weekly score", unit: "wins", kinds: ["line", "bar", "hist"], kind: "official", get: function (r) { return r.score; } },
    total: { label: "Season total", unit: "wins", kinds: ["line", "bar"], kind: "calc", get: function (r) { return r.total; } },
    place: { label: "Season place", unit: "place", kinds: ["line"], kind: "calc", get: function (r) { return r.place; }, invert: true },
    behind: { label: "Wins behind the leader", unit: "wins", kinds: ["line", "bar"], kind: "calc", get: function (r) { return r.behind; }, invert: true },
    vsAvg: { label: "Score vs pool average", unit: "wins", kinds: ["line", "bar"], kind: "calc", get: function (r) { return r.vsAvg; } },
    avgsd: { label: "Average vs consistency (per coach)", unit: "", kinds: ["scatter"], kind: "calc" }
  };
  var NR_KINDS = { line: "Line over weeks", bar: "Bars across coaches (one week)", hist: "Histogram (one week)", scatter: "Scatter" };
  function nrStudio(s, C, st) {
    var S = LM.nr.studio;
    var set = NR_SETS[S.set] ? S.set : "score", def = NR_SETS[set];
    var kind = def.kinds.indexOf(S.kind) >= 0 ? S.kind : def.kinds[0];
    S.set = set; S.kind = kind;
    var wk = S.week && C.byWeek[S.week] && st.weeks.indexOf(S.week) >= 0 ? S.week : st.to;
    var end = C.byWeek[st.to];
    if (!S.on || !S.on.length) S.on = end.rows.slice(0, 4).map(function (r) { return r.name; }).concat(LM.sel.a && end.by[LM.sel.a] && end.rows.slice(0, 4).every(function (r) { return r.name !== LM.sel.a; }) ? [LM.sel.a] : []);
    var on = S.on.filter(function (n) { return end.by[n]; });
    var controls = el("div", { class: "nr-studio-ctl" }, [
      el("label", { class: "lm-pick" }, [el("span", { text: "Data" }), el("select", { onchange: function (e) { S.set = e.target.value; lmDraw(); } },
        Object.keys(NR_SETS).map(function (k) { return el("option", { value: k, selected: k === set, text: NR_SETS[k].label }); }))]),
      el("label", { class: "lm-pick" }, [el("span", { text: "Chart" }), el("select", { onchange: function (e) { S.kind = e.target.value; lmDraw(); } },
        def.kinds.map(function (k) { return el("option", { value: k, selected: k === kind, text: NR_KINDS[k] }); }))]),
      kind === "bar" || kind === "hist" ? el("label", { class: "lm-pick" }, [el("span", { text: "Week" }), el("select", { onchange: function (e) { S.week = Number(e.target.value); lmDraw(); } },
        st.weeks.map(function (k) { return el("option", { value: String(k), selected: k === wk, text: "Week " + k }); }))]) : null,
      kind === "line" ? el("label", { class: "lm-pick" }, [el("span", { text: "Add a coach" }), el("select", { onchange: function (e) { if (e.target.value && on.indexOf(e.target.value) < 0) S.on = on.concat([e.target.value]); lmDraw(); } },
        [el("option", { value: "", text: "Choose…" })].concat(end.rows.filter(function (r) { return on.indexOf(r.name) < 0; }).map(function (r) { return el("option", { value: r.name, text: r.name }); })))]) : null
    ]);
    var chips = kind === "line" ? el("div", { class: "lm-chips" }, on.map(function (n) {
      return el("button", { type: "button", class: "lm-chipbtn", "aria-pressed": "true", title: "Take " + n + " off the chart", onclick: function () { S.on = on.filter(function (x) { return x !== n; }); if (!S.on.length) S.on = [n]; lmDraw(); } }, [n, " ×"]);
    })) : null;
    var n = 0, chart;
    if (kind === "line") {
      var xs = st.weeks;
      chart = lmChart(300, function (width) {
        var lines = on.map(function (name, i) { return { name: name, role: name === LM.sel.a || (!LM.sel.a && i === 0) ? "me" : "strong", label: true,
          values: xs.map(function (k) { var r = C.byWeek[k].by[name]; return r ? def.get(r) : null; }) }; });
        var all = lines.reduce(function (acc, l) { return acc.concat(l.values.filter(function (v) { return v != null; })); }, []);
        var lo = Math.min.apply(null, all.concat([0])), hi = Math.max.apply(null, all.concat([1]));
        var opts = { xs: xs, height: 300, min: set === "place" ? 1 : Math.floor(lo), max: set === "place" ? end.rows.length : Math.ceil(hi + (hi - lo) * 0.08), invert: !!def.invert,
          zero: set === "vsAvg", title: def.label, fmt: function (v) { return set === "place" ? ordinal(Math.round(v)) : set === "vsAvg" ? lmSigned(v, 1) : lmFix(v, v % 1 ? 1 : 0); } };
        var wrap = lineChart(width, lines, opts);
        return lmClickWeeks(wrap, width, xs, function (k) { lmGo("timemachine", { week: k }); });
      }, def.label);
      on.forEach(function (name) { xs.forEach(function (k) { var r = C.byWeek[k].by[name]; if (r && def.get(r) != null) n++; }); });
    } else if (kind === "bar") {
      var rows = C.byWeek[wk].rows.filter(function (r) { return def.get(r) != null; }).sort(function (x, y) { return def.invert ? def.get(x) - def.get(y) : def.get(y) - def.get(x); });
      n = rows.length;
      chart = lmChart(rows.length * 22 + 30, function (width) { return nrBars(width, rows.map(function (r) { return { name: r.name, v: def.get(r) }; }), set === "vsAvg" ? function (v) { return lmSigned(v, 1); } : function (v) { return String(v); }); }, def.label);
    } else if (kind === "hist") {
      var sc = C.byWeek[wk].rows.map(function (r) { return r.score; }).filter(function (v) { return v != null; }).sort(function (x, y) { return x - y; });
      n = sc.length;
      chart = lmChart(240, function (width) { var me = C.byWeek[wk].by[lmCoach(s)]; return nrHistogram(width, sc, { mark: me ? me.score : null, avg: C.byWeek[wk].average, label: "Week " + wk }); }, "Histogram");
    } else {
      var pts = st.rows.filter(function (r) { return r.sd != null; });
      n = pts.length;
      chart = lmChart(320, function (width) { return nrScatter(width, pts, lmCoach(s)); }, "Scatter");
    }
    return el("div", { class: "nr-stack" }, [nrCard("Chart studio", [
      el("p", { class: "note", text: "Pick the data, then one of the charts that suits it - the choices only offer pairings the data can honestly draw. Weeks follow the From/To at the top." }),
      controls, chips, chart,
      el("p", { class: "note" }, [lmSrc(def.kind), " " + def.label + (def.unit ? " (" + def.unit + ")" : "") + " · " + plural(n, "data point") +
        (kind === "line" ? " · " + plural(on.length, "coach", "coaches") + " over " + plural(st.weeks.length, "week") : kind === "scatter" ? " · coaches with 2+ weeks" : " · week " + wk)])
    ])]);
  }
  function nrBars(width, rows, fmt) {
    var rowH = 22, H = rows.length * rowH + 24, padL = Math.min(170, width * 0.38), padR = 44;
    var vals = rows.map(function (r) { return r.v; }), lo = Math.min.apply(null, vals.concat([0])), hi = Math.max.apply(null, vals.concat([0]));
    if (hi === lo) hi = lo + 1;
    function X(v) { return padL + (v - lo) / (hi - lo) * (width - padL - padR); }
    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + H, width: width, height: H, role: "img", "aria-label": "Bar chart, " + rows.length + " coaches" });
    svg.appendChild(svgEl("line", { class: "nr-mid", x1: X(0), x2: X(0), y1: 0, y2: H - 20 }));
    rows.forEach(function (r, i) {
      var y = i * rowH + 3, on = r.name === LM.sel.a;
      svg.appendChild(svgEl("text", { class: "ax" + (on ? " me" : ""), x: padL - 8, y: y + 13, "text-anchor": "end", text: r.name.length > 22 ? r.name.slice(0, 21) + "…" : r.name }));
      var x0 = X(Math.min(0, r.v)), x1 = X(Math.max(0, r.v));
      var rect = svgEl("rect", { class: "nr-bar" + (on ? " me" : ""), x: x0, y: y, width: Math.max(1, x1 - x0), height: rowH - 6, tabindex: "0", "aria-label": r.name + ": " + fmt(r.v) });
      rect.appendChild(svgEl("title", { text: r.name + ": " + fmt(r.v) }));
      svg.appendChild(rect);
      svg.appendChild(svgEl("text", { class: "ax", x: x1 + 4, y: y + 13, text: fmt(r.v) }));
    });
    return svg;
  }

  // ---- data tables ----
  var NR_DATASETS = {
    weekly: "Weekly results (one row a coach a week)",
    coaches: "Coach statistics (the chosen weeks)",
    standings: "Standings after each week",
    teams: "Team selections (coach by team)",
    h2h: "Head-to-head: every pair of coaches",
    records: "Records"
  };
  function nrTables(s, C, st) {
    var ds = NR_DATASETS[LM.nr.ds] ? LM.nr.ds : "weekly";
    if ((ds === "teams") && !s.current) ds = "weekly";
    LM.nr.ds = ds;
    var name = "acql-" + s.year + "-" + ds + "-weeks-" + st.from + "-" + st.to, table;
    if (ds === "weekly" || ds === "standings") {
      var rows = [];
      st.cps.forEach(function (c) {
        var w = s.current ? weekData(c.week) : null;
        c.rows.forEach(function (r) {
          var line = w ? w.scores.filter(function (x) { return x.name === r.name; })[0] : null;
          rows.push({ week: c.week, name: r.name, score: r.score, regular: line ? line.regular : null, bl: line ? line.big_loser : null, vsAvg: r.vsAvg, wplace: r.wplace,
            won: c.winners.indexOf(r.name) >= 0 ? "yes" : "", total: r.total, place: r.place, tied: r.tied, move: r.move, behind: r.behind });
        });
      });
      var cols = ds === "weekly" ? [
        { key: "week", label: "Week", num: true, get: function (r) { return r.week; } },
        { key: "name", label: "Coach", get: function (r) { return r.name; } },
        { key: "score", label: "Total", num: true, get: function (r) { return r.score; } },
        s.current ? { key: "regular", label: "Games right", num: true, get: function (r) { return r.regular; } } : null,
        s.current ? { key: "bl", label: "Big Loser", num: true, get: function (r) { return r.bl; } } : null,
        { key: "won", label: "Won week", get: function (r) { return r.won; } },
        { key: "vsAvg", label: "vs pool avg", num: true, derived: true, get: function (r) { return r.vsAvg == null ? null : Math.round(r.vsAvg * 100) / 100; } },
        { key: "wplace", label: "Week rank", num: true, derived: true, get: function (r) { return r.wplace; } }
      ].filter(Boolean) : [
        { key: "week", label: "After week", num: true, get: function (r) { return r.week; } },
        { key: "name", label: "Coach", get: function (r) { return r.name; } },
        { key: "place", label: "Place", num: true, derived: true, get: function (r) { return r.place; }, csv: function (r) { return (r.tied ? "T" : "") + r.place; }, fmt: function (r) { return (r.tied ? "T" : "") + r.place; } },
        { key: "total", label: "Season total", num: true, derived: true, get: function (r) { return r.total; } },
        { key: "behind", label: "Behind 1st", num: true, derived: true, get: function (r) { return r.behind; } },
        { key: "move", label: "Move", num: true, derived: true, get: function (r) { return r.move; } }
      ];
      table = nrTable("tbl-" + ds, cols, rows, { sort: { col: "week", dir: 1 }, search: function (r) { return r.name + " week " + r.week; }, placeholder: "Coach or week", limit: 80, csv: name });
    } else if (ds === "coaches") {
      table = nrTable("tbl-coaches", nrCoachCols(s), st.rows, { sort: { col: "place", dir: 1 }, search: function (r) { return r.name; }, csv: name });
    } else if (ds === "teams") {
      var T = lmTeamPicks(st.from, st.to), trows = [];
      Object.keys(T.cells).forEach(function (n) { Object.keys(T.cells[n]).forEach(function (t) { trows.push({ name: n, team: t, n: T.cells[n][t].n, ok: T.cells[n][t].ok }); }); });
      table = nrTable("tbl-teams", [
        { key: "name", label: "Coach", get: function (r) { return r.name; } },
        { key: "team", label: "Team", get: function (r) { return r.team; } },
        { key: "n", label: "Times picked", num: true, get: function (r) { return r.n; } },
        { key: "ok", label: "Right", num: true, get: function (r) { return r.ok; } }
      ], trows, { sort: { col: "n", dir: -1 }, search: function (r) { return r.name + " " + r.team; }, placeholder: "Coach or team", limit: 80, csv: name });
    } else if (ds === "h2h") {
      var people = st.rows.map(function (r) { return r.name; }), prow = [];
      for (var i = 0; i < people.length; i++) for (var j = i + 1; j < people.length; j++) {
        var aw = 0, bw = 0, t = 0;
        st.cps.forEach(function (c) { var x = c.by[people[i]], y = c.by[people[j]]; if (!x || !y || x.score == null || y.score == null) return; if (x.score > y.score) aw++; else if (y.score > x.score) bw++; else t++; });
        prow.push({ a: people[i], b: people[j], aw: aw, bw: bw, t: t });
      }
      table = nrTable("tbl-h2h", [
        { key: "a", label: "Coach", get: function (r) { return r.a; } },
        { key: "b", label: "Against", get: function (r) { return r.b; } },
        { key: "aw", label: "Weeks ahead", num: true, derived: true, get: function (r) { return r.aw; } },
        { key: "bw", label: "Weeks behind", num: true, derived: true, get: function (r) { return r.bw; } },
        { key: "t", label: "Level", num: true, derived: true, get: function (r) { return r.t; } }
      ], prow, { sort: { col: "aw", dir: -1 }, search: function (r) { return r.a + " " + r.b; }, placeholder: "Find a coach", limit: 60, csv: name });
    } else {
      var rrows = [];
      lmRecords().forEach(function (r) { r.holders.forEach(function (h) { rrows.push({ rec: r.label, value: r.value, unit: r.unit, name: h.name, year: h.year, week: h.week, kind: LM_KINDS[r.kind].label, calc: r.calc }); }); });
      table = nrTable("tbl-records", [
        { key: "rec", label: "Record", get: function (r) { return r.rec; } },
        { key: "value", label: "Value", num: true, get: function (r) { return r.value; } },
        { key: "unit", label: "Unit", get: function (r) { return r.unit; } },
        { key: "name", label: "Coach", get: function (r) { return r.name; } },
        { key: "year", label: "Season", num: true, get: function (r) { return r.year; } },
        { key: "week", label: "Week", num: true, get: function (r) { return r.week; } },
        { key: "kind", label: "Source", get: function (r) { return r.kind; } },
        { key: "calc", label: "How it's worked out", get: function (r) { return r.calc; } }
      ], rrows, { sort: { col: "rec", dir: 1 }, search: function (r) { return r.rec + " " + r.name; }, csv: "acql-records" });
    }
    return el("div", { class: "nr-stack" }, [nrCard("Data tables", [
      el("label", { class: "lm-pick" }, [el("span", { text: "Dataset" }), el("select", { onchange: function (e) { LM.nr.ds = e.target.value; lmDraw(); } },
        Object.keys(NR_DATASETS).filter(function (k) { return k !== "teams" || s.current; }).map(function (k) { return el("option", { value: k, selected: k === ds, text: NR_DATASETS[k] }); }))]),
      el("p", { class: "note", text: "The CSV holds exactly the rows the table shows: the chosen weeks, the search, the sort. Official values go out as recorded; a heading marked \"(calculated)\" in the file was worked out here." }),
      table
    ])]);
  }

  function nrGlossary() {
    var extra = [
      ["Places and ties", "Season standings rank coaches by total; equal totals share a place and the next place is skipped (1, 2, 2, 4) - the dashboard's own rule. The official table may order a tie; where it does, the Time Machine's Sources says so."],
      ["Move", "Places gained (+) or lost (−) in the season standings from the week before. A move says what changed, not which game changed it."],
      ["Pool average", "The average of every card's total that week, as the week's official recap gives it."],
      ["Rolling average", "The mean of a week and the two before it."],
      ["Small samples", "Six or seven weeks is a small sample: a standard deviation or a favourite-picking rate from it can swing a lot with one more week. Treat differences of a fraction of a win as noise."],
      ["Weeks differ", "Byes change how many games a week has (and so its most possible score). % of max evens that out; raw totals don't."],
      ["Estimates", "Title chances (Broadcast) come from the site's own simulation of the weeks left: a chance, never a result."],
      ["Provisional", "Live scores during games: they change until the games are final and the pool's results are entered."]
    ];
    return nrCard("What the numbers mean", [el("dl", { class: "nr-gloss" }, Object.keys(NR_DEFS).map(function (k) { return [NR_DEFS[k][0], NR_DEFS[k][1]]; }).concat(extra)
      .reduce(function (acc, d) { return acc.concat([el("dt", { text: d[0] }), el("dd", { text: d[1] })]); }, []))]);
  }
