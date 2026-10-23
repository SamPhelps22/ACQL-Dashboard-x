  // ---- the week's story, from its numbers ---------------------------------------------
  function secondBest(w) {
    var below = w.scores.map(function (s) { return s.total; }).filter(function (v) { return v < w.top; });
    return below.length ? Math.max.apply(null, below) : null;
  }
  // The most a card could score that week (games plus Big Loser picks), from the official sheet.
  function weekMost(w) { return w && w.most > 0 ? w.most : null; }
  function headline(w) {
    var n = w.winners, second = secondBest(w), gap = second == null ? 0 : w.top - second;
    if (n.length === 1) {
      if (w.top === w.games) return n[0] + " runs the table in week " + w.week;
      if (gap >= 3) return n[0] + " runs away with week " + w.week;
      if (gap === 1) return n[0] + " edges out week " + w.week;
      return n[0] + " takes week " + w.week;
    }
    if (n.length === 2) return n[0] + " and " + n[1] + " split week " + w.week;
    return cap((WORDS[n.length] || n.length) + "-way split of week " + w.week);
  }
  function isTie(u) { return /^tie$/i.test(String(u.winner || "").trim()); }
  function story(w) {
    var bits = [];
    var second = secondBest(w);
    var runners = second == null ? [] : w.scores.filter(function (s) { return s.total === second; }).map(function (s) { return s.name; });
    if (w.winners.length === 1 && second != null) {
      bits.push(w.top + " of " + w.games + " was enough, " + (w.top - second === 1 ? "one game ahead of " : numberWord(w.top - second) + " games ahead of ") + listNames(runners, 2) + ".");
    } else if (w.winners.length > 1) {
      bits.push("All on " + w.top + " of " + w.games + ".");
    }
    if (w.payout_each) bits.push(money(w.payout_each) + (w.winners.length > 1 ? " each." : " to the winner."));
    var u = (w.upsets || [])[0];
    if (u) {
      var who = u.right ? "only " + u.right + " of " + u.entrants + " saw it coming" : "nobody saw it coming";
      bits.push(isTie(u) ? "The " + u.matchup + " tie wrecked cards; " + who + "." : u.winner + " was the killer; " + who + ".");
    }
    return bits.join(" ");
  }
  // The rest of the week, for the home banner: how it was won, how the games
  // went, who went home. Each line only when the week has the facts for it.
  function weekTold(w) {
    var bits = [];
    var lc = function (s) { return s ? s.charAt(0).toLowerCase() + s.slice(1) : s; };
    var beat = function (kind) { return (w.beats || []).filter(function (b) { return b.kind === kind; })[0]; };
    var dec = beat("decider"), bad = beat("bad-beat");
    if (dec) bits.push(dec.who + " was " + lc(dec.detail).replace(/\.?$/, "."));
    if (bad && (!dec || bad.who !== dec.who)) bits.push(bad.who + " was " + lc(bad.detail).replace(/\.?$/, "."));
    var climb = (w.awards || []).filter(function (a) { return a.title === "Biggest climber"; })[0];
    if (climb) bits.push(climb.who + " moved " + climb.detail + ".");
    var c = w.chaos;
    if (c && c.upsets != null) {
      bits.push(cap(plural(c.upsets, "upset")) + " against " + c.expected.toFixed(1) + " expected" +
        (c.label ? ", a " + c.label.toLowerCase() + " week" : "") + (c.biggest ? "; the biggest was " + c.biggest + "." : "."));
    }
    var res = (w.results || []).filter(function (g) { return g.right != null; });
    if (res.length) {
      var best = res.reduce(function (a, g) { return g.right > a.right ? g : a; });
      bits.push("Best-called game: " + best.winner + " over " + best.loser + ", " + best.right + " of " + w.entrants + " had it.");
    }
    if (w.scores && w.scores.length) {
      var low = Math.min.apply(null, w.scores.map(function (s) { return s.total; }));
      var lows = w.scores.filter(function (s) { return s.total === low; }).length;
      bits.push("Low card was " + low + (lows > 1 ? ", shared by " + lows + " coaches." : "."));
    }
    var sp = w.suicide;
    if (sp && sp.killed && sp.killer) {
      bits.push(sp.killer + " knocked " + plural(sp.killed, "coach", "coaches") + " out of the suicide pool" +
        (sp.left != null ? ", " + (sp.left === 1 ? "one left standing." : sp.left + " left standing.") : "."));
    }
    return bits.join(" ");
  }
  // How many coaches went out of the suicide pool in a week, whichever team did it.
  function outIn(week) {
    return DATA.players.filter(function (p) { return p.suicide.out === week; }).length;
  }
  // The coach (or coaches) with the most Big Loser points this week.
  function bigLoser(w) {
    var best = w.scores.reduce(function (a, s) { return Math.max(a, s.big_loser || 0); }, 0);
    if (!best) return null;
    return { pts: best, names: w.scores.filter(function (s) { return (s.big_loser || 0) === best; }).map(function (s) { return s.name; }) };
  }
  // A week's story as the lower third: on the home page the latest week (its
  // headline the page's h1), on Weeks any week.
  function heroRecap(w, onWeeks) {
    var alive = onWeeks && w.suicide && w.suicide.left != null ? w.suicide.left : aliveNames().length;
    var out = outIn(w.week);
    var second = secondBest(w);
    var crowd = w.crowd || {};
    var loser = bigLoser(w);
    var suicideLabel = alive === 1 ? "last one standing in suicide" : "alive in suicide";
    if (out) suicideLabel += " · " + out + " out this week";
    var stats = [
      stat(w.top + "/" + w.games, w.winners.length > 1 ? "winning score" : "winning score · " + w.winners[0], "lead"),
      second != null && w.winners.length === 1
        ? stat("+" + (w.top - second), "margin of victory")
        : stat(String(w.winners.length), "tied at the top"),
      crowd.games ? stat(crowd.right + "–" + (crowd.games - crowd.right), "crowd’s record · avg " + w.average.toFixed(1))
                  : stat(w.average.toFixed(1), "pool average"),
      stat(String(alive), suicideLabel, alive <= 1 ? "alarm" : null)
    ];
    var main = [
      el("span", { class: "kicker" }, [el("span", { text: onWeeks ? "Week " + w.week : "Week " + w.week + " · Final" })]),
      el(onWeeks ? "h2" : "h1", { text: headline(w) }),
      el("p", { class: "deck", text: story(w) })
    ];
    if (loser) main.push(el("p", { class: "hero-foot", text: "Big Loser: " + listNames(loser.names, 2) + ", " + plural(loser.pts, "pt") }));
    return hero("Week " + w.week, main, stats);
  }
  // The banner's top line: hello to the chosen coach, then where the season
  // stands, each part only from what the page knows.
  function welcome(parts) {
    var out = hasMe() ? [el("span", { class: "hello", text: "Welcome back, " + state.me })] : [];
    parts.filter(Boolean).forEach(function (p) { out.push(el("span", { text: (out.length ? "· " : "") + p })); });
    return out;
  }
  function seasonOver() { var R = DATA.race; return !!R && R.season_weeks && DATA.through_week >= R.season_weeks; }
  // "Sunday is underway" while a Sunday game is on; between windows just the week.
  var DAYS = ["Sunday", "Monday night", "Tuesday", "Wednesday", "Thursday night", "Friday", "Saturday"];
  function underway(t, week) {
    var on = t.games.filter(function (x) { return x.state === "in" && x.kick; })[0];
    return on ? DAYS[new Date(on.kick).getDay()] + " is underway" : "Week " + week + " is underway";
  }
  // The lower third: the one loud thing on a page. Its numbers sit in a
  // panel beside the headline on a wide screen, under it on a phone.
  function hero(label, main, stats, cls) {
    return el("section", { class: "hero" + (stats ? " sided" : "") + (cls ? " " + cls : ""), "aria-label": label }, [
      el("div", { class: "hero-main" }, main),
      stats ? el("div", { class: "hero-side" }, [el("div", { class: "stats" }, stats)]) : null]);
  }
  // share (0-1), when given, draws a thin meter under the number: how much of the card it is.
  function stat(value, label, tone, share) {
    var meter = share == null ? null : el("span", { class: "meter", "aria-hidden": "true" },
      [el("i", { style: "width:" + Math.max(0, Math.min(100, share * 100)).toFixed(1) + "%" })]);
    return el("div", { class: "stat" + (tone ? " " + tone : "") }, [el("span", { class: "v", text: value, "data-tick": "h:" + label }), meter, el("span", { class: "k", text: label })]);
  }
  // A sentence with the coaches' names in bold, longest names first so "Jim T" doesn't eat "Jim".
  function boldNames(text, names) {
    var found = names.filter(function (n) { return n && text.indexOf(n) >= 0; }).sort(function (a, b) { return b.length - a.length; });
    if (!found.length) return [document.createTextNode(text)];
    var re = new RegExp("(" + found.map(function (n) { return n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("|") + ")");
    return text.split(re).map(function (part, i) { return i % 2 ? el("b", { text: part }) : document.createTextNode(part); });
  }

