  // ---- one coach's page (the viewer's own is Me) -------------------------------------------
  function coachView(p) {
    var mine = isMe(p.name);
    var s = p.suicide;
    var lead = DATA.players.length ? DATA.players[0].wins : 0;
    var weeks = DATA.weeks.slice().sort(function (a, b) { return b.week - a.week; });
    var played = 0, won = 0, best = null, worst = null, diff = 0, moneyWon = 0;
    var rows = [];
    weeks.forEach(function (w) {
      var me = null;
      for (var i = 0; i < w.scores.length; i++) if (w.scores[i].name === p.name) me = w.scores[i];
      if (!me) return;
      played++;
      var rank = 1 + w.scores.filter(function (o) { return o.total > me.total; }).length;
      var tiedRank = w.scores.filter(function (o) { return o.total === me.total; }).length > 1;
      var isWin = w.winners.indexOf(p.name) >= 0;
      if (isWin) { won++; if (w.payout_each) moneyWon += w.payout_each; }
      if (!best || me.total > best.total) best = { total: me.total, week: w.week };
      if (!worst || me.total < worst.total) worst = { total: me.total, week: w.week };
      var vs = me.total - w.average;
      diff += vs;
      var pick = s.picks[String(w.week)] || "";
      var result = !pick ? null : (s.out === w.week ? el("span", { class: "sui-no", text: " ✗ out" }) : el("span", { class: "sui-ok", text: " ✓" }));
      rows.push(el("tr", {}, [
        el("td", { class: "n num", text: String(w.week) }),
        el("td", { class: "n total num" }, [String(me.total), isWin ? el("span", { class: "star", text: " ★", title: "Won the week" }) : null]),
        el("td", { class: "n num " + (vs > 0.05 ? "up" : vs < -0.05 ? "down" : "flat"), text: (vs > 0 ? "+" : vs < 0 ? "−" : "") + Math.abs(vs).toFixed(1) }),
        el("td", { class: "n num hide-narrow", text: String(me.regular) }),
        el("td", { class: "n num hide-narrow", text: me.big_loser ? String(me.big_loser) : "–" }),
        el("td", { class: "n num", text: (tiedRank ? "T" : "") + ordinal(rank) }),
        el("td", { class: "n num hide-narrow", text: w.week === DATA.through_week && p.place != null ? String(p.place) : placesAfter(w.week)[p.name] }),
        el("td", {}, pick ? [pick, result] : ["–"])
      ]));
    });
    var status = s.alive ? "still in the suicide pool" : (s.out ? "out of the suicide pool in week " + s.out : "not in the suicide pool");
    var line = [p.place != null ? ordinal(p.place) + " of " + DATA.entrants : "", plural(p.wins, "win"),
      p.big_loser ? plural(p.big_loser, "Big Loser point") : "", status].filter(Boolean).join(" · ");
    var back = !mine && state.view !== "me" ? el("button", { class: "btn back", type: "button",
      text: "‹ Back to " + (VIEWS[state.view] ? VIEWS[state.view].label.toLowerCase() : "home"), onclick: function () { closeCoach(); } }) : null;
    var avg = played ? diff / played : 0;
    var week = weekCardFor(p.name);
    var head = el("section", { class: "mehead" }, [
      back,
      el("div", { class: "idrow" }, [el("span", { class: "initials xl", style: avatarStyle(p.name), text: initials(p.name) }),
        el("div", {}, [nickname(p.name) ? el("span", { class: "nickname", title: nickname(p.name).why, text: "“" + nickname(p.name).name + "”" }) : null,
          el("h1", {}, [p.name, formBadge(p.name)]), el("p", { class: "coach-line note", text: line }),
          form(p.name) ? el("p", { class: "note form-line", text: formText(form(p.name)) }) : null])]),
      el("div", { class: "figures" }, [
        figure(p.place != null ? ordinal(p.place) : "–", "in the standings",
          (p.move ? (p.move > 0 ? "▲ up " : "▼ down ") + plural(Math.abs(p.move), "place") : "no move") + " last week"),
        figure(String(p.wins), "wins", (lead - p.wins ? (lead - p.wins) + " behind the lead" : "leading") + " · " +
          (avg > 0 ? "+" : avg < 0 ? "−" : "") + Math.abs(avg).toFixed(1) + " a week on the average"),
        figure(titleText(p) || "–", "title chance", p.out_of_reach ? "out of reach" : ""),
        figure(money(DATA.money ? (p.won || 0) : moneyWon), "money won", plural(won, "week") + " won" +
          (DATA.money && p.net != null ? " · " + money(p.net) + " net" : ""))
      ]),
      el("div", { style: "display:flex;flex-wrap:wrap;gap:8px" }, [
        el("button", { class: "btn" + (mine ? " primary" : ""), type: "button", onclick: function () { shareWeek(p.name); } }, [icon("share"), mine ? "Share my week" : "Share " + p.name + "’s week"]),
        available("h2h") ? el("button", { class: "btn", type: "button", text: "Head-to-head with…",
          onclick: function () { state.a = p.name; if (state.b === p.name) state.b = ""; go("h2h"); } }) : null,
        mine ? el("button", { class: "btn", type: "button", text: "Not " + p.name + "?", onclick: function () { state.me = ""; remember(""); render({ top: true }); } })
          : (!hasMe() ? el("button", { class: "btn", type: "button", text: "This is me", onclick: function () { state.me = p.name; remember(p.name); state.coach = ""; go("me"); } }) : null)
      ])
    ]);
    var chance = mine ? chanceModule() : null;
    return el("div", { class: "view", "data-view": mine ? "me" : "coach" }, [
      head,
      week,
      week ? rootingFor(p.name) : null,
      chance,
      el("div", { class: "cols" }, [
        el("div", {}, [trendModule(p), maxModule(p), profileModule(p), blindSpotsModule(p)]),
        el("div", {}, [trophyShelf(p), twinsModule(p), rivalsModule(p), poolsModuleFor(p), moneyModuleFor(p, moneyWon)])
      ]),
      played ? module("Every week", plural(played, "week"), [scroller(el("table", { id: "coach-weeks" }, [el("thead", {}, [el("tr", {}, [
        el("th", { class: "n", text: "Wk" }), el("th", { class: "n", text: "Wins" }),
        el("th", { class: "n", text: "vs avg" }), el("th", { class: "n hide-narrow", text: "Picks right" }),
        el("th", { class: "n hide-narrow", text: "Big Loser" }), el("th", { class: "n", text: "Week" }),
        el("th", { class: "n hide-narrow", text: "Season" }), el("th", { text: "Suicide pick" })])]), el("tbody", {}, rows)])),
        el("p", { class: "note", text: "Week is where that week’s score ranked. Season is the place in the standings after it. Wins include Big Loser points." })])
        : stateMsg("No completed games yet", "Weekly scores show here once the first week is entered.")
    ]);
  }
  function placesAfter(n, raw) {
    // competition ranking on season totals through week n (ties share a place)
    var totals = DATA.players.map(function (p) {
      var t = 0;
      Object.keys(p.weekly).forEach(function (k) { if (Number(k) <= n) t += p.weekly[k]; });
      return { name: p.name, total: t };
    });
    var out = {};
    totals.forEach(function (a) {
      var ahead = totals.filter(function (b) { return b.total > a.total; }).length;
      var tied = totals.filter(function (b) { return b.total === a.total; }).length > 1;
      out[a.name] = raw ? ahead + 1 : (tied ? "T" : "") + (ahead + 1);
    });
    return out;
  }

  // The viewer's chance of winning this week, as it has moved on this phone.
  function chanceModule() {
    if (!hasLive() || !live.fetched) return null;
    var t = liveTally();
    if (!t.games.some(function (x) { return x.state !== "pre"; })) return null;
    var points = myChances();
    var now = simulate(t).chance[state.me];
    if (now == null) return null;
    var first = points.length ? points[0] : null;
    return module("Your chance this week", pct(now) + " now", [
      points.length > 1 ? chartBox("my-chance", 150, function (w) { return sparkChart(points, w); }) : null,
      el("p", { class: "note", text: first && points.length > 1 ? "From " + pct(first[1]) + " at " + clock(new Date(first[0])) + " to " + pct(now) + " now - each time this phone checked the scores." :
        "The line fills in as the scores come in while you have the page open." })
    ], { "data-card": "chance" });
  }

  // Each week's score against the most that week allowed, so a 9 in a short
  // bye week and a 9 in a full slate read differently. Only weeks whose
  // maximum the official sheet supports.
  function maxModule(p) {
    var rows = DATA.weeks.filter(function (w) { return weekMost(w) && p.weekly[String(w.week)] != null; })
      .sort(function (a, b) { return b.week - a.week; })
      .map(function (w) { var v = p.weekly[String(w.week)]; return { w: w, v: v, share: v / weekMost(w) }; });
    if (!rows.length) return null;
    var best = Math.max.apply(null, rows.map(function (r) { return r.share; }));
    var worst = Math.min.apply(null, rows.map(function (r) { return r.share; }));
    return module("Points against the max", "games plus Big Loser picks", [
      el("div", { class: "rows maxweeks" }, rows.map(function (r) {
        return el("div", { class: "r" + (rows.length > 1 && r.share === best ? " best" : "") }, [
          el("span", { class: "meta", text: "Wk " + r.w.week }),
          el("span", { class: "num" }, [el("b", { text: String(r.v) }), " of " + weekMost(r.w)]),
          bar(r.share, 1),
          el("span", { class: "num", style: "text-align:right", text: Math.round(r.share * 100) + "%" })]);
      })),
      rows.length > 1 && best !== worst ? el("p", { class: "note", text: "Best week " + Math.round(best * 100) + "% of the max, worst " + Math.round(worst * 100) + "%." }) : null
    ], { "data-card": "max" });
  }
  // Where the coach has been, week by week: place and score against the pool.
  function trendModule(p) {
    var weeks = DATA.weeks.map(function (w) { return w.week; }).sort(function (a, b) { return a - b; });
    if (!weeks.length) return null;
    return module("Week by week", "score against the pool’s average", [
      chartBox("trend-" + p.name, 220, function (w) { return weekScoreChart(p, w); }),
      el("div", { class: "chart" }, [el("div", { class: "legend" }, [el("span", {}, [el("i", { class: "dot" }), p.name]),
        el("span", {}, [el("i", { class: "rng" }), "the pool, low to high"]), el("span", {}, [el("i", {}), "the pool’s average"])])])
    ], { "data-card": "trend" });
  }

