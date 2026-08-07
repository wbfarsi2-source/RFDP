/**
 * Keyed primitive-geometry cache for procedural avatars (2026-07-30).
 *
 * Every buildCharacter() call minted a fresh BoxGeometry/SphereGeometry per
 * body part AND per outline shell (~46 geometries per remote avatar), yet the
 * dimensions all come from a small fixed set — the head is always
 * Box(0.44, 0.34, 0.44) on every avatar in the room. At 40 remotes that is
 * 1,500-2,500 identical live geometries uploaded to the GPU one avatar at a
 * time. This cache returns ONE shared geometry per distinct dimension key.
 *
 * Shared geometries are tagged `userData.__sharedGeometry = true`, the opt-out
 * honored by disposeOwnedThreeSubtree (shipped with the click-proxy fix) and by
 * the avatar preview teardown walks in game.js — an avatar leaving the room
 * frees its materials but never the geometry the rest of the room still draws.
 * three r160 keeps CPU-side arrays after dispose(), so even a stray dispose on
 * a shared geometry self-heals via re-upload rather than crashing — the cache
 * is a perf lever, not a correctness cliff.
 *
 * Callers must NEVER mutate a returned geometry in place (translate/scale/
 * morph). Resize-style operations swap the mesh's geometry reference for
 * another cache entry instead (see outfitResizeBoxMesh). The merge passes are
 * safe: merge-avatar-static-body/shells clone() sources before transforming.
 *
 * The map is unbounded growth-proof by construction (keys come from fixed
 * outfit/body dimension tables), but a cap guards against a future caller with
 * dynamic dims: at the cap the factory returns an UNTAGGED owned geometry —
 * exactly the pre-cache behavior, disposed normally with its avatar.
 */

const CACHE_CAP = 1024;

/**
 * @param {typeof import('three')} THREE
 * @returns {{ box(w:number,h:number,d:number): object,
 *             sphere(r:number,ws:number,hs:number): object,
 *             size(): number }}
 */
export function makeAvatarGeoCache(THREE) {
  const cache = new Map();
  function get(key, make) {
    let g = cache.get(key);
    if (g) return g;
    g = make();
    if (cache.size >= CACHE_CAP) return g; // fail-open: owned + untagged
    g.userData.__sharedGeometry = true;
    cache.set(key, g);
    return g;
  }
  return {
    box(w, h, d) {
      return get(`b|${w}|${h}|${d}`, () => new THREE.BoxGeometry(w, h, d));
    },
    sphere(r, ws, hs) {
      return get(`s|${r}|${ws}|${hs}`, () => new THREE.SphereGeometry(r, ws, hs));
    },
    size() {
      return cache.size;
    },
  };
}
