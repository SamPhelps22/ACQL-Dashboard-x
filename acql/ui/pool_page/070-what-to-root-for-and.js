  // ---- what to root for, and what the week would pay -----------------------------
  // The results still to come that move a coach's chance of the week most:
  // who is credited in each game still to finish, and their own Big Losers
  // losing by 15 or more. Each comes with the coach's chance if it happens,
  // if it doesn't, and how often it happens in the play-outs. A result seen
  // fewer than 40 times in 4,000 says too little to go on.
  var ROOT_FLOOR = 40;
  function rootsFor(t, sim, name) {
    var L = DATA.live, c = -1;
    L.coaches.forEach(function (co, i) { if (co.name === name) c = i; });
    if (c < 0 || !sim.wins) return [];
    var out = [], all = sim.wins[c];
    sim.open.forEach(function (gi, o) {
      var x = t.games[gi], g = x.g, sp = sim.split[o];
      if (sp.h[0] >= ROOT_FLOOR && sp.a[0] >= ROOT_FLOOR) {
        var ifH = sp.h[1][c] / sp.h[0], ifA = sp.a[1][c] / sp.a[0], home = ifH >= ifA;
        out.push({ kind: "pick", x: x, team: home ? g.hc : g.ac, other: home ? g.ac : g.hc,
          ifSo: Math.max(ifH, ifA), ifNot: Math.min(ifH, ifA), likely: (home ? sp.h[0] : sp.a[0]) / sim.sims });
      }
      L.coaches[c].bl.forEach(function (team) {
        if (team !== g.hc && team !== g.ac) return;
        var b = team === g.hc ? sp.hb : sp.ab, rest = sim.sims - b[0];
        if (b[0] < ROOT_FLOOR || rest < ROOT_FLOOR) return;
        out.push({ kind: "loser", x: x, team: team, other: team === g.hc ? g.ac : g.hc,
          ifSo: b[1][c] / b[0], ifNot: (all - b[1][c]) / rest, likely: b[0] / sim.sims });
      });
    });
    out.forEach(function (r) { r.swing = r.ifSo - r.ifNot; });
    // a Big Loser that would hurt (it costs a pick of theirs more) is covered by that game's own line
    out = out.filter(function (r) { return r.kind === "pick" || r.swing > 0; });
    out.sort(function (a, b) { return b.swing - a.swing; });
    return out;
  }
  // The result in words, with the pool's line in it: "Buffalo to win by 9 or
  // more", "the Chargers to stay within 8", "Atlanta to lose by 15 or more".
  function rootPhrase(r) {
    var g = r.x.g, name = teamName(r.x, r.team);
    if (r.kind === "loser") return name + " to lose by 15 or more";
    if (g.line != null && g.fav) {
      var need = Math.ceil(g.line - 1e-9);
      if (r.team === g.fav) return name + (need > 1 ? " to win by " + need + " or more" : " to win");
      return name + (need > 1 ? " to stay within " + (need - 1) : " to win or tie");
    }
    return name + " to win";
  }
  // What the week would pay each card if it ended as it stands, by the pool's
  // rule: the best card collects a dollar a game from every card behind it,
  // and cards level at the top split it.
  function moneyNow(t) {
    var out = {}, best = null, pot = 0, top = 0;
    t.rows.forEach(function (r) { if (best == null || r.now > best) best = r.now; });
    t.rows.forEach(function (r) { pot += best - r.now; if (r.now === best) top++; });
    t.rows.forEach(function (r) { out[r.c.name] = r.now === best ? (pot ? pot / top : 0) : r.now - best; });
    return out;
  }
  // The week's pot: what every card behind pays the best card, or cards.
  function pot(pay) { return Object.keys(pay).reduce(function (a, k) { return a + Math.max(0, pay[k]); }, 0); }
  // "+$23.50", "−$4", "$0"
  function cash(v) {
    if (v == null) return "";
    var r = Math.round(v * 100) / 100;
    if (!r) return "$0";
    var a = Math.abs(r);
    return (r > 0 ? "+" : "−") + "$" + (a % 1 ? a.toFixed(2) : String(a));
  }
  function cashTone(v) { return v > 0.004 ? "up" : v < -0.004 ? "down" : "flat"; }
  // Where the pool's line stands in a game under way or over: "Buffalo +7,
  // 2 short of the 8.5", "Buffalo +10, covering the 8.5", "Detroit leads by 3".
  function standingText(x) {
    if (x.state === "pre" || x.hs == null || x.as == null) return "";
    var g = x.g, margin = x.hs - x.as, over = x.state === "post";
    if (g.line != null && g.fav) {
      var by = g.fav === g.hc ? margin : -margin, need = Math.ceil(g.line - 1e-9), name = teamName(x, g.fav);
      if (by >= need) return name + " +" + by + ", " + (over ? "covered" : "covering") + " the " + g.line;
      if (by > 0 || !over) return name + (by > 0 ? " +" + by : by < 0 ? " −" + (-by) : " level") + ", " + (need - by) + " short of the " + g.line;
    }
    if (!margin) return over ? "Tied" : "Level";
    return teamName(x, margin > 0 ? g.hc : g.ac) + (over ? " won by " : " leads by ") + Math.abs(margin);
  }

