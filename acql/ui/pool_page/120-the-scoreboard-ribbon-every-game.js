  // ---- the scoreboard ribbon: every game of the week being played -----------------------
  // Under the top bar on every page from the moment the pick sheet is in:
  // the games on now, then the kickoffs to come, then the finals. Each one
  // opens its game's card on the live page.
  function ticker() {
    if (!hasLive()) return null;
    var t = liveTally();
    var rank = { "in": 0, pre: 1, post: 2 };
    var order = t.games.slice().sort(function (a, b) {
      return rank[a.state] - rank[b.state] || (a.kick || 0) - (b.kick || 0);
    });
    return el("div", { class: "ticker" }, [el("div", { class: "track", role: "list", "aria-label": "Week " + DATA.live.week + " scores" }, order.map(scoreBug))]);
  }
  // "Sun 1:00 PM" - where room is short: the ribbon, a list
  function kickText(at) {
    var d = new Date(at);
    return kickDay(d) + " " + clock(d);
  }
  function scoreBug(x) {
    var g = x.g;
    var st = x.state === "in" ? (liveDetail(x) || "Live") : x.state === "post" ? "Final"
      : x.sc && x.sc.off ? liveDetail(x) : x.kick ? kickText(x.kick) : live.fetched ? "Time to come" : live.error ? "No scores yet" : "Loading…";
    var sc = x.sc || {}, on = x.state === "in";
    var me = DATA.live.coaches.filter(function (c) { return isMe(c.name); })[0];
    var pick = me ? me.picks[DATA.live.games.indexOf(g)] || "" : "";
    function side(team, pts) {
      var mark = (x.credit === team ? " credited" : "") + (pick === team ? " mine" : "");
      return [el("span", { class: "side" + mark, title: pick === team ? "Your pick" : null }, [badge(team),
          on && sc.poss === team ? el("span", { class: "ball", role: "img", "aria-label": "has the ball" }) : null]),
        el("span", { class: "pts" + mark + (pts != null && x.state !== "pre" && moved(g) ? " score-new" : ""), text: x.state === "pre" || pts == null ? "" : String(pts) })];
    }
    var lined = g.line != null && g.fav;
    var key = g.ac + "@" + g.hc;
    return el("a", { class: "bug" + (on ? " in" : x.state === "post" ? " post" : "") + (on && sc.rz ? " rz" : ""), role: "listitem",
      href: "#live", "data-bug": key, onclick: jumpToGame(key),
      title: g.a + " at " + g.h + (lined ? ", pool line " + teamName(x, g.fav) + " by " + g.line : "") +
        (on && sc.down ? ". " + sc.down + (sc.rz ? ", in the red zone" : "") : "") + ". Open the game." },
      [el("span", { class: "state", text: st })]
        .concat(side(g.ac, x.as), side(g.hc, x.hs)));
  }
  // From the ribbon to a game: the live page, scrolled to its card, the card
  // lit for a moment. Its details stay as the viewer left them.
  function jumpToGame(key) {
    return function (e) {
      e.preventDefault();
      if (currentView() !== "live") go("live");
      var card = app.querySelector('.gcard[data-game="' + key + '"]');
      if (!card) return;
      var bar = app.querySelector(".topbar"), tk = app.querySelector(".ticker");
      var above = (bar ? bar.offsetHeight : 0) + (tk ? tk.offsetHeight : 0) + 12;
      window.scrollTo({ top: Math.max(0, card.getBoundingClientRect().top + window.scrollY - above), behavior: smooth() });
      card.classList.remove("lit");
      void card.offsetWidth;
      card.classList.add("lit");
      var btn = card.querySelector(".flipbtn");
      if (btn) btn.focus({ preventScroll: true });
    };
  }

