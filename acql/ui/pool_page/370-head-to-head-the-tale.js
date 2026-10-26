  // ---- head-to-head: the tale of the tape -------------------------------------------------
  function rememberedVs() { return stored(VS_KEY); }
  function pair() {
    var all = names();
    var a = all.indexOf(state.a) >= 0 ? state.a : (all.indexOf(state.me) >= 0 ? state.me : all[0]);
    var b = all.indexOf(state.b) >= 0 ? state.b : rememberedVs();
    if (all.indexOf(b) < 0 || b === a) b = all[0] !== a ? all[0] : all[1];
    state.a = a;
    state.b = b;
    return [a, b];
  }
  function vsHash() { return "#vs=" + encodeURIComponent(state.a) + "&" + encodeURIComponent(state.b); }
  function setPair(a, b) {
    state.a = a;
    state.b = b;
    store(VS_KEY, b);
    try { history.replaceState(null, "", vsHash()); } catch (e) { /* not allowed here */ }
    render();
  }
  // Two coaches week by week and pick by pick - the one place this is worked
  // out (the coach pages, the Numbers Room and Broadcast all read it). From
  // and to, when given, keep to that run of weeks.
  function compare(a, b, from, to) {
    var out = { weeks: [], agree: 0, both: 0, aSplit: 0, bSplit: 0, aWeeks: 0, bWeeks: 0, level: 0 };
    DATA.weeks.slice().sort(function (x, y) { return x.week - y.week; }).forEach(function (w) {
      if ((from && w.week < from) || (to && w.week > to)) return;
      var pa = w.picks && w.picks[a], pb = w.picks && w.picks[b];
      var sa = null, sb = null;
      w.scores.forEach(function (s) { if (s.name === a) sa = s.total; if (s.name === b) sb = s.total; });
      var row = { week: w.week, a: sa, b: sb, splits: [], aRight: 0, bRight: 0 };
      if (pa && pb) {
        for (var j = 0; j < Math.min(pa.length, pb.length); j++) {
          if (pa[j] === "-" || pb[j] === "-") continue;
          out.both++;
          if (pa[j] === pb[j]) { out.agree++; continue; }
          var g = w.results[j] || {};
          var aOk = pa[j] === "1";
          row.splits.push({ game: g.matchup || "", aTeam: aOk ? g.winner : g.loser, bTeam: aOk ? g.loser : g.winner, aOk: aOk });
          if (aOk) row.aRight++; else row.bRight++;
        }
        out.aSplit += row.aRight;
        out.bSplit += row.bRight;
      }
      if (sa != null && sb != null) {
        if (sa > sb) out.aWeeks++; else if (sb > sa) out.bWeeks++; else out.level++;
      }
      out.weeks.push(row);
    });
    return out;
  }
  function h2hView() {
    var ab = pair(), a = ab[0], b = ab[1];
    var pa = player(a), pb = player(b);
    var all = names().slice().sort(function (x, y) { return x.localeCompare(y); });
    function chooser(value, label, onpick) {
      return el("select", { "aria-label": label, onchange: function (e) { onpick(e.target.value); } }, all.map(function (n) {
        return el("option", { value: n, text: n, selected: n === value });
      }));
    }
    var copy = el("button", { class: "linkish", type: "button", text: "Copy a link to this matchup" });
    copy.addEventListener("click", function () {
      var link = location.href.split("#")[0] + vsHash();
      var done = function () { copy.textContent = "Link copied"; };
      try { navigator.clipboard.writeText(link).then(done, function () { copy.textContent = link; }); } catch (e) { copy.textContent = link; }
    });
    var c = compare(a, b);
    var agreePct = c.both ? Math.round(100 * c.agree / c.both) : 0;
    function line(l, key, r, better) {
      return el("div", { class: "line" }, [el("span", { class: "l" + (better < 0 ? " ahead" : ""), text: l }),
        el("span", { class: "k", text: key }), el("span", { class: "rr" + (better > 0 ? " ahead" : ""), text: r })]);
    }
    var tape = el("section", { class: "tape", "aria-label": a + " against " + b }, [
      el("div", { class: "names" }, [el("b", { text: a }), el("span", { text: "vs" }), el("b", { text: b })]),
      line(String(pa.wins), "season wins", String(pb.wins), pb.wins - pa.wins),
      line(pa.place != null ? ordinal(pa.place) : "–", "place", pb.place != null ? ordinal(pb.place) : "–", (pa.place || 99) - (pb.place || 99) > 0 ? 1 : (pa.place || 99) < (pb.place || 99) ? -1 : 0),
      line(String(c.aWeeks), "weeks with the higher score", String(c.bWeeks), c.bWeeks - c.aWeeks),
      line(String(c.aSplit), "right when they split", String(c.bSplit), c.bSplit - c.aSplit),
      line(String(pa.big_loser || 0), "Big Loser points", String(pb.big_loser || 0), (pb.big_loser || 0) - (pa.big_loser || 0)),
      el("div", { class: "line" }, [el("span", {}), el("span", { class: "k", text: agreePct + "% the same pick (" + c.agree + " of " + c.both + ")" }), el("span", {})])
    ]);
    var rows = c.weeks.slice().reverse().map(function (r) {
      var cls = function (x, y) { return "n num" + (x != null && y != null && x > y ? " won-it" : ""); };
      return el("tr", {}, [
        el("td", { class: "n num", text: String(r.week) }),
        el("td", { class: cls(r.a, r.b), text: r.a == null ? "–" : String(r.a) }),
        el("td", { class: cls(r.b, r.a), text: r.b == null ? "–" : String(r.b) }),
        el("td", { class: "n num", text: String(r.splits.length) }),
        el("td", { class: "n num", text: r.aRight + "–" + r.bRight })
      ]);
    });
    var weekList = c.weeks.filter(function (r) { return r.splits.length; });
    var shownWeek = weekList.filter(function (r) { return r.week === state.week; })[0] || weekList[weekList.length - 1];
    var picker = weekList.length > 1 ? el("div", { class: "weeks", role: "group", "aria-label": "Choose a week" }, weekList.map(function (r) {
      return el("button", { type: "button", "aria-pressed": r === shownWeek ? "true" : "false", "aria-label": "Week " + r.week,
        onclick: function () { state.week = r.week; render(); }, text: String(r.week) });
    })) : null;
    var splits = shownWeek ? scroller(el("table", {}, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Game" }), el("th", { text: a }), el("th", { text: b })])]),
      el("tbody", {}, shownWeek.splits.map(function (s) {
        return el("tr", { class: "split-row" }, [
          el("td", { class: "game", text: s.game }),
          el("td", { class: s.aOk ? "ok" : "no", text: s.aTeam + (s.aOk ? " ✓" : "") }),
          el("td", { class: s.aOk ? "no" : "ok", text: s.bTeam + (s.aOk ? "" : " ✓") })
        ]);
      }))
    ])) : null;
    return el("div", { class: "view", "data-view": "h2h" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Head-to-head" }), copy]),
      el("div", { class: "vs" }, [
        chooser(a, "First coach", function (v) { setPair(v, v === b ? a : b); }),
        el("span", { class: "and", text: "vs" }),
        chooser(b, "Second coach", function (v) { setPair(v === a ? b : a, v); }),
        el("button", { class: "btn", type: "button", title: "Swap them", "aria-label": "Swap the two coaches", text: "⇄", onclick: function () { setPair(b, a); } })
      ]),
      tape,
      module("Week by week", null, [scroller(el("table", { id: "h2h-weeks" }, [
        el("thead", {}, [el("tr", {}, [el("th", { class: "n", text: "Wk" }), el("th", { class: "n", text: a }),
          el("th", { class: "n", text: b }), el("th", { class: "n", text: "Split", title: "Games where they picked different sides" }), el("th", { class: "n", text: "Right", title: "Who was right in those games" })])]),
        el("tbody", {}, rows)
      ]))]),
      shownWeek ? module("Where they split in week " + shownWeek.week, picker, [splits])
        : el("p", { class: "note", text: a + " and " + b + " have picked the same side in every game so far." }),
      el("p", { class: "note", text: "Only finished games. ✓ is the side that got the point. Scores include Big Loser points." })
    ]);
  }

