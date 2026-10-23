  // ---- everyone's picks: the week's cards, side by side ----------------------------
  // A row a coach, a column a game, straight from the week's pick sheet. The
  // side most of the pool took sits on top, then the viewer's own card, then
  // the rest - most right first once games are under way. Under it: how each
  // game split, and every coach's Big Losers and suicide pick.
  function picksView() {
    var L = DATA.live;
    if (!live.fetched && !live.error && !live.busy) fetchScores();
    var t = liveTally(), n = L.coaches.length;
    var started = t.games.some(function (x) { return x.state !== "pre"; });
    var right = {}, season = {};
    t.rows.forEach(function (r) { right[r.c.name] = r.games; });
    DATA.players.forEach(function (p) { season[p.name] = p; });
    var me = L.coaches.filter(function (c) { return isMe(c.name); })[0];
    var rest = L.coaches.filter(function (c) { return !isMe(c.name); });
    // each game: the cards on each side, and the side most of them are on
    var cols = t.games.map(function (x, gi) {
      var a = 0, h = 0;
      L.coaches.forEach(function (c) { var pk = c.picks[gi]; if (pk === x.g.ac) a++; else if (pk === x.g.hc) h++; });
      return { x: x, a: a, h: h, cards: a + h, most: Math.max(a, h), top: a === h ? "" : a > h ? x.g.ac : x.g.hc,
        share: a + h ? Math.max(a, h) / (a + h) : 0 };
    });
    var picked = cols.filter(function (c) { return c.cards; });
    var agreed = picked.slice().sort(function (p, q) { return q.share - p.share || q.cards - p.cards; })[0];
    var split = picked.slice().sort(function (p, q) { return p.share - q.share || q.cards - p.cards; })[0];
    var crowdRight = 0, crowdDone = 0, withCrowd = 0, ofCrowd = 0;
    cols.forEach(function (c, gi) {
      if (!c.top) return;
      if (c.x.state !== "pre") { crowdDone++; if (c.x.credit === c.top) crowdRight++; }
      if (me && me.picks[gi]) { ofCrowd++; if (me.picks[gi] === c.top) withCrowd++; }
    });
    function mini(v, k) {
      return el("div", { class: "mini-fig" }, [el("span", { class: "v", text: v }), el("span", { class: "k", text: k })]);
    }
    var tiles = el("div", { class: "minis" }, [
      mini(String(n), n >= DATA.entrants ? "cards in, the whole pool" : "cards in, of " + DATA.entrants + " coaches"),
      agreed ? mini(agreed.top ? agreed.top.toUpperCase() : "–", "most agreed on: " + agreed.most + " of " + agreed.cards + " cards") : null,
      split ? mini(split.a + "–" + split.h, "most split: " + split.x.g.ac.toUpperCase() + " at " + split.x.g.hc.toUpperCase()) : null,
      me && ofCrowd ? mini(withCrowd + " of " + ofCrowd, "games where you’re with the crowd")
        : crowdDone ? mini(crowdRight + " of " + crowdDone, "right for the crowd’s card so far")
        : mini(String(picked.filter(function (c) { return c.share >= 0.8; }).length), "games where 4 in 5 cards agree")
    ]);

    // the board
    var az = !started || state.picksOrder === "az";
    var order = (me ? [me] : []).concat(rest.slice().sort(function (p, q) {
      return (az ? 0 : (right[q.name] || 0) - (right[p.name] || 0)) || p.name.localeCompare(q.name);
    }));
    function cell(pick, c, under) {
      var x = c.x, cls = "pk";
      if (pick && x.state !== "pre") cls += (x.credit === pick ? " ok" : x.credit ? " no" : "") + (x.state === "in" ? " live" : "");
      if (pick && c.top && pick !== c.top) cls += " apart";
      return el("td", { class: cls }, [pick ? pick.toUpperCase() : "·", under != null ? el("small", { text: under }) : null]);
    }
    function nameCell(c, quiet) {
      return [who(c.name), isMe(c.name) ? el("span", { class: "youtag" + (quiet ? " hide-narrow" : ""), text: "YOU" }) : null];
    }
    var head = [el("th", { class: "stick-b", text: "Coach" })];
    if (started) head.push(el("th", { class: "n", text: "Right", title: "Picks right as the scores stand" }));
    cols.forEach(function (c) {
      var x = c.x, g = x.g, lined = g.line != null && g.fav;
      function side(team) {
        var won = x.state !== "pre" && x.credit === team;
        return el("span", { class: won ? "won" + (x.state === "in" ? " live" : "") : null, text: team.toUpperCase() });
      }
      head.push(el("th", { class: "gk", title: g.a + " at " + g.h + (lined ? ", pool line " + teamName(x, g.fav) + " by " + g.line : "") },
        [side(g.ac), side(g.hc)]));
    });
    var crowd = el("tr", { class: "crowd" }, [el("td", { class: "coach stick-b", text: "Most cards" })].concat(
      started ? [el("td", { class: "n num", text: String(crowdRight) })] : [],
      cols.map(function (c) { return cell(c.top, c, !c.cards ? "" : c.top ? String(c.most) : "even"); })));
    var body = [crowd].concat(order.map(function (c) {
      var cells = [el("td", { class: "coach stick-b" }, nameCell(c))];
      if (started) cells.push(el("td", { class: "n num", text: String(right[c.name] || 0) }));
      cols.forEach(function (col, gi) { cells.push(cell(c.picks[gi] || "", col)); });
      return el("tr", { class: isMe(c.name) ? "me" : null }, cells);
    }));
    var sorter = started ? el("div", { class: "seg", role: "group", "aria-label": "Order" }, [["", "Most right"], ["az", "A to Z"]].map(function (o) {
      return el("button", { type: "button", "aria-pressed": (state.picksOrder || "") === o[0] ? "true" : "false",
        onclick: function () { state.picksOrder = o[0]; render(); }, text: o[1] });
    })) : "tap a name for their week";
    var board = module("Every pick", sorter, [
      scroller(el("table", { id: "picks-table" }, [el("thead", {}, [el("tr", {}, head)]), el("tbody", {}, body)])),
      el("p", { class: "note", text: (started ? "Green is right and crossed out is wrong, as the scores stand. " : "Picks turn green or get crossed out once the games start. ") +
        "A gold line under a pick means it goes against most of the pool. Most cards is the side most of the pool took, with the number of cards on it." })
    ], { "data-card": "every-pick" });

    // the side pools: three Big Losers a card, and a suicide pick while still in
    function sidePick(team, good, bad, word) {
      return el("span", { class: "sp" + (good ? " sui-ok" : bad ? " sui-no" : ""), title: teamName(tallyGame(t, team), team) }, [badge(team), word || null]);
    }
    var sideRows = (me ? [me] : []).concat(rest).map(function (c) {
      var p = season[c.name], sui;
      var losers = c.bl.map(function (team) {
        var x = tallyGame(t, team), s = loserState(x, team);
        var hit = s.by != null && s.by >= 15, miss = !hit && s.by != null && x.state === "post";
        return sidePick(team, hit, miss, hit ? "✓" : miss ? "✗" : "");
      });
      if (!p || !p.suicide.alive) sui = p && p.suicide.out
        ? el("span", { class: "flat", title: "Out of the suicide pool in week " + p.suicide.out }, ["out", el("span", { class: "hide-narrow", text: " in week " + p.suicide.out })])
        : el("span", { class: "flat", text: "–" });
      else if (!c.sui) sui = el("span", { class: "flat", text: "no pick" });
      else {
        var now = survivalState(tallyGame(t, c.sui), c.sui).now;
        sui = sidePick(c.sui, now === "through" || now === "ahead", now === "out" || now === "behind",
          now === "through" ? "✓" : now === "out" ? "✗ out" : now);
      }
      return el("tr", { class: isMe(c.name) ? "me" : null }, [
        el("td", { class: "coach" }, nameCell(c, true)),
        el("td", { class: "sidepicks" }, losers.length ? losers : [el("span", { class: "flat", text: "–" })]),
        el("td", { class: "sidepicks" }, [sui])
      ]);
    });
    var sideCard = L.coaches.some(function (c) { return c.bl.length || c.sui; }) ? module("Side pool picks", plural(n, "card"), [
      scroller(el("table", { id: "picks-side" }, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "Coach" }), el("th", { text: "Big Losers" }),
          el("th", {}, ["Suicide", el("span", { class: "hide-narrow", text: " pick" })])])]),
        el("tbody", {}, sideRows)])),
      el("p", { class: "note", text: "A Big Loser scores a point when the team loses by 15 or more. Only coaches still in the suicide pool have a suicide pick." })
    ], { "data-card": "side-picks" }) : null;

    return el("div", { class: "view", "data-view": "picks" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Week " + L.week + ", everyone’s picks" }), liveStatus(t)]),
      tiles,
      board,
      splitsCard(t),
      sideCard
    ]);
  }

