  // ---- the standings, between good looks: who moved, who gained -----------------------
  var standBase = null, standMove = null, standAt = null;
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
    if (!standBase || any) standAt = live.fetched;
    standBase = now;
    standMove = any && cine.open ? move : null;      // played by an open Cinema mode once, or not at all
  }

