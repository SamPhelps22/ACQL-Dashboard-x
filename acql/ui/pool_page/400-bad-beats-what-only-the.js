  // ---- bad beats: what only the order of things tells -----------------------------------
  function beatsModule(w) {
    var beats = w.beats || [];
    if (!beats.length) return null;
    var canWatch = !!w.replay;
    return module("Bad beats", "and the moments that decided it", beats.map(function (b) {
      return el("div", { class: "award beat", "data-beat": b.kind }, [
        el("span", { class: "t", text: b.title }),
        el("span", { class: "w", text: b.who }),
        el("span", { class: "why", text: b.detail }),
        el("span", { class: "beat-foot" }, [b.at ? el("span", { class: "when", text: frameTime([b.at]) }) : null,
        canWatch && b.frame != null ? el("button", { class: "linkish watch", type: "button", text: "Watch it",
          onclick: function () {
            stopReplay();
            replayPos[w.week] = b.frame;
            var got = replays[w.week];
            var rep = got && got.data ? got.data : w.replay && w.replay.data;
            if (rep && rep.slider && rep.slider.isConnected) replayGo(rep, b.frame);
            var card = document.getElementById("replay-card");
            if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
          } }) : null])
      ]);
    }), { "data-card": "beats" });
  }

