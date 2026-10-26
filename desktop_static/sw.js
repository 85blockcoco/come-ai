/* SPEC-050 — Mode hors-ligne (service worker + cache).
   Périmètre : "/" (enregistré depuis n'importe quelle page NAGE).
   Stratégies :
   - navigations  : réseau d'abord (timeout court), puis coquille /app en cache,
                    puis page de secours /app-static/offline.html ;
   - /api/* (GET) : réseau d'abord, cache local en secours (en-tête
                    X-Nage-Offline pour que l'UI signale des données périmées) ;
   - /app-static/*: cache d'abord, revalidation en arrière-plan.
   Aucune écriture n'est mise en cache : seules les requêtes GET passent ici. */

const CACHE_VERSION = "nage-v2";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const ASSET_CACHE = `${CACHE_VERSION}-assets`;
const API_CACHE = `${CACHE_VERSION}-api`;

const OFFLINE_URL = "/app-static/offline.html";
const APP_SHELL_URL = "/app";

const PRECACHE_URLS = [
  APP_SHELL_URL,
  "/app.webmanifest",
  "/app-static/app.css",
  "/app-static/app.js",
  "/app-static/nage-intro.js",
  "/app-static/icon.png",
  OFFLINE_URL,
];

const NAVIGATION_TIMEOUT_MS = 3000;
const API_TIMEOUT_MS = 2500;

const KEPT_CACHES = new Set([SHELL_CACHE, ASSET_CACHE, API_CACHE]);

/* ---------- Utilitaires ---------- */

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("cache-timeout")), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

async function cachePut(cacheName, request, response) {
  if (!response || !response.ok) return;
  try {
    const cache = await caches.open(cacheName);
    await cache.put(request, response);
  } catch {
    /* quota / réponse opaque : on continue sans cache */
  }
}

function offlineJsonResponse() {
  return new Response(
    JSON.stringify({
      detail: "Hors-ligne : aucune donnée en cache pour cette requête.",
      offline: true,
    }),
    {
      status: 503,
      headers: { "Content-Type": "application/json; charset=utf-8", "X-Nage-Offline": "1" },
    },
  );
}

function markCachedResponse(response) {
  const headers = new Headers(response.headers);
  headers.set("X-Nage-Offline", "1");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

/* ---------- Stratégies ---------- */

async function navigationStrategy(request) {
  try {
    const response = await withTimeout(fetch(request), NAVIGATION_TIMEOUT_MS);
    if (response && response.ok) {
      await cachePut(SHELL_CACHE, APP_SHELL_URL, response.clone());
      return response;
    }
    throw new Error(`navigation-${response && response.status}`);
  } catch {
    return (
      (await caches.match(request)) ||
      (await caches.match(APP_SHELL_URL)) ||
      (await caches.match(OFFLINE_URL)) ||
      new Response("Hors-ligne", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } })
    );
  }
}

async function apiStrategy(request) {
  try {
    const response = await withTimeout(fetch(request), API_TIMEOUT_MS);
    if (response && response.ok) {
      await cachePut(API_CACHE, request, response.clone());
      return response;
    }
    throw new Error(`api-${response && response.status}`);
  } catch {
    const cached = await caches.match(request);
    return cached ? markCachedResponse(cached) : offlineJsonResponse();
  }
}
/* ---------- Cycle de vie ---------- */

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      await Promise.allSettled(
        PRECACHE_URLS.map(async (url) => {
          const response = await fetch(new Request(url, { cache: "reload", credentials: "same-origin" }));
          if (response && response.ok) await cache.put(url, response);
        }),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.filter((name) => !KEPT_CACHES.has(name)).map((name) => caches.delete(name)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  const type = event.data && event.data.type;
  if (type === "SKIP_WAITING") {
    self.skipWaiting();
    return;
  }
  if (type === "CLEAR_OFFLINE_CACHE") {
    event.waitUntil(Promise.all([...KEPT_CACHES].map((name) => caches.delete(name))));
  }
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(navigationStrategy(request));
    return;
  }
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(apiStrategy(request));
    return;
  }
  if (url.pathname.startsWith("/app-static/")) {
    // Cache d'abord, revalidation en arrière-plan rattachée à l'événement :
    // le worker reste vivant jusqu'à la mise à jour effective du cache.
    const network = fetch(request)
      .then(async (response) => {
        if (response && response.ok) await cachePut(ASSET_CACHE, request, response.clone());
        return response;
      })
      .catch(() => null);
    event.waitUntil(network.then(() => undefined, () => undefined));
    event.respondWith(
      (async () =>
        (await caches.match(request)) ||
        (await network) ||
        new Response("", { status: 504, statusText: "Offline" }))(),
    );
  }
});
