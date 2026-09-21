/* AURA OS service worker — app-shell cache + Web Push + offline fallback. v1.4.0 */
const CACHE = "aura-shell-v2";
const SHELL = ["/", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET" || !request.url.startsWith(self.location.origin)) return;
  if (new URL(request.url).pathname.startsWith("/api/")) return; // never cache API
  e.respondWith(
    caches.match(request, { ignoreSearch: true }).then(
      (hit) =>
        hit ||
        fetch(request)
          .then((res) => {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(request, copy));
            return res;
          })
          .catch(() =>
            request.mode === "navigate" ? caches.match("/") : Promise.reject(new Error("offline"))
          )
    )
  );
});

self.addEventListener("push", (e) => {
  let data = { title: "AURA", body: "", url: "/" };
  try { data = { ...data, ...e.data.json() }; } catch { /* plain push */ }
  e.waitUntil(
    self.registration.showNotification(data.title || "AURA", {
      body: data.body || "",
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) if ("focus" in w) { w.navigate(url); return w.focus(); }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
