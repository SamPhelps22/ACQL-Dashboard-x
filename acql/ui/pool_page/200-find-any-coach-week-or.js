  // ---- find: any coach, week or page - a tap, "/" or Ctrl+K ------------------------------
  // It lives outside the page that redraws itself, so new scores arriving
  // never take the box away from someone typing in it.
  var finder = { box: null, input: null, list: null, items: [], shown: [], at: 0, back: null };
  function finderItems() {
    var out = [];
    if (hasMe()) out.push({ kind: "You", label: state.me, sub: "Your page", name: state.me, go: function () { go("me"); } });
    pageList().forEach(function (v) {
      out.push({ kind: "Page", label: VIEWS[v].label, sub: VIEWS[v].about || "", icon: VIEWS[v].icon, go: function () { go(v); } });
    });
    DATA.weeks.slice().sort(function (a, b) { return b.week - a.week; }).forEach(function (w) {
      out.push({ kind: "Week", label: "Week " + w.week, week: w.week, icon: "weeks",
        sub: (w.winners || []).length ? "Won by " + listNames(w.winners, 2) + " with " + w.top : "",
        go: function () { state.week = w.week; go("weeks"); } });
    });
    DATA.players.forEach(function (p) {
      out.push({ kind: "Coach", label: p.name, name: p.name,
        sub: (p.place != null ? ordinal(p.place) + " · " : "") + plural(p.wins, "win"),
        go: function () { openCoach(p.name); } });
    });
    return out;
  }
  function finderMatch(q) {
    q = String(q || "").trim().toLowerCase();
    var all = finder.items;
    if (!q) {
      return all.filter(function (x) { return x.kind !== "Coach" && x.kind !== "Week"; })
        .concat(all.filter(function (x) { return x.kind === "Week"; }).slice(0, 1))
        .concat(all.filter(function (x) { return x.kind === "Coach"; }).slice(0, 5));
    }
    var wk = /^(?:wk|week)?\s*(\d{1,2})$/.exec(q);
    var hits = [];
    all.forEach(function (x) {
      var label = x.label.toLowerCase(), at = label.indexOf(q), score = -1;
      if (wk && x.kind === "Week") score = x.week === +wk[1] ? 0 : -1;
      else if (label === q) score = 0;
      else if (at === 0) score = 1;
      else if (label.split(/[^a-z0-9]+/).some(function (w) { return w.indexOf(q) === 0; })) score = 2;
      else if (at > 0) score = 3;
      else if (x.kind !== "Coach" && (x.sub || "").toLowerCase().indexOf(q) >= 0) score = 4;
      if (score >= 0) hits.push({ x: x, s: score });
    });
    hits.sort(function (a, b) { return a.s - b.s || a.x.label.localeCompare(b.x.label); });
    return hits.slice(0, 12).map(function (h) { return h.x; });
  }
  function finderMark() {
    Array.prototype.forEach.call(finder.list.children, function (li, i) {
      if (li.getAttribute("role") === "option") li.setAttribute("aria-selected", i === finder.at ? "true" : "false");
    });
    var cur = finder.list.children[finder.at];
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" });
    if (finder.shown.length) finder.input.setAttribute("aria-activedescendant", "find-" + finder.at);
    else finder.input.removeAttribute("aria-activedescendant");
  }
  function finderDraw() {
    var shown = finder.shown = finderMatch(finder.input.value);
    finder.at = Math.max(0, Math.min(finder.at, shown.length - 1));
    finder.list.textContent = "";
    if (!shown.length) {
      finder.list.appendChild(el("li", { class: "none", text: "Nobody and nothing by that name." }));
      finderMark();
      return;
    }
    shown.forEach(function (x, i) {
      var lead = x.name ? el("span", { class: "initials", style: avatarStyle(x.name), text: initials(x.name) })
        : el("span", { class: "fic" }, [icon(x.icon || "home")]);
      finder.list.appendChild(el("li", { role: "option", id: "find-" + i, "aria-selected": "false",
        onclick: function () { finderGo(x); },
        onmousemove: function () { if (finder.at !== i) { finder.at = i; finderMark(); } } },
        [lead, el("span", { class: "t" }, [x.label, x.sub ? el("small", { text: x.sub }) : null]), el("span", { class: "k", text: x.kind })]));
    });
    finderMark();
  }
  function closeFinder(going) {
    if (!finder.box) return;
    finder.box.parentNode.removeChild(finder.box);
    finder.box = null;
    document.documentElement.classList.remove("finding");
    if (!going && finder.back && finder.back.focus) { try { finder.back.focus(); } catch (e) { /* gone in a redraw */ } }
  }
  function finderGo(x) { closeFinder(true); x.go(); }
  function openFinder() {
    if (finder.box) return;
    finder.back = document.activeElement;
    finder.items = finderItems();
    finder.at = 0;
    finder.input = el("input", { type: "search", id: "find-input", placeholder: "Find a coach, a week or a page",
      "aria-label": "Find a coach, a week or a page", autocomplete: "off", autocapitalize: "off", spellcheck: "false",
      role: "combobox", "aria-expanded": "true", "aria-controls": "find-list", "aria-autocomplete": "list",
      oninput: function () { finder.at = 0; finderDraw(); },
      onkeydown: function (e) {
        if (e.key === "ArrowDown") { e.preventDefault(); finder.at = Math.min(finder.at + 1, finder.shown.length - 1); finderMark(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); finder.at = Math.max(finder.at - 1, 0); finderMark(); }
        else if (e.key === "Enter") { e.preventDefault(); var x = finder.shown[finder.at]; if (x) finderGo(x); }
        else if (e.key === "Escape") { e.preventDefault(); closeFinder(); }
      } });
    finder.list = el("ul", { class: "fresults", id: "find-list", role: "listbox", "aria-label": "Results" });
    finder.box = el("div", { class: "finder-wrap" }, [
      el("div", { class: "finder-scrim", onclick: function () { closeFinder(); } }),
      el("div", { class: "finder", role: "dialog", "aria-modal": "true", "aria-label": "Find" }, [
        el("div", { class: "fhead" }, [icon("search"), finder.input,
          el("button", { class: "btn", type: "button", "aria-label": "Close", onclick: function () { closeFinder(); } }, [icon("close")])]),
        finder.list,
        el("p", { class: "fhint note", text: "↑ ↓ to choose · Enter to go · Esc to close · press / anywhere to search" })
      ])
    ]);
    document.body.appendChild(finder.box);
    document.documentElement.classList.add("finding");
    finderDraw();
    setTimeout(function () { if (finder.input) finder.input.focus(); }, 0);
  }
  document.addEventListener("keydown", function (e) {
    if (finder.box) return;
    var t = e.target, typing = !!t && (/^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName || "") || t.isContentEditable);
    var slash = e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey;
    var combo = (e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K");
    if (slash || combo) { e.preventDefault(); openFinder(); }
  });

  var heroShown = false;    // the lower third wipes in once a visit, not on every refresh
  // Numbers tagged data-tick flash once when they differ from what this viewer
  // last saw. Within a visit only a redraw of the same page counts (moving to
  // another week or tab is not news); the official standings ("s:") are also
  // remembered between visits, so a new week's totals flash on arrival.
  var TICK_KEY = "acql-pool-seen", tickSeen = {}, drawnOnce = false, drawnWeek = null;
  (function () { var s = storedJSON(TICK_KEY); if (s && typeof s === "object") tickSeen = s; })();
  function ticks(sameView) {
    var keep = {};
    Array.prototype.forEach.call(app.querySelectorAll("[data-tick]"), function (n) {
      var k = n.getAttribute("data-tick"), v = n.textContent;
      var counts = sameView || (!drawnOnce && k.indexOf("s:") === 0);
      if (counts && Object.prototype.hasOwnProperty.call(tickSeen, k) && tickSeen[k] !== v) n.classList.add("ticked");
      tickSeen[k] = v;
    });
    Object.keys(tickSeen).forEach(function (k) { if (k.indexOf("s:") === 0) keep[k] = tickSeen[k]; });
    storeJSON(TICK_KEY, keep);
    drawnOnce = true;
  }
  var shown = "";           // the page last drawn
  function render(opts) {
    opts = opts || {};
    if (opts.quiet && busyHere()) { renderWaiting = true; return; }
    renderWaiting = false;
    var focused = focusKey();
    var ownerBox = document.getElementById("owner");
    var keep = ownerBox ? Array.prototype.slice.call(ownerBox.childNodes) : [];
    var y = window.scrollY;
    // how far each wide table was scrolled sideways, to put it back on the same page
    var here = state.coach ? "coach=" + state.coach : state.view;
    var slid = opts.top || here !== shown ? [] : Array.prototype.map.call(app.querySelectorAll(".scroll"), function (s) { return s.scrollLeft; });
    if (!available(state.view)) state.view = "home";
    if (!weekData(state.week)) state.week = DATA.through_week;
    applyTheme();
    charts = [];
    app.textContent = "";
    app.className = "page";
    app.appendChild(topbar());
    var box = document.getElementById("owner");
    keep.forEach(function (n) { box.appendChild(n); });
    var tk = ticker();
    if (tk) app.appendChild(tk);
    var main = el("main", { id: "main" });
    if (updateBar) main.appendChild(updateBar);
    var view = viewNode();
    var tabs = subnav();
    if (tabs) main.appendChild(tabs);
    main.appendChild(view);
    app.appendChild(main);
    app.appendChild(footer());
    app.appendChild(bottombar());
    app.appendChild(toTop());
    var bar = app.querySelector(".topbar");
    if (bar) document.documentElement.style.setProperty("--bar-h", bar.offsetHeight + "px");
    if (opts.top) view.classList.add("enter");
    (sheet() || []).forEach(function (n) { app.appendChild(n); });
    var hero = view.querySelector(".hero");
    if (hero && !heroShown) { hero.classList.add("enter"); heroShown = true; }
    drawCharts();
    ticks(drawnOnce && here === shown && state.week === drawnWeek);
    drawnWeek = state.week;
    var wide = app.querySelectorAll(".scroll");
    if (slid.length === wide.length) slid.forEach(function (left, i) { if (left) wide[i].scrollLeft = left; });
    shown = state.coach ? "coach=" + state.coach : state.view;
    edges();
    if (opts.top) window.scrollTo(0, 0);
    else if (Math.abs(window.scrollY - y) > 1) window.scrollTo(0, y);
    refocus(focused, opts.top);
    if (cine.open) cineDraw();
    scoreMoved = {};                       // played once; a redraw never plays it again
  }

