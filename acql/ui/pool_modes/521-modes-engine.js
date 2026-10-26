  // ---- league modes: the one place their numbers are worked out ------------------------
  // League Broadcast, League Time Machine and the Numbers Room all read the
  // league from here, so a standing, a streak or a record means the same
  // thing in each. Everything starts from the seasons the site already knows
  // (thisSeason and the archive, History's allSeasons): each coach's official
  // weekly total and each week's official winners and average. Standings at a
  // week are those totals added up to it, ranked the way the pool ranks them
  // (competition ranking: 1, 2, 2, 4 - recap._places in the dashboard).
  // Nothing here is ever written back; nothing is guessed for a week the
  // archive doesn't have.

  // What a figure is, said the same way everywhere.
  var LM_KINDS = {
    official: { label: "Official", tip: "As the pool's own files record it" },
    calc: { label: "Calculated", tip: "Worked out from official weekly totals" },
    est: { label: "Estimate", tip: "A simulation's chance - not a result" },
    prov: { label: "Provisional", tip: "Games still being played: this can change" },
    hypo: { label: "What if", tip: "A hypothetical - this did not happen" }
  };
  function lmSrc(kind, text) {
    var k = LM_KINDS[kind] || LM_KINDS.calc;
    return el("span", { class: "lm-src " + kind, title: k.tip + (text ? " - " + text : "") }, [k.label]);
  }

  var lmCache = { data: null, hist: null, seasons: null, cps: {}, stats: {}, misc: {} };
  function lmFresh() {
    if (lmCache.data !== DATA || lmCache.hist !== historyData) {
      lmCache = { data: DATA, hist: historyData, seasons: null, cps: {}, stats: {}, misc: {} };
    }
  }
  function lmSeasons() {
    lmFresh();
    if (!lmCache.seasons) lmCache.seasons = allSeasons().filter(function (s) { return s && (s.standings || []).length; });
    return lmCache.seasons;
  }
  function lmSeason(year) {
    var all = lmSeasons();
    for (var i = 0; i < all.length; i++) if (String(all[i].year) === String(year)) return all[i];
    return all[0] || null;
  }
  function lmWeekNums(s) {
    return (s.weeks || []).map(function (w) { return Number(w.week); }).filter(function (n) { return n > 0; })
      .sort(function (a, b) { return a - b; });
  }
  // A week's own record: this season's full one from the page, an archived season's summary.
  function lmWeekRec(s, n) {
    if (s.current) { var w = weekData(n); if (w) return w; }
    for (var i = 0; i < (s.weeks || []).length; i++) if (Number(s.weeks[i].week) === n) return s.weeks[i];
    return null;
  }
  // Competition ranking of values, highest first: equal values share a place.
  function lmRank(values) {
    var out = {}, keys = Object.keys(values);
    keys.forEach(function (k) {
      var v = values[k];
      if (v == null) return;
      var ahead = 0, same = 0;
      keys.forEach(function (j) { if (values[j] != null) { if (values[j] > v) ahead++; else if (values[j] === v) same++; } });
      out[k] = { place: ahead + 1, tied: same > 1 };
    });
    return out;
  }
  function lmMean(xs) { return xs.length ? xs.reduce(function (a, b) { return a + b; }, 0) / xs.length : null; }
  // Population standard deviation: how far a coach's weeks sit from their own average.
  function lmSd(xs) {
    if (xs.length < 2) return null;
    var m = lmMean(xs);
    return Math.sqrt(xs.reduce(function (a, x) { return a + (x - m) * (x - m); }, 0) / xs.length);
  }
  // Quartiles by linear interpolation between the sorted scores.
  function lmQuantile(sorted, q) {
    if (!sorted.length) return null;
    var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }
  function lmFix(v, d) { return v == null || isNaN(v) ? "–" : Number(v).toFixed(d == null ? 1 : d); }
  function lmSigned(v, d) { return v == null || isNaN(v) ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d == null ? 1 : d); }
  // "1 week", "3 weeks", "1 place"
  function lmUnit(v, unit) { return Math.abs(v) === 1 ? unit.replace(/s$/, "") : unit; }
  function lmPlace(row) { return row ? (row.tied ? "T" : "") + row.place : "–"; }

  // The standings after every week on record, for one season.
  function lmCheckpoints(s) {
    lmFresh();
    var key = String(s.year);
    if (lmCache.cps[key]) return lmCache.cps[key];
    var weeks = lmWeekNums(s), people = (s.standings || []).filter(function (x) { return x && x.name; });
    var run = {}, prev = null, cps = [], byWeek = {};
    people.forEach(function (x) { run[x.name] = 0; });
    weeks.forEach(function (n) {
      var rec = lmWeekRec(s, n) || {}, scores = {}, scored = [];
      people.forEach(function (x) {
        var v = (x.weekly || {})[String(n)];
        scores[x.name] = v == null ? null : Number(v);
        if (v != null) { run[x.name] += Number(v); scored.push(Number(v)); }
      });
      var totals = {};
      people.forEach(function (x) { totals[x.name] = run[x.name]; });
      var places = lmRank(totals), wranks = lmRank(scores);
      var lead = Math.max.apply(null, people.map(function (x) { return totals[x.name]; }).concat([0]));
      var average = rec.average != null ? Number(rec.average) : lmMean(scored);
      var rows = people.map(function (x) {
        var pl = places[x.name], before = prev ? prev.by[x.name] : null;
        return { name: x.name, total: totals[x.name], place: pl.place, tied: pl.tied,
          move: before ? before.place - pl.place : null, behind: lead - totals[x.name],
          score: scores[x.name], wplace: wranks[x.name] ? wranks[x.name].place : null,
          vsAvg: scores[x.name] != null && average != null ? scores[x.name] - average : null };
      }).sort(function (a, b) { return a.place - b.place || b.total - a.total || a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
      var by = {};
      rows.forEach(function (r) { by[r.name] = r; });
      var cp = { week: n, rows: rows, by: by, lead: lead, leaders: rows.filter(function (r) { return r.place === 1; }).map(function (r) { return r.name; }),
        winners: (rec.winners || []).slice(), top: rec.top != null ? Number(rec.top) : (scored.length ? Math.max.apply(null, scored) : null),
        low: scored.length ? Math.min.apply(null, scored) : null, average: average, scored: scored.length,
        most: rec.most != null ? Number(rec.most) : null, games: rec.games != null ? Number(rec.games) : null };
      cps.push(cp);
      byWeek[n] = cp;
      prev = cp;
    });
    var last = weeks.length ? weeks[weeks.length - 1] : 0;
    var through = Number(s.through_week) || last, missing = [];
    for (var k = 1; k <= through; k++) if (!byWeek[k]) missing.push(k);
    var verify = lmVerify(s, cps[cps.length - 1]);
    lmOfficialEnd(s, cps[cps.length - 1], verify);
    var out = { year: s.year, weeks: weeks, cps: cps, byWeek: byWeek, missing: missing, last: last,
      seasonWeeks: Number(s.season_weeks) || 18, verify: verify };
    lmCache.cps[key] = out;
    return out;
  }
  // Do the standings worked out here end where the official table does?
  // A difference only in how a tie is broken is said so, not counted as wrong.
  function lmVerify(s, cp) {
    var out = { checked: 0, matched: 0, ties: 0, off: [], week: cp ? cp.week : null };
    if (!cp || Number(s.through_week || 0) !== cp.week) return out;
    (s.standings || []).forEach(function (x) {
      var mine = cp.by[x.name];
      if (!mine || x.place == null) return;
      out.checked++;
      var off = Number(x.place), same = cp.rows.filter(function (r) { return r.total === mine.total; }).length;
      if (off === mine.place) out.matched++;
      else if (mine.tied && off >= mine.place && off < mine.place + same) out.ties++;
      else out.off.push({ name: x.name, official: off, calc: mine.place });
    });
    return out;
  }
  // The latest week has an official table: its places (ties broken the pool's
  // way) and moves are used as they are. Earlier weeks' tie order was never
  // kept, so there equal totals share a place. Only when the worked-out
  // table agrees with the official one apart from tie order.
  function lmOfficialEnd(s, cp, verify) {
    if (!cp || !verify.checked || verify.off.length || verify.checked !== cp.rows.length) return;
    var std = {};
    (s.standings || []).forEach(function (x) { std[x.name] = x; });
    cp.rows.forEach(function (r) {
      r.calcPlace = r.place; r.calcTied = r.tied; r.calcMove = r.move;
      r.place = Number(std[r.name].place);
      r.tied = cp.rows.filter(function (q) { return Number(std[q.name].place) === r.place; }).length > 1;
      var p = s.current ? player(r.name) : null;
      if (p && p.move != null) r.move = p.move;
    });
    cp.rows.sort(function (a, b) { return a.place - b.place || a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
    cp.leaders = cp.rows.filter(function (r) { return r.place === 1; }).map(function (r) { return r.name; });
    cp.official = true;
  }
  function lmCp(s, n) { var c = lmCheckpoints(s); return c.byWeek[n] || null; }

  // Every coach's numbers over a run of weeks [from, to] in one season.
  function lmStats(s, from, to) {
    lmFresh();
    var C = lmCheckpoints(s);
    from = from || C.weeks[0] || 0;
    to = to || C.last;
    var key = s.year + ":" + from + ":" + to;
    if (lmCache.stats[key]) return lmCache.stats[key];
    var span = C.cps.filter(function (c) { return c.week >= from && c.week <= to; });
    var endCp = span[span.length - 1] || null, before = C.cps.filter(function (c) { return c.week < from; }).pop() || null;
    var rows = (s.standings || []).map(function (x) {
      var name = x.name, sc = [], vs = [], above = 0, wins = 0, outright = 0, winWeeks = [], atTop = 0, topRun = 0, run = 0,
        best = null, worst = null, bestW = [], worstW = [], rise = null, fall = null, moves = [], aboveRun = 0, ar = 0,
        bestPlace = null, worstPlace = null, made = 0, most = 0, path = [], winRun = 0, wr = 0, bl = 0, blKnown = s.current;
      span.forEach(function (c) {
        var r = c.by[name];
        if (!r) { path.push(null); return; }
        path.push(r.place);
        if (bestPlace == null || r.place < bestPlace) bestPlace = r.place;
        if (worstPlace == null || r.place > worstPlace) worstPlace = r.place;
        if (r.place === 1) { atTop++; run++; topRun = Math.max(topRun, run); } else run = 0;
        if (r.move != null && (c !== span[0] || before)) {
          moves.push(r.move);
          if (rise == null || r.move > rise.v) rise = { v: r.move, week: c.week };
          if (fall == null || r.move < fall.v) fall = { v: r.move, week: c.week };
        }
        var won = c.winners.indexOf(name) >= 0;
        if (won) { wins++; winWeeks.push(c.week); if (c.winners.length === 1) outright++; wr++; winRun = Math.max(winRun, wr); } else wr = 0;
        if (r.score == null) { ar = 0; return; }
        sc.push(r.score);
        if (best == null || r.score > best) { best = r.score; bestW = [c.week]; } else if (r.score === best) bestW.push(c.week);
        if (worst == null || r.score < worst) { worst = r.score; worstW = [c.week]; } else if (r.score === worst) worstW.push(c.week);
        if (r.vsAvg != null) { vs.push(r.vsAvg); if (r.vsAvg > 0) { above++; ar++; aboveRun = Math.max(aboveRun, ar); } else ar = 0; }
        if (c.most) { made += r.score; most += c.most; }
        if (s.current) {
          var w = weekData(c.week), line = w ? w.scores.filter(function (q) { return q.name === name; })[0] : null;
          if (line) bl += Number(line.big_loser || 0);
        }
      });
      var end = endCp ? endCp.by[name] : null;
      return { name: name, place: end ? end.place : null, tied: end ? end.tied : false, total: sc.reduce(function (a, b) { return a + b; }, 0),
        weeks: sc.length, avg: lmMean(sc), sd: lmSd(sc), vsAvg: lmMean(vs), above: above, abovePct: sc.length ? above / sc.length : null,
        best: best, bestWeeks: bestW, worst: worst, worstWeeks: worstW, wins: wins, outright: outright, winWeeks: winWeeks,
        winRun: winRun, atTop: atTop, topRun: topRun, rise: rise, fall: fall,
        vol: moves.length ? lmMean(moves.map(Math.abs)) : null, aboveRun: aboveRun, bestPlace: bestPlace, worstPlace: worstPlace,
        pctPossible: most ? made / most : null, path: path, bigLoser: blKnown ? bl : null,
        seasonTotal: end ? end.total : null, behind: end ? end.behind : null };
    });
    var out = { season: s, from: from, to: to, weeks: span.map(function (c) { return c.week; }), cps: span, rows: rows,
      by: rows.reduce(function (o, r) { o[r.name] = r; return o; }, {}) };
    lmCache.stats[key] = out;
    return out;
  }

  // The league's record book: across every season the site knows. Each record
  // names its season, week and coach, and how it was worked out.
  function lmRecords() {
    lmFresh();
    if (lmCache.misc.records) return lmCache.misc.records;
    var out = [];
    function keep(id, label, unit, calc, kind, better) {
      var r = { id: id, label: label, unit: unit, calc: calc, kind: kind, value: null, holders: [] };
      r.offer = function (v, h) {
        if (v == null) return;
        if (r.value == null || better(v, r.value)) { r.value = v; r.holders = [h]; } else if (v === r.value) r.holders.push(h);
      };
      out.push(r);
      return r;
    }
    var hi = keep("high", "Highest weekly score", "wins", "A coach's official total for one week (games plus Big Loser points).", "official", function (a, b) { return a > b; });
    var lo = keep("low", "Lowest weekly score", "wins", "The fewest official wins a coach with a recorded card scored in one week.", "official", function (a, b) { return a < b; });
    var marg = keep("margin", "Most above the pool's average", "wins", "A week's score minus that week's official pool average.", "calc", function (a, b) { return a > b; });
    var won = keep("weeks", "Most weekly wins in a season", "weeks", "Weeks a coach was among the official weekly winners (a shared week counts).", "official", function (a, b) { return a > b; });
    var streak = keep("winrun", "Longest run of weekly wins", "weeks", "Weeks in a row among the weekly winners.", "calc", function (a, b) { return a > b; });
    var total = keep("total", "Most wins in a season", "wins", "A coach's season total: the official weekly totals added up.", "calc", function (a, b) { return a > b; });
    var rise = keep("rise", "Biggest one-week climb", "places", "Places gained in the season standings from one week to the next.", "calc", function (a, b) { return a > b; });
    var top = keep("attop", "Most weeks in first place", "weeks", "Weeks a coach finished in first place (a share counts) in one season's standings.", "calc", function (a, b) { return a > b; });
    var steady = keep("aboverun", "Longest run above the average", "weeks", "Weeks in a row scoring above the pool's average.", "calc", function (a, b) { return a > b; });
    lmSeasons().forEach(function (s) {
      var C = lmCheckpoints(s), st = lmStats(s);
      C.cps.forEach(function (c) {
        c.rows.forEach(function (r) {
          if (r.score == null) return;
          var h = { name: r.name, year: s.year, week: c.week };
          hi.offer(r.score, h);
          lo.offer(r.score, h);
          if (r.vsAvg != null) marg.offer(Math.round(r.vsAvg * 100) / 100, h);
          if (r.move != null && r.move > 0) rise.offer(r.move, h);
        });
      });
      st.rows.forEach(function (r) {
        var h = { name: r.name, year: s.year, week: null };
        if (r.wins) won.offer(r.wins, h);
        if (r.winRun) streak.offer(r.winRun, { name: r.name, year: s.year, week: r.winWeeks[r.winWeeks.length - 1] || null });
        if (r.weeks === C.cps.length) total.offer(r.total, h);
        if (r.atTop) top.offer(r.atTop, h);
        if (r.aboveRun) steady.offer(r.aboveRun, h);
      });
    });
    // a "run" of one is no run: those records wait until someone strings two together
    lmCache.misc.records = out.filter(function (r) { return r.value != null && r.holders.length && !((r.id === "winrun" || r.id === "aboverun") && r.value < 2); });
    return lmCache.misc.records;
  }

  // What happened, week by week: every item comes from a record or a sum of them.
  // The archive keeps weeks, never times, so an event is dated to its week.
  function lmEvents(s) {
    lmFresh();
    var key = "ev" + s.year;
    if (lmCache.misc[key]) return lmCache.misc[key];
    var C = lmCheckpoints(s), out = [], high = null, everTop = {};
    C.cps.forEach(function (c, i) {
      var prev = i ? C.cps[i - 1] : null;
      if (c.winners.length) out.push({ week: c.week, kind: "win", src: "official", who: c.winners,
        text: listNames(c.winners, 3) + (c.winners.length > 1 ? " shared week " : " won week ") + c.week + (c.top != null ? " with " + plural(c.top, "win") : "") });
      var leadersNow = c.leaders.slice().sort().join("|"), leadersThen = prev ? prev.leaders.slice().sort().join("|") : "";
      if (leadersNow !== leadersThen) out.push({ week: c.week, kind: "lead", src: "calc", who: c.leaders,
        text: (prev ? "" : "First leader: ") + listNames(c.leaders, 3) + (c.leaders.length > 1 ? " share first place" : prev ? " took over first place" : "") + " on " + plural(c.lead, "win") });
      c.leaders.forEach(function (n) {
        if (prev && !everTop[n]) out.push({ week: c.week, kind: "first", src: "calc", who: [n], text: n + " reached first place for the first time this season" });
        everTop[n] = true;
      });
      if (c.top != null && high != null && c.top > high) out.push({ week: c.week, kind: "record", src: "official", who: c.winners,
        text: "New season high: " + plural(c.top, "win") + " (" + listNames(c.winners, 2) + "), beating " + high });
      if (c.top != null) high = high == null ? c.top : Math.max(high, c.top);
      if (prev) {
        var up = c.rows.filter(function (r) { return r.move != null; }).sort(function (a, b) { return b.move - a.move; });
        if (up.length && up[0].move >= 4) {
          var bestUp = up.filter(function (r) { return r.move === up[0].move; }).map(function (r) { return r.name; });
          out.push({ week: c.week, kind: "move", src: "calc", who: bestUp, text: listNames(bestUp, 2) + " climbed " + plural(up[0].move, "place") + " to " + ordinal(c.by[bestUp[0]].place) });
        }
      }
      var rec = lmWeekRec(s, c.week);
      if (s.current && rec && rec.suicide && rec.suicide.killed) {
        out.push({ week: c.week, kind: "suicide", src: "official", who: [],
          text: plural(rec.suicide.killed, "coach", "coaches") + " knocked out of the suicide pool" + (rec.suicide.killer ? " - most by " + rec.suicide.killer : "") +
            (rec.suicide.left != null ? "; " + rec.suicide.left + " left" : "") });
      }
    });
    if (!s.current) {
      (s.standings || []).forEach(function (x) {
        if (x.suicide_out && C.byWeek[x.suicide_out]) out.push({ week: Number(x.suicide_out), kind: "suicide", src: "official", who: [x.name], text: x.name + " went out of the suicide pool" });
      });
    }
    out.sort(function (a, b) { return a.week - b.week; });
    lmCache.misc[key] = out;
    return out;
  }

  // Two coaches over the same weeks: who scored more, week by week.
  // The current season's head-to-head is the site's own compare(); an archived
  // season (no picks kept) is read from its week-by-week totals.
  function lmVs(s, a, b, from, to) {
    var st = lmStats(s, from, to), out = { a: a, b: b, aw: 0, bw: 0, ties: 0, weeks: [], gap: [], shared: null };
    st.cps.forEach(function (c) {
      var ra = c.by[a], rb = c.by[b];
      if (!ra || !rb) return;
      out.gap.push(ra.total - rb.total);
      if (s.current || ra.score == null || rb.score == null) return;
      out.weeks.push({ week: c.week, a: ra.score, b: rb.score });
      if (ra.score > rb.score) out.aw++; else if (rb.score > ra.score) out.bw++; else out.ties++;
    });
    if (s.current) {
      var cmp = compare(a, b, st.from, st.to);
      out.aw = cmp.aWeeks; out.bw = cmp.bWeeks; out.ties = cmp.level;
      out.weeks = cmp.weeks.filter(function (r) { return r.a != null && r.b != null; }).map(function (r) { return { week: r.week, a: r.a, b: r.b }; });
      out.shared = { same: cmp.agree, games: cmp.both };
    }
    return out;
  }

  // Every graded game of the season, with how the pool's cards went on it.
  function lmGames(from, to) {
    lmFresh();
    var key = "g" + from + ":" + to;
    if (lmCache.misc[key]) return lmCache.misc[key];
    var out = [];
    pickedWeeks().forEach(function (w) {
      if ((from && w.week < from) || (to && w.week > to)) return;
      (w.results || []).forEach(function (g, j) {
        if (!g.winner) return;
        var on = 0, right = 0, favs = 0;
        Object.keys(w.picks || {}).forEach(function (n) {
          var x = sideOf(w, n, j);
          if (!x) return;
          on++;
          if (x.ok) right++;
          if (g.fav && x.team === g.fav) favs++;
        });
        out.push({ week: w.week, j: j, matchup: g.matchup, home: g.home, away: g.away, winner: g.winner, loser: g.loser,
          cards: on, right: right, wrong: on - right, pct: on ? right / on : null, fav: g.fav || "", spread: g.spread,
          upset: !!(g.fav && g.winner !== g.fav), split: on ? Math.min(right, on - right) / on : 0, onFav: favs, line: g.line || "" });
      });
    });
    lmCache.misc[key] = out;
    return out;
  }
  // How each coach has picked each team, from the graded cards only.
  function lmTeamPicks(from, to) {
    lmFresh();
    var key = "t" + from + ":" + to;
    if (lmCache.misc[key]) return lmCache.misc[key];
    var cells = {}, teams = {}, coaches = {}, favTend = {};
    pickedWeeks().forEach(function (w) {
      if ((from && w.week < from) || (to && w.week > to)) return;
      (w.results || []).forEach(function (g, j) {
        Object.keys(w.picks || {}).forEach(function (n) {
          var x = sideOf(w, n, j);
          if (!x || !x.team) return;
          var c = cells[n] || (cells[n] = {});
          var t = c[x.team] || (c[x.team] = { n: 0, ok: 0 });
          t.n++; if (x.ok) t.ok++;
          var tt = teams[x.team] || (teams[x.team] = { n: 0, ok: 0 });
          tt.n++; if (x.ok) tt.ok++;
          coaches[n] = (coaches[n] || 0) + 1;
          if (g.fav) {
            var f = favTend[n] || (favTend[n] = { games: 0, fav: 0, favOk: 0, dog: 0, dogOk: 0 });
            f.games++;
            if (x.team === g.fav) { f.fav++; if (x.ok) f.favOk++; } else { f.dog++; if (x.ok) f.dogOk++; }
          }
        });
      });
    });
    var out = { cells: cells, teams: teams, coaches: coaches, fav: favTend };
    lmCache.misc[key] = out;
    return out;
  }

  // A table as a CSV file: the rows on screen, columns as shown; a worked-out
  // column says so in its heading.
  function lmCsv(cols, rows) {
    function q(v) {
      if (v == null) return "";
      // official values are whole numbers and go out as they are; worked-out ones to 4 places
      var t = typeof v === "number" && !Number.isInteger(v) ? String(Math.round(v * 10000) / 10000) : String(v);
      return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
    }
    var head = cols.map(function (c) { return q(c.label + (c.derived ? " (calculated)" : "")); }).join(",");
    return [head].concat(rows.map(function (r) { return cols.map(function (c) { return q(c.csv ? c.csv(r) : c.get(r)); }).join(","); })).join("\r\n") + "\r\n";
  }
  function lmDownload(name, text, type) {
    try {
      var blob = new Blob([text], { type: type || "text/csv;charset=utf-8" });
      var a = el("a", { href: URL.createObjectURL(blob), download: name });
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      return true;
    } catch (e) { return false; }
  }
  // A short, stable fingerprint of a recap's facts, so a viewer can tell the
  // figures behind a finished week's recap have not changed.
  function lmHash(text) {
    var h = 2166136261;
    for (var i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return ("00000000" + h.toString(16)).slice(-8);
  }
