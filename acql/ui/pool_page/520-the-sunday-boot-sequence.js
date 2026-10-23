  // ---- the Sunday boot sequence ----------------------------------------------------------
  // The first open of a visit while a week is being played powers up like a
  // control room: the crest, then the score feed, the slate and the cards
  // checked off. The page is already drawn under it; it is gone within two
  // seconds, any tap, click or key ends it at once, and with reduced motion
  // (or once already seen this visit) it never shows.
  var BOOT_KEY = "acql-booted";
  function bootSequence() {
    if (!hasLive() || state.coach) return;
    try {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      if (sessionStorage.getItem(BOOT_KEY)) return;
      sessionStorage.setItem(BOOT_KEY, "1");
    } catch (e) { return; }
    var L = DATA.live, started = Date.now(), done = false;
    function line(label) {
      var v = el("span", { class: "v", text: "…" });
      return { node: el("li", {}, [el("span", { class: "k", text: label }), v]), v: v };
    }
    var feed = line("Score feed"), slate = line("Slate"), cards = line("Cards");
    var box = el("div", { class: "boot", "aria-hidden": "true" }, [
      el("div", { class: "core" }, [el("div", { class: "mark" }, [crest(), el("span", { class: "ring" }), el("span", { class: "ring two" })]),
        el("div", { class: "word" }, ["ACQL", el("small", { text: "Week " + L.week })]),
        el("ul", { class: "checks" }, [feed.node, slate.node, cards.node]),
        el("span", { class: "skip", text: "Tap to skip" })])
    ]);
    function finish() {
      if (done) return;
      done = true;
      clearInterval(poll);
      box.classList.add("out");
      ["pointerdown", "keydown"].forEach(function (k) { document.removeEventListener(k, finish, true); });
      setTimeout(function () { box.remove(); }, 260);
    }
    function tick() {
      var gone = Date.now() - started;
      if (gone > 250) { slate.v.textContent = plural(L.games.length, "game"); slate.node.className = "ok"; }
      if (gone > 450) { cards.v.textContent = L.coaches.length + " in"; cards.node.className = "ok"; }
      if (gone > 650 && live.fetched && !live.error) { feed.v.textContent = "connected"; feed.node.className = "ok"; }
      else if (gone > 650 && live.error) { feed.v.textContent = live.fetched ? "saved scores" : "offline"; feed.node.className = "warn"; }
      else if (gone > 1300) { feed.v.textContent = "still connecting"; feed.node.className = "warn"; }
      var ready = gone > 650 && (live.fetched || live.error) && gone > 1000;
      if ((ready && gone > 1150) || gone > 1700) finish();
    }
    var poll = setInterval(tick, 60);
    ["pointerdown", "keydown"].forEach(function (k) { document.addEventListener(k, finish, true); });
    document.body.appendChild(box);
  }

