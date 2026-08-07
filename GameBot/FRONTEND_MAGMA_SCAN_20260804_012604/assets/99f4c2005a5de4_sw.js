/**
 * Kintara Service Worker — static asset cache + deploy-cutover maintenance fallback.
 *
 * Two responsibilities:
 *
 *   1. Cache /assets/** and /node_modules/three/** for fast return-visit loads.
 *      Cache-first with background refresh; bump STATIC_CACHE_VERSION to evict.
 *
 *   2. Serve /site/maintenance.html (and its CSS/font/bg dependencies) from a
 *      pre-warmed cache when the origin returns 5xx or is unreachable.
 *      Triggers automatically during Render deploy cutover windows so returning
 *      users see the branded maintenance page instead of Render's raw 502.
 *
 * Caching policy (deliberately conservative so live game updates always work):
 *
 *   ALWAYS CACHED  (cache-first, served instantly, refreshed in background):
 *     - /assets/**            — images, audio, SVG, GLB models
 *     - /node_modules/three/** — Three.js library (versioned, rarely changes)
 *
 *   PRE-WARMED ON INSTALL (used only as fallback when origin is down):
 *     - /site/maintenance.html
 *     - /site/css/style1/home.css
 *     - /site/css/fonts/cinzel-variable.woff2
 *     - /site/img/bg1.png … /site/img/bg6.png
 *
 *   NEVER CACHED  (always network, no caching at all):
 *     - /                     — HTML entry, must be fresh
 *     - /index.html
 *     - /game.js              — main game module, updated often
 *     - /src/**               — game source modules
 *     - /api/**               — server endpoints (auth, presence, friends, …)
 *     - WebSockets / EventSource (handled by browser anyway)
 *     - Anything from a third-party origin (esm.sh, etc.)
 *
 * Cache invalidation:
 *   Bump `STATIC_CACHE_VERSION` whenever you change/replace asset files. The
 *   activate handler purges every cache that doesn't match the current version
 *   so old assets are reclaimed automatically. JS / HTML do not need a bump
 *   because they are never cached here in the first place.
 *
 *   Bump `MAINT_CACHE_VERSION` when /site/maintenance.html or its dependencies
 *   change so existing users re-prefetch on their next visit.
 */

/**
 * Bumping the version string makes the activate handler purge every old cache
 * entry on next visit.
 *
 * v2: King Scorpia's mount icon was redrawn in place. Asset filenames carry no
 * content hash, so a REPLACED file is invisible to returning players until the
 * cache is dropped — they kept the old brown scorpion long after the new art
 * shipped. Any future in-place art swap needs a bump here too.
 */
/** v3 2026-08-03: the first compressed-GLB build shipped quantized (invisible)
 *  *.c.glb files that cache-first would keep serving after the ETC1S-only
 *  rebuild replaced them at the same URLs — evict. */
const STATIC_CACHE_VERSION = 'kintara-static-v3';
const MAINT_CACHE_VERSION = 'kintara-maint-v1';

const CACHEABLE_PREFIXES = [
  '/assets/',
  '/node_modules/three/',
];

/** Pre-warmed on install. Failure of any individual prefetch is non-fatal —
 *  the SW still installs; that particular asset just won't be available as
 *  fallback. The maintenance HTML is the only one whose absence breaks the
 *  fallback entirely.
 *  Only the CRITICAL set downloads at install: the full six-background
 *  slideshow is ~7.6 MB, and install fires on a player's FIRST visit — right
 *  when the pipe should belong to realm assets, for a page that only matters
 *  if the origin later goes down. bg2–bg6 arrive via the deferred prefetch
 *  message the page sends once entry loading has long finished; until then any
 *  uncached background falls back to the cached bg1 (see tryMaintCacheMatch). */
const MAINT_PREFETCH_URLS = [
  '/site/maintenance.html',
  '/site/css/style1/home.css',
  '/site/css/fonts/cinzel-variable.woff2',
  '/site/img/bg1.png',
];
const MAINT_PREFETCH_DEFERRED_URLS = [
  '/site/img/bg2.png',
  '/site/img/bg3.png',
  '/site/img/bg4.png',
  '/site/img/bg5.png',
  '/site/img/bg6.png',
];

/** Asset paths the deploy-cutover fallback also serves from cache. Matches the
 *  prefixes of MAINT_PREFETCH_URLS so the maintenance page can load its CSS,
 *  fonts and background images even when the origin is down. */
const MAINT_FALLBACK_PREFIXES = [
  '/site/css/',
  '/site/img/',
  '/site/maintenance.html',
];

/** Install: pre-warm the maintenance cache. Game assets remain lazy so we never
 *  delay the first page load by fetching dozens of them up front. */
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(MAINT_CACHE_VERSION);
      await Promise.all(MAINT_PREFETCH_URLS.map(async url => {
        try {
          /** `cache: 'reload'` bypasses the HTTP cache so a fresh copy of each
           *  maintenance asset lands in the SW cache, even if the browser has
           *  a stale 304. */
          const res = await fetch(url, { cache: 'reload', credentials: 'same-origin' });
          if (res && res.ok && res.status === 200) {
            await cache.put(url, res.clone());
          }
        } catch (_) { /* ignore individual failures */ }
      }));
    } catch (_) { /* ignore — SW still installs without the fallback warm */ }
    /** Activate the new SW immediately on next page load (no need to refresh twice). */
    self.skipWaiting();
  })());
});

/** Deferred maintenance prefetch — fired by the page ~60s after load, i.e. far
 *  off the first-visit critical path. Runs on EVERY page load, so it checks the
 *  cache before fetching: steady state is six no-op cache.match calls, not a
 *  6 MB re-download per visit. */
self.addEventListener('message', event => {
  if (!event.data || event.data.type !== 'kintara-maint-prefetch-rest') return;
  const run = (async () => {
    try {
      const cache = await caches.open(MAINT_CACHE_VERSION);
      for (const url of MAINT_PREFETCH_DEFERRED_URLS) {
        try {
          if (await cache.match(url, { ignoreSearch: true })) continue;
          const res = await fetch(url, { cache: 'reload', credentials: 'same-origin' });
          if (res && res.ok && res.status === 200) await cache.put(url, res.clone());
        } catch (_) { /* individual failures leave that bg on the bg1 fallback */ }
      }
    } catch (_) { /* cache API unavailable — fallback degrades to bg1 only */ }
  })();
  if (event.waitUntil) event.waitUntil(run);
});

/** Activate: drop any cache that does not match the current version strings. */
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter(k => k !== STATIC_CACHE_VERSION && k !== MAINT_CACHE_VERSION)
        .map(k => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

/** True iff this request should hit our cache-first asset cache. */
function isCacheableRequest(req) {
  if (req.method !== 'GET') return false;
  const url = new URL(req.url);
  // Same-origin only — never cache third-party CDN content (esm.sh, RPC, etc.).
  if (url.origin !== self.location.origin) return false;
  return CACHEABLE_PREFIXES.some(p => url.pathname.startsWith(p));
}

function isMaintFallbackPath(pathname) {
  return MAINT_FALLBACK_PREFIXES.some(p => pathname.startsWith(p));
}

/** Cache-first strategy: serve from cache if present, otherwise fetch + cache. */
async function cacheFirst(req) {
  const cache = await caches.open(STATIC_CACHE_VERSION);
  const hit = await cache.match(req);
  if (hit) {
    // Refresh in background so the next visit gets any silent updates.
    fetch(req).then(res => {
      if (res && res.ok && res.status === 200 && res.type === 'basic') {
        cache.put(req, res.clone()).catch(() => { /* ignore quota errors */ });
      }
    }).catch(() => { /* ignore network failure on background refresh */ });
    return hit;
  }
  let res;
  try {
    res = await fetch(req);
  } catch (e) {
    throw e;
  }
  if (res && res.ok && res.status === 200 && res.type === 'basic') {
    try { await cache.put(req, res.clone()); } catch (_) { /* ignore quota errors */ }
  }
  return res;
}

/** Inject a meta-refresh into the cached maintenance HTML so the page polls the
 *  origin every 6s and snaps back to the real site as soon as it's healthy
 *  again. Idempotent — only injects when the tag isn't already present. */
function injectMaintRefresh(html) {
  if (typeof html !== 'string') return html;
  if (/http-equiv=["']refresh["']/i.test(html)) return html;
  return html.replace(
    /<head([^>]*)>/i,
    '<head$1>\n  <meta http-equiv="refresh" content="6">'
  );
}

/** Build a 503 Response from the cached maintenance.html. Returns null when
 *  the SW failed to prefetch it on install. */
async function buildMaintenanceResponse() {
  try {
    const cache = await caches.open(MAINT_CACHE_VERSION);
    const cached = await cache.match('/site/maintenance.html');
    if (!cached) return null;
    const html = injectMaintRefresh(await cached.text());
    return new Response(html, {
      status: 503,
      statusText: 'Service Unavailable',
      headers: {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-store',
      },
    });
  } catch (_) {
    return null;
  }
}

/** Try the cached copy of a maintenance subresource (css/font/image). A miss on
 *  any slideshow background substitutes the always-prefetched bg1 — a repeated
 *  backdrop beats five blank panes when the origin is down before the deferred
 *  prefetch has run. */
async function tryMaintCacheMatch(req) {
  try {
    const cache = await caches.open(MAINT_CACHE_VERSION);
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    const url = new URL(req.url);
    if (/^\/site\/img\/bg\d+\.png$/.test(url.pathname)) {
      const bg1 = await cache.match('/site/img/bg1.png', { ignoreSearch: true });
      if (bg1) return bg1;
    }
    return null;
  } catch (_) {
    return null;
  }
}

/** Navigation requests: try the network, fall back to cached maintenance.html on
 *  5xx or network failure. 4xx errors (404 etc.) pass through normally — those
 *  are application-level, not origin-down. */
async function handleNavigation(req) {
  try {
    const res = await fetch(req);
    if (res.status >= 500 && res.status <= 599) {
      const fallback = await buildMaintenanceResponse();
      if (fallback) return fallback;
    }
    return res;
  } catch (_) {
    const fallback = await buildMaintenanceResponse();
    if (fallback) return fallback;
    return new Response('Site unavailable.', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

/** Maintenance subresource (its own css/font/bg image): try network, fall back
 *  to pre-warmed cache so the maintenance page renders properly during the
 *  deploy gap. Normal /site/** requests still hit network first. */
async function handleMaintSubresource(req) {
  try {
    const res = await fetch(req);
    if (res && res.status >= 500 && res.status <= 599) {
      const hit = await tryMaintCacheMatch(req);
      if (hit) return hit;
    }
    return res;
  } catch (_) {
    const hit = await tryMaintCacheMatch(req);
    if (hit) return hit;
    throw _;
  }
}

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  /** Navigation = top-level page load or refresh. */
  if (req.mode === 'navigate') {
    event.respondWith(handleNavigation(req));
    return;
  }
  /** Same-origin /site/** subresources fall back to the maintenance cache on
   *  failure so the served maintenance.html actually renders. */
  try {
    const url = new URL(req.url);
    if (url.origin === self.location.origin && isMaintFallbackPath(url.pathname)) {
      event.respondWith(handleMaintSubresource(req));
      return;
    }
  } catch (_) { /* fall through */ }
  if (!isCacheableRequest(req)) return; // let browser handle it normally
  event.respondWith(cacheFirst(req));
});
