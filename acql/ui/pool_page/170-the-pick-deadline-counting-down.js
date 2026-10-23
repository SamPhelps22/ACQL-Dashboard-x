  // ---- the pick deadline, counting down ------------------------------------------------
  // When the next week's picks are due: the pool's deadline, or the week's first
  // kickoff if that comes sooner. Gone once it has passed.
  function deadlineAt() {
    var d = DATA.deadline;
    return d && d.at && d.at > Date.now() && d.week === DATA.through_week + 1 ? d : null;
  }
  function countdownText(at) {
    var ms = at - Date.now();
    if (ms <= 0) return "Picks are closed";
    var mins = Math.floor(ms / 60000), days = Math.floor(mins / 1440), hrs = Math.floor((mins % 1440) / 60), m = mins % 60;
    if (days) return days + "d " + hrs + "h " + m + "m";
    if (hrs) return hrs + "h " + m + "m";
    return m + "m " + (Math.floor(ms / 1000) % 60) + "s";
  }
  function deadlineBanner() {
    var d = deadlineAt();
    if (!d) return null;
    var due = new Date(d.at);
    var soon = d.at - Date.now() < 24 * 3600 * 1000;
    return el("aside", { class: "deadline" + (soon ? " soon" : ""), "aria-label": "Pick deadline" }, [
      el("span", { class: "dl-label", text: "Week " + d.week + " picks due" }),
      el("b", { class: "dl-count num", "data-countdown": String(d.at), text: countdownText(d.at) }),
      el("span", { class: "dl-when", text: due.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }) + " · " + clock(due) }),
      /^https?:\/\//.test(d.form || "") ? el("a", { class: "btn primary dl-go", href: d.form, target: "_blank", rel: "noopener", text: "Enter picks" }) : null
    ]);
  }
  setInterval(function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-countdown]"), function (node) {
      var at = Number(node.getAttribute("data-countdown"));
      node.textContent = countdownText(at);
      var box = node.parentNode;
      if (box) box.classList.toggle("soon", at - Date.now() < 24 * 3600 * 1000);
    });
  }, 1000);

  function footer() {
    var foot = el("footer", {}, [
      hasLogo() ? el("div", { class: "fbrand" }, [logoImg("logo"), "Arm Chair Quarterback League"]) : null,
      "Updated " + when(DATA.generated) + ", after week " + DATA.through_week + "’s results. Every number comes from the pool’s own sheets."
        + (standingsBehind() ? " Week " + standingsBehind() + " is over but not in these standings yet." : ""),
      el("a", { class: "mainsite", href: MAIN_SITE, target: "_blank", rel: "noopener", text: "The league's main site" }),
      typeof ownerFooter === "function" ? ownerFooter() : null,
      homeScreenTip()
    ]);
    // five quick taps down here open a page that is no use without its passphrase
    var taps = 0, since = 0;
    foot.addEventListener("click", function (event) {
      if (event.target.closest && event.target.closest("a, button")) return;
      var now = Date.now();
      if (now - since > 2500) { taps = 0; since = now; }
      taps += 1;
      if (taps >= 5) { taps = 0; window.location.href = "locker.html"; }
    });
    return foot;
  }
  function homeScreenTip() {
    if (!LIVE.hosted) return null;
    var saved = false;
    try { saved = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true; } catch (e) { /* older browser */ }
    if (saved) return null;
    return el("span", { class: "narrow-only", text: "Keep this one tap away: on iPhone tap Share › Add to Home Screen; on Android tap ⋮ › Add to Home screen." });
  }

