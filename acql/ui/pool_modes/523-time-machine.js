  // ---- League Time Machine: the league as it stood after any week on record ----------
  // A timeline of the season's weeks; the standings, the week's results and the
  // title race as they were at the chosen one; a replay that walks the season
  // forward. Weeks the archive doesn't have are shown as missing, never filled in.
  var TM_TABS = [
    ["standings", "Standings"], ["race", "Title race"], ["week", "The week"], ["coach", "Coach"],
    ["events", "Timeline"], ["compare", "Compare"], ["sources", "Sources"]
  ];
  var TM_SPEEDS = [[0.5, "½×"], [1, "1×"], [2, "2×"], [4, "4×"]];

  function tmSetWeek(n, keepPlaying) {
    LM.sel.week = n;
    if (!keepPlaying) tmStop();
    lmDraw();
  }
  function tmStep(dir) {
    var s = lmSeasonNow(), C = lmCheckpoints(s), at = C.weeks.indexOf(lmWeek(s));
    var to = C.weeks[Math.max(0, Math.min(C.weeks.length - 1, at + dir))];
    if (to != null) tmSetWeek(to);
  }
  function tmStop() {
    if (LM.tm.timer) { clearInterval(LM.tm.timer); LM.tm.timer = null; }
    LM.tm.playing = false;
  }
  function tmPlay() {
    var s = lmSeasonNow(), C = lmCheckpoints(s);
    if (!C.weeks.length) return;
    if (LM.tm.playing) { tmStop(); lmDraw(); return; }
    // from the start when already at the end
    if (lmWeek(s) === C.last) LM.sel.week = C.weeks[0];
    LM.tm.playing = true;
    lmDraw();
    LM.tm.timer = setInterval(function () {
      var s2 = lmSeasonNow(), C2 = lmCheckpoints(s2), i = C2.weeks.indexOf(lmWeek(s2));
      if (!LM.mode || LM.mode !== "timemachine" || i < 0 || i >= C2.weeks.length - 1) { tmStop(); if (LM.mode === "timemachine") lmDraw(); return; }
      LM.sel.week = C2.weeks[i + 1];
      lmDraw();
    }, Math.round(2600 / LM.tm.speed));
  }
  // What the chosen view is: a week's end, a season's final table, or the live week (not in the archive).
  function tmStatus(s, n) {
    var C = lmCheckpoints(s);
    if (!C.cps.length) return { kind: "official", text: "Final season record", note: "Only the final table was archived for this season." };
    if (!s.current && s.complete && n === C.last) return { kind: "official", text: "Final season record", note: "The season's last week: the final table." };
    var cp = C.byWeek[n];
    var note = cp && cp.official ? "The official table after week " + n + ": its places and moves as the pool's standings give them, ties broken its way."
      : "The standings once week " + n + "’s games were all graded, worked out from the official weekly totals - the official order of tied coaches wasn't kept for past weeks, so ties share a place.";
    if (s.current && n === C.last && hasLive() && DATA.live.week > n) note += " Week " + DATA.live.week + " is being played - it joins the timeline once it is final.";
    return { kind: cp && cp.official ? "official" : "calc", text: "End of week " + n, note: note };
  }

  function tmView() {
    var s = lmSeasonNow();
    if (!s) return el("div", { class: "lm-body tm" }, [stateMsg("No season on record yet", "The Time Machine starts once a week has been graded.")]);
    var C = lmCheckpoints(s), n = lmWeek(s), st = tmStatus(s, n);
    var tab = TM_TABS.some(function (t) { return t[0] === LM.tm.tab; }) ? LM.tm.tab : "standings";
    LM.tm.tab = tab;
    var main;
    if (!C.cps.length) main = tmFinalOnly(s);
    else if (tab === "race") main = tmRace(s, C, n);
    else if (tab === "week") main = tmWeekView(s, C, n);
    else if (tab === "coach") main = tmCoach(s, C, n);
    else if (tab === "events") main = tmEvents(s, C, n);
    else if (tab === "compare") main = tmCompare(s, C, n);
    else if (tab === "sources") main = tmSources(s, C);
    else main = tmStandings(s, C, n);
    return el("div", { class: "lm-body tm" }, [
      el("div", { class: "tm-head" }, [
        el("div", { class: "tm-when" }, [el("span", { class: "k", text: s.year + " season" }),
          el("b", { text: C.cps.length ? "Week " + n : "Final table" }),
          el("span", { class: "tm-status" }, [lmSrc(st.kind), " ", st.text])]),
        lmSeasonPicker(),
        lmPicker(s, lmCoach(s), function (v) { LM.sel.a = v; lmDraw(); }, "Follow")
      ]),
      C.cps.length ? tmRail(s, C, n) : null,
      el("p", { class: "tm-note note", text: st.note }),
      el("nav", { class: "lm-tabs", "aria-label": "Time Machine views" }, TM_TABS.map(function (t) {
        return el("button", { type: "button", "aria-current": t[0] === tab ? "page" : null, onclick: function () { LM.tm.tab = t[0]; lmDraw(); }, text: t[1] });
      })),
      main
    ]);
  }

  // The timeline: one stop a week of the season; played weeks on record can be
  // visited, a missing one says so, the weeks still to come are faint.
  function tmRail(s, C, n) {
    var events = lmEvents(s), count = {};
    events.forEach(function (e) { count[e.week] = (count[e.week] || 0) + 1; });
    var stops = [], last = Math.max(C.seasonWeeks, C.last);
    for (var k = 1; k <= last; k++) (function (k) {
      var has = !!C.byWeek[k], miss = C.missing.indexOf(k) >= 0, cp = C.byWeek[k];
      var tip = has ? "Week " + k + ": " + (cp.winners.length ? listNames(cp.winners, 2) + " won it; " : "") + listNames(cp.leaders, 2) + " led after it"
        : miss ? "Week " + k + ": played, but not in the archive" : "Week " + k + ": not played yet";
      stops.push(el("button", { type: "button", class: "tm-stop" + (has ? " on" : miss ? " miss" : " later") + (k === n ? " here" : ""),
        disabled: !has, "aria-current": k === n ? "step" : null, title: tip, "aria-label": tip,
        onclick: has ? function () { tmSetWeek(k); } : null }, [el("span", { class: "n", text: String(k) }),
        count[k] ? el("i", { class: "dot", "aria-hidden": "true" }) : null]));
    })(k);
    var pos = C.weeks.indexOf(n);
    return el("div", { class: "tm-rail" }, [
      el("div", { class: "tm-stops", style: "--weeks:" + last }, stops),
      el("div", { class: "tm-ctl", role: "group", "aria-label": "Travel through the season" }, [
        lmCtl("first", "First week on record", function () { tmSetWeek(C.weeks[0]); }, { disabled: pos <= 0 }),
        lmCtl("prev", "Previous week", function () { tmStep(-1); }, { disabled: pos <= 0 }),
        lmCtl(LM.tm.playing ? "pause" : "play", LM.tm.playing ? "Pause the replay" : "Play the season from here", tmPlay, { class: "lm-btn big", "aria-pressed": LM.tm.playing ? "true" : "false" }),
        lmCtl("next", "Next week", function () { tmStep(1); }, { disabled: pos >= C.weeks.length - 1 }),
        lmCtl("last", "Latest week on record", function () { tmSetWeek(C.last); }, { disabled: pos >= C.weeks.length - 1 }),
        el("div", { class: "lm-seg", role: "group", "aria-label": "Replay speed" }, TM_SPEEDS.map(function (o) {
          return el("button", { type: "button", "aria-pressed": LM.tm.speed === o[0] ? "true" : "false", text: o[1],
            onclick: function () { LM.tm.speed = o[0]; if (LM.tm.playing) { tmStop(); tmPlay(); } else lmDraw(); } });
        }))
      ])
    ]);
  }

  function tmBoardCells(s, cp, focus) {
    return function (r) {
      return [
        el("span", { class: "pl", text: lmPlace(r) }),
        lmMove(r.move),
        el("span", { class: "nm" }, [lmWho(r.name), cp.winners.indexOf(r.name) >= 0 ? el("span", { class: "lm-tag gold", title: "Won week " + cp.week, text: "Won wk" }) : null]),
        el("span", { class: "wk", title: "Week " + cp.week + " score" }, [r.score == null ? "–" : String(r.score)]),
        el("span", { class: "tot", title: "Season total after week " + cp.week, text: String(r.total) }),
        el("span", { class: "gap", title: "Wins behind first place", text: r.behind ? "−" + r.behind : "lead" })
      ];
    };
  }
  function tmBoardHead() {
    return el("div", { class: "lm-board-head", "aria-hidden": "true" }, ["#", "", "Coach", "Wk", "Total", "Gap"].map(function (t) { return el("span", { text: t }); }));
  }
  function tmStandings(s, C, n) {
    var cp = C.byWeek[n], focus = lmCoach(s), prev = C.cps[C.cps.indexOf(cp) - 1] || null;
    var board = lmBoard("tm-" + s.year, cp.rows, { rowH: 38, label: "Standings after week " + n, cells: tmBoardCells(s, cp, focus),
      rowClass: function (r) { return (r.name === focus ? "focus " : "") + (r.place === 1 ? "first " : "") + (isMe(r.name) ? "me" : ""); } });
    var movers = cp.rows.filter(function (r) { return r.move; }).slice().sort(function (a, b) { return b.move - a.move; });
    var up = movers.filter(function (r) { return r.move > 0; }).slice(0, 3), down = movers.filter(function (r) { return r.move < 0; }).slice(-3).reverse();
    var second = cp.rows.filter(function (r) { return r.place > 1; })[0];
    var evs = lmEvents(s).filter(function (e) { return e.week === n; });
    var side = el("div", { class: "tm-side" }, [
      el("div", { class: "lm-card" }, [el("h3", { text: "Week " + n + " at a glance" }),
        el("dl", { class: "lm-facts" }, [
          lmFact("Weekly winner" + (cp.winners.length > 1 ? "s" : ""), cp.winners.length ? listNames(cp.winners, 3) : "Not on record", "official"),
          lmFact("Top score", cp.top != null ? plural(cp.top, "win") + (cp.most ? " of " + cp.most + " possible" : "") : "–", "official"),
          lmFact("Pool average", lmFix(cp.average, 2), "official"),
          lmFact("Leading", listNames(cp.leaders, 3) + " · " + plural(cp.lead, "win"), "calc"),
          second ? lmFact("Lead over 2nd", cp.lead - second.total ? plural(cp.lead - second.total, "win") : "level", "calc") : null
        ])]),
      up.length || down.length ? el("div", { class: "lm-card" }, [el("h3", { text: prev ? "Biggest moves from week " + prev.week : "Moves" }),
        el("ul", { class: "lm-list" }, up.map(function (r) { return el("li", {}, [lmMove(r.move), " ", lmWho(r.name), " to " + ordinal(r.place)]); })
          .concat(down.map(function (r) { return el("li", {}, [lmMove(r.move), " ", lmWho(r.name), " to " + ordinal(r.place)]); })))]) : null,
      evs.length ? el("div", { class: "lm-card tm-mile" }, [el("h3", { text: "Milestones" }),
        el("ul", { class: "lm-list" }, evs.map(function (e) { return el("li", {}, [lmSrc(e.src), " ", e.text]); }))]) : null,
      el("div", { class: "lm-links" }, [
        s.current ? el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("broadcast", { week: n, kind: "recap" }); }, text: "Week " + n + " broadcast recap" }) : null,
        el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("numbers", { tab: "distribution", week: n }); }, text: "Week " + n + " in the Numbers Room" }),
        s.current ? el("button", { class: "lm-link", type: "button", onclick: function () { lmClose(false); state.week = n; go("weeks"); }, text: "Week " + n + " on the site" }) : null
      ])
    ]);
    return el("div", { class: "tm-grid" }, [
      el("div", { class: "lm-card tm-board" }, [el("h3", {}, ["Season standings after week " + n + " ", lmSrc(st0(s, C, n))]),
        el("p", { class: "note", text: C.byWeek[n].official ? "The official table. Rows slide as you travel." : "Totals are the official weekly wins added up; equal totals share a place. Rows slide as you travel." }),
        tmBoardHead(), board]),
      side
    ]);
  }
  function st0(s, C, n) { return C.byWeek[n] && C.byWeek[n].official ? "official" : "calc"; }
  function lmFact(k, v, kind) {
    return el("div", {}, [el("dt", {}, [k, kind ? " " : null, kind ? lmSrc(kind) : null]), el("dd", { text: v })]);
  }

  // The title race: season places week by week for the chosen coaches.
  function tmRace(s, C, n) {
    var cp = C.byWeek[n], focus = lmCoach(s), last = C.cps[C.cps.length - 1];
    if (!LM.tm.race || LM.tm.race.year !== s.year) {
      var champ = s.complete ? last.leaders : [];
      LM.tm.race = { year: s.year, on: last.rows.slice(0, 5).map(function (r) { return r.name; }).concat(champ) };
    }
    var on = LM.tm.race.on.filter(function (x, i, a) { return a.indexOf(x) === i; });
    if (on.indexOf(focus) < 0) on = on.concat([focus]);
    var xs = [];
    for (var k = 1; k <= C.last; k++) xs.push(k);
    var N = last.rows.length;
    function draw(width) {
      var lines = on.map(function (name) {
        return { name: name, role: name === focus ? "me" : "strong", label: true,
          values: xs.map(function (k) { var c = C.byWeek[k]; return c && c.by[name] ? c.by[name].place : null; }) };
      });
      var wrap = lineChart(width, lines, { xs: xs, height: width < 520 ? 260 : 340, min: 1, max: Math.max(2, N), invert: true,
        fmt: function (v) { return ordinal(Math.round(v)); }, title: "Season place after each week",
        tipTitle: function (i) { var c = C.byWeek[xs[i]]; return c ? "After week " + xs[i] + " · leader on " + c.lead : "Week " + xs[i] + " - not in the archive"; } });
      tmMarker(wrap, width, xs, n);
      return lmClickWeeks(wrap, width, xs, function (k) { if (C.byWeek[k]) tmSetWeek(k); });
    }
    var chips = last.rows.slice(0, 12).map(function (r) { return r.name; });
    if (chips.indexOf(focus) < 0) chips.push(focus);
    var gapRows = on.map(function (name) { var r = cp.by[name]; return r ? { name: name, r: r } : null; }).filter(Boolean)
      .sort(function (a, b) { return a.r.place - b.r.place; });
    var changes = lmEvents(s).filter(function (e) { return e.kind === "lead"; });
    return el("div", { class: "tm-grid" }, [
      el("div", { class: "lm-card" }, [
        el("h3", {}, ["Where they stood, week by week ", lmSrc("calc")]),
        el("p", { class: "note", text: "Place in the season standings after each week (1st at the top). Click the chart to travel to that week; the gold line is " + focus + "." +
          (s.complete ? " The eventual champion is " + listNames(last.leaders, 2) + "." : "") + (C.missing.length ? " Weeks " + C.missing.join(", ") + " are not in the archive: their lines break." : "") }),
        el("div", { class: "lm-chips", role: "group", "aria-label": "Coaches on the chart" }, chips.map(function (name) {
          var pressed = on.indexOf(name) >= 0;
          return el("button", { type: "button", class: "lm-chipbtn", "aria-pressed": pressed ? "true" : "false", disabled: name === focus,
            onclick: function () { var list = LM.tm.race.on; var i = list.indexOf(name); if (i >= 0) list.splice(i, 1); else list.push(name); lmDraw(); }, text: name });
        })),
        lmChart(340, draw, "Season place by week")
      ]),
      el("div", { class: "tm-side" }, [
        el("div", { class: "lm-card" }, [el("h3", { text: "The gaps after week " + n }),
          el("table", { class: "lm-table" }, [el("thead", {}, [el("tr", {}, ["#", "Coach", "Total", "Behind 1st"].map(function (h) { return el("th", { text: h }); }))]),
            el("tbody", {}, gapRows.map(function (g) {
              return el("tr", { class: g.name === focus ? "focus" : "" }, [el("td", { text: lmPlace(g.r) }), el("td", {}, [lmWho(g.name)]),
                el("td", { class: "num", text: String(g.r.total) }), el("td", { class: "num", text: g.r.behind ? "−" + g.r.behind : "lead" })]);
            }))])]),
        el("div", { class: "lm-card" }, [el("h3", {}, ["Changes at the top ", lmSrc("calc")]),
          changes.length ? el("ul", { class: "lm-list" }, changes.map(function (e) {
            return el("li", {}, [el("button", { type: "button", class: "lm-wk", onclick: function () { tmSetWeek(e.week); }, text: "Wk " + e.week }), " ", e.text]);
          })) : el("p", { class: "note", text: "No change at the top yet." })])
      ])
    ]);
  }
  // A thin gold line on a week chart where the traveller is.
  function tmMarker(wrap, width, xs, n) {
    var svg = wrap.querySelector("svg"), i = xs.indexOf(n);
    if (!svg || i < 0) return;
    var narrow = width < 520, padL = 40, padR = narrow ? 84 : 112, H = Number(svg.getAttribute("height")) || 300;
    var x = padL + (xs.length > 1 ? i * (width - padL - padR) / (xs.length - 1) : (width - padL - padR) / 2);
    svg.insertBefore(svgEl("line", { class: "lm-now", x1: x, x2: x, y1: 8, y2: H - 26 }), svg.firstChild.nextSibling);
  }

  // One week, rebuilt from what was recorded of it.
  function tmWeekView(s, C, n) {
    var cp = C.byWeek[n], rec = lmWeekRec(s, n) || {}, focus = lmCoach(s);
    var kids = [];
    var results = s.current && rec.results ? rec.results : null;
    kids.push(el("div", { class: "lm-card" }, [el("h3", {}, ["The NFL games ", lmSrc("official")]),
      results ? scroller(el("table", { class: "lm-table" }, [
        el("thead", {}, [el("tr", {}, ["Game", "Winner", "Pool line", "Cards right"].map(function (h) { return el("th", { text: h }); }))]),
        el("tbody", {}, results.map(function (g) {
          return el("tr", {}, [el("td", { text: g.matchup }), el("td", { text: g.winner || "not played" }), el("td", { text: g.line || "–" }),
            el("td", { class: "num", text: g.right == null ? "–" : g.right + " of " + (rec.entrants || "?") })]);
        }))])) : el("p", { class: "note", text: "The archive keeps each past season's weekly totals, not its games: there is no game list for this week." })]));
    var picksOf = s.current && rec.picks ? rec.picks : null;
    kids.push(el("div", { class: "lm-card" }, [el("h3", {}, ["Every coach that week ", lmSrc("official", "week scores"), " ", lmSrc("calc", "standings")]),
      scroller(el("table", { class: "lm-table" }, [
        el("thead", {}, [el("tr", {}, ["Week rank", "Coach", "Week", "vs avg", "Season", "Place", "Move"].map(function (h) { return el("th", { text: h }); }))]),
        el("tbody", {}, cp.rows.slice().sort(function (a, b) { return (a.wplace || 999) - (b.wplace || 999) || a.place - b.place; }).map(function (r) {
          return el("tr", { class: (r.name === focus ? "focus " : "") + (cp.winners.indexOf(r.name) >= 0 ? "won" : "") }, [
            el("td", { text: r.wplace ? String(r.wplace) : "–" }), el("td", {}, [lmWho(r.name)]),
            el("td", { class: "num", text: r.score == null ? "no card" : String(r.score) }), el("td", { class: "num", text: lmSigned(r.vsAvg) }),
            el("td", { class: "num", text: String(r.total) }), el("td", { class: "num", text: lmPlace(r) }), el("td", {}, [lmMove(r.move)])]);
        }))])),
      picksOf ? null : el("p", { class: "note", text: "Picks for this season were not archived game by game." })]));
    if (s.current && rec.awards && rec.awards.length) kids.push(el("div", { class: "lm-card" }, [el("h3", {}, ["The week’s awards ", lmSrc("official")]),
      el("ul", { class: "lm-list" }, rec.awards.map(function (a) { return el("li", {}, [el("b", { text: a.title + ": " }), a.who + (a.detail ? " - " + a.detail : "")]); }))]));
    if (s.current && rec.suicide) {
      var su = rec.suicide;
      kids.push(el("div", { class: "lm-card" }, [el("h3", {}, ["Side pools ", lmSrc("official")]),
        el("dl", { class: "lm-facts" }, [
          lmFact("Suicide pool: knocked out", su.killed != null ? String(su.killed) : "–"),
          lmFact("Suicide pool: still in", su.left != null ? String(su.left) : "–"),
          su.killer ? lmFact("Cost the most", su.killer + (su.tied && su.tied.length ? " (tied with " + su.tied.join(", ") + ")" : "")) : null,
          lmFact("Big Loser points that week", String((rec.scores || []).reduce(function (a, x) { return a + (x.big_loser || 0); }, 0)))
        ])]));
    }
    kids.push(el("div", { class: "lm-links" }, [
      s.current ? el("button", { class: "lm-link", type: "button", onclick: function () { lmClose(false); state.week = n; go("weeks"); }, text: "Open week " + n + " on the site (replay, stories)" }) : null,
      s.current ? el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("broadcast", { week: n, kind: "recap" }); }, text: "Watch the week " + n + " recap" }) : null,
      el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("numbers", { tab: "distribution", week: n }); }, text: "Score spread in the Numbers Room" })
    ]));
    return el("div", { class: "tm-stack" }, kids);
  }

  // One coach across every season the site knows.
  function tmCoach(s, C, n) {
    var name = lmCoach(s), seasons = lmSeasons();
    var rows = seasons.map(function (x) {
      var me = (x.standings || []).filter(function (y) { return y.name === name; })[0];
      if (!me) return null;
      var st = lmStats(x), r = st.by[name];
      return { s: x, me: me, r: r };
    }).filter(Boolean);
    var bestSeason = rows.filter(function (x) { return x.me.place != null; }).sort(function (a, b) { return a.me.place - b.me.place; })[0];
    var xs = [];
    for (var k = 1; k <= C.last; k++) xs.push(k);
    function draw(width) {
      var lines = [{ name: name, role: "me", label: true, values: xs.map(function (k) { var c = C.byWeek[k]; return c && c.by[name] ? c.by[name].place : null; }) }];
      var wrap = lineChart(width, lines, { xs: xs, height: 240, min: 1, max: Math.max(2, C.cps[C.cps.length - 1].rows.length), invert: true,
        fmt: function (v) { return ordinal(Math.round(v)); }, title: name + "’s place by week" });
      tmMarker(wrap, width, xs, n);
      return lmClickWeeks(wrap, width, xs, function (k) { if (C.byWeek[k]) { LM.tm.tab = "standings"; tmSetWeek(k); } });
    }
    var trophies = typeof trophiesOf === "function" ? trophiesOf(name) : [];
    var r = lmStats(s).by[name];
    return el("div", { class: "tm-grid" }, [
      el("div", { class: "tm-stack" }, [
        el("div", { class: "lm-card" }, [el("h3", {}, [name + " in " + s.year + " ", lmSrc("calc")]),
          el("p", { class: "note", text: "Click a week to travel there." }), lmChart(240, draw, name + " by week"),
          r ? el("dl", { class: "lm-facts cols" }, [
            lmFact("Best week", r.best != null ? r.best + " (wk " + r.bestWeeks.join(", ") + ")" : "–"),
            lmFact("Worst week", r.worst != null ? r.worst + " (wk " + r.worstWeeks.join(", ") + ")" : "–"),
            lmFact("Weekly wins", r.wins ? r.wins + " (wk " + r.winWeeks.join(", ") + ")" : "0", "official"),
            lmFact("Highest place", r.bestPlace ? ordinal(r.bestPlace) : "–"),
            lmFact("Weeks in 1st", String(r.atTop)),
            lmFact("Biggest climb", r.rise && r.rise.v > 0 ? "+" + r.rise.v + " in wk " + r.rise.week : "–")
          ]) : null]),
        el("div", { class: "lm-card" }, [el("h3", { text: "Season by season" }),
          scroller(el("table", { class: "lm-table" }, [
            el("thead", {}, [el("tr", {}, ["Season", "Place", "Total", "Weekly wins", "Best week", "Status"].map(function (h) { return el("th", { text: h }); }))]),
            el("tbody", {}, rows.map(function (x) {
              return el("tr", { class: x.s.year === s.year ? "focus" : "" }, [
                el("td", {}, [el("button", { type: "button", class: "lm-wk", onclick: function () { LM.sel.season = String(x.s.year); LM.sel.week = 0; lmDraw(); }, text: String(x.s.year) })]),
                el("td", { class: "num", text: x.me.place != null ? ordinal(x.me.place) : "–" }), el("td", { class: "num", text: String(x.me.wins) }),
                el("td", { class: "num", text: String(x.me.weeks_won != null ? x.me.weeks_won : x.r ? x.r.wins : "–") }),
                el("td", { class: "num", text: x.r && x.r.best != null ? String(x.r.best) : "–" }),
                el("td", { text: x.s.current ? "after week " + x.s.through_week : x.s.complete ? "final" : "archived part-way" })]);
            }))])),
          bestSeason && rows.length > 1 ? el("p", { class: "note", text: "Best recorded finish: " + ordinal(bestSeason.me.place) + " in " + bestSeason.s.year + "." }) :
            el("p", { class: "note", text: rows.length > 1 ? "" : "Only this season is on record so far: past seasons appear here once they are archived." })]),
      ]),
      el("div", { class: "tm-side" }, [
        el("div", { class: "lm-card" }, [el("h3", { text: "Trophies" }),
          trophies.length ? el("ul", { class: "lm-list" }, trophies.map(function (a) { return el("li", {}, [el("b", { text: a.title + (a.current ? "" : " " + a.year) }), " - " + a.text]); }))
            : el("p", { class: "note", text: "No season trophies on record." })]),
        el("div", { class: "lm-links" }, [
          el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("numbers", { tab: "h2h", a: name }); }, text: "Head-to-head in the Numbers Room" }),
          el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("broadcast", { a: name, kind: "recap", spot: true }); }, text: "Coach spotlight broadcast" }),
          el("button", { class: "lm-link", type: "button", onclick: function () { lmClose(false); openCoach(name); }, text: name + "’s page on the site" })
        ])
      ])
    ]);
  }

  function tmEvents(s, C, n) {
    var evs = lmEvents(s), weeks = {};
    evs.forEach(function (e) { (weeks[e.week] = weeks[e.week] || []).push(e); });
    return el("div", { class: "lm-card tm-events" }, [
      el("h3", { text: "The " + s.year + " season, as it happened" }),
      el("p", { class: "note", text: "Every item is a recorded result or a sum of them. The archive keeps weeks, not times, so each is dated to its week." }),
      el("ol", { class: "tm-tl" }, Object.keys(weeks).map(Number).sort(function (a, b) { return a - b; }).map(function (k) {
        return el("li", { class: k === n ? "here" : "" }, [
          el("button", { type: "button", class: "lm-wk", onclick: function () { LM.tm.tab = "standings"; tmSetWeek(k); }, text: "Week " + k }),
          el("ul", {}, weeks[k].map(function (e) { return el("li", { class: "ev " + e.kind }, [lmSrc(e.src), " ", e.text]); }))
        ]);
      }))
    ]);
  }

  // Two points in time, two coaches, or two seasons at the same week.
  function tmCompare(s, C, n) {
    var kind = LM.tm.cmp === "seasons" ? "seasons" : "weeks", seasons = lmSeasons();
    var seg = el("div", { class: "lm-seg", role: "group", "aria-label": "Compare" }, [["weeks", "Two weeks"], ["seasons", "Two seasons"]].map(function (o) {
      return el("button", { type: "button", "aria-pressed": kind === o[0] ? "true" : "false", onclick: function () { LM.tm.cmp = o[0]; lmDraw(); }, text: o[1] });
    }));
    var body;
    if (kind === "weeks") {
      var other = LM.tm.cw && C.byWeek[LM.tm.cw] ? LM.tm.cw : C.weeks[0];
      var A = C.byWeek[other], B = C.byWeek[n];
      var pick = el("label", { class: "lm-pick" }, [el("span", { text: "Compare week " + n + " with" }),
        el("select", { onchange: function (e) { LM.tm.cw = Number(e.target.value); lmDraw(); } }, C.weeks.map(function (k) {
          return el("option", { value: String(k), selected: k === other, text: "Week " + k });
        }))]);
      var rows = B.rows.map(function (r) { var a = A.by[r.name]; return { r: r, a: a, d: a ? a.place - r.place : null }; })
        .sort(function (x, y) { return (y.d || 0) - (x.d || 0); });
      body = el("div", {}, [pick, el("p", { class: "note", text: "Places after week " + other + " against after week " + n + ". Up means more places gained between them." }),
        scroller(el("table", { class: "lm-table" }, [el("thead", {}, [el("tr", {}, ["Coach", "Wk " + other, "Wk " + n, "Change", "Wins between"].map(function (h) { return el("th", { text: h }); }))]),
          el("tbody", {}, rows.map(function (x) {
            return el("tr", {}, [el("td", {}, [lmWho(x.r.name)]), el("td", { class: "num", text: lmPlace(x.a) }), el("td", { class: "num", text: lmPlace(x.r) }),
              el("td", {}, [lmMove(other === n ? null : (other < n ? x.d : -x.d))]),
              el("td", { class: "num", text: x.a ? String(Math.abs(x.r.total - x.a.total)) : "–" })]);
          }))]))]);
    } else {
      var others = seasons.filter(function (x) { return x.year !== s.year; });
      if (!others.length) body = stateMsg("Only one season on record", "Comparing seasons needs another archived season. Each season is archived at its end; " +
        "earlier seasons can be added from the dashboard's season archive. Nothing is filled in until then.");
      else {
        var o = lmSeason(LM.tm.cs) && LM.tm.cs !== String(s.year) ? lmSeason(LM.tm.cs) : others[0], OC = lmCheckpoints(o);
        var same = OC.byWeek[n];
        body = el("div", {}, [el("label", { class: "lm-pick" }, [el("span", { text: "Compare with" }),
          el("select", { onchange: function (e) { LM.tm.cs = e.target.value; lmDraw(); } }, others.map(function (x) { return el("option", { value: String(x.year), selected: x === o, text: String(x.year) }); }))]),
          el("p", { class: "note", text: "Both seasons as they stood after week " + n + ". Scoring rules: a week's total is the games called right plus Big Loser points in every season on record; the number of games differs week to week with byes." }),
          el("div", { class: "cols even" }, [[s, C.byWeek[n]], [o, same]].map(function (pair) {
            var cpx = pair[1];
            return el("div", { class: "lm-card" }, [el("h3", { text: pair[0].year + " after week " + n }),
              cpx ? el("ol", { class: "lm-list" }, cpx.rows.slice(0, 5).map(function (r) { return el("li", { text: lmPlace(r) + ". " + r.name + " - " + r.total + (r.behind ? " (−" + r.behind + ")" : "") }); }))
                : el("p", { class: "note", text: "Week " + n + " of " + pair[0].year + " is not in the archive." })]);
          }))]);
      }
    }
    return el("div", { class: "lm-card" }, [el("h3", { text: "Compare" }), seg, body,
      el("div", { class: "lm-links" }, [el("button", { class: "lm-link", type: "button", onclick: function () { lmGo("numbers", { tab: "h2h" }); }, text: "Two coaches: head-to-head in the Numbers Room" })])]);
  }

  function tmSources(s, C) {
    var v = C.verify;
    var ok = v.checked && !v.off.length;
    return el("div", { class: "tm-stack" }, [
      el("div", { class: "lm-card" }, [el("h3", { text: "Where these figures come from" }),
        el("ul", { class: "lm-list" }, [
          el("li", {}, [lmSrc("official"), " Each coach's weekly total, each week's winners, top score and pool average: the pool's stats export and pick sheets, as the site publishes them" + (s.current ? "." : " (kept in the season archive).")]),
          el("li", {}, [lmSrc("calc"), " Standings after each earlier week: those weekly totals added up, equal totals sharing a place (1, 2, 2, 4) - the same rule the dashboard uses. The official order of tied coaches wasn't kept for past weeks."]),
          C.cps.length && C.cps[C.cps.length - 1].official ? el("li", {}, [lmSrc("official"), " Standings after week " + C.last + ": the official table's own places and moves, ties broken its way."]) : null,
          el("li", {}, [lmSrc("calc"), " Moves, gaps, leaders, streaks and milestones: worked out from the standings above."]),
          s.current ? el("li", {}, [lmSrc("official"), " Games, awards and side pools: each finished week's published recap."]) : null
        ])]),
      el("div", { class: "lm-card" }, [el("h3", { text: "Checked against the official table" }),
        v.checked ? el("p", {}, [ok ? "✓ " : "⚠ ", "After week " + v.week + ", " + v.matched + " of " + v.checked + " coaches are in exactly their official place" +
          (v.ties ? "; " + v.ties + " share a tie the official table orders" : "") + (v.off.length ? "; " + v.off.length + " differ: " +
            v.off.map(function (x) { return x.name + " (official " + x.official + ", worked out " + x.calc + ")"; }).join(", ") : "") + "."])
          : el("p", { class: "note", text: "No official table to check this season's last week against." })]),
      el("div", { class: "lm-card" }, [el("h3", { text: "Gaps in the archive" }),
        el("p", { text: C.missing.length ? "Weeks " + C.missing.join(", ") + " were played but aren't in the archive; the timeline marks them and nothing is filled in." : "No missing weeks: every played week of " + s.year + " is on record." }),
        el("p", { class: "note", text: lmSeasons().length < 2 ? "Only the " + s.year + " season is archived. Earlier seasons appear here once added to the dashboard's season archive." : plural(lmSeasons().length, "season") + " on record." }),
        el("p", { class: "note", text: "Week-by-week picks are kept for this season only; past seasons keep their weekly totals and final table. Nothing here was recorded with a time of day, so events are dated by week." })])
    ]);
  }
  // A season whose archive has only its final table.
  function tmFinalOnly(s) {
    var rows = (s.standings || []).slice().sort(function (a, b) { return (a.place || 999) - (b.place || 999); });
    return el("div", { class: "lm-card" }, [el("h3", {}, [s.year + " final table ", lmSrc("official")]),
      el("p", { class: "note", text: "Week-by-week totals weren't archived for this season, so the Time Machine can't show how it unfolded - only how it finished." }),
      el("ol", { class: "lm-list" }, rows.map(function (x) { return el("li", { text: (x.place || "–") + ". " + x.name + " - " + x.wins }); }))]);
  }
