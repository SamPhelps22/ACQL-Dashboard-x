  // ---- the week, replayed ------------------------------------------------------------
  // Every kickoff, score and final whistle of a finished week, in order, with
  // the pool's scores after each - "if it ended there", the live page's rule.
  // The dashboard works it all out (replay.py); the page only shows it. On the
  // website each week's is its own small file, fetched when the week is opened.
  var replays = {};            // week -> { state: "loading" | "ready" | "failed", data }
  var replayPos = {};          // week -> the frame on screen
  var replayTimer = null;
  function replayOf(w) {
    var info = w && w.replay;
    if (!info) return null;
    if (info.data) return { state: "ready", data: info.data };
    var got = replays[w.week];
    if (got) return got;
    got = replays[w.week] = { state: "loading" };
    if (!info.file || typeof fetch !== "function") { got.state = "failed"; return got; }
    fetch(info.file + "?v=" + encodeURIComponent(info.v || ""), { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    }).then(function (d) {
      got.state = "ready";
      got.data = d;
    }).catch(function () {
      got.state = "failed";
    }).then(function () {
      if (state.view === "weeks" && state.week === w.week) render({ quiet: true });
    });
    return got;
  }
  var DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz";
  function frameTotals(f) {
    var out = [];
    for (var i = 0; i < f[8].length; i++) out.push(DIGITS.indexOf(f[8].charAt(i)));
    return out;
  }
  function frameDay(f) { return new Date(f[0] * 1000).toLocaleDateString([], { weekday: "short" }); }
  function frameTime(f) { var d = new Date(f[0] * 1000); return d.toLocaleDateString([], { weekday: "short" }) + " " + clock(d); }
  function quarterText(period, clockText) {
    if (!period) return "";
    return (period >= 5 ? "OT" : "Q" + period) + (clockText ? " " + clockText : "");
  }
  // What happened at a frame, as the readout's two lines.
  function frameWords(rep, i) {
    var f = rep.frames[i], g = rep.games[f[1]];
    var line = g.a + " " + f[3] + " – " + f[4] + " " + g.h;
    if (f[2] === "k") return { head: "Kickoff: " + g.a + " at " + g.h, play: g.line != null ? "Pool line: " + teamFull(g.fav) + " by " + g.line : "Pool line: straight up" };
    if (f[2] === "f") return { head: f[7] + ": " + line, play: g.w ? "Credited to " + teamFull(g.w) : "Nobody credited" };
    if (f[2] === "o") return { head: "The pool’s own scores", play: "Where the week finished on the pool’s sheet." };
    return { head: line + " · " + quarterText(f[5], f[6]), play: f[7] };
  }
  // Each coach's place at a frame (ties share it).
  function placesAt(totals) {
    return totals.map(function (v) { return 1 + totals.filter(function (o) { return o > v; }).length; });
  }
  function leadersAt(totals) {
    var top = Math.max.apply(null, totals);
    var out = [];
    totals.forEach(function (v, i) { if (v === top) out.push(i); });
    return out;
  }

  function replayChart(rep, width, pos, focus) {
    var H = width < 520 ? 210 : 250, narrow = width < 520;
    var padL = 34, padR = narrow ? 92 : 128, padT = 12, padB = 26;
    var frames = rep.frames, n = frames.length;
    var totals = frames.map(frameTotals);
    var behind = totals.map(function (t) { var top = Math.max.apply(null, t); return t.map(function (v) { return top - v; }); });
    var hi = 3;
    behind.forEach(function (row) { row.forEach(function (v) { if (v > hi) hi = v; }); });
    hi = Math.min(hi, 12);
    function X(i) { return padL + (n > 1 ? i * (width - padL - padR) / (n - 1) : 0); }
    function Y(v) { return padT + Math.min(v, hi) / hi * (H - padT - padB); }
    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + H, width: width, height: H, role: "img",
      "aria-label": "Wins behind the week’s leader after every score" });
    var grid = svgEl("g", { class: "grid" });
    ticksFor(0, hi, 3).forEach(function (v) {
      grid.appendChild(svgEl("line", { x1: padL, x2: width - padR + 8, y1: Y(v), y2: Y(v) }));
      grid.appendChild(svgEl("text", { x: padL - 6, y: Y(v) + 4, "text-anchor": "end", text: v === 0 ? "lead" : "−" + v }));
    });
    svg.appendChild(grid);
    // the days along the bottom, where each begins; the steps are one per score,
    // not by the clock, so a day with few scores would put its name under the
    // next day's - that one moves right to clear it (or is left off at the edge)
    var last = "", free = 0;
    frames.forEach(function (f, i) {
      var d = frameDay(f);
      if (d === last) return;
      last = d;
      svg.appendChild(svgEl("line", { class: "day", x1: X(i), x2: X(i), y1: padT, y2: H - padB }));
      var lx = Math.max(X(i) + 3, free), lw = d.length * 8;
      if (lx + lw > width) return;
      free = lx + lw + 6;
      svg.appendChild(svgEl("text", { x: lx, y: H - 8, text: d }));
    });
    var top = rep.coaches.slice(0, 1).concat(rep.coaches.filter(function (c, i) { return i > 0 && totals[n - 1][i] === totals[n - 1][0]; }));
    var marked = {};
    top.forEach(function (c) { marked[c] = "strong"; });
    (rep.beatsFor || []).forEach(function (c) { if (!marked[c]) marked[c] = "mid"; });
    if (focus) marked[focus] = "me";
    function path(ci) {
      var d = "";
      behind.forEach(function (row, i) {
        d += i ? "H" + X(i).toFixed(1) + "V" + Y(row[ci]).toFixed(1) : "M" + X(0).toFixed(1) + " " + Y(row[ci]).toFixed(1);
      });
      return d;
    }
    var order = { ctx: 0, mid: 1, strong: 2, me: 3 };
    rep.coaches.map(function (c, ci) { return { c: c, ci: ci, role: marked[c] || "ctx" }; })
      .sort(function (a, b) { return order[a.role] - order[b.role]; })
      .forEach(function (ln) { svg.appendChild(svgEl("path", { class: "ln " + ln.role, d: path(ln.ci) })); });
    // end labels: names that finish level share one; one that would collide is left off
    var ends = {};
    rep.coaches.forEach(function (c, ci) {
      if (!marked[c]) return;
      var v = behind[n - 1][ci];
      svg.appendChild(svgEl("circle", { class: "end " + marked[c], cx: X(n - 1), cy: Y(v), r: 4 }));
      (ends[v] = ends[v] || []).push(c);
    });
    var taken = [];
    Object.keys(ends).map(Number).sort(function (a, b) { return a - b; }).forEach(function (v) {
      var yy = Y(v), who_ = ends[v];
      if (taken.some(function (t) { return Math.abs(t - yy) < 14; })) return;
      taken.push(yy);
      var mineHere = who_.indexOf(focus) >= 0;
      var text = who_.length > 1 ? who_[0] + " +" + (who_.length - 1) : who_[0];
      if (who_.length === 2 && (who_[0] + who_[1]).length < (narrow ? 14 : 24)) text = who_[0] + " & " + who_[1];
      if (text.length > (narrow ? 14 : 24)) text = text.slice(0, narrow ? 13 : 23) + "…";
      svg.appendChild(svgEl("text", { class: "lbl" + (mineHere ? " me" : ""), x: X(n - 1) + 8, y: yy + 4, text: text }));
    });
    var marker = svgEl("line", { class: "now", x1: X(pos), x2: X(pos), y1: padT - 4, y2: H - padB });
    svg.appendChild(marker);
    var hit = svgEl("rect", { class: "hit scrub", x: padL, y: 0, width: Math.max(1, width - padL - padR), height: H });
    function pick(evt) {
      var box = svg.getBoundingClientRect();
      var px = (evt.clientX - box.left) * (width / box.width);
      var i = Math.round((px - padL) / Math.max(1, width - padL - padR) * (n - 1));
      return Math.max(0, Math.min(n - 1, i));
    }
    var dragging = false;
    hit.addEventListener("pointerdown", function (e) { dragging = true; replayGo(rep, pick(e)); });
    hit.addEventListener("pointermove", function (e) { if (dragging) replayGo(rep, pick(e)); });
    ["pointerup", "pointerleave", "pointercancel"].forEach(function (k) { hit.addEventListener(k, function () { dragging = false; }); });
    svg.appendChild(hit);
    rep.moveMarker = function (i) { marker.setAttribute("x1", X(i)); marker.setAttribute("x2", X(i)); };
    return svg;
  }

  // Move the replay to frame i: the marker, the slider and the readout, no redraw.
  function replayGo(rep, i) {
    i = Math.max(0, Math.min(rep.frames.length - 1, i));
    replayPos[rep.week] = i;
    if (rep.moveMarker) rep.moveMarker(i);
    if (rep.slider && Number(rep.slider.value) !== i) rep.slider.value = String(i);
    if (rep.fill) rep.fill(i);
  }
  function stopReplay() {
    if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
  }

  function replayModule(w) {
    var got = replayOf(w);
    if (!got) return null;
    var info = w.replay;
    var aside = plural(info.scores || 0, "score") + " · lead changed hands " + plural(info.lead_changes || 0, "time");
    if (got.state === "loading") return module("The week, replayed", aside, [el("div", { class: "chart-wait" }, [el("p", { class: "note", text: "Loading the replay…" })])], { "data-card": "replay" });
    if (got.state === "failed") return module("The week, replayed", aside, [stateMsg("Replay unavailable", "This week’s replay file couldn’t be loaded - check the connection. The week’s results are unaffected.",
      { text: "Try again", go: function () { delete replays[w.week]; render({ quiet: true }); } }, "bad")], { "data-card": "replay" });
    var rep = got.data;
    var n = rep.frames.length;
    if (!n) return null;
    rep.beatsFor = (w.beats || []).filter(function (b) { return b.kind === "bad-beat" || b.kind === "front-runner"; }).map(function (b) { return b.who; });
    var start = replayPos[w.week];
    if (start == null || start >= n) start = n - 1;
    replayPos[w.week] = start;
    var focus = highlighted();
    var mine = rep.coaches.indexOf(focus);

    var when = el("span", { class: "rp-when" });
    var head = el("b", { class: "rp-head" });
    var play = el("span", { class: "rp-play" });
    var board = el("ol", { class: "rp-board", "aria-live": "polite" });
    rep.fill = function (i) {
      var f = rep.frames[i];
      var words = frameWords(rep, i);
      when.textContent = frameTime(f);
      head.textContent = words.head;
      play.textContent = words.play;
      var t = frameTotals(f), places = placesAt(t);
      var before = i ? frameTotals(rep.frames[i - 1]) : t;
      var order = t.map(function (v, ci) { return ci; }).sort(function (a, b) { return t[b] - t[a] || rep.coaches[a].localeCompare(rep.coaches[b]); });
      var shown = order.slice(0, 5);
      if (mine >= 0 && shown.indexOf(mine) < 0) shown.push(mine);
      board.textContent = "";
      shown.forEach(function (ci) {
        var moved = t[ci] - before[ci];
        board.appendChild(el("li", { class: ci === mine ? "me" : null }, [
          el("span", { class: "pos", text: (places.filter(function (p) { return p === places[ci]; }).length > 1 ? "T" : "") + places[ci] }),
          el("span", { class: "nm", text: rep.coaches[ci] }),
          el("span", { class: "tot num", text: String(t[ci]) }),
          el("span", { class: "mv " + (moved > 0 ? "up" : moved < 0 ? "down" : ""), text: moved > 0 ? "+" + moved : moved < 0 ? "−" + (-moved) : "" })
        ]));
      });
      var lead = leadersAt(t);
      rep.leadText.textContent = lead.length === 1 ? "Leading: " + rep.coaches[lead[0]] + " with " + t[lead[0]]
        : lead.length <= 3 ? "Level at the top on " + t[lead[0]] + ": " + listNames(lead.map(function (ci) { return rep.coaches[ci]; }))
        : plural(lead.length, "coach", "coaches") + " level at the top on " + t[lead[0]];
    };
    rep.leadText = el("span", { class: "rp-lead" });
    var slider = el("input", { type: "range", min: "0", max: String(n - 1), step: "1", value: String(start), class: "rp-slider",
      "aria-label": "Move through the week", oninput: function (e) { stopReplay(); replayGo(rep, Number(e.target.value)); } });
    rep.slider = slider;
    var playBtn = el("button", { class: "btn rp-play-btn", type: "button", text: "▶ Play" });
    playBtn.addEventListener("click", function () {
      if (replayTimer) { stopReplay(); playBtn.textContent = "▶ Play"; return; }
      var i = replayPos[w.week] >= n - 1 ? 0 : replayPos[w.week];
      var step = Math.max(35, Math.round(14000 / n));
      playBtn.textContent = "❚❚ Pause";
      replayGo(rep, i);
      replayTimer = setInterval(function () {
        if (!slider.isConnected) { stopReplay(); return; }
        i++;
        replayGo(rep, i);
        if (i >= n - 1) { stopReplay(); playBtn.textContent = "▶ Play"; }
      }, step);
    });
    function nudge(by) { return function () { stopReplay(); playBtn.textContent = "▶ Play"; replayGo(rep, (replayPos[w.week] || 0) + by); }; }
    rep.week = w.week;
    var box = el("div", { class: "replay" }, [
      chartBox("replay-" + w.week, 230, function (width) { return replayChart(rep, width, replayPos[w.week], focus); }),
      el("div", { class: "rp-controls" }, [playBtn,
        el("button", { class: "btn", type: "button", "aria-label": "Back one", text: "‹", onclick: nudge(-1) }),
        slider,
        el("button", { class: "btn", type: "button", "aria-label": "On one", text: "›", onclick: nudge(1) })]),
      el("div", { class: "rp-read" }, [el("div", { class: "rp-moment" }, [when, head, play]),
        el("div", { class: "rp-standing" }, [rep.leadText, board])]),
      rep.adjusted && rep.adjusted.length ? el("p", { class: "note", text: "The last step puts in the pool’s own scores for " + listNames(rep.adjusted) + ", whose card the replay only partly knew." }) : null,
      el("p", { class: "note", text: "Each step is a kickoff, a score or a final whistle. The scores show where the week stood at that moment. The line is wins behind the leader." })
    ]);
    rep.fill(start);
    return module("The week, replayed", aside, [box], { "data-card": "replay", id: "replay-card" });
  }

