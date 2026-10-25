  // ---- factions: who picks with whom (upgrade book #9) ------------------------------------
  // Every coach's side in every game, worked out from the graded sheet the site
  // already has: a "1" took the credited side, a "0" the other one.
  function sideOf(w, name, j) {
    var bits = w.picks && w.picks[name], g = w.results && w.results[j];
    if (!bits || !g || bits[j] === "-" || bits[j] === undefined) return null;
    return { team: bits[j] === "1" ? g.winner : g.loser, ok: bits[j] === "1" };
  }
  function pickedWeeks() {
    return DATA.weeks.filter(function (w) { return w.picks && w.results && w.results.length; })
      .sort(function (a, b) { return a.week - b.week; });
  }
  // Rows in an order where coaches who pick alike sit together (average linkage).
  function clusterOrder(names_, dist) {
    var groups = names_.map(function (n) { return [n]; });
    function d(a, b) {
      var s = 0, k = 0;
      a.forEach(function (x) { b.forEach(function (y) { s += dist(x, y); k++; }); });
      return k ? s / k : 0;
    }
    while (groups.length > 1) {
      var best = null;
      for (var i = 0; i < groups.length; i++) for (var j = i + 1; j < groups.length; j++) {
        var v = d(groups[i], groups[j]);
        if (!best || v < best.v) best = { i: i, j: j, v: v };
      }
      var merged = groups[best.i].concat(groups[best.j]);
      groups.splice(best.j, 1);
      groups.splice(best.i, 1, merged);
    }
    return groups[0] || [];
  }
  function factionsView() {
    var weeks = pickedWeeks();
    if (!weeks.length) return el("div", { class: "view", "data-view": "factions" }, [stateMsg("No pick sheets yet", "Factions show up once a week's picks are in.")]);
    var mode = state.fxWeek === "season" ? "season" : (weeks.filter(function (w) { return w.week === state.fxWeek; })[0] || weeks[weeks.length - 1]);
    var picker = el("div", { class: "weeks", role: "group", "aria-label": "Choose a week" }, weeks.map(function (w) {
      return el("button", { type: "button", "aria-pressed": mode === w ? "true" : "false", "aria-label": "Week " + w.week,
        onclick: function () { state.fxWeek = w.week; render(); }, text: String(w.week) });
    }).concat([el("button", { type: "button", "aria-pressed": mode === "season" ? "true" : "false",
      onclick: function () { state.fxWeek = "season"; render(); }, text: "Season" })]));
    return el("div", { class: "view", "data-view": "factions" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Factions" })]),
      el("p", { class: "note", text: "Who picks with whom. Coaches who picked alike sit next to each other, so the pool's blocs show up as solid bands. Faded squares are picks that lost." }),
      picker,
      mode === "season" ? factionSeason(weeks) : factionWeek(mode)
    ]);
  }
  function factionWeek(w) {
    var coaches = Object.keys(w.picks).filter(function (n) { return player(n); });
    var games = w.results.map(function (g, j) {
      var tally = {};
      coaches.forEach(function (n) { var s = sideOf(w, n, j); if (s) tally[s.team] = (tally[s.team] || 0) + 1; });
      var teams = Object.keys(tally).sort(function (a, b) { return tally[b] - tally[a]; });
      var total = teams.reduce(function (s, t) { return s + tally[t]; }, 0);
      return { j: j, g: g, top: teams[0], share: total ? tally[teams[0]] / total : 1 };
    }).sort(function (a, b) { return a.share - b.share; });          // most split first
    function agreeWithCrowd(n) {
      var same = 0, k = 0;
      games.forEach(function (c) { var s = sideOf(w, n, c.j); if (s) { k++; if (s.team === c.top) same++; } });
      return k ? same / k : 0;
    }
    var order = clusterOrder(coaches, function (a, b) {
      var diff = 0, k = 0;
      games.forEach(function (c) { var x = sideOf(w, a, c.j), y = sideOf(w, b, c.j); if (x && y) { k++; if (x.team !== y.team) diff++; } });
      return k ? diff / k : 1;
    });
    var bands = [["With the crowd", function (p) { return p >= 0.85; }], ["Mostly with it", function (p) { return p >= 0.65 && p < 0.85; }],
                 ["Going it alone", function (p) { return p < 0.65; }]];
    var head = el("tr", {}, [el("th", {})].concat(games.map(function (c) {
      return el("th", { class: "g", title: c.g.matchup + " - " + Math.round(c.share * 100) + "% on " + teamFull(codeOf(c.top)), text: (c.g.away ? codeOf(c.g.away).toUpperCase() : "") + "@" + (c.g.home ? codeOf(c.g.home).toUpperCase() : "") });
    })));
    var rows = [], counts = [];
    bands.forEach(function (b, bi) {
      var inBand = order.filter(function (n) { return b[1](agreeWithCrowd(n)); });
      counts.push(inBand.length);
      if (!inBand.length) return;
      rows.push(el("tr", {}, [el("td", { class: "grp", colspan: String(games.length + 1), text: b[0] + " · " + inBand.length })]));
      inBand.forEach(function (n) {
        rows.push(el("tr", {}, [el("td", { class: "nm" + (isMe(n) ? " me" : ""), text: n })].concat(games.map(function (c) {
          var s = sideOf(w, n, c.j);
          var col = s ? (TEAM_COLORS[codeOf(s.team)] || ["#8a968c"])[0] : "";
          return el("td", { class: "c" }, [el("span", { class: "sq" + (s ? (s.ok ? "" : " lost") : " none"), style: s ? "--c:" + col : "",
            title: n + ": " + (s ? teamFull(codeOf(s.team)) + (s.ok ? " ✓" : " ✗") : "no pick") + " (" + c.g.matchup + ")" })]);
        }))));
      });
    });
    var split = games[0];
    var summary = counts[0] + " of " + order.length + " coaches picked with the crowd on nearly every game; " + counts[2] +
      " went their own way on more than a third. The most split game was " + split.g.matchup + " (" + Math.round(split.share * 100) + "% on " + teamFull(codeOf(split.top)) + ").";
    return module("Week " + w.week, null, [el("p", { class: "note", text: summary }), scroller(el("table", { class: "fx" }, [el("thead", {}, [head]), el("tbody", {}, rows)]))]);
  }
  function factionSeason(weeks) {
    var coaches = names();
    function share(w, n) {
      if (!w.picks[n]) return null;
      var same = 0, k = 0;
      w.results.forEach(function (g, j) {
        var tally = {};
        Object.keys(w.picks).forEach(function (m) { var s = sideOf(w, m, j); if (s) tally[s.team] = (tally[s.team] || 0) + 1; });
        var top = Object.keys(tally).sort(function (a, b) { return tally[b] - tally[a]; })[0];
        var s = sideOf(w, n, j);
        if (s) { k++; if (s.team === top) same++; }
      });
      return k ? same / k : null;
    }
    var table = coaches.map(function (n) {
      var by = weeks.map(function (w) { return share(w, n); });
      var seen = by.filter(function (v) { return v != null; });
      return { n: n, by: by, avg: seen.length ? seen.reduce(function (a, b) { return a + b; }, 0) / seen.length : 0 };
    }).sort(function (a, b) { return b.avg - a.avg; });
    var head = el("tr", {}, [el("th", {})].concat(weeks.map(function (w) { return el("th", { text: "W" + w.week }); })).concat([el("th", { text: "Season" })]));
    var rows = table.map(function (r) {
      return el("tr", {}, [el("td", { class: "nm" + (isMe(r.n) ? " me" : ""), text: r.n })].concat(r.by.map(function (v, i) {
        return el("td", { class: "c" }, [v == null ? el("span", { class: "sq none" }) :
          el("span", { class: "pct", style: "--a:" + Math.round(Math.max(0, v - 0.4) / 0.6 * 100) + "%", title: r.n + ", week " + weeks[i].week + ": with the crowd on " + Math.round(v * 100) + "%", text: Math.round(v * 100) })]);
      })).concat([el("td", { class: "c" }, [el("span", { class: "pct", style: "--a:" + Math.round(Math.max(0, r.avg - 0.4) / 0.6 * 100) + "%", text: Math.round(r.avg * 100) })])]));
    });
    var top = table[0], low = table[table.length - 1];
    return module("The season", null, [
      el("p", { class: "note", text: "How often each coach took the side most of the pool took, week by week. " + top.n + " has been with the crowd most (" + Math.round(top.avg * 100) + "%), " + low.n + " least (" + Math.round(low.avg * 100) + "%)." }),
      scroller(el("table", { class: "fx" }, [el("thead", {}, [head]), el("tbody", {}, rows)]))]);
  }

  // ---- team lens: the pool and one team (upgrade book #40) --------------------------------
  var TEAM_KEY = "acql-team";
  function teamsView() {
    var weeks = pickedWeeks();
    var codes = Object.keys(DATA.teams || {}).sort(function (a, b) { return teamFull(a).localeCompare(teamFull(b)); });
    if (!weeks.length || !codes.length) return el("div", { class: "view", "data-view": "teams" }, [stateMsg("No pick sheets yet", "Team pages show up once a week's picks are in.")]);
    var chosen = codes.indexOf(state.team) >= 0 ? state.team : (codes.indexOf(stored(TEAM_KEY)) >= 0 ? stored(TEAM_KEY) : codes[0]);
    state.team = chosen;
    var chooser = el("div", { class: "tl-pick", role: "group", "aria-label": "Choose a team" }, codes.map(function (c) {
      return el("button", { type: "button", "aria-pressed": c === chosen ? "true" : "false", title: teamFull(c), "aria-label": teamFull(c),
        onclick: function () { state.team = c; store(TEAM_KEY, c); render(); } }, [badge(c)]);
    }));
    var games = [], loyal = {};
    weeks.forEach(function (w) {
      w.results.forEach(function (g, j) {
        var mine = codeOf(g.home) === chosen ? g.home : codeOf(g.away) === chosen ? g.away : null;
        if (!mine) return;
        var on = 0, all = 0;
        Object.keys(w.picks).forEach(function (n) {
          var s = sideOf(w, n, j);
          if (!s) return;
          all++;
          var backs = codeOf(s.team) === chosen;
          if (backs) on++;
          loyal[n] = loyal[n] || { n: n, on: 0, all: 0 };
          loyal[n].all++;
          if (backs) loyal[n].on++;
        });
        var other = mine === g.home ? g.away : g.home;
        games.push({ week: w.week, other: other, home: mine === g.home, on: on, all: all, credited: codeOf(g.winner) === chosen });
      });
    });
    var backs = games.reduce(function (s, x) { return s + x.on; }, 0), seen = games.reduce(function (s, x) { return s + x.all; }, 0);
    var rightBacks = games.reduce(function (s, x) { return s + (x.credited ? x.on : 0); }, 0);
    var credited = games.filter(function (x) { return x.credited; }).length;
    var col = (TEAM_COLORS[chosen] || ["#8a968c"])[0];
    var bars = el("div", { class: "tl-bars" }, games.map(function (x) {
      var pct = x.all ? Math.round(100 * x.on / x.all) : 0;
      return el("div", { class: "r" }, [el("span", { text: "W" + x.week + " " + (x.home ? "v " : "@ ") + codeOf(x.other).toUpperCase() }),
        el("span", { class: "t", title: x.on + " of " + x.all + " on " + teamFull(chosen) }, [el("i", { class: x.credited ? "" : "lost", style: "width:" + pct + "%;--c:" + col })]),
        el("span", { class: "num", text: pct + "% · " + (x.credited ? "✓" : "✗") })]);
    }));
    var fans = Object.keys(loyal).map(function (k) { return loyal[k]; }).filter(function (r) { return r.all >= 2; })
      .sort(function (a, b) { return b.on / b.all - a.on / a.all || b.all - a.all; });
    var miss = games.filter(function (x) { return !x.credited; }).sort(function (a, b) { return b.on / b.all - a.on / a.all; })[0];
    var steal = games.filter(function (x) { return x.credited; }).sort(function (a, b) { return a.on / a.all - b.on / b.all; })[0];
    var stories = [];
    if (miss && miss.all) stories.push("The pool's biggest miss: week " + miss.week + ", " + miss.on + " of " + miss.all + " on " + teamFull(chosen) + " " + (miss.home ? "against " : "at ") + teamFull(codeOf(miss.other)) + ", and they didn't come through.");
    if (steal && steal.all) stories.push("The one the pool didn't see: week " + steal.week + ", only " + steal.on + " of " + steal.all + " took " + teamFull(chosen) + ", and they came through.");
    return el("div", { class: "view", "data-view": "teams" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Teams" })]),
      chooser,
      module(teamFull(chosen), plural(games.length, "game"), [
        el("div", { class: "tl-stats" }, [
          el("div", {}, [el("b", { text: seen ? Math.round(100 * backs / seen) + "%" : "–" }), el("span", { class: "note", text: "of picks in their games went on them" })]),
          el("div", {}, [el("b", { text: backs ? Math.round(100 * rightBacks / backs) + "%" : "–" }), el("span", { class: "note", text: "of those picks came in" })]),
          el("div", {}, [el("b", { text: credited + "–" + (games.length - credited) }), el("span", { class: "note", text: "credited by the pool's lines" })])
        ]),
        el("h3", { text: "Pool on them, week by week" }), bars,
        stories.length ? el("p", { class: "note", text: stories.join(" ") }) : null
      ]),
      fans.length ? module("Who backs them", null, [scroller(el("table", {}, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "Coach" }), el("th", { class: "n", text: "On them" }), el("th", { class: "n", text: "Games" })])]),
        el("tbody", {}, fans.slice(0, 5).concat(fans.length > 8 ? fans.slice(-3) : []).map(function (r) {
          return el("tr", {}, [el("td", { class: isMe(r.n) ? "me" : "", text: r.n }), el("td", { class: "n num", text: Math.round(100 * r.on / r.all) + "%" }), el("td", { class: "n num", text: String(r.all) })]);
        }))]))]) : null
    ]);
  }
