/**
 * OBS-1 — client frame-time telemetry (2026-07-27).
 *
 * The 2026-07 review ranked the low-FPS causes entirely from code reading,
 * because NOTHING measures the client. Every cause in that report is a
 * hypothesis. This module makes them testable.
 *
 * It is deliberately built to answer a COMPARATIVE question, not to log raw
 * FPS. "Average FPS is 42" ranks nothing; "p50 fps is 51 with the radar hidden
 * and 33 with it visible, at the same remote-player count" ranks the radar. So
 * every sample carries the context needed to slice it: realm, whether the radar
 * is rendering, draw calls, triangles, live program count, remote players, and
 * a coarse GPU string (integrated vs discrete is the single biggest confound).
 *
 * Cost discipline — this runs on the frame path of a game we are trying to make
 * FASTER, so:
 *   - per frame it does ONE subtraction and ONE array increment into a fixed
 *     histogram. No allocation, no Date, no sort, no closure call.
 *   - the context provider is invoked once per FLUSH (minutes apart), never per
 *     frame.
 *   - percentiles are derived from the histogram at flush time, so we never
 *     retain a sample array.
 *
 * The histogram also survives aggregation: the server merges these bucket
 * arrays across players, so fleet-wide percentiles stay meaningful instead of
 * being an average-of-averages.
 */

/**
 * Frame-time bucket UPPER bounds in ms. Chosen around the frame budgets that
 * matter: 16.7 = 60fps, 33.3 = 30fps, 50 = 20fps. The tail is coarse because
 * once a frame costs >100ms the exact number is not the interesting part.
 */
const BUCKET_MS = [8, 10, 12, 14, 16.7, 20, 25, 33.3, 50, 75, 100, 200];
/** One extra slot for everything over the last bound. */
const BUCKET_COUNT = BUCKET_MS.length + 1;

const DEFAULT_WINDOW_MS = 60_000;
const DEFAULT_FLUSH_MS = 300_000;
/** Below this a window is statistically useless (tab was mostly hidden). */
const MIN_FRAMES_TO_REPORT = 120;

let _hist = new Uint32Array(BUCKET_COUNT);
let _frames = 0;
let _worstMs = 0;
let _windowStartMs = 0;
let _lastFrameMs = 0;
let _nextFlushMs = 0;
let _contextProvider = null;
let _enabled = true;
let _deviceInfo = null;
let _postUrl = '/api/client-perf';
let _windowMs = DEFAULT_WINDOW_MS;
let _flushMs = DEFAULT_FLUSH_MS;
let _inFlight = false;
let _consecutiveFailures = 0;

/**
 * Hitch attribution (2026-07-29). Draw-call work fixed the p50s; the p95/p99
 * spikes (13-20 fps lows across every GPU class) survived, which means they
 * are main-thread stalls, not render cost. Two push-based signals slice them:
 *   - Long Tasks: the browser reports main-thread blocks >=50ms (GC, JS,
 *     parse, layout) with zero frame-path cost. Count + total + worst / window.
 *   - Heap drops (Chrome only): usedJSHeapSize sampled every 64 frames; a
 *     downward step >8MB is a major-GC proxy. `heapMB` tracks the window max.
 * Both reset with the window and ride the existing sample as `hitch` —
 * additive, so an older server simply ignores the field.
 */
let _ltObserver = null;
let _ltN = 0;
let _ltMs = 0;
let _ltWorst = 0;
let _gcDrops = 0;
let _heapMB = 0;
let _lastHeap = 0;
let _heapTick = 0;

/**
 * Phase attribution (2026-07-29). The hitch fields established THAT crowded
 * realms stall the main thread (~118ms average long task at beach/world) but
 * not WHERE. These fixed-key accumulators split main-thread time into the
 * phases that can plausibly own a 50ms+ block, so the fleet aggregate can name
 * the culprit instead of guessing from code reading:
 *   - 'snap'        WS presence-snapshot apply (runs OUTSIDE the frame callback)
 *   - 'raf'         the whole animate() frame callback (includes 'render')
 *   - 'render'      renderer.render alone (so raf-minus-render = JS tick cost)
 *   - 'avatarBuild' avatar construction + static-shell/body merges (spawn churn)
 * Interpretation: a phase whose per-window MAX reaches long-task size owns the
 * stalls; if every phase stays small while ltMs is large, the stalls live in
 * GC / parse / layout — outside our instrumented code.
 * Fixed key set: unknown keys are IGNORED (no cardinality growth), and each
 * add is two number writes + a compare — safe on the hot path.
 */
let _phase = _emptyPhase();
function _emptyPhase() {
  return {
    snap: { ms: 0, n: 0, max: 0 },
    raf: { ms: 0, n: 0, max: 0 },
    render: { ms: 0, n: 0, max: 0 },
    avatarBuild: { ms: 0, n: 0, max: 0 },
  };
}
/** @param {'snap'|'raf'|'render'|'avatarBuild'} key @param {number} ms */
export function addPerfPhaseMs(key, ms) {
  const p = _phase[key];
  if (!p || !Number.isFinite(ms) || ms < 0) return;
  p.ms += ms;
  p.n++;
  if (ms > p.max) p.max = ms;
}
function _phaseOut(p) {
  return { ms: Math.round(p.ms), n: p.n, max: Math.round(p.max) };
}

function ensureLongTaskObserver() {
  if (_ltObserver !== null) return;
  _ltObserver = false; /* only try once — unsupported browsers stay at false */
  try {
    if (typeof PerformanceObserver === 'undefined') return;
    const obs = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        _ltN++;
        _ltMs += e.duration;
        if (e.duration > _ltWorst) _ltWorst = e.duration;
      }
    });
    obs.observe({ type: 'longtask', buffered: false });
    _ltObserver = obs;
  } catch (_) { /* unsupported — hitch fields stay 0, sample still valid */ }
}

function sampleHeap() {
  try {
    const m = performance.memory;
    if (!m || !m.usedJSHeapSize) return;
    const mb = m.usedJSHeapSize / 1048576;
    if (mb > _heapMB) _heapMB = mb;
    if (_lastHeap && _lastHeap - mb > 8) _gcDrops++;
    _lastHeap = mb;
  } catch (_) { /* non-Chrome */ }
}

/** @param {number} ms frame delta */
function bucketFor(ms) {
  for (let i = 0; i < BUCKET_MS.length; i++) {
    if (ms <= BUCKET_MS[i]) return i;
  }
  return BUCKET_COUNT - 1;
}

/**
 * Percentile from the histogram. Returns the bucket's UPPER bound, so the value
 * is an upper estimate of frame time (and therefore a LOWER estimate of fps) —
 * the conservative direction for a perf investigation.
 */
function percentileMs(hist, total, q) {
  if (!total) return 0;
  const want = total * q;
  let seen = 0;
  for (let i = 0; i < hist.length; i++) {
    seen += hist[i];
    if (seen >= want) return i < BUCKET_MS.length ? BUCKET_MS[i] : 250;
  }
  return 250;
}

function msToFps(ms) {
  return ms > 0 ? Math.round(1000 / ms) : 0;
}

/**
 * Coarse, one-time device facts. The GPU string is the load-bearing one: an
 * integrated Intel part and a discrete card produce completely different FPS
 * for identical code, and without it every other comparison is confounded.
 * Truncated, and gathered from a throwaway context that is disposed immediately.
 */
function collectDeviceInfo() {
  const out = { dpr: 0, cores: 0, mem: 0, gpu: '', w: 0, h: 0 };
  try {
    out.dpr = Math.round((window.devicePixelRatio || 1) * 100) / 100;
    out.cores = Number(navigator.hardwareConcurrency) || 0;
    out.mem = Number(navigator.deviceMemory) || 0;
    out.w = window.screen && window.screen.width ? window.screen.width | 0 : 0;
    out.h = window.screen && window.screen.height ? window.screen.height | 0 : 0;
  } catch (_) { /* non-browser / locked down */ }
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2') || c.getContext('webgl');
    if (gl) {
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      if (dbg) out.gpu = String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || '').slice(0, 96);
      const lose = gl.getExtension('WEBGL_lose_context');
      if (lose) lose.loseContext();
    }
  } catch (_) { /* blocked — fleet-wide comparison degrades, nothing breaks */ }
  return out;
}

/**
 * Register the callback that supplies render context. Called ONCE PER FLUSH,
 * not per frame, so it may do real work (read renderer.info, count remotes).
 * @param {() => object} fn
 */
export function setPerfContextProvider(fn) {
  _contextProvider = typeof fn === 'function' ? fn : null;
}

/** Runtime kill switch + tuning, so a bad rollout needs no client deploy. */
export function configurePerfTelemetry(opts = {}) {
  if (typeof opts.enabled === 'boolean') _enabled = opts.enabled;
  if (Number.isFinite(opts.windowMs) && opts.windowMs > 0) _windowMs = Math.max(5_000, Math.min(600_000, opts.windowMs));
  if (Number.isFinite(opts.flushMs) && opts.flushMs > 0) _flushMs = Math.max(30_000, Math.min(3_600_000, opts.flushMs));
  if (typeof opts.url === 'string' && opts.url) _postUrl = opts.url;
}

function resetWindow(nowMs) {
  _hist = new Uint32Array(BUCKET_COUNT);
  _frames = 0;
  _worstMs = 0;
  _windowStartMs = nowMs;
  _ltN = 0;
  _ltMs = 0;
  _ltWorst = 0;
  _gcDrops = 0;
  _heapMB = _lastHeap;
  _phase = _emptyPhase();
}

/** Boot milestones (2026-08-03). Boot cost was invisible: recordPerfFrame only
 *  runs post-sessionReady, so the part of the session players judge first —
 *  fetch/parse/connect — was never measured. Two anchors, both ms from
 *  navigation start, sent ONCE per session on the first successful flush:
 *  evalMs  = this module's evaluation (static import graph fetched + parsed,
 *            game.js body starting);
 *  readyMs = the first gameplay frame (session ready + tab visible). */
const _bootEvalMs = Math.round(
  typeof performance !== 'undefined' && performance.now ? performance.now() : 0
);
let _bootReadyMs = 0;
let _bootSent = false;
function _bootPayload() {
  if (_bootSent || !_bootReadyMs) return undefined;
  let coarse = 0;
  try { coarse = matchMedia('(pointer: coarse)').matches ? 1 : 0; } catch (_) { /* ignore */ }
  return { evalMs: _bootEvalMs, readyMs: _bootReadyMs, coarse };
}

function buildSample(nowMs) {
  const total = _frames;
  const p50 = percentileMs(_hist, total, 0.5);
  const p95 = percentileMs(_hist, total, 0.95);
  const p99 = percentileMs(_hist, total, 0.99);
  let ctx = {};
  try { ctx = (_contextProvider && _contextProvider()) || {}; } catch (_) { ctx = {}; }
  if (!_deviceInfo) _deviceInfo = collectDeviceInfo();
  return {
    boot: _bootPayload(),
    kind: 'frame_window',
    frames: total,
    durMs: Math.round(nowMs - _windowStartMs),
    /** fps is derived from frame-time percentiles: p50 fps comes from p50 frame
     *  time, so "p95" here means the 95th-percentile SLOW frame (low fps). */
    fps: { p50: msToFps(p50), p95: msToFps(p95), p99: msToFps(p99), worst: msToFps(_worstMs) },
    hist: Array.from(_hist),
    ctx: {
      realm: String(ctx.realm || '').slice(0, 24),
      radar: ctx.radar ? 1 : 0,
      calls: Number(ctx.calls) | 0,
      tris: Number(ctx.tris) | 0,
      progs: Number(ctx.progs) | 0,
      tex: Number(ctx.tex) | 0,
      geo: Number(ctx.geo) | 0,
      remotes: Number(ctx.remotes) | 0,
    },
    hitch: {
      ltN: _ltN,
      ltMs: Math.round(_ltMs),
      ltWorst: Math.round(_ltWorst),
      gcDrops: _gcDrops,
      heapMB: Math.round(_heapMB),
    },
    phase: {
      snap: _phaseOut(_phase.snap),
      raf: _phaseOut(_phase.raf),
      render: _phaseOut(_phase.render),
      avatarBuild: _phaseOut(_phase.avatarBuild),
    },
    dev: _deviceInfo,
  };
}

async function flush(nowMs) {
  if (_inFlight || !_enabled) return;
  const sample = buildSample(nowMs);
  _inFlight = true;
  try {
    const r = await fetch(_postUrl, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sample),
    });
    if (r.status === 404 || r.status === 403 || r.status === 501) {
      /** Server does not want these (older build / disabled). Stop entirely
       *  rather than retry forever — telemetry must never become the load. */
      _enabled = false;
    } else if (!r.ok) {
      _consecutiveFailures++;
      if (_consecutiveFailures >= 5) _enabled = false;
    } else {
      _consecutiveFailures = 0;
      /* Boot milestones are one-shot; only stop sending once a flush that
       * carried them actually landed. */
      if (sample.boot) _bootSent = true;
    }
  } catch (_) {
    _consecutiveFailures++;
    if (_consecutiveFailures >= 5) _enabled = false;
  } finally {
    _inFlight = false;
  }
}

/**
 * Call once per rendered frame with a monotonic timestamp (performance.now()).
 * Hot path: one subtraction, one compare chain, one increment.
 * @param {number} nowMs
 */
export function recordPerfFrame(nowMs) {
  if (!_enabled) return;
  if (!_lastFrameMs) {
    _lastFrameMs = nowMs;
    _windowStartMs = nowMs;
    _nextFlushMs = nowMs + _flushMs;
    if (!_bootReadyMs) _bootReadyMs = Math.round(nowMs);
    ensureLongTaskObserver();
    return;
  }
  const dt = nowMs - _lastFrameMs;
  _lastFrameMs = nowMs;
  /** A tab that was hidden or a debugger pause produces a huge delta that is
   *  not a rendering cost. Discard rather than poison the tail. */
  if (dt <= 0 || dt > 2000) return;
  _frames++;
  if (dt > _worstMs) _worstMs = dt;
  _hist[bucketFor(dt)]++;
  if ((++_heapTick & 63) === 0) sampleHeap();

  if (nowMs - _windowStartMs < _windowMs) return;
  if (nowMs >= _nextFlushMs && _frames >= MIN_FRAMES_TO_REPORT) {
    _nextFlushMs = nowMs + _flushMs;
    void flush(nowMs);
  }
  resetWindow(nowMs);
}

/** Test/diagnostic access — never used by the game. */
export const __perfInternals = {
  BUCKET_MS,
  BUCKET_COUNT,
  bucketFor,
  percentileMs,
  msToFps,
  buildSample: (nowMs) => buildSample(nowMs),
  reset: () => {
    _hist = new Uint32Array(BUCKET_COUNT);
    _frames = 0; _worstMs = 0; _lastFrameMs = 0; _windowStartMs = 0;
    _nextFlushMs = 0; _enabled = true; _consecutiveFailures = 0; _deviceInfo = { dpr: 1, cores: 0, mem: 0, gpu: '', w: 0, h: 0 };
    _ltN = 0; _ltMs = 0; _ltWorst = 0; _gcDrops = 0; _heapMB = 0; _lastHeap = 0; _heapTick = 0;
    _phase = _emptyPhase();
    _bootReadyMs = 0; _bootSent = false;
  },
  state: () => ({ frames: _frames, enabled: _enabled, worstMs: _worstMs }),
  /** Phase test hook: read the live accumulator state. */
  _phaseState: () => _phase,
  /** Hitch test hooks: feed synthetic longtask/heap signals without a browser. */
  _hitch: {
    fakeLongTask: (ms) => { _ltN++; _ltMs += ms; if (ms > _ltWorst) _ltWorst = ms; },
    fakeHeap: (mb) => { if (mb > _heapMB) _heapMB = mb; if (_lastHeap && _lastHeap - mb > 8) _gcDrops++; _lastHeap = mb; },
    state: () => ({ ltN: _ltN, ltMs: _ltMs, ltWorst: _ltWorst, gcDrops: _gcDrops, heapMB: _heapMB }),
  },
};
