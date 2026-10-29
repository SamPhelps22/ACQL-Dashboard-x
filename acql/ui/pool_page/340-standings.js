  // ---- standings ---------------------------------------------------------------------
  function standingsView() {
    var lead = DATA.players.length ? DATA.players[0].wins : 0;
    var latest = weekData(DATA.through_week);
    var toggle = el("div", { class: "seg", role: "group", "aria-label": "Show" }, [["", "Leaderboard"], ["every", "Every week"]].map(function (o) {
      return el("button", { type: "button", "aria-pressed": (state.every ? "every" : "") === o[0] ? "true" : "false",
        onclick: function () { state.every = !!o[0]; render(); }, text: o[1] });
    }));
    return el("div", { class: "view", "data-view": "standings" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Standings" }), toggle]),
      el("p", { class: "lede", text: raceSummary() }),
      state.every ? null : podium(),
      state.every ? everyWeekTable() : leaderboard(lead, latest),
      raceCard(),
      el("p", { class: "note rule-links" }, [ruleLink("season-tie", "How ties in the table are broken"), " ",
        moreLink("Power Rankings (unofficial)", "power")])
    ]);
  }
  // The top three, on the podium: gold, silver and bronze.
  function podium() {
    var top = DATA.players.slice(0, 3);
    if (top.length < 3 || !DATA.through_week) return null;
    var lead = top[0].wins;
    function shared(p) { return DATA.players.filter(function (q) { return q.place === p.place; }).length > 1; }
    return el("div", { class: "podium", role: "group", "aria-label": "The top three" }, top.map(function (p, i) {
      var back = lead - p.wins;
      return el("div", { class: "step p" + (i + 1) + (isMe(p.name) ? " me" : "") }, [
        el("span", { class: "medal", text: p.place != null ? (shared(p) ? "T" : "") + ordinal(p.place) : ordinal(i + 1) }),
        el("span", { class: "initials", style: avatarStyle(p.name), "aria-hidden": "true", text: initials(p.name) }),
        el("span", { class: "podname" }, [who(p.name), formBadge(p.name)]),
        el("span", { class: "wins num", text: String(p.wins) }),
        el("span", { class: "sub", text: (back ? back + " back" : "leads") + (p.title != null ? " · " + titleText(p) + " title" : "") })
      ]);
    }));
  }
  function raceSummary() {
    var R = DATA.race;
    if (!R || !DATA.players.length) return "";
    var lead = DATA.players[0].wins, left = R.weeks_left;
    var close = DATA.players.filter(function (p) { return p.wins < lead && lead - p.wins <= 3; }).length;
    var gone = DATA.players.filter(function (p) { return p.out_of_reach; }).length;
    var names_ = leaders().map(function (p) { return p.name; });
    return left
      ? listNames(names_, 2) + (names_.length > 1 ? " share the lead" : " leads") + " with " + plural(lead, "win") + ", " + plural(left, "week") + " to go. " +
        (close ? plural(close, "coach is", "coaches are") + " within 3 wins. " : "") +
        (gone ? plural(gone, "coach", "coaches") + " can no longer catch the lead, even with perfect weeks." : "Nobody is out of it yet.")
      : "The season is over: " + listNames(names_, 2) + (names_.length > 1 ? " share the title." : " wins the title.");
  }
  function leaderboard(lead, latest) {
    var avg = poolAverage();
    var rows = [el("div", { class: "r hdr", "aria-hidden": "true" }, [
      el("span", { class: "pos", style: "font:600 12px var(--body)", text: "#" }), el("span", {}), el("span", { text: "Coach" }),
      el("span", { class: "big", text: "Wins" }), el("span", { class: "col", text: "Back" }), el("span", { class: "col", text: "Title" }),
      el("span", { class: "col", text: "Last week" }), el("span", { class: "col", text: "Side pools" })])];
    var drawn = false;
    DATA.players.forEach(function (p) {
      var line = !drawn && p.wins < avg;
      if (line) drawn = true;
      var last = latest ? latest.scores.filter(function (s) { return s.name === p.name; })[0] : null;
      var won = latest && latest.winners.indexOf(p.name) >= 0;
      var s = p.suicide;
      var sui = s.alive ? "Still in the suicide pool. " : s.out ? "Out of the suicide pool in week " + s.out + ". " : "Not in the suicide pool. ";
      var side = [el("span", { class: "dot " + (s.alive ? "alive" : "out"), title: sui.trim() }), el("span", { class: "vh", text: sui }),
        p.big_loser ? "BL " + p.big_loser : "BL –"];
      var meta = [el("span", { class: "dot " + (s.alive ? "alive" : "out") }), el("span", { class: "vh", text: sui }),
        [lead - p.wins ? (lead - p.wins) + " back" : "leads",
          p.title != null ? titleText(p) + " title" : "",
          last ? "last wk " + last.total + (won ? " ★" : "") : "",
          p.big_loser ? "BL " + p.big_loser : ""].filter(Boolean).join(" · ")];
      rows.push(el("div", { class: "r" + (isMe(p.name) ? " me" : "") + (line ? " avgtop" : ""), "data-name": p.name }, [
        el("span", { class: "pos", text: p.place != null ? String(p.place) : "", "data-tick": "s:place:" + p.name }),
        moveMark(p.move),
        el("span", { class: "name" }, [el("span", { class: "initials sm", style: avatarStyle(p.name), "aria-hidden": "true", text: initials(p.name) }),
          who(p.name), formBadge(p.name), isMe(p.name) ? el("span", { class: "youtag", text: "YOU" }) : null]),
        el("span", { class: "big", text: String(p.wins), "data-tick": "s:total:" + p.name }),
        el("span", { class: "col", text: lead - p.wins ? String(lead - p.wins) : "–" }),
        el("span", { class: "col" + (p.out_of_reach ? " gone" : ""), text: titleText(p) }),
        el("span", { class: "col", text: last ? String(last.total) + (won ? " ★" : "") : "" }),
        el("span", { class: "col" }, side),
        el("span", { class: "meta" }, meta)
      ]));
    });
    var avgNote = el("p", { class: "note", text: "The dashed line is the pool’s average, " + avg.toFixed(1) + " wins. Wins include Big Loser points (BL). Arrows show places gained or lost since last week. A green dot means still in the suicide pool. 🔥 on fire: above the pool’s average in each of the last three weeks, by " + FORM_EDGE + "+ wins in all. 🧊 on the hot seat: below it every week by as much." });
    return el("div", {}, [el("div", { class: "rows standrows", id: "leaderboard" }, rows), avgNote]);
  }
  function everyWeekTable() {
    var weeks = DATA.weeks.map(function (w) { return w.week; }).sort(function (a, b) { return b - a; });
    var avg = poolAverage();
    var head = [el("th", { class: "n stick-a", text: "#" }), el("th", { class: "stick-b", text: "Coach" }),
      el("th", { class: "n", text: "Wins" }), el("th", { class: "n", text: "Move" }),
      DATA.race ? el("th", { class: "n", text: "Title", title: "Chance of finishing the season on top" }) : null,
      el("th", { class: "n", text: "Big Loser" }), el("th", { text: "Suicide" })].filter(Boolean);
    weeks.forEach(function (n) {
      head.push(el("th", { class: "n" + (n === DATA.through_week ? " latest" : ""), text: "Wk " + n }));
    });
    var cols = head.length;
    var rows = [], drawn = false;
    DATA.players.forEach(function (p) {
      if (!drawn && p.wins < avg) {
        drawn = true;
        rows.push(el("tr", { class: "avg" }, [el("td", { colspan: String(cols), class: "note", text: "Pool average: " + avg.toFixed(1) + " wins" })]));
      }
      var s = p.suicide;
      var mv = p.move == null || p.move === 0 ? el("td", { class: "n flat", text: "–" })
        : p.move > 0 ? el("td", { class: "n up", text: "▲" + p.move }) : el("td", { class: "n down", text: "▼" + Math.abs(p.move) });
      var cells = [el("td", { class: "n place num stick-a", text: p.place != null ? String(p.place) : "", "data-tick": "s:place:" + p.name }),
        el("td", { class: "coach stick-b" }, [who(p.name)]),
        el("td", { class: "n total num", text: String(p.wins), "data-tick": "s:total:" + p.name }), mv,
        DATA.race ? el("td", { class: "n num" + (p.out_of_reach ? " gone" : ""), text: titleText(p) }) : null,
        el("td", { class: "n num", text: p.big_loser ? String(p.big_loser) : "–" }),
        el("td", {}, [el("span", { class: "dot " + (s.alive ? "alive" : "out") }), s.alive ? "Still in" : (s.out ? "Out wk " + s.out : "–")])].filter(Boolean);
      weeks.forEach(function (n) {
        var v = p.weekly[String(n)];
        cells.push(el("td", { class: "n num" + (n === DATA.through_week ? " latest" : ""), text: v == null ? "" : String(v) }));
      });
      rows.push(el("tr", { class: isMe(p.name) ? "me" : null }, cells));
    });
    return el("div", { style: "display:grid;gap:8px" }, [
      scroller(el("table", { id: "every-week" }, [el("thead", {}, [el("tr", {}, head)]), el("tbody", {}, rows)])),
      el("p", { class: "note" }, ["Every week’s score, newest first. ", el("span", { class: "narrow-only", text: "Swipe the table for each week." })])
    ]);
  }
  // Catch the leader: who's in range, and each coach's title chance.
  function raceCard() {
    var R = DATA.race;
    if (!R || !DATA.players.length) return null;
    var lead = DATA.players[0].wins;
    var left = R.weeks_left;
    var byChance = DATA.players.slice().sort(function (a, b) {
      return (b.title || 0) - (a.title || 0) || b.wins - a.wins || a.name.localeCompare(b.name);
    });
    var shown = byChance.slice(0, 8);
    var mine = DATA.players.filter(function (p) { return isMe(p.name); })[0];
    if (mine && shown.indexOf(mine) < 0) shown.push(mine);
    var top = Math.max.apply(null, shown.map(function (p) { return p.title || 0; }).concat([1]));
    function perWeek(p) {
      var back = lead - p.wins;
      if (!back) return "leads";
      if (!left || p.out_of_reach) return "–";
      return "+" + (back / left).toFixed(1);
    }
    return module("The title race", plural(left, "week") + " left", [
      el("div", { class: "box" }, [el("table", {}, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "Coach" }), el("th", { class: "n", text: "Per week" }),
          el("th", { class: "n", text: "Title" }), el("th", { class: "bar-cell hide-narrow", text: "" })])]),
        el("tbody", {}, shown.map(function (p) {
          return el("tr", { class: isMe(p.name) ? "me" : null }, [
            el("td", { class: "coach" }, [who(p.name)]),
            el("td", { class: "n num", text: perWeek(p) }),
            el("td", { class: "n pct num" + (p.out_of_reach ? " gone" : ""), text: titleText(p) }),
            el("td", { class: "bar-cell hide-narrow" }, [bar(p.title || 0, top)])
          ]);
        }))
      ])]),
      el("p", { class: "note", text: "The likeliest champions. Per week is how much a coach has to beat the leader by, every week from here, to catch up. Title is the chance of winning the season, from playing out the rest of it 10,000 times on the standings alone." }),
      moreLink("Title odds week by week", "charts")
    ], { "data-card": "race" });
  }

