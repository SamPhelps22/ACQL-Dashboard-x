  // ---- the menu: every page under its section, sharing, the theme ------------------------
  var themeChoice = null;   // this visit's choice, for a phone that won't keep it
  function themePref() {
    var v = themeChoice != null ? themeChoice : stored(THEME_KEY);
    return v === "light" || v === "dark" ? v : "auto";
  }
  function gameOn() { return hasLive() && !!live.fetched && gamesOn(liveTally()) > 0; }
  // Text size: the whole page scaled, so every figure and chart grows with the words.
  var TEXT_SIZES = [["", "Normal"], ["l", "Larger"], ["xl", "Largest"]];
  var textChoice = null;
  function textPref() {
    var v = textChoice != null ? textChoice : stored(TEXT_KEY);
    return v === "l" || v === "xl" ? v : "";
  }
  function applyTheme() {
    var pref = themePref(), root = document.documentElement;
    if (textPref()) root.setAttribute("data-text", textPref()); else root.removeAttribute("data-text");
    var want = pref === "auto" ? (gameOn() ? "dark" : "") : pref;
    if (want) root.setAttribute("data-theme", want); else root.removeAttribute("data-theme");
  }
  var sheetWasOpen = false;
  function sheet() {
    if (!state.sheet) { sheetWasOpen = false; return null; }
    var opening = !sheetWasOpen;
    sheetWasOpen = true;
    function close() {
      state.sheet = false;
      render();
      var b = document.getElementById("more-btn");
      if (b) b.focus();
    }
    var pref = themePref(), here = currentView();
    var items = sections().filter(function (s) { return s.id !== "home"; }).map(function (s) {
      return el("div", { class: "group" }, [el("b", { text: s.label }), el("div", { class: "links" }, s.pages.map(function (v) {
        return el("a", { href: "#" + v, "aria-current": v === here ? "page" : null, onclick: navTo(v) },
          [icon(VIEWS[v].icon), el("span", { text: VIEWS[v].tab || VIEWS[v].label })]);
      }))]);
    });
    if (hasMe()) {
      items.push(el("button", { class: "item", type: "button", onclick: function () { state.sheet = false; render(); shareWeek(state.me); } },
        [icon("share"), el("span", {}, ["Share my week", el("small", { text: "A picture of your week for the group chat" })])]));
    }
    items.push(el("a", { class: "item", href: MAIN_SITE, target: "_blank", rel: "noopener" },
      [icon("share"), el("span", {}, ["The league's main site", el("small", { text: "users.erols.com/merpdave" })])]));
    var themes = el("div", { class: "themes" }, [
      el("b", { text: "Colours" }),
      el("div", { class: "seg", role: "group", "aria-label": "Colours" }, [["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]].map(function (o) {
        return el("button", { type: "button", "aria-pressed": pref === o[0] ? "true" : "false",
          onclick: function () { themeChoice = o[0]; store(THEME_KEY, o[0] === "auto" ? "" : o[0]); render(); }, text: o[1] });
      })),
      el("span", { class: "note", text: "Auto follows your phone, and goes dark while games are on." }),
      el("b", { text: "Text size" }),
      el("div", { class: "seg", role: "group", "aria-label": "Text size" }, TEXT_SIZES.map(function (o) {
        return el("button", { type: "button", "aria-pressed": textPref() === o[0] ? "true" : "false",
          onclick: function () { textChoice = o[0]; store(TEXT_KEY, o[0]); render(); }, text: o[1] });
      }))
    ].concat(DATA.texts ? [
      el("b", { text: "Text alerts" }),
      el("a", { class: "btn", href: "mailto:" + DATA.texts + "?subject=" + encodeURIComponent("ACQL text alerts") +
        "&body=" + encodeURIComponent("Add me to the text alerts.\nNumber: \nCarrier: "), text: "Email to sign up" }),
      el("span", { class: "note", text: "Get a text before picks close and when the week's results are in. Email your number and carrier to " + DATA.texts + " (any carrier but AT&T)." })
    ].concat(DATA.alerts ? [el("a", { class: "note", href: DATA.alerts, target: "_blank", rel: "noopener", text: "Or get them in the free ntfy app" })] : [])
    : DATA.alerts ? [
      el("b", { text: "Phone alerts" }),
      el("a", { class: "btn", href: DATA.alerts, target: "_blank", rel: "noopener", text: "Get alerts on your phone" }),
      el("span", { class: "note", text: "Install the free ntfy app, then subscribe from this link: a reminder before picks close, and when the week's results are in." })
    ] : []));
    var box = el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": "Menu", tabindex: "-1",
      onkeydown: function (e) { if (e.key === "Escape") close(); } }, [
      el("div", { class: "sh-head" }, [el("h2", { text: "Menu" }),
        el("button", { class: "btn", type: "button", "aria-label": "Close", onclick: close }, [icon("close")])])
    ].concat(items, [themes]));
    if (opening) setTimeout(function () { if (box.isConnected) box.focus(); }, 0);
    return [el("div", { class: "scrim", onclick: close }), box];
  }

