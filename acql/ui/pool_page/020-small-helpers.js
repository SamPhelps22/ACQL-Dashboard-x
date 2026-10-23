  // ---- small helpers ------------------------------------------------------
  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v == null || v === false) return;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k === "width") node.style.width = v;
        else if (k === "style") node.setAttribute("style", v);
        else if (k.slice(0, 2) === "on") node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v === true ? "" : v);
      });
    }
    (kids || []).forEach(function (kid) {
      if (kid == null || kid === false) return;
      node.appendChild(typeof kid === "string" || typeof kid === "number" ? document.createTextNode(String(kid)) : kid);
    });
    return node;
  }
  function svgEl(tag, attrs, kids) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === "text") node.textContent = v;
      else if (k.slice(0, 2) === "on") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }
  function stored(key) {
    try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
  }
  function store(key, value) {
    try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch (e) { /* this visit only */ }
  }
  function storedJSON(key) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : null; } catch (e) { return null; }
  }
  function storeJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* full or blocked: fine */ }
  }
  function remember(name) { store(ME_KEY, name); }
  function money(v) {
    if (v == null) return "";
    var sign = v < 0 ? "−" : "";
    return sign + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function dollars(v) {
    if (v == null) return "";
    var sign = v < 0 ? "−" : v > 0 ? "+" : "";
    return sign + "$" + Math.round(Math.abs(v)).toLocaleString("en-US");
  }
  function plural(n, word, many) { return n + " " + (n === 1 ? word : (many || word + "s")); }
  var WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
  function numberWord(n) { return n >= 0 && n <= 10 ? WORDS[n] : String(n); }
  function count(n, word, many) { return (n >= 0 && n <= 10 ? WORDS[n] : String(n)) + " " + (n === 1 ? word : (many || word + "s")); }
  function cap(text) { return text ? text.charAt(0).toUpperCase() + text.slice(1) : text; }
  function listNames(names, max) {
    max = max || 3;
    if (!names.length) return "";
    if (names.length === 1) return names[0];
    if (names.length <= max) return names.slice(0, -1).join(", ") + " & " + names[names.length - 1];
    return names.slice(0, max - 1).join(", ") + " & " + (names.length - max + 1) + " more";
  }
  function ordinal(n) {
    var s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }
  function when(stamp) {
    var d = stamp ? new Date(String(stamp).replace(" ", "T")) : null;
    if (!d || isNaN(d.getTime())) return String(stamp || "");
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  }
  function clock(d) { return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
  function seasonYear() {
    var d = DATA.generated ? new Date(String(DATA.generated).replace(" ", "T")) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    return d.getMonth() < 5 ? d.getFullYear() - 1 : d.getFullYear();
  }
  function weekData(n) {
    for (var i = 0; i < DATA.weeks.length; i++) if (DATA.weeks[i].week === n) return DATA.weeks[i];
    return null;
  }
  function player(name) {
    for (var i = 0; i < DATA.players.length; i++) if (DATA.players[i].name === name) return DATA.players[i];
    return null;
  }
  function names() { return DATA.players.map(function (p) { return p.name; }); }
  function isMe(name) { return !!state.me && name === state.me; }
  function hasMe() { return !!state.me && !!player(state.me); }
  function initials(name) {
    var bits = String(name || "").replace(/[^A-Za-z0-9 ]+/g, " ").trim().split(/\s+/).filter(Boolean);
    if (!bits.length) return "?";
    if (bits.length === 1) return bits[0].slice(0, 2).toUpperCase();
    return (bits[0][0] + bits[bits.length - 1][0]).toUpperCase();
  }
  function who(name) {
    return el("button", { class: "who-link", type: "button", title: "See " + name + "’s season",
      onclick: function () { openCoach(name); }, text: name });
  }
  function scroller(table) {
    return el("div", { class: "scroll-wrap" }, [el("div", { class: "scroll" }, [table])]);
  }
  function edges() {
    Array.prototype.forEach.call(app.querySelectorAll(".scroll"), function (sc) {
      function update() { sc.parentNode.classList.toggle("more", sc.scrollLeft + sc.clientWidth < sc.scrollWidth - 2); }
      if (!sc.acqlEdge) { sc.acqlEdge = true; sc.addEventListener("scroll", update, { passive: true }); }
      update();
    });
  }
  function bar(value, top) {
    return el("div", { class: "bar" + (top > 0 && value >= top ? " top" : ""), width: (top > 0 ? Math.max(0, Math.round(100 * value / top)) : 0) + "%" });
  }
  // Cards side by side on a wide screen; nothing at all when there are none.
  function twoUp(cards) {
    cards = cards.filter(Boolean);
    return cards.length ? el("div", { class: "cols even" }, cards) : null;
  }
  // A fold-out that stays open (or shut) when the page redraws itself.
  var opened = {};
  function fold(key, summary, kids, cls) {
    return el("details", { class: cls || null, open: !!opened[key], ontoggle: function (e) { opened[key] = e.target.open; } },
      [el("summary", { text: summary })].concat(kids));
  }
  // A section of a page: a heading on a heavy rule, then whatever it holds.
  function module(title, aside, kids, attrs) {
    var a = attrs || {};
    a.class = "module" + (a.class ? " " + a.class : "");
    return el("section", a, [el("div", { class: "mhead" }, [el("h2", { text: title }),
      aside == null ? null : typeof aside === "string" ? el("span", { class: "aside", text: aside }) : aside])].concat(kids));
  }
  // An empty or error state: a plain title, a line on why, and the next step.
  function stateMsg(title, detail, action, tone) {
    return el("div", { class: "state-msg" + (tone ? " " + tone : ""), role: tone === "bad" ? "alert" : "status" }, [
      el("strong", { text: title }),
      detail ? el("span", { class: "note", text: detail }) : null,
      action ? el("button", { class: "btn", type: "button", text: action.text, onclick: action.go }) : null
    ]);
  }
  function moreLink(text, view) {
    return el("a", { class: "more-link", href: "#" + view, onclick: function (e) { e.preventDefault(); go(view); }, text: text });
  }
  function aliveNames() {
    return DATA.players.filter(function (p) { return p.suicide.alive; }).map(function (p) { return p.name; });
  }
  function poolAverage() {
    var w = weekData(DATA.through_week);
    if (w && typeof w.pool_average === "number") return w.pool_average;
    if (!DATA.players.length) return 0;
    return DATA.players.reduce(function (a, p) { return a + p.wins; }, 0) / DATA.players.length;
  }
  function titleText(p) {
    if (p.title == null) return "";
    if (p.out_of_reach) return "out";
    if (p.title >= 99.95) return "100%";
    if (p.title < 1) return "<1%";
    return Math.round(p.title) + "%";
  }
  function weeksWon(name) {
    return DATA.weeks.filter(function (w) { return w.winners.indexOf(name) >= 0; }).length;
  }
  // Form over the last three finished weeks: on fire when a coach beat the
  // pool's average every one of them and by FORM_EDGE wins in all, on the hot
  // seat when below it every week by as much. Most coaches are neither.
  var FORM_WEEKS = 3, FORM_EDGE = 4.5, formCache = null;
  function form(name) {
    if (!formCache) {
      formCache = {};
      var last = DATA.weeks.slice().sort(function (a, b) { return b.week - a.week; }).slice(0, FORM_WEEKS);
      if (last.length === FORM_WEEKS) names().forEach(function (n) {
        var diffs = last.map(function (w) {
          var s = w.scores.filter(function (x) { return x.name === n; })[0];
          return s ? s.total - w.average : null;
        });
        if (diffs.some(function (d) { return d == null; })) return;
        var sum = diffs.reduce(function (a, d) { return a + d; }, 0);
        if (sum >= FORM_EDGE && diffs.every(function (d) { return d > 0; })) formCache[n] = { kind: "hot", by: sum };
        else if (sum <= -FORM_EDGE && diffs.every(function (d) { return d < 0; })) formCache[n] = { kind: "cold", by: sum };
      });
    }
    return formCache[name] || null;
  }
  function formText(f) {
    return (f.kind === "hot" ? "On fire: above the pool’s average in each of the last three weeks, "
      : "On the hot seat: below the pool’s average in each of the last three weeks, ") +
      Math.abs(f.by).toFixed(1) + " wins " + (f.kind === "hot" ? "ahead of" : "behind") + " it in all.";
  }
  function formBadge(name) {
    var f = form(name);
    if (!f) return null;
    return el("span", { class: "form " + f.kind, title: formText(f), role: "img", "aria-label": formText(f),
      text: f.kind === "hot" ? "🔥" : "🧊" });
  }
  function leaders() {
    var best = DATA.players.length ? Math.max.apply(null, DATA.players.map(function (p) { return p.wins; })) : 0;
    return DATA.players.filter(function (p) { return p.wins === best; });
  }

