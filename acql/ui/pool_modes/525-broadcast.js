  // ---- League Broadcast: the league as a TV show -----------------------------------------
  // An opening card, then segments that play by themselves or by hand. Weekly
  // Recap tells a finished week from its official results; Live follows the
  // week being played and says on every graphic that it is provisional. A
  // segment appears only when there is something real to put in it.
  var BC_DUR = 9000, BC_LONG = 13000;

  function bcSeason() {
    var all = lmSeasons();
    for (var i = 0; i < all.length; i++) if (all[i].current) return all[i];
    return all[0] || null;
  }
  function bcWeek(s) {
    var C = lmCheckpoints(s);
    return LM.sel.week && C.byWeek[LM.sel.week] ? LM.sel.week : C.last;
  }
  function bcLive() { return LM.bc.kind === "live" && hasLive(); }

  // ---- the segments of a finished week ----
  function bcRecapSegs(s, n) {
    var C = lmCheckpoints(s), cp = C.byWeek[n], i = C.cps.indexOf(cp), prev = i > 0 ? C.cps[i - 1] : null;
    var rec = lmWeekRec(s, n) || {}, segs = [], focus = lmCoach(s);
    var evs = lmEvents(s).filter(function (e) { return e.week === n; });
    var moved = cp.rows.filter(function (r) { return r.move != null; });
    var risers = moved.filter(function (r) { return r.move > 0; }).sort(function (a, b) { return b.move - a.move || a.place - b.place; }).slice(0, 3);
    var fallers = moved.filter(function (r) { return r.move < 0; }).sort(function (a, b) { return a.move - b.move || a.place - b.place; }).slice(0, 3);
    var second = cp.rows.filter(function (r) { return r.place > 1; })[0];

    // Opening headlines: the week's biggest stories, from the record.
    var heads = [];
    if (cp.winners.length) heads.push({ src: "official", text: listNames(cp.winners, 3) + (cp.winners.length > 1 ? " share week " : " wins week ") + n + " with " + plural(cp.top, "win") });
    evs.filter(function (e) { return e.kind === "lead" || e.kind === "record" || e.kind === "first"; }).forEach(function (e) { heads.push({ src: e.src, text: e.text }); });
    if (risers.length && risers[0].move >= 3) heads.push({ src: "calc", text: risers[0].name + " climbs " + plural(risers[0].move, "place") + " to " + ordinal(risers[0].place) });
    if (rec.suicide && rec.suicide.killed) heads.push({ src: "official", text: plural(rec.suicide.killed, "coach", "coaches") + " out of the suicide pool" + (rec.suicide.killer ? ", most on " + rec.suicide.killer : "") });
    if (!evs.some(function (e) { return e.kind === "lead"; }) && cp.leaders.length) heads.push({ src: "calc", text: listNames(cp.leaders, 2) + " still lead" + (cp.leaders.length > 1 ? "" : "s") + (second ? " by " + plural(cp.lead - second.total, "win") : "") });
    if (heads.length) segs.push({ id: "headlines", title: "Opening headlines", kicker: "Week " + n, src: "official", sum: heads[0].text,
      draw: function () { return el("ol", { class: "bc-heads" }, heads.slice(0, 5).map(function (h, k) { return el("li", { style: "--i:" + k }, [lmSrc(h.src), el("span", { text: h.text })]); })); } });

    segs.push({ id: "board", title: "The leaderboard", kicker: "Season standings after week " + n, src: cp.official ? "official" : "calc", long: true,
      sum: listNames(cp.leaders, 2) + " lead" + (cp.leaders.length > 1 ? "" : "s") + " on " + cp.lead,
      draw: function (animate) { return bcBoard(s, C, cp, prev, focus, animate); } });

    if (risers.length || fallers.length) segs.push({ id: "movers", title: "Risers and fallers", kicker: prev ? "Week " + prev.week + " to week " + n : "Week " + n, src: cp.official ? "official" : "calc",
      sum: risers.length ? risers[0].name + " +" + risers[0].move : fallers[0].name + " " + fallers[0].move,
      draw: function () {
        function col(list, up) {
          return el("div", { class: "bc-col " + (up ? "up" : "dn") }, [el("h3", { text: up ? "Rising" : "Falling" })].concat(list.length ? list.map(function (r, k) {
            return el("div", { class: "bc-mover", style: "--i:" + k }, [el("span", { class: "big", text: (up ? "+" : "−") + Math.abs(r.move) }),
              el("div", {}, [el("b", { text: r.name }), el("span", { text: "now " + ordinal(r.place) + (r.tied ? " (tied)" : "") + " · " + plural(r.score == null ? 0 : r.score, "win") + " this week" })])]);
          }) : [el("p", { class: "note", text: up ? "Nobody climbed." : "Nobody dropped." })]));
        }
        return el("div", { class: "bc-two" }, [col(risers, true), col(fallers, false)]);
      } });

    if (cp.winners.length) {
      var runner = cp.rows.filter(function (r) { return r.score != null && cp.winners.indexOf(r.name) < 0; }).sort(function (a, b) { return b.score - a.score; })[0];
      segs.push({ id: "winners", title: cp.winners.length > 1 ? "Weekly winners" : "Weekly winner", kicker: "Week " + n, src: "official",
        sum: listNames(cp.winners, 3) + " (" + cp.top + ")",
        draw: function () {
          return el("div", { class: "bc-winner" }, [
            el("div", { class: "bc-names" }, cp.winners.map(function (w, k) { return el("b", { style: "--i:" + k, text: w }); })),
            el("div", { class: "bc-stats" }, [
              bcStat(String(cp.top), "wins" + (cp.most ? " of " + cp.most : "")),
              runner ? bcStat("+" + (cp.top - runner.score), "over the next card") : null,
              bcStat(lmFix(cp.average, 1), "pool average"),
              rec.payout_each != null ? bcStat(money(rec.payout_each), cp.winners.length > 1 ? "each" : "won") : null
            ]),
            rec.awards && rec.awards.length ? el("ul", { class: "bc-awards" }, rec.awards.slice(0, 4).map(function (a) { return el("li", {}, [el("b", { text: a.title }), " " + a.who]); })) : null
          ]);
        } });
    }

    // Matchup of the week: a game that decided the week, else the one that split the pool most.
    var close = rec.so_close && rec.so_close.outcomes && rec.so_close.outcomes.length ? rec.so_close.outcomes[0] : null;
    var games = lmGames(n, n);
    var divider = games.slice().sort(function (a, b) { return b.split - a.split; })[0];
    if (close && close.games && close.games.length) {
      var g0 = close.games[0], real = games.filter(function (g) { return g.matchup === g0.matchup; })[0];
      segs.push({ id: "matchup", title: "Matchup of the week", kicker: g0.matchup, src: "hypo",
        sum: g0.matchup + " decided the week",
        draw: function () {
          return el("div", { class: "bc-match" }, [
            el("div", { class: "bc-game" }, [el("b", { text: g0.matchup }), el("span", { text: (g0.was || (real && real.winner) || "") + " won" + (real ? " · " + real.right + " of " + real.cards + " cards had them" : "") })]),
            el("p", { class: "bc-line" }, [lmSrc("hypo"), " Had " + g0.instead + " won instead, " + listNames(close.who, 2) + " would have " + (close.who.length > 1 ? "shared" : "won") + " the week with " + close.score + "."]),
            el("p", { class: "note", text: "Worked out from the recorded cards: the week's other results left as they were." })
          ]);
        } });
    } else if (divider) {
      segs.push({ id: "matchup", title: "Matchup of the week", kicker: divider.matchup, src: "official", sum: divider.matchup + " split the pool",
        draw: function () {
          return el("div", { class: "bc-match" }, [el("div", { class: "bc-game" }, [el("b", { text: divider.matchup }), el("span", { text: divider.winner + " won" })]),
            el("div", { class: "bc-split" }, [el("i", { style: "width:" + Math.round(100 * divider.pct) + "%" }), el("span", { text: divider.right + " right · " + divider.wrong + " wrong" })]),
            el("p", { class: "note", text: "The game that divided the pool most this week." })]);
        } });
    }

    // Rivalry report: first against second, and the closest pair near the top that swapped places.
    if (second) {
      var leader = cp.rows[0], vs = lmVs(s, leader.name, second.name, C.weeks[0], n);
      var before = prev ? (prev.by[leader.name] ? prev.by[leader.name].total : 0) - (prev.by[second.name] ? prev.by[second.name].total : 0) : null;
      var swap = null;
      if (prev) cp.rows.slice(0, 10).forEach(function (r) {
        cp.rows.slice(0, 10).forEach(function (q) {
          if (swap || r.name === q.name || !prev.by[r.name] || !prev.by[q.name]) return;
          if (r.place < q.place && prev.by[r.name].place > prev.by[q.name].place) swap = { up: r, down: q };
        });
      });
      segs.push({ id: "rivalry", title: "Rivalry report", kicker: leader.name + " v " + second.name, src: "calc",
        sum: leader.name + " v " + second.name + ": " + (leader.total - second.total ? plural(leader.total - second.total, "win") + " apart" : "level"),
        draw: function () {
          var gap = leader.total - second.total;
          return el("div", { class: "bc-rival" }, [
            el("div", { class: "bc-vs" }, [el("div", {}, [el("b", { text: leader.name }), el("span", { class: "big", text: String(leader.total) })]),
              el("div", { class: "mid" }, [el("span", { text: gap ? "gap " + gap : "level" }), before != null ? el("span", { class: "note", text: "was " + before + " a week ago" }) : null]),
              el("div", {}, [el("b", { text: second.name }), el("span", { class: "big", text: String(second.total) })])]),
            el("p", { text: "This season, week against week: " + leader.name + " " + vs.aw + ", " + second.name + " " + vs.bw + (vs.ties ? ", level " + vs.ties : "") + "." +
              (vs.shared && vs.shared.games ? " Same side in " + vs.shared.same + " of " + vs.shared.games + " games." : "") }),
            swap ? el("p", { class: "bc-line" }, [lmSrc("calc"), " Also: " + swap.up.name + " passed " + swap.down.name + " - now " + ordinal(swap.up.place) + " and " + ordinal(swap.down.place) + "."]) : null
          ]);
        } });
    }

    // Records watch: season and league records set or matched this week.
    var recs = lmRecords().filter(function (r) { return r.holders.some(function (h) { return h.week === n && h.year === s.year; }); });
    var pbs = cp.rows.filter(function (r) {
      if (r.score == null) return false;
      var before_ = C.cps.slice(0, i).map(function (c) { return c.by[r.name] ? c.by[r.name].score : null; }).filter(function (v) { return v != null; });
      return before_.length >= 2 && r.score > Math.max.apply(null, before_);
    }).sort(function (a, b) { return b.score - a.score; });
    if (recs.length || pbs.length || evs.some(function (e) { return e.kind === "record"; })) segs.push({ id: "records", title: "Records watch", kicker: "Week " + n, src: "calc",
      sum: recs.length ? recs[0].label + ": " + recs[0].value : pbs.length + " personal bests",
      draw: function () {
        return el("div", { class: "bc-recs" }, [
          recs.length ? el("ul", { class: "bc-heads" }, recs.map(function (r, k) {
            var who_ = r.holders.filter(function (h) { return h.week === n && h.year === s.year; }).map(function (h) { return h.name; });
            return el("li", { style: "--i:" + k }, [lmSrc(r.kind), el("span", { text: r.label + " (" + (lmRecords().length ? "every season on record" : "") + "): " + listNames(who_, 2) + ", " + (r.id === "margin" ? "+" + lmFix(r.value, 2) : r.value) + " " + lmUnit(r.value, r.unit) + (r.holders.length > who_.length ? " - matching " + (r.holders.length - who_.length) + " earlier" : "") })]);
          })) : null,
          pbs.length ? el("p", {}, [lmSrc("calc"), " Season bests this week: " + pbs.slice(0, 5).map(function (r) { return r.name + " " + r.score; }).join(", ") + (pbs.length > 5 ? " +" + (pbs.length - 5) + " more" : "") + "."]) : null
        ]);
      } });

    // Side pools.
    var blTop = (rec.scores || []).filter(function (x) { return x.big_loser; }).sort(function (a, b) { return b.big_loser - a.big_loser; });
    if ((rec.suicide && (rec.suicide.killed != null || rec.suicide.left != null)) || blTop.length) segs.push({ id: "pools", title: "Side pool spotlight", kicker: "Week " + n, src: "official",
      sum: rec.suicide && rec.suicide.left != null ? rec.suicide.left + " left in the suicide pool" : "Big Loser",
      draw: function () {
        var su = rec.suicide || {};
        return el("div", { class: "bc-two" }, [
          el("div", { class: "bc-col" }, [el("h3", { text: "Suicide pool" }),
            el("div", { class: "bc-stats" }, [bcStat(su.killed != null ? String(su.killed) : "–", "knocked out"), bcStat(su.left != null ? String(su.left) : "–", "still in")]),
            su.killer ? el("p", { text: su.killer + " cost the most" + (su.tied && su.tied.length ? " (with " + su.tied.join(", ") + ")" : "") + "." }) : null]),
          el("div", { class: "bc-col" }, [el("h3", { text: "Big Loser" }),
            blTop.length ? el("ul", { class: "bc-awards" }, blTop.slice(0, 4).map(function (x) { return el("li", {}, [el("b", { text: x.name }), " " + plural(x.big_loser, "point")]); }))
              : el("p", { class: "note", text: "No Big Loser points this week." })])
        ]);
      } });

    // Championship race.
    segs.push({ id: "race", title: "Championship race", kicker: "After week " + n, src: "calc", sum: bcRaceLine(s, C, cp),
      draw: function () { return bcRace(s, C, cp); } });

    // Coach spotlight.
    if (cp.by[focus]) segs.push({ id: "spotlight", title: "Coach spotlight", kicker: focus, src: "calc", sum: focus + ": " + ordinal(cp.by[focus].place),
      draw: function () { return bcSpotlight(s, C, cp, focus); } });

    segs.push({ id: "final", title: "Final recap", kicker: "Week " + n + " in a minute", src: "official",
      draw: function () { return bcFinal(s, C, cp, segs); } });
    return segs;
  }
  function bcStat(big, small) { return el("div", { class: "bc-stat" }, [el("b", { text: big }), el("span", { text: small })]); }

  // The board revealed from the bottom up, then the rows slide from last week's places to this week's.
  function bcBoard(s, C, cp, prev, focus, animate) {
    var full = !!LM.bc.full;
    var shown = full ? cp.rows : cp.rows.slice(0, 10);
    if (!full && cp.by[focus] && shown.indexOf(cp.by[focus]) < 0) shown = shown.concat([cp.by[focus]]);
    var startAt = null;
    if (animate && prev) {
      var order = shown.slice().sort(function (a, b) { var pa = prev.by[a.name], pb = prev.by[b.name]; return (pa ? pa.place : 999) - (pb ? pb.place : 999); });
      startAt = {};
      order.forEach(function (r, k) { startAt[r.name] = k; });
    }
    // one board per showing: a quiet redraw (pause, a live refresh) keeps it mid-slide
    var key = "bc-" + cp.week + (full ? "-full" : "") + "-" + LM.bc.anim;
    var reveal = animate && !reducedMotion();
    var board = lmBoard(key, shown, { rowH: 44, cls: "bc-board" + (reveal ? " reveal" : ""), label: "Standings after week " + cp.week, startAt: startAt,
      delay: reveal && startAt ? 1700 : 0,
      rowClass: function (r) { return (r.name === focus ? "focus " : "") + (r.place === 1 ? "first " : "") + (isMe(r.name) ? "me" : ""); },
      cells: function (r, k) {
        var tag = cp.winners.indexOf(r.name) >= 0 ? el("span", { class: "lm-tag gold", text: "Week winner" }) : null;
        var cells = [el("span", { class: "pl", text: lmPlace(r) }), lmMove(r.move), el("span", { class: "nm" }, [el("b", { text: r.name }), tag]),
          el("span", { class: "wk", title: "This week", text: r.score == null ? "–" : "+" + r.score }), el("span", { class: "tot", text: String(r.total) }),
          el("span", { class: "gap", text: r.behind ? "−" + r.behind : "lead" })];
        return cells;
      } });
    if (reveal) Array.prototype.forEach.call(board.children, function (li, k) { li.style.setProperty("--i", String(shown.length - 1 - k)); });
    return el("div", { class: "bc-boardwrap" }, [
      el("div", { class: "lm-board-head bc", "aria-hidden": "true" }, ["#", "", "Coach", "Week", "Total", "Gap"].map(function (t) { return el("span", { text: t }); })),
      board,
      el("div", { class: "bc-boardfoot" }, [
        el("span", { class: "note", text: cp.official ? "The official table: places and moves as the pool's standings give them." : (prev ? "Moves are against the standings after week " + prev.week + ". " : "") + "Equal totals share a place (the official order of ties wasn't kept for past weeks)." }),
        el("button", { class: "lm-btn txt", type: "button", onclick: function () { LM.bc.full = !full; bcPause(); lmDraw(); }, text: full ? "Top ten" : "Whole table" })
      ])
    ]);
  }

  // How the race stands, without claiming more than the numbers allow.
  function bcRaceFacts(s, C, cp) {
    var R = DATA.race || {}, perfect = Number(R.perfect_week) || null, total = C.seasonWeeks;
    var left = Math.max(0, total - cp.week), most = perfect ? left * perfect : null;
    var leader = cp.rows[0], second = cp.rows.filter(function (r) { return r.place > 1; })[0];
    var alive = most == null ? null : cp.rows.filter(function (r) { return r.behind <= most; }).length;
    var clinched = !!(most != null && second && second.behind > most && cp.leaders.length === 1);
    var over = left === 0 && (!s.current || s.complete);
    return { left: left, perfect: perfect, most: most, leader: leader, second: second, alive: alive, clinched: clinched, over: over };
  }
  function bcRaceLine(s, C, cp) {
    var f = bcRaceFacts(s, C, cp);
    if (f.over) return listNames(cp.leaders, 2) + " finished first";
    if (f.clinched) return cp.leaders[0] + " can't be caught";
    return listNames(cp.leaders, 2) + (f.second ? " by " + plural(cp.lead - f.second.total, "win") : "") + ", " + plural(f.left, "week") + " left";
  }
  function bcRace(s, C, cp) {
    var f = bcRaceFacts(s, C, cp), T = DATA.title_by_week || {}, ti = (T.weeks || []).indexOf(cp.week);
    var top = cp.rows.slice(0, 6), lead = cp.lead;
    function odds(name) { return ti >= 0 && T.odds && T.odds[name] ? T.odds[name][ti] : null; }
    var verdict = f.over ? "The season is over: " + listNames(cp.leaders, 2) + " finished first." :
      f.clinched ? cp.leaders[0] + " has clinched: the gap to second (" + f.second.behind + ") is more than the " + f.most + " wins left at most." :
      f.most != null ? plural(f.alive, "coach", "coaches") + " can still catch the lead on paper: " + plural(f.left, "week") + " left, at most " + f.perfect + " wins a week (" + f.most + " in all)." :
      plural(f.left, "week") + " left.";
    return el("div", { class: "bc-race" }, [
      el("div", { class: "bc-bars" }, top.map(function (r, k) {
        var o = odds(r.name);
        return el("div", { class: "bc-bar" + (r.place === 1 ? " first" : ""), style: "--i:" + k }, [
          el("span", { class: "pl", text: lmPlace(r) }), el("b", { text: r.name }),
          el("span", { class: "track" }, [el("i", { style: "width:" + Math.max(4, Math.round(100 * r.total / Math.max(1, lead))) + "%" })]),
          el("span", { class: "tot", text: String(r.total) }), el("span", { class: "gap", text: r.behind ? "−" + r.behind : "lead" }),
          o != null ? el("span", { class: "odds", title: "Title chance from the site's simulation after week " + cp.week, text: (o < 1 ? "<1" : Math.round(o)) + "%" }) : null
        ]);
      })),
      el("p", { class: "bc-line" }, [lmSrc("calc"), " " + verdict]),
      ti >= 0 ? el("p", { class: "note" }, [lmSrc("est"), " Percentages are title chances from the site's own simulation of the weeks left - estimates, not results."]) : null
    ]);
  }
  function bcSpotlight(s, C, cp, name) {
    var r = cp.by[name], st = lmStats(s, C.weeks[0], cp.week).by[name], f = typeof form === "function" && s.current ? form(name) : null;
    var rival = lmRival(s, name), v = rival ? lmVs(s, name, rival, C.weeks[0], cp.week) : null;
    var trophies = typeof trophiesOf === "function" ? trophiesOf(name).filter(function (a) { return a.current; }) : [];
    var others = lmSeasons().filter(function (x) { return !x.current; }).map(function (x) {
      var me = (x.standings || []).filter(function (y) { return y.name === name; })[0];
      return me ? x.year + ": " + (me.place ? ordinal(me.place) : "–") : null;
    }).filter(Boolean);
    var xs = C.weeks.filter(function (k) { return k <= cp.week; });
    return el("div", { class: "bc-spot" }, [
      el("div", { class: "bc-spot-id" }, [el("span", { class: "bc-mono", text: initials(name) }), el("div", {}, [el("b", { text: name }),
        el("span", { text: ordinal(r.place) + (r.tied ? " (tied)" : "") + " · " + plural(r.total, "win") + (r.behind ? " · " + r.behind + " behind" : " · leading") })])]),
      el("div", { class: "bc-stats" }, [
        bcStat(r.score == null ? "–" : String(r.score), "this week"), bcStat(lmSigned(r.vsAvg, 1), "vs the average"),
        st && st.best != null ? bcStat(String(st.best), "best (wk " + st.bestWeeks.join(", ") + ")") : null,
        st ? bcStat(String(st.wins), "weekly wins") : null, st && st.bestPlace ? bcStat(ordinal(st.bestPlace), "highest place") : null
      ]),
      lmChart(150, function (width) {
        var wrap = lineChart(width, [{ name: name, role: "me", label: true, values: xs.map(function (k) { var x = C.byWeek[k].by[name]; return x ? x.place : null; }) }],
          { xs: xs, height: 150, min: 1, max: cp.rows.length, invert: true, title: name + "'s place", fmt: function (q) { return ordinal(Math.round(q)); } });
        return wrap;
      }, name + " by week"),
      el("ul", { class: "bc-awards" }, [
        f ? el("li", { text: formText(f) }) : null,
        v ? el("li", { text: "Against " + rival + " (nearest in the table): ahead " + v.aw + " weeks, behind " + v.bw + (v.ties ? ", level " + v.ties : "") }) : null,
        trophies.length ? el("li", { text: "Holds: " + trophies.map(function (a) { return a.title; }).join(", ") }) : null,
        others.length ? el("li", { text: "Past seasons: " + others.join(", ") }) : el("li", { class: "note", text: "No earlier season on record to compare with." })
      ]),
      el("div", { class: "bc-pickrow" }, [lmPicker(s, name, function (x) { LM.sel.a = x; bcPause(); lmDraw(); }, "Spotlight on")])
    ]);
  }
  function bcFinal(s, C, cp, segs) {
    var facts = bcFacts(s, C, cp), hash = lmHash(JSON.stringify(facts)), seen = bcSeen(cp.week, hash);
    return el("div", { class: "bc-final" }, [
      el("ul", { class: "bc-heads" }, segs.filter(function (g) { return g.sum && g.id !== "final"; }).map(function (g, k) {
        return el("li", { style: "--i:" + k }, [lmSrc(g.src), el("span", {}, [el("b", { text: g.title + ": " }), g.sum])]);
      })),
      el("p", { class: "note" }, ["Built from week " + cp.week + "’s official results · recap data #" + hash +
        (seen.changed ? " - the figures have changed since you first watched this recap on " + seen.first + " (a correction or ruling)." : seen.first ? " · unchanged since " + seen.first : "")]),
      el("div", { class: "bc-share" }, [
        el("button", { class: "lm-btn txt", type: "button", onclick: function () { bcShare("board", s, C, cp); } }, [icon("share"), " Leaderboard picture"]),
        el("button", { class: "lm-btn txt", type: "button", onclick: function () { bcShare("movers", s, C, cp); } }, [icon("share"), " Risers & fallers picture"]),
        el("button", { class: "lm-btn txt", type: "button", onclick: function () { bcShare("race", s, C, cp); } }, [icon("share"), " Title race picture"]),
        el("button", { class: "lm-btn txt", type: "button", onclick: function () { lmDownload("acql-" + s.year + "-week-" + cp.week + "-recap.json", JSON.stringify(Object.assign({ fingerprint: hash }, facts), null, 1), "application/json"); } }, [lmGlyph("down"), " Recap data"])
      ])
    ]);
  }
  // The facts a recap is made of - the same in, the same recap out.
  function bcFacts(s, C, cp) {
    return { season: s.year, week: cp.week, winners: cp.winners, top: cp.top, average: cp.average,
      sources: "weekly totals, winners and average: official; standings: calculated (competition ranking)",
      standings: cp.rows.map(function (r) { return [r.name, r.score, r.total, (r.tied ? "T" : "") + r.place, r.move]; }) };
  }
  // The first time this viewer watched a week's recap, and with which figures.
  function bcSeen(week, hash) {
    var all = storedJSON("acql-bc-recaps") || {}, key = String(week), was = all[key];
    var today = new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" });
    if (!was) { all[key] = { hash: hash, first: today }; storeJSON("acql-bc-recaps", all); return { first: "", changed: false }; }
    return { first: was.first, changed: was.hash !== hash };
  }

  // ---- live ----
  function bcLiveSegs() {
    var t = liveTally(), ph = phase(t), fr = freshness(), wk = DATA.live.week, segs = [];
    var on = gamesOn(t), done = t.games.filter(function (x) { return x.state === "post"; }).length;
    var rows = t.rows.slice(), sim = null;
    try { sim = ph === "gameday" || ph === "final" ? simulate(t) : null; } catch (e) { sim = null; }
    var label = ph === "final" ? "Games over - not yet official" : ph === "preview" ? "Before kickoff" : "Provisional · " + dataLabel(fr);
    segs.push({ id: "live-board", title: "Live leaderboard", kicker: "Week " + wk + " · " + label, src: "prov", long: true,
      draw: function () {
        var top = rows.slice(0, 10);
        var me = rows.filter(function (r) { return r.c.name === lmCoach(); })[0];
        if (me && top.indexOf(me) < 0) top = top.concat([me]);
        var ranks = lmRank(rows.reduce(function (o, r) { o[r.c.name] = r.now; return o; }, {}));
        var board = lmBoard("bc-live-" + wk, top.map(function (r) { return { name: r.c.name, r: r, k: ranks[r.c.name] }; }), { rowH: 44, cls: "bc-board", label: "Week " + wk + " so far",
          rowClass: function (x) { return x.name === lmCoach() ? "focus" : ""; },
          cells: function (x) {
            return [el("span", { class: "pl", text: (x.k.tied ? "T" : "") + x.k.place }), el("span", { class: "lm-mv none" }),
              el("span", { class: "nm" }, [el("b", { text: x.name }), x.r.left ? el("span", { class: "lm-tag", text: x.r.left + " to play" }) : null]),
              el("span", { class: "wk", text: String(x.r.now) }), el("span", { class: "tot", title: "Season total if it ended now", text: String(x.r.season) }),
              el("span", { class: "gap", text: sim && sim.chance[x.name] != null ? pct(sim.chance[x.name]) : "" })];
          } });
        return el("div", { class: "bc-boardwrap" }, [
          el("div", { class: "lm-board-head bc", "aria-hidden": "true" }, ["#", "", "Coach", "Week", "Season", sim ? "Win wk" : ""].map(function (x) { return el("span", { text: x }); })),
          board,
          el("p", { class: "note" }, [lmSrc("prov"), " Wins so far, counting games still in progress as they stand. ", sim ? lmSrc("est") : null, sim ? " Win-week chances are the site's simulation." : ""])
        ]);
      } });
    segs.push({ id: "live-games", title: "On the field", kicker: on + " live · " + done + " final · " + (t.games.length - on - done) + " to come", src: "prov",
      draw: function () {
        var order = t.games.slice().sort(function (a, b) { var r = { "in": 0, pre: 1, post: 2 }; return r[a.state] - r[b.state]; });
        return el("div", { class: "bc-games" }, order.slice(0, 9).map(function (x, k) {
          var sp = poolSplit(x.g);
          return el("div", { class: "bc-g " + x.state, style: "--i:" + k }, [
            el("b", { text: x.g.a + " " + (x.as == null ? "" : x.as) + " @ " + x.g.h + " " + (x.hs == null ? "" : x.hs) }),
            el("span", { text: (x.state === "in" ? "● " + (liveDetail(x) || "Live") : x.state === "post" ? "Final" : x.kick ? kickFull(x.kick) : "To come") + " · pool " + sp.a + "–" + sp.h })
          ]);
        }));
      } });
    var sui = { safe: 0, out: 0, pending: 0, live: 0 };
    t.rows.forEach(function (r) { if (!r.sui) return; if (r.sui === "safe") sui.safe++; else if (r.sui === "out") sui.out++; else if (r.sui === "pending") sui.pending++; else sui.live++; });
    if (sui.safe + sui.out + sui.pending + sui.live) segs.push({ id: "live-pools", title: "Suicide pool watch", kicker: "Week " + wk, src: "prov",
      draw: function () { return el("div", { class: "bc-stats" }, [bcStat(String(sui.safe), "safe"), bcStat(String(sui.live), "playing now"), bcStat(String(sui.pending), "still to play"), bcStat(String(sui.out), "out")]); } });
    segs.push({ id: "live-race", title: "Championship race, live", kicker: "If the week ended now", src: "prov",
      draw: function () {
        var bySeason = t.rows.slice().sort(function (a, b) { return b.season - a.season; }).slice(0, 6), top = bySeason.length ? bySeason[0].season : 1;
        var placed = lmRank(t.rows.reduce(function (o, r) { o[r.c.name] = r.season; return o; }, {}));
        return el("div", { class: "bc-race" }, [el("div", { class: "bc-bars" }, bySeason.map(function (r, k) {
          return el("div", { class: "bc-bar" + (k === 0 ? " first" : ""), style: "--i:" + k }, [el("span", { class: "pl", text: (placed[r.c.name].tied ? "T" : "") + placed[r.c.name].place }), el("b", { text: r.c.name }),
            el("span", { class: "track" }, [el("i", { style: "width:" + Math.max(4, Math.round(100 * r.season / Math.max(1, top))) + "%" })]),
            el("span", { class: "tot", text: String(r.season) }), el("span", { class: "gap", text: r.season === top ? "lead" : "−" + (top - r.season) })]);
        })), el("p", { class: "note" }, [lmSrc("prov"), " Official standings change only when the week's results are entered."])]);
      } });
    return segs;
  }

  // ---- the show ----
  function bcSegs(s) { return bcLive() ? bcLiveSegs() : bcRecapSegs(s, bcWeek(s)); }
  function bcPause() { LM.bc.playing = false; if (LM.bc.timer) { clearTimeout(LM.bc.timer); LM.bc.timer = null; } }
  function bcSchedule(segs) {
    if (LM.bc.timer) { clearTimeout(LM.bc.timer); LM.bc.timer = null; }
    if (!LM.bc.playing || LM.mode !== "broadcast") return;
    var seg = segs[LM.bc.seg], dur = LM.bc.intro ? 6500 : seg && seg.long ? BC_LONG : BC_DUR;
    LM.bc.t0 = Date.now();
    LM.bc.timer = setTimeout(function () {
      LM.bc.timer = null;
      if (LM.mode !== "broadcast" || !LM.bc.playing) return;
      if (LM.bc.intro) bcGo(0, true);
      else if (LM.bc.seg < bcSegs(bcSeason()).length - 1) bcGo(LM.bc.seg + 1, true);
      else { LM.bc.playing = false; lmDraw(); }
    }, dur);
  }
  function bcGo(i, auto) {
    LM.bc.intro = false;
    LM.bc.seg = i;
    LM.bc.anim = String(Date.now());
    if (!auto) bcPause();
    lmDraw();
  }
  function bcView(opts) {
    var s = bcSeason();
    if (!s) return el("div", { class: "lm-body bc" }, [stateMsg("Nothing to broadcast yet", "The show starts once a week has been graded.")]);
    if (LM.bc.kind === "live" && !hasLive()) LM.bc.kind = "recap";
    var C = lmCheckpoints(s);
    if (!C.cps.length && !bcLive()) return el("div", { class: "lm-body bc" }, [stateMsg("Nothing to broadcast yet", "The show starts once a week has been graded.")]);
    var segs = bcSegs(s);
    if (LM.bc.spot) {
      LM.bc.spot = false;
      LM.bc.intro = false;
      var sp = segs.map(function (g) { return g.id; }).indexOf("spotlight");
      if (sp >= 0) { LM.bc.seg = sp; LM.bc.anim = String(Date.now()); LM.bc.playing = false; }
    }
    if (LM.bc.seg >= segs.length) LM.bc.seg = segs.length - 1;
    var n = bcWeek(s), seg = segs[LM.bc.seg];
    // play the entrance only when the segment is new - a live refresh just updates it
    var animKey = (bcLive() ? "live" : n) + ":" + LM.bc.seg + ":" + LM.bc.anim + ":" + LM.bc.intro;
    var animate = LM.bc.drawn !== animKey && !opts.quiet;
    LM.bc.drawn = animKey;
    if (animate) bcSchedule(segs);
    var stage = LM.bc.intro ? bcIntro(s, C, n) : el("section", { class: "bc-seg" + (animate ? " enter" : ""), "aria-live": "polite", "data-seg": seg.id }, [
      el("div", { class: "bc-title" }, [el("span", { class: "k", text: seg.kicker }), el("h2", { text: seg.title }), lmSrc(seg.src)]),
      seg.draw(animate)
    ]);
    var weeks = C.weeks;
    return el("div", { class: "lm-body bc" + (bcLive() ? " live" : "") }, [
      el("div", { class: "bc-bar-top" }, [
        el("div", { class: "lm-seg", role: "group", "aria-label": "Broadcast" }, [
          el("button", { type: "button", "aria-pressed": !bcLive() ? "true" : "false", onclick: function () { LM.bc.kind = "recap"; LM.bc.seg = 0; LM.bc.intro = true; LM.bc.playing = !reducedMotion(); lmDraw(); }, text: "Weekly recap" }),
          el("button", { type: "button", "aria-pressed": bcLive() ? "true" : "false", disabled: !hasLive(), title: hasLive() ? "Follow week " + DATA.live.week + " as it is played" : "No week is being played",
            onclick: function () { LM.bc.kind = "live"; LM.bc.seg = 0; LM.bc.intro = true; LM.bc.playing = !reducedMotion(); lmDraw(); }, text: hasLive() ? "Live · week " + DATA.live.week : "Live" })
        ]),
        !bcLive() ? el("label", { class: "lm-pick" }, [el("span", { text: "Week" }), el("select", { onchange: function (e) { LM.sel.week = Number(e.target.value); LM.bc.seg = 0; LM.bc.intro = true; LM.bc.playing = !reducedMotion(); lmDraw(); } },
          weeks.map(function (k) { return el("option", { value: String(k), selected: k === n, text: "Week " + k + (k === C.last ? " (latest)" : "") }); }))]) : null,
        bcLive() ? el("span", { class: "bc-prov" }, [el("i", {}), "PROVISIONAL - games in progress"]) : el("span", { class: "bc-final-tag", text: "FINAL · official results" })
      ]),
      el("div", { class: "bc-stage" }, [stage]),
      el("div", { class: "bc-ctl" }, [
        el("div", { class: "bc-btns", role: "group", "aria-label": "Broadcast controls" }, [
          lmCtl("prev", "Previous segment", function () { bcGo(Math.max(0, LM.bc.intro ? 0 : LM.bc.seg - 1)); }, { disabled: LM.bc.intro || LM.bc.seg === 0 }),
          lmCtl(LM.bc.playing ? "pause" : "play", LM.bc.playing ? "Pause" : "Play", function () {
            if (LM.bc.playing) { bcPause(); lmDraw({ quiet: true }); } else { LM.bc.playing = true; if (!LM.bc.intro && LM.bc.seg >= segs.length - 1) bcGo(0, true); else { bcSchedule(segs); lmDraw({ quiet: true }); } }
          }, { class: "lm-btn big", "aria-pressed": LM.bc.playing ? "true" : "false" }),
          lmCtl("next", "Next segment", function () { bcGo(LM.bc.intro ? 0 : Math.min(segs.length - 1, LM.bc.seg + 1)); }, { disabled: !LM.bc.intro && LM.bc.seg >= segs.length - 1 }),
          lmCtl("replay", "Replay from the opening", function () { LM.bc.intro = true; LM.bc.seg = 0; LM.bc.anim = String(Date.now()); LM.bc.playing = !reducedMotion(); lmDraw(); }),
          LM.bc.intro ? el("button", { class: "lm-btn txt bc-skip", type: "button", onclick: function () { bcGo(0, LM.bc.playing); } }, [lmGlyph("skip"), " Skip intro"]) : null
        ]),
        el("ol", { class: "bc-dots", "aria-label": "Segments" }, segs.map(function (g, k) {
          return el("li", {}, [el("button", { type: "button", class: (k === LM.bc.seg && !LM.bc.intro ? "on" : "") + (k < LM.bc.seg && !LM.bc.intro ? " done" : ""),
            "aria-current": k === LM.bc.seg && !LM.bc.intro ? "step" : null, title: g.title, onclick: function () { bcGo(k); } }, [el("span", { text: g.title })])]);
        })),
        LM.bc.playing ? el("div", { class: "bc-progress", style: "--dur:" + (LM.bc.intro ? 6500 : seg && seg.long ? BC_LONG : BC_DUR) + "ms;--off:-" + Math.max(0, Date.now() - (LM.bc.t0 || Date.now())) + "ms" }, [el("i", {})]) : null
      ])
    ]);
  }
  function bcIntro(s, C, n) {
    var live = bcLive(), cp = C.byWeek[n];
    var big = null, t = live ? liveTally() : null;
    if (!live && cp) {
      var m = cp.rows.filter(function (r) { return r.move; }).sort(function (a, b) { return Math.abs(b.move) - Math.abs(a.move); })[0];
      if (m) big = m.name + " " + (m.move > 0 ? "up " : "down ") + plural(Math.abs(m.move), "place");
    }
    var lead = live ? t.rows.slice().sort(function (a, b) { return b.season - a.season; })[0] : null;
    return el("section", { class: "bc-intro" }, [
      el("div", { class: "bc-crest" }, [crest()]),
      el("span", { class: "bc-k", text: "Arm Chair Quarterback League" }),
      el("h2", {}, [el("span", { text: "Week " + (live ? DATA.live.week : n) }), el("small", { text: s.year + " season" })]),
      el("div", { class: "bc-intro-facts" }, [
        bcStat(String(live ? DATA.live.coaches.length : (cp ? cp.scored : s.entrants)), "coaches"),
        live ? bcStat(lead ? lead.c.name : "–", "leads, provisionally") : bcStat(cp ? listNames(cp.leaders, 2) : "–", "league leader"),
        live ? bcStat(phase(t) === "final" ? "Games over" : gamesOn(t) + " live", "results not yet official") :
          bcStat(cp && cp.winners.length ? listNames(cp.winners, 2) : "To be confirmed", "weekly winner"),
        big ? bcStat(big, "biggest move") : null
      ]),
      el("span", { class: "bc-tag" }, [lmSrc(live ? "prov" : "official"), live ? " The standings change until the week is final" : " Final results"])
    ]);
  }

  // ---- shareable pictures ----
  function bcShare(kind, s, C, cp) {
    var i = C.cps.indexOf(cp), prev = i > 0 ? C.cps[i - 1] : null, lines = [], title, sub;
    if (kind === "board") {
      title = "Standings"; sub = "After week " + cp.week;
      cp.rows.slice(0, 10).forEach(function (r) { lines.push([lmPlace(r), r.name, String(r.total), r.move ? (r.move > 0 ? "▲" : "▼") + Math.abs(r.move) : ""]); });
    } else if (kind === "movers") {
      title = "Risers & fallers"; sub = prev ? "Week " + prev.week + " to week " + cp.week : "Week " + cp.week;
      var mv = cp.rows.filter(function (r) { return r.move; }).sort(function (a, b) { return b.move - a.move; });
      mv.slice(0, 5).concat(mv.length > 5 ? mv.slice(-5).reverse() : []).forEach(function (r) { lines.push([(r.move > 0 ? "+" : "−") + Math.abs(r.move), r.name, ordinal(r.place), ""]); });
    } else {
      title = "Title race"; sub = bcRaceLine(s, C, cp);
      cp.rows.slice(0, 8).forEach(function (r) { lines.push([lmPlace(r), r.name, String(r.total), r.behind ? "−" + r.behind : "lead"]); });
    }
    var W = 1080, H = 1350, canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    var g = canvas.getContext("2d");
    var DISPLAY = '"Rajdhani", "Big Shoulders", "Barlow Condensed", "Arial Narrow", sans-serif', BODY = '"Barlow", "Segoe UI", system-ui, sans-serif';
    g.fillStyle = "#050708"; g.fillRect(0, 0, W, H);
    g.fillStyle = "rgba(242, 184, 58, 0.12)";
    g.beginPath(); g.moveTo(W - 320, 0); g.lineTo(W - 170, 0); g.lineTo(W - 440, H); g.lineTo(W - 590, H); g.closePath(); g.fill();
    g.fillStyle = "#f2b83a"; g.fillRect(0, 0, W, 12);
    g.fillStyle = "#f3f6fa"; g.font = "700 64px " + DISPLAY; g.fillText("ACQL " + s.year, 70, 120);
    g.fillStyle = "#f2b83a"; g.font = "700 110px " + DISPLAY; g.fillText(title.toUpperCase(), 70, 250);
    g.fillStyle = "#c5cdc6"; g.font = "600 38px " + BODY; g.fillText(sub, 72, 310);
    lines.forEach(function (l, k) {
      var y = 420 + k * 82;
      g.fillStyle = k % 2 ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.07)"; g.fillRect(56, y - 56, W - 112, 76);
      g.fillStyle = "#f2b83a"; g.font = "700 48px " + DISPLAY; g.fillText(l[0], 80, y);
      g.fillStyle = "#f3f6fa"; g.font = "600 44px " + BODY; g.fillText(l[1].length > 22 ? l[1].slice(0, 21) + "…" : l[1], 220, y);
      g.textAlign = "right"; g.font = "700 48px " + DISPLAY; g.fillText(l[2], W - 230, y);
      g.fillStyle = "#98a39a"; g.font = "600 36px " + BODY; g.fillText(l[3], W - 80, y);
      g.textAlign = "left";
    });
    g.fillStyle = "#98a39a"; g.font = "500 26px " + BODY;
    g.fillText("Official weekly totals · standings worked out from them · recap #" + lmHash(JSON.stringify(bcFacts(s, C, cp))), 70, H - 60);
    canvas.toBlob(function (blob) {
      if (!blob) return;
      var name = "ACQL " + s.year + " week " + cp.week + " - " + title + ".png", file = null;
      try { file = new File([blob], name, { type: "image/png" }); } catch (e) { file = null; }
      if (file && navigator.canShare && navigator.canShare({ files: [file] })) {
        navigator.share({ files: [file], title: "ACQL week " + cp.week }).catch(function () { lmDownload(name, blob, "image/png"); });
      } else lmDownload(name, blob, "image/png");
    }, "image/png");
  }
