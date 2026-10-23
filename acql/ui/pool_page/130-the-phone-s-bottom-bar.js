  // ---- the phone's bottom bar -----------------------------------------------------------
  function bottombar() {
    return el("nav", { class: "bottombar", "aria-label": "Sections" }, sections().map(function (s) {
      return el("a", { href: "#" + s.first, id: "bar-" + s.id, "aria-current": s.on ? "page" : null, onclick: navTo(s.first) },
        [icon(s.icon), el("span", { text: s.short }), s.live ? el("span", { class: "livedot", title: "Games on now" }) : null]);
    }).concat([
      el("a", { href: "#me", id: "bar-me", "aria-current": currentView() === "me" ? "page" : null, onclick: navTo("me") },
        [icon("me"), el("span", { text: VIEWS.me.label })])
    ]));
  }

