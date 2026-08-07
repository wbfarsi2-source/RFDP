/**
 * Boot-time GPU prewarm for lazy-loaded GLB templates (2026-07-29).
 *
 * Phase-attribution telemetry put the crowd hitches INSIDE renderer.render —
 * 100ms-2.2s single-call maxes with a healthy ~6ms steady state — which is
 * the signature of FIRST-USE GPU uploads: an authored mount GLB (big
 * textures, real geometry) hits the GPU on the first frame its first rider
 * walks into view, mid-combat. The templates load lazily (first rider
 * triggers network+parse+upload all at once), so the whole cost lands on a
 * combat frame.
 *
 * This module front-loads that cost into the seconds right after world
 * reveal: a staggered queue (one action per tick, default 300ms) triggers
 * each registered template load, and when a template lands it is uploaded
 * once — every texture via renderer.initTexture, geometry buffers via a
 * single 8x8 offscreen render — so the first rider later costs a clone, not
 * an upload. Stagger means the worst case per frame is ONE template's
 * upload, in the calmest seconds of a session instead of a fight.
 *
 * Deliberately NOT during the loading screen: these are network fetches
 * (0.5-3MB each); serializing them before reveal would add seconds to boot.
 * Post-reveal stagger costs nothing visible.
 *
 * Programs are NOT the target (live program count is stable — the glow-pool
 * work fixed that class); the offscreen render compiles against the prewarm
 * scene's own lights, which may not match the main scene's variant, and
 * that's fine — buffers and textures are renderer-global, and they are the
 * stall class being killed.
 *
 * Escape hatch: `window.__KINTARA_BOOT_PREWARM = 0` before reveal disables
 * the queue (support/debug — client-only concern, no server env needed).
 * Fail-open everywhere: any error skips that template and the game plays
 * exactly as before (lazy path unchanged, populate/clone flow untouched).
 */

export function createBootPrewarm(gameCtx) {
  const targets = [];
  let started = false;
  let timer = null;
  let scene = null;
  let cam = null;
  let rt = null;

  const TICK_MS = 300;
  const START_DELAY_MS = 2000;

  function registerBootPrewarmTarget(label, start, template) {
    targets.push({ label, start, template, startedLoad: false, uploaded: false });
  }

  function prewarmEnabled() {
    try {
      if (typeof window !== 'undefined' && window.__KINTARA_BOOT_PREWARM === 0) return false;
      /* The prewarm force-downloads 8 GLBs (0.5-3MB each) + uploads them in
       * the first ~30s of a session — correct on desktop, harmful on a
       * metered or memory-tight phone where that window is exactly when
       * thermal/memory headroom is smallest. Skip on Data Saver and on
       * low-memory devices; other touch devices keep it (the mid-combat
       * upload stall it prevents hurts them the most). */
      const conn = typeof navigator !== 'undefined' ? navigator.connection : null;
      if (conn && conn.saveData) return false;
      if (typeof navigator !== 'undefined' && Number(navigator.deviceMemory) > 0 && Number(navigator.deviceMemory) <= 3) return false;
    } catch (_) { /* no window (tests) */ }
    return true;
  }

  /** Upload every GPU resource this object owns: textures explicitly, geometry
   *  buffers via one tiny offscreen render. Restores the previous render
   *  target; the template is removed from the prewarm scene before return. */
  function prewarmObjectGpuResources(root) {
    const THREE = gameCtx.THREE;
    const renderer = gameCtx.renderer;
    if (!THREE || !renderer || !root) return false;
    root.traverse((o) => {
      if (!o.isMesh || !o.material) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      for (const m of mats) {
        if (!m) continue;
        for (const k of Object.keys(m)) {
          const v = m[k];
          if (v && v.isTexture) {
            try { renderer.initTexture(v); } catch (_) { /* unsupported/disposed — draw path uploads later */ }
          }
        }
      }
    });
    try {
      if (!scene) {
        scene = new THREE.Scene();
        cam = new THREE.PerspectiveCamera(50, 1, 0.1, 50);
        cam.position.set(0, 2, 6);
        cam.lookAt(0, 1, 0);
        scene.add(new THREE.AmbientLight(0xffffff, 0.8));
        rt = new THREE.WebGLRenderTarget(8, 8);
      }
      scene.add(root);
      const prevRt = renderer.getRenderTarget();
      renderer.setRenderTarget(rt);
      renderer.render(scene, cam);
      renderer.setRenderTarget(prevRt);
      scene.remove(root);
      return true;
    } catch (_) {
      try { if (scene && root.parent === scene) scene.remove(root); } catch (_) { /* keep template usable */ }
      return false;
    }
  }

  function tick() {
    if (!prewarmEnabled()) { stop(); return; }
    /** One ACTION per tick: either kick the next un-started load, or upload
     *  one landed template. Loads are async (network), so early ticks mostly
     *  kick loads and later ticks drain the uploads as templates arrive. */
    for (const t of targets) {
      if (t.startedLoad && !t.uploaded) {
        let tpl = null;
        try { tpl = t.template(); } catch (_) { tpl = null; }
        if (tpl) {
          t.uploaded = prewarmObjectGpuResources(tpl) || true; /* true even on failure: never retry-loop a broken template */
          return;
        }
      }
    }
    for (const t of targets) {
      if (!t.startedLoad) {
        t.startedLoad = true;
        try { t.start(); } catch (_) { /* lazy path still covers this mount */ }
        return;
      }
    }
    /** All loads kicked, nothing landed this tick — keep polling for
     *  in-flight fetches, but give up a minute in (failed loads retry via
     *  their own lazy paths; the queue must not poll forever). */
    if (Date.now() - _startedAtMs > 60_000) stop();
  }
  let _startedAtMs = 0;

  function stop() {
    if (timer != null) { clearInterval(timer); timer = null; }
  }

  /** Call once at world reveal. Idempotent. The delay lets the reveal's own
   *  first-render burst settle before the queue adds any work. */
  function startBootPrewarm() {
    if (started || !prewarmEnabled() || !targets.length) return;
    started = true;
    setTimeout(() => {
      _startedAtMs = Date.now();
      timer = setInterval(tick, TICK_MS);
      if (timer && typeof timer.unref === 'function') timer.unref();
    }, START_DELAY_MS);
  }

  return {
    registerBootPrewarmTarget,
    startBootPrewarm,
    /** test hooks */
    _internals: { tick, prewarmObjectGpuResources, targets, stop },
  };
}
