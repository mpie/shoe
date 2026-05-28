self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open("solebox-monitor-v1").then((cache) => cache.addAll([
      "/",
      "/app.js",
      "/styles.css",
      "/manifest.webmanifest",
      "/icon.svg",
    ])),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request)),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow("/"));
});
