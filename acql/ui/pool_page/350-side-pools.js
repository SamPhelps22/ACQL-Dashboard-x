  // ---- side pools --------------------------------------------------------------------
  function poolsView() {
    var alive = aliveNames().sort(function (a, b) { return a.localeCompare(b); });
    var out = {};
    DATA.players.forEach(function (p) {
      var s = p.suicide;
      if (!s.alive && s.out) {
        var team = s.picks[String(s.out)] || "";
        var key = s.out + "|" + team;
        (out[key] = out[key] || { week: s.out, team: team, names: [] }).names.push(p.name);
      }
    });
    var groups = Object.keys(out).map(function (k) { return out[k]; })
      .sort(function (a, b) { return b.week - a.week || b.names.length - a.names.length || a.team.localeCompare(b.team); });
    var bl = DATA.players.filter(function (p) { return p.big_loser; })
      .sort(function (a, b) { return b.big_loser - a.big_loser || a.name.localeCompare(b.name); });
    var blTop = bl.length ? bl[0].big_loser : 0;
    var shown = bl.slice(0, 15);
    var mine = bl.filter(function (p) { return isMe(p.name); })[0];
    if (mine && shown.indexOf(mine) < 0) shown.push(mine);
    function nameList(list) {
      var sorted = list.slice().sort(function (a, b) { return a.localeCompare(b); });
      var bits = [];
      sorted.forEach(function (n, i) {
        if (i) bits.push(", ");
        bits.push(isMe(n) ? el("mark", {}, [who(n)]) : who(n));
      });
      return bits;
    }
    // The week being played comes first, followed live.
    var L = DATA.live, thisWeek = [];
    if (hasLive() && L.coaches && L.coaches.length) {
      if (!live.fetched && !live.error && !live.busy) fetchScores();
      var t = liveTally();
      var cards = twoUp([weekSuicideCard(t), weekLosersCard(t)]);
      if (cards) thisWeek = [el("div", { class: "pagehead" }, [el("h1", { text: "Week " + L.week + " side pools" }), liveStatus(t)]), cards,
        el("h2", { text: "The season", style: "font-size:32px" })];
    }
    return el("div", { class: "view", "data-view": "pools" }, (thisWeek.length ? thisWeek : [el("div", { class: "pagehead" }, [el("h1", { text: "Side pools" })])]).concat([
      el("div", { class: "cols even" }, [
        module("Suicide pool", alive.length + " still in", [
          ruleLink("suicide-survive", "Suicide pool rules"),
          alive.length && alive.length <= 3 ? el("div", { class: "survivor" }, [
            el("span", { class: "k", text: alive.length === 1 ? "Last one standing" : "The last " + numberWord(alive.length) + " standing" }),
            el("div", { class: "names" }, alive.map(function (n) { return el("b", { class: isMe(n) ? "me" : null }, [who(n)]); }))
          ]) : alive.length ? el("div", { class: "chips" }, alive.map(function (n) { return el("span", { class: "chip alive" + (isMe(n) ? " me" : "") }, [who(n)]); }))
            : el("p", { class: "note", text: "Nobody is left standing." }),
          groups.length ? el("div", { class: "grave" }, [el("b", { text: "Knocked out" })].concat(groups.map(function (g, i) {
            return el("div", { class: "grave-row" }, [
              el("span", { class: "when", text: i && groups[i - 1].week === g.week ? "" : "Week " + g.week }),
              el("span", { class: "who" }, [g.team ? el("b", { text: g.team + ": " }) : null].concat(nameList(g.names)))
            ]);
          }))) : null,
          el("p", { class: "note", text: "In a lined game your team has to be credited with the game: a favourite must win by at least the line." })
        ], { "data-card": "suicide-season" }),
        module("Big Loser", "points so far", [
          bl.length ? el("div", { class: "box" }, [el("table", {}, [el("tbody", {}, shown.map(function (p) {
            return el("tr", { class: isMe(p.name) ? "me" : null }, [
              el("td", { class: "coach" }, [who(p.name)]),
              el("td", { class: "n total num", text: String(p.big_loser) }),
              el("td", { class: "bar-cell" }, [bar(p.big_loser, blTop)])
            ]);
          }))])]) : stateMsg("No Big Loser points yet", "A point goes to each pick whose team loses by 15 or more."),
          bl.length > shown.length ? el("p", { class: "note", text: "and " + plural(bl.length - shown.length, "more coach", "more coaches") + " on the board" }) : null,
          el("p", { class: "note", text: "Three picks a week, a point each when the team loses by 15 or more." })
        ], { "data-card": "losers-season" })
      ]),
      survivorWall(),
      suicideBoard()
    ]));
  }

  // The survivor wall: every coach's suicide picks as a row of logos, week by week -
  // the knocked-out greyed, the losing pick crossed, this week's pick dashed.
  function suicideLogo(team) {
    var code = codeOf(team);
    if (!code) return el("span", { class: "tb", text: String(team || "?").slice(0, 3).toUpperCase() });
    var img = document.createElement("img");
    img.alt = teamFull(code);
    img.title = teamFull(code);
    img.loading = "lazy";
    img.decoding = "async";
    img.src = logoUrl(code);
    var holder = el("span", {}, [img]);
    img.onerror = function () { holder.textContent = ""; holder.appendChild(badge(code)); };
    return holder;
  }
  function survivorWall() {
    // Past pools (the suicide pool started again after someone won it) can
    // be looked back at; the one being played is shown first.
    var past = DATA.suicide_rounds || [];
    var round = state.wallPool ? past.filter(function (r) { return r.pool === state.wallPool; })[0] : null;
    var poolNow = past.length + 1;
    var chooser = past.length ? el("div", { class: "weeks", role: "group", "aria-label": "Choose a suicide pool" },
      [el("button", { type: "button", "aria-pressed": round ? "false" : "true",
        onclick: function () { state.wallPool = 0; render(); }, text: "Pool #" + poolNow + " (now)" })].concat(
      past.slice().reverse().map(function (r) {
        return el("button", { type: "button", "aria-pressed": round === r ? "true" : "false",
          onclick: function () { state.wallPool = r.pool; render(); }, text: "Pool #" + r.pool });
      }))) : null;
    var weeks = seasonWeeks();
    var rows = DATA.players.filter(function (p) { return Object.keys(p.suicide.picks || {}).length || p.suicide.out; });
    if (round) {
      weeks = weeks.filter(function (n) { return n >= round.start && n <= round.end; });
      rows = round.coaches.map(function (c) { return { name: c.name, suicide: { picks: c.picks, out: c.out, alive: c.alive } }; });
    }
    if (!round && past.length) {
      // the round being played starts where the last one ended
      var from = past[past.length - 1].end + 1;
      weeks = weeks.filter(function (n) { return n >= from; });
    }
    // With the chooser the earlier round has its own view; without it, its
    // weeks are shown faded before the restart.
    var restart = round || past.length ? 0 : (DATA.suicide_round_start || 0);
    var champs = restart ? (DATA.suicide_winners || []) : [];
    if (restart) rows = DATA.players.filter(function (p) {
      return Object.keys(p.suicide.picks || {}).length || p.suicide.out || Object.keys(p.suicide.before || {}).length;
    });
    if (!weeks.length || !rows.length) return null;
    var liveSui = {};
    var liveWeek = !round && hasLive() && DATA.live.coaches ? DATA.live.week : null;
    if (liveWeek) DATA.live.coaches.forEach(function (c) { if (c.sui) liveSui[c.name] = c.sui; });
    var cols = weeks.slice();
    if (liveWeek && cols.indexOf(liveWeek) < 0 && Object.keys(liveSui).length) cols.push(liveWeek);
    rows.sort(function (a, b) {
      return (b.suicide.alive - a.suicide.alive) || ((b.suicide.out || 0) - (a.suicide.out || 0)) || a.name.localeCompare(b.name);
    });
    var standing = rows.filter(function (p) { return p.suicide.alive; }).length;
    var body = rows.map(function (p, i) {
      var s = p.suicide, gone = false, goneBefore = false;
      var cells = cols.map(function (n) {
        if (restart && n < restart) {
          var old = (s.before || {})[String(n)];
          var won = champs.indexOf(p.name) >= 0 && n === restart - 1;
          if (goneBefore || !old) return el("td", { class: "past" }, [el("span", { class: "cell gone" })]);
          var out = s.before_out === n;
          if (out) goneBefore = true;
          return el("td", { class: "past" }, [el("span", { class: "cell" + (out ? " lost" : "") + (won ? " won" : ""),
            title: "Week " + n + ": " + teamFull(codeOf(old)) + (out ? " – knocked out" : won ? " – won the round" : "") }, [suicideLogo(old)])]);
        }
        var team = (s.picks || {})[String(n)];
        var now = !team && n === liveWeek && s.alive ? liveSui[p.name] : null;
        if (gone || (!team && !now)) return el("td", { class: n === restart ? "reset" : null }, [el("span", { class: "cell gone" })]);
        var lost = s.out === n;
        if (lost) gone = true;
        return el("td", { class: n === restart ? "reset" : null }, [el("span", { class: "cell" + (lost ? " lost" : "") + (now ? " now" : ""),
          title: "Week " + n + ": " + teamFull(codeOf(team || now)) + (lost ? " – knocked out" : now ? " – being played" : "") }, [suicideLogo(team || now)])]);
      });
      var cls = [s.alive ? "" : "out", isMe(p.name) ? "me" : "", i && i === standing ? "cut" : ""].filter(Boolean).join(" ");
      return el("tr", { class: cls || null }, [el("td", { class: "coach" }, [who(p.name)])].concat(cells));
    });
    var aside = round ? "weeks " + round.start + "–" + round.end + (round.winners.length ? " · won by " + round.winners.join(" & ") : "")
      : standing + " of " + rows.length + " still standing";
    return module("Survivor wall", aside, [
      chooser,
      el("div", { class: "swall" }, [el("table", {}, [
        el("thead", {}, [el("tr", {}, [el("th", { class: "coach", text: "Coach" })].concat(cols.map(function (n) {
          return el("th", { class: restart && n < restart ? "past" : n === restart ? "reset" : null, text: "Wk " + n });
        })))]),
        el("tbody", {}, body)])]),
      el("p", { class: "note", text: "Every pick so far, a logo a week. A crossed logo is the pick that knocked a coach out" +
        (Object.keys(liveSui).length ? "; a dashed one is this week’s pick, still being played." : ".") +
        (restart ? " Faded weeks are the earlier round" + (champs.length ? ", won by " + champs.join(" & ") : "") +
          "; the pool started again in week " + restart + "." : "") })
    ], { "data-card": "survivor-wall" });
  }

  // The suicide board: what each coach still standing has left to use.
  var TOP_TEAMS = 10, THIN = 5;
  function suicideBoard() {
    var teams = DATA.teams || {};
    var codes = Object.keys(teams);
    var alive = DATA.players.filter(function (p) { return p.suicide.alive && p.suicide.used; });
    if (!codes.length || !alive.length) return null;
    var rank = DATA.team_rank || {};
    var ranked = Object.keys(rank).length >= 28;
    function strong(c) { return ranked && rank[c] <= TOP_TEAMS; }
    var liveSui = {};
    if (DATA.live && DATA.live.coaches) DATA.live.coaches.forEach(function (c) { if (c.sui) liveSui[c.name] = c.sui; });
    var rows = alive.map(function (p) {
      var used = p.suicide.used;
      var left = codes.filter(function (c) { return used.indexOf(c) < 0; });
      return { p: p, left: left, top: left.filter(strong).length };
    }).sort(function (a, b) {
      return (ranked ? a.top - b.top : 0) || a.left.length - b.left.length || a.p.name.localeCompare(b.p.name);
    });
    var count_ = {};
    DATA.players.forEach(function (p) { (p.suicide.used || []).forEach(function (c) { count_[c] = (count_[c] || 0) + 1; }); });
    var popular = Object.keys(count_).sort(function (a, b) { return count_[b] - count_[a] || teams[a].localeCompare(teams[b]); }).slice(0, 4);
    var cards = rows.map(function (r) {
      var p = r.p;
      var weeks = Object.keys(p.suicide.picks).map(Number).sort(function (a, b) { return a - b; });
      var usedFull = weeks.map(function (n) { return "Week " + n + ": " + p.suicide.picks[String(n)]; }).join("\n");
      var now = liveSui[p.name];
      return el("div", { class: "scard" + (isMe(p.name) ? " me" : "") }, [
        el("div", { class: "top" }, [who(p.name), el("span", { class: "note", text: r.left.length + " left" })]),
        el("span", { class: "small", title: usedFull }, p.suicide.used.length ? ["Used: "].concat(p.suicide.used.map(function (c, i) {
          return el("span", { style: "margin-right:3px" }, [badge(c)]);
        })) : ["Nothing used yet"]),
        ranked ? el("span", { class: "small" + (r.top <= THIN ? " thin" : "") },
          [r.top + " of the top " + TOP_TEAMS + " left" + (r.top <= THIN ? " – running thin" : "")]) : null,
        now && teams[now] ? el("span", { class: "small" }, ["Week " + DATA.live.week + ": ", badge(now), " " + teams[now]]) : null,
        fold("left:" + p.name, "Teams left", [el("div", { class: "chips" }, r.left.slice().sort(function (a, b) {
          return teams[a].localeCompare(teams[b]);
        }).map(function (c) { return el("span", { class: "chip" + (strong(c) ? " strong" : ""), text: teams[c] }); }))])
      ]);
    });
    return module("Suicide board", "teams each survivor has left", [
      popular.length ? el("p", { class: "race-sum", text: "Most used so far: " + popular.map(function (c) { return teams[c] + " (" + count_[c] + ")"; }).join(", ") + "." }) : null,
      el("div", { class: "sboard" }, cards),
      el("p", { class: "note", text: "Each team can be used once a season." + (ranked
        ? " Top " + TOP_TEAMS + " is the ten best teams by this season’s betting lines, shown in bold under Teams left. The coach with fewest left comes first."
        : " Fewest teams left comes first.") })
    ], { "data-card": "board" });
  }

