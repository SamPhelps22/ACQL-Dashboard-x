  // ---- the week being played, followed live --------------------------------------
  // Scores come straight from ESPN's public scoreboard, fetched by the page
  // itself: every 30 seconds while a game is on, every 2 minutes when a kickoff
  // is close, every 5 otherwise, and not at all once every game is final.
  // The pool's own rules are applied to them here: a lined favourite must
  // win by at least the line (a win by exactly the line goes to the
  // favourite), and a Big Loser has to lose by 15 or more.
  var REFRESH_MS = 5 * 60 * 1000, LIVE_REFRESH_MS = 30 * 1000, SOON_REFRESH_MS = 2 * 60 * 1000;
  var SCORES = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard";
  var ESPN_CODES = { wsh: "was", la: "lar", jac: "jax", lvr: "lv", oak: "lv", sd: "lac", stl: "lar" };
  var CACHE_KEY = "acql-scores";
  var live = { scores: {}, spreads: {}, kick: {}, fetched: null, error: "", timer: null, busy: false, every: REFRESH_MS,
    lastTry: 0,              // when the last fetch began, worked or not: the countdown runs from it
    failedAt: null,          // when the last fetch failed (cleared by the next good one)
    good: 0 };               // good answers this visit: the first is the baseline nothing flashes against
  function code(abbr) { var c = String(abbr || "").toLowerCase(); return ESPN_CODES[c] || c; }
  function gameKey(a, b) { return [a, b].sort().join("@"); }
  function hasLive() { var L = DATA.live; return !!(L && L.games && L.games.length); }

  // The last scores this phone saw, so a page opened mid-game shows them at
  // once while the new ones load.
  (function restoreScores() {
    if (!hasLive()) return;
    var saved = storedJSON(CACHE_KEY);
    if (!saved || saved.week !== DATA.live.week || saved.year !== seasonYear()) return;
    if (Date.now() - saved.at > 20 * 60 * 1000) return;
    live.scores = saved.scores || {};
    live.spreads = saved.spreads || {};
    live.kick = saved.kick || {};
    live.fetched = new Date(saved.at);
  })();

  function fetchScores() {
    var L = DATA.live;
    if (!L || live.busy) return;
    live.busy = true;
    live.lastTry = Date.now();
    var year = String(seasonYear());
    var url = SCORES + "?seasontype=2&week=" + L.week + "&dates=" + year + "&_=" + Date.now();
    fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.json();
    }).then(function (json) {
      var got = {};
      (json.events || []).forEach(function (ev) {
        var comp = (ev.competitions || [])[0] || {};
        var teams = {}, rec = {};
        (comp.competitors || []).forEach(function (c) {
          var team = code(c.team && c.team.abbreviation), r = recordOf(c);
          teams[c.homeAway] = { code: team, score: pointsOf(c.score) };
          if (team && r) rec[team] = r;
        });
        if (!teams.home || !teams.away || !teams.home.code || !teams.away.code) return;
        var status = comp.status || ev.status || {};
        var st = status.type || {};
        var key = gameKey(teams.home.code, teams.away.code);
        // on or over with no readable score: this answer says nothing about it (the last good score stays)
        if ((st.state === "in" || (st.state === "post" && st.completed !== false)) &&
            (teams.home.score == null || teams.away.score == null)) return;
        if (teams.home.score == null) teams.home.score = 0;
        if (teams.away.score == null) teams.away.score = 0;
        // The betting line: "BUF -8.5" means Buffalo by 8.5. Kept with ESPN's
        // home team, which isn't always the sheet's (a neutral-site game).
        var details = String(((comp.odds || [])[0] || {}).details || "");
        var m = details.match(/^([A-Za-z]+)\s+(-?\d+(?:\.\d+)?)/);
        if (m) {
          var fav = code(m[1]), pts = Math.abs(Number(m[2]));
          if (fav === teams.home.code || fav === teams.away.code) {
            live.spreads[key] = { home: teams.home.code, pts: fav === teams.home.code ? pts : -pts };
          }
        } else if (/^even/i.test(details)) live.spreads[key] = { home: teams.home.code, pts: 0 };
        var start = Date.parse(comp.date || ev.date || "");
        if (!isNaN(start)) live.kick[key] = start;
        // Postponed or cancelled: ESPN calls it over, but nothing was decided.
        var off = st.state === "post" && st.completed === false;
        var field = !off && st.state === "in" ? fieldOf(comp) : {};
        got[key] = {
          home: teams.home.code, away: teams.away.code,
          hs: off ? 0 : teams.home.score, as: off ? 0 : teams.away.score,
          state: off ? "pre" : st.state || "pre", off: off, detail: st.shortDetail || st.detail || (off ? "Postponed" : ""),
          period: Number(status.period || 0), clock: Number(status.clock || 0),
          poss: field.poss || "", down: field.down || "", rz: !!field.rz, play: field.play || "", spot: field.spot || "",
          tv: tvOf(comp), rec: rec
        };
      });
      // A well-formed answer with no games in it is a bad answer: keep the scores already shown.
      if (!Object.keys(got).length) throw new Error("the feed listed no games");
      // A partial answer: the games it left out keep their last good scores.
      Object.keys(live.scores).forEach(function (k) { if (!got[k]) got[k] = live.scores[k]; });
      live.scores = got;
      live.fetched = new Date();
      live.error = "";
      live.failedAt = null;
      live.good++;
      storeJSON(CACHE_KEY, { week: L.week, year: seasonYear(), at: Date.now(), scores: got, spreads: live.spreads, kick: live.kick });
      afterScores();
    }).catch(function (e) {
      live.error = e && e.message ? e.message : "no connection";
      live.failedAt = new Date();
    }).then(function () {
      live.busy = false;
      schedule();                          // first, so the page says how often it now looks
      if (!updateBar) render({ quiet: true });
    });
  }
  function retryScores() { fetchScores(); render({ quiet: true }); }
  // A score as ESPN writes it ("24", 24, {value: 24}); null when it isn't one.
  function pointsOf(v) {
    if (v && typeof v === "object") v = v.value != null ? v.value : v.displayValue;
    if (v == null || v === "") return null;
    var n = Number(v);
    return isFinite(n) && n >= 0 ? Math.round(n) : null;
  }
  // How fresh the scores on screen are, from the stored times alone. The
  // thresholds live with the dashboard's (tokens.FRESHNESS), written into the
  // stylesheet; these numbers are only the fallback.
  function freshLimit(live_) {
    var name = live_ ? "--fresh-scores-live-s" : "--fresh-scores-s";
    var v = NaN;
    try { v = Number(getComputedStyle(document.documentElement).getPropertyValue(name)); } catch (e) { /* no styles yet */ }
    return (isFinite(v) && v > 0 ? v : live_ ? 90 : 900) * 1000;
  }
  function clockSec(d) {
    var z = zoneName(d);
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" }) + (z ? " " + z : "");
  }
  function ageWords(ms) {
    var s = Math.max(0, Math.round(ms / 1000));
    if (s < 60) return "just now";
    if (s < 3600) return plural(Math.floor(s / 60), "minute") + " ago";
    return plural(Math.floor(s / 3600), "hour") + " ago";
  }
  function freshness() {
    var on = Object.keys(live.scores).some(function (k) { return live.scores[k].state === "in"; });
    if (!live.fetched) return live.error ? { level: "error", head: "No successful data refresh yet", detail: "Last attempt failed (" + live.error + ")" }
      : { level: "waiting", head: "Fetching scores…", detail: "" };
    var age = Date.now() - live.fetched.getTime();
    var detail = "Last successful update: " + clockSec(live.fetched) +
      (live.failedAt ? " · last attempt " + clockSec(live.failedAt) + " failed (" + live.error + ")" : "");
    if (live.error) return { level: "failed", head: "Refresh failed — showing data from " + clockSec(live.fetched), detail: detail, age: age };
    if (age > freshLimit(on)) return { level: "stale", head: "Scores are " + (age < 60000 ? "under a minute" : ageWords(age).replace(" ago", "")) + " old — last successful update " + clockSec(live.fetched), detail: detail, age: age };
    return { level: "fresh", head: "Updated " + ageWords(age), detail: detail, age: age };
  }
  // A game's card state: its status, and a data warning apart from it (a final stands whatever the feed does now).
  function cardState(x) {
    var status = x.sc && x.sc.off ? "postponed" : x.state === "in" ? "live" : x.state === "post" ? "final" : "upcoming";
    var f = freshness(), warn = status === "final" ? "" : f.level === "error" ? "error" : f.level === "stale" || f.level === "failed" ? "stale" : "";
    return { status: status, warn: warn };
  }
  function warnTag(cs) {
    return cs.warn ? el("span", { class: "dwarn " + cs.warn, title: freshness().head, text: cs.warn === "error" ? "▲ Data error" : "▲ Stale data" }) : null;
  }
  // What went wrong with the score feed, and what still works without it.
  function liveProblem() {
    if (!live.error) return null;
    var retry = { text: live.busy ? "Trying…" : "Try again", go: retryScores };
    if (live.fetched) return stateMsg("Last update failed",
      "Refresh failed — showing scores from " + clockSec(live.fetched) + " (" + live.error + "). It tries again on its own, or now:", retry, "bad");
    return stateMsg("Market feed unavailable",
      "Live scores and betting lines can’t be reached (" + live.error + "). Every pick is still here, and win chances use the pool lines until it’s back.", retry, "bad");
  }
  // ESPN's words, tidied: single spaces, nothing at either end.
  function words(v) { return v == null ? "" : String(v).replace(/\s+/g, " ").trim(); }
  // Who has the ball, where, and what just happened - read only while a game
  // is on. Anything odd in it is left out: it never costs the scores.
  function fieldOf(comp) {
    try {
      var sit = comp.situation;
      if (!sit || typeof sit !== "object") return {};
      var holder = words(sit.possession), poss = "";
      (comp.competitors || []).forEach(function (c) {
        if (holder && (words(c.id) === holder || words(c.team && c.team.id) === holder)) poss = code(c.team && c.team.abbreviation);
      });
      var play = sit.lastPlay && typeof sit.lastPlay === "object" ? words(sit.lastPlay.text) : "";
      return { poss: poss, down: words(sit.downDistanceText || sit.shortDownDistanceText), rz: sit.isRedZone === true,
        play: play.length > 160 ? play.slice(0, 159) + "…" : play, spot: words(sit.possessionText) };
    } catch (e) { return {}; }
  }
  // A team's record, "3-1", from one side of a game.
  function recordOf(c) {
    try {
      var rs = (c && c.records) || [];
      for (var i = 0; i < rs.length; i++) {
        var kind = String((rs[i] && (rs[i].type || rs[i].name)) || "");
        if (kind === "total" || kind === "overall") return words(rs[i].summary);
      }
    } catch (e) { /* no record, then */ }
    return "";
  }
  // The TV network(s) showing a game: "CBS", "FOX / NFLN".
  function tvOf(comp) {
    var out = [];
    function add(n) { n = words(n); if (n && out.indexOf(n) < 0) out.push(n); }
    try {
      (comp.broadcasts || []).forEach(function (b) { ((b && b.names) || []).forEach(add); });
      if (!out.length) (comp.geoBroadcasts || []).forEach(function (b) { add(b && b.media && b.media.shortName); });
    } catch (e) { /* no TV, then */ }
    return out.slice(0, 2).join(" / ");
  }
  // Whether what's on screen follows the scores.
  function followsScores() {
    if (!hasLive()) return false;
    if (state.coach) return true;
    return ["home", "live", "picks", "pools", "me"].indexOf(state.view) >= 0;
  }
  // How long until the next look: a minute while a game is on, two when a
  // kickoff is close, five otherwise; none once every game is final.
  function refreshEvery() {
    var keys = Object.keys(live.scores);
    if (!keys.length) return REFRESH_MS;
    var states = keys.filter(function (k) { return !live.scores[k].off; }).map(function (k) { return live.scores[k].state; });
    if (states.every(function (s) { return s === "post"; })) return 0;
    if (states.some(function (s) { return s === "in"; })) return LIVE_REFRESH_MS;
    var next = nextKickoff();
    if (next && next.at - Date.now() < 20 * 60 * 1000) return SOON_REFRESH_MS;
    return REFRESH_MS;
  }
  // The next look is due a full interval after the last one began - moving
  // around the site doesn't restart the countdown.
  function schedule() {
    clearTimeout(live.timer);
    live.timer = null;
    live.every = refreshEvery();
    if (!followsScores() || !live.every) return;
    live.timer = setTimeout(fetchScores, Math.max(1000, live.lastTry + live.every - Date.now()));
  }
  // On arriving at a page that shows scores: look now if the last look is
  // getting old, otherwise carry on with the countdown.
  function freshen() {
    if (live.busy) return;                 // its finish sets up the next one
    if (followsScores() && refreshEvery() && Date.now() - live.lastTry > 25 * 1000) fetchScores();
    else schedule();
  }
  function everyText() {
    var off = Object.keys(live.scores).some(function (k) { return live.scores[k].off; });
    return live.every === LIVE_REFRESH_MS ? "refreshed every 30 seconds" : live.every === SOON_REFRESH_MS ? "refreshed every 2 minutes"
      : live.every ? "refreshed every 5 minutes" : off ? "every game played is final" : "every game final";
  }
  // Who the pool credits in one game right now: "home", "away", or "" (level or not started).
  function credited(g, sc) {
    if (!sc || sc.state === "pre") return "";
    var homeIsHome = sc.home === g.hc;
    var hs = homeIsHome ? sc.hs : sc.as, as = homeIsHome ? sc.as : sc.hs;
    if (g.line != null && g.fav) {
      var need = Math.ceil(g.line - 1e-9);
      var favHome = g.fav === g.hc;
      var favMargin = favHome ? hs - as : as - hs;
      var favWins = favMargin >= need;
      return favHome ? (favWins ? "home" : "away") : (favWins ? "away" : "home");
    }
    if (hs === as) return "";
    return hs > as ? "home" : "away";
  }
  function liveTally() {
    var L = DATA.live;
    var games = L.games.map(function (g) {
      var sc = live.scores[gameKey(g.hc, g.ac)] || null;
      var side = credited(g, sc);
      var homeIsHome = sc && sc.home === g.hc;
      return { g: g, sc: sc, state: sc ? sc.state : "pre", credit: side === "home" ? g.hc : side === "away" ? g.ac : "",
        hs: sc ? (homeIsHome ? sc.hs : sc.as) : null, as: sc ? (homeIsHome ? sc.as : sc.hs) : null,
        kick: live.kick[gameKey(g.hc, g.ac)] || null };
    });
    function lostBy(team) {
      for (var i = 0; i < games.length; i++) {
        var x = games[i];
        if (x.hs == null) continue;
        if (x.g.hc === team) return { by: x.as - x.hs, state: x.state };
        if (x.g.ac === team) return { by: x.hs - x.as, state: x.state };
      }
      return null;
    }
    var season = {};
    DATA.players.forEach(function (p) { season[p.name] = p; });
    var rows = L.coaches.map(function (c) {
      var done = 0, now = 0, left = 0, bl = 0, blLive = 0;
      c.picks.forEach(function (pick, i) {
        var x = games[i];
        if (!pick || !x) return;
        if (x.state === "pre") { left++; return; }
        if (x.credit === pick) { now++; if (x.state === "post") done++; }
      });
      c.bl.forEach(function (team) {
        var r = lostBy(team);
        if (r && r.by >= 15) { if (r.state === "post") bl++; else blLive++; }
      });
      var sui = "";
      var p = season[c.name];
      if (c.sui && p && p.suicide.alive) {
        var gi = -1;
        games.forEach(function (x, i) { if (x.g.hc === c.sui || x.g.ac === c.sui) gi = i; });
        var x = games[gi];
        sui = !x || x.state === "pre" ? "pending" : x.credit === c.sui ? (x.state === "post" ? "safe" : "ahead")
          : x.state === "post" ? "out" : x.credit ? "behind" : "level";
      }
      return { c: c, now: now + bl + blLive, games: now, final: done + bl, left: left, bl: bl + blLive,
        season: (p ? p.wins : 0) + now + bl + blLive, sui: sui, place: p ? p.place : null };
    });
    rows.sort(function (a, b) { return b.now - a.now || b.season - a.season || a.c.name.localeCompare(b.c.name); });
    return { games: games, rows: rows };
  }
  // Where the week is: "recap" (nothing being played), "preview" (picks in,
  // no kickoff yet), "gameday" (under way) or "final" (all over, not yet entered).
  function phase(t) {
    if (!hasLive()) return "recap";
    t = t || liveTally();
    if (weekOver(t)) return "final";
    if (t.games.some(function (x) { return x.state !== "pre"; })) return "gameday";
    return "preview";
  }
  function gamesOn(t) { return t.games.filter(function (x) { return x.state === "in"; }).length; }
  function weekOver(t) {
    return t.games.length && t.games.every(function (x) { return x.state === "post"; });
  }
  function nextKickoff() {
    if (!hasLive()) return null;
    var best = null, now = Date.now();
    DATA.live.games.forEach(function (g) {
      var key = gameKey(g.hc, g.ac), sc = live.scores[key], at = live.kick[key];
      if (!at || (sc && (sc.state !== "pre" || sc.off)) || at < now - 5 * 60 * 1000) return;
      if (!best || at < best.at) best = { at: at, g: g };
    });
    return best;
  }
  // A countdown, only ever said beside the time itself and only in the last
  // hour and a half: "in 40 min". Nothing further out, where the time says more.
  function untilText(at) {
    var mins = Math.round((at - Date.now()) / 60000);
    if (mins > 90) return "";
    if (mins <= 0) return "any minute";
    if (mins < 60) return "in " + mins + " min";
    return "in 1 h" + (mins - 60 ? " " + (mins - 60) + " min" : "");
  }
  // Kickoff times, said exactly, in the viewer's own time: the day (today,
  // tomorrow or its name), the date, the time and the zone.
  function zoneName(d) {
    try {
      var parts = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" }).formatToParts(d);
      for (var i = 0; i < parts.length; i++) if (parts[i].type === "timeZoneName") return parts[i].value;
    } catch (e) { /* an older browser: no zone */ }
    return "";
  }
  function kickDay(d, long) {
    var a = new Date(d.getTime()), b = new Date();
    a.setHours(0, 0, 0, 0); b.setHours(0, 0, 0, 0);
    var days = Math.round((a - b) / 864e5);
    return days === 0 ? "Today" : days === 1 ? "Tomorrow" : d.toLocaleDateString("en-US", { weekday: long ? "long" : "short" });
  }
  function kickDate(d) { return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }); }
  // "Sun, Oct 18 · 1:00 PM EDT" - on a game card
  function kickFull(at) {
    var d = new Date(at), z = zoneName(d);
    return kickDay(d) + ", " + kickDate(d) + " · " + clock(d) + (z ? " " + z : "");
  }
  // "1:00 PM EDT" today, "Sunday 1:00 PM EDT" in the days ahead, with the
  // date too when it isn't this week - in a headline
  function kickLong(at) {
    var d = new Date(at), z = zoneName(d), day = kickDay(d, true), far = at - Date.now() > 6 * 864e5;
    return (day === "Today" ? "" : day + (far ? ", " + kickDate(d) : "") + " ") + clock(d) + (z ? " " + z : "");
  }
  // The headline's kickoff: the time, then the countdown once it's close.
  function kickNode(at) {
    return el("span", { class: "kicktime" }, [kickLong(at), " ",
      el("span", { class: "until", "data-until": String(at), text: untilText(at) })]);
  }
  // Keep "in 40 min" true without redrawing the page.
  setInterval(function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-until]"), function (node) {
      node.textContent = untilText(Number(node.getAttribute("data-until")));
    });
  }, 30 * 1000);

