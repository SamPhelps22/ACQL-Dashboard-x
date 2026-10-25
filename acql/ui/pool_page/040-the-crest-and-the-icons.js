  // ---- the crest and the icons -------------------------------------------------------
  // The league's crest: an armchair with a football on its seat, on a shield.
  // The same drawing as the dashboard's home-screen icon (previewcard.CREST).
  var CREST = '<svg viewBox="0 0 100 112" role="img" aria-label="ACQL crest">' +
    '<path d="M8 6H92V52C92 80 70 98 50 108C30 98 8 80 8 52Z" fill="#1d6a44" stroke="#efb32f" stroke-width="5" stroke-linejoin="round"/>' +
    '<g fill="#f4f7f2" stroke="#0a0c0b" stroke-width="1.6">' +
    '<rect x="30" y="20" width="40" height="38" rx="8"/><rect x="21" y="46" width="13" height="26" rx="5"/>' +
    '<rect x="66" y="46" width="13" height="26" rx="5"/><rect x="31" y="58" width="38" height="13" rx="4"/>' +
    '<rect x="26" y="70" width="6" height="10" rx="1.5"/><rect x="68" y="70" width="6" height="10" rx="1.5"/></g>' +
    '<g transform="rotate(-14 50 54)"><ellipse cx="50" cy="54" rx="13" ry="7.5" fill="#efb32f" stroke="#0a0c0b" stroke-width="1.8"/>' +
    '<g stroke="#f4f7f2" stroke-linecap="round" stroke-width="1.6"><line x1="44" y1="54" x2="56" y2="54"/>' +
    '<line x1="46" y1="51.8" x2="46" y2="56.2"/><line x1="50" y1="51.8" x2="50" y2="56.2"/><line x1="54" y1="51.8" x2="54" y2="56.2"/></g></g></svg>';
  // The league's logo, written into the page by the dashboard (brand.py);
  // without it - an old copy, a page saved by hand - the drawn crest stands in.
  var LOGO = "__POOL_LOGO__";
  function hasLogo() { return LOGO.indexOf("data:") === 0; }
  if (hasLogo()) document.documentElement.style.setProperty("--logo", 'url("' + LOGO + '")');
  function logoImg(cls) { return el("img", { class: cls, src: LOGO, alt: "", decoding: "async" }); }
  // Every coach wears a colour of their own, worked out from the name.
  function avatarStyle(name) {
    var h = 0, s = String(name || "");
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return "background:hsl(" + (h % 360) + ",52%,38%);color:#fff";
  }
  function crest() {
    if (hasLogo()) return logoImg("crest logo");
    var span = el("span", { class: "crest" });
    span.innerHTML = CREST;            // a fixed drawing: no data in it
    return span.firstChild;
  }
  var ICONS = {
    search: '<circle cx="10.6" cy="10.6" r="6"/><path d="M15.1 15.1l5 5"/>',
    up: '<path d="M12 19V5.5M5.5 11.5 12 5l6.5 6.5"/>',
    home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/><path d="M10 19.5v-5h4v5"/>',
    live: '<circle cx="12" cy="12" r="2.4"/><path d="M8 8a5.7 5.7 0 0 0 0 8M16 8a5.7 5.7 0 0 1 0 8M5.1 5.1a9.8 9.8 0 0 0 0 13.8M18.9 5.1a9.8 9.8 0 0 1 0 13.8"/>',
    standings: '<path d="M4 6.5h16M4 12h11M4 17.5h7"/>',
    pools: '<circle cx="12" cy="8.2" r="3"/><path d="M6.6 19.6v-.8a5.4 5.4 0 0 1 10.8 0v.8"/><circle cx="4.9" cy="10.6" r="1.9"/><path d="M1.8 18.4v-.4a3.2 3.2 0 0 1 2.5-3.1"/><circle cx="19.1" cy="10.6" r="1.9"/><path d="M22.2 18.4v-.4a3.2 3.2 0 0 0-2.5-3.1"/>',
    me: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20.2v-.8a7 7 0 0 1 14 0v.8"/>',
    weeks: '<rect x="4" y="5.2" width="16" height="14.8" rx="2"/><path d="M4 9.8h16"/><path d="M8.5 3.2v3.6"/><path d="M15.5 3.2v3.6"/><path d="M8 13.4h1.2"/><path d="M11.4 13.4h1.2"/><path d="M14.8 13.4h1.2"/><path d="M8 16.6h1.2"/><path d="M11.4 16.6h1.2"/>',
    picks: '<path d="M4 7.5l2 2 3.5-4M4 16l2 2 3.5-4M13 8h7M13 16.5h7"/>',
    h2h: '<path d="M6 8h12l-3-3M18 16H6l3 3"/>',
    charts: '<path d="M4 19V5M4 19h16M7.5 15l4-4.5 3 2.5 5-6"/>',
    history: '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 5.6H5.2v1.2A3.2 3.2 0 0 0 8.3 10"/><path d="M16 5.6h2.8v1.2A3.2 3.2 0 0 1 15.7 10"/><path d="M12 13v3.6"/><path d="M9.6 16.6h4.8l.8 3.4H8.8z"/>',
    money: '<rect x="3" y="6.6" width="18" height="10.8" rx="1.6"/><circle cx="12" cy="12" r="2.6"/><path d="M6.2 9.8v4.4"/><path d="M17.8 9.8v4.4"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    share: '<path d="M12 15V4M8 8l4-4 4 4"/><path d="M5 13v6h14v-6"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4.2"/><circle cx="12" cy="12" r="0.9" fill="currentColor"/>',
    flame: '<path d="M12 21c-3.9 0-6.5-2.6-6.5-6.1 0-3.4 2.4-5.2 3.6-8.4.4 2 1.6 3.2 2.8 3.6.3-2.6 1.6-5 3.6-6.6-.2 2.8 3 5.4 3 9.6 0 4.3-2.7 7.9-6.5 7.9z"/><path d="M12 21c-1.6 0-2.8-1.2-2.8-2.9 0-1.8 1.4-2.7 2.1-4.2.9 1.4 3.5 2.3 3.5 4.3 0 1.6-1.2 2.8-2.8 2.8z"/>',
    snow: '<path d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9"/><path d="M9.6 4.6 12 6.6l2.4-2M9.6 19.4l2.4-2 2.4 2"/>',
    steady: '<path d="M4.5 19.5h15"/><rect x="5.5" y="10" width="3" height="9.5" rx=".6"/><rect x="10.5" y="7.5" width="3" height="12" rx=".6"/><rect x="15.5" y="9" width="3" height="10.5" rx=".6"/>',
    climb: '<path d="M4 18l5.5-5.5 3.5 3.5L20 9"/><path d="M14.5 9H20v5.5"/>',
    drop: '<path d="M4 6l5.5 5.5 3.5-3.5L20 15"/><path d="M14.5 15H20V9.5"/>',
    shield: '<path d="M12 3.5l7 2.6v5.2c0 4.4-3 7.9-7 9.2-4-1.3-7-4.8-7-9.2V6.1z"/><path d="M9 12l2.2 2.2L15.2 10"/>',
    spoon: '<ellipse cx="15.5" cy="8.2" rx="3.6" ry="4.8" transform="rotate(40 15.5 8.2)"/><path d="M12.6 11.4 4.5 19.5"/>',
    crown: '<path d="M4 8l3.8 3.4L12 5.5l4.2 5.9L20 8l-1.6 10H5.6z"/><path d="M5.8 20.5h12.4"/>',
    theme: '<circle cx="12" cy="12" r="7.6"/><path d="M12 4.4a7.6 7.6 0 0 1 0 15.2z" fill="{colour}"/>'
  };
  // The drawings the site shares with the dashboard (acql/ui/iconset.py), written in
  // when the site is published; the ones above stand in for a page saved by hand.
  var SHARED_ICONS = "__POOL_ICONS__";
  try { var shared = JSON.parse(SHARED_ICONS); for (var k in shared) ICONS[k] = shared[k]; } catch (e) { /* not published from the dashboard */ }
  function icon(name) {
    var span = el("span", {});
    span.innerHTML = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + ICONS[name] + "</svg>";
    return span.firstChild;
  }

