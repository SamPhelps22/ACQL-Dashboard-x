  // ---- picks in, no kickoff yet: the preview ----------------------------------------------
  function previewHome(t) {
    var L = DATA.live;
    var next = nextKickoff();
    var w = weekData(DATA.through_week);
    var lined = L.games.filter(function (g) { return g.line != null && g.fav; }).length;
    var losers = L.coaches.reduce(function (a, c) { return a + c.bl.length; }, 0);
    var top = hero("Week " + L.week, [
      el("span", { class: "kicker" }, welcome(["Week " + L.week + " is up next", "the picks are in"])),
      el("h1", {}, next ? ["Kickoff ", kickNode(next.at)] : ["Week " + L.week + " is set"]),
      el("p", { class: "deck" }, [plural(L.coaches.length, "card") + " in. " + aliveNames().length + " still alive in the suicide pool." +
        (next ? " " + next.g.a + " at " + next.g.h + " starts it." : "")]),
      hasMe() && L.coaches.some(function (c) { return isMe(c.name); })
        ? el("button", { class: "btn onair", type: "button", text: "Your card for week " + L.week, onclick: function () { go("me"); } }) : null
    ], [
      stat(String(L.coaches.length), "cards in"),
      stat(String(L.games.length), lined ? "games, " + lined + " with a pool line" : "games"),
      stat(String(aliveNames().length), "still in the suicide pool"),
      stat(String(losers), "Big Loser picks")
    ]);
    return [
      top,
      el("div", { class: "cols" }, [
        el("div", {}, [splitsCard(t, true), limbCard(t)]),
        el("div", {}, [weekSuicideCard(t), weekLosersCard(t), w ? lastWeekModule(w) : null])
      ])
    ];
  }
  function lastWeekModule(w) {
    return module("Last week", "week " + w.week, [
      el("p", { class: "race-sum" }, [el("b", { text: headline(w) + ". " }), story(w)]),
      moreLink("Week " + w.week + " in full", "weeks")
    ], { "data-card": "last-week" });
  }

