  // ---- games on: the week as it happens ------------------------------------------------------
  function gamedayHome(t) {
    var L = DATA.live, sim = simulate(t);
    var on = gamesOn(t), finals = t.games.filter(function (x) { return x.state === "post"; }).length;
    var top = t.rows.length ? t.rows[0].now : 0;
    var leaders = t.rows.filter(function (r) { return r.now === top; }).map(function (r) { return r.c.name; });
    var mine = t.rows.filter(function (r) { return isMe(r.c.name); })[0];
    var next = nextKickoff();
    var place = mine ? 1 + t.rows.filter(function (o) { return o.now > mine.now; }).length : 0;
    var pay = moneyNow(t);
    var behind = mine ? top - mine.now : 0;
    var stats = mine ? [
      stat(String(mine.now), "your score now"),
      stat(ordinal(place), "of " + t.rows.length + " right now"),
      stat(pct(sim.chance[state.me] || 0), "chance to win the week"),
      stat(cash(pay[state.me]), "if it ended now", "money " + cashTone(pay[state.me]))
    ] : [
      stat(String(top), "the best score now"),
      stat(String(on), on === 1 ? "game on now" : "games on now"),
      stat(String(finals), "of " + t.games.length + " final"),
      stat(String(t.games.length - on - finals), "still to play")
    ];
    var top_ = hero("Week " + L.week + " live", [
      el("span", { class: "kicker" }, [on ? el("span", { class: "live-tag", text: "LIVE" }) : null].concat(welcome([underway(t, L.week),
        (on ? plural(on, "game") + " on, " : "") + finals + " of " + t.games.length + " final"]))),
      el("h1", { text: leaders.length > 3 ? cap(count(leaders.length, "coach", "coaches")) + " share the lead on " + top
        : listNames(leaders, 3) + (leaders.length > 1 ? " lead" : " leads") + " the week with " + top }),
      mine ? el("p", { class: "deck", text: (!behind ? (leaders.length > 1 ? "You share the lead" : "You lead the week") : "You’re " + behind + " behind the lead") +
          (mine.left ? ", with " + plural(mine.left, "pick") + " still to play." : ".") })
        : el("p", { class: "deck", text: hasMe() ? "No card from " + state.me + " on this week’s sheet." : "Pick your name to follow your own card." }),
      next ? el("p", { class: "deck" }, ["Next kickoff ", kickNode(next.at), ": " + next.g.a + " at " + next.g.h + "."]) : null,
      el("button", { class: "btn onair", type: "button", text: "Every card, live", onclick: function () { go("live"); } })
    ], stats, "onair-live");
    return [
      top_,
      el("div", { class: "cols" }, [
        el("div", {}, [
          module("The week so far", "if it ended now", [weekBoard(t, sim, 8), moreLink("Every card", "live"), moreLink("Everyone’s picks", "picks")], { "data-card": "board" }),
          onNowModule(t),
          rootingCard(t, sim),
          swingCard(t, sim)
        ]),
        el("div", {}, [swingsFeed(), weekSuicideCard(t), weekLosersCard(t), limbCard(t)])
      ])
    ];
  }

