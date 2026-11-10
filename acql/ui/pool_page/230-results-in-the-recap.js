  // ---- results in: the recap -----------------------------------------------------------
  function recapHome() {
    var w = weekData(DATA.through_week);
    if (!w) return [stateMsg("No completed games yet",
      "The recap and standings appear here once week 1’s results are entered in the dashboard.",
      { text: "See the season’s picks", go: function () { go("weeks"); } })];
    return [
      heroRecap(w),
      el("div", { class: "cols" }, [
        el("div", {}, [tableTop(), storiesModule(w)]),
        el("div", {}, [youModule(w), sidePoolsModule(w), titleRaceModule(), movers()])
      ])
    ];
  }
  // The top of the table, and where the viewer is.
  function tableTop() {
    var lead = DATA.players.length ? DATA.players[0].wins : 0;
    var shown = DATA.players.slice(0, 6);
    var mine = DATA.players.filter(function (p) { return isMe(p.name); })[0];
    if (mine && shown.indexOf(mine) < 0) shown.push(mine);
    return module("The table", "after week " + DATA.through_week, [
      el("div", { class: "rows standrows" }, shown.map(function (p) {
        return el("div", { class: "r" + (isMe(p.name) ? " me" : ""), style: "grid-template-columns: 30px 30px minmax(0,1fr) auto" }, [
          el("span", { class: "pos", text: p.place != null ? String(p.place) : "" }),
          moveMark(p.move),
          el("span", { class: "name" }, [who(p.name), isMe(p.name) ? el("span", { class: "youtag", text: "YOU" }) : null,
            el("span", { class: "meta", style: "display:block", text: (lead - p.wins ? (lead - p.wins) + " back" : "leads") + (p.title != null ? " · " + titleText(p) + " title chance" : "") })]),
          el("span", { class: "big", text: String(p.wins) })
        ]);
      })),
      moreLink("The full standings", "standings")
    ], { "data-card": "table" });
  }
  function moveMark(move) {
    if (move == null || move === 0) return el("span", { class: "mv flat", text: "–", "aria-label": "no change" });
    return move > 0 ? el("span", { class: "mv up", text: "▲" + move, "aria-label": "up " + move })
      : el("span", { class: "mv down", text: "▼" + (-move), "aria-label": "down " + (-move) });
  }
  function movers() {
    var up = DATA.players.filter(function (p) { return p.move >= 2; }).sort(function (a, b) { return b.move - a.move || a.place - b.place; }).slice(0, 3);
    var down = DATA.players.filter(function (p) { return p.move <= -2; }).sort(function (a, b) { return a.move - b.move || a.place - b.place; }).slice(0, 3);
    if (!up.length && !down.length) return null;
    function line(p) {
      return el("div", { class: "r", style: "grid-template-columns: 44px minmax(0,1fr) auto" }, [
        moveMark(p.move), el("span", { class: "name" }, [who(p.name)]),
        el("span", { class: "meta", text: "now " + placeText(p) })
      ]);
    }
    return module("Who moved", "places since last week", [el("div", { class: "rows" }, up.concat(down).map(line))], { "data-card": "movers" });
  }
  function shareBar(right, of) {
    var p = of ? Math.max(0, Math.min(100, right / of * 100)) : 0;
    return el("span", { class: "share", "aria-hidden": "true" }, [el("i", { style: "width:" + p.toFixed(1) + "%" })]);
  }
  function storiesModule(w) {
    var kids = (w.awards || []).map(function (a) {
      return el("div", { class: "award" }, [a.title ? el("span", { class: "t", text: a.title }) : null,
        el("span", { class: "w", text: a.who }), a.detail ? el("span", { class: "why", text: a.detail }) : null]);
    });
    kids = kids.length ? [el("div", { class: "awards" }, kids)] : [];
    (w.upsets || []).slice(0, 2).forEach(function (u) {
      kids.push(el("div", { class: "upset" }, [
        el("span", { class: "game" }, [el("span", { class: "team" }, [badge(u.winner), el("span", { text: u.matchup })])]),
        el("span", { class: "had num", text: u.right + " of " + u.entrants }),
        shareBar(u.right, u.entrants),
        el("span", { class: "how", text: u.line ? "Credited to " + u.winner + ", pool line " + u.line : u.winner + " won" })
      ]));
    });
    if (!kids.length) return null;
    return module("The week’s stories", null, kids.concat([moreLink("Everything from week " + w.week, "weeks")]), { "data-card": "stories" });
  }
  // The viewer's own week - or the way to say who they are.
  function youModule(w) {
    if (!hasMe()) {
      return module("Your week", null, [
        el("p", { class: "race-sum", text: "Pick your name once and this page shows your week, your place and your side pools first." }),
        el("button", { class: "btn primary", type: "button", text: "Pick your name", onclick: function () { go("me"); } })
      ], { "data-card": "you" });
    }
    var p = player(state.me);
    var mine = w.scores.filter(function (s) { return s.name === p.name; })[0];
    var kids = [];
    if (mine) {
      var rank = weekPlace(w, mine.name);
      var vs = mine.total - w.average;
      kids.push(el("div", { class: "figures", style: "grid-template-columns: repeat(2, minmax(0,1fr))" }, [
        figure(String(mine.total), "week " + w.week + (w.winners.indexOf(p.name) >= 0 ? " ★ won it" : ", " + ordinal(rank) + " of " + w.scores.length),
          (vs >= 0 ? "+" : "−") + Math.abs(vs).toFixed(1) + " on the average"),
        figure(p.place != null ? placeText(p) : "–", "in the standings", plural(p.wins, "win") + (p.move ? (p.move > 0 ? ", up " : ", down ") + Math.abs(p.move) : ""))
      ]));
    }
    kids.push(el("p", { class: "note", text: (p.suicide.alive ? "Still in the suicide pool" : p.suicide.out ? "Out of the suicide pool in week " + p.suicide.out : "Not in the suicide pool") +
      (p.big_loser ? " · " + plural(p.big_loser, "Big Loser point") : "") }));
    kids.push(moreLink("Your page", "me"));
    return module("Your week", state.me, kids, { "data-card": "you" });
  }
  function figure(value, label, detail) {
    return el("div", { class: "figure" }, [el("span", { class: "v", text: value }), el("span", { class: "k", text: label }),
      detail ? el("span", { class: "d", text: detail }) : null]);
  }
  function sidePoolsModule(w) {
    var alive = aliveNames();
    var sui = w.suicide || {};
    var tied = sui.tied || [];
    var out = outIn(w.week);
    var how = sui.killer ? sui.killer + " knocked out " + plural(sui.killed, "coach", "coaches") +
      (tied.length ? " (so did " + listNames(tied, 2) + ")" : "") + " in week " + w.week +
      (out > sui.killed * (1 + tied.length) ? ", " + out + " out in all" : "")
      : out ? plural(out, "coach", "coaches") + " went out in week " + w.week : "Every pick came in in week " + w.week;
    var bl = DATA.players.filter(function (p) { return p.big_loser; }).sort(function (a, b) { return b.big_loser - a.big_loser; });
    var top = bl.length ? bl[0].big_loser : 0;
    var blLeaders = bl.filter(function (p) { return p.big_loser === top; }).map(function (p) { return p.name; });
    return module("Side pools", null, [
      el("div", { class: "rows" }, [
        el("div", { class: "r", style: "grid-template-columns: 52px minmax(0,1fr)" }, [el("span", { class: "big", text: String(alive.length) }),
          el("span", {}, [el("b", { text: "still in the suicide pool" }), el("span", { class: "meta", style: "display:block", text: how })])]),
        top ? el("div", { class: "r", style: "grid-template-columns: 52px minmax(0,1fr)" }, [el("span", { class: "big", text: String(top) }),
          el("span", {}, [el("b", { text: "Big Loser points lead the way" }), el("span", { class: "meta", style: "display:block", text: listNames(blLeaders, 3) })])]) : null
      ]),
      moreLink("The side pools", "pools")
    ], { "data-card": "side" });
  }
  function titleRaceModule() {
    var R = DATA.race;
    if (!R || !DATA.players.length) return null;
    var byChance = DATA.players.filter(function (p) { return p.title != null; }).sort(function (a, b) { return (b.title || 0) - (a.title || 0); }).slice(0, 4);
    if (!byChance.length) return null;
    return module("Title odds", plural(R.weeks_left, "week") + " left", [
      el("div", { class: "rows" }, byChance.map(function (p) {
        return el("div", { class: "r" + (isMe(p.name) ? " me" : ""), style: "grid-template-columns: minmax(0,1fr) 44px 30%" }, [
          el("span", { class: "name" }, [who(p.name)]), el("span", { class: "num", style: "text-align:right;font-weight:700", text: titleText(p) }),
          bar(p.title || 0, Math.max(1, byChance[0].title || 0))
        ]);
      })),
      moreLink("How the odds have moved", "charts")
    ], { "data-card": "odds" });
  }

