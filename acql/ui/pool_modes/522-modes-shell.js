  // ---- league modes: the shell they share ----------------------------------------------
  // Each mode is a screen of its own over the site, like Cinema mode, with its
  // own address (#broadcast, #timemachine, #numbers) so it can be opened from a
  // link. The coach, season and weeks chosen in one mode go with the viewer to
  // the next. Esc, or "Back to the site", returns to the page underneath.
  var LM_MODES = {
    broadcast: { label: "League Broadcast", short: "Broadcast", icon: "live",
      about: "The week as a TV show: the table revealed, risers and fallers, rivalries and the title race." },
    timemachine: { label: "League Time Machine", short: "Time Machine", icon: "history",
      about: "Travel back to any week on record and watch the season unfold again." },
    numbers: { label: "The Numbers Room", short: "Numbers Room", icon: "charts",
      about: "Every coach, week, pick and record - sortable, comparable, downloadable." }
  };
  var LM_ORDER = ["broadcast", "timemachine", "numbers"];
  var LM = { mode: "", node: null, back: null, fs: false, charts: [], boards: {}, seen: null,
    sel: { season: "", week: 0, a: "", b: "", from: 0, to: 0 },
    tm: { tab: "standings", playing: false, speed: 1, timer: null, cmp: "weeks", cw: 0 },
    nr: { tab: "home", sort: {}, q: "", ds: "weekly", studio: {}, week: 0, pool: "suicide" },
    bc: { kind: "recap", seg: 0, playing: true, timer: null, intro: true, anim: "", t0: 0 } };
  var LM_KEY = "acql-modes-sel";
  (function () {
    var saved = storedJSON(LM_KEY);
    if (saved && typeof saved === "object") ["season", "a", "b"].forEach(function (k) { if (saved[k]) LM.sel[k] = String(saved[k]); });
  })();

  function lmSeasonNow() { var s = lmSeason(LM.sel.season); if (s) LM.sel.season = String(s.year); return s; }
  // The chosen coach: one picked here, else the viewer, else the leader.
  function lmCoach(s) {
    s = s || lmSeasonNow();
    var names_ = s ? s.standings.map(function (x) { return x.name; }) : [];
    if (LM.sel.a && names_.indexOf(LM.sel.a) >= 0) return LM.sel.a;
    if (state.me && names_.indexOf(state.me) >= 0) return state.me;
    var C = s ? lmCheckpoints(s) : null, last = C && C.cps.length ? C.cps[C.cps.length - 1] : null;
    return last ? last.rows[0].name : names_[0] || "";
  }
  function lmRival(s, a) {
    var names_ = s ? s.standings.map(function (x) { return x.name; }) : [];
    if (LM.sel.b && LM.sel.b !== a && names_.indexOf(LM.sel.b) >= 0) return LM.sel.b;
    var C = lmCheckpoints(s), last = C.cps[C.cps.length - 1];
    if (!last) return "";
    var me = last.by[a], best = null;
    last.rows.forEach(function (r) {
      if (r.name === a) return;
      var d = me ? Math.abs(r.total - me.total) : r.place;
      if (!best || d < best.d) best = { d: d, name: r.name };
    });
    return best ? best.name : "";
  }
  function lmWeek(s) {
    var C = lmCheckpoints(s);
    if (LM.sel.week && C.byWeek[LM.sel.week]) return LM.sel.week;
    return C.last;
  }
  function lmRange(s) {
    var C = lmCheckpoints(s), first = C.weeks[0] || 0, last = C.last;
    var f = LM.sel.from && C.byWeek[LM.sel.from] ? LM.sel.from : first;
    var t = LM.sel.to && C.byWeek[LM.sel.to] ? LM.sel.to : last;
    if (f > t) { var x = f; f = t; t = x; }
    return { from: f, to: t };
  }
  function lmKeep() { storeJSON(LM_KEY, { season: LM.sel.season, a: LM.sel.a, b: LM.sel.b }); }

  // ---- addresses ----
  function lmHash() {
    var p = [], s = LM.sel;
    if (s.season) p.push("s=" + encodeURIComponent(s.season));
    if (s.week) p.push("w=" + s.week);
    if (s.a) p.push("c=" + encodeURIComponent(s.a));
    if (LM.mode === "numbers" && s.b) p.push("d=" + encodeURIComponent(s.b));
    if (LM.mode === "numbers" && s.from) p.push("f=" + s.from);
    if (LM.mode === "numbers" && s.to) p.push("t=" + s.to);
    if (LM.mode === "numbers" && LM.nr.tab !== "home") p.push("tab=" + LM.nr.tab);
    if (LM.mode === "timemachine" && LM.tm.tab !== "standings") p.push("tab=" + LM.tm.tab);
    if (LM.mode === "broadcast" && LM.bc.kind === "live") p.push("live=1");
    return "#" + LM.mode + (p.length ? "?" + p.join("&") : "");
  }
  function lmSetHash() {
    if (!LM.mode) return;
    try { history.replaceState(null, "", lmHash()); } catch (e) { /* not allowed here */ }
    lmKeep();
  }
  function lmParse(hash) {
    var raw = String(hash || "").replace(/^#/, ""), q = raw.indexOf("?");
    var mode = q >= 0 ? raw.slice(0, q) : raw;
    if (!LM_MODES[mode]) return null;
    var params = {};
    (q >= 0 ? raw.slice(q + 1) : "").split("&").forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf("=");
      try { params[i < 0 ? kv : kv.slice(0, i)] = i < 0 ? "1" : decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* a broken link: ignore that part */ }
    });
    return { mode: mode, params: params };
  }
  function lmApply(params) {
    if (params.s) LM.sel.season = params.s;
    if (params.w) LM.sel.week = Number(params.w) || 0;
    if (params.c) LM.sel.a = params.c;
    if (params.d) LM.sel.b = params.d;
    if (params.f) LM.sel.from = Number(params.f) || 0;
    if (params.t) LM.sel.to = Number(params.t) || 0;
    if (params.tab) { LM.nr.tab = params.tab; LM.tm.tab = params.tab; }
    if (params.live) LM.bc.kind = "live";
  }
  function lmRoute() {
    var found = lmParse(location.hash);
    if (found) {
      lmApply(found.params);
      if (LM.mode !== found.mode) lmOpen(found.mode, null, true);
      else lmDraw();
    } else if (LM.mode) lmClose(true);
  }
  window.addEventListener("hashchange", function () { setTimeout(lmRoute, 0); });
  setTimeout(lmRoute, 0);

  // ---- opening and closing ----
  // Go to a mode, taking along whatever selections are passed.
  function lmGo(mode, sel) {
    // tab, kind and spot say where to land in the mode; the rest is the shared selection
    if (sel) Object.keys(sel).forEach(function (k) { if (sel[k] != null && LM.sel.hasOwnProperty(k)) LM.sel[k] = sel[k]; });
    if (sel && sel.tab) { if (mode === "numbers") LM.nr.tab = sel.tab; if (mode === "timemachine") LM.tm.tab = sel.tab; }
    if (sel && sel.kind) LM.bc.kind = sel.kind;
    LM.bc.spot = !!(sel && sel.spot);
    if (LM.mode === mode) { lmDraw(); lmSetHash(); return; }
    lmOpen(mode, null, false);
  }
  function lmOpen(mode, sel, fromHash) {
    if (!LM_MODES[mode]) return;
    if (typeof cine !== "undefined" && cine.open) closeCinema();
    lmStopAll();
    if (sel) Object.keys(sel).forEach(function (k) { LM.sel[k] = sel[k]; });
    loadHistory();
    var fresh = !LM.node;
    if (fresh) {
      LM.back = document.activeElement;
      LM.node = el("div", { class: "lm", role: "dialog", "aria-modal": "true", tabindex: "-1" });
      document.body.appendChild(LM.node);
      document.documentElement.classList.add("lm-on");
    }
    LM.mode = mode;
    LM.boards = {};
    LM.node.className = "lm lm-" + mode;
    LM.node.setAttribute("aria-label", LM_MODES[mode].label);
    if (mode === "broadcast") { LM.bc.intro = true; LM.bc.seg = 0; LM.bc.anim = ""; LM.bc.playing = !reducedMotion(); }
    lmDraw();
    if (!fromHash || !lmParse(location.hash)) {
      try { history.pushState(null, "", lmHash()); } catch (e) { /* not allowed here */ }
    } else lmSetHash();
    var focusOn = LM.node.querySelector(".lm-close");
    if (fresh && focusOn) focusOn.focus({ preventScroll: true });
    lmWaitHistory();
  }
  function lmClose(fromHash) {
    if (!LM.mode) return;
    lmStopAll();
    LM.mode = "";
    if (document.fullscreenElement) { try { document.exitFullscreen(); } catch (e) { /* already out */ } }
    var node = LM.node;
    LM.node = null;
    document.documentElement.classList.remove("lm-on");
    if (node) { node.classList.add("out"); setTimeout(function () { node.remove(); }, reducedMotion() ? 0 : 200); }
    if (!fromHash) { try { history.replaceState(null, "", state.coach ? "#coach=" + encodeURIComponent(state.coach) : "#" + state.view); } catch (e) { /* fine */ } }
    if (LM.back && LM.back.isConnected) LM.back.focus({ preventScroll: true });
  }
  function lmStopAll() {
    if (LM.tm.timer) { clearInterval(LM.tm.timer); LM.tm.timer = null; }
    LM.tm.playing = false;
    if (LM.bc.timer) { clearTimeout(LM.bc.timer); LM.bc.timer = null; }
  }
  // The archive of past seasons arrives a moment after the mode opens.
  function lmWaitHistory() {
    var tries = 0;
    (function look() {
      if (!LM.mode) return;
      if (historyBusy && tries++ < 40) { setTimeout(look, 250); return; }
      if (lmCache.hist !== historyData) lmDraw();
    })();
  }
  document.addEventListener("keydown", function (e) {
    if (!LM.mode || e.key !== "Escape" || document.fullscreenElement) return;
    e.preventDefault();
    lmClose(false);
  });
  document.addEventListener("fullscreenchange", function () { LM.fs = !!document.fullscreenElement; if (LM.mode) lmTopState(); });
  function lmFullscreen() {
    try {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (LM.node && LM.node.requestFullscreen) LM.node.requestFullscreen().catch(function () { /* not allowed here */ });
    } catch (e) { /* not available */ }
  }
  function lmTopState() {
    var b = LM.node && LM.node.querySelector(".lm-fs");
    if (b) b.setAttribute("aria-pressed", document.fullscreenElement ? "true" : "false");
  }

  // The site redraws itself when scores or data arrive: the modes follow,
  // keeping whatever the viewer had chosen.
  var lmBaseRender = render;
  render = function (opts) {
    lmBaseRender(opts);
    if (!LM.mode) return;
    if (LM.seen !== DATA) lmDraw();
    else if (LM.mode === "broadcast" && LM.bc.kind === "live") lmDraw({ quiet: true });
  };

  // ---- drawing ----
  function lmDraw(opts) {
    if (!LM.mode || !LM.node) return;
    opts = opts || {};
    LM.seen = DATA;
    var node = LM.node, keepScroll = {};
    Array.prototype.forEach.call(node.querySelectorAll("[data-keep-scroll]"), function (n) { keepScroll[n.getAttribute("data-keep-scroll")] = n.scrollTop; });
    LM.charts = [];
    var y = node.scrollTop;
    node.textContent = "";
    var body;
    try {
      body = LM.mode === "broadcast" ? bcView(opts) : LM.mode === "timemachine" ? tmView() : nrView();
    } catch (e) {
      body = el("div", { class: "lm-body" }, [stateMsg("This mode couldn’t be drawn", String(e && e.message || e), { text: "Back to the site", go: function () { lmClose(false); } }, "bad")]);
    }
    node.appendChild(lmTop());
    node.appendChild(body);
    Array.prototype.forEach.call(node.querySelectorAll("[data-keep-scroll]"), function (n) {
      var k = n.getAttribute("data-keep-scroll");
      if (keepScroll[k]) n.scrollTop = keepScroll[k];
    });
    lmDrawCharts();
    if (!opts.top) node.scrollTop = y;
    lmSetHash();
  }
  function lmDrawCharts() {
    LM.charts.forEach(function (c) {
      if (!c.node.isConnected) return;
      var w = Math.max(260, Math.floor(c.node.clientWidth || 600));
      c.node.textContent = "";
      try { var out = c.draw(w); if (out) c.node.appendChild(out); }
      catch (e) { c.node.appendChild(el("p", { class: "note", text: "This chart couldn’t be drawn." })); }
      c.node.style.minHeight = "";
    });
  }
  var lmResize = null;
  window.addEventListener("resize", function () { if (!LM.mode) return; clearTimeout(lmResize); lmResize = setTimeout(lmDrawCharts, 160); });
  function lmChart(height, draw, label) {
    var box = el("div", { class: "chart lm-chart", style: "min-height:" + height + "px", "aria-label": label || null });
    LM.charts.push({ node: box, draw: draw });
    return box;
  }
  // Clicking a week on one of the site's line charts: which week was it?
  function lmClickWeeks(wrap, width, xs, go_) {
    var narrow = width < 520, padL = 40, padR = narrow ? 84 : 112;
    wrap.addEventListener("click", function (e) {
      var svg = wrap.querySelector("svg");
      if (!svg || xs.length < 1) return;
      var box = svg.getBoundingClientRect(), px = (e.clientX - box.left) * (width / box.width);
      var i = xs.length > 1 ? Math.round((px - padL) / ((width - padL - padR) / (xs.length - 1))) : 0;
      i = Math.max(0, Math.min(xs.length - 1, i));
      go_(xs[i]);
    });
    wrap.classList.add("lm-clickable");
    return wrap;
  }

  // The bar across the top of every mode.
  function lmTop() {
    var m = LM_MODES[LM.mode];
    return el("header", { class: "lm-top" }, [
      el("div", { class: "lm-brand" }, [el("span", { class: "lm-crest" }, [crest()]),
        el("div", {}, [el("span", { class: "k", text: "ACQL" }), el("b", { text: m.label })])]),
      el("nav", { class: "lm-switch", "aria-label": "League modes" }, LM_ORDER.map(function (k) {
        return el("button", { type: "button", "aria-current": k === LM.mode ? "page" : null, onclick: function () { lmGo(k); } },
          [icon(LM_MODES[k].icon), el("span", { text: LM_MODES[k].short })]);
      })),
      el("div", { class: "lm-acts" }, [
        el("button", { class: "lm-btn lm-fs", type: "button", "aria-pressed": document.fullscreenElement ? "true" : "false",
          title: "Full screen", "aria-label": "Full screen", onclick: lmFullscreen, hidden: !document.fullscreenEnabled }, [lmGlyph("fs")]),
        el("button", { class: "lm-btn lm-close", type: "button", title: "Back to the site (Esc)", onclick: function () { lmClose(false); } },
          [icon("close"), el("span", { text: "Back to the site" })])
      ])
    ]);
  }
  // The few marks the modes need that the site's icon set doesn't have.
  var LM_GLYPHS = {
    fs: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
    pause: '<path d="M7 4h3.5v16H7zM13.5 4H17v16h-3.5z" fill="currentColor" stroke="none"/>',
    prev: '<path d="M15 5l-7 7 7 7"/>', next: '<path d="M9 5l7 7-7 7"/>',
    first: '<path d="M6 5v14M18 5l-7 7 7 7"/>', last: '<path d="M18 5v14M6 5l7 7-7 7"/>',
    replay: '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4.5h4.5"/>',
    skip: '<path d="M5 5l7 7-7 7M12 5l7 7-7 7"/>',
    down: '<path d="M12 4v12M6 11l6 6 6-6M5 20h14"/>',
    up: '<path d="M12 19V6M6 11l6-6 6 6"/>', dn: '<path d="M12 5v13M6 13l6 6 6-6"/>'
  };
  function lmGlyph(name) {
    var span = el("span", {});
    span.innerHTML = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + (LM_GLYPHS[name] || "") + "</svg>";
    return span.firstChild;
  }
  function lmCtl(glyph, label, onclick, attrs) {
    var a = Object.assign({ class: "lm-btn", type: "button", title: label, "aria-label": label, onclick: onclick }, attrs || {});
    return el("button", a, [lmGlyph(glyph)]);
  }
  // A coach picker; "" for none when `none` names it.
  function lmPicker(s, value, onpick, label, none) {
    var opts = (none ? [el("option", { value: "", text: none })] : []).concat(
      lmCheckpoints(s).cps.length ? lmCheckpoints(s).cps[lmCheckpoints(s).cps.length - 1].rows.map(function (r) { return r.name; }).map(function (n) {
        return el("option", { value: n, selected: n === value, text: n });
      }) : []);
    return el("label", { class: "lm-pick" }, [el("span", { text: label }),
      el("select", { onchange: function (e) { onpick(e.target.value); } }, opts)]);
  }
  function lmSeasonPicker(onpick) {
    var all = lmSeasons(), now = lmSeasonNow();
    if (all.length < 2) return el("span", { class: "lm-chip", title: "Seasons on record" }, [String(now ? now.year : seasonYear()) + (now && now.current ? " season" : "")]);
    return el("label", { class: "lm-pick" }, [el("span", { text: "Season" }),
      el("select", { onchange: function (e) { LM.sel.season = e.target.value; LM.sel.week = 0; LM.sel.from = LM.sel.to = 0; (onpick || lmDraw)(); } },
        all.map(function (s) { return el("option", { value: String(s.year), selected: now && s.year === now.year, text: s.year + (s.current ? " (this season)" : s.complete ? "" : " (part)") }); }))]);
  }
  // Who a name belongs to: the coach's page on the site, from inside a mode.
  function lmWho(name, cls) {
    if (!player(name)) return el("span", { class: cls || "", text: name });
    return el("button", { type: "button", class: "lm-who" + (cls ? " " + cls : ""), title: "Open " + name + "’s page on the site",
      onclick: function () { lmClose(false); openCoach(name); }, text: name });
  }
  function lmMove(move) {
    if (move == null) return el("span", { class: "lm-mv none", text: "–", title: "No earlier week to compare" });
    if (move === 0) return el("span", { class: "lm-mv same", text: "=", title: "Same place" });
    return el("span", { class: "lm-mv " + (move > 0 ? "up" : "down"), title: (move > 0 ? "Up " : "Down ") + plural(Math.abs(move), "place") },
      [lmGlyph(move > 0 ? "up" : "dn"), String(Math.abs(move))]);
  }

  // An animated standings board: rows slide to their new places when the
  // week changes, so a climb or a fall can be seen as it happens.
  function lmBoard(key, rows, opts) {
    opts = opts || {};
    var rowH = opts.rowH || 40;
    var b = LM.boards[key];
    if (!b) {
      b = LM.boards[key] = { node: el("ol", { class: "lm-board" + (opts.cls ? " " + opts.cls : ""), "aria-label": opts.label || "Standings" }), rows: {} };
    }
    var node = b.node, seen = {};
    node.style.height = (rows.length * rowH) + "px";
    var moves = [];
    rows.forEach(function (r, i) {
      var li = b.rows[r.name], born = !li;
      if (born) {
        li = b.rows[r.name] = el("li", { class: "lm-row", style: "transform:translateY(" + ((opts.startAt && opts.startAt[r.name] != null ? opts.startAt[r.name] : i) * rowH) + "px)" });
        node.appendChild(li);
      }
      li.textContent = "";
      opts.cells(r, i).forEach(function (c) { if (c) li.appendChild(c); });
      li.className = "lm-row" + (opts.rowClass ? " " + (opts.rowClass(r, i) || "") : "") + (born && !opts.startAt ? " born" : "");
      li.style.height = rowH + "px";
      li.style.zIndex = String(1000 - i);
      moves.push([li, i * rowH]);
      seen[r.name] = true;
    });
    Object.keys(b.rows).forEach(function (n) { if (!seen[n]) { b.rows[n].remove(); delete b.rows[n]; } });
    var go_ = function () { moves.forEach(function (m) { m[0].style.transform = "translateY(" + m[1] + "px)"; }); };
    if (opts.delay) setTimeout(go_, opts.delay);
    else requestAnimationFrame(function () { requestAnimationFrame(go_); });
    return node;
  }

  // ---- the launcher: on the home page and in the menu ----
  function lmLauncher(compact) {
    return el("section", { class: "module lm-launch" + (compact ? " compact" : ""), "data-card": "league-modes", "aria-label": "League modes" }, [
      el("div", { class: "mhead" }, [el("h2", { text: "League modes" }), el("span", { class: "aside", text: "Three ways into the league" })]),
      el("div", { class: "lm-tiles" }, LM_ORDER.map(function (k) {
        var m = LM_MODES[k];
        return el("a", { class: "lm-tile " + k, href: "#" + k, onclick: function (e) { e.preventDefault(); lmGo(k); } }, [
          el("span", { class: "ic" }, [icon(m.icon)]),
          el("b", { text: m.label }),
          el("span", { class: "note", text: m.about })
        ]);
      }))
    ]);
  }
  var lmBaseHome = homeView;
  homeView = function () {
    var v = lmBaseHome();
    if (DATA.weeks && DATA.weeks.length) {
      var kids = v.children, at = kids.length > 2 ? kids[2] : null;
      v.insertBefore(lmLauncher(false), at);
    }
    return v;
  };
  var lmBaseSheet = sheet;
  sheet = function () {
    var out = lmBaseSheet();
    if (!out || !DATA.weeks || !DATA.weeks.length) return out;
    var box = out[1], themes = box && box.querySelector(".themes");
    if (box) box.insertBefore(el("div", { class: "group" }, [el("b", { text: "League modes" }), el("div", { class: "links" }, LM_ORDER.map(function (k) {
      return el("a", { href: "#" + k, onclick: function (e) { e.preventDefault(); state.sheet = false; lmBaseRender(); lmGo(k); } },
        [icon(LM_MODES[k].icon), el("span", { text: LM_MODES[k].short })]);
    }))]), themes);
    return out;
  };
