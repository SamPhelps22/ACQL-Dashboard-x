  // ---- updating the page (only whoever can edit it sees any of this) -----------------
  function pageSource(data) {
    var style = document.getElementById("pool-style").textContent;
    var code = document.getElementById("pool-app").textContent;
    var json = JSON.stringify(data).replace(/</g, "\\u003c");
    return "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">" +
      "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">" +
      "<title>" + TITLE + "</title>" +
      "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">" +
      "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>" +
      FONTS.map(function (f) { return "<link rel=\"stylesheet\" href=\"" + f + "\">"; }).join("") +
      "<style id=\"pool-style\">" + style + "</style></head><body>" +
      "<div id=\"app\" class=\"page\"></div>" +
      "<script type=\"application/json\" id=\"pool-data\">" + json + "<\/script>" +
      "<script id=\"pool-app\">" + code + "<\/script></body></html>";
  }
  function checkData(d) {
    if (!d || d.schema !== 1 || !Array.isArray(d.players) || !Array.isArray(d.weeks) || typeof d.through_week !== "number") {
      return "That isn’t a pool page file. In the dashboard click Results › Pool page, then choose the file it saves (ACQL pool page - week N.json, in Downloads).";
    }
    if (!d.players.length) return "That file has no coaches in it.";
    if (!d.weeks.length) return "That file has no finished weeks in it yet.";
    return "";
  }
  // Who can update the page: the top button shows once the page knows this
  // viewer can edit it. Everyone else gets a small link at the bottom that
  // offers the same thing - and, where this view can't publish, says why -
  // so the owner is never left without a way in.
  // On the pool's own website (DATA.hosted) the dashboard publishes the page, so there is nothing to update here.
  var caps = { checking: !LIVE.hosted && !!(window.claude && typeof window.claude.use === "function"), artifact: null, editor: null };
  var ownerShown = false;
  var input = el("input", { type: "file", accept: ".json,application/json", hidden: true });
  var updateBox = el("div", { class: "update", role: "status" });
  function show(kids) {
    updateBox.textContent = "";
    kids.forEach(function (k) { if (k) updateBox.appendChild(k); });
    updateBar = updateBox;
    render();
    try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) { window.scrollTo(0, 0); }
  }
  function close() {
    updateBar = null;
    DATA = LIVE;
    dataChanged();
    input.value = "";
    render();
  }
  function closeButton() {
    return el("div", { class: "owner" }, [el("button", { class: "btn", type: "button", text: "Close", onclick: close })]);
  }
  function startUpdate() {
    if (caps.checking) {
      show([el("p", { text: "Still checking whether this view can update the page. Try again in a few seconds." }), closeButton()]);
    } else if (!caps.artifact) {
      show([el("p", { class: "error", text: "This view can’t update the page. Open it signed in to your Claude account on a computer (claude.ai in a browser, or the Claude app), then try again." }), closeButton()]);
    } else {
      input.click();
    }
  }
  function publishing(data) {
    var publish = el("button", { class: "btn primary", type: "button", text: "Publish for everyone" });
    var cancel = el("button", { class: "btn", type: "button", text: "Cancel", onclick: close });
    publish.addEventListener("click", function () {
      publish.disabled = true;
      cancel.disabled = true;
      publish.textContent = "Publishing…";
      caps.artifact.publish(pageSource(data)).then(function () {
        publish.textContent = "Published · reloading";
      }).catch(function (err) {
        var code = err && err.code;
        if (code === "conflict") return;          // a newer version won; the page is reloading to it
        cancel.disabled = false;
        var readOnly = ["not_writer", "not_granted", "not_declared", "consent_required", "capability_disabled", "capability_removed"].indexOf(code) >= 0;
        publish.disabled = readOnly;
        publish.textContent = "Publish for everyone";
        updateBox.appendChild(el("p", { class: "error", text:
          readOnly ? "This view can’t publish the page (" + code + "). Only the page’s owner can, signed in to their Claude account on a computer." :
          code === "too_large" ? "That file is too big for the page." :
          code === "rate_limited" ? "Published too often just now. Wait a minute, then try again." :
          "Couldn’t publish just now (" + (code || "unknown") + "). Try again in a minute." }));
      });
    });
    return el("div", { class: "owner" }, [publish, cancel]);
  }
  function read(file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onerror = function () { show([el("p", { class: "error", text: "Couldn’t read that file." }), closeButton()]); };
    reader.onload = function () {
      var data = null, problem = "";
      try { data = JSON.parse(String(reader.result)); } catch (e) { problem = "That isn’t a pool page file (it isn’t readable JSON)."; }
      problem = problem || checkData(data);
      if (problem) { show([el("p", { class: "error", text: problem }), closeButton()]); return; }
      var older = data.through_week < LIVE.through_week;
      DATA = data;
      dataChanged();
      state.week = data.through_week;
      show([
        el("p", {}, [el("b", { text: "Preview: after week " + data.through_week }),
          " · " + plural(data.players.length, "coach", "coaches") + " · made " + when(data.generated) +
          ". Nobody else sees this until you publish."]),
        older ? el("p", { class: "error", text: "This file is older than the page (week " + data.through_week + ", the page shows week " + LIVE.through_week + ")." }) : null,
        publishing(data)
      ]);
    };
    reader.readAsText(file);
  }
  input.addEventListener("change", function () { read(input.files && input.files[0]); });
  document.body.appendChild(input);
  function ownerFooter() {
    if (ownerShown || LIVE.hosted) return null;
    return el("button", { class: "linkish", type: "button", onclick: startUpdate, text: "Page owner: update this page" });
  }
  function showOwnerButton() {
    var box = document.getElementById("owner");
    if (ownerShown || !box) return;
    ownerShown = true;
    box.appendChild(el("button", { class: "btn", type: "button", onclick: startUpdate, text: "Update this page" }));
    // A file dragged onto the page works too.
    var depth = 0;
    document.addEventListener("dragenter", function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") < 0) return;
      depth++;
      document.body.classList.add("dropping");
    });
    document.addEventListener("dragleave", function () {
      depth = Math.max(0, depth - 1);
      if (!depth) document.body.classList.remove("dropping");
    });
    document.addEventListener("dragover", function (e) { e.preventDefault(); });
    document.addEventListener("drop", function (e) {
      e.preventDefault();
      depth = 0;
      document.body.classList.remove("dropping");
      read(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]);
    });
  }
  function settle(promise, ms) {
    return new Promise(function (resolve) {
      var done = false;
      function finish(v) { if (!done) { done = true; resolve(v); } }
      setTimeout(function () { finish(null); }, ms);
      Promise.resolve(promise).then(finish, function () { finish(null); });
    });
  }
  function isEditor(user) {
    if (!user) return Promise.resolve(null);
    var asks = [
      typeof user.canEdit === "function" ? user.canEdit() : null,
      typeof user.isOwner === "function" ? user.isOwner() : null,
      typeof user.can === "function" ? user.can("files.write") : null
    ];
    return Promise.all(asks.map(function (a) { return settle(a, 8000); })).then(function (r) {
      return r[0] === true || r[1] === true || r[2] === true;
    });
  }
  if (caps.checking) {
    Promise.all([settle(window.claude.use("user"), 12000), settle(window.claude.use("artifact"), 12000)])
      .then(function (found) {
        caps.artifact = found[1];
        return isEditor(found[0]).then(function (editor) { caps.editor = editor; });
      })
      .catch(function () { /* treated as a view that can't publish */ })
      .then(function () {
        caps.checking = false;
        if (caps.artifact && caps.editor) showOwnerButton();
        render();
      });
  }

})();
