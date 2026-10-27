  // ---- share my week: a picture for the group chat -----------------------------------------
  // Drawn on the phone itself - no server - in the site's on-air colours. It
  // opens the phone's share sheet where there is one, and offers the file to
  // save everywhere else.
  function shareWeek(name) {
    var p = player(name);
    if (!p) return;
    var W = 1080, H = 1350;
    var canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    var g = canvas.getContext("2d");
    var DISPLAY = '"Big Shoulders", "Big Shoulders Display", "Barlow Condensed", "Arial Narrow", sans-serif';
    var BODY = '"Barlow", "Segoe UI", system-ui, sans-serif';
    var fontsReady = document.fonts && document.fonts.load ? Promise.all([
      document.fonts.load("800 120px " + DISPLAY), document.fonts.load("600 40px " + BODY)
    ]).catch(function () {}) : Promise.resolve();
    var img = new Image();
    var crestReady = new Promise(function (resolve) {
      img.onload = resolve;
      img.onerror = resolve;
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(CREST.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '));
    });
    var timeout = new Promise(function (resolve) { setTimeout(resolve, 1500); });
    Promise.race([Promise.all([fontsReady, crestReady]), timeout]).then(function () {
      draw();
      canvas.toBlob(function (blob) { if (blob) offer(blob); }, "image/png");
    });

    function fit(text, size, weight, family, room) {
      var s = size;
      g.font = weight + " " + s + "px " + family;
      while (g.measureText(text).width > room && s > size * 0.45) { s -= 2; g.font = weight + " " + s + "px " + family; }
      return s;
    }
    function draw() {
      g.fillStyle = "#0a0c0b";
      g.fillRect(0, 0, W, H);
      // a gold slash in the corner, like the lower third's
      g.save();
      g.fillStyle = "rgba(232, 178, 58, 0.14)";
      g.beginPath(); g.moveTo(W - 300, 0); g.lineTo(W - 160, 0); g.lineTo(W - 420, H); g.lineTo(W - 560, H); g.closePath(); g.fill();
      g.restore();
      g.fillStyle = "#efb32f";
      g.fillRect(0, 0, 14, H);
      if (img.complete && img.naturalWidth) g.drawImage(img, 70, 64, 120, 134);
      g.textBaseline = "alphabetic";
      g.fillStyle = "#f3f6fa";
      g.font = "800 84px " + DISPLAY;
      g.fillText("ACQL", 214, 150);
      var w1 = g.measureText("ACQL ").width;
      g.fillStyle = "#efb32f";
      g.fillText(String(seasonYear()), 214 + w1, 150);
      g.fillStyle = "#a9b3ab";
      g.font = "600 30px " + BODY;
      g.fillText("Arm Chair Quarterback League", 216, 192);

      g.fillStyle = "#f3f6fa";
      var size = fit(p.name, 150, 800, DISPLAY, W - 140);
      g.fillText(p.name, 70, 380);

      // this week, or the last one played
      var lines = weekLines(p);
      g.fillStyle = "#151b17";
      g.fillRect(70, 440, W - 140, 330);
      g.fillStyle = "#efb32f";
      g.fillRect(70, 440, W - 140, 8);
      g.fillStyle = "#efb32f";
      g.font = "700 36px " + BODY;
      g.fillText(lines.kicker, 110, 520);
      g.fillStyle = "#f3f6fa";
      fit(lines.big, 120, 800, DISPLAY, W - 220);
      g.fillText(lines.big, 110, 640);
      g.fillStyle = "#c5cdc6";
      g.font = "500 38px " + BODY;
      g.fillText(lines.small, 110, 718);

      // the season, the side pools
      var s = p.suicide;
      var rows = [
        ["Season", plural(p.wins, "win") + (p.place != null ? ", " + ordinal(p.place) + " of " + DATA.entrants : "") + (p.move ? (p.move > 0 ? "  ▲" : "  ▼") + Math.abs(p.move) : "")],
        ["Suicide pool", s.alive ? "still in" : s.out ? "out in week " + s.out : "not in it"],
        ["Big Loser", plural(p.big_loser || 0, "point")]
      ];
      var y = 880;
      rows.forEach(function (r) {
        g.fillStyle = "#a9b3ab";
        g.font = "600 34px " + BODY;
        g.fillText(r[0], 70, y);
        g.fillStyle = "#f3f6fa";
        g.font = "800 60px " + DISPLAY;
        g.fillText(r[1], 70, y + 64);
        y += 140;
      });
      g.fillStyle = "#a9b3ab";
      g.font = "500 28px " + BODY;
      var site = LIVE.hosted ? location.origin + location.pathname : "";
      g.fillText(site.replace(/^https?:\/\//, "").replace(/\/$/, ""), 70, H - 50);
      return size;
    }
    function offer(blob) {
      var file = null;
      var fileName = "ACQL " + seasonYear() + " - " + p.name.replace(/[^\w .-]+/g, "") + ".png";
      try { file = new File([blob], fileName, { type: "image/png" }); } catch (e) { file = null; }
      var url = URL.createObjectURL(blob);
      var canShare = !!(file && navigator.canShare && navigator.canShare({ files: [file] }));
      var view = el("div", { class: "shareview", role: "dialog", "aria-modal": "true", "aria-label": "Share " + p.name + "’s week",
        onclick: function (e) { if (e.target === view) close(); }, onkeydown: function (e) { if (e.key === "Escape") close(); }, tabindex: "-1" }, [
        el("div", { class: "inner" }, [
          el("img", { src: url, alt: p.name + "’s week, as a picture" }),
          el("div", { class: "acts" }, [
            canShare ? el("button", { class: "btn primary", type: "button", onclick: function () {
              navigator.share({ files: [file], title: "ACQL", text: p.name + "’s week" }).catch(function () { /* closed: fine */ });
            } }, [icon("share"), "Share"]) : null,
            el("a", { class: "btn" + (canShare ? "" : " primary"), href: url, download: fileName, text: "Save picture" }),
            el("button", { class: "btn", type: "button", text: "Close", onclick: close })
          ]),
          el("p", { class: "note", style: "color:#c5cdc6;text-align:center", text: "On a phone you can also press and hold the picture to save it." })
        ])
      ]);
      function close() { view.remove(); URL.revokeObjectURL(url); }
      document.body.appendChild(view);
      view.focus();
    }
  }
  // What the picture says about the week: the one being played if it has
  // started, else the last one finished.
  function weekLines(p) {
    if (hasLive() && live.fetched) {
      var t = liveTally();
      var r = t.rows.filter(function (x) { return x.c.name === p.name; })[0];
      if (r && t.games.some(function (x) { return x.state !== "pre"; })) {
        var place = livePlace(t, r.c.name);
        var over = weekOver(t);
        return { kicker: "Week " + DATA.live.week + (over ? ", final" : " live"),
          big: plural(r.now, "win") + ", " + ordinal(place),
          small: over ? (place === 1 ? "Won the week" : "of " + t.rows.length) : pct(simulate(t).chance[p.name] || 0) + " to win the week" };
      }
    }
    var w = weekData(DATA.through_week);
    var mine = w ? w.scores.filter(function (s) { return s.name === p.name; })[0] : null;
    if (!mine) return { kicker: "After week " + DATA.through_week, big: plural(p.wins, "win"), small: "this season" };
    var rank = weekPlace(w, mine.name);
    var won = w.winners.indexOf(p.name) >= 0;
    return { kicker: "Week " + w.week, big: plural(mine.total, "win") + ", " + ordinal(rank) + (won ? " ★" : ""),
      small: won ? "Won the week" + (w.payout_each ? ", " + money(w.payout_each) : "") : "of " + w.scores.length + ", the pool averaged " + w.average.toFixed(1) };
  }

