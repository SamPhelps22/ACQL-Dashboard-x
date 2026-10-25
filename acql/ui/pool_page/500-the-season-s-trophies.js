  // ---- the season's trophies -------------------------------------------------------------
  // Worked out from the weekly scores alone, so the same rules give a past
  // season's trophies from the History archive. A tie shares the trophy.
  var TROPHIES = [
    { id: "weeks", icon: "🏆", title: "Week winner", about: "Most weeks won" },
    { id: "best", icon: "🎯", title: "Best week", about: "The season’s highest score in a week" },
    { id: "streak", icon: "🔥", title: "Hot streak", about: "Most weeks in a row above the pool’s average" },
    { id: "steady", icon: "🧱", title: "Steady hand", about: "Most weeks above the pool’s average" },
    { id: "climb", icon: "🚀", title: "Comeback", about: "Most places climbed in one week" },
    { id: "loser", icon: "💣", title: "Big Loser king", about: "Most Big Loser points" },
    { id: "survivor", icon: "🛡️", title: "Survivor", about: "Longest run in the suicide pool" },
    { id: "spoon", icon: "🥄", title: "Wooden spoon", about: "Most weeks with the pool’s low score" }
  ];
  function seasonAwards(s) {
    var weeks = (s.weeks || []).slice().sort(function (a, b) { return a.week - b.week; });
    var people = (s.standings || []).filter(function (x) { return x && x.name; });
    if (weeks.length < 2 || people.length < 2) return [];
    function score(x, w) { var v = (x.weekly || {})[String(w.week)]; return v == null ? null : Number(v); }
    function average(w) {
      if (w.average != null) return w.average;
      var v = people.map(function (x) { return score(x, w); }).filter(function (v) { return v != null; });
      return v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : null;
    }
    var stat = {};
    people.forEach(function (x) { stat[x.name] = { weeks: 0, best: null, bestWeek: null, run: 0, streak: 0, above: 0, climb: 0, climbWeek: null, spoon: 0, total: 0 }; });
    var placeBefore = null;
    weeks.forEach(function (w) {
      var avg = average(w), lows = [], low = null;
      people.forEach(function (x) {
        var v = score(x, w), r = stat[x.name];
        if ((w.winners || []).indexOf(x.name) >= 0) r.weeks++;
        if (v == null) { r.run = 0; return; }
        r.total += v;
        if (r.best == null || v > r.best) { r.best = v; r.bestWeek = w.week; }
        if (avg != null && v > avg) { r.above++; r.run++; r.streak = Math.max(r.streak, r.run); } else r.run = 0;
        if (low == null || v < low) { low = v; lows = [x.name]; } else if (v === low) lows.push(x.name);
      });
      if (lows.length && lows.length <= 3) lows.forEach(function (n) { stat[n].spoon++; });
      var place = {};
      people.forEach(function (x) { place[x.name] = 1 + people.filter(function (y) { return stat[y.name].total > stat[x.name].total; }).length; });
      if (placeBefore) people.forEach(function (x) {
        var up = placeBefore[x.name] - place[x.name];
        if (up > stat[x.name].climb) { stat[x.name].climb = up; stat[x.name].climbWeek = w.week; }
      });
      placeBefore = place;
    });
    var last = weeks[weeks.length - 1].week;
    people.forEach(function (x) {
      stat[x.name].loser = Number(x.big_loser) || 0;
      stat[x.name].survivor = x.suicide_alive ? (s.through_week || last) : x.suicide_out ? x.suicide_out - 1 : 0;
    });
    function top(field, words, least) {
      var best = null, who = [];
      people.forEach(function (x) {
        var v = stat[x.name][field];
        if (v == null || v < (least || 1)) return;
        if (best == null || v > best) { best = v; who = [x.name]; } else if (v === best) who.push(x.name);
      });
      // a "trophy" shared by half the pool is nobody's
      if (best == null || who.length > Math.max(3, people.length / 4)) return null;
      return { value: best, who: who, text: words(best, who) };
    }
    function one(who, key) { return who.length === 1 ? stat[who[0]][key] : null; }
    var found = {
      weeks: top("weeks", function (v) { return plural(v, "week") + " won"; }),
      best: top("best", function (v, who) { var wk = one(who, "bestWeek"); return plural(v, "win") + (wk ? " in week " + wk : ""); }),
      streak: top("streak", function (v) { return plural(v, "week") + " in a row"; }, 2),
      steady: top("above", function (v) { return v + " of " + plural(weeks.length, "week"); }),
      climb: top("climb", function (v, who) { var wk = one(who, "climbWeek"); return "up " + plural(v, "place") + (wk ? " in week " + wk : ""); }, 2),
      loser: top("loser", function (v) { return plural(v, "point"); }),
      survivor: top("survivor", function (v) { return plural(v, "week") + " alive"; }),
      spoon: top("spoon", function (v) { return plural(v, "low score"); }, 2)
    };
    return TROPHIES.map(function (t) { return found[t.id] ? Object.assign({ year: s.year, current: !!s.current }, t, found[t.id]) : null; }).filter(Boolean);
  }
  // the trophies' emoji, drawn in the site's own line icons
  var TROPHY_ICONS = { "🏆": "history", "🎯": "target", "🔥": "flame", "🧱": "steady", "🚀": "climb",
    "💣": "drop", "🛡️": "shield", "🥄": "spoon", "👑": "crown" };
  function trophyIcon(e) {
    var n = TROPHY_ICONS[e];
    return n ? el("span", { class: "ic drawn", "aria-hidden": "true" }, [icon(n)]) : el("span", { class: "ic", "aria-hidden": "true", text: e });
  }
  function trophyCard(a) {
    return el("div", { class: "trophy" + (a.who.some(isMe) ? " mine" : "") }, [
      trophyIcon(a.icon),
      el("div", {}, [el("b", { text: a.title }), el("span", { class: "who" }, a.who.slice(0, 4).map(function (n, i) {
        return [i ? ", " : "", player(n) ? who(n) : n];
      }).reduce(function (x, y) { return x.concat(y); }, []).concat(a.who.length > 4 ? [" +" + (a.who.length - 4) + " more"] : [])),
        el("span", { class: "note", text: a.text + " · " + firstLower(a.about) })])
    ]);
  }
  function awardsView() {
    loadHistory();
    var now = seasonAwards(thisSeason());
    var past = allSeasons().filter(function (s) { return !s.current; });
    var kids = [
      el("div", { class: "pagehead" }, [el("h1", { text: "Awards" })]),
      el("p", { class: "lede", text: "The season’s trophies so far, worked out from every week’s scores. A tie shares the trophy. Each finished season keeps its own in History." }),
      module(seasonYear() + " so far", DATA.through_week ? "after week " + DATA.through_week : null,
        now.length ? [el("div", { class: "trophies" }, now.map(trophyCard))] : [el("p", { class: "note", text: "Trophies start once two weeks are done." })],
        { "data-card": "trophies" })
    ];
    past.forEach(function (s) {
      var list = seasonAwards(s);
      if (list.length) kids.push(fold("awards-" + s.year, s.year + " · " + plural(list.length, "trophy", "trophies"),
        [el("div", { class: "trophies" }, list.map(trophyCard))]));
    });
    if (historyBusy) kids.push(el("p", { class: "note", text: "Fetching past seasons…" }));
    return el("div", { class: "view", "data-view": "awards" }, kids);
  }
  // A coach's trophy shelf: what they hold this season and won in past ones, and their titles.
  function trophyShelf(p) {
    loadHistory();
    var mine = trophiesOf(p.name);
    var champs = championsByYear(allSeasons()), titles = Object.keys(champs).filter(function (y) {
      return splitNames(champs[y].names).indexOf(p.name) >= 0;
    }).sort().reverse();
    var kids = titles.map(function (y) {
      return el("div", { class: "trophy title" }, [trophyIcon("👑"),
        el("div", {}, [el("b", { text: "Champion " + y }), el("span", { class: "note", text: champs[y].note || "Won the season" })])]);
    }).concat(mine.map(function (a) {
      return el("div", { class: "trophy" }, [trophyIcon(a.icon),
        el("div", {}, [el("b", { text: a.title + (a.current ? "" : " " + a.year) }),
          el("span", { class: "note", text: a.text + (a.who.length > 1 ? ", shared" : "") + (a.current ? " · holds it so far" : "") })])]);
    }));
    return module("Trophy shelf", kids.length ? plural(kids.length, "trophy", "trophies") : null,
      kids.length ? [el("div", { class: "trophies shelf" }, kids), moreLink("Every award", "awards")]
        : [el("p", { class: "note", text: "Nothing on the shelf yet. " + (DATA.weeks.length < 2 ? "Trophies start once two weeks are done." : "There’s a season of them to win.") }),
          moreLink("The awards", "awards")],
      { "data-card": "trophies-for" });
  }
  // Every trophy one coach holds, this season and in the archive.
  function trophiesOf(name) {
    var out = [];
    allSeasons().forEach(function (s) {
      seasonAwards(s).forEach(function (a) { if (a.who.indexOf(name) >= 0) out.push(a); });
    });
    return out;
  }

