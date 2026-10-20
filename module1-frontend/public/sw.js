const CACHE_NAME = "saiv-cache-v5";

// Pages reachable from the sidebar. Saved at install so they open offline.
const PAGES = ["/", "/courses", "/privacy", "/help", "/consent", "/login", "/register"];

const ASSET_RE = /\/_next\/static\/[^"'\\\s<>]+\.(?:js|css)/g;

function isApiRequest(url) {
  return url.includes("/api/") || url.includes(":8000");
}

// Save the scripts and styles a page needs, so it can run offline
function storeAssets(html) {
  const assets = Array.from(new Set(html.match(ASSET_RE) || []));
  return caches.open(CACHE_NAME).then((cache) =>
    Promise.all(
      assets.map((a) => cache.match(a).then((hit) => hit || cache.add(a).catch(() => {})))
    )
  );
}

async function savePage(path) {
  const res = await fetch(path);
  if (!res.ok) return;
  const cache = await caches.open(CACHE_NAME);
  await cache.put(path, res.clone());
  await storeAssets(await res.text());
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    Promise.all(PAGES.map((p) => savePage(p).catch(() => {}))).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function offlinePage(request) {
  const exact = await caches.match(request, { ignoreVary: true });
  if (exact) return exact;
  const path = new URL(request.url).pathname;
  if (path.startsWith("/courses/")) {
    const list = await caches.match("/courses", { ignoreVary: true });
    if (list) return list;
  }
  return caches.match("/", { ignoreVary: true });
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = request.url;

  if (request.method !== "GET") return;

  // Backend calls always go to the network (the app handles offline itself)
  if (isApiRequest(url)) {
    event.respondWith(fetch(request));
    return;
  }

  // Next.js data requests: let them fail, and Next then loads the full page instead
  if (url.includes("_rsc=")) return;

  const wantsHtml =
    request.mode === "navigate" || (request.headers.get("accept") || "").includes("text/html");

  if (wantsHtml) {
    // Pages: network first, so they're never stale. The saved copy is the offline fallback.
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const forCache = res.clone();
            const forParse = res.clone();
            event.waitUntil(
              caches
                .open(CACHE_NAME)
                .then((c) => c.put(request, forCache))
                .then(() => forParse.text())
                .then(storeAssets)
                .catch(() => {})
            );
          }
          return res;
        })
        .catch(() => offlinePage(request))
    );
    return;
  }

  // Scripts, styles, icons: saved copy first
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, copy));
          }
          return res;
        })
    )
  );
});