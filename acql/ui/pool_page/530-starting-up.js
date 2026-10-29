  // ---- starting up -----------------------------------------------------------------
  // Whatever DATA the page shows, the things worked out from it start afresh.
  function dataChanged() {
    poolProfile = null;
    formCache = null;
    historyData = null;
    historyError = "";
    simCache = { key: "", sim: null };
  }
  function route(hash) {
    var wanted = String(hash || "").replace("#", "");
    state.coach = "";
    if (wanted.indexOf("coach=") === 0) {
      try { state.coach = decodeURIComponent(wanted.slice(6)); } catch (e) { state.coach = ""; }
    } else if (wanted.indexOf("vs=") === 0) {
      // a shared matchup: #vs=First%20coach&Second%20coach
      var both = wanted.slice(3).split("&");
      try { state.a = decodeURIComponent(both[0] || ""); state.b = decodeURIComponent(both[1] || ""); } catch (e) { state.a = state.b = ""; }
      state.view = "h2h";
    } else if (wanted) {
      var q = wanted.indexOf("?"), base_ = q >= 0 ? wanted.slice(0, q) : wanted;
      var v = ALIASES[base_] || base_;
      if (VIEWS[v]) state.view = v;
      // a week kept in the address: only one this season has (never a guess)
      var wk = q >= 0 ? (/(?:^|&)w=([^&]+)/.exec(wanted.slice(q + 1)) || [])[1] : null;
      if (wk && v === "weeks" && weekData(Number(wk))) state.week = Number(wk);
      var rid = q >= 0 ? (/(?:^|&)r=([^&]+)/.exec(wanted.slice(q + 1)) || [])[1] : null;
      if (v === "rules") state.rule = rid || "";
      if (wk && v === "factions") state.fxWeek = wk === "season" ? "season" : (weekData(Number(wk)) ? Number(wk) : state.fxWeek);
    }
    if (!available(state.view)) state.view = "home";
  }
  route(location.hash);
  window.addEventListener("hashchange", function () { route(location.hash); render({ top: true }); freshen(); });
  if (live.fetched && hasLive()) lastSeen = seen(liveTally());
  if (hasLive()) setTimeout(fetchScores, 0);
  render();
  bootSequence();
  // Saved to a phone's home screen, the site opens at once and works with no signal.
  if (LIVE.hosted === "web" && "serviceWorker" in navigator &&
      (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function () { /* the site works the same without it */ });
    });
  }

