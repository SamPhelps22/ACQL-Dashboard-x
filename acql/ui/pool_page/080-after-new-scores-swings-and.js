  // ---- after new scores: swings, and the viewer's chance over time -------------------
  var swings = [];          // what changed while this page was open, newest first
  var lastSeen = null;      // each game's credited side at the previous look
  var scoreMoved = {};      // games whose score really changed at the last look, until when to mark them
  var halves = {};          // games already announced at halftime
  var stateTurned = {};     // games that started, reached halftime or finished at the last look, until when to mark them
  function turnedNow(g) { return stateTurned[gameKey(g.hc, g.ac)] > Date.now(); }
  function seen(t) {
    var now = {};
    t.games.forEach(function (x) {
      now[gameKey(x.g.hc, x.g.ac)] = { credit: x.credit, state: x.state, hs: x.hs, as: x.as, detail: liveDetail(x) };
    });
    return now;
  }
  // Who the pool credits at 0-0: the underdog of a lined game, nobody otherwise.
  function startCredit(g) {
    var side = credited(g, { state: "in", home: g.hc, hs: 0, as: 0 });
    return side === "home" ? g.hc : side === "away" ? g.ac : "";
  }
  function afterScores() {
    if (!hasLive()) return;
    var t = liveTally();
    var now = seen(t);
    if (lastSeen) {
      var found = [];
      t.games.forEach(function (x) {
        var key = gameKey(x.g.hc, x.g.ac), before = lastSeen[key];
        if (!before) return;
        // a real change between two good looks this visit; never on the first (or a cached) one
        if (live.good > 1 && before.hs != null && x.hs != null && (before.hs !== x.hs || before.as !== x.as)) scoreMoved[key] = Date.now() + 4000;
        // halftime, said once a game, and its card marked for a moment (Cinema mode)
        if (x.state === "in" && /half/i.test(liveDetail(x)) && !/half/i.test(before.detail || "") && !halves[key]) {
          halves[key] = 1;
          stateTurned[key] = Date.now() + 4000;
          found.push({ title: "Halftime: " + x.g.a + " " + x.as + ", " + x.g.h + " " + x.hs, text: "", tone: "half", quiet: true });
        }
        if (before.state !== x.state) stateTurned[key] = Date.now() + 4000;
        var pickers = function (team) {
          return DATA.live.coaches.filter(function (c) { return c.picks[DATA.live.games.indexOf(x.g)] === team; });
        };
        // a game that has just kicked off is measured from 0-0, not from "not started"
        var was = before.state === "pre" ? startCredit(x.g) : before.credit;
        if (x.credit && x.credit !== was) {
          var gain = pickers(x.credit);
          var mine = gain.some(function (c) { return isMe(c.name); });
          var lost = was ? pickers(was).some(function (c) { return isMe(c.name); }) : false;
          found.push({ title: (x.state === "post" ? "Final: " : "") + teamName(x, x.credit) + (was ? " now credited" : " on the board"),
            text: x.g.a + " " + (x.as == null ? "" : x.as) + ", " + x.g.h + " " + (x.hs == null ? "" : x.hs) + " · " +
              plural(gain.length, "coach", "coaches") + " gain a point" + (mine ? " - you’re one" : lost ? " - you lose one" : ""),
            tone: mine ? "mine" : lost ? "bad" : "" });
        } else if (x.state === "post" && before.state !== "post") {
          found.push({ title: "Final: " + x.g.a + " " + x.as + ", " + x.g.h + " " + x.hs,
            text: x.credit ? teamName(x, x.credit) + " credited" : "No side credited", tone: "" });
        }
        [x.g.hc, x.g.ac].forEach(function (team) {
          var by = x.hs == null ? null : team === x.g.hc ? x.as - x.hs : x.hs - x.as;
          var was = before.hs == null ? null : team === x.g.hc ? before.as - before.hs : before.hs - before.as;
          if (by != null && by >= 15 && (was == null || was < 15)) {
            var cards = DATA.live.coaches.filter(function (c) { return c.bl.indexOf(team) >= 0; });
            if (!cards.length) return;
            var mine = cards.some(function (c) { return isMe(c.name); });
            found.push({ title: teamName(x, team) + " down " + by,
              text: "A Big Loser point if it holds, for " + plural(cards.length, "card") + (mine ? " - yours too" : ""), tone: mine ? "mine" : "" });
          }
        });
      });
      found.forEach(function (f) { f.at = new Date(); swings.unshift(f); if (!f.quiet) toast(f); });
      swings = swings.slice(0, 30);
    }
    lastSeen = now;
    standingsAccept(t);
    noteMyChance(t);
  }
  // A score that changed at the last good look, for this draw only: the first
  // draw after it plays the wash, and the end of that draw uses it up.
  function moved(g) { return scoreMoved[gameKey(g.hc, g.ac)] > Date.now(); }
  // The viewer's chance of winning the week, kept on this phone for the line on Me.
  function chanceKey() { return "acql-chance-" + seasonYear() + "-" + (DATA.live ? DATA.live.week : 0) + "-" + state.me; }
  function noteMyChance(t) {
    if (!hasMe() || !DATA.live.coaches.some(function (c) { return isMe(c.name); })) return;
    var v = simulate(t).chance[state.me] || 0;
    var points = storedJSON(chanceKey()) || [];
    var last = points[points.length - 1];
    var at = Date.now();
    if (last && Math.abs(last[1] - v) < 0.005 && at - last[0] < 15 * 60 * 1000) return;
    points.push([at, Math.round(v * 1000) / 1000]);
    storeJSON(chanceKey(), points.slice(-300));
  }
  function myChances() { return hasMe() && hasLive() ? (storedJSON(chanceKey()) || []) : []; }

