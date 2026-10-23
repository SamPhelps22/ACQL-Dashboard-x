  // ---- pick twins and nemeses ---------------------------------------------------------------
  // From every game played: who picks most like this coach and least like them,
  // and who has had the better of them week for week - and who they've had the
  // better of. Head-to-head shows any pair in full.
  var TWIN_MIN_GAMES = 10;
  function matchups(name) {
    return names().filter(function (n) { return n !== name; }).map(function (n) {
      var c = compare(name, n), margin = 0;
      c.weeks.forEach(function (r) { if (r.a != null && r.b != null) margin += r.a - r.b; });
      return { name: n, c: c, agree: c.both >= TWIN_MIN_GAMES ? c.agree / c.both : null, net: c.aWeeks - c.bWeeks, margin: margin };
    });
  }
  function twinsModule(p) {
    var all = matchups(p.name);
    var known = all.filter(function (m) { return m.agree != null; });
    if (!known.length) return null;
    function best(list, better) { return list.slice().sort(better)[0]; }
    var twin = best(known, function (a, b) { return b.agree - a.agree || b.c.both - a.c.both || a.name.localeCompare(b.name); });
    var opposite = best(known, function (a, b) { return a.agree - b.agree || b.c.both - a.c.both || a.name.localeCompare(b.name); });
    var nemesis = best(all.filter(function (m) { return m.net < 0; }), function (a, b) { return a.net - b.net || a.margin - b.margin || a.name.localeCompare(b.name); });
    var victim = best(all.filter(function (m) { return m.net > 0; }), function (a, b) { return b.net - a.net || b.margin - a.margin || a.name.localeCompare(b.name); });
    function pct(m) { return Math.round(100 * m.agree) + "%"; }
    function weeksText(m) {
      var more = m.margin > 0 ? p.name : m.margin < 0 ? m.name : "";
      return "Higher score: " + p.name + " " + plural(m.c.aWeeks, "week") + ", " + m.name + " " + m.c.bWeeks +
        (m.c.level ? ", level " + m.c.level : "") + (more ? " · " + more + " by " + plural(Math.abs(m.margin), "win") + " in all" : "");
    }
    function row(kind, label, m, big, meta) {
      return el("button", { class: "twin", type: "button", "data-twin": kind, title: "Head-to-head: " + p.name + " and " + m.name,
        onclick: function () { state.a = p.name; state.b = m.name; store(VS_KEY, m.name); go("h2h"); } }, [
        el("span", { class: "k", text: label }),
        el("span", { class: "nm", text: m.name }),
        el("span", { class: "big num", text: big }),
        el("span", { class: "meta", text: meta })
      ]);
    }
    var kids = [];
    kids.push(row("twin", "Pick twin", twin, pct(twin), "The same side in " + twin.c.agree + " of " + plural(twin.c.both, "game")));
    if (opposite && opposite.name !== twin.name) kids.push(row("opposite", "Opposite", opposite, pct(opposite),
      "The same side in only " + opposite.c.agree + " of " + plural(opposite.c.both, "game")));
    if (nemesis) kids.push(row("nemesis", "Nemesis", nemesis, nemesis.c.aWeeks + "–" + nemesis.c.bWeeks, weeksText(nemesis)));
    if (victim) kids.push(row("victim", "Favourite victim", victim, victim.c.aWeeks + "–" + victim.c.bWeeks, weeksText(victim)));
    var up = all.filter(function (m) { return m.net > 0; }).length, down = all.filter(function (m) { return m.net < 0; }).length;
    var even = all.length - up - down;
    var parts = ["the better of " + (up || "none") + (up ? " of " + plural(all.length, "coach", "coaches") : ""),
      down ? "the worse of " + down : "the worse of nobody"];
    if (even) parts.push("even with " + even);
    kids.push(el("p", { class: "race-sum", text: "Week for week, " + p.name + " has had " + parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] + "." }));
    kids.push(el("p", { class: "note", text: "Tap one for the full head-to-head. Twins are counted over every game played. Weeks include Big Loser points." }));
    return module("Twins and nemeses", null, [el("div", { class: "twins" }, kids)], { "data-card": "twins" });
  }

