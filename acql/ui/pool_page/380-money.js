  // ---- money --------------------------------------------------------------------
  function moneyView() {
    var rows = DATA.players.slice().sort(function (a, b) { return (b.net || 0) - (a.net || 0) || a.name.localeCompare(b.name); });
    return el("div", { class: "view", "data-view": "money" }, [
      el("div", { class: "pagehead" }, [el("h1", { text: "Money" }),
        el("span", { class: "note", text: DATA.money === "stats" ? "From the pool’s standings sheet" : "From the pool’s weekly sheet" })]),
      moneyChartModule(),
      module("Who’s up", null, [scroller(el("table", { id: "money-table" }, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "Coach" }), el("th", { class: "n", text: "Won" }),
          el("th", { class: "n", text: "Owe" }), el("th", { class: "n", text: "Net" })])]),
        el("tbody", {}, rows.map(function (p) {
          var net = p.net || 0;
          return el("tr", { class: isMe(p.name) ? "me" : null }, [
            el("td", { class: "coach" }, [who(p.name)]),
            el("td", { class: "n num", text: money(p.won) }),
            el("td", { class: "n num", text: money(p.paid) }),
            el("td", { class: "n num " + (net > 0 ? "up" : net < 0 ? "down" : "flat"), text: money(p.net) })
          ]);
        }))
      ]))])
    ]);
  }

