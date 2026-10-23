  // ---- Me: pick your name once, then your page --------------------------------------------
  function meView() {
    if (hasMe()) return coachView(player(state.me));
    var filterText = state.filter || "";
    var all = names().slice().sort(function (a, b) { return a.localeCompare(b); });
    var shown = all.filter(function (n) { return !filterText || n.toLowerCase().indexOf(filterText.toLowerCase()) >= 0; });
    var input = el("input", { class: "filter", id: "name-filter", type: "search", placeholder: "Find your name", "aria-label": "Find your name", value: filterText,
      oninput: function (e) {
        state.filter = e.target.value;
        var grid = document.getElementById("name-grid");
        if (!grid) return;
        Array.prototype.forEach.call(grid.children, function (b) {
          b.hidden = !!state.filter && b.getAttribute("data-name").toLowerCase().indexOf(state.filter.toLowerCase()) < 0;
        });
      } });
    return el("div", { class: "view", "data-view": "me" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Who are you?" })]),
      el("p", { class: "lede", text: "Pick your name and the site puts you first: your week on the home page, your rows highlighted, your own page here. It’s remembered on this phone only." }),
      input,
      el("div", { class: "namegrid", id: "name-grid" }, all.map(function (n) {
        return el("button", { type: "button", "data-name": n, hidden: shown.indexOf(n) < 0,
          onclick: function () { state.me = n; remember(n); state.filter = ""; noteMyChanceSoon(); render({ top: true }); } },
          [el("span", { class: "initials", style: avatarStyle(n), text: initials(n) }), el("span", { text: n })]);
      }))
    ]);
  }
  function noteMyChanceSoon() { if (hasLive() && live.fetched) setTimeout(function () { noteMyChance(liveTally()); }, 0); }

