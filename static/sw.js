/* Hisaab service worker — offline shell for weak connections.
   Strategy: network-first for our own HTML/CSS/JS (so a deploy is picked up
   immediately and stale code never sticks), falling back to cache when the
   network is unavailable. Fonts: stale-while-revalidate. API: never touched. */
const CACHE = "hisaab-v7";
const SHELL = [
  "/", "/index.html", "/app.css", "/manifest.webmanifest",
  "/js/main.js?v=20260906.3", "/js/ui.js?v=20260906.3", "/js/i18n.js?v=20260906.3",
  "/js/api.js?v=20260906.3", "/js/auth.js?v=20260906.3", "/js/screens.js?v=20260906.3",
  "/js/actions.js?v=20260906.3", "/js/help.js?v=20260906.3",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/")) return;          // user data: straight to network

  const isFont = /fonts\.(gstatic|googleapis)\.com$/.test(url.hostname);
  const isOwn = url.origin === location.origin;
  if (!isOwn && !isFont) return;

  if (isOwn) {
    // network-first
    e.respondWith(
      fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      }).catch(() => caches.match(e.request).then((hit) => hit || caches.match("/")))
    );
    return;
  }

  // fonts: stale-while-revalidate
  e.respondWith(
    caches.match(e.request).then((hit) => {
      const net = fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
