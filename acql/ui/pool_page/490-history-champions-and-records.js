  // ---- history: champions and records ------------------------------------------------------
  // Past seasons live in their own file beside the page, fetched only when
  // someone opens History - it grows every year and nobody needs it on the
  // way to the standings. This season comes from the page itself.
  var historyData = null, historyBusy = false, historyError = "";
  function loadHistory() {
    if (historyData || historyBusy) return;
    if (DATA.history) { historyData = DATA.history; return; }
    if (!DATA.history_url) { historyData = { champions: [], seasons: [] }; return; }
    historyBusy = true;
    fetch(DATA.history_url, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.json();
    }).then(function (d) {
      historyData = d && typeof d === "object" ? d : { champions: [], seasons: [] };
    }).catch(function () {
      historyError = "The history file couldn’t be loaded - check the connection. This season’s records are below.";
      historyData = { champions: [], seasons: [] };
    }).then(function () {
      historyBusy = false;
      // History, Awards and a coach's trophy shelf all draw from the archive
      if (state.coach || ["history", "awards", "me"].indexOf(state.view) >= 0) render({ quiet: true });
    });
  }
  function thisSeason() {
    var weeksIn = (DATA.race || {}).season_weeks || 18;
    return {
      year: seasonYear(), current: true, through_week: DATA.through_week, season_weeks: weeksIn,
      complete: DATA.through_week >= weeksIn, entrants: DATA.entrants,
      standings: DATA.players.map(function (p) {
        return { name: p.name, place: p.place, wins: p.wins, big_loser: p.big_loser, weeks_won: weeksWon(p.name), net: p.net,
          suicide_out: p.suicide.out, suicide_alive: p.suicide.alive, weekly: p.weekly };
      }),
      weeks: DATA.weeks.map(function (w) { return { week: w.week, top: w.top, winners: w.winners, average: w.average }; })
    };
  }
  function allSeasons() {
    var past = ((historyData && historyData.seasons) || []).filter(function (s) { return s && s.year !== seasonYear(); });
    return [thisSeason()].concat(past).sort(function (a, b) { return b.year - a.year; });
  }
  function championsByYear(seasons) {
    var out = {};
    ((historyData && historyData.champions) || []).forEach(function (c) { out[c.year] = { names: c.names, note: c.note || "" }; });
    seasons.forEach(function (s) {
      if (out[s.year] || !s.complete || !(s.standings || []).length) return;
      var best = Math.max.apply(null, s.standings.map(function (x) { return x.wins; }));
      out[s.year] = { names: listNames(s.standings.filter(function (x) { return x.wins === best; }).map(function (x) { return x.name; }), 3),
        note: plural(best, "win") };
    });
    return out;
  }
  function splitNames(text) { return String(text || "").split(/\s*(?:&|,| and )\s*/).filter(Boolean); }

  // The league's records, across every season the site knows.
  function records(seasons) {
    var out = [];
    function season(s) { return s.current ? s.year + ", so far" : String(s.year); }
    var bestWeek = null, margin = null;
    seasons.forEach(function (s) {
      (s.weeks || []).forEach(function (w) {
        if (!bestWeek || w.top > bestWeek.top) bestWeek = { top: w.top, who: w.winners, at: "week " + w.week + ", " + season(s), more: 0 };
        else if (w.top === bestWeek.top) bestWeek.more++;
        var scores = (s.standings || []).map(function (x) { return (x.weekly || {})[String(w.week)]; }).filter(function (v) { return v != null; });
        var below = scores.filter(function (v) { return v < w.top; });
        if (w.winners.length === 1 && below.length) {
          var by = w.top - Math.max.apply(null, below);
          if (!margin || by > margin.by) margin = { by: by, who: w.winners, at: "week " + w.week + ", " + season(s) };
        }
      });
    });
    if (bestWeek) out.push({ k: "Best week", v: plural(bestWeek.top, "win"), w: listNames(bestWeek.who, 2), d: bestWeek.at + (bestWeek.more ? " (and " + plural(bestWeek.more, "other time") + ")" : "") });
    if (margin) out.push({ k: "Biggest win of a week", v: "by " + margin.by, w: listNames(margin.who, 2), d: margin.at });
    function seasonBest(field, label, fmt) {
      var best = null;
      seasons.forEach(function (s) {
        (s.standings || []).forEach(function (x) {
          var v = x[field];
          if (v == null) return;
          if (!best || v > best.v) best = { v: v, who: [x.name], at: season(s) };
          else if (v === best.v && best.who.indexOf(x.name) < 0) best.who.push(x.name);
        });
      });
      if (best && best.v > 0) out.push({ k: label, v: fmt(best.v), w: listNames(best.who, 2), d: best.at });
    }
    seasonBest("wins", "Most wins in a season", function (v) { return String(v); });
    seasonBest("weeks_won", "Most weeks won in a season", function (v) { return String(v); });
    seasonBest("big_loser", "Most Big Loser points in a season", function (v) { return String(v); });
    var run = null;
    seasons.forEach(function (s) {
      (s.standings || []).forEach(function (x) {
        var weeks = x.suicide_alive ? s.through_week : x.suicide_out ? x.suicide_out - 1 : 0;
        if (!weeks) return;
        if (!run || weeks > run.v) run = { v: weeks, who: [x.name], at: season(s), alive: x.suicide_alive && !s.complete };
        else if (weeks === run.v && run.who.indexOf(x.name) < 0) run.who.push(x.name);
      });
    });
    if (run) out.push({ k: "Longest suicide run", v: plural(run.v, "week"), w: listNames(run.who, 2), d: run.at + (run.alive ? ", still going" : "") });
    var titles = {};
    var champs = championsByYear(seasons);
    Object.keys(champs).forEach(function (y) { splitNames(champs[y].names).forEach(function (n) { titles[n] = (titles[n] || 0) + 1; }); });
    var most = Object.keys(titles).sort(function (a, b) { return titles[b] - titles[a]; });
    if (most.length && titles[most[0]] > 1) {
      var top = titles[most[0]];
      out.push({ k: "Most titles", v: String(top), w: listNames(most.filter(function (n) { return titles[n] === top; }), 3), d: "of " + plural(Object.keys(champs).length, "season") + " on record" });
    }
    return out;
  }
  function historyView() {
    loadHistory();
    var seasons = allSeasons();
    var champs = championsByYear(seasons);
    var current = seasons.filter(function (s) { return s.current; })[0];
    var lead = leaders().map(function (p) { return p.name; });
    var rows = [];
    if (current && !current.complete) {
      rows.push(el("div", { class: "season-row now" }, [el("span", { class: "yr", text: String(current.year) }),
        el("span", { class: "champ", text: listNames(lead, 2) + (lead.length > 1 ? " lead" : " leads") }),
        el("span", { class: "what", text: "After week " + current.through_week + " of " + current.season_weeks + ", with " + plural(DATA.players.length ? DATA.players[0].wins : 0, "win") + "." })]));
    }
    Object.keys(champs).map(Number).sort(function (a, b) { return b - a; }).forEach(function (y) {
      var c = champs[y];
      var s = seasons.filter(function (x) { return x.year === y; })[0];
      rows.push(el("div", { class: "season-row" }, [el("span", { class: "yr", text: String(y) }),
        el("span", { class: "champ", text: c.names }),
        el("span", { class: "what", text: [c.note, s && s.entrants ? s.entrants + " coaches" : ""].filter(Boolean).join(" · ") || "Champion" })]));
    });
    var recs = records(seasons);
    var past = seasons.filter(function (s) { return !s.current; });
    var kids = [
      el("div", { class: "pagehead" }, [el("h1", { text: "History" })]),
      el("p", { class: "lede", text: "The league’s champions, its records, and every season the site has kept." }),
      historyBusy ? el("p", { class: "note", text: "Fetching past seasons…" }) : null,
      historyError ? stateMsg("Past seasons unavailable", historyError,
        { text: "Try again", go: function () { historyError = ""; historyData = null; loadHistory(); render({ quiet: true }); } }, "bad") : null,
      el("div", { class: "cols" }, [
        el("div", {}, [module("Champions", null, [el("div", { class: "timeline" }, rows),
          Object.keys(champs).length ? null : el("p", { class: "note", text: "Past champions show here once they’re added in the dashboard (Results › ⚙). Each season the dashboard publishes is kept too." })],
          { "data-card": "champions" })]),
        el("div", {}, [module("Records", past.length ? "across " + plural(past.length + 1, "season") : "this season so far",
          recs.length ? [el("div", { class: "records" }, recs.map(function (r) {
            return el("div", { class: "record" }, [el("span", { class: "k", text: r.k }), el("span", { class: "v", text: r.v }),
              el("span", { class: "w", text: r.w }), el("span", { class: "d", text: r.d })]);
          }))] : [el("p", { class: "note", text: "Records start once a week is done." })], { "data-card": "records" })])
      ])
    ];
    if (past.length) kids.push(allTimeModule(seasons, champs));
    else kids.push(el("p", { class: "note", text: "All-time standings start with the next season: the dashboard keeps each season as it publishes, and this one joins the history when it’s done." }));
    return el("div", { class: "view", "data-view": "history" }, kids);
  }
  function allTimeModule(seasons, champs) {
    var by = {};
    seasons.forEach(function (s) {
      (s.standings || []).forEach(function (x) {
        var r = by[x.name] = by[x.name] || { name: x.name, seasons: 0, wins: 0, weeks: 0, best: null, titles: 0 };
        r.seasons++;
        r.wins += x.wins || 0;
        r.weeks += x.weeks_won || 0;
        if (x.place != null && (r.best == null || x.place < r.best)) r.best = x.place;
      });
    });
    Object.keys(champs).forEach(function (y) { splitNames(champs[y].names).forEach(function (n) { if (by[n]) by[n].titles++; }); });
    var list = Object.keys(by).map(function (k) { return by[k]; }).sort(function (a, b) { return b.titles - a.titles || b.wins - a.wins || a.name.localeCompare(b.name); });
    return module("All-time", plural(seasons.length, "season"), [scroller(el("table", { id: "all-time" }, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Coach" }), el("th", { class: "n", text: "Titles" }), el("th", { class: "n", text: "Seasons" }),
        el("th", { class: "n", text: "Wins" }), el("th", { class: "n", text: "Weeks won" }), el("th", { class: "n", text: "Best finish" })])]),
      el("tbody", {}, list.map(function (r) {
        return el("tr", { class: isMe(r.name) ? "me" : null }, [el("td", { class: "coach" }, [player(r.name) ? who(r.name) : r.name]),
          el("td", { class: "n num", text: r.titles ? String(r.titles) : "–" }), el("td", { class: "n num", text: String(r.seasons) }),
          el("td", { class: "n num", text: String(r.wins) }), el("td", { class: "n num", text: String(r.weeks) }),
          el("td", { class: "n num", text: r.best != null ? ordinal(r.best) : "–" })]);
      }))
    ])), el("p", { class: "note", text: "Includes this season so far. Names are matched exactly as each season’s sheet wrote them." })], { "data-card": "all-time" });
  }

