  // ---- the places on the site, and how to get to them ------------------------------
  // Every page there is. `tab` is what a page is called among its section's
  // pages, where that isn't its own name.
  var VIEWS = {
    home: { label: "Home", icon: "home" },
    live: { label: "Live", icon: "live", about: "The week as it happens: scores and every card" },
    picks: { label: "Picks", icon: "picks", about: "Everyone’s picks this week, side by side" },
    weeks: { label: "Past weeks", icon: "weeks", about: "Results, stories and replays of every finished week" },
    standings: { label: "Standings", tab: "Table", icon: "standings", about: "The season’s table and the title race" },
    charts: { label: "Charts", icon: "charts", about: "The season race, title odds and the power map" },
    h2h: { label: "Head-to-head", icon: "h2h", about: "Any two coaches, pick by pick" },
    factions: { label: "Factions", icon: "h2h", about: "Who picks with whom, and who goes it alone" },
    teams: { label: "Teams", icon: "standings", about: "How the pool has backed each team, and how it went" },
    history: { label: "History", icon: "history", about: "Champions and records" },
    rules: { label: "Rulebook", tab: "Rules", icon: "history", about: "How the pool is scored, ranked and paid - searchable" },
    power: { label: "Power Rankings", tab: "Power", icon: "standings", about: "An unofficial ranking of recent form, beside the official table" },
    connections: { label: "Connection Map", tab: "Connections", icon: "h2h", about: "Coaches linked by their picks and weekly scores" },
    awards: { label: "Awards", icon: "history", about: "The season’s trophies, and who holds them" },
    pools: { label: "Side pools", icon: "pools", about: "The suicide pool and the Big Losers" },
    money: { label: "Money", icon: "money", about: "Who’s up and who owes" },
    me: { label: "Me", icon: "me" }
  };
  var ALIASES = { week: "weeks", table: "standings" };
  function available(view) {
    if (view === "live" || view === "picks") return hasLive();
    if (view === "h2h" || view === "factions" || view === "teams") return DATA.weeks.some(function (w) { return w.picks; });
    if (view === "money") return !!DATA.money;
    if (view === "rules") return !!(DATA.rulebook && DATA.rulebook.rules);
    if (view === "power") return !!(DATA.power && DATA.power.weeks && DATA.power.weeks.length);
    if (view === "connections") return DATA.weeks.some(function (w) { return w.scores && w.scores.length; }) && DATA.players.length > 1;
    return !!VIEWS[view];
  }
  // every page, in the order the search lists them
  function pageList() {
    return ["home", "live", "picks", "weeks", "standings", "charts", "h2h", "factions", "teams", "power", "connections", "awards", "history", "rules", "pools", "money"].filter(available);
  }
  // The few sections the bars show, and the pages each one holds. Me is its
  // own button beside them. Each section answers one kind of question: what's
  // on this week, where everyone officially stands, digging into the numbers,
  // and the side competitions.
  var SECTIONS = [
    { id: "home", label: "Home", icon: "home", views: ["home"] },
    { id: "week", label: "This week", icon: "weeks", views: ["live", "picks", "weeks"] },
    { id: "standings", label: "Standings", icon: "standings", views: ["standings", "awards", "history", "rules"] },
    { id: "explore", label: "Explore", icon: "charts", views: ["charts", "h2h", "factions", "teams", "power", "connections"] },
    { id: "pools", label: "Pools & money", short: "Pools", icon: "pools", views: ["pools", "money"] }
  ];
  // The sections as the bars draw them: the pages each has now, where it
  // leads, and whether the viewer is in it. With no week being played the
  // week's section is only the weeks gone by, and says so.
  function sections() {
    var here = currentView();
    return SECTIONS.map(function (s) {
      var pages = s.views.filter(available);
      var quiet = s.id === "week" && !hasLive();
      return { id: s.id, icon: s.icon, pages: pages, first: pages[0], on: pages.indexOf(here) >= 0,
        label: quiet ? "Weeks" : s.label, short: quiet ? "Weeks" : s.short || s.label,
        live: s.id === "week" && gameOn() };
    }).filter(function (s) { return s.pages.length; });
  }
  function currentView() {
    if (state.coach) return isMe(state.coach) ? "me" : "";
    return state.view;
  }
  function navTo(view) {
    return function (e) { e.preventDefault(); go(view); };
  }

