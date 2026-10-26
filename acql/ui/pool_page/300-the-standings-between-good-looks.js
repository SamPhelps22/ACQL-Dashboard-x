  // ---- the standings, between good looks: who moved, who gained -----------------------
  var standBase = null, standMove = null, standAt = null, poolSaid = {};
  // What a change in the table means, said once: a new leader, the viewer's place.
  function poolNews(before, now) {
    function leaders(tab) { return Object.keys(tab).filter(function (k) { return tab[k].place === 1; }).sort(); }
    var said = [], a = leaders(now), b = leaders(before);
    if (a.length && a.join() !== b.join())
      said.push({ title: a.length === 1 ? a[0] + " takes the lead" : a.slice(0, 3).join(" and ") + " share the lead", tone: "pool" });
    if (state.me && now[state.me] && before[state.me] && now[state.me].place !== before[state.me].place) {
      var was = before[state.me].place, is = now[state.me].place;
      said.push({ title: "You " + (is < was ? "climb" : "drop") + " to " + ordinal(is) + " (from " + ordinal(was) + ")", tone: "mine" });
    }
    said.forEach(function (f) {
      if (poolSaid[f.tone + f.title]) return;
      poolSaid[f.tone + f.title] = 1;
      f.text = ""; f.at = new Date();
      swings.unshift(f);
    });
    swings = swings.slice(0, 30);
  }
  function standingsAccept(t) {
    if (!live.good) return;
    var now = {};
    t.rows.forEach(function (r) {
      now[r.c.name] = { place: 1 + t.rows.filter(function (o) { return o.now > r.now; }).length, pts: r.now };
    });
    var move = { moved: {}, gained: {} }, any = false;
    if (standBase) Object.keys(now).forEach(function (k) {
      var b = standBase[k];
      if (!b) return;
      if (b.place !== now[k].place) { move.moved[k] = [b.place, now[k].place]; any = true; }
      if (now[k].pts > b.pts) { move.gained[k] = [b.pts, now[k].pts]; any = true; }
    });
    if (standBase && any) poolNews(standBase, now);
    if (!standBase || any) standAt = live.fetched;
    standBase = now;
    standMove = any && cine.open ? move : null;      // played by an open Cinema mode once, or not at all
  }

