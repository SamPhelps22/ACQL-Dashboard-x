  // ---- a section's own pages: the tabs at the top of each of them -----------------------
  function subnav() {
    var here = currentView();
    var s = sections().filter(function (x) { return x.on; })[0];
    if (!s || s.pages.length < 2) return null;
    var nav = el("nav", { class: "subnav", "aria-label": s.label, "data-section": s.id }, s.pages.map(function (v) {
      return el("a", { href: "#" + v, id: "sub-" + v, "aria-current": v === here ? "page" : null, onclick: navTo(v) },
        [v === "live" && s.live ? el("span", { class: "dot-live" }) : null, VIEWS[v].tab || VIEWS[v].label]);
    }));
    // on a screen too narrow for every tab, bring the current one into view
    setTimeout(function () {
      var a = nav.querySelector('[aria-current="page"]');
      if (!a || !nav.isConnected || nav.scrollWidth <= nav.clientWidth) return;
      var past = a.getBoundingClientRect().right - nav.getBoundingClientRect().right;
      if (past > 0) nav.scrollLeft += past + 16;
    }, 0);
    return nav;
  }

