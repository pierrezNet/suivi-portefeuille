// Service Worker — Suivi Portefeuille (PWA v2.0)
//
// Stratégies :
//   - index.html         : network-first, fallback cache (shell offline)
//   - data.enc.json      : network-first (3 s), fallback cache + flag offline
//   - autres (icônes…)   : cache-first
//
// Le cache est versionné par CACHE_VERSION (à bumper à chaque publication
// du HTML — sinon les vieilles versions traînent).

const CACHE_VERSION = "v__BUILD_ID__";
const CACHE_SHELL = `bourse-shell-${CACHE_VERSION}`;
const CACHE_DATA = `bourse-data-${CACHE_VERSION}`;

const SHELL_ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon.svg",
  "./icon-192.png",
  "./icon-512.png",
  "./apple-touch-icon-180.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_SHELL).then((c) =>
      c.addAll(SHELL_ASSETS).catch(() => null)
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((noms) =>
      Promise.all(
        noms
          .filter((n) => n.startsWith("bourse-") && !n.endsWith(CACHE_VERSION))
          .map((n) => caches.delete(n))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;

  const isData = url.pathname.endsWith("data.enc.json");
  const isShell =
    url.pathname.endsWith("/") ||
    url.pathname.endsWith("index.html") ||
    url.pathname.endsWith("manifest.json");

  if (isData) {
    event.respondWith(networkFirstWithTimeout(event.request, CACHE_DATA, 3000));
    return;
  }
  if (isShell) {
    event.respondWith(networkFirstWithTimeout(event.request, CACHE_SHELL, 2000));
    return;
  }
  // Autres (icônes, etc.) : cache-first
  event.respondWith(
    caches.match(event.request).then(
      (r) => r || fetch(event.request).then((rep) => {
        const copie = rep.clone();
        caches.open(CACHE_SHELL).then((c) => c.put(event.request, copie));
        return rep;
      })
    )
  );
});

function networkFirstWithTimeout(request, cacheName, timeoutMs) {
  return new Promise((resolve) => {
    let resolu = false;
    const tFallback = setTimeout(() => {
      if (resolu) return;
      caches.match(request).then((r) => {
        if (r && !resolu) { resolu = true; resolve(r); }
      });
    }, timeoutMs);
    fetch(request)
      .then((rep) => {
        // TOUJOURS rafraîchir le cache avec la réponse réseau, même si le
        // timeout a déjà servi une version en cache pour CETTE requête —
        // sinon, sur connexion lente, le cache reste périmé indéfiniment
        // (data.enc.json chiffré avec un ancien mot de passe → « incorrect »).
        const copie = rep.clone();
        caches.open(cacheName).then((c) => c.put(request, copie));
        if (resolu) return;
        resolu = true;
        clearTimeout(tFallback);
        resolve(rep);
      })
      .catch(() => {
        if (resolu) return;
        caches.match(request).then((r) => {
          if (resolu) return;
          resolu = true;
          if (r) resolve(r);
          else resolve(new Response("Offline et aucun cache", { status: 503 }));
        });
      });
  });
}
