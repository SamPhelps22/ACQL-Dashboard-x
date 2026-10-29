  // ---- putting it together ----------------------------------------------------------
  // A page's address, with the week chosen on it when that isn't the latest,
  // so a refresh or a shared link opens the same week (#weeks?w=4,
  // #factions?w=season).
  function viewHash(view) {
    if (view === "h2h") return vsHash();
    if (view === "weeks" && state.week && state.week !== DATA.through_week) return "#weeks?w=" + state.week;
    if (view === "factions" && state.fxWeek) return "#factions?w=" + state.fxWeek;
    if (view === "rules" && state.rule) return "#rules?r=" + state.rule;
    return "#" + view;
  }
  function syncHash() {
    if (state.coach || state.view === "h2h" || document.documentElement.classList.contains("lm-on")) return;
    // only the site's own pages' addresses: a mode's (#timemachine?...) is the mode's to read
    var now = location.hash.replace("#", ""), base_ = now.split("?")[0];
    if (base_ && !VIEWS[ALIASES[base_] || base_]) return;
    var want = viewHash(state.view);
    if (location.hash !== want) { try { history.replaceState(null, "", want); } catch (e) { /* not allowed here */ } }
  }
  function go(view) {
    view = ALIASES[view] || view;
    if (!available(view)) view = "home";
    state.view = view;
    state.coach = "";
    state.sheet = false;
    freshen();
    if (view === "h2h") pair();
    try { history.replaceState(null, "", viewHash(view)); } catch (e) { /* not allowed here */ }
    render({ top: true });
  }
  function openCoach(name) {
    state.coach = name;
    state.sheet = false;
    try { history.replaceState(null, "", "#coach=" + encodeURIComponent(name)); } catch (e) { /* not allowed here */ }
    render({ top: true });
    freshen();
  }
  function closeCoach() {
    state.coach = "";
    try { history.replaceState(null, "", "#" + state.view); } catch (e) { /* not allowed here */ }
    render({ top: true });
    freshen();
  }
  function viewNode() {
    var coach = state.coach ? player(state.coach) : null;
    if (state.coach && !coach) state.coach = "";
    if (coach) return coachView(coach);
    switch (state.view) {
      case "live": return liveView();
      case "picks": return picksView();
      case "standings": return standingsView();
      case "pools": return poolsView();
      case "me": return meView();
      case "weeks": return weeksView();
      case "h2h": return h2hView();
      case "factions": return factionsView();
      case "teams": return teamsView();
      case "charts": return chartsView();
      case "history": return historyView();
      case "awards": return awardsView();
      case "money": return moneyView();
      case "rules": return rulesView();
      case "power": return powerView();
      case "connections": return mapView();
      default: return homeView();
    }
  }
