  // ---- this week's side pools, and the picks nobody else made -------------------
  // One row per team: who has it, how it stands, and the coaches' names
  // (folded away when there are many). Past `limit` rows the rest fold away
  // too, except the viewer's own. `prefix` keeps each fold's open or shut
  // state apart from the other lists' across the redraws.
  function pickRows(rows, prefix, limit) {
    function mineIn(r) { return r.who.some(function (n) { return isMe(n); }); }
    var shown = rows, rest = [];
    if (limit && rows.length > limit + 2) {      // never fold away just one or two
      shown = rows.filter(function (r, i) { return i < limit || mineIn(r); });
      rest = rows.filter(function (r) { return shown.indexOf(r) < 0; });
    }
    var list = el("div", { class: "picks-list" }, shown.map(pickRow));
    if (!rest.length) return list;
    return el("div", { class: "picks-list" }, [list, fold(prefix + ":more", "Show " + plural(rest.length, "more team"),
      [el("div", { class: "picks-list" }, rest.map(pickRow))], "picks-more")]);
    function pickRow(r) {
      var sorted = r.who.slice().sort(function (a, b) { return a.localeCompare(b); });
      var mine = mineIn(r);
      var names = [];
      sorted.forEach(function (n, i) {
        if (i) names.push(", ");
        names.push(isMe(n) ? el("mark", {}, [who(n)]) : who(n));
      });
      var count = plural(sorted.length, "coach", "coaches") + (r.share != null ? " · " + Math.round(r.share * 100) + "%" : "");
      return el("div", { class: "pick-row" + (mine ? " mine" : "") }, [
        el("div", { class: "top" }, [el("span", { class: "team" }, [r.badge ? badge(r.badge) : null, el("b", { text: r.name })]),
          el("span", { class: "count num", text: count })]),
        el("span", { class: "state " + (r.tone || ""), text: r.status }),
        sorted.length > 6
          ? fold(prefix + ":" + r.team, mine ? "Who: " + state.me + " and " + plural(sorted.length - 1, "other") : "Who",
              [el("div", { class: "names" }, names)])
          : el("div", { class: "names" }, names)
      ]);
    }
  }
  // How one Big Loser pick stands. `by` is how many points the team is
  // losing by (null before kickoff); a point needs 15 or more at the end.
  function loserState(x, team) {
    if (!x) return { text: "not on this week’s sheet", tone: "muted", by: null, chance: null };
    var chance = blownChance(x, team);
    var by = x.state !== "pre" && x.hs != null ? (x.g.hc === team ? x.as - x.hs : x.hs - x.as) : null;
    if (by == null) return { text: pct(chance) + " to lose by 15+", tone: "muted", by: null, chance: chance };
    if (x.state === "post") {
      return { text: by >= 15 ? "lost by " + by + " · a point" : by > 0 ? "lost by " + by + " · no point" : by < 0 ? "won · no point" : "tied · no point",
        tone: by >= 15 ? "good" : "bad", by: by, chance: chance };
    }
    return { text: upDown(-by) + " · " + liveDetail(x) + " · " + pct(chance) + " to lose by 15+",
      tone: by >= 15 ? "good live" : "live", by: by, chance: chance };
  }
  // How one suicide pick stands, with the pool's line applied.
  function survivalState(x, team) {
    if (!x) return { text: "not on this week’s sheet", tone: "muted", now: "", chance: null };
    var chance = creditChance(x, team);
    var lined = x.g.line != null && x.g.fav;
    if (x.state === "pre") {
      return { text: pct(chance) + " to survive" + (lined ? " · pool line " + teamName(x, x.g.fav) + " by " + x.g.line : ""),
        tone: "muted", now: "", chance: chance };
    }
    if (x.state === "post") {
      var ok = x.credit === team;
      return { text: ok ? "through ✓" : "out ✗", tone: ok ? "good" : "bad", now: ok ? "through" : "out", chance: chance };
    }
    // credited now, not credited, or level in a game with no line
    var now = x.credit === team ? "ahead" : x.credit ? "behind" : "level";
    var margin = team === x.g.hc ? x.hs - x.as : x.as - x.hs;
    return { text: (now === "level" ? "" : now + " · ") + upDown(margin) + (lined ? " (line " + x.g.line + ")" : "") +
      " · " + liveDetail(x) + " · " + pct(chance) + " to survive", tone: now === "ahead" ? "good live" : now === "behind" ? "bad live" : "live", now: now, chance: chance };
  }

  // Every Big Loser the pool picked this week, how it stands, and who has it.
  function weekLosersCard(t) {
    var L = DATA.live, held = {}, cards = 0;
    L.coaches.forEach(function (c) {
      if (c.bl.length) cards++;
      c.bl.forEach(function (team) { (held[team] = held[team] || []).push(c.name); });
    });
    var teams = Object.keys(held);
    if (!teams.length) return null;
    var banked = 0, holding = 0, expected = 0;
    var rows = teams.map(function (team) {
      var x = tallyGame(t, team), who = held[team], s = loserState(x, team);
      if (s.by != null && s.by >= 15) { if (x.state === "post") banked += who.length; else holding += who.length; }
      expected += (s.chance || 0) * who.length;
      return { team: team, badge: team, name: teamName(x, team), who: who, share: cards ? who.length / cards : null,
        chance: s.chance || 0, status: s.text, tone: s.tone, point: s.by != null && s.by >= 15 };
    });
    // the ones landing a point first, then the most picked
    rows.sort(function (a, b) {
      return (b.point ? 1 : 0) - (a.point ? 1 : 0) || b.who.length - a.who.length || b.chance - a.chance || a.name.localeCompare(b.name);
    });
    var sum = [banked ? plural(banked, "point") + " banked" : "No points banked yet"];
    if (holding) sum.push(holding + " more on course if the scores hold");
    sum.push("about " + (cards ? expected / cards : 0).toFixed(1) + " a card expected, from where the games stand");
    var mine = L.coaches.filter(function (c) { return isMe(c.name); })[0];
    var mineText = mine && mine.bl.length ? mine.bl.map(function (team) {
      var x = tallyGame(t, team), s = loserState(x, team);
      return teamName(x, team) + (s.by != null && s.by >= 15 ? " ✓" : s.by != null && x.state === "post" ? " ✗" : "");
    }).join(", ") : "";
    return module("Week " + L.week + " Big Losers", plural(cards, "card") + ", " + plural(teams.length, "team"), [
      el("p", { class: "race-sum", text: sum.join(" · ") + "." }),
      mineText ? el("p", { class: "note" }, [el("b", { text: "Yours: " }), mineText]) : null,
      pickRows(rows, "bl", 8),
      el("p", { class: "note", text: "A team scores a point when it loses by 15 or more. The % is the share of cards with that team. Chances come from the live score and the betting line." })
    ], { "data-card": "losers" });
  }

  // The suicide pool this week: who is on which team, and how it stands.
  function weekSuicideCard(t) {
    var L = DATA.live, season = {}, on = {}, none = [], alive = 0;
    DATA.players.forEach(function (p) { season[p.name] = p; });
    L.coaches.forEach(function (c) {
      var p = season[c.name];
      if (!p || !p.suicide.alive) return;
      alive++;
      if (!c.sui) { none.push(c.name); return; }
      (on[c.sui] = on[c.sui] || []).push(c.name);
    });
    if (!alive) return null;
    var expected = 0, out = 0, behind = 0;
    var rows = Object.keys(on).map(function (team) {
      var x = tallyGame(t, team), who = on[team], s = survivalState(x, team);
      expected += (s.chance == null ? 1 : s.chance) * who.length;
      if (s.now === "out") out += who.length;
      if (s.now === "behind") behind += who.length;
      return { team: team, badge: team, name: teamName(x, team), who: who, share: null, chance: s.chance == null ? 1 : s.chance, status: s.text, tone: s.tone };
    });
    rows.sort(function (a, b) { return b.who.length - a.who.length || a.chance - b.chance || a.name.localeCompare(b.name); });
    var bits = [plural(alive, "coach", "coaches") + " still in", "about " + expected.toFixed(1) + " expected through this week"];
    if (behind) bits.push(behind + " behind right now");
    if (out) bits.push(out + " out");
    return module("Week " + L.week + " suicide pool", plural(Object.keys(on).length, "team") + " picked", [
      el("p", { class: "race-sum", text: bits.join(" · ") + "." }),
      rows.length ? pickRows(rows, "sui", 10) : null,
      none.length ? el("p", { class: "note", text: sentence("No suicide pick on the sheet: " + listNames(none.slice().sort(), 6)) }) : null,
      el("p", { class: "note", text: "Your team has to win its game. If the game has a pool line, the favourite must win by at least the line, and the underdog survives by keeping it closer." })
    ], { "data-card": "suicide" });
  }

  // Picks almost nobody made, and how the crowd's own card is doing.
  function limbCard(t) {
    var L = DATA.live, n = L.coaches.length, few = Math.max(2, Math.round(n * 0.1));
    var rows = [], crowdRight = 0, crowdDone = 0;
    t.games.forEach(function (x, gi) {
      var on = {};
      L.coaches.forEach(function (c) { var pk = c.picks[gi]; if (pk) (on[pk] = on[pk] || []).push(c.name); });
      var h = (on[x.g.hc] || []).length, a = (on[x.g.ac] || []).length;
      if (x.state !== "pre" && (h || a)) { crowdDone++; if (x.credit === (h >= a ? x.g.hc : x.g.ac)) crowdRight++; }
      [x.g.hc, x.g.ac].forEach(function (team) {
        var who = on[team] || [];
        if (!who.length || who.length > few) return;
        var other = team === x.g.hc ? x.g.ac : x.g.hc;
        var status, tone;
        if (x.state === "pre") { status = pct(creditChance(x, team)) + " to come in"; tone = "muted"; }
        else if (x.state === "post") { status = x.credit === team ? "came in ✓" : "missed"; tone = x.credit === team ? "good" : "bad"; }
        else {
          status = (x.credit === team ? "coming in · " : x.credit ? "not right now · " : "") + upDown(team === x.g.hc ? x.hs - x.as : x.as - x.hs) +
            " · " + liveDetail(x) + " · " + pct(creditChance(x, team)) + " to come in";
          tone = x.credit === team ? "good live" : "live";
        }
        rows.push({ team: team, badge: team, name: teamName(x, team) + " over " + teamName(x, other), who: who, share: null, status: status, tone: tone });
      });
    });
    return module("Out on a limb", "on " + few + " or fewer cards", [
      el("p", { class: "race-sum", text: crowdDone
        ? "The crowd’s card (the side most of the pool took in each game) has " + crowdRight + " of " + crowdDone + " right as things stand."
        : "The crowd’s card (the side most of the pool took in each game) is scored here once the games start." }),
      rows.length ? pickRows(rows, "limb", 10) : el("p", { class: "note", text: "Nobody went out on a limb this week." })
    ], { "data-card": "limb" });
  }

  // How the pool picked every game: the split between the two sides.
  function splitsCard(t, link) {
    var L = DATA.live, mine = L.coaches.filter(function (c) { return isMe(c.name); })[0];
    var rows = t.games.map(function (x, gi) {
      var g = x.g, h = 0, a = 0;
      L.coaches.forEach(function (c) { var pk = c.picks[gi]; if (pk === g.hc) h++; else if (pk === g.ac) a++; });
      var total = h + a || 1, my = mine ? mine.picks[gi] : "";
      var lined = g.line != null && g.fav;
      function side(team, name, n, home) {
        var bits = [badge(team), el("b", { text: name }), el("span", { class: "n", text: String(n) }),
          my === team ? el("span", { class: "mine-pick", text: "YOU" }) : null];
        return el("div", { class: "side" + (home ? " home" : "") }, home ? bits.reverse() : bits);
      }
      return el("div", { class: "split" }, [
        side(g.ac, g.a, a, false), el("span", { class: "at", text: "at" }), side(g.hc, g.h, h, true),
        el("div", { class: "barline", "aria-hidden": "true" }, [
          el("span", { class: a > h ? "lead" : null, style: "width:" + Math.round(100 * a / total) + "%" }),
          el("span", { class: h > a ? "lead" : null, style: "width:" + Math.round(100 * h / total) + "%" })
        ]),
        lined || x.state !== "pre" || my ? el("span", { class: "lineinfo" + (lined || x.state !== "pre" ? "" : " narrow-only") +
          (scoreMoved[gameKey(g.hc, g.ac)] > Date.now() ? " score-new" : "") }, [[lined ? "Pool line: " + teamName(x, g.fav) + " by " + g.line : "",
          x.state === "post" ? "Final " + x.as + "–" + x.hs : x.state === "in" ? liveDetail(x) + " " + x.as + "–" + x.hs : ""].filter(Boolean).join("   "),
          my ? el("span", { class: "narrow-only you", text: (lined || x.state !== "pre" ? " · " : "") + "you: " + my.toUpperCase() }) : null]) : null
      ]);
    });
    return module("How the pool picked", plural(L.coaches.length, "card"), [el("div", { class: "splits" }, rows),
      link ? moreLink("Everyone’s picks", "picks") : null], { "data-card": "splits" });
  }

  // One coach's whole card for the week being played: every pick, the Big
  // Losers and the suicide pick, each with how it stands.
  function weekCardFor(name) {
    var L = DATA.live;
    if (!L || !L.coaches || !L.games || !L.games.length) return null;
    var c = L.coaches.filter(function (x) { return x.name === name; })[0];
    if (!c) return null;
    if (!live.fetched && !live.error && !live.busy) fetchScores();
    var t = liveTally(), right = 0, wrong = 0, open = 0;
    var row = t.rows.filter(function (r) { return r.c.name === name; })[0];
    var chance = simulate(t).chance[name] || 0;
    function line(kind, game, pick, s) {
      return el("tr", {}, [
        el("td", { class: "game" }, [].concat(game, kind ? el("span", { class: "sub" }, [].concat(kind)) : null)),
        el("td", { class: "coach", text: pick }),
        el("td", { class: "state " + (s.tone || ""), text: s.text })
      ]);
    }
    var rows = t.games.map(function (x, gi) {
      var pick = c.picks[gi], s;
      if (!pick) s = { text: "no pick", tone: "muted" };
      else if (x.state === "pre") { s = { text: pct(creditChance(x, pick)) + " to come in", tone: "muted" }; open++; }
      else if (x.state === "post") { var ok = x.credit === pick; s = { text: ok ? "✓ right" : "✗ wrong", tone: ok ? "good" : "bad" }; if (ok) right++; else wrong++; }
      else {
        var now = x.credit === pick ? "right" : x.credit ? "wrong" : "";
        s = { text: (now ? now + " now · " : "") + upDown(x.g.hc === pick ? x.hs - x.as : x.as - x.hs) + " · " + liveDetail(x),
          tone: now === "right" ? "good live" : now === "wrong" ? "bad live" : "live" };
        open++;
      }
      var lined = x.g.line != null && x.g.fav;
      return line(lined ? [el("span", { class: "hide-narrow", text: "pool line: " + teamName(x, x.g.fav) + " by " + x.g.line }),
          el("span", { class: "narrow-only", text: x.g.fav.toUpperCase() + " by " + x.g.line })] : "",
        [el("span", { class: "hide-narrow", text: x.g.a + " @ " + x.g.h }),
          el("span", { class: "narrow-only", text: x.g.ac.toUpperCase() + " @ " + x.g.hc.toUpperCase() })],
        pick ? teamName(x, pick) : "–", s);
    });
    c.bl.forEach(function (team) {
      var x = tallyGame(t, team);
      rows.push(line("", "Big Loser", teamName(x, team), loserState(x, team)));
    });
    var p = player(name);
    if (p && p.suicide.alive && c.sui) {
      var sx = tallyGame(t, c.sui);
      rows.push(line("", "Suicide pick", teamName(sx, c.sui), survivalState(sx, c.sui)));
    }
    var started = t.games.some(function (x) { return x.state !== "pre"; });
    var m = started ? moneyNow(t)[name] : null;
    function mini(v, k, tone) {
      return el("div", { class: "mini-fig" + (tone ? " " + tone : "") }, [el("span", { class: "v", text: v }), el("span", { class: "k", text: k })]);
    }
    return module("Week " + L.week + " card", live.error ? null : live.fetched ? "scores at " + clock(live.fetched) : "fetching scores…", [
      el("div", { class: "minis" }, [
        mini(String(row ? row.now : 0), row && row.bl ? "now, with " + plural(row.bl, "Big Loser point") : "now"),
        mini(pct(chance), "to win the week"),
        started ? mini(cash(m), weekOver(t) ? "for the week" : "if it ended now", "money " + cashTone(m)) : null,
        mini(right + "–" + wrong, open ? "right–wrong, " + open + " still to finish" : "right–wrong")
      ]),
      liveProblem(),
      el("div", { class: "box week-card" }, [el("table", {}, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "Game" }), el("th", { text: "Pick" }), el("th", { text: "How it stands" })])]),
        el("tbody", {}, rows)])])
    ], { "data-card": "week-card" });
  }

  // Who a coach should cheer for in the games still to finish, the pool's
  // lines and their own Big Losers in it. With `fixed` it is that coach's
  // own (on their page); without, a chooser picks whose.
  function rootingCard(t, sim, fixed) {
    var L = DATA.live;
    var whom = fixed || state.root || state.me;
    var all = L.coaches.map(function (c) { return c.name; });
    var picker = fixed ? null : el("select", { id: "root-for", "aria-label": "Rooting guide for", class: "filter", style: "max-width:14em",
      onchange: function (e) { state.root = e.target.value; render(); } },
      [el("option", { value: "", text: "Choose a coach…" })].concat(all.slice().sort(function (a, b) { return a.localeCompare(b); }).map(function (n) {
        return el("option", { value: n, text: n, selected: n === whom });
      })));
    if (all.indexOf(whom) < 0) return fixed ? null : module("Rooting guide", picker, [
      el("p", { class: "note", text: "Choose a coach to see who they should cheer for in the games still to finish." })], { "data-card": "rooting" });
    if (fixed && !sim.open.length) return null;
    var you = isMe(whom);
    var mine = sim.chance[whom] || 0;
    var roots = rootsFor(t, sim, whom);
    var matters = roots.filter(function (r) { return r.swing >= 0.01; });
    var shrug = roots.filter(function (r) { return r.kind === "pick" && r.swing < 0.01; });
    function where(x) {
      if (x.state === "in") return x.g.ac.toUpperCase() + " " + x.as + ", " + x.g.hc.toUpperCase() + " " + x.hs + " · " + liveDetail(x);
      return x.g.ac.toUpperCase() + " @ " + x.g.hc.toUpperCase() + (x.kick ? " · " + kickText(x.kick) : "");
    }
    var title = !fixed ? "Rooting guide" : you ? "What to root for" : "What " + whom + " needs";
    return module(title, fixed ? pct(mine) + " to win the week" : picker, [
      fixed ? null : el("p", { class: "race-sum" }, [el("b", { text: pct(mine) }), " to win the week."]),
      mine <= 0 && t.games.some(function (x) { return x.state !== "post"; })
        ? el("p", { class: "note", text: "No way to finish top this week any more - but the season total still counts." }) : null,
      matters.length ? el("div", { class: "roots" }, matters.slice(0, 8).map(function (r) {
        return el("div", { class: "r root" + (r.x.state === "in" ? " on" : "") }, [
          el("span", { class: "team" }, [badge(r.team, true), el("b", { text: rootPhrase(r) })]),
          el("span", { class: "swing", title: (you ? "Your" : whom + "’s") + " chance of winning the week: " + pct(r.ifNot) + " if not, " + pct(r.ifSo) + " if so",
            text: "+" + Math.round(r.swing * 100) + "%" }),
          el("span", { class: "meta" }, [r.x.state === "in" ? el("span", { class: "dot-live", title: "On now" }) : null,
            where(r.x) + (r.kind === "loser" ? " · " + (you ? "your" : "a") + " Big Loser" : "")]),
          el("span", { class: "jump" }, [el("span", { class: "mini", "aria-hidden": "true" }, [
              el("i", { class: "so", style: "width:" + Math.round(100 * r.ifSo) + "%" }),
              el("i", { class: "not", style: "width:" + Math.round(100 * r.ifNot) + "%" })]),
            el("span", { text: pct(r.ifSo) + " to win the week if so, " + pct(r.ifNot) + " if not · it happens " + pct(r.likely) + " of the time" })])
        ]);
      })) : el("p", { class: "note", text: "None of the games still to finish changes much for " + (you ? "you" : whom) + " now." }),
      shrug.length ? el("p", { class: "note", text: "Doesn’t matter: " + shrug.map(function (r) { return r.x.g.ac.toUpperCase() + "–" + r.x.g.hc.toUpperCase(); }).join(", ") }) : null
    ], { "data-card": fixed ? "rooting-own" : "rooting", "data-nav": fixed ? null : "Rooting guide" });
  }
  // The rooting guide on a coach's own page, while there's a game left to root for.
  function rootingFor(name) {
    var L = DATA.live;
    if (!hasLive() || !L.coaches.some(function (c) { return c.name === name; })) return null;
    var t = liveTally();
    if (weekOver(t)) return null;
    return rootingCard(t, simulate(t), name);
  }

  // The games still to finish that move the week most.
  function swingCard(t, sim) {
    var L = DATA.live, n = L.coaches.length;
    var rows = sim.open.map(function (gi, o) {
      var sp = sim.split[o];
      if (!sp.h[0] || !sp.a[0]) return null;
      var moved = 0, bestH = -1, bestA = -1, whoH = "", whoA = "";
      for (var c = 0; c < n; c++) {
        var h = sp.h[1][c] / sp.h[0], a = sp.a[1][c] / sp.a[0];
        moved += Math.abs(h - a) / 2;
        if (h - a > bestH) { bestH = h - a; whoH = L.coaches[c].name; }
        if (a - h > bestA) { bestA = a - h; whoA = L.coaches[c].name; }
      }
      return { g: t.games[gi].g, moved: moved, whoH: whoH, whoA: whoA };
    }).filter(Boolean).sort(function (a, b) { return b.moved - a.moved; }).slice(0, 3);
    if (!rows.length) return null;
    return module("The games that decide the week", null, rows.map(function (r) {
      return el("div", { class: "upset" }, [
        el("span", { class: "game" }, [el("span", { class: "team" }, [badge(r.g.ac), badge(r.g.hc), el("span", { text: r.g.a + " @ " + r.g.h })])]),
        el("span", { class: "had num", style: "color:var(--ink)", text: Math.round(r.moved * 100) + "% swings" }),
        el("span", { class: "how", text: (r.whoH ? r.g.h + " helps " + r.whoH : "") + (r.whoA ? " · " + r.g.a + " helps " + r.whoA : "") })
      ]);
    }), { "data-card": "swing", "data-nav": "Deciding games" });
  }

  // What changed while this page was open.
  function swingsFeed() {
    if (!swings.length) return null;
    return module("Just now", "while you’ve been watching", [el("div", { class: "feed" }, swings.slice(0, 8).map(function (f) {
      return el("div", { class: "f" + (f.tone === "mine" ? " mine" : "") }, [el("time", { text: clock(f.at) }),
        el("span", {}, [el("b", { text: f.title }), " ", f.text])]);
    }))], { "data-card": "feed" });
  }

  // The week so far, best first, with each coach's chance of winning it and
  // what the week would pay them if it ended now.
  function weekBoard(t, sim, limit) {
    var place = {}, pay = moneyNow(t), over = weekOver(t);
    t.rows.forEach(function (r) { place[r.c.name] = 1 + t.rows.filter(function (o) { return o.now > r.now; }).length; });
    var shown = t.rows.slice(0, limit);
    var mine = t.rows.filter(function (r) { return isMe(r.c.name); })[0];
    if (mine && shown.indexOf(mine) < 0) shown.push(mine);
    return el("div", { class: "rows standrows weekboard" }, [el("div", { class: "r hdr", "aria-hidden": "true", style: "grid-template-columns: 30px minmax(0,1fr) auto 66px" }, [
      el("span", {}), el("span", { text: "Coach" }), el("span", { class: "big", text: "Now" }),
      el("span", { class: "odds" }, [el("span", { text: "Win %" }), el("span", { text: over ? "Pays" : "$ now" })])])].concat(shown.map(function (r) {
      var m = pay[r.c.name];
      return el("div", { class: "r" + (isMe(r.c.name) ? " me" : "") + (place[r.c.name] === 1 && r.now > 0 ? " lead" : ""), style: "grid-template-columns: 30px minmax(0,1fr) auto 66px" }, [
        el("span", { class: "pos", text: String(place[r.c.name]), "data-tick": "l:pos:" + r.c.name }),
        el("span", { class: "name" }, [who(r.c.name), isMe(r.c.name) ? el("span", { class: "youtag", text: "YOU" }) : null,
          el("span", { class: "meta", style: "display:block", text: r.final + " final · " + r.left + " to play" + (r.bl ? " · " + plural(r.bl, "Big Loser point") : "") })]),
        el("span", { class: "big", text: String(r.now), "data-tick": "l:now:" + r.c.name }),
        el("span", { class: "odds num" }, [el("b", { text: pct(sim.chance[r.c.name] || 0) }),
          el("span", { class: "cash " + cashTone(m), title: (over ? "What the week pays: " : "If it ended now: ") + cash(m), text: cash(m) })])
      ]);
    })));
  }

