  // ---- all over, not yet entered ---------------------------------------------------------
  function finalHome(t) {
    var L = DATA.live, sim = simulate(t);
    var top = t.rows.length ? t.rows[0].now : 0;
    var winners = t.rows.filter(function (r) { return r.now === top; }).map(function (r) { return r.c.name; });
    var mine = t.rows.filter(function (r) { return isMe(r.c.name); })[0];
    var pay = moneyNow(t);
    var average = t.rows.length ? t.rows.reduce(function (a, r) { return a + r.now; }, 0) / t.rows.length : 0;
    var top_ = hero("Week " + L.week + " final", [
      el("span", { class: "kicker" }, welcome(["Week " + L.week + " is final", "official table to follow"])),
      el("h1", { text: winners.length > 2 ? cap(count(winners.length, "coach", "coaches")) + " share week " + L.week + " on " + top
        : listNames(winners, 2) + (winners.length > 1 ? " win" : " wins") + " week " + L.week + " with " + top }),
      el("p", { class: "deck", text: "From the final scores. The official table follows once the week is entered." })
    ], mine ? [
      stat(String(mine.now), "your score"),
      stat(ordinal(livePlace(t, mine.c.name)), "of " + t.rows.length),
      stat(cash(pay[mine.c.name]), "for the week", "money " + cashTone(pay[mine.c.name])),
      stat(String(top), "the winning score")
    ] : [
      stat(String(top), "the winning score"),
      stat(average.toFixed(1), "the pool’s average"),
      stat(cash(pot(pay)), winners.length > 1 ? "to the winners" : "to the winner", "money up"),
      stat(String(t.rows.length), "cards")
    ]);
    return [
      top_,
      el("div", { class: "cols" }, [
        el("div", {}, [module("Final", "week " + L.week + ", from the scores", [weekBoard(t, sim, 10), moreLink("Every card", "live"), moreLink("Everyone’s picks", "picks")], { "data-card": "board" })]),
        el("div", {}, [weekPoolsBrief(t)])
      ])
    ];
  }

