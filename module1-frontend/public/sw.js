const CACHE_NAME = "saiv-cache-v2";

const STATIC_ASSETS = [
  "/",
];

function isApiRequest(url) {
  return url.includes("/api/") || url.includes(":8000");
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  console.log("Service Worker activated");
});

self.addEventListener("fetch", (event) => {
  const url = event.request.url;

  if (event.request.method !== "GET") {
    return;
  }

  if (isApiRequest(url)) {
    event.respondWith(
      fetch(event.request).catch((err) => {
        console.warn("API request failed (likely offline):", url);
        throw err; // let axios see the failure so your fallback logic can handle it
      })
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }

      return fetch(event.request)
        .then((networkResponse) => {
          if (!networkResponse.ok) return networkResponse; // never cache 404s or 500s
          return caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, networkResponse.clone());
            return networkResponse;
          });
        })
        .catch((err) => {
          console.warn("Static asset fetch failed:", url);
          throw err;
        });
    })
  );
});