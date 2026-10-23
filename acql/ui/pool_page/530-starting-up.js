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
      var v = ALIASES[wanted] || wanted;
      if (VIEWS[v]) state.view = v;
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

