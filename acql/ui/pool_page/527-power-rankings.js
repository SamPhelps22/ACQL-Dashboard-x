  // ---- power rankings: unofficial, beside the official table -------------------------
  // Worked out once, in acql/pool/powerrank.py (DATA.power), from the same weekly
  // scores the site shows; each week's ranking uses only the weeks up to it.
  // Nothing here feeds the official places.
  function powerData() { return DATA.power && DATA.power.weeks && DATA.power.weeks.length ? DATA.power : null; }
  function signed(v) { return v == null ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1); }
  function powerView() {
    var pd = powerData();
    var head = el("div", { class: "pagehead" }, [el("h1", { text: "Power Rankings" })]);
    if (!pd) return el("div", { class: "view", "data-view": "power" }, [head,
      stateMsg("No rankings yet", "Power Rankings start once a week's scores are in.")]);
    var snaps = pd.weeks;
    var wk = Number(state.powerWeek) || snaps[snaps.length - 1].week;
    var snap = snaps.filter(function (s) { return s.week === wk; })[0] || snaps[snaps.length - 1];
    var latest = snap === snaps[snaps.length - 1];
    var picker = el("div", { class: "weeks", role: "group", "aria-label": "Ranking as of week" }, snaps.map(function (s) {
      return el("button", { type: "button", "aria-pressed": s === snap ? "true" : "false", "aria-label": "As of week " + s.week,
        text: String(s.week), onclick: function () { state.powerWeek = s.week; render(); } });
    }));
    // official places as of that week: the table's own for the latest week, shared ties before it
    var official = {};
    if (latest) DATA.players.forEach(function (p) { official[p.name] = p.place; });
    else {
      var tot = {};
      DATA.players.forEach(function (p) {
        var t = 0, any = false;
        Object.keys(p.weekly || {}).forEach(function (w) { if (Number(w) <= snap.week) { t += p.weekly[w]; any = true; } });
        if (any) tot[p.name] = t;
      });
      var ranked = rankAll(tot);
      Object.keys(ranked).forEach(function (n) { official[n] = ranked[n].place; });
    }
    var me = state.me;
    var body = snap.rows.map(function (r) {
      var off = official[r.name];
      var gap = off != null ? off - r.rank : null;
      return el("tr", { class: isMe(r.name) ? "me" : null }, [
        el("td", { class: "num", text: String(r.rank) }),
        el("td", { class: "num pr-move", text: r.move == null ? "new" : r.move > 0 ? "▲" + r.move : r.move < 0 ? "▼" + (-r.move) : "–",
          "aria-label": r.move == null ? "first ranking" : r.move > 0 ? "up " + r.move : r.move < 0 ? "down " + (-r.move) : "no change" }),
        el("td", {}, [who(r.name), r.small ? el("span", { class: "note", text: " (" + plural(r.weeks, "week") + ")" }) : null]),
        el("td", { class: "num", text: signed(r.rating) }),
        el("td", { class: "num", text: off == null ? "–" : ordinal(off) }),
        el("td", { class: "num" + (gap != null && Math.abs(gap) >= 5 ? " pr-gap" : ""), text: gap == null ? "–" : gap > 0 ? "+" + gap : String(gap) }),
        el("td", { class: "num", text: signed(r.recent) }),
        el("td", { class: "num", text: r.last3.map(function (x) { return x == null ? "–" : x; }).join(" · ") }),
        el("td", { class: "num", text: r.spread == null ? "–" : r.spread.toFixed(1) })
      ]);
    });
    var table = el("table", { id: "power-table" }, [
      el("caption", { class: "sr-only", text: "Power Rankings as of week " + snap.week }),
      el("thead", {}, [el("tr", {}, ["Rank", "Move", "Coach", "Rating", "Official", "Gap", "Recent", "Last weeks", "Swing"].map(function (h, i) {
        return el("th", { scope: "col", class: i === 2 ? null : "num", text: h });
      }))]),
      el("tbody", {}, body)
    ]);
    // the biggest differences between the two lists, said plainly
    var diffs = snap.rows.filter(function (r) { return official[r.name] != null && Math.abs(official[r.name] - r.rank) >= 5; })
      .sort(function (a, b) { return Math.abs(official[b.name] - b.rank) - Math.abs(official[a.name] - a.rank); }).slice(0, 4);
    var diffNote = diffs.length ? el("ul", { class: "pr-diffs" }, diffs.map(function (r) {
      var off = official[r.name];
      return el("li", {}, [who(r.name), " is " + ordinal(off) + " in the official table and " + ordinal(r.rank) + " here - " +
        (r.rank < off ? "the recent weeks have been stronger than the season total shows." : "the season total is stronger than the recent weeks.")]);
    })) : el("p", { class: "note", text: "No coach is five or more places apart between the two lists." });
    var m = pd.method;
    var explain = fold("power-how", "How the rankings are worked out", [
      el("p", { text: "Each week, every coach's score is compared with that week's pool average (coaches with no card that week aren't in the average). Three things go in:" }),
      el("ul", {}, [
        el("li", { text: "Recent - the average gap to the pool over the pool's last " + m.recent + " weeks (weight " + m.weights.recent + "). Recent form is what the official table can't show." }),
        el("li", { text: "Earlier - the same over the weeks before those (weight " + m.weights.earlier + "). The two don't overlap, so no week counts twice." }),
        el("li", { text: "Steadiness - how much less a coach's weeks swing than the typical coach's (weight " + m.weights.steadiness + "; needs " + m.steady_min + " weeks)." })
      ]),
      el("p", { text: "Rating = 0.55 × recent + 0.30 × earlier + 0.15 × steadiness, in wins a week against the average coach. When a part is missing its weight is shared out over the rest. Season wins aren't an input - that's the official table's job." }),
      el("p", { class: "note", text: "Calculated with weeks 1–" + snap.week + " only: a past week's ranking uses nothing that happened after it. " +
        (snap.kind === "recorded" ? "This ranking matches the one recorded the first time the site was built with this week." :
          "This ranking is reconstructed from the weekly scores; it was not recorded at the time.") +
        " Coaches with fewer than " + m.small_sample + " weeks are marked. Equal ratings share a place. One season of weekly scores is a small sample: a few tenths of a win is noise, and the rankings have not been tested as a forecast of future weeks." })
    ]);
    return el("div", { class: "view", "data-view": "power" }, [head,
      el("p", { class: "lede", text: "An unofficial ranking of who's picking best lately. It never changes the official standings, scores, money or awards." }),
      el("div", { class: "pr-tools" }, [el("span", { class: "note", text: "As of week" }), picker,
        el("span", { class: "rb-badge " + (snap.kind === "recorded" ? "rb-verified" : "rb-on-record"), text: snap.kind === "recorded" ? "Recorded" : "Reconstructed" })]),
      module("Power Rankings", "week " + snap.week + (hasMe() && me ? "" : ""), [scroller(table),
        el("p", { class: "note", text: "Rating and Recent: wins a week above (+) or below (−) the pool average. Official: the official table" + (latest ? "" : " as of that week (ties shared)") + ". Gap: official place minus power rank. Swing: how much a coach's weeks vary." })]),
      module("Where the two lists differ", null, [diffNote, moreLink("Official standings", "standings")]),
      explain
    ]);
  }
