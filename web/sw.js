const CACHE = "pixal-dm-5c50b4f6";
const SHELL = [
  "/",
  "/app.js",
  "/manifest.webmanifest",
  "/vendor/three.module.js",
  "/icons/tile-16.png",
  "/icons/tile-24.png",
  "/icons/tile-32.png",
  "/icons/tile-48.png",
  "/icons/tile-64.png",
  "/icons/tile-128.png",
  "/icons/tile-256.png",
  "/icons/block-192.png",
  "/icons/block-512.png"
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;   // chat, events, images: always live
  if (url.pathname === "/" || url.pathname === "/index.html" || url.pathname === "/app.js") {
    // network-first: the shell + bundle change with the server, never serve them stale
    e.respondWith(fetch(e.request).then(r => {
      const copy = r.clone();
      caches.open(CACHE).then(c => c.put(url.pathname, copy));
      return r;
    }).catch(() => caches.match(url.pathname)));
    return;
  }
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
});
