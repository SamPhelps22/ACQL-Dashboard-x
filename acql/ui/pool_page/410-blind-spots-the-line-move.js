  // ---- blind spots, the line move and chaos (patterns.py) -----------------------------------
  // Every split is set against how the rest of the pool did in the same games, so a
  // hard week or a trap line counts against nobody.
  function pctText(x) { return Math.round(100 * x) + "%"; }
  function signed(x, digits) { return (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(digits == null ? 1 : digits); }
  function spotRecord(s) { return s.right + "–" + (s.picks - s.right); }
  function firstLower(text) { return text.charAt(0).toLowerCase() + text.slice(1); }
  function blindSpotsModule(p) {
    var pt = p.patterns;
    if (!pt || !pt.overall || !pt.overall.picks) return null;
    var kids = [];
    function row(kind, s) {
      return el("div", { class: "award", "data-spot": kind }, [
        el("span", { class: "t", text: kind === "blind" ? "Blind spot" : "Strong suit" }),
        el("span", { class: "w", text: s.label + " · " + spotRecord(s) }),
        el("span", { class: "why", text: pctText(s.right / s.picks) + " right, where the rest of the pool hit " + pctText(s.field) + " in the same games." })
      ]);
    }
    (pt.blind || []).forEach(function (s) { kids.push(row("blind", s)); });
    (pt.strong || []).forEach(function (s) { kids.push(row("strong", s)); });
    if (!kids.length) kids.push(el("p", { class: "note", text: "No blind spot or strong suit stands out yet – " + p.name + " picks about as well as usual everywhere." }));
    function teamList(list) { return list.map(function (s) { return firstLower(s.label) + " " + spotRecord(s); }).join(", "); }
    var teams = [];
    if ((pt.weak_teams || []).length) teams.push("weakest " + teamList(pt.weak_teams));
    if ((pt.best_teams || []).length) teams.push("best " + teamList(pt.best_teams));
    if (teams.length) kids.push(el("p", { class: "race-sum", text: "By team: " + teams.join("; ") + "." }));
    var m = pt.move;
    if (m && m.moved) kids.push(el("p", { class: "race-sum", text: "The line move: on the side the line moved toward " + m.with + " of " + plural(m.moved, "time") +
      " it moved a point or more – " + signed(m.gained, 2) + " wins of value between the opening line and kickoff, " + ordinal(m.rank) + " of " + m.of + "." }));
    var a = pt.adjusted;
    if (a) {
      var text = "Weighed by how hard each week was: " + a.adjusted.toFixed(1) + " a week, " + ordinal(a.rank) + " (" + ordinal(a.actual) + " as scored).";
      if (a.wild != null) text += " In wild weeks " + signed(a.wild) + " against the pool" + (a.calm != null ? ", in calm ones " + signed(a.calm) + "." : ".");
      kids.push(el("p", { class: "race-sum", text: text }));
    }
    kids.push(el("p", { class: "note", text: "Each one is compared with how the rest of the pool did in the same games. The line move is settled before kickoff, so it’s skill rather than luck." }));
    return module("Blind spots", spotRecord(pt.overall) + " on every pick", kids, { "data-card": "spots" });
  }

  // How wild a week was against the lines: 0 every favourite came in, 10 once in years.
  function chaosModule(w) {
    var c = w.chaos;
    if (!c) return null;
    return module("Chaos rating", "week " + w.week, [
      el("div", { class: "meter" }, [
        el("div", { class: "top" }, [el("b", { text: c.label }), el("span", { class: "num", text: c.rating.toFixed(1) })]),
        el("div", { class: "track", role: "img", "aria-label": "Chaos rating " + c.rating.toFixed(1) + " of 10" }, [
          el("div", { class: "fill", style: "width:" + Math.round(c.rating * 10) + "%" })]),
        el("span", { class: "why", text: plural(c.upsets, "upset") + " where the lines expected " + c.expected.toFixed(1) + "." +
          (c.biggest ? " The biggest: " + c.biggest + "." : "") })
      ]),
      el("p", { class: "note", text: "A score out of 10 for how surprising the week’s results were. A 7 means seven weeks in ten would have been calmer." })
    ], { "data-card": "chaos" });
  }

