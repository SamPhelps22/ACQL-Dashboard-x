  // ---- home: the front page follows the week -------------------------------------------
  // Results in and no new picks yet: the week's story. Picks in, no kickoff
  // yet: how the pool picked. Games on: the week as it happens. All over but
  // not yet entered: who won it.
  function homeView() {
    var t = hasLive() ? liveTally() : null;
    var ph = phase(t);
    var kids = [behindNote(), notice(), deadlineBanner()];
    if (ph === "gameday" || ph === "preview") kids.push(slateStrip(t));
    if (ph === "gameday") kids = kids.concat(gamedayHome(t));
    else if (ph === "final") kids = kids.concat(finalHome(t));
    else if (ph === "preview") kids = kids.concat(previewHome(t));
    else kids = kids.concat(recapHome());
    return el("div", { class: "view", "data-view": "home", "data-phase": ph }, kids);
  }

