  // ---- the announcement, the footer ------------------------------------------------------
  // The week is over on ESPN's scoreboard, but these standings were built
  // before it ended: the computer that publishes the site hasn't since (it may
  // be off). The live scores come straight from ESPN; the standings don't.
  var BEHIND_AFTER = 11 * 3600 * 1000;     // kickoff of the last game + about 11 hours
  function standingsBehind() {
    if (!hasLive() || !(DATA.live.week > DATA.through_week)) return null;
    var t = liveTally(), last = 0;
    for (var i = 0; i < t.games.length; i++) {
      var x = t.games[i];
      if (x.state !== "post") return null;
      if (x.kick && x.kick > last) last = x.kick;
    }
    return last && Date.now() - last > BEHIND_AFTER ? DATA.live.week : null;
  }
  function behindNote() {
    var week = standingsBehind();
    if (!week) return null;
    return el("aside", { class: "notice behind", "aria-label": "Standings not updated yet" }, [
      el("b", { text: "Week " + week + " is over, but the standings here are still after week " + DATA.through_week + "." }),
      el("span", { class: "when", text: "They catch up when the pool's computer next updates the site. Scores on the Live page come straight from ESPN." })
    ]);
  }
  function notice() {
    var n = DATA.note;
    if (!n || !n.text) return null;
    var posted = n.posted ? new Date(n.posted + "T12:00:00") : null;
    return el("aside", { class: "notice", "aria-label": "Announcement" }, [
      el("b", { text: n.text }),
      posted && !isNaN(posted.getTime()) ? el("span", { class: "when", text: "Posted " + posted.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }) }) : null
    ]);
  }
  // The league's own long-running site, linked from the menu and the footer.
  var MAIN_SITE = "http://users.erols.com/merpdave/ACQL2007x.html";
