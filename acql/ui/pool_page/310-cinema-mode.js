  // ---- Cinema mode -----------------------------------------------------------------------
  var cine = { open: false, node: null, rows: {}, selected: "", fs: false, back: null, tab: "games",
    filter: "all", dense: 0, table: "week", sort: "place" };
  try { cine.dense = Math.max(-1, Math.min(1, Number(localStorage.getItem("acql-cine-dense")) || 0)); } catch (e) { cine.dense = 0; }
  // What the scores on screen are: live, delayed, stale, cached or unavailable - never "streamed".
  function dataLabel(fr) {
    if (fr.level === "waiting" || fr.level === "error") return "Unavailable";
    if (fr.level === "failed") return "Cached";
    if (fr.level === "stale") return "Stale";
    return fr.age != null && fr.age > 90000 ? "Delayed" : "Live";
  }
  function inFilter(x, me) {
    var gi = DATA.live.games.indexOf(x.g), off = x.sc && x.sc.off;
    if (cine.filter === "live") return x.state === "in";
    if (cine.filter === "upcoming") return x.state === "pre" || !!off;
    if (cine.filter === "final") return x.state === "post" && !off;
    if (cine.filter === "mine") return !!(me && me.picks[gi]);
    return true;
  }
  // How the pool split on one game: cards on each side.
  function poolSplit(g) {
    var gi = DATA.live.games.indexOf(g), h = 0, a = 0;
    DATA.live.coaches.forEach(function (c) { if (c.picks[gi] === g.hc) h++; else if (c.picks[gi] === g.ac) a++; });
    return { h: h, a: a };
  }
  function reducedMotion() { try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; } }
  function motionMs(name, fallback) {
    var v = NaN;
    try { v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--m-" + name)); } catch (e) { /* none */ }
    return isFinite(v) ? v : fallback;
  }
  function openCinema() {
    if (cine.open || !hasLive()) return;
    cine.back = document.activeElement;
    cine.open = true;
    cine.rows = {};
    var node = el("div", { class: "cine", role: "dialog", "aria-modal": "true", "aria-label": "Cinema mode, week " + DATA.live.week, tabindex: "-1" });
    cine.node = node;
    document.body.appendChild(node);
    document.documentElement.classList.add("cine-on");
    cineDraw();
    try {
      if (document.fullscreenEnabled && node.requestFullscreen) {
        node.requestFullscreen().then(function () { cine.fs = true; }, function () { cine.fs = false; });
      }
    } catch (e) { cine.fs = false; }              // not allowed here: the full window does
    var exit = node.querySelector(".cine-exit");
    if (exit) exit.focus({ preventScroll: true });
    freshen();
  }
  function closeCinema() {
    if (!cine.open) return;
    cine.open = false;
    var node = cine.node;
    cine.node = null;
    if (document.fullscreenElement) { try { document.exitFullscreen(); } catch (e) { /* already out */ } }
    cine.fs = false;
    document.documentElement.classList.remove("cine-on");
    node.classList.add("out");
    setTimeout(function () { node.remove(); }, reducedMotion() ? 0 : motionMs("cinema", 220));
    if (cine.back && cine.back.isConnected) cine.back.focus({ preventScroll: true });
  }
  document.addEventListener("keydown", function (e) { if (cine.open && e.key === "Escape") { e.preventDefault(); closeCinema(); } });
  // Esc in full screen leaves full screen first: that is leaving Cinema mode too.
  document.addEventListener("fullscreenchange", function () { if (cine.open && cine.fs && !document.fullscreenElement) closeCinema(); });
  function cineDraw() {
    var node = cine.node;
    if (!node) return;
    var t = liveTally(), s = slateOf(t), fr = freshness();
    var rank = { "in": 0, pre: 1, post: 2 };
    var order = t.games.slice().sort(function (a, b) {
      var ao = a.sc && a.sc.off ? 3 : rank[a.state], bo = b.sc && b.sc.off ? 3 : rank[b.state];
      return ao - bo || (a.state === "post" ? (b.kick || 0) - (a.kick || 0) : (a.kick || Infinity) - (b.kick || Infinity));
    });
    var me = DATA.live.coaches.filter(function (c) { return isMe(c.name); })[0];
    function tile(x) {
      var g = x.g, cs = cardState(x), key = gameKey(g.hc, g.ac), sc = x.sc || {}, gi = DATA.live.games.indexOf(g);
      var pick = me ? me.picks[gi] || "" : "";
      var st = cs.status === "live" ? "● LIVE · " + (liveDetail(x) || "") : cs.status === "final" ? (liveDetail(x) || "Final").toUpperCase()
        : cs.status === "postponed" ? "POSTPONED" : x.kick ? kickFull(x.kick) : "Kickoff time to come";
      var m = live.spreads[key], market = "";
      if (m) { var mf = m.pts > 0 ? m.home : m.pts < 0 ? (m.home === g.hc ? g.ac : g.hc) : ""; market = mf ? "Market " + mf.toUpperCase() + " −" + Math.abs(m.pts) : "Market even"; }
      var stand = standing(x), sp = poolSplit(g);
      function side(team, name, pts) {
        return el("div", { class: "row" + (pick === team ? " pick" : "") + (x.credit === team ? " credit" : "") }, [badge(team, true),
          el("b", { class: "nm", text: name }), el("span", { class: "sc num" + (pts != null && x.state !== "pre" && moved(g) ? " score-new" : ""),
            text: x.state === "pre" || pts == null ? "" : String(pts) })]);
      }
      return el("button", { type: "button", class: "ctile" + (turnedNow(g) ? " turned" : ""), "data-status": cs.status, "data-warn": cs.warn,
        "aria-pressed": cine.selected === key ? "true" : "false", "data-key": key,
        "aria-label": g.a + " at " + g.h + ", " + st.replace("●", "").trim() + (cine.selected === key ? ", selected" : ""),
        onclick: function () { cine.selected = cine.selected === key ? "" : key; cineDraw(); } }, [
        el("span", { class: "st" }, [el("span", { text: st }), warnTag(cs), sc.tv && cs.status !== "final" ? el("span", { class: "tv", text: sc.tv }) : null]),
        side(g.ac, g.a, x.as), side(g.hc, g.h, x.hs),
        el("span", { class: "ln", text: [g.line != null && g.fav ? "Pool " + g.fav.toUpperCase() + " by " + g.line : "Pool: straight up", market,
          sp.h || sp.a ? "Picked " + g.ac.toUpperCase() + " " + sp.a + " · " + g.hc.toUpperCase() + " " + sp.h : "", stand.text].filter(Boolean).join(" · ") })]);
    }
    // keep the open card focused across a redraw
    var focusKey_ = document.activeElement && document.activeElement.getAttribute ? document.activeElement.getAttribute("data-key") : null;
    var head = el("div", { class: "cine-head" }, [
      el("div", { class: "wk" }, [el("span", { text: "ACQL · Week" }), el("b", { text: String(DATA.live.week) })]),
      el("div", { class: "cnt" }, [["total", "Games"], ["live", "Live"], ["final", "Final"], ["upcoming", "To play"]].map(function (p) {
        return el("div", { class: "c" + (p[0] === "live" && s.live ? " on" : "") }, [el("b", { class: "num", text: String(s[p[0]]) }), el("span", { text: p[1] })]);
      })),
      el("div", { class: "cine-tabs", role: "group", "aria-label": "Show" }, [["games", "Games"], ["picks", "Picks"]].map(function (p) {
        return el("button", { type: "button", "aria-pressed": cine.tab === p[0] ? "true" : "false",
          onclick: function () { cine.tab = p[0]; cineDraw(); }, text: p[1] });
      })),
      nextNode(t),
      el("button", { class: "cine-exit", type: "button", onclick: closeCinema, text: "Exit ✕", title: "Back to the site (Esc)" })]);
    var shown = order.filter(function (x) { return inFilter(x, me); });
    var grid = cine.tab === "picks" ? cinePicks(t) : el("div", { class: "cine-main" }, [cineBar(), cineDetail(t, me),
      shown.length ? el("div", { class: "cine-grid", "data-dense": String(cine.dense) }, shown.map(tile))
        : el("p", { class: "cine-empty", text: ({ live: "No game is on right now.", upcoming: "Every game has kicked off.",
          final: "No game has finished yet.", mine: hasMe() ? "No picks of yours on this week’s sheet." : "Choose your name on Me to see your picks here." })[cine.filter] || "No games." })]);
    var side = el("aside", { class: "cine-side" }, [
      el("div", { class: "cine-tablebar" }, [el("h2", { text: cine.table === "season" ? "Season · official standings" : "Pool · if it ended now" }),
        el("div", { class: "cine-chips" }, [["week", "Week"], ["season", "Season"]].map(function (p) {
          return el("button", { type: "button", class: "cchip", "aria-pressed": cine.table === p[0] ? "true" : "false",
            onclick: function () { cine.table = p[0]; cineDraw(); }, text: p[1] });
        }).concat(cine.table === "week" ? [el("button", { type: "button", class: "cchip", title: "Order by place now, best place still possible, or name",
          onclick: function () { cine.sort = { place: "best", best: "name", name: "place" }[cine.sort]; cineDraw(); }, text: "Sort: " + cine.sort })] : []))]),
      cine.table === "season" ? seasonStrip() : standStrip(t),
      el("p", { class: "cine-note", text: cine.table === "season" ? "Season wins from the pool’s official standings; this week’s points so far beside them."
        : (standAt ? "Standings worked out from the scores at " + clockSec(standAt) + ", by the pool’s own rules." : "") + youRange(t) }),
      el("h2", { text: "Just happened" }),
      swings.length ? el("ol", { class: "cine-feed" }, swings.slice(0, 7).map(function (f) {
        return el("li", { class: (f.tone || "") + (/^Final/.test(f.title) ? " fin" : "") || null }, [el("time", { text: clock(f.at) }), el("span", { text: f.title })]);
      })) : el("p", { class: "cine-note", text: "Nothing yet - changes while this page is open show here." }),
      el("h2", { text: "System" }),
      el("p", { class: "cine-health " + fr.level }, [el("b", { class: "dl", text: dataLabel(fr) }), fr.head, fr.detail ? el("small", { text: fr.detail }) : null,
        el("small", { text: "Scores are refreshed by polling ESPN’s scoreboard, not a live stream." })])]);
    var strip = cine.node.querySelector(".cine-strip");
    var keep = strip ? strip.scrollTop : 0;
    node.textContent = "";
    node.appendChild(head);
    node.appendChild(cine.tab === "picks" ? el("div", { class: "cine-body solo" }, [grid]) : el("div", { class: "cine-body" }, [grid, side]));
    var fresh = node.querySelector(".cine-strip");
    if (fresh) fresh.scrollTop = keep;
    playStand();
    if (focusKey_) { var f = node.querySelector('[data-key="' + focusKey_ + '"]'); if (f) f.focus({ preventScroll: true }); }
  }
  // The Picks tab: one row per coach - every game, the Big Losers, the suicide pick.
  function cinePicks(t) {
    var L = DATA.live, started = t.games.some(function (x) { return x.state !== "pre"; });
    function mark(team, ok, bad, live_, title) {
      return el("td", { class: "cp" + (ok ? " ok" : bad ? " no" : "") + (live_ ? " lv" : ""), title: title || teamFull(codeOf(team)) },
        [team ? badge(team) : el("span", { class: "flat", text: "–" })]);
    }
    var head = [el("th", { class: "nm", text: "Coach" }), el("th", { class: "n", text: started ? "Now" : "" })]
      .concat(t.games.map(function (x) {
        var g = x.g, lined = g.line != null && g.fav;
        return el("th", { class: "gk", title: g.a + " at " + g.h + (lined ? ", pool " + g.fav.toUpperCase() + " by " + g.line : "") },
          [el("span", { text: g.ac.toUpperCase() }), el("span", { text: g.hc.toUpperCase() })]);
      }))
      .concat([el("th", { class: "sep", colspan: "3", text: "Big Losers" }), el("th", { class: "sep", text: "Suicide" })]);
    var rows = t.rows.map(function (r, i) {
      var c = r.c, p = player(c.name);
      var cells = [el("td", { class: "nm" + (isMe(c.name) ? " me" : "") }, [el("span", { class: "pl num", text: String(i + 1) }), c.name]),
        el("td", { class: "n num", text: started ? String(r.now) : "" })];
      t.games.forEach(function (x, gi) {
        var pick = c.picks[gi] || "";
        var decided = x.state !== "pre" && !!x.credit;
        cells.push(mark(pick, decided && x.credit === pick, decided && x.credit !== pick, x.state === "in"));
      });
      for (var k = 0; k < 3; k++) {
        var team = c.bl[k] || "";
        if (!team) { cells.push(mark("", false, false, false)); continue; }
        var s = loserState(tallyGame(t, team), team), x = tallyGame(t, team);
        var hit = s.by != null && s.by >= 15, miss = !hit && s.by != null && x && x.state === "post";
        cells.push(mark(team, hit, miss, x && x.state === "in", teamFull(codeOf(team)) + " · " + s.text));
      }
      if (!p || !p.suicide.alive) cells.push(el("td", { class: "cp" }, [el("span", { class: "flat", text: p && p.suicide.out ? "out" : "–" })]));
      else if (!c.sui) cells.push(el("td", { class: "cp" }, [el("span", { class: "flat", text: "none" })]));
      else {
        var st = survivalState(tallyGame(t, c.sui), c.sui);
        cells.push(mark(c.sui, st.now === "through" || st.now === "ahead", st.now === "out" || st.now === "behind",
          st.now === "ahead" || st.now === "behind" || st.now === "level", teamFull(codeOf(c.sui)) + " · " + st.text));
      }
      return el("tr", { class: isMe(c.name) ? "me" : null }, cells);
    });
    return el("div", { class: "cine-picks" }, [el("table", {}, [el("thead", {}, [el("tr", {}, head)]), el("tbody", {}, rows)]),
      el("p", { class: "cine-note", text: "Green is right and red is wrong as the scores stand; a pulsing edge is a game being played. " +
        "A Big Loser counts when its team loses by 15 or more." })]);
  }
  // The standings strip. Its rows are kept by coach between draws, so a
  // coach changing place glides there (and never because of a redraw).
  function standStrip(t) {
    var box = el("ol", { class: "cine-strip" });
    var first = {};
    Object.keys(cine.rows).forEach(function (k) { if (cine.rows[k].isConnected) first[k] = cine.rows[k].getBoundingClientRect().top; });
    cine.first = first;
    var ranges = rangesOf(t), rows = t.rows.slice();
    if (cine.sort === "best" && ranges) rows.sort(function (a, b) { return (ranges.best[a.c.name] || 99) - (ranges.best[b.c.name] || 99) || b.now - a.now; });
    else if (cine.sort === "name") rows.sort(function (a, b) { return a.c.name.localeCompare(b.c.name); });
    rows.forEach(function (r) {
      var name = r.c.name, place = 1 + t.rows.filter(function (o) { return o.now > r.now; }).length;
      var row = cine.rows[name];
      if (!row) {
        row = el("li", { class: "sr" }, [el("span", { class: "p num" }), el("span", { class: "n" }), el("b", { class: "v num" }), el("span", { class: "r num" })]);
        cine.rows[name] = row;
      }
      row.className = "sr" + (isMe(name) ? " me" : "");
      row.children[0].textContent = String(place);
      row.children[1].textContent = name + (isMe(name) ? "  · you" : "");
      if (!row.counting) row.children[2].textContent = String(r.now);
      var lo = ranges && ranges.best[name], hi = ranges && ranges.worst[name];
      row.children[3].textContent = lo ? (lo === hi ? String(lo) : lo + "–" + hi) : "";
      row.title = lo ? name + ": " + ordinal(place) + " now · can still finish anywhere from " + ordinal(lo) + " to " + ordinal(hi) : "";
      box.appendChild(row);
    });
    return box;
  }
  // Best and worst places still possible, while the week is open.
  function rangesOf(t) {
    var started = t.games.some(function (x) { return x.state !== "pre"; });
    if (!started || weekOver(t)) return null;
    try { return { best: bestPlaces(t), worst: worstPlaces(t) }; } catch (e) { return null; }
  }
  function youRange(t) {
    var r = rangesOf(t), me = t.rows.filter(function (x) { return isMe(x.c.name); })[0];
    if (!r || !me) return "";
    var place = 1 + t.rows.filter(function (o) { return o.now > me.now; }).length;
    return " You: " + ordinal(place) + " now, best " + ordinal(r.best[me.c.name]) + ", worst " + ordinal(r.worst[me.c.name]) + ".";
  }
  // The season so far, by the official standings; this week's points beside them until they count.
  function seasonStrip() {
    var t = liveTally(), now = {};
    t.rows.forEach(function (r) { now[r.c.name] = r.now; });
    var wk = String(DATA.live.week);
    return el("ol", { class: "cine-strip" }, DATA.players.slice().sort(function (a, b) { return a.place - b.place || a.name.localeCompare(b.name); })
      .map(function (p) {
        var counted = p.weekly && p.weekly[wk] != null, extra = !counted && now[p.name] != null ? "+" + now[p.name] : "";
        return el("li", { class: "sr" + (isMe(p.name) ? " me" : ""), title: extra ? now[p.name] + " so far this week, not yet in the official totals" : "" },
          [el("span", { class: "p num", text: String(p.place) }), el("span", { class: "n", text: p.name + (isMe(p.name) ? "  · you" : "") }),
            el("b", { class: "v num", text: String(p.wins) }), el("span", { class: "r num", text: extra })]);
      }));
  }
  // Filters and density over the grid.
  function cineBar() {
    var chips = [["all", "All"], ["live", "Live"], ["upcoming", "Upcoming"], ["final", "Final"], ["mine", "My picks"]].map(function (p) {
      return el("button", { type: "button", class: "cchip", "aria-pressed": cine.filter === p[0] ? "true" : "false",
        onclick: function () { cine.filter = p[0]; cineDraw(); }, text: p[1] });
    });
    function dense(way) {
      return function () {
        cine.dense = Math.max(-1, Math.min(1, cine.dense + way));
        try { localStorage.setItem("acql-cine-dense", String(cine.dense)); } catch (e) { /* this visit only */ }
        cineDraw();
      };
    }
    return el("div", { class: "cine-bar", role: "group", "aria-label": "Show games" }, chips.concat([
      el("span", { class: "dn", text: "Density" }),
      el("button", { type: "button", class: "cchip", "aria-label": "Fewer, larger cards", disabled: cine.dense <= -1 ? "disabled" : null, onclick: dense(-1), text: "−" }),
      el("button", { type: "button", class: "cchip", "aria-label": "More, smaller cards", disabled: cine.dense >= 1 ? "disabled" : null, onclick: dense(1), text: "+" })]));
  }
  // The chosen game opened out: drive, last play, records, the pool on it, your pick.
  function cineDetail(t, me) {
    var x = t.games.filter(function (y) { return gameKey(y.g.hc, y.g.ac) === cine.selected; })[0];
    if (!x) return null;
    var g = x.g, sc = x.sc || {}, gi = DATA.live.games.indexOf(g), sp = poolSplit(g), bits = [];
    if (x.state === "in") {
      if (sc.down) bits.push((sc.poss ? sc.poss.toUpperCase() + " ball · " : "") + sc.down + (sc.spot ? " · " + sc.spot : "") + (sc.rz ? " · Red zone" : ""));
      if (sc.play) bits.push("Last play: " + sc.play);
    }
    var rec = sc.rec || {};
    if (rec[g.ac] || rec[g.hc]) bits.push("Records: " + [rec[g.ac] ? g.a + " " + rec[g.ac] : "", rec[g.hc] ? g.h + " " + rec[g.hc] : ""].filter(Boolean).join(" · "));
    bits.push((g.line != null && g.fav ? "Pool line: " + teamName(x, g.fav) + " by " + g.line : "Pool line: straight up") + (sc.tv ? " · on " + sc.tv : ""));
    bits.push("The pool: " + sp.a + " on " + g.a + ", " + sp.h + " on " + g.h);
    var pick = me ? me.picks[gi] || "" : "";
    if (pick) {
      var how = x.state === "pre" ? "to come" : !x.credit ? (x.state === "post" ? "push" : "level")
        : x.credit === pick ? (x.state === "post" ? "right" : "winning") : (x.state === "post" ? "wrong" : "losing");
      bits.push("Your pick: " + teamName(x, pick) + " (" + how + ")");
    }
    var key = gameKey(g.hc, g.ac), score = x.state === "pre" ? g.a + " at " + g.h : g.a + " " + x.as + ", " + g.h + " " + x.hs;
    return el("div", { class: "cine-detail" }, [
      el("div", { class: "dt" }, [el("b", { text: score + " · " + (liveDetail(x) || (x.kick ? kickFull(x.kick) : "Kickoff to come")) }),
        el("p", {}, bits.map(function (b) { return el("span", { text: b }); }))]),
      el("div", { class: "dbtn" }, [
        el("button", { type: "button", class: "cine-exit", text: "Game card", title: "Close Cinema and open this game’s card on Live",
          onclick: function () { closeCinema(); jumpToGame(key)({ preventDefault: function () {} }); } }),
        el("button", { type: "button", class: "cine-exit", text: "Close", onclick: function () { cine.selected = ""; cineDraw(); } })])]);
  }
  function playStand() {
    var move = standMove;
    standMove = null;                      // once
    if (!move) return;
    var still = reducedMotion();
    Object.keys(move.moved).forEach(function (k) {
      var row = cine.rows[k], was = cine.first && cine.first[k];
      if (!row || was == null || still) return;
      var dy = was - row.getBoundingClientRect().top;
      if (!dy) return;
      row.style.transition = "none";
      row.style.transform = "translateY(" + dy + "px)";
      row.getBoundingClientRect();
      row.style.transition = "transform " + motionMs("rank", 450) + "ms var(--ease, ease-out)";
      row.style.transform = "";
    });
    Object.keys(move.gained).forEach(function (k) {
      var row = cine.rows[k];
      if (!row) return;
      var v = row.children[2], from = move.gained[k][0], to = move.gained[k][1];
      v.classList.remove("score-new"); v.getBoundingClientRect(); v.classList.add("score-new");
      if (still) { v.textContent = String(to); return; }
      var start = performance.now(), dur = motionMs("count", 700);
      row.counting = true;
      (function step(now) {
        var k_ = Math.min(1, (now - start) / dur);
        v.textContent = String(Math.round(from + (to - from) * (1 - Math.pow(1 - k_, 3))));
        if (k_ < 1 && v.isConnected) requestAnimationFrame(step); else { v.textContent = String(to); row.counting = false; }
      })(start);
    });
  }

