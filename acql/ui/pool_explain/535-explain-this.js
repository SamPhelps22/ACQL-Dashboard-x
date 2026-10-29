  // ---- explain this: what a number is, where it came from, and whether a recount agrees ----
  // A number is explainable when a view tags it with xa(node, metric, coach, week, other).
  // Everything the panel says comes from DATA.explain (acql/site/explain.py) and the page's
  // own DATA: the definition, method and rules live in one registry there, not in the views.
  var XP = { box: null, back: null };
  var XP_STATUS = {
    "verified": ["Verified", "good", "An independent recount agrees with the number shown."],
    "cross-checked": ["Cross-checked", "cross", "It agrees with a second figure in the official files. That is not an independent recount."],
    "differs": ["Doesn’t match", "bad", "A recount gives a different number. The official figure is shown unchanged."],
    "partial": ["Partly checked", "part", "Only part of this could be recounted."],
    "unchecked": ["Not checked", "none", "Nothing could be recounted for this number."]
  };
  function xpMeta(metric) { var X = DATA.explain; return X && X.metrics ? X.metrics[metric] : null; }
  function xpCoach(name) { var X = DATA.explain; return X && X.coaches ? X.coaches[name] : null; }
  function xpWeek(n) { var X = DATA.explain; return X && X.weeks ? X.weeks[String(n)] : null; }
  function xpBadge(status) {
    var s = XP_STATUS[status] || XP_STATUS.unchecked;
    return el("span", { class: "xp-badge xp-" + s[1], text: s[0] });
  }
  function xpRows(pairs) {
    return el("dl", { class: "xp-kv" }, [].concat.apply([], pairs.filter(function (p) { return p && p[1] != null && p[1] !== ""; }).map(function (p) {
      return [el("dt", { text: p[0] }), el("dd", {}, [typeof p[1] === "object" ? p[1] : String(p[1])])];
    })));
  }
  function xpSection(title, kids) {
    kids = (kids || []).filter(Boolean);
    return kids.length ? el("section", { class: "xp-sec" }, [el("h3", { text: title })].concat(kids)) : null;
  }
  function xpList(items) {
    items = (items || []).filter(Boolean);
    return items.length ? el("ul", { class: "xp-list" }, items.map(function (t) { return el("li", {}, [t]); })) : null;
  }
  function xpSourceFor(week) {
    var w = xpWeek(week);
    var X = DATA.explain || {};
    var src = (X.sources || []).filter(function (s) { return s.kind === "stats" && s.week === week; })[0];
    return { week: w, file: src };
  }
  function xpWeeklyTable(name, weeks, valueOf, col) {
    col = col || 1;
    var c = xpCoach(name) || { weeks: {} };
    return scroller(el("table", { class: "xp-table" }, [
      el("thead", {}, [el("tr", {}, [el("th", { class: "n", text: "Wk" }), el("th", { class: "n", text: "On file" }),
        el("th", { class: "n", text: "Recount" }), el("th", { text: "Check" })])]),
      el("tbody", {}, weeks.map(function (n) {
        var r = c.weeks[String(n)] || ["unchecked", null, null, "no recount kept"];
        var v = valueOf(n);
        return el("tr", {}, [el("td", { class: "n num", text: String(n) }), el("td", { class: "n num", text: v == null ? "–" : String(v) }),
          el("td", { class: "n num", text: r[col] == null ? "–" : String(r[col]) }), el("td", {}, [xpBadge(r[0]), r[3] ? el("small", { class: "xp-why", text: " " + r[3] }) : null])]);
      }))
    ]));
  }
  function xpWeeksOf(name) {
    var p = player(name);
    return p ? Object.keys(p.weekly).map(Number).sort(function (a, b) { return a - b; }) : [];
  }

  // What each kind of number shows: [value shown, source records, validation, issues]
  function xpExplain(metric, name, week, other) {
    var p = name ? player(name) : null, c = name ? xpCoach(name) : null, X = DATA.explain || {};
    var out = { value: "", sources: [], check: null, checkText: "", issues: [], week: week || DATA.through_week };
    if (metric === "weekly_score") {
      var w = weekData(week), s = w ? w.scores.filter(function (x) { return x.name === name; })[0] : null;
      var sw = xpSourceFor(week), r = c && c.weeks[String(week)];
      out.value = s ? String(s.total) : "–";
      out.sources.push(xpRows([["Coach", name], ["Week", week], ["Picks right", s ? s.regular : null],
        ["Big Loser points", s ? s.big_loser : null], ["Total", s ? s.total : null],
        ["From", sw.week && sw.week.source ? sw.week.source : null],
        ["Pick sheet", sw.week && sw.week.sheet ? sw.week.sheet + (sw.week.sheet_graded ? " (graded copy)" : "") : null]]));
      if (r) {
        out.check = r[0];
        out.checkText = r[0] === "verified" ? "Every pick re-graded against ESPN’s final scores with the line rule (picks from the stats export, or the pick sheet where the export leaves them out), and each Big Loser pick checked against the final margin: recount " + r[1] + ", on file " + r[2] + "."
          : r[0] === "differs" ? "Recount " + r[1] + ", on file " + r[2] + (r[3] ? " (" + r[3] + ")" : "") + "."
          : (r[3] ? r[3].charAt(0).toUpperCase() + r[3].slice(1) + "." : "");
      }
      if (sw.week) {
        out.issues = out.issues.concat(sw.week.issues || []);
        (sw.week.game_diffs || []).forEach(function (g) {
          out.issues.push("Game " + g.game + " (" + g.matchup + "): on file " + (g.on_file || "–") + ", ESPN gives " + (g.espn || "–") + " — " + g.why + ".");
        });
        if (sw.week.official === false) out.issues.push("This week was worked out from the scores; the official file doesn’t cover it yet.");
      }
    } else if (metric === "season_wins" || metric === "place" || metric === "move") {
      var weeks = xpWeeksOf(name), m = c ? c[metric === "season_wins" ? "wins" : metric] : null;
      if (metric === "season_wins") out.value = p ? String(p.wins) : "–";
      else if (metric === "place") out.value = p && p.place != null ? placeText(p) : "–";
      else out.value = !p || p.move == null ? "–" : p.move > 0 ? "▲" + p.move : p.move < 0 ? "▼" + (-p.move) : "no change";
      if (metric === "season_wins") {
        out.sources.push(xpWeeklyTable(name, weeks, function (n) { return p.weekly[String(n)]; }));
        if (c) out.sources.push(xpRows([["Weekly scores added up", c.wins.sum_of_weeks], ["Shown", c.wins.shown], ["Taken from", c.wins.from]]));
      } else if (metric === "place" && c) {
        out.sources.push(xpRows([["Season wins", p.wins], ["Coaches on the same total", c.place.tied], ["Place by competition ranking", c.place.recount],
          ["Place shown", c.place.shown], ["Taken from", c.place.from]]));
      } else if (c) {
        out.sources.push(xpRows([["Place the week before", c.move.before], ["Place now", c.place.shown], ["Movement shown", c.move.shown],
          ["Movement from the weekly scores", c.move.recount], ["Taken from", c.move.from]]));
      }
      if (m) {
        out.check = m.status;
        out.checkText = (m.note ? m.note.charAt(0).toUpperCase() + m.note.slice(1) + ". " : "") +
          (metric === "season_wins" ? "Compared with the weekly scores added up. " + (c.weeks_verified + " of " + c.weeks_total + " of those weekly scores were independently verified.") : "Compared with a ranking of the weekly scores added up.");
      }
      if (c) (c.conflicts || []).forEach(function (k) { out.issues.push("The files disagree on " + k.field + ": " + k.official + " was used, another file says " + k.other + (k.note ? " (" + k.note + ")" : "") + "."); });
      if (m && m.status === "differs") out.issues.push("The official figure and the recount differ. Nothing on the page was changed; the commissioner decides which is right.");
    } else if (metric === "big_loser") {
      out.value = p ? String(p.big_loser || 0) : "–";
      var b = c && c.big_loser;
      if (b) {
        var bw = Object.keys(b.by_week).map(Number).sort(function (x, y) { return x - y; });
        out.sources.push(xpWeeklyTable(name, bw, function (n) { return b.by_week[String(n)]; }, 4));
        out.sources.push(xpRows([["Weekly points added up", b.sum_of_weeks], ["Independent recount", b.independent], ["Shown", b.shown]]));
        out.check = b.status;
        out.checkText = b.independent != null ? "Each week’s Big Loser picks checked against ESPN’s final margins: " + b.independent + " in all."
          : "Not every week’s Big Loser picks could be checked against final scores; compared with the weekly points instead.";
      }
    } else if (metric === "suicide") {
      var su = p ? p.suicide : null, cs = c && c.suicide;
      out.value = !su ? "–" : su.alive ? "Still in" : su.out ? "Out in week " + su.out : "Not in";
      if (su) out.sources.push(xpRows(Object.keys(su.picks).sort(function (a, b) { return a - b; }).map(function (wk) { return ["Week " + wk + " pick", su.picks[wk]]; })
        .concat([["Out in week", su.out]])));
      if (cs) {
        out.check = cs.status;
        out.checkText = "Worked out again from each pick and the result with the lines applied: " + (cs.recount_alive ? "still in" : cs.recount_out ? "out in week " + cs.recount_out : "not in") + "." +
          (cs.files_out ? " The files mark them out in week " + cs.files_out + "." : "");
      }
    } else if (metric === "h2h") {
      var cmp = compare(name, other), both = cmp.weeks.filter(function (r) { return r.a != null && r.b != null; });
      var ca = xpCoach(name), cb = xpCoach(other), ok = 0, bad = 0;
      both.forEach(function (r) {
        var a = ca && ca.weeks[String(r.week)], bb = cb && cb.weeks[String(r.week)];
        if (a && bb && a[0] === "verified" && bb[0] === "verified") ok++;
        if ((a && a[0] === "differs") || (bb && bb[0] === "differs")) bad++;
      });
      out.value = cmp.aWeeks + "–" + cmp.bWeeks + (cmp.level ? "–" + cmp.level : "");
      out.sources.push(scroller(el("table", { class: "xp-table" }, [
        el("thead", {}, [el("tr", {}, [el("th", { class: "n", text: "Wk" }), el("th", { class: "n", text: name }), el("th", { class: "n", text: other }), el("th", { class: "n", text: "Right in splits" })])]),
        el("tbody", {}, both.map(function (r) {
          return el("tr", {}, [el("td", { class: "n num", text: String(r.week) }), el("td", { class: "n num", text: String(r.a) }),
            el("td", { class: "n num", text: String(r.b) }), el("td", { class: "n num", text: r.aRight + "–" + r.bRight })]);
        }))])));
      out.sources.push(xpRows([["Weeks " + name + " scored higher", cmp.aWeeks], ["Weeks " + other + " scored higher", cmp.bWeeks], ["Level weeks", cmp.level],
        ["Games they split", cmp.aSplit + cmp.bSplit], ["Same pick", cmp.agree + " of " + cmp.both]]));
      out.check = !both.length ? "unchecked" : bad ? "differs" : ok === both.length ? "verified" : ok ? "partial" : "unchecked";
      out.statusText = "This record has no source of its own; the badge is about its inputs, both coaches’ weekly scores.";
      out.checkText = "Built here from the weekly scores, so it is checked through them: both coaches’ scores independently verified in " + ok + " of " + both.length + " weeks" + (bad ? "; " + bad + " week(s) where a recount differs" : "") + ".";
    }
    if (!DATA.explain) out.issues.push("No checking evidence was published with this copy of the page, so nothing here could be validated.");
    return out;
  }

  function closeExplain(going) {
    if (!XP.box) return;
    XP.box.parentNode.removeChild(XP.box);
    XP.box = null;
    document.documentElement.classList.remove("explaining");
    if (!going && XP.back && XP.back.focus) { try { XP.back.focus(); } catch (e) { /* gone in a redraw */ } }
  }
  function openExplain(metric, name, week, other) {
    var meta = xpMeta(metric);
    if (!meta && !DATA.explain) meta = { label: "This number", definition: "", method: "", rules: [], shown_in: [] };
    if (!meta) return;
    closeExplain(true);
    XP.back = document.activeElement;
    week = week ? Number(week) : null;
    var x = xpExplain(metric, name, week, other), X = DATA.explain || {};
    var sw = xpSourceFor(x.week), statsFile = sw.file;
    var title = meta.label + (name ? " · " + name + (other ? " vs " + other : "") : "") + (week ? " · Week " + week : "");
    var when = [["Season", X.year || null], ["Week", week || (DATA.through_week ? "Through week " + DATA.through_week : null)],
      ["Page built", DATA.generated], ["Official file", statsFile ? statsFile.name + (statsFile.modified ? ", saved " + statsFile.modified : "") : (sw.week && sw.week.source) || null],
      ["ESPN scores kept", sw.week ? sw.week.espn_time : null],
      ["Standings", X.official === false ? "worked out from the weeks shown (the official file is behind)" : X.official ? "official, through week " + X.through_week : null]];
    var issues = x.issues.slice();
    if ((X.provisional_weeks || []).length) issues.push("Provisional weeks (not yet in an official file): " + X.provisional_weeks.join(", ") + ".");
    (X.warnings || []).slice(0, 3).forEach(function (w) { issues.push(w); });
    var close = el("button", { class: "btn", type: "button", "aria-label": "Close", onclick: function () { closeExplain(); } }, [icon("close")]);
    var panel = el("div", { class: "xp-panel", role: "dialog", "aria-modal": "true", "aria-labelledby": "xp-title",
      onkeydown: function (e) { if (e.key === "Escape") { e.preventDefault(); closeExplain(); } } }, [
      el("div", { class: "xp-head" }, [el("div", {}, [el("span", { class: "xp-kicker", text: "Explain this" }), el("h2", { id: "xp-title", text: title })]), close]),
      el("div", { class: "xp-body" }, [
        el("div", { class: "xp-value" }, [el("b", { class: "num", text: x.value }), x.check ? xpBadge(x.check) : null]),
        meta.definition ? el("p", { class: "xp-def", text: meta.definition }) : null,
        xpSection("Source records", x.sources.length ? x.sources : [el("p", { class: "note", text: "No source records for this number were published with the page." })]),
        xpSection("How it’s worked out", [meta.method ? el("p", { text: meta.method }) : null, xpList(meta.rules)]),
        xpSection("When and which week", [xpRows(when)]),
        xpSection("Validation", [el("p", {}, [x.check ? xpBadge(x.check) : xpBadge("unchecked"), " ", x.statusText || (XP_STATUS[x.check] || XP_STATUS.unchecked)[2]]),
          x.checkText ? el("p", { class: "note", text: x.checkText }) : null]),
        xpSection("Also used in", [meta.shown_in && meta.shown_in.length ? el("div", { class: "xp-chips" }, meta.shown_in.map(function (s) { return el("span", { class: "chip", text: s }); })) : el("p", { class: "note", text: "Only here." })]),
        xpSection("Gaps and issues", [issues.length ? xpList(issues) : el("p", { class: "note", text: "None found." })])
      ])
    ]);
    XP.box = el("div", { class: "xp-wrap" }, [el("div", { class: "xp-scrim", onclick: function () { closeExplain(); } }), panel]);
    document.body.appendChild(XP.box);
    document.documentElement.classList.add("explaining");
    setTimeout(function () { try { close.focus(); } catch (e) { /* closed already */ } }, 0);
  }
  function xpFrom(node) {
    return [node.getAttribute("data-x"), node.getAttribute("data-xc") || "", node.getAttribute("data-xw") || "", node.getAttribute("data-xb") || ""];
  }
  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target.closest("[data-x]") : null;
    if (!t || (XP.box && XP.box.contains(t))) return;
    e.preventDefault();
    e.stopPropagation();
    var a = xpFrom(t);
    openExplain(a[0], a[1], a[2], a[3]);
  }, true);
  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (!t || !t.getAttribute || !t.getAttribute("data-x") || (e.key !== "Enter" && e.key !== " ")) return;
    e.preventDefault();
    var a = xpFrom(t);
    openExplain(a[0], a[1], a[2], a[3]);
  });
  // Tagged numbers can be reached from the keyboard and say what they open.
  (function () {
    function mark(root) {
      var nodes = root.querySelectorAll ? root.querySelectorAll("[data-x]:not([tabindex])") : [];
      for (var i = 0; i < nodes.length; i++) {
        nodes[i].setAttribute("tabindex", "0");
        nodes[i].setAttribute("role", "button");
        nodes[i].setAttribute("aria-haspopup", "dialog");
        if (!nodes[i].getAttribute("aria-label")) nodes[i].setAttribute("aria-label", (nodes[i].textContent || "").trim() + " — explain this number");
      }
    }
    if (typeof MutationObserver === "function" && app) new MutationObserver(function () { mark(app); }).observe(app, { childList: true, subtree: true });
    if (app) mark(app);
  })();
