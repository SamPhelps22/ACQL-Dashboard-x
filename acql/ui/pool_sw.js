// The pool website, kept on the phone: it opens at once from the home screen
// and still shows the last standings with no signal. The network always comes
// first, so a newer page is never held back; the saved copy is only for when
// there is no connection. Live scores are never saved.
const CACHE = "acql-__VERSION__";
const SHELL = ["./", "manifest.webmanifest", "icon-192.png", "icon-512.png", "apple-touch-icon.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL).catch(() => undefined))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.indexOf("acql-") === 0 && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  const fonts = url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com";
  if (url.origin !== self.location.origin && !fonts) return;   // scores and anything else: straight through
  if (fonts) {
    // fonts never change: the saved copy, refreshed in the background
    event.respondWith(caches.open(CACHE).then((cache) => cache.match(request).then((hit) => {
      const fresh = fetch(request).then((response) => {
        if (response && (response.ok || response.type === "opaque")) cache.put(request, response.clone());
        return response;
      }).catch(() => hit);
      return hit || fresh;
    })));
    return;
  }
  // the page itself always asks the server, past the browser's own cache
  const asked = request.mode === "navigate" ? new Request(request, { cache: "no-cache" }) : request;
  event.respondWith(
    fetch(asked).then((response) => {
      if (response && response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy));
      }
      return response;
    }).catch(() => caches.match(request).then((hit) => hit || (request.mode === "navigate" ? caches.match("./") : undefined)))
  );
});
