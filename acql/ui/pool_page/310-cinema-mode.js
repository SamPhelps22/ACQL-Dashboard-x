  // ---- Cinema mode -----------------------------------------------------------------------
  var cine = { open: false, node: null, rows: {}, selected: "", fs: false, back: null };
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
      var stand = standing(x);
      function side(team, name, pts) {
        return el("div", { class: "row" + (pick === team ? " pick" : "") + (x.credit === team ? " credit" : "") }, [badge(team, true),
          el("b", { class: "nm", text: name }), el("span", { class: "sc num" + (pts != null && x.state !== "pre" && moved(g) ? " score-new" : ""),
            text: x.state === "pre" || pts == null ? "" : String(pts) })]);
      }
      return el("button", { type: "button", class: "ctile", "data-status": cs.status, "data-warn": cs.warn,
        "aria-pressed": cine.selected === key ? "true" : "false", "data-key": key,
        "aria-label": g.a + " at " + g.h + ", " + st.replace("●", "").trim() + (cine.selected === key ? ", selected" : ""),
        onclick: function () { cine.selected = cine.selected === key ? "" : key; cineDraw(); } }, [
        el("span", { class: "st" }, [el("span", { text: st }), warnTag(cs), sc.tv && cs.status !== "final" ? el("span", { class: "tv", text: sc.tv }) : null]),
        side(g.ac, g.a, x.as), side(g.hc, g.h, x.hs),
        el("span", { class: "ln", text: [g.line != null && g.fav ? "Pool " + g.fav.toUpperCase() + " by " + g.line : "Pool: straight up", market, stand.text].filter(Boolean).join(" · ") })]);
    }
    // keep the open card focused across a redraw
    var focusKey_ = document.activeElement && document.activeElement.getAttribute ? document.activeElement.getAttribute("data-key") : null;
    var head = el("div", { class: "cine-head" }, [
      el("div", { class: "wk" }, [el("span", { text: "ACQL · Week" }), el("b", { text: String(DATA.live.week) })]),
      el("div", { class: "cnt" }, [["total", "Games"], ["live", "Live"], ["final", "Final"], ["upcoming", "To play"]].map(function (p) {
        return el("div", { class: "c" + (p[0] === "live" && s.live ? " on" : "") }, [el("b", { class: "num", text: String(s[p[0]]) }), el("span", { text: p[1] })]);
      })),
      nextNode(t),
      el("button", { class: "cine-exit", type: "button", onclick: closeCinema, text: "Exit ✕", title: "Back to the site (Esc)" })]);
    var grid = el("div", { class: "cine-grid" }, order.map(tile));
    var side = el("aside", { class: "cine-side" }, [
      el("h2", { text: "Pool · if it ended now" }), standStrip(t),
      el("p", { class: "cine-note", text: standAt ? "Standings worked out from the scores at " + clockSec(standAt) + ", by the pool’s own rules." : "" }),
      el("h2", { text: "Just happened" }),
      swings.length ? el("ol", { class: "cine-feed" }, swings.slice(0, 7).map(function (f) {
        return el("li", { class: f.tone || null }, [el("time", { text: clock(f.at) }), el("span", { text: f.title })]);
      })) : el("p", { class: "cine-note", text: "Nothing yet - changes while this page is open show here." }),
      el("h2", { text: "System" }),
      el("p", { class: "cine-health " + fr.level }, [fr.head, fr.detail ? el("small", { text: fr.detail }) : null])]);
    var strip = cine.node.querySelector(".cine-strip");
    var keep = strip ? strip.scrollTop : 0;
    node.textContent = "";
    node.appendChild(head);
    node.appendChild(el("div", { class: "cine-body" }, [grid, side]));
    var fresh = node.querySelector(".cine-strip");
    if (fresh) fresh.scrollTop = keep;
    playStand();
    if (focusKey_) { var f = node.querySelector('[data-key="' + focusKey_ + '"]'); if (f) f.focus({ preventScroll: true }); }
  }
  // The standings strip. Its rows are kept by coach between draws, so a
  // coach changing place glides there (and never because of a redraw).
  function standStrip(t) {
    var box = el("ol", { class: "cine-strip" });
    var first = {};
    Object.keys(cine.rows).forEach(function (k) { if (cine.rows[k].isConnected) first[k] = cine.rows[k].getBoundingClientRect().top; });
    cine.first = first;
    t.rows.forEach(function (r) {
      var name = r.c.name, place = 1 + t.rows.filter(function (o) { return o.now > r.now; }).length;
      var row = cine.rows[name];
      if (!row) {
        row = el("li", { class: "sr" }, [el("span", { class: "p num" }), el("span", { class: "n" }), el("b", { class: "v num" })]);
        cine.rows[name] = row;
      }
      row.className = "sr" + (isMe(name) ? " me" : "");
      row.children[0].textContent = String(place);
      row.children[1].textContent = name + (isMe(name) ? "  · you" : "");
      if (!row.counting) row.children[2].textContent = String(r.now);
      box.appendChild(row);
    });
    return box;
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

