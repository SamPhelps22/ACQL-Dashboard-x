  // ---- putting it together ----------------------------------------------------------
  function go(view) {
    view = ALIASES[view] || view;
    if (!available(view)) view = "home";
    state.view = view;
    state.coach = "";
    state.sheet = false;
    freshen();
    if (view === "h2h") pair();
    try { history.replaceState(null, "", view === "h2h" ? vsHash() : "#" + view); } catch (e) { /* not allowed here */ }
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
      default: return homeView();
    }
  }
