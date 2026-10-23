  // ---- the Charts page ------------------------------------------------------------------
  // The power map: every team's logo by what the betting lines rate it (across) and
  // what it has actually won (up). The dashed line is the record a rating usually
  // earns, so a logo well under it is better than its record says.
  function teamRecords() {
    var rec = {};
    DATA.weeks.forEach(function (w) {
      (w.results || []).forEach(function (g) {
        var win = codeOf(g.winner), lose = codeOf(g.loser);
        if (!win || !lose || win === lose) return;
        (rec[win] = rec[win] || { w: 0, l: 0 }).w++;
        (rec[lose] = rec[lose] || { w: 0, l: 0 }).l++;
      });
    });
    return rec;
  }
  function powerPoints() {
    var power = DATA.team_power || {}, rec = teamRecords();
    var pts = Object.keys(power).filter(function (c) { return rec[c]; }).map(function (c) {
      var r = rec[c];
      return { code: c, rating: power[c], w: r.w, l: r.l, pct: r.w / (r.w + r.l) };
    });
    if (pts.length < 28) return null;
    // the record a rating usually earns: a straight line through the points
    var n = pts.length, mx = 0, my = 0, sxy = 0, sxx = 0;
    pts.forEach(function (p) { mx += p.rating / n; my += p.pct / n; });
    pts.forEach(function (p) { sxy += (p.rating - mx) * (p.pct - my); sxx += (p.rating - mx) * (p.rating - mx); });
    var slope = sxx ? sxy / sxx : 0;
    pts.forEach(function (p) { p.gap = p.pct - (my + slope * (p.rating - mx)); });
    return { pts: pts, fit: function (x) { return my + slope * (x - mx); } };
  }
  function powerMap(width) {
    var P = powerPoints();
    if (!P) return null;
    var pts = P.pts, small = width < 520;
    var H = small ? 340 : 440, padL = 44, padR = 16, padT = 22, padB = 38, size = small ? 24 : 32;
    var lo = Math.min.apply(null, pts.map(function (p) { return p.rating; })), hi = Math.max.apply(null, pts.map(function (p) { return p.rating; }));
    var span = Math.max(Math.abs(lo), Math.abs(hi), 3) + 1;
    function X(v) { return padL + (v + span) / (2 * span) * (width - padL - padR); }
    function Y(v) { return padT + (1 - v) * (H - padT - padB); }
    var kids = [];
    [0, 0.25, 0.5, 0.75, 1].forEach(function (v) {
      kids.push(svgEl("line", { x1: padL, x2: width - padR, y1: Y(v), y2: Y(v), class: "axis", "stroke-width": v === 0.5 ? 1.5 : 0.6 }));
      kids.push(svgEl("text", { x: padL - 6, y: Y(v) + 4, "text-anchor": "end", text: Math.round(v * 100) + "%" }));
    });
    var step = span > 8 ? 4 : 2;
    for (var t = -Math.floor(span / step) * step; t <= span; t += step) {
      kids.push(svgEl("line", { x1: X(t), x2: X(t), y1: padT, y2: H - padB, class: "axis", "stroke-width": t === 0 ? 1.5 : 0.6 }));
      kids.push(svgEl("text", { x: X(t), y: H - padB + 16, "text-anchor": "middle", text: t === 0 ? "avg" : (t > 0 ? "+" : "−") + Math.abs(t) }));
    }
    kids.push(svgEl("text", { x: (padL + width - padR) / 2, y: H - 4, "text-anchor": "middle", class: "lbl", text: "Betting-line rating: points better than an average team →" }));
    kids.push(svgEl("text", { x: 12, y: (padT + H - padB) / 2, "text-anchor": "middle", class: "lbl",
      transform: "rotate(-90 12 " + (padT + H - padB) / 2 + ")", text: "Games won" }));
    kids.push(svgEl("text", { x: width - padR - 4, y: H - padB - 8, "text-anchor": "end", class: "quad", text: "Better than the record" }));
    kids.push(svgEl("text", { x: padL + 6, y: padT + 14, class: "quad", text: "Winning above the rating" }));
    var fx1 = -span, fx2 = span;
    kids.push(svgEl("line", { x1: X(fx1), y1: Y(Math.max(0, Math.min(1, P.fit(fx1)))), x2: X(fx2), y2: Y(Math.max(0, Math.min(1, P.fit(fx2)))), class: "fit", "stroke-width": 1.5 }));
    var sorted = pts.slice().sort(function (a, b) { return Math.abs(a.gap) - Math.abs(b.gap); });
    var standouts = pts.slice().sort(function (a, b) { return Math.abs(b.gap) - Math.abs(a.gap); }).slice(0, 4).map(function (p) { return p.code; });
    sorted.forEach(function (p) {
      var cx = X(p.rating), cy = Y(p.pct);
      var tip = teamFull(p.code) + ": " + p.w + "–" + p.l + ", rated " + (p.rating > 0 ? "+" : p.rating < 0 ? "−" : "") + Math.abs(p.rating) + " by the lines";
      var g = svgEl("g", {}, [
        standouts.indexOf(p.code) >= 0 ? svgEl("circle", { cx: cx, cy: cy, r: size * 0.72, class: "spot" }) : null,
        svgEl("text", { x: cx, y: cy + 4, "text-anchor": "middle", class: "lbl", text: p.code.toUpperCase() }),
        svgEl("image", { href: logoUrl(p.code), x: cx - size / 2, y: cy - size / 2, width: size, height: size }),
        svgEl("title", { text: tip })
      ]);
      kids.push(g);
    });
    return svgEl("svg", { viewBox: "0 0 " + width + " " + H, role: "img", "aria-label": "Teams by betting-line rating and games won" }, kids);
  }
  function powerMapModule() {
    var P = powerPoints();
    if (!P) return null;
    function line(p) { return teamFull(p.code) + " " + p.w + "–" + p.l; }
    var under = P.pts.filter(function (p) { return p.gap < -0.1; }).sort(function (a, b) { return a.gap - b.gap; }).slice(0, 4);
    var over = P.pts.filter(function (p) { return p.gap > 0.1; }).sort(function (a, b) { return b.gap - a.gap; }).slice(0, 4);
    function list(title, items) {
      return items.length ? el("div", {}, [el("b", { text: title }), el("div", { class: "chips" }, items.map(function (p) {
        return el("span", { class: "chip", title: line(p) }, [badge(p.code), " " + p.w + "–" + p.l]); }))]) : null;
    }
    return module("Power map", "every team: what the lines think, against what it has won", [
      el("div", { class: "pmap" }, [chartBox("power", 340, powerMap)]),
      el("div", { class: "pmap-lists" }, [list("Better than their record", under), list("Winning more than the lines expect", over)]),
      el("p", { class: "note", text: "Across: how many points better than an average team the betting lines make each team, from every line this season. Up: the share of its games it has won. The dashed line is the record that rating usually brings; the further a logo sits below it, the more the market still believes in a team its record doesn’t back up." }),
      tableView("power", ["Team", "Record", "Rating"], P.pts.slice().sort(function (a, b) { return b.rating - a.rating; }).map(function (p) {
        return [teamFull(p.code), p.w + "–" + p.l, (p.rating > 0 ? "+" : "") + p.rating]; }))
    ], { "data-card": "power-map" });
  }
  function chartsView() {
    var focus = highlighted();
    var weeks = seasonWeeks();
    var all = names().slice().sort(function (a, b) { return a.localeCompare(b); });
    var pick = el("label", { class: "note pick-coach" }, ["In gold",
      el("select", { class: "filter", style: "max-width:14em", id: "chart-coach", "aria-label": "Coach shown in gold",
        onchange: function (e) { state.chartMe = e.target.value; render(); } },
        [el("option", { value: "", text: "Choose a coach…" })].concat(all.map(function (n) { return el("option", { value: n, text: n, selected: n === focus }); })))]);
    var kids = [el("div", { class: "pagehead" }, [el("h1", { text: "Charts" }), pick])];
    if (weeks.length < 2) {
      kids.push(el("p", { class: "lede", text: "The charts fill in once two weeks are done." }));
      return el("div", { class: "view", "data-view": "charts" }, kids);
    }
    var totals = totalsByWeek();
    var top = DATA.players.slice(0, 3).map(function (p) { return p.name; });
    var keyLines = [["me", focus || "Choose a coach"], ["", "the top three now"], ["ctx", "everyone else"]];
    kids.push(module("The season race", "wins behind the leader after each week", [
      chartBox("race", 300, function (w) { return raceChart(w, focus); }), legend(keyLines),
      tableView("race", ["Coach"].concat(weeks.map(function (n) { return "Wk " + n; })),
        DATA.players.map(function (p) { return [p.name].concat(totals[p.name]); }))
    ], { "data-card": "race-chart" }));
    var T = DATA.title_by_week || {};
    if (T.weeks && T.weeks.length >= 2) {
      kids.push(module("Title odds", "the chance of the title as it stood after each week", [
        chartBox("title", 300, function (w) { return titleChart(w, focus); }), legend([["me", focus || "Choose a coach"], ["", "the four likeliest now"], ["ctx", "everyone else"]]),
        el("p", { class: "note", text: "Each week’s chance comes from playing out the rest of the season thousands of times from the standings at that point." }),
        tableView("title", ["Coach"].concat(T.weeks.map(function (n) { return "Wk " + n; })),
          Object.keys(T.odds).sort(function (a, b) { return (T.odds[b][T.odds[b].length - 1] || 0) - (T.odds[a][T.odds[a].length - 1] || 0); })
            .map(function (k) { return [k].concat(T.odds[k].map(function (v) { return v == null ? "–" : (v < 1 && v > 0 ? "<1" : Math.round(v)) + "%"; })); }))
      ], { "data-card": "title-chart" }));
    }
    kids.push(module("Every week’s scores", "the pool from lowest to highest, and its average", [
      chartBox("spread", 260, function (w) { return spreadChart(w, focus); }),
      legend([["dot", focus || "Choose a coach"], ["rng", "the pool, low to high"], ["", "the average"]]),
      tableView("spread", ["Week", "Best", "Average", "Lowest"].concat(focus ? [focus] : []), DATA.weeks.slice().sort(function (a, b) { return a.week - b.week; }).map(function (w) {
        var lo = Math.min.apply(null, w.scores.map(function (s) { return s.total; }));
        var mine = focus ? w.scores.filter(function (s) { return s.name === focus; })[0] : null;
        return ["Week " + w.week, w.top, w.average.toFixed(1), lo].concat(focus ? [mine ? mine.total : "–"] : []);
      }))
    ], { "data-card": "spread-chart" }));
    var M = DATA.money_by_week || {};
    if (Object.keys(M).length) {
      kids.push(module("Money", "each coach’s money after each week", [
        chartBox("money", 300, function (w) { return moneyChart(w, focus, false); }),
        legend([["me", focus || "Choose a coach"], ["", "most and least so far"], ["ctx", "everyone else"]]),
        el("p", { class: "note", text: "Each week the best card collects a dollar a game from everyone behind it. The weeks add up to the money sheet’s totals." }),
        tableView("money", ["Coach"].concat(weeks.map(function (n) { return "Wk " + n; })),
          Object.keys(M).sort(function (a, b) { return M[b][M[b].length - 1] - M[a][M[a].length - 1]; }).map(function (k) { return [k].concat(M[k].map(dollars)); }))
      ], { "data-card": "money-chart" }));
    }
    kids.push(powerMapModule());
    return el("div", { class: "view", "data-view": "charts" }, kids);
  }
  function moneyChartModule() {
    var M = DATA.money_by_week || {};
    if (!Object.keys(M).length || seasonWeeks().length < 2) return null;
    var focus = highlighted();
    return module("Over the season", "each coach’s money after each week", [
      chartBox("money-page", 300, function (w) { return moneyChart(w, focus, false); }),
      legend([["me", focus || "You (pick your name)"], ["", "most and least so far"], ["ctx", "everyone else"]])
    ], { "data-card": "money-chart" });
  }

