  // ---- toasts ----------------------------------------------------------------------
  var toastBox = null;
  function toast(f) {
    if (!toastBox || !toastBox.isConnected) {
      toastBox = el("div", { class: "toasts", role: "status", "aria-live": "polite" });
      document.body.appendChild(toastBox);
    }
    var node = el("div", { class: "toast" + (f.tone ? " " + f.tone : "") }, [
      el("b", { text: f.title }), el("button", { type: "button", "aria-label": "Dismiss", text: "×", onclick: function () { node.remove(); } }),
      el("span", { text: f.text })
    ]);
    toastBox.appendChild(node);
    while (toastBox.children.length > 3) toastBox.removeChild(toastBox.firstChild);
    setTimeout(function () { if (node.isConnected) node.remove(); }, 8000);
  }

