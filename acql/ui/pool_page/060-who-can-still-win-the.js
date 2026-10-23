  // ---- who can still win the week ------------------------------------------------
  // Each unfinished game's final margin is drawn from a bell around where it
  // is heading: the current margin plus the line's share of the time left,
  // narrowing as the clock runs down. Pre-game it is the line itself; with no
  // line known, the pool's line, or even. 13.5 points either side over a
  // full game is how far NFL results land from the line. A game level at the
  // end goes to overtime, as the dashboard has it.
  var FULL_SD = 13.5, SIMS = 4000;
  function rng(seed) {                     // small, seeded: same data, same numbers
    return function () {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  // The betting line as the home side's expected margin, the home side being the sheet's.
  function marketSpread(g) {
    var s = live.spreads[gameKey(g.hc, g.ac)];
    if (s == null) return null;
    if (typeof s === "number") return s;   // kept by an older version of the page
    return s.home === g.hc ? s.pts : -s.pts;
  }
  // The dashboard's own curve (analytics.margin_distribution before kickoff,
  // gameday.outlook during play), so the site and the dashboard give the same
  // chance for the same game. Its numbers come with the page data (DATA.curve,
  // written by poolpage.py from analytics.py); without them the site falls
  // back to the single bell it used before.
  var SQRT2 = Math.SQRT2, REACH = 80, REGULATION = 3600, OVERTIME = 600;
  function erfc(z) { return 2 * (1 - phi(z * SQRT2)); }
  function withCumulative(d) {             // running totals, for sampling
    var c = new Array(d.p.length), s = 0;
    for (var i = 0; i < d.p.length; i++) { s += d.p[i]; c[i] = s; }
    d.c = c;
    return d;
  }
  var preCache = {};
  function preDist(spread) {               // analytics.margin_distribution
    var C = DATA.curve, key = (Math.round(spread * 10) / 10).toFixed(1);
    if (preCache[key]) return preCache[key];
    var target = +key, narrow = C.sd, wide = C.sd * C.ratio, S = C.share, keys = C.keys, lo = C.low;
    function shape(centre) {
      var w = new Array(keys.length), tot = 0;
      for (var i = 0; i < keys.length; i++) {
        var off = lo + i - centre;
        w[i] = ((1 - S) * Math.exp(-(off / narrow) * (off / narrow) / 2) / narrow
                + S * Math.exp(-(off / wide) * (off / wide) / 2) / wide) * keys[i];
        tot += w[i];
      }
      for (i = 0; i < w.length; i++) w[i] /= tot;
      return w;
    }
    function mean(w) { var m = 0; for (var i = 0; i < w.length; i++) m += w[i] * (lo + i); return m; }
    var a = target - 8, b = target + 8;
    for (var it = 0; it < 40; it++) { var mid = (a + b) / 2; if (mean(shape(mid)) < target) a = mid; else b = mid; }
    return (preCache[key] = withCumulative({ lo: lo, p: shape((a + b) / 2) }));
  }
  function liveDist(now, left, expected) { // gameday.outlook, once a game is under way
    var C = DATA.curve, S = C.share, scale = Math.sqrt(left);
    var narrow = C.sd * scale, wide = C.sd * C.ratio * scale, centre = now + expected * left;
    function tail(x) {
      return (1 - S) * 0.5 * erfc((x - centre) / (narrow * SQRT2)) + S * 0.5 * erfc((x - centre) / (wide * SQRT2));
    }
    var lo = Math.round(now) - REACH, n = 2 * REACH + 1, p = new Array(n), tot = 0, i;
    for (i = 0; i < n; i++) { p[i] = Math.max(0, tail(lo + i - 0.5) - tail(lo + i + 0.5)); tot += p[i]; }
    for (i = 0; i < n; i++) p[i] /= tot;
    var z = -lo;                           // where a level score sits: overtime
    if (z >= 0 && z < n && p[z]) {
      var settled = p[z] * (1 - OT_TIE) / 2;
      p[z] *= OT_TIE;
      if (z + OT_MARGIN < n) p[z + OT_MARGIN] += settled;
      if (z - OT_MARGIN >= 0) p[z - OT_MARGIN] += settled;
    }
    return withCumulative({ lo: lo, p: p });
  }
  function outlook(x) {
    var g = x.g;
    var spread = marketSpread(g);
    if (spread == null) spread = g.line != null && g.fav ? (g.fav === g.hc ? g.line : -g.line) : 0;
    if (x.state === "post") return { fixed: (x.hs || 0) - (x.as || 0) };
    if (!DATA.curve) return oldOutlook(x, spread);
    if (x.state === "in" && x.sc) {
      var per = x.sc.period || 1, now = (x.hs || 0) - (x.as || 0), clock = Math.max(0, x.sc.clock || 0);
      if (per > 4) return { dist: liveDist(now, Math.max(clock, 60) / REGULATION, 0) };      // overtime
      var left = ((4 - per) * 900 + clock) / REGULATION;
      if (left * REGULATION < 1) {
        if (now !== 0) return { fixed: now };
        return { dist: liveDist(0, OVERTIME / REGULATION, 0) };                          // level: overtime
      }
      return { dist: liveDist(now, left, spread) };
    }
    return { dist: preDist(spread) };
  }
  function oldOutlook(x, spread) {         // the single bell, for page data without the curve
    if (x.state === "in" && x.sc) {
      var per = x.sc.period || 1;
      var left = per > 4 ? 0.04 : Math.max(0, ((4 - per) * 900 + Math.max(0, x.sc.clock || 0)) / 3600);
      return { mean: (x.hs || 0) - (x.as || 0) + spread * left, sd: FULL_SD * Math.sqrt(Math.max(left, 0.01)) };
    }
    return { mean: spread, sd: FULL_SD };
  }
  function drawMargin(o, rand, normal) {   // one simulated final margin
    if (o.fixed != null) return o.fixed;
    if (o.dist) {
      var c = o.dist.c, u = rand(), a = 0, b = c.length - 1;
      while (a < b) { var m = (a + b) >> 1; if (c[m] < u) a = m + 1; else b = m; }
      return o.dist.lo + a;
    }
    var margin = Math.round(o.mean + o.sd * normal());
    if (margin === 0) {                     // level after regulation: overtime
      var ot = rand();
      margin = ot < OT_TIE ? 0 : ot < (1 + OT_TIE) / 2 ? OT_MARGIN : -OT_MARGIN;
    }
    return margin;
  }
  function phi(z) {                        // the standard normal curve, to a millionth
    var t = 1 / (1 + 0.2316419 * Math.abs(z));
    var d = 0.3989422804014327 * Math.exp(-z * z / 2);
    var p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
    return z > 0 ? 1 - p : p;
  }
  // A game level at the end of regulation goes to overtime, which settles
  // all but about one in twenty - by a field goal as often as not.
  var OT_TIE = 0.05, OT_MARGIN = 3;
  // Chance the home margin finishes at k or more (scores are whole numbers,
  // as in the Win % simulation, which rounds each drawn margin), overtime
  // taken into account.
  function atLeast(o, k) {
    if (o.fixed != null) return o.fixed >= k ? 1 : 0;
    if (o.dist) {                          // the dashboard's curve: add up the margins from k
      var d = o.dist, i = Math.max(0, k - d.lo);
      return i >= d.c.length ? 0 : Math.min(1, Math.max(0, 1 - (i ? d.c[i - 1] : 0)));
    }
    var p = 1 - phi((k - 0.5 - o.mean) / o.sd);
    var settled = (phi((0.5 - o.mean) / o.sd) - phi((-0.5 - o.mean) / o.sd)) * (1 - OT_TIE) / 2;
    if (k > 0 && k <= OT_MARGIN) p += settled;          // won by 3 in overtime: now it reaches k
    else if (k <= 0 && k > -OT_MARGIN) p -= settled;    // lost by 3 in overtime: now it falls short
    return Math.min(1, Math.max(0, p));
  }
  // Chance a team loses by 15 or more - a Big Loser point.
  function blownChance(x, team) {
    var o = outlook(x);
    return team === x.g.hc ? 1 - atLeast(o, -14) : atLeast(o, 15);
  }
  // Chance a team is credited with its game, with the pool's line applied.
  function creditChance(x, team) {
    var g = x.g, o = outlook(x);
    if (g.line != null && g.fav) {
      var need = Math.ceil(g.line - 1e-9);
      var pFav = g.fav === g.hc ? atLeast(o, need) : 1 - atLeast(o, -need + 1);
      return team === g.fav ? pFav : 1 - pFav;
    }
    return team === g.hc ? atLeast(o, 1) : 1 - atLeast(o, 0);
  }
  function tallyGame(t, team) {
    for (var i = 0; i < t.games.length; i++) {
      if (t.games[i].g.hc === team || t.games[i].g.ac === team) return t.games[i];
    }
    return null;
  }
  function teamName(x, team) { return x ? (x.g.hc === team ? x.g.h : x.g.a) : teamFull(team); }
  var simCache = { key: "", sim: null };
  function simulate(t) {
    var L = DATA.live, games = t.games;
    var key = L.week + "|" + games.map(function (x) { return x.state + (x.hs || 0) + ":" + (x.as || 0) + ":" + (x.sc ? x.sc.clock + "/" + x.sc.period : ""); }).join(",") +
      "|" + JSON.stringify(live.spreads);
    if (simCache.key === key) return simCache.sim;
    var rand = rng(L.week * 7919 + games.reduce(function (a, x) { return a + (x.hs || 0) * 31 + (x.as || 0) * 17; }, 0));
    function normal() { var u = 1 - rand(), v = rand(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
    var plan = games.map(outlook);
    function creditOf(g, margin) {        // margin from the home side
      if (g.line != null && g.fav) {
        var need = Math.ceil(g.line - 1e-9), favMargin = g.fav === g.hc ? margin : -margin;
        return (favMargin >= need) === (g.fav === g.hc) ? "h" : "a";
      }
      return margin > 0 ? "h" : margin < 0 ? "a" : "";
    }
    var coaches = L.coaches, n = coaches.length;
    var wins = new Array(n).fill(0);
    var open = plan.map(function (pl, i) { return pl.fixed == null ? i : -1; }).filter(function (i) { return i >= 0; });
    // Per open game, each way it can go - home credited (h), away credited
    // (a), neither (n: level with no line), the home side losing by 15 or
    // more (hb), the away side (ab) - the sims where it went that way, and
    // each coach's wins among them.
    function way() { return [0, new Array(n).fill(0)]; }
    var split = open.map(function () { return { h: way(), a: way(), n: way(), hb: way(), ab: way() }; });
    var went = new Array(open.length);
    var margins = new Array(games.length), totals = new Array(n);
    for (var s = 0; s < SIMS; s++) {
      for (var i = 0; i < games.length; i++) {
        var pl = plan[i];
        margins[i] = drawMargin(pl, rand, normal);
      }
      var best = -1;
      for (var c = 0; c < n; c++) {
        var tot = 0, co = coaches[c];
        for (var j = 0; j < games.length; j++) {
          var side = creditOf(games[j].g, margins[j]);
          if (side && co.picks[j] === (side === "h" ? games[j].g.hc : games[j].g.ac)) tot++;
        }
        for (var b = 0; b < co.bl.length; b++) {
          for (var k = 0; k < games.length; k++) {
            var gg = games[k].g;
            if (gg.hc === co.bl[b] && margins[k] <= -15) tot++;
            else if (gg.ac === co.bl[b] && margins[k] >= 15) tot++;
          }
        }
        totals[c] = tot;
        if (tot > best) best = tot;
      }
      var top = 0;
      for (c = 0; c < n; c++) if (totals[c] === best) top++;
      for (var o = 0; o < open.length; o++) {
        var m = margins[open[o]], sp = split[o];
        went[o] = creditOf(games[open[o]].g, m) || "n";
        sp[went[o]][0]++;
        if (m <= -15) sp.hb[0]++;
        else if (m >= 15) sp.ab[0]++;
      }
      for (c = 0; c < n; c++) {
        if (totals[c] !== best) continue;
        var share = 1 / top;
        wins[c] += share;
        for (o = 0; o < open.length; o++) {
          var m2 = margins[open[o]], sp2 = split[o];
          sp2[went[o]][1][c] += share;
          if (m2 <= -15) sp2.hb[1][c] += share;
          else if (m2 >= 15) sp2.ab[1][c] += share;
        }
      }
    }
    var chance = {};
    coaches.forEach(function (co, c) { chance[co.name] = wins[c] / SIMS; });
    var sim = { chance: chance, open: open, split: split, wins: wins, sims: SIMS };
    simCache = { key: key, sim: sim };
    return sim;
  }
  // What a coach needs (#86): the results that went the same way in nearly every
  // simulated week they won. Read off the same simulation as Win %, so it costs nothing more.
  var NEED_SHARE = 0.95;
  function needs(t, sim, name) {
    var c = DATA.live.coaches.findIndex(function (co) { return co.name === name; });
    if (c < 0 || !sim.wins[c] || sim.wins[c] < sim.sims * 0.005) return null;
    var won = sim.wins[c], out = [];
    sim.open.forEach(function (gi, o) {
      var sp = sim.split[o], g = t.games[gi].g;
      if (sp.h[1][c] / won >= NEED_SHARE) out.push(teamName(t.games[gi], g.hc));
      else if (sp.a[1][c] / won >= NEED_SHARE) out.push(teamName(t.games[gi], g.ac));
      if (sp.hb[1][c] / won >= NEED_SHARE) out.push(teamName(t.games[gi], g.hc) + " to lose by 15+");
      else if (sp.ab[1][c] / won >= NEED_SHARE) out.push(teamName(t.games[gi], g.ac) + " to lose by 15+");
    });
    return out;
  }
  function pct(v) { return v >= 0.995 ? "99%+" : v > 0 && v < 0.005 ? "<1%" : Math.round(v * 100) + "%"; }
  function liveDetail(x) { return x && x.sc && x.sc.detail ? x.sc.detail : ""; }
  function upDown(margin) { return margin > 0 ? "up " + margin : margin < 0 ? "down " + (-margin) : "level"; }

