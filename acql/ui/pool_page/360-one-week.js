  // ---- one week ----------------------------------------------------------------------
  function weeksView() {
    var w = weekData(state.week) || weekData(DATA.through_week);
    setTimeout(function () {             // bring the chosen week into view when the row scrolls
      var b = picker.querySelector('[aria-pressed="true"]');
      if (b && picker.isConnected && picker.scrollWidth > picker.clientWidth) picker.scrollLeft = b.offsetLeft - picker.clientWidth / 2;
    }, 0);
    var picker = el("div", { class: "weeks", role: "group", "aria-label": "Choose a week" }, DATA.weeks.map(function (x) {
      return el("button", { type: "button", "aria-pressed": x.week === w.week ? "true" : "false", "aria-label": "Week " + x.week,
        onclick: function () { state.week = x.week; render(); }, text: String(x.week) });
    }));
    var top = w.scores.length ? w.scores[0].total : 0;
    var scores = scroller(el("table", { id: "week-scores" }, [
      el("thead", {}, [el("tr", {}, [el("th", { class: "n", text: "#" }), el("th", { text: "Coach" }),
        el("th", { class: "n", text: "Wins" }), el("th", { class: "n hide-narrow", text: "Picks right" }),
        el("th", { class: "n", text: "Big Loser" }), el("th", { class: "bar-cell hide-narrow", text: "" })])]),
      el("tbody", {}, w.scores.map(function (s) {
        var place = weekPlace(w, s.name);
        var won = w.winners.indexOf(s.name) >= 0;
        return el("tr", { class: isMe(s.name) ? "me" : null }, [
          el("td", { class: "n place num", text: String(place) }),
          el("td", { class: "coach" }, [who(s.name), won ? el("span", { class: "star", text: " ★", title: "Won the week" }) : null]),
          el("td", { class: "n total num", text: String(s.total) }),
          el("td", { class: "n num hide-narrow", text: String(s.regular) }),
          el("td", { class: "n num", text: s.big_loser ? String(s.big_loser) : "–" }),
          el("td", { class: "bar-cell hide-narrow" }, [bar(s.total, top)])
        ]);
      }))
    ]));
    var awards = module("The week’s stories", null, w.awards.length ? [el("div", { class: "awards" }, w.awards.map(function (a) {
      return el("div", { class: "award" }, [a.title ? el("span", { class: "t", text: a.title }) : null,
        el("span", { class: "w", text: a.who }), a.detail ? el("span", { class: "why", text: a.detail }) : null]);
    }))] : [el("p", { class: "note", text: "A quiet week." })], { "data-card": "stories" });
    var upsets = module("The games that sank the pool", null, w.upsets.length ? w.upsets.map(function (u) {
      return el("div", { class: "upset" }, [
        el("span", { class: "game" }, [el("span", { class: "team" }, [badge(u.winner), el("span", { text: u.matchup })])]),
        el("span", { class: "had num", text: u.right + " of " + u.entrants + " had it" }),
        shareBar(u.right, u.entrants),
        el("span", { class: "how", text: u.line ? "Credited to " + u.winner + " · pool line " + u.line : u.winner + " won" })
      ]);
    }) : [el("p", { class: "note", text: "No upsets: most of the pool had every winner." })], { "data-card": "upsets", "data-nav": "Upsets" });
    var results = scroller(el("table", { id: "week-results" }, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Game" }), el("th", { text: "Credited to" }),
        el("th", { class: "hide-narrow", text: "Pool line" }), el("th", { class: "n", text: "Had it" })])]),
      el("tbody", {}, w.results.map(function (g) {
        return el("tr", {}, [
          el("td", { class: "game", text: g.matchup }),
          el("td", { class: "coach winner" }, [g.winner ? el("span", { class: "team" }, [badge(g.winner), el("span", { text: g.winner })]) : "–",
            g.line ? el("span", { class: "narrow-only note", style: "display:block", text: "line: " + g.line }) : null]),
          el("td", { class: "hide-narrow", text: g.line || "" }),
          el("td", { class: "n num", text: g.right == null ? "" : g.right + " of " + w.entrants })
        ]);
      }))
    ]));
    return el("div", { class: "view", "data-view": "weeks" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Week " + w.week }), picker]),
      heroRecap(w, true),
      replayModule(w),
      el("div", { class: "cols" }, [el("div", {}, [chaosModule(w), awards, upsets]), el("div", {}, [beatsModule(w), soCloseCard(w)])]),
      module("Scoreboard", plural(w.scores.length, "coach", "coaches"), [scores]),
      module("Results", plural(w.results.length, "game"), [results])
    ]);
  }
  // So close: the one game that would have changed who won the week.
  function soCloseCard(w) {
    var sc = w.so_close;
    if (!sc) return null;
    var outcomes = sc.outcomes || [];
    var MAX_GAMES = 4;
    var kids = [];
    if (!outcomes.length) {
      kids.push(el("p", { class: "race-sum", text: sc.margin >= 2
        ? listNames(w.winners) + " won by " + plural(sc.margin, "clear win") + " – no single game would have changed it."
        : "No single game going the other way would have changed who won." }));
    }
    outcomes.forEach(function (o) {
      var shared = o.who.length > 1;
      var games = o.games.slice(0, MAX_GAMES).map(function (g) {
        return el("li", { text: g.instead + " instead of " + g.was + " (" + g.matchup + ")" });
      });
      if (o.games.length > MAX_GAMES) games.push(el("li", { text: "or " + plural(o.games.length - MAX_GAMES, "other game") }));
      var head = listNames(o.new) + (shared ? " would have shared it" + (o.who.length > o.new.length ? " with " + listNames(o.who.filter(function (n) { return o.new.indexOf(n) < 0; })) : "") : " would have won it") +
        " with " + o.score + ", if the pool had credited " + (o.games.length > 1 ? "any one of:" : ":");
      kids.push(el("div", { class: "close-one" }, [el("span", { class: "who", text: head }), el("ul", {}, games)]));
    });
    kids.push(el("p", { class: "note", text: "Pick’em points only: Big Loser points stay as they were." }));
    return module("So close", "one game from winning week " + w.week, kids, { "data-card": "so-close" });
  }

