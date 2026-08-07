/**
 * GLTFLoader wrapper: transparently serves size-capped GLB variants.
 *
 * game.js imports THIS as `GLTFLoader` (its single loader import), so every
 * construction site — the seven mount loaders in game.js, glb-loaders.js,
 * dunes-cosmetics-camp.js, chest-vending-machine.js — gets the behavior with
 * zero call-site changes: when a requested URL appears in the generated
 * manifest (compressed-glb-manifest.js), load the `*.c.glb` sibling instead.
 * Variants are built by scripts/build-compressed-assets.mjs and differ ONLY
 * in embedded texture dimensions (≤1024 — a 2048² baseColor decodes to 22MB
 * of GPU memory, the cap quarters it). Geometry, node graph and materials
 * are identical, and the textures decode natively (plain png/jpeg): no wasm,
 * no workers, no CSP surface.
 *
 * Failure posture — the variant path can NEVER break loading:
 *   - any load error retries the ORIGINAL URL;
 *   - a WATCHDOG treats a load that neither succeeds nor errors within
 *     12s as failed and falls back too (lesson from 2026-08-03: the KTX2
 *     transcoder died inside its worker under CSP and the pending texture
 *     promise never settled — models sat invisible with no error to catch);
 *   - two consecutive failures trip a session breaker that routes every
 *     later load straight to originals;
 *   - `window.__KINTARA_NO_CGLB` (injected by the server when
 *     KINTARA_DISABLE_COMPRESSED_GLB is set — an env flip, no deploy)
 *     disables the whole path up front.
 */
import { GLTFLoader as ThreeGLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { COMPRESSED_GLB_VARIANTS } from './compressed-glb-manifest.js?v=20260803-cglb4';

let _failures = 0;
const BREAKER_LIMIT = 2;
const WATCHDOG_MS = 12000;

export class GLTFLoader extends ThreeGLTFLoader {
  load(url, onLoad, onProgress, onError) {
    const key = String(url || '').split('?')[0];
    const enabled =
      _failures < BREAKER_LIMIT &&
      !(typeof window !== 'undefined' && window.__KINTARA_NO_CGLB);
    const compressedUrl = enabled ? COMPRESSED_GLB_VARIANTS.get(key) : null;
    if (!compressedUrl) {
      return super.load(url, onLoad, onProgress, onError);
    }
    let settled = false;
    const fallback = (why) => {
      if (settled) return;
      settled = true;
      _failures++;
      console.warn(`[cglb] ${compressedUrl} ${why} (${_failures}/${BREAKER_LIMIT}) — loading original`);
      super.load(url, onLoad, onProgress, onError);
    };
    const watchdog = setTimeout(() => fallback('timed out'), WATCHDOG_MS);
    super.load(
      compressedUrl,
      (gltf) => {
        clearTimeout(watchdog);
        if (settled) return;
        settled = true;
        _failures = 0;
        onLoad && onLoad(gltf);
      },
      onProgress,
      (err) => {
        clearTimeout(watchdog);
        fallback('failed: ' + (err && (err.message || err)));
      }
    );
  }
}
