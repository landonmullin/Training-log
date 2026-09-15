// Training Log — service worker (push notifications only; no caching so updates stay instant)
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", e => {
  let payload = {};
  try { payload = e.data ? e.data.json() : {}; } catch(_) { payload = { body: e.data ? e.data.text() : "" }; }
  const title = payload.title || "Training Log";
  const opts = {
    body: payload.body || "",
    icon: "icon.png",
    badge: "icon.png",
    tag: payload.tag || "reminder",
    data: { url: payload.url || "./" }
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "./";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) { if ("focus" in c) return c.focus(); }
    return self.clients.openWindow(url);
  }));
});
