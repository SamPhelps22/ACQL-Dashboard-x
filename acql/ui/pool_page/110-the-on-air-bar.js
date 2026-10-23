  // ---- the on-air bar ---------------------------------------------------------------
  function topbar() {
    var t = hasLive() ? liveTally() : null;
    var on = t ? gamesOn(t) : 0;
    // the week's tag is the short way to the week itself
    var pill;
    if (t) {
      var over = live.fetched && weekOver(t);
      pill = el("a", { class: "weekpill" + (on ? " live" : ""), href: "#live", id: "week-pill", onclick: navTo("live"),
        text: "Week " + DATA.live.week + (on ? " live" : over ? " final" : "") });
    } else {
      pill = el("a", { class: "weekpill", href: "#weeks", id: "week-pill", onclick: navTo("weeks"), text: "After week " + DATA.through_week });
    }
    var me = hasMe() ? state.me : "";
    var chip = el("a", { class: "mechip" + (me ? "" : " empty"), href: "#me", id: "me-chip", onclick: navTo("me"),
      "aria-label": me ? "Your page, " + me : "Pick your name" },
      [el("span", { class: "initials", style: me ? avatarStyle(me) : null, text: me ? initials(me) : "?" }), el("span", { class: "who", text: me || "Pick your name" })]);
    return el("header", { class: "topbar" }, [el("div", { class: "inner" + (pill.textContent.length > 8 ? " tight" : "") }, [
      el("a", { class: "brandmark", href: "#home", onclick: navTo("home"), "aria-label": "ACQL, home" }, [
        crest(), el("span", { class: "wordmark" }, ["ACQL", el("span", { class: "yr", text: String(seasonYear()) })])
      ]),
      pill,
      el("nav", { class: "desknav", "aria-label": "Sections" }, sections().map(function (s) {
        return el("a", { href: "#" + s.first, id: "nav-" + s.id, "aria-current": s.on ? "page" : null, onclick: navTo(s.first),
          text: s.label });
      })),
      el("div", { class: "right" }, [
        el("button", { class: "searchbtn", type: "button", id: "find-btn", "aria-label": "Find a coach, a week or a page",
          title: "Find a coach, a week or a page (press /)", onclick: function () { openFinder(); } },
          [icon("search"), el("span", { class: "lbl", text: "Search" }), el("kbd", { text: "/" })]),
        el("div", { id: "owner" }),
        chip,
        el("button", { class: "iconbtn menubtn", type: "button", id: "more-btn", "aria-label": "Menu", "aria-haspopup": "dialog",
          onclick: function () { state.sheet = true; render(); } }, [icon("menu")])
      ])
    ])]);
  }

