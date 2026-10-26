  // ---- what each coach needs to win the week (#86) ---------------------------------
  function needsCard(t, sim) {
    var rows = DATA.live.coaches.map(function (co) { return { name: co.name, p: sim.chance[co.name] || 0 }; })
      .filter(function (r) { return r.p >= 0.01; })
      .sort(function (a, b) { return b.p - a.p; }).slice(0, 8);
    if (!rows.length || !sim.open.length) return null;
    return module("What each coach needs", "to win the week from here", [el("div", { class: "records" }, rows.map(function (r) {
      var need = needs(t, sim, r.name) || [];
      return el("div", { class: "record" + (isMe(r.name) ? " me" : "") }, [
        el("span", { class: "k", text: pct(r.p) + " to win" }), el("span", { class: "v", text: r.name }),
        el("span", { class: "d", text: need.length ? "Needs " + listNames(need, 4) : "No single result they can't do without" })]);
    })), el("p", { class: "note", text: "A result shows when it went that way in nearly every simulated finish where they won the week." })],
      { "data-card": "needs" });
  }

  // ---- the live page --------------------------------------------------------------
  function liveView() {
    var L = DATA.live;
    if (!live.fetched && !live.error && !live.busy) fetchScores();
    var t = liveTally();
    var sim = simulate(t);
    var pay = moneyNow(t), started = t.games.some(function (x) { return x.state !== "pre"; });
    var bestNow = started && !weekOver(t) ? bestPlaces(t) : null;
    // the games not on now: the next kickoffs first, then the ones over
    var later = t.games.filter(function (x) { return x.state === "pre"; }).sort(function (a, b) {
      return (a.sc && a.sc.off ? 1 : 0) - (b.sc && b.sc.off ? 1 : 0) || (a.kick || Infinity) - (b.kick || Infinity);
    });
    var done = t.games.filter(function (x) { return x.state === "post"; });
    var head = [el("th", { class: "n", text: "#" }), el("th", { class: "stick-b", text: "Coach" }),
      el("th", { class: "n", text: "Now" }),
      bestNow ? el("th", { class: "n", text: "Best", title: "The best place they can still finish this week" }) : null,
      el("th", { class: "n", text: "Win %" }),
      el("th", { class: "n", text: weekOver(t) ? "Pays" : "$ now", title: weekOver(t) ? "What the week pays" : "Money if it ended now" }),
      el("th", { class: "n hide-narrow", text: "Final" }),
      el("th", { class: "n hide-narrow", text: "Left" }), el("th", { class: "n", text: "BL" }),
      el("th", { class: "n", text: "Season" }), el("th", { "data-col": "suicide", text: "Suicide" })];
    t.games.forEach(function (x) { head.push(el("th", { class: "gk", text: x.g.ac.toUpperCase() + " @ " + x.g.hc.toUpperCase() })); });
    var body = t.rows.map(function (r) {
      var place = 1 + t.rows.filter(function (o) { return o.now > r.now; }).length;
      var suiText = { pending: r.c.sui.toUpperCase(), safe: r.c.sui.toUpperCase() + " ✓", ahead: r.c.sui.toUpperCase() + " ahead",
        behind: r.c.sui.toUpperCase() + " behind", level: r.c.sui.toUpperCase() + " level", out: r.c.sui.toUpperCase() + " ✗ out" }[r.sui] || "–";
      var m = pay[r.c.name];
      var cells = [el("td", { class: "n place num", text: String(place) }),
        el("td", { class: "coach stick-b" }, [who(r.c.name)]),
        el("td", { class: "n total num", text: String(r.now) }),
        bestNow ? el("td", { class: "n num", text: ordinal(bestNow[r.c.name]) }) : null,
        el("td", { class: "n num", text: pct(sim.chance[r.c.name] || 0) }),
        el("td", { class: "n num cash " + (started ? cashTone(m) : "flat"), text: started ? cash(m) : "–" }),
        el("td", { class: "n num hide-narrow", text: String(r.final) }),
        el("td", { class: "n num hide-narrow", text: String(r.left) }),
        el("td", { class: "n num", text: r.bl ? String(r.bl) : "–" }),
        el("td", { class: "n num", text: String(r.season) }),
        el("td", { class: r.sui === "safe" || r.sui === "ahead" ? "sui-ok" : r.sui === "out" || r.sui === "behind" ? "sui-no" : "", text: suiText })];
      t.games.forEach(function (x, gi) {
        var pick = r.c.picks[gi] || "";
        var cls = "pk";
        if (pick && x.state !== "pre") cls += (x.credit === pick ? " ok" : x.credit ? " no" : "") + (x.state === "in" ? " live" : "");
        cells.push(el("td", { class: cls, text: pick ? pick.toUpperCase() : "·" }));
      });
      return el("tr", { class: isMe(r.c.name) ? "me" : null }, cells);
    });
    return el("div", { class: "view", "data-view": "live" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Week " + L.week + ", as it happens" }), liveStatus(t)]),
      slateStrip(t),
      fold("live:how", "How the live numbers work", [el("p", { class: "note", text: "Now counts every pick that is right as the scores stand, plus Big Loser teams losing by 15 or more. Best is the highest place a coach can still finish, every result still to come going their way - certain, not simulated. Win % is each coach’s chance of having the best week. $ now is what the week would pay if it ended now: the best card collects a dollar a game from every card behind it, and tied cards split it. Final counts finished games only. Season adds Now to each coach’s wins so far." })], "howto"),
      weekOver(t) ? finalBanner(t, false) : null,
      onNowModule(t),
      el("div", { class: "cols" }, [
        el("div", {}, weekOver(t) ? [] : [rootingCard(t, sim), swingCard(t, sim)]),
        el("div", {}, [swingsFeed(), weekPoolsBrief(t), limbCard(t)])
      ]),
      weekOver(t) ? null : needsCard(t, sim),
      module("Every card", "tap a name for their week", [scroller(el("table", { id: "live-table" }, [el("thead", {}, [el("tr", {}, head)]), el("tbody", {}, body)]))]),
      later.length ? module("Still to play", plural(later.length, "game"), [el("div", { class: "games" }, later.map(gameCard))], { "data-card": "to-play" }) : null,
      done.length ? module("Final", plural(done.length, "game"), [el("div", { class: "games" }, done.map(gameCard))], { "data-card": "finals" }) : null,
      el("div", {}, [el("button", { class: "btn", type: "button", text: "Refresh scores now", onclick: function () { fetchScores(); } })])
    ]);
  }

