  // ---- the picking profile ---------------------------------------------------------------
  // From every played game: which side the coach took. A graded sheet keeps
  // only the right picks, so a miss is read as the other side.
  function profileOf(name) {
    var out = { games: 0, fav: 0, favKnown: 0, favRight: 0, home: 0, against: 0, againstRight: 0, lined: 0, linedRight: 0, straight: 0, straightRight: 0, right: 0, teams: {} };
    DATA.weeks.forEach(function (w) {
      var mine = w.picks && w.picks[name];
      if (!mine) return;
      var all = Object.keys(w.picks || {}).map(function (n) { return w.picks[n]; });
      w.results.forEach(function (g, j) {
        var bit = mine[j];
        if (bit !== "1" && bit !== "0") return;
        var picked = bit === "1" ? g.winner : g.loser;
        if (!picked) return;
        out.games++;
        var ok = bit === "1";
        if (ok) out.right++;
        var home = g.home || String(g.matchup || "").split(" @ ")[1] || "";
        if (picked === home) out.home++;
        var fav = g.fav || g.pool_fav || "";
        if (fav) { out.favKnown++; if (picked === fav) { out.fav++; if (ok) out.favRight++; } }
        var right = 0, cards = 0;
        all.forEach(function (bits) { if (bits[j] === "1") right++; if (bits[j] === "1" || bits[j] === "0") cards++; });
        var crowdRight = right * 2 > cards ? true : right * 2 < cards ? false : null;
        if (crowdRight != null && crowdRight !== ok) { out.against++; if (ok) out.againstRight++; }
        if (g.pool_line != null || g.line) { out.lined++; if (ok) out.linedRight++; } else { out.straight++; if (ok) out.straightRight++; }
        var rec = out.teams[picked] = out.teams[picked] || { right: 0, wrong: 0 };
        if (ok) rec.right++; else rec.wrong++;
      });
    });
    return out;
  }
  var poolProfile = null;
  function poolProfiles() {
    if (poolProfile) return poolProfile;
    var sum = { fav: 0, favKnown: 0, home: 0, games: 0, against: 0 };
    names().forEach(function (n) {
      var pr = profileOf(n);
      sum.fav += pr.fav; sum.favKnown += pr.favKnown; sum.home += pr.home; sum.games += pr.games; sum.against += pr.against;
    });
    poolProfile = sum;
    return sum;
  }
  function profileModule(p) {
    var pr = profileOf(p.name);
    if (pr.games < 8) return null;
    var pool = poolProfiles();
    function meter(label, value, poolValue, why) {
      return el("div", { class: "meter" }, [
        el("div", { class: "top" }, [el("b", { text: label }), el("span", { text: Math.round(value * 100) + "%" })]),
        el("div", { class: "track", role: "img", "aria-label": label + ": " + Math.round(value * 100) + "%, the pool " + Math.round(poolValue * 100) + "%" }, [
          el("div", { class: "fill", style: "width:" + Math.round(value * 100) + "%" }),
          el("div", { class: "pool", style: "left:calc(" + Math.round(poolValue * 100) + "% - 1px)", title: "The pool: " + Math.round(poolValue * 100) + "%" })]),
        el("span", { class: "why", text: why + " The line is the pool, " + Math.round(poolValue * 100) + "%." })
      ]);
    }
    var kids = [];
    if (pr.favKnown >= 8) kids.push(meter("Takes the favourite", pr.fav / pr.favKnown, pool.favKnown ? pool.fav / pool.favKnown : 0.5,
      "Took the favourite in " + pr.fav + " of " + plural(pr.favKnown, "game") + " with one known, and " + pr.favRight + " of those came in."));
    kids.push(meter("Takes the home team", pr.home / pr.games, pool.games ? pool.home / pool.games : 0.5,
      "Took the home side in " + pr.home + " of " + plural(pr.games, "game") + "."));
    kids.push(meter("Goes against the crowd", pr.against / pr.games, pool.games ? pool.against / pool.games : 0.2,
      pr.against ? "Went against most of the pool " + plural(pr.against, "time") + ", and " + pr.againstRight + " came in." : "Not once yet."));
    var teams = Object.keys(pr.teams).map(function (t) { return { team: t, right: pr.teams[t].right, wrong: pr.teams[t].wrong }; })
      .filter(function (t) { return t.right + t.wrong >= 2; });
    var bestT = teams.slice().sort(function (a, b) { return (b.right - b.wrong) - (a.right - a.wrong) || b.right - a.right; })[0];
    var worstT = teams.slice().sort(function (a, b) { return (b.wrong - b.right) - (a.wrong - a.right) || b.wrong - a.wrong; })[0];
    var recs = [];
    if (bestT && bestT.right > bestT.wrong) recs.push(el("div", { class: "box" }, [el("span", { class: "note", text: "Best team to pick" }),
      el("span", { class: "team" }, [badge(bestT.team), el("b", { text: bestT.team })]), el("span", { class: "note", text: bestT.right + "–" + bestT.wrong + " when picked" })]));
    if (worstT && worstT.wrong > worstT.right) recs.push(el("div", { class: "box" }, [el("span", { class: "note", text: "Worst team to pick" }),
      el("span", { class: "team" }, [badge(worstT.team), el("b", { text: worstT.team })]), el("span", { class: "note", text: worstT.right + "–" + worstT.wrong + " when picked" })]));
    if (recs.length) kids.push(el("div", { class: "teamrec" }, recs));
    if (pr.lined && pr.straight) kids.push(el("p", { class: "note", text: "Right on " + pr.linedRight + " of " + pr.lined + " lined games and " + pr.straightRight + " of " + pr.straight + " straight-up ones." }));
    return module("Picking profile", plural(pr.right, "pick") + " right of " + pr.games, [el("div", { class: "profile" }, kids)], { "data-card": "profile" });
  }

  // A nickname from how a coach picks: the habit furthest from the pool's,
  // once there are enough picks to tell. Most coaches get one; it changes as they do.
  function nickname(name) {
    var pr = profileOf(name);
    if (pr.games < 12) return null;
    var pool = poolProfiles(), options = [];
    function rate(a, b) { return b ? a / b : null; }
    var fav = rate(pr.fav, pr.favKnown), poolFav = rate(pool.fav, pool.favKnown);
    var home = rate(pr.home, pr.games), poolHome = rate(pool.home, pool.games);
    var against = rate(pr.against, pr.games), poolAgainst = rate(pool.against, pool.games);
    if (fav != null && poolFav != null && pr.favKnown >= 12) {
      options.push({ by: fav - poolFav, name: "Chalk Eater", why: "Takes the favourite " + pctText(fav) + " of the time; the pool, " + pctText(poolFav) + "." });
      options.push({ by: poolFav - fav, name: "Dog Lover", why: "Takes the underdog " + pctText(1 - fav) + " of the time; the pool, " + pctText(1 - poolFav) + "." });
    }
    if (poolHome != null) {
      options.push({ by: home - poolHome, name: "Homebody", why: "Takes the home side " + pctText(home) + " of the time; the pool, " + pctText(poolHome) + "." });
      options.push({ by: poolHome - home, name: "Road Warrior", why: "Takes the road side " + pctText(1 - home) + " of the time; the pool, " + pctText(1 - poolHome) + "." });
    }
    if (poolAgainst != null) {
      options.push({ by: (against - poolAgainst) * 1.5, name: "The Contrarian", why: "Goes against most of the pool " + pctText(against) + " of the time; the pool, " + pctText(poolAgainst) + "." });
      options.push({ by: (poolAgainst - against) * 1.5, name: "Mr. Consensus", why: "Goes against most of the pool only " + pctText(against) + " of the time; the pool, " + pctText(poolAgainst) + "." });
    }
    var best = options.filter(function (o) { return o.by >= 0.06; }).sort(function (a, b) { return b.by - a.by; })[0];
    return best ? { name: best.name, why: best.why } : null;
  }

  // The coaches just above and below, and how they've done against each other.
  function rivalsModule(p) {
    var above = DATA.players.filter(function (q) { return q.wins > p.wins; }).sort(function (a, b) { return a.wins - b.wins; })[0];
    var level = DATA.players.filter(function (q) { return q.wins === p.wins && q.name !== p.name; });
    var below = DATA.players.filter(function (q) { return q.wins < p.wins; }).sort(function (a, b) { return b.wins - a.wins; })[0];
    var list = [];
    if (above) list.push(above);
    level.slice(0, 2).forEach(function (q) { list.push(q); });
    if (below) list.push(below);
    if (!list.length) return null;
    return module("Rivals", "just above and below", list.map(function (q) {
      var c = compare(p.name, q.name);
      var gap = q.wins - p.wins;
      return el("div", { class: "rival" }, [
        el("span", { class: "name" }, [who(q.name), el("span", { class: "note", text: "  " + (q.place != null ? ordinal(q.place) : "") })]),
        el("span", { class: "gap " + (gap > 0 ? "down" : gap < 0 ? "up" : "flat"), text: gap > 0 ? gap + " ahead" : gap < 0 ? -gap + " behind" : "level" }),
        el("span", { class: "meta", text: "Higher score " + c.aWeeks + "–" + c.bWeeks + " in weeks against each other · same pick " +
          (c.both ? Math.round(100 * c.agree / c.both) : 0) + "% of the time" })
      ]);
    }).concat([available("h2h") ? el("a", { class: "more-link", href: "#h2h", onclick: function (e) {
      e.preventDefault(); state.a = p.name; state.b = list[0].name; go("h2h"); }, text: "Head-to-head in full" }) : null]), { "data-card": "rivals" });
  }

  function poolsModuleFor(p) {
    var s = p.suicide;
    var teams = DATA.teams || {};
    var left = s.alive ? Object.keys(teams).filter(function (c) { return (s.used || []).indexOf(c) < 0; }) : [];
    var kids = [el("p", { class: "race-sum", text: s.alive ? "Still in the suicide pool, with " + plural(left.length, "team") + " left to use." :
      s.out ? "Out of the suicide pool in week " + s.out + (s.picks[String(s.out)] ? ", on " + s.picks[String(s.out)] + "." : ".") : "Not in the suicide pool." })];
    if ((s.used || []).length) kids.push(el("div", { class: "chips" }, [el("span", { class: "note", text: "Used: " })].concat(s.used.map(function (c) { return badge(c); }))));
    kids.push(el("p", { class: "race-sum", text: p.big_loser ? plural(p.big_loser, "Big Loser point") + " this season." : "No Big Loser points yet." }));
    return module("Side pools", null, kids, { "data-card": "pools-for" });
  }
  function moneyModuleFor(p, moneyWon) {
    if (!DATA.money) return null;
    var series = (DATA.money_by_week || {})[p.name];
    return module("Money", p.net != null ? money(p.net) + " net" : null, [
      el("p", { class: "race-sum", text: "Won " + money(p.won || 0) + ", owes " + money(p.paid || 0) + "." }),
      series && series.length > 1 ? chartBox("money-" + p.name, 160, function (w) { return moneyChart(w, p.name, true); }) : null,
      moreLink("Everyone’s money", "money")
    ], { "data-card": "money-for" });
  }

