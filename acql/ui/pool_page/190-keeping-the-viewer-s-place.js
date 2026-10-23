  // ---- keeping the viewer's place when the page redraws itself ---------------------------
  // A redraw replaces every element, so whatever had the keyboard's focus is
  // found again afterwards: by its id, its chart, or what it says.
  function sameAs(key) {
    return Array.prototype.filter.call(app.getElementsByTagName(key.tag), function (n) {
      return (n.getAttribute("class") || "") === key.cls && (n.getAttribute("href") || "") === key.href &&
        (n.getAttribute("aria-label") || (n.textContent || "").trim()) === key.label;
    });
  }
  function focusKey() {
    var a = document.activeElement;
    if (!a || a === document.body || !app.contains(a)) return null;
    if (a.id) return { id: a.id };
    var chart = a.closest ? a.closest("[data-chart]") : null;
    if (chart && a.getAttribute("class") === "hit") return { chart: chart.getAttribute("data-chart") };
    var label = a.getAttribute("aria-label") || (a.textContent || "").trim();
    if (!label) return null;
    var key = { tag: a.tagName, cls: a.getAttribute("class") || "", href: a.getAttribute("href") || "", label: label };
    key.nth = Math.max(0, sameAs(key).indexOf(a));
    return key;
  }
  function refocus(key, moved) {
    if (!key || (moved && !key.id)) return;   // a new page: only the bars' links are still the same thing
    var node = null;
    if (key.id) node = document.getElementById(key.id);
    else if (key.chart) {
      Array.prototype.forEach.call(app.querySelectorAll("[data-chart]"), function (c) {
        if (!node && c.getAttribute("data-chart") === key.chart) node = c.querySelector(".hit");
      });
    } else {
      var list = sameAs(key);
      node = list[Math.min(key.nth, list.length - 1)] || null;
    }
    if (!node || node === document.activeElement || !app.contains(node)) return;
    try { node.focus({ preventScroll: true }); } catch (e) { node.focus(); }
  }
  // A redraw the viewer didn't ask for (new scores, say) waits while they are
  // typing, choosing from a list, or pressing something, then catches up.
  var pointer = { down: false, at: 0 }, renderWaiting = false;
  function busyHere() {
    if (pointer.down && Date.now() - pointer.at < 10 * 1000) return true;
    var a = document.activeElement;
    return !!a && app.contains(a) && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName);
  }
  function catchUp() { if (renderWaiting && !busyHere()) render({ quiet: true }); }
  function soon() { if (renderWaiting) setTimeout(catchUp, 300); }
  document.addEventListener("pointerdown", function () { pointer.down = true; pointer.at = Date.now(); }, true);
  document.addEventListener("pointerup", function () { pointer.down = false; soon(); }, true);
  document.addEventListener("pointercancel", function () { pointer.down = false; soon(); }, true);
  document.addEventListener("focusout", soon, true);

  function smooth() {
    try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"; } catch (e) { return "auto"; }
  }

  window.addEventListener("scroll", function () {
    document.documentElement.classList.toggle("scrolled", window.scrollY > 700);
  }, { passive: true });
  function toTop() {
    return el("button", { class: "totop", type: "button", "aria-label": "Back to the top", title: "Back to the top",
      onclick: function () { window.scrollTo({ top: 0, behavior: smooth() }); } }, [icon("up")]);
  }

