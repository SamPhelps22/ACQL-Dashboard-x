  // ---- game-day strip: the slate in numbers, the next kickoff to the second ----------
  // Counting rules: every game on the week's pick sheet once; postponed
  // games are counted apart and in none of the others; "to play" is not
  // started and not postponed.
  function slateOf(t) {
    var s = { total: t.games.length, live: 0, final: 0, upcoming: 0, postponed: 0 };
    t.games.forEach(function (x) {
      if (x.sc && x.sc.off) s.postponed++;
      else if (x.state === "in") s.live++;
      else if (x.state === "post") s.final++;
      else s.upcoming++;
    });
    return s;
  }
  // The next kickoff, as the scoreboard timed it, with every game starting then.
  function nextGroup() {
    var nk = nextKickoff();
    if (!nk || nk.at <= Date.now()) return null;
    var with_ = DATA.live.games.filter(function (g) { var k = gameKey(g.hc, g.ac), sc = live.scores[k];
      return live.kick[k] === nk.at && !(sc && (sc.state !== "pre" || sc.off)); });
    return { at: nk.at, games: with_ };
  }
  function countText(ms) {
    var s = Math.max(0, Math.floor(ms / 1000)), d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600),
      m = Math.floor(s % 3600 / 60), sec = s % 60, two = function (n) { return (n < 10 ? "0" : "") + n; };
    return (d ? d + "d " + two(h) + ":" : h ? two(h) + ":" : "") + two(m) + ":" + two(sec);
  }
  function nextNode(t) {
    var nx = nextGroup(), s = slateOf(t);
    var due = t.games.some(function (x) { return x.state === "pre" && !(x.sc && x.sc.off) && x.kick && x.kick <= Date.now(); });
    if (nx) {
      var g = nx.games[0];
      return el("div", { class: "next" }, [el("span", { class: "k", text: "Next kickoff" }),
        el("b", { class: "cd num", "data-count-to": String(nx.at), text: countText(nx.at - Date.now()) }),
        el("span", { class: "m", text: kickFull(nx.at) + (g ? " · " + g.a + " at " + g.h : "") + (nx.games.length > 1 ? " +" + (nx.games.length - 1) + " more" : "") })]);
    }
    var word = due ? ["Kickoff", "Kicking off"] : s.live ? ["On now", plural(s.live, "game") + " live"]
      : s.total && !s.upcoming ? ["Slate", "Complete"] : ["Next kickoff", live.fetched ? "Time to come" : "–"];
    return el("div", { class: "next" }, [el("span", { class: "k", text: word[0] }), el("b", { class: "cd", text: word[1] }),
      el("span", { class: "m", text: due ? "Waiting for the scoreboard to show it under way" : "" })]);
  }
  function slateStrip(t) {
    if (!hasLive()) return null;
    var s = slateOf(t), fr = freshness();
    function cell(n, k, cls) { return el("div", { class: "c" + (cls ? " " + cls : "") }, [el("b", { class: "num", text: String(n) }), el("span", { text: k })]); }
    return el("div", { class: "slate", role: "group", "aria-label": "Week " + DATA.live.week + " slate" }, [
      el("div", { class: "wk" }, [el("span", { text: "Week" }), el("b", { text: String(DATA.live.week) })]),
      cell(s.total, "games"), cell(s.live, "live", s.live ? "on" : ""), cell(s.final, "final"), cell(s.upcoming, "to play"),
      s.postponed ? cell(s.postponed, "postponed") : null,
      nextNode(t),
      el("span", { class: "fresh " + fr.level, title: fr.detail || fr.head, "data-fresh": "1", text: freshWord(fr) }),
      el("button", { class: "cinebtn", type: "button", onclick: openCinema, "aria-label": "Cinema mode: the week full screen" }, [
        el("span", { class: "glyph", "aria-hidden": "true", text: "⛶" }), "Cinema"]),
      // only on a browser where Phelpy is the chosen coach: the Lab runs on that one computer
      state.me === "Phelpy" ? el("a", { class: "cinebtn labbtn", href: "http://127.0.0.1:8765/", target: "_blank",
        rel: "noopener noreferrer", title: "Open the Lab (runs on your own computer)" }, [
        el("span", { class: "glyph", "aria-hidden": "true", text: "▤" }), "Lab"]) : null,
      state.me === "Phelpy" ? el("a", { class: "cinebtn labbtn", href: "http://127.0.0.1:8765/redzone", target: "_blank",
        rel: "noopener noreferrer", title: "Open RedZone on your dashboard" }, [
        el("span", { class: "glyph", "aria-hidden": "true", text: "◉" }), "RedZone"]) : null
    ]);
  }
  function freshWord(fr) {
    var word = feedLabel(fr);
    if (fr.level === "fresh") return "Updated " + ageWords(fr.age);
    if (fr.level === "stale" || fr.level === "failed") return word + " · data from " + ageWords(fr.age);
    return fr.level === "error" ? word + " · retrying" : word;
  }
  // Every second while one is on screen: the countdowns' digits and the age words - nothing redrawn.
  setInterval(function () {
    if (document.hidden) return;
    var nodes = document.querySelectorAll("[data-count-to]");
    var zero = false;
    Array.prototype.forEach.call(nodes, function (n) {
      var left = Number(n.getAttribute("data-count-to")) - Date.now();
      if (left <= 0) zero = true;
      n.textContent = countText(left);
    });
    var fr = null;
    Array.prototype.forEach.call(document.querySelectorAll("[data-fresh]"), function (n) {
      fr = fr || freshness();
      n.textContent = freshWord(fr);
      n.className = "fresh " + fr.level;
    });
    // kickoff came: the countdown hands over to "kicking off", never below zero
    if (zero && !busyHere()) render({ quiet: true });
  }, 1000);

  // Each card's status as last drawn: a card whose status really changed
  // plays one short transition, never on a redraw of the same status.
  var cardStates = {};
  function noteCardState(key, status, node) {
    var was = cardStates[key];
    cardStates[key] = status;
    if (was && was !== status) node.classList.add("turned-" + status);
  }

