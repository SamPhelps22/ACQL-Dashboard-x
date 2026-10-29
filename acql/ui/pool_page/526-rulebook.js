  // ---- the rulebook: every rule the pool's code applies, searchable ------------------
  // The rules come from acql/pool/rulebook.py (DATA.rulebook): each names where
  // it is enforced, and the ones nobody has written down say so. #rules?r=<id>
  // opens one rule; other pages link here with ruleLink() instead of repeating it.
  function rulebookData() { return DATA.rulebook && DATA.rulebook.rules ? DATA.rulebook : null; }
  function ruleById(id) {
    var rb = rulebookData();
    return rb ? rb.rules.filter(function (r) { return r.id === id; })[0] || null : null;
  }
  function ruleLink(id, text) {
    if (!ruleById(id)) return null;
    return el("a", { class: "more-link rule-link", href: "#rules?r=" + id, onclick: function (e) {
      e.preventDefault(); state.rule = id; go("rules");
    }, text: text || "How this is worked out" });
  }
  var RULE_STATUS = { "verified": "Verified", "on record": "On record", "unverified": "Not verified" };
  function ruleMatches(r, q) {
    if (!q) return true;
    var hay = [r.title, r.rule, r.applies, r.how, r.example, r.exceptions].join(" ").toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) >= 0; });
  }
  function rulesView() {
    var rb = rulebookData();
    var head = el("div", { class: "pagehead" }, [el("h1", { text: "Rulebook" })]);
    if (!rb) return el("div", { class: "view", "data-view": "rules" }, [head,
      stateMsg("The rulebook isn't in this copy of the site", "It is built with the site; it will be back at the next update.")]);
    var season = state.ruleSeason || rb.seasons[0];
    var cat = state.ruleCat || "";
    var q = state.ruleQ || "";
    var search = el("input", { type: "search", class: "filter rb-search", placeholder: "Search the rules (e.g. tie, line, suicide)",
      "aria-label": "Search the rules", value: q, oninput: function (e) {
        state.ruleQ = e.target.value; drawList();
      } });
    var seasons = rb.seasons.concat(["earlier"]);
    var seasonPick = el("label", { class: "note" }, ["Season ", el("select", { class: "filter", "aria-label": "Season", onchange: function (e) {
      state.ruleSeason = e.target.value; render();
    } }, seasons.map(function (s) {
      return el("option", { value: s, text: s === "earlier" ? "Earlier seasons" : s, selected: s === season });
    }))]);
    var cats = el("div", { class: "weeks rb-cats", role: "group", "aria-label": "Rule category" },
      [{ id: "", label: "All" }].concat(rb.categories).map(function (c) {
        return el("button", { type: "button", "aria-pressed": cat === c.id ? "true" : "false", text: c.label,
          onclick: function () { state.ruleCat = c.id; render(); } });
      }));
    var list = el("div", { class: "rb-list", id: "rb-list", "aria-live": "polite" });
    function drawList() {
      list.textContent = "";
      if (season === "earlier") {
        list.appendChild(stateMsg("No earlier rulebook on file",
          "Only the " + rb.seasons[0] + " rules are documented. They are not applied to seasons before it, and earlier seasons' rules have not been verified."));
        return;
      }
      var q2 = state.ruleQ || "";
      var shown = rb.rules.filter(function (r) { return (!cat || r.category === cat) && ruleMatches(r, q2); });
      if (!shown.length) { list.appendChild(stateMsg("No rule matches", "Try another word, or choose All.")); return; }
      rb.categories.forEach(function (c) {
        var mine = shown.filter(function (r) { return r.category === c.id; });
        if (!mine.length) return;
        list.appendChild(el("h2", { class: "rb-cat", text: c.label }));
        mine.forEach(function (r) { list.appendChild(ruleCard(r)); });
      });
    }
    drawList();
    var counts = {};
    rb.rules.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
    var key = el("p", { class: "note rb-key" }, Object.keys(rb.statuses).map(function (s) {
      return el("span", { class: "rb-status-line" }, [el("span", { class: "rb-badge rb-" + s.replace(/\s+/g, "-"), text: RULE_STATUS[s] || s }),
        " " + rb.statuses[s] + " (" + (counts[s] || 0) + ")"]);
    }));
    setTimeout(function () {
      if (!state.rule) return;
      var open = document.getElementById("rule-" + state.rule);
      if (open) { open.open = true; open.scrollIntoView({ block: "start" }); }
    }, 0);
    return el("div", { class: "view", "data-view": "rules" }, [head,
      el("p", { class: "lede", text: "How the pool is scored, ranked and paid - only rules the pool's own scoring applies. Tap a rule for the details and a made-up example." }),
      el("div", { class: "rb-tools" }, [search, seasonPick]), cats, key, list]);
  }
  function ruleCard(r) {
    var rows = [["The rule", r.rule], ["When it applies", r.applies], ["How it's worked out", r.how],
      ["Example (hypothetical)", r.example], ["Exceptions", r.exceptions], ["Where it's enforced", r.source]]
      .filter(function (x) { return x[1] && x[1] !== "-"; });
    var links = (r.links || []).filter(function (v) { return VIEWS[v] && available(v); }).map(function (v) {
      return moreLink(VIEWS[v].label, v);
    });
    var copy = el("button", { class: "linkish", type: "button", text: "Copy a link to this rule", onclick: function (e) {
      var link = location.href.split("#")[0] + "#rules?r=" + r.id, b = e.target;
      try { navigator.clipboard.writeText(link).then(function () { b.textContent = "Link copied"; }); } catch (x) { b.textContent = link; }
    } });
    return el("details", { class: "rb-rule" + (r.status === "unverified" ? " rb-unverified" : ""), id: "rule-" + r.id,
      open: state.rule === r.id ? true : null, ontoggle: function (e) {
        if (e.target.open) { state.rule = r.id; try { history.replaceState(null, "", "#rules?r=" + r.id); } catch (x) { /* not allowed */ } }
      } }, [
      el("summary", {}, [el("span", { class: "rb-title", text: r.title }),
        el("span", { class: "rb-badge rb-" + r.status.replace(/\s+/g, "-"), text: RULE_STATUS[r.status] || r.status })]),
      el("dl", { class: "rb-detail" }, rows.reduce(function (acc, x) {
        return acc.concat([el("dt", { text: x[0] }), el("dd", { text: x[1] })]);
      }, [])),
      el("div", { class: "rb-links" }, links.concat([copy]))
    ]);
  }
