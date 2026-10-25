  // ---- teams: their colours, for the badges ---------------------------------------
  // Each team's own two colours, as a small badge with its letters - the only
  // place team colour appears.
  var TEAM_COLORS = {
    ari: ["#97233f", "#ffb612"], atl: ["#a71930", "#101820"], bal: ["#241773", "#9e7c0c"], buf: ["#00338d", "#c60c30"],
    car: ["#0085ca", "#101820"], chi: ["#0b162a", "#c83803"], cin: ["#fb4f14", "#101820"], cle: ["#311d00", "#ff3c00"],
    dal: ["#003594", "#869397"], den: ["#fb4f14", "#002244"], det: ["#0076b6", "#b0b7bc"], gb: ["#203731", "#ffb612"],
    hou: ["#03202f", "#a71930"], ind: ["#002c5f", "#a2aaad"], jax: ["#006778", "#d7a22a"], kc: ["#e31837", "#ffb81c"],
    lv: ["#101820", "#a5acaf"], lac: ["#0080c6", "#ffc20e"], lar: ["#003594", "#ffa300"], mia: ["#008e97", "#fc4c02"],
    min: ["#4f2683", "#ffc62f"], ne: ["#002244", "#c60c30"], no: ["#d3bc8d", "#101820"], nyg: ["#0b2265", "#a71930"],
    nyj: ["#125740", "#ffffff"], phi: ["#004c54", "#a5acaf"], pit: ["#ffb612", "#101820"], sea: ["#002244", "#69be28"],
    sf: ["#aa0000", "#b3995d"], tb: ["#d50a0a", "#34302b"], ten: ["#0c2340", "#4b92db"], was: ["#5a1414", "#ffb612"]
  };
  var CODE_OF = {};
  Object.keys(DATA.teams || {}).forEach(function (c) { CODE_OF[String(DATA.teams[c]).toLowerCase()] = c; });
  function codeOf(team) {
    var t = String(team || "").toLowerCase();
    if (TEAM_COLORS[t]) return t;
    return CODE_OF[t] || "";
  }
  function teamFull(code) { return (DATA.teams || {})[code] || String(code || "").toUpperCase(); }
  function lightColour(hex) {
    var h = hex.replace("#", "");
    var r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
    function f(c) { return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
    // 0.2 is where dark and white letters read equally well; above it, dark wins
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b) > 0.2;
  }
  // The team's logo, from ESPN's image server (the same place the live scores
  // come from). Any logo that fails to load removes itself, leaving the badge.
  var LOGO_CODES = { was: "wsh" };
  function logoUrl(code) {
    // ESPN's resizer: a 120px copy is plenty for a badge (the 500px original is ~15x the bytes);
    // if it ever fails, the image removes itself and the colour badge stands alone
    return "https://a.espncdn.com/combiner/i?img=/i/teamlogos/nfl/500/" + (LOGO_CODES[code] || code) + ".png&h=120&w=120";
  }
  function badge(team, big) {
    var code = codeOf(team);
    var c = TEAM_COLORS[code] || ["#556373", "#8a968c"];
    var tag = el("span", { class: "tb" + (big ? " lg" : ""), title: teamFull(code) || String(team || ""),
      style: "--c1:" + c[0] + ";--c2:" + c[1] + ";--ct:" + (lightColour(c[0]) ? "#101820" : "#ffffff"),
      text: code ? code.toUpperCase() : String(team || "?").slice(0, 3).toUpperCase() });
    if (!code) return tag;
    var img = document.createElement("img");
    img.className = "tl" + (big ? " lg" : "");
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.src = logoUrl(code);
    img.onerror = function () { if (img.parentNode) img.parentNode.removeChild(img); };
    return el("span", { class: "logo" }, [img, tag]);
  }
  function teamTag(team) {
    return el("span", { class: "team" }, [badge(team), el("b", { text: teamFull(codeOf(team)) || team })]);
  }

