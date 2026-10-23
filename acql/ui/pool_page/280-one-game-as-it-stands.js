  // ---- one game, as it stands ---------------------------------------------------------
  var flipped = {};         // the game cards turned to their back, by game, kept across redraws
  // A scoreboard card: the clock and the TV, the score, who has the ball and
  // where (a strip of field with the line to gain), the last play, where the
  // pool's line stands, each side's chance of being credited, and how the
  // pool picked it - the viewer's own pick, Big Loser and suicide pick named.
  function gameCard(x) {
    var L = DATA.live, g = x.g, sc = x.sc || {}, gi = L.games.indexOf(g);
    var on = x.state === "in", over = x.state === "post", lined = g.line != null && g.fav;
    var count = {};
    L.coaches.forEach(function (c) { var pk = c.picks[gi]; if (pk) count[pk] = (count[pk] || 0) + 1; });
    var me = L.coaches.filter(function (c) { return isMe(c.name); })[0], mine = [];
    function row(team, name, score, other) {
      var ball = on && sc.poss === team, rec = !on && !over && sc.rec ? sc.rec[team] : "";
      return el("div", { class: "row" + (x.credit && x.credit === team ? " credit" : "") + (ball ? " poss" : "") +
          (over && score != null && other != null && score < other ? " lost" : "") + (me && me.picks[gi] === team ? " picked" : "") }, [
        el("span", { class: "team" }, [badge(team, true), el("b", { text: name }),
          ball ? el("span", { class: "ball", role: "img", "aria-label": "has the ball", title: "Has the ball" }) : null]),
        rec ? el("span", { class: "rec", text: rec }) : el("span", { class: "pts" + (score != null && moved(g) ? " score-new" : ""), text: score == null ? "" : String(score) })]);
    }
    var when = sc.off ? sc.detail || "Postponed" : x.state === "pre" && x.kick ? kickFull(x.kick) : liveDetail(x) || (x.kick ? kickFull(x.kick) : live.fetched ? "Kickoff time to come" : "Not started");
    var stand = standing(x);
    if (me) {
      if (me.picks[gi]) mine.push("you: " + me.picks[gi].toUpperCase() + (over ? (x.credit === me.picks[gi] ? " ✓" : " ✗") : ""));
      me.bl.forEach(function (team) {
        if (team !== g.hc && team !== g.ac) return;
        var lost = over && x.hs != null ? (team === g.hc ? x.as - x.hs : x.hs - x.as) : null;
        mine.push("your Big Loser: " + team.toUpperCase() + (lost == null ? "" : lost >= 15 ? " ✓" : " ✗"));
      });
      var p = player(me.name);
      if (me.sui && p && p.suicide.alive && (me.sui === g.hc || me.sui === g.ac)) {
        mine.push("your suicide pick: " + me.sui.toUpperCase() + (over ? (x.credit === me.sui ? " ✓" : " ✗") : ""));
      }
    }
    var spot = on ? spotOf(x) : null;
    var key = g.ac + "@" + g.hc, turned = !!flipped[key];
    var cs = cardState(x);
    var top = el("div", { class: "top" }, [el("span", { class: "when" + (on ? " in" : "") }, [on ? el("span", { class: "dot-live" }) : null,
        over ? el("b", { class: "finaltag", text: "FINAL " }) : null, over && /^final$/i.test(when) ? null : when]),
      warnTag(cs),
      on && sc.rz ? el("span", { class: "rztag", text: "RED ZONE" }) : null,
      sc.tv && !over ? el("span", { class: "tv", text: sc.tv }) : null]);
    var card;
    function turn() {
      flipped[key] = !turned;
      var fresh = gameCard(x);
      fresh.classList.add("turning");
      card.replaceWith(fresh);
      var b = fresh.querySelector(".flipbtn");
      if (b) b.focus({ preventScroll: true });
    }
    var flip = el("button", { class: "flipbtn", type: "button", "aria-expanded": turned ? "true" : "false",
      "aria-label": (turned ? "Back to the score: " : "More on ") + g.a + " at " + g.h, onclick: turn },
      [el("span", { text: turned ? "Back" : "More" }), el("span", { class: "glyph", "aria-hidden": "true", text: "\u21bb" })]);
    var front = [top,
      row(g.ac, g.a, x.state === "pre" ? null : x.as, x.hs),
      row(g.hc, g.h, x.state === "pre" ? null : x.hs, x.as),
      el("div", { class: "gline" }, [el("span", { class: "line", text: lined ? "Pool line: " + teamName(x, g.fav) + " by " + g.line : "Straight up" }),
        stand.text ? el("span", { class: "stand " + stand.tone, text: stand.text }) : null]),
      el("div", { class: "gfoot" }, [pickChip(), flip])];
    // the viewer's pick, or with no viewer the side most of the pool took
    function pickChip() {
      var p = me ? me.picks[gi] : "";
      if (p) return el("span", { class: "pickchip" + (over ? (x.credit === p ? " ok" : " no") : "") },
        ["Your pick ", badge(p), over ? (x.credit === p ? " ✓" : " ✗") : null]);
      var a = count[g.ac] || 0, h = count[g.hc] || 0;
      if (!a && !h) return el("span", { class: "meta", text: "No picks for this game" });
      return el("span", { class: "meta", text: a === h ? "The pool is split " + a + "–" + h
        : "Most cards: " + (a > h ? g.ac : g.hc).toUpperCase() + ", " + Math.max(a, h) + " of " + (a + h) });
    }
    var back = turned ? [top,
      el("div", { class: "mini" }, [miniSide(g.ac, x.as), el("span", { class: "at", text: "at" }), miniSide(g.hc, x.hs)]),
      spot ? fieldStrip(x, spot) : null,
      on && sc.down ? el("span", { class: "down", text: sc.down }) : null,
      on && sc.play ? el("p", { class: "play", text: sc.play }) : null,
      over ? null : chanceBar(x, me ? me.picks[gi] : ""),
      el("dl", { class: "facts" }, factRows()),
      el("span", { class: "meta" }, [(count[g.ac] || 0) + " on " + g.ac.toUpperCase() + " · " + (count[g.hc] || 0) + " on " + g.hc.toUpperCase(),
        mine.length ? el("span", { class: "you", text: " · " + mine.join(" · ") }) : null]),
      el("div", { class: "gfoot" }, [el("span", { class: "meta", text: sourceText() }), flip])] : null;
    function miniSide(team, pts) {
      return el("span", { class: "ms" + (x.credit === team ? " credit" : "") }, [badge(team), x.state === "pre" || pts == null ? null : el("b", { text: String(pts) })]);
    }
    // the deeper numbers: the market's line beside the pool's, and each
    // side's pool record so far this season (who the pool's lines credited)
    function factRows() {
      var rows = [], m = live.spreads[gameKey(g.hc, g.ac)], rec = teamRecords();
      rows.push(["Pool line", lined ? teamName(x, g.fav) + " by " + g.line : "Straight up, no line"]);
      if (m) {
        var mFav = m.pts > 0 ? m.home : m.pts < 0 ? (m.home === g.hc ? g.ac : g.hc) : "";
        rows.push(["Market line", mFav ? teamName(x, mFav) + " by " + Math.abs(m.pts) : "Even"]);
      } else rows.push(["Market line", live.fetched ? "Not posted" : "Not read yet"]);
      [g.ac, g.hc].forEach(function (team) {
        var r = rec[team], wl = sc.rec && sc.rec[team];
        rows.push([team.toUpperCase() + " this season", (r ? "Pool " + r.w + "–" + r.l : "No pool games yet") + (wl ? " · record " + wl : "")]);
      });
      return rows.map(function (r) { return el("div", {}, [el("dt", { text: r[0] }), el("dd", { text: r[1] })]); });
    }
    // where the numbers came from, and how fresh they are
    function sourceText() {
      var score = live.error && !live.fetched ? "Score feed not reached" : live.fetched ? "Scores from ESPN at " + clock(live.fetched) + (live.error ? " (last update failed)" : "") : "Scores loading";
      return score + ". Lines and picks from the pool’s sheet. " + (x.kick ? "Kickoff from ESPN." : "Kickoff time not known yet.");
    }
    card = el("div", { class: "gcard" + (on ? " in" : over ? " post" : " pre") + (on && sc.rz ? " rz" : "") + (turned ? " back" : "") +
      (cs.warn ? " warn-" + cs.warn : ""), "data-game": key, "data-status": cs.status }, turned ? back : front);
    noteCardState(key, cs.status, card);
    return card;
  }
  // Where the ball is: yards from the away side's goal line (the left of the
  // strip), the way the team with it is going, and the line to gain. Read
  // from ESPN's "LAC 23", or the down's "at LAC 23"; nothing when neither says.
  function spotOf(x) {
    var sc = x.sc || {}, g = x.g, said = sc.spot || "", down = sc.down || "", yard = null;
    var m = /^([A-Za-z]{2,3})\s+(\d{1,2})$/.exec(said) || /\bat ([A-Za-z]{2,3})\s+(\d{1,2})$/.exec(down);
    if (m) {
      var side = code(m[1]), y = Number(m[2]);
      if (y <= 50) yard = side === g.ac ? y : side === g.hc ? 100 - y : null;
    } else if (/^(\w+\s+)?50$/.test(said) || /\bat 50$/.test(down)) yard = 50;
    if (yard == null) return null;
    var dir = sc.poss === g.ac ? 1 : sc.poss === g.hc ? -1 : 0;
    var togo = Number((/&\s*(\d{1,2})\b/.exec(down) || [])[1]);
    var gain = !dir ? null : /&\s*goal/i.test(down) ? (dir > 0 ? 100 : 0) : togo ? Math.max(0, Math.min(100, yard + dir * togo)) : null;
    return { yard: yard, dir: dir, gain: gain };
  }
  // The strip of field: end zones lettered, the red zone shaded when they're
  // in it, the line of scrimmage (blue), the line to gain (yellow), the ball.
  function fieldStrip(x, spot) {
    var g = x.g, sc = x.sc || {};
    function at(yard) { return ((10 + yard) / 1.2).toFixed(2) + "%"; }
    return el("div", { class: "field", "aria-hidden": "true" }, [
      el("span", { class: "ez l", text: g.ac.toUpperCase() }),
      el("span", { class: "ez r", text: g.hc.toUpperCase() }),
      sc.rz && spot.dir ? el("span", { class: "zone", style: "left:" + at(spot.dir > 0 ? 80 : 0) + ";width:" + (20 / 1.2).toFixed(2) + "%" }) : null,
      spot.gain != null ? el("span", { class: "gain", style: "left:" + at(spot.gain) }) : null,
      el("span", { class: "los", style: "left:" + at(spot.yard) }),
      el("span", { class: "fball" + (spot.dir > 0 ? " right" : spot.dir < 0 ? " left" : ""), style: "left:" + at(spot.yard) })
    ]);
  }
  // Where the pool's line stands, and how that reads: covering (good), short
  // of it (warn), or just the score.
  function standing(x) {
    var text = standingText(x);
    if (!text) return { text: "", tone: "" };
    var g = x.g;
    if (g.line != null && g.fav) {
      if (/cover/.test(text)) return { text: text, tone: "good" };
      if (/short of/.test(text)) return { text: text, tone: "warn" };
    }
    return { text: text, tone: "plain" };
  }
  // Each side's chance of being credited with the game, the pool's line
  // applied: the likelier side darker, the viewer's own pick in gold.
  function chanceBar(x, pick) {
    var g = x.g, pa = creditChance(x, g.ac), ph = creditChance(x, g.hc), all = pa + ph || 1;
    var wa = Math.round(100 * pa / all);
    function seg(team, width, fav) {
      return el("i", { class: (fav ? "fav" : "") + (pick === team ? " mine" : ""), style: "width:" + width + "%" });
    }
    return el("div", { class: "chance", role: "img",
      "aria-label": "Chance of being credited: " + teamName(x, g.ac) + " " + pct(pa) + ", " + teamName(x, g.hc) + " " + pct(ph) }, [
      el("span", { class: "p" + (pa >= ph ? " fav" : ""), text: g.ac.toUpperCase() + " " + pct(pa) }),
      el("span", { class: "track" }, [seg(g.ac, wa, pa >= ph), seg(g.hc, 100 - wa, ph > pa)]),
      el("span", { class: "p" + (ph > pa ? " fav" : ""), text: pct(ph) + " " + g.hc.toUpperCase() })
    ]);
  }
  // The games on now, as cards; nothing when none are.
  function onNowModule(t) {
    var on = t.games.filter(function (x) { return x.state === "in"; });
    if (!on.length) return null;
    return module("On now", plural(on.length, "game"), [el("div", { class: "games" }, on.map(gameCard)),
      el("p", { class: "note", text: "The bar under a game shows each side’s chance of getting the point." })],
      { "data-card": "on-now" });
  }
  function finalBanner(t, withLink) {
    var top = t.rows.length ? t.rows[0].now : 0;
    var winners = t.rows.filter(function (r) { return r.now === top; }).map(function (r) { return r.c.name; });
    return el("div", { class: "final-banner" }, [
      el("span", { class: "note", text: "Week " + DATA.live.week + " is over" }),
      el("b", { text: "★ " + listNames(winners, 3) + " " + (winners.length > 1 ? "win" : "wins") + " with " + top }),
      el("span", { class: "note", text: "From the final scores. The official table follows once the week is entered." }),
      withLink ? el("button", { class: "btn", type: "button", text: "See the final table", onclick: function () { go("live"); } }) : null
    ]);
  }
  function liveStatus(t) {
    var inPlay = gamesOn(t);
    var finals = t.games.filter(function (x) { return x.state === "post"; }).length;
    var fr = freshness();
    if (!live.error && fr.level === "stale") return el("span", { class: "live-status warn", title: fr.detail }, [fr.head + " ",
        el("button", { class: "linkish", type: "button", text: live.busy ? "trying…" : "refresh now", onclick: retryScores })]);
    return live.error ? el("span", { class: "live-status bad", title: fr.detail }, [
        live.fetched ? "Refresh failed — showing data from " + clockSec(live.fetched) + " " : "No successful data refresh yet ",
        el("button", { class: "linkish", type: "button", text: live.busy ? "trying…" : "try again", onclick: retryScores })])
      : el("span", { class: "live-status" }, [inPlay ? el("span", { class: "dot-live" }) : null,
          (inPlay ? inPlay + " on now · " : "") + finals + " of " + t.games.length + " final" +
          (live.fetched ? " · scores at " + clock(live.fetched) + ", " + everyText() : " · fetching scores…")]);
  }

