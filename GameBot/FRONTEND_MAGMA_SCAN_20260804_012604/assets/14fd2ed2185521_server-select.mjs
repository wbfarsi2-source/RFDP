/**
 * Server-selection & queue UX for the Kintara `/play` boot flow.
 *
 * Order of operations after wallet login + display-name + clicking Play:
 *   1. We fetch `/api/servers` for the live population labels (Low / Medium /
 *      High — never raw counts).
 *   2. The player picks Server 1 or Server 2.
 *   3. We open `/ws/queue/sN`. The server replies with either:
 *        - `queue_ready` (a slot was free; reservation now held for us)
 *        - `queue_pos`   (we are queued at position N)
 *      followed by further `queue_pos` updates as the queue advances.
 *   4. On `queue_ready` we resolve and the caller opens `/ws/presence/sN`.
 *
 * The modal lives directly on top of the boot overlay and uses the same
 * Cinzel + gold-on-deep-blue palette as `index.html` so it reads as part
 * of the Kintara boot sequence, not a generic browser popup.
 *
 * Caller contract:
 *   - `chooseServerAndConnect()` resolves with `{ shardId, presenceUrl }`
 *     once a shard is ready for the presence WS upgrade. The boot overlay
 *     phase label is driven through the supplied `setPhase(label, pct)`
 *     hook so every stage feels native to the existing loading screen.
 *   - The DOM is torn down automatically once a shard is ready or the user
 *     hits the retry button after an error.
 */

import { getWalletProvider, getSessionWalletPubkey } from '../auth-gate.js';
import { executeClubMembershipPayment } from '../../club-membership-wallet.mjs';

const SERVERS_API = '/api/servers';
const SERVERS_POLL_MS = 6000;
const QUEUE_PING_MS = 5000;
const QUEUE_CONNECT_TIMEOUT_MS = 15000;
/** Once queued, the server feeds queue_pos two ways: a reply to each q_ping
 *  (every QUEUE_PING_MS) AND a server-initiated keepalive every ~10s
 *  (QUEUE_HEARTBEAT_MS, queue-hub.js) — so a healthy gate is never silent this
 *  long even if a single ping round-trip is dropped. Used as a sliding
 *  "no message received" watchdog AFTER the first message, replacing the old
 *  fixed connect deadline that killed players legitimately waiting in queue.
 *  30s tolerates ~2 missed server keepalives before giving up. */
const QUEUE_STALL_TIMEOUT_MS = 30000;

function readFanoutOrigin() {
  try {
    const raw = typeof window !== 'undefined' ? String(window.KINTARA_READ_FANOUT_ORIGIN || '').trim() : '';
    if (!raw) return '';
    return new URL(raw, location.origin).origin;
  } catch (_) {
    return '';
  }
}

function apiUrl(path) {
  const origin = readFanoutOrigin();
  return origin ? `${origin}${path}` : path;
}

async function readFanoutFetch(path, options) {
  const fanoutUrl = apiUrl(path);
  if (fanoutUrl === path) return fetch(path, options);
  try {
    const r = await fetch(fanoutUrl, { ...(options || {}), credentials: 'omit' });
    if (r && r.ok) return r;
  } catch (_) {
    /* fall back to authoritative server */
  }
  return fetch(path, options);
}

/** Inject the CSS once per page load. The styles deliberately mirror the boot
 *  overlay frame so the selection card looks like a continuation of the boot
 *  sequence (parchment-gold on weave-textured deep blue), not a popup. */
function ensureServerSelectStyles() {
  if (typeof document === 'undefined') return;
  if (document.getElementById('kintara-server-select-style')) return;
  const st = document.createElement('style');
  st.id = 'kintara-server-select-style';
  st.textContent = `
.kintara-server-select-root {
  position: fixed;
  inset: 0;
  z-index: 100000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  pointer-events: auto;
  font-family: 'Inter', system-ui, 'Segoe UI', Roboto, sans-serif;
  color: #d4c4a8;
  /* Solid backdrop so the game canvas / HUD never bleeds through behind
   * the card. Matches the boot overlay palette so this reads as a
   * continuation of the boot sequence rather than a popup. */
  background-color: #121a22;
  isolation: isolate;
}
/* Faint weave + radial bloom ornament identical to .kintara-load-skin, so
 * the selection screen visually matches the rest of the boot flow even
 * when the boot overlay underneath has already faded out. */
.kintara-server-select-root::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image:
    repeating-linear-gradient(
      -32deg,
      transparent 0,
      transparent 7px,
      rgba(255, 200, 120, 0.028) 7px,
      rgba(255, 200, 120, 0.028) 8px
    ),
    repeating-linear-gradient(
      58deg,
      transparent 0,
      transparent 11px,
      rgba(130, 180, 255, 0.022) 11px,
      rgba(130, 180, 255, 0.022) 12px
    ),
    radial-gradient(ellipse 55% 40% at 20% 15%, rgba(255, 150, 70, 0.07) 0%, transparent 55%),
    radial-gradient(ellipse 50% 45% at 85% 75%, rgba(80, 140, 200, 0.06) 0%, transparent 50%);
}
.kintara-server-select-root::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background: repeating-linear-gradient(
    180deg,
    transparent 0 2px,
    rgba(0, 0, 0, 0.06) 2px 3px
  );
  opacity: 0.35;
  mix-blend-mode: multiply;
}
.kintara-server-select-root > * { position: relative; z-index: 1; }
.kintara-server-select-card {
  position: relative;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: min(520px, 100%);
  max-height: calc(100vh - 48px);
  overflow: hidden;
  padding: 26px 28px 24px;
  text-align: center;
  border: 2px solid rgba(100, 140, 180, 0.42);
  border-radius: 16px;
  background: linear-gradient(
    165deg,
    rgba(40, 58, 78, 0.97) 0%,
    rgba(24, 38, 54, 0.98) 45%,
    rgba(16, 24, 34, 0.99) 100%
  );
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    inset 0 -14px 36px rgba(0, 0, 0, 0.28),
    0 12px 42px rgba(8, 14, 24, 0.55),
    0 2px 0 rgba(255, 200, 140, 0.06);
}
.kintara-server-select-card::before,
.kintara-server-select-card::after {
  content: '◆';
  position: absolute;
  top: 14px;
  font-size: 12px;
  color: rgba(255, 190, 120, 0.5);
  text-shadow: 0 0 12px rgba(120, 190, 255, 0.2);
}
.kintara-server-select-card::before { left: 18px; }
.kintara-server-select-card::after { right: 18px; }
.kintara-server-select-sub {
  margin: 0 0 12px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: rgba(170, 195, 220, 0.6);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
}
.kintara-server-select-title {
  font-family: 'Cinzel', Georgia, 'Times New Roman', serif;
  font-size: clamp(24px, 4.5vw, 32px);
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin: 0 0 8px;
  background: linear-gradient(180deg, #fff8e4 0%, #ffd463 25%, #e88820 65%, #9a4a12 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 1px 0 rgba(55, 28, 8, 0.95)) drop-shadow(0 2px 6px rgba(0, 0, 0, 0.55));
}
.kintara-server-select-blurb {
  margin: 0 0 22px;
  font-size: 13px;
  font-weight: 600;
  color: rgba(200, 215, 235, 0.75);
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.6);
}
.kintara-server-zone-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: -4px 0 14px;
}
.kintara-server-zone-tab {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 72px;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid rgba(100, 140, 180, 0.38);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.05) 0%, transparent 40%),
    linear-gradient(180deg, rgba(32, 48, 66, 0.95) 0%, rgba(17, 27, 40, 0.98) 100%);
  color: rgba(210, 224, 242, 0.72);
  cursor: pointer;
  text-align: center;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.07),
    inset 0 -4px 14px rgba(0, 0, 0, 0.32),
    0 1px 0 rgba(255, 200, 140, 0.04);
  overflow: hidden;
}
.kintara-server-zone-tab::before {
  content: '';
  position: absolute;
  left: 10px;
  right: 10px;
  top: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent 0%, rgba(130, 180, 220, 0.35) 50%, transparent 100%);
}
.kintara-server-zone-tab:hover,
.kintara-server-zone-tab:focus-visible {
  outline: none;
  border-color: rgba(255, 190, 120, 0.5);
  filter: brightness(1.06);
}
.kintara-server-zone-tab[aria-selected='true'] {
  border-color: rgba(255, 190, 120, 0.78);
  color: #f5e6c6;
  background:
    radial-gradient(ellipse 90% 120% at 50% -20%, rgba(255, 190, 100, 0.16) 0%, transparent 58%),
    linear-gradient(180deg, rgba(58, 70, 78, 0.98) 0%, rgba(32, 45, 58, 0.98) 100%);
}
.kintara-server-zone-tab[aria-selected='true']::before {
  background: linear-gradient(90deg, transparent 0%, rgba(255, 205, 118, 0.8) 50%, transparent 100%);
}
.kintara-server-zone-tab__copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: center;
}
.kintara-server-zone-tab__label {
  font-family: 'Cinzel', Georgia, 'Times New Roman', serif;
  font-size: 18px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #f0e1c0;
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.85);
}
.kintara-server-zone-tab__sub {
  font-size: 8.5px;
  font-weight: 900;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(170, 195, 220, 0.58);
  white-space: nowrap;
}
.kintara-server-zone-tab__count {
  display: block;
  width: 100%;
  min-width: 0;
  padding: 4px 6px;
  border-radius: 999px;
  border: 1px solid rgba(122, 223, 143, 0.65);
  color: #92eea4;
  font-size: 9px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-align: center;
  text-transform: uppercase;
  box-shadow: inset 0 0 12px rgba(122, 223, 143, 0.1);
}
.kintara-server-zone-tab__count[data-empty='true'] {
  border-color: rgba(170, 195, 220, 0.34);
  color: rgba(170, 195, 220, 0.62);
  box-shadow: none;
}
.kintara-server-select-list {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  gap: 8px;
  margin: 0;
  /* Only the list scrolls — the header above stays pinned. The old fixed
   * calc(100vh - 410px) assumed ~410px of chrome above/below the list; on a
   * landscape phone (390-412px tall) that computed to 0 and the list vanished
   * entirely — no server could be picked. Floor it so at least ~2 rows always
   * show, use dvh so iOS browser-chrome collapse doesn't over-count, and let
   * the card's own max-height do the fine clamping. */
  max-height: max(140px, calc(100dvh - 300px));
  overflow-y: auto;
  overscroll-behavior: contain;
  /* Inset the scrollbar from the card's rounded corner, and leave a little
   * top/side breathing room so a card's hover lift + orange outline isn't
   * clipped by the scroll container's edge (overflow-y:auto also clips x). */
  padding: 3px 10px 20px 2px;
  /* Themed scrollbar — Firefox */
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.5) transparent;
}
/* Short viewports (landscape phones): slim the ornamental header so the
 * server list — the only part the player actually needs — keeps the room. */
@media (max-height: 480px) {
  .kintara-server-select-root { padding: 10px; }
  .kintara-server-select-card { max-height: calc(100dvh - 20px); padding: 12px 18px 12px; }
  .kintara-server-select-sub { display: none; }
  .kintara-server-select-blurb { display: none; }
  .kintara-server-select-title { margin: 0 0 6px; font-size: clamp(18px, 4.5vh, 24px); }
  .kintara-server-select-list { max-height: none; }
}
.kintara-server-zone-empty {
  padding: 22px 16px;
  border-radius: 10px;
  border: 1px solid rgba(100, 140, 180, 0.32);
  background:
    radial-gradient(ellipse 90% 120% at 50% -30%, rgba(100, 140, 180, 0.12) 0%, transparent 60%),
    linear-gradient(180deg, rgba(28, 42, 58, 0.82) 0%, rgba(16, 24, 36, 0.9) 100%);
  color: rgba(205, 220, 238, 0.72);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  text-align: center;
}
/* Themed scrollbar — WebKit/Chromium */
.kintara-server-select-list::-webkit-scrollbar {
  width: 8px;
}
.kintara-server-select-list::-webkit-scrollbar-track {
  background: transparent;
  margin: 2px 0;
}
.kintara-server-select-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
}
.kintara-server-select-list::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.7);
}
.kintara-server-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  border-radius: 10px;
  cursor: pointer;
  border: 1px solid rgba(100, 140, 180, 0.32);
  background: linear-gradient(180deg, rgba(36, 52, 72, 0.92) 0%, rgba(20, 30, 44, 0.96) 100%);
  text-align: left;
  transition: transform 120ms ease, border-color 120ms ease, filter 120ms ease;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    inset 0 -3px 12px rgba(0, 0, 0, 0.32);
}
.kintara-server-card:hover,
.kintara-server-card:focus-visible {
  border-color: rgba(255, 190, 120, 0.55);
  filter: brightness(1.08);
  outline: none;
  transform: translateY(-1px);
}
.kintara-server-card[disabled] {
  cursor: not-allowed;
  filter: grayscale(0.4) brightness(0.78);
}
.kintara-server-card--joining,
.kintara-server-card--joining[disabled] {
  cursor: wait;
  border-color: rgba(255, 190, 120, 0.78);
  filter: brightness(1.08);
  background:
    radial-gradient(ellipse 70% 140% at 88% 50%, rgba(255, 180, 80, 0.12) 0%, transparent 62%),
    linear-gradient(180deg, rgba(42, 58, 78, 0.98) 0%, rgba(24, 36, 52, 0.99) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    inset 0 -3px 14px rgba(0, 0, 0, 0.34),
    0 0 0 1px rgba(255, 190, 120, 0.18),
    0 0 18px rgba(255, 160, 64, 0.12);
}
.kintara-server-card__name {
  font-family: 'Cinzel', Georgia, 'Times New Roman', serif;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #f0e1c0;
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.8);
}
.kintara-server-card__hint {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(170, 195, 220, 0.55);
  margin-top: 2px;
}
.kintara-server-card__bossq {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(170, 195, 220, 0.55);
  margin-top: 2px;
}
.kintara-server-card__pop {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 9.5px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  border: 1px solid currentColor;
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.6);
}
.kintara-server-card__pop::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 8px currentColor;
}
.kintara-server-card__pop[data-bucket='Low'] { color: #7adf8f; }
.kintara-server-card__pop[data-bucket='Medium'] { color: #ffd56b; }
.kintara-server-card__pop[data-bucket='High'] { color: #ff9072; }
.kintara-server-card__pop[data-bucket='Full'] { color: #ff7280; }
.kintara-server-card__pop[data-bucket='Joining'] { color: #ffd56b; }
.kintara-server-card__pop[data-bucket='Joining']::before {
  width: 9px;
  height: 9px;
  background: transparent;
  border: 2px solid currentColor;
  border-top-color: transparent;
  box-shadow: none;
  animation: kintara-server-select-spin 0.8s linear infinite;
}
@keyframes kintara-server-select-spin {
  to { transform: rotate(360deg); }
}

/* ── Queue state ───────────────────────────────────────────────────────── */
.kintara-server-select-queue {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 8px 4px 16px;
}
.kintara-server-select-queue__line1 {
  font-family: 'Cinzel', Georgia, 'Times New Roman', serif;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #f0e1c0;
}
.kintara-server-select-queue__line2 {
  font-size: 14px;
  font-weight: 700;
  color: rgba(220, 232, 250, 0.85);
}
.kintara-server-select-queue__pos {
  font-family: 'Cinzel', Georgia, 'Times New Roman', serif;
  font-size: 44px;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: transparent;
  background: linear-gradient(180deg, #fff8e4 0%, #ffd463 28%, #e88820 70%, #9a4a12 100%);
  -webkit-background-clip: text;
  background-clip: text;
  filter: drop-shadow(0 2px 3px rgba(0, 0, 0, 0.6));
}
.kintara-server-select-queue__bar {
  margin: 6px auto 0;
  width: min(280px, 78%);
  height: 10px;
  border-radius: 999px;
  padding: 3px;
  background: linear-gradient(180deg, rgba(36, 48, 62, 0.95) 0%, rgba(14, 20, 30, 0.98) 100%);
  border: 1px solid rgba(100, 140, 180, 0.28);
  overflow: hidden;
}
.kintara-server-select-queue__barFill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(180deg, #fff0c8 0%, #ffb24a 35%, #d66a18 72%, #8f3d0c 100%);
  box-shadow: 0 0 10px rgba(255, 180, 80, 0.4);
  transition: width 0.35s ease;
  width: 8%;
}
.kintara-server-select-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 8px;
}
.kintara-server-select-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 120px;
  padding: 10px 22px;
  font-family: 'Inter', system-ui, 'Segoe UI', Roboto, sans-serif;
  font-weight: 800;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  cursor: pointer;
  border-radius: 10px;
  border: 1px solid rgba(100, 140, 180, 0.35);
  color: #d4c4a8;
  background: linear-gradient(180deg, rgba(48, 68, 90, 0.92) 0%, rgba(22, 34, 50, 0.96) 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
  transition: transform 120ms ease, filter 120ms ease;
}
.kintara-server-select-btn:hover,
.kintara-server-select-btn:focus-visible {
  outline: none;
  filter: brightness(1.12);
  border-color: rgba(255, 190, 120, 0.55);
}
.kintara-server-select-btn--primary {
  color: #4f210a;
  border-color: #6e3010;
  background: linear-gradient(180deg, #ffaf5e 0%, #ff8a3a 48%, #ed6f1c 100%);
  text-shadow: 0 1px 0 rgba(255, 228, 170, 0.42);
  box-shadow:
    inset 0 2px 0 rgba(255, 236, 200, 0.55),
    inset 0 -3px 10px rgba(110, 42, 10, 0.38);
}
.kintara-server-select-btn[disabled] {
  cursor: progress;
  filter: grayscale(0.2) brightness(0.85);
}

/* ── Error state ───────────────────────────────────────────────────────── */
.kintara-server-select-error {
  padding: 16px 18px;
  border-radius: 10px;
  margin: 12px 0 14px;
  background: rgba(120, 28, 28, 0.32);
  border: 1px solid rgba(255, 140, 140, 0.32);
  color: #ffd0d0;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.45;
}

.kintara-server-select-loader {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 24px 18px;
  box-sizing: border-box;
}
.kintara-server-select-loader__bars {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 7px;
  height: 48px;
}
.kintara-server-select-loader__bars span {
  display: block;
  width: 8px;
  height: 32px;
  border-radius: 6px;
  flex-shrink: 0;
  overflow: hidden;
  transform-origin: center bottom;
  background: linear-gradient(180deg, rgba(130,190,255,0.38) 0%, rgba(55,85,120,0.72) 42%, rgba(22,32,48,0.98) 100%);
  border: 1px solid rgba(100,150,200,0.32);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.12);
  animation: kintara-loader-bar 1.12s cubic-bezier(0.45,0.05,0.55,0.95) infinite;
}
.kintara-server-select-loader__bars span::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(180deg, #fff6dc 0%, #ffc658 32%, #e07018 68%, #6a2e0a 100%);
  opacity: 0;
  animation: kintara-loader-bar-glow 1.12s cubic-bezier(0.45,0.05,0.55,0.95) infinite;
}
.kintara-server-select-loader__bars span:nth-child(1),
.kintara-server-select-loader__bars span:nth-child(1)::before { animation-delay: 0ms; }
.kintara-server-select-loader__bars span:nth-child(2),
.kintara-server-select-loader__bars span:nth-child(2)::before { animation-delay: 100ms; }
.kintara-server-select-loader__bars span:nth-child(3),
.kintara-server-select-loader__bars span:nth-child(3)::before { animation-delay: 200ms; }
.kintara-server-select-loader__bars span:nth-child(4),
.kintara-server-select-loader__bars span:nth-child(4)::before { animation-delay: 300ms; }
.kintara-server-select-loader__bars span:nth-child(5),
.kintara-server-select-loader__bars span:nth-child(5)::before { animation-delay: 400ms; }
.kintara-server-select-loader__bars span:nth-child(6),
.kintara-server-select-loader__bars span:nth-child(6)::before { animation-delay: 500ms; }
.kintara-server-select-loader__bars span:nth-child(7),
.kintara-server-select-loader__bars span:nth-child(7)::before { animation-delay: 600ms; }
@keyframes kintara-loader-bar {
  0%, 100% { transform: scaleY(0.38); }
  40% { transform: scaleY(1); }
  65% { transform: scaleY(0.52); }
}
@keyframes kintara-loader-bar-glow {
  0%, 100% { opacity: 0; }
  40% { opacity: 1; }
  65% { opacity: 0.12; }
}
.kintara-server-select-loader__label {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #c8d0e0;
  text-shadow: 0 1px 0 rgba(0,0,0,0.85), 0 0 18px rgba(140,190,255,0.12);
  min-height: 1.3em;
}

/* ── Kintara Club membership modal ─────────────────────────────────────────
 * Reuses the selection-screen design language (parchment panel, ◆ corner
 * marks, Cinzel gold-foil headings, server-card tiers) so the subscription
 * flow reads as part of the game rather than a bolted-on popup. */
.kintara-club-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
  z-index: 40;
  background:
    radial-gradient(ellipse 60% 50% at 50% 40%, rgba(10, 16, 30, 0.7) 0%, transparent 70%),
    rgba(6, 10, 22, 0.86);
}
.kintara-club-modal {
  position: relative;
  width: min(440px, 100%);
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  padding: 26px 26px 22px;
  text-align: center;
  border: 2px solid rgba(201, 162, 58, 0.5);
  border-radius: 16px;
  background: linear-gradient(
    165deg,
    rgba(40, 58, 78, 0.97) 0%,
    rgba(24, 38, 54, 0.98) 45%,
    rgba(16, 24, 34, 0.99) 100%
  );
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    inset 0 -14px 36px rgba(0, 0, 0, 0.28),
    0 12px 42px rgba(8, 14, 24, 0.6),
    0 0 22px rgba(201, 162, 58, 0.1);
  color: #f3e7c4;
  font-family: 'Inter', system-ui, 'Segoe UI', Roboto, sans-serif;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.5) transparent;
}
.kintara-club-modal::-webkit-scrollbar { width: 8px; }
.kintara-club-modal::-webkit-scrollbar-thumb { border-radius: 999px; background: rgba(255, 255, 255, 0.4); }
.kintara-club-modal::before,
.kintara-club-modal::after {
  content: '◆';
  position: absolute;
  top: 14px;
  font-size: 12px;
  color: rgba(255, 210, 130, 0.6);
  text-shadow: 0 0 12px rgba(255, 200, 120, 0.3);
}
.kintara-club-modal::before { left: 18px; }
.kintara-club-modal::after { right: 18px; }
.kintara-club-modal__eyebrow {
  margin: 0 0 8px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: rgba(201, 162, 58, 0.85);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
}
.kintara-club-modal__title {
  font-family: 'Cinzel', Georgia, 'Times New Roman', serif;
  font-size: clamp(22px, 4vw, 28px);
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin: 0 0 8px;
  background: linear-gradient(180deg, #fff8e4 0%, #ffd463 25%, #e88820 65%, #9a4a12 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 1px 0 rgba(55, 28, 8, 0.95)) drop-shadow(0 2px 6px rgba(0, 0, 0, 0.55));
}
.kintara-club-modal__blurb {
  margin: 0 auto 16px;
  max-width: 360px;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  color: rgba(200, 215, 235, 0.78);
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.6);
}
.kintara-club-tiers {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 4px;
}
.kintara-club-tier {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 12px 16px;
  border-radius: 10px;
  cursor: pointer;
  text-align: left;
  border: 1px solid rgba(100, 140, 180, 0.32);
  background: linear-gradient(180deg, rgba(36, 52, 72, 0.92) 0%, rgba(20, 30, 44, 0.96) 100%);
  transition: transform 120ms ease, border-color 120ms ease, filter 120ms ease;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    inset 0 -3px 12px rgba(0, 0, 0, 0.32);
}
.kintara-club-tier:hover:not(:disabled),
.kintara-club-tier:focus-visible:not(:disabled) {
  border-color: rgba(255, 190, 120, 0.55);
  filter: brightness(1.08);
  outline: none;
  transform: translateY(-1px);
}
.kintara-club-tier:disabled { cursor: progress; filter: grayscale(0.3) brightness(0.8); }
.kintara-club-tier--best { border-color: rgba(201, 162, 58, 0.7); }
/* Sold out (env-gated): muted, non-interactive, price replaced with SOLD OUT. */
.kintara-club-tier--soldout { cursor: not-allowed; filter: grayscale(0.55) brightness(0.8); }
.kintara-club-tier--soldout:hover { transform: none; border-color: rgba(100, 140, 180, 0.32); }
.kintara-club-tier--soldout .kintara-club-tier__price {
  background: none;
  -webkit-background-clip: border-box;
  background-clip: border-box;
  color: #d98c8c;
  font-size: 14px;
  letter-spacing: 0.1em;
}
.kintara-club-tier__left { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.kintara-club-tier__name {
  font-family: 'Cinzel', Georgia, 'Times New Roman', serif;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #f0e1c0;
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.8);
}
.kintara-club-tier__sub {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(170, 195, 220, 0.6);
}
.kintara-club-tier__right { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; flex: none; }
.kintara-club-tier__price {
  font-family: 'Cinzel', Georgia, 'Times New Roman', serif;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0.02em;
  background: linear-gradient(180deg, #fff8e4 0%, #ffd463 42%, #e88820 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.5));
}
.kintara-club-tier__cur {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(170, 195, 220, 0.55);
}
.kintara-club-tier__badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 8.5px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #4f210a;
  background: linear-gradient(180deg, #ffd463 0%, #e88820 100%);
  box-shadow: inset 0 1px 0 rgba(255, 240, 200, 0.5);
  vertical-align: middle;
}
.kintara-club-foot {
  margin: 14px 0 0;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(170, 195, 220, 0.45);
}
.kintara-club-status {
  min-height: 18px;
  margin: 12px 0 2px;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.45;
  color: rgba(200, 215, 235, 0.82);
}
.kintara-club-status--err { color: #ff9a8a; }
`;
  document.head.appendChild(st);
}

/** Tiny helper around the shared boot-overlay phase setter exposed by `index.html`. */
function setBootPhase(label, pct) {
  try {
    if (typeof window !== 'undefined' && typeof window.__kintaraLoadingPhase === 'function') {
      window.__kintaraLoadingPhase(label, pct);
    }
  } catch (_) { /* ignore */ }
}

function setBootConnectingMode(label) {
  try {
    if (typeof window !== 'undefined' && typeof window.__kintaraLoadingShowConnecting === 'function') {
      window.__kintaraLoadingShowConnecting(label);
    }
  } catch (_) { /* ignore */ }
}

function serverRegionAcronym(server) {
  const raw = String((server && (server.region || server.zone || server.regionLabel || server.zoneLabel)) || '').trim().toLowerCase();
  if (!raw) return '';
  if (raw === 'us' || raw === 'usa' || raw === 'na' || raw === 'north-america' || raw === 'north_america' || raw.includes('america')) return 'NA';
  if (raw === 'eu' || raw === 'eur' || raw === 'europe' || raw.includes('europe')) return 'EUR';
  if (raw === 'asia' || raw === 'as' || raw === 'apac' || raw === 'asia-pacific' || raw === 'asia_pacific' || raw.includes('asia') || raw.includes('pacific')) return 'ASIA';
  return raw.toUpperCase().replace(/_/g, '-');
}

/** Fetch the live server list — ALWAYS from the authoritative server, never
 *  the read-fanout origin. The fanout box was caught serving a copy frozen at
 *  the pre-expansion fleet (exactly 10 entries: 5 clubs + 5 servers, vs 31
 *  live), which also slid past the first fix's <10 length floor by one. The
 *  list is tiny and only fetched when the picker opens, so the authoritative
 *  box answers it trivially; no length heuristic can distinguish a stale
 *  complete-looking list from a fresh one, so the only correct source is the
 *  server that owns the data. */
async function fetchServers() {
  const r = await fetch(SERVERS_API, { credentials: 'include', cache: 'no-store' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const j = await r.json().catch(() => null);
  if (!j || j.ok !== true || !Array.isArray(j.servers)) throw new Error('invalid_response');
  /** Stash shardId→name so the in-game server badge (game.js) can render the
   *  authoritative label ("Level 20 Server" / "Server 1") instead of the raw
   *  shard id. Special servers are pulled OUT of the numbering, so raw id != label. */
  try {
    if (typeof window !== 'undefined') {
      const names = {};
      const regions = {};
      for (const s of j.servers) {
        if (s && s.id != null) {
          const id = Number(s.id) | 0;
          names[id] = String(s.name || '');
          regions[id] = serverRegionAcronym(s);
        }
      }
      window.__kintaraServerNamesByShard = names;
      window.__kintaraServerRegionsByShard = regions;
    }
  } catch (_) { /* ignore */ }
  return { servers: j.servers, adminBypass: j.adminBypass === true };
}

function wsBaseIsCrossOrigin(base) {
  const b = String(base || '').trim();
  if (!b || typeof location === 'undefined') return false;
  try {
    const httpBase = b.replace(/^wss:/i, 'https:').replace(/^ws:/i, 'http:');
    return new URL(httpBase, location.href).origin !== location.origin;
  } catch (_) {
    return true;
  }
}

function appendConnectToken(url, token) {
  const t = String(token || '').trim();
  if (!t) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}kt=${encodeURIComponent(t)}`;
}

/** Compose `wss://...` or `ws://...` URL for a given relative path. */
function wsUrl(path, base, connectToken = '') {
  // Host-aware: when a server entry carries an absolute ws(s):// (or http(s)://)
  // base, connect directly to THAT server's host — this is what lets the client
  // reach a fleet of servers on different machines. Empty base => same-origin
  // (current single-host behaviour), so this is fully backward-compatible.
  const b = String(base || '').trim();
  if (b) return appendConnectToken(`${b.replace(/^http/i, 'ws').replace(/\/+$/, '')}${path}`, connectToken);
  const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = typeof location !== 'undefined' ? location.host : 'localhost';
  return appendConnectToken(`${proto}//${host}${path}`, connectToken);
}

/**
 * Public entry point. Returns a promise resolving to `{ shardId, presenceUrl }`
 * once the player has both picked a server and reached the front of its queue
 * (or walked straight in if the shard had capacity). On any unrecoverable
 * error the promise rejects.
 *
 * The function takes ownership of the boot overlay phase label and renders
 * its own card on top of the existing overlay. The card and any open queue
 * WebSocket are cleaned up before the promise settles.
 *
 * Options (used by the in-game "Switch Server" flow — boot passes none):
 *   - `allowCancel`     show a "Back to game" control that rejects with
 *                       `server_select_cancelled` so the caller can resume the
 *                       world it was already in instead of treating it as a fail.
 *   - `currentShardId`  the shard the player is on right now; rendered as
 *                       "Current server" and not re-joinable (no-op pick).
 *   - `currentZone`     geographic fleet of that server; keeps the switcher on
 *                       EU/Asia instead of resetting its selected tab to NA.
 */
export function chooseServerAndConnect(options = {}) {
  const allowCancel = !!(options && options.allowCancel);
  const currentShardId =
    options && Number(options.currentShardId) > 0 ? Number(options.currentShardId) | 0 : 0;
  /** Globally-unique DISPLAY id of the server we actually joined — settle()
   *  persists it on every successful join (incl. auto-join and token
   *  re-mints). 0 when unknown (direct-entry edge), where (route, zone) stays
   *  the best available signal. */
  const currentDisplayServerId =
    typeof window !== 'undefined' && Number(window.__kintaraSelectedDisplayServerId) > 0
      ? Number(window.__kintaraSelectedDisplayServerId) | 0
      : 0;
  /** "Stalk a friend" / follow flow: skip the picker and queue straight into a
   *  known shard (the friend's). All gates + the full queue still apply. */
  const autoJoinShardId =
    options && Number(options.autoJoinShardId) > 0 ? Number(options.autoJoinShardId) | 0 : 0;
  return new Promise((resolve, reject) => {
    ensureServerSelectStyles();

    /** Root DOM. The selection card is appended directly to body so the boot
     *  overlay (still visible underneath) provides the background ornament. */
    const root = document.createElement('div');
    root.className = 'kintara-server-select-root';
    /** aria-modal: the game's window-level click-to-move handler treats
     *  `[aria-modal="true"]` ancestors as HUD — without it, clicks on the
     *  server buttons fell through to the world raycast and walked the
     *  player (works even after settle() detaches the root: closest()
     *  traverses the detached subtree). */
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    const card = document.createElement('div');
    card.className = 'kintara-server-select-card';
    root.appendChild(card);
    document.body.appendChild(root);

    /** Returned to caller after successful shard pick. */
    let activeQueueWs = null;
    let pollTimer = null;
    /** Set by renderSelection so the membership modal can repaint + resume polling on close. */
    let refreshSelectionRef = null;
    let pingTimer = null;
    let settled = false;
    let adminBypassQueue = false;
    /** Phase label shown on the boot overlay at the final "connecting to the world"
     *  step. Normal entry says "Joining the world…"; the stalk/auto-join path
     *  overrides this to "Entering <server>…" so the whole hop reads as a server
     *  entry (per the in-game "stalk a friend" flow). */
    let joinPhaseLabel = 'Joining the world…';
    /** Throttle for the auto-retry on a transient gate failure (RPC balance check
     *  busy). We retry at most ONCE per 5s so a throttled backend isn't hammered by
     *  the client either — mirrors the server-side cooldown. */
    let gateAutoRetryAt = 0;
    let gateAutoRetryCount = 0;
    const GATE_AUTO_RETRY_MS = 5000;
    const GATE_AUTO_RETRY_MAX = 3;
    /** Mid-queue reconnect: when the queue WS drops AFTER we had connected (a
     *  transport blip, coordinator event-loop spike, brief gateway hiccup, worker
     *  rebalance or rolling deploy), silently re-join the SAME shard's queue
     *  instead of dumping the player on the "Something went wrong" screen. Bounded
     *  so a genuinely down gate still fails to a manual Retry. The counter is
     *  forgiven once a fresh connection stays healthy for QUEUE_RECONNECT_STABLE_MS
     *  (see startQueueFor), so a long, blip-prone wait isn't capped by old blips.
     *  NOTE: the server drops a queued player's spot the instant the socket
     *  closes, so an auto-rejoin re-enters at the back of the queue — still far
     *  better than a dead-end error. */
    let queueReconnectCount = 0;
    const QUEUE_RECONNECT_MAX = 6;
    const QUEUE_RECONNECT_DELAY_MS = 1200;
    const QUEUE_RECONNECT_STABLE_MS = 12000;
    /** The queue card's follow-up line, so the reconnect path can swap in a
     *  "reconnecting…" hint on the persistent card without a jarring repaint. */
    let queueStatusEl = null;
    /** Env-gated (default on): when true, the Club membership payment tiers render
     *  as SOLD OUT (not purchasable) for non-members. Set from /api/club/status. */
    let clubSoldOut = true;
    /** Absolute ws(s):// base of the server the player picked (multi-server fleet).
     *  Empty => same-origin. Set from the chosen server entry's wsBaseUrl on click. */
    let selectedWsBase = '';
    /** Read-fanout origin of the picked server's REGION. Empty => keep whatever
     *  the page loaded with (single-region / legacy controllers). Adopted into
     *  window.KINTARA_READ_FANOUT_ORIGIN at settle so merchant WS, spectate and
     *  cached reads all follow the player to the region-local fanout instead of
     *  staying pinned to the fanout of the box that served the HTML. */
    let selectedFanoutOrigin = '';
    /** Fleet (us/eu/asia) of the picked server — published as
     *  window.__kintaraSelectedFleet at settle so chat calls can scope to the
     *  realm (world_chat fleet column, migration 0048). */
    let selectedFleet = '';
    let selectedServerName = '';
    let selectedServerRegionTag = '';
    /** DISPLAY id of the entry being joined — the only fleet-unique server
     *  key. Sent with connect-token requests so the lobby gates against the
     *  exact box instead of the ambiguous (zone, local shard) pair. */
    let selectedDisplayServerId = 0;
    let selectedPresenceConnectToken = '';
    const currentZone = normalizeZoneId(
      (options && options.currentZone) ||
      (typeof window !== 'undefined' && window.__kintaraSelectedFleet) ||
      'us'
    );
    let selectedZone = currentZone;
    let joiningRouteShardId = 0;
    const BASE_ZONES = [
      { id: 'us', label: 'NA', sub: 'Americas' },
      { id: 'eu', label: 'EUR', sub: 'Europe' },
      { id: 'asia', label: 'ASIA', sub: 'Pacific' },
    ];
    function normalizeZoneId(value) {
      const raw = String(value || '').trim().toLowerCase();
      if (!raw) return 'us';
      if (raw === 'usa' || raw === 'na' || raw === 'north-america' || raw === 'north_america') return 'us';
      if (raw === 'europe') return 'eu';
      if (raw === 'apac' || raw === 'asia-pacific' || raw === 'asia_pacific') return 'asia';
      return raw.replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'us';
    }
    function zoneMetaFor(id, servers) {
      const zid = normalizeZoneId(id);
      const fromBase = BASE_ZONES.find(z => z.id === zid);
      const match = (servers || []).find(s => normalizeZoneId(s && (s.zone || s.region)) === zid);
      const label = match && (match.zoneLabel || match.regionLabel);
      const sub = match && (match.zoneSubtitle || match.zoneSub || match.subtitle);
      if (fromBase) return { ...fromBase, label: label ? String(label) : fromBase.label, sub: sub ? String(sub) : fromBase.sub };
      return {
        id: zid,
        label: label ? String(label) : zid.toUpperCase(),
        sub: sub ? String(sub) : 'Server Region',
      };
    }
    function zoneLabelFor(id, servers) {
      return zoneMetaFor(id, servers).label;
    }
    function zonesForServers(servers) {
      /** Only render zones the lobby actually configured servers for. BASE_ZONES
       *  is an ordering/label template, not a promise — painting all three
       *  unconditionally put a ghost "Soon" tab next to the real one when an
       *  environment runs fewer regions (dev runs 2). */
      const present = new Set((servers || []).map(s => normalizeZoneId(s && (s.zone || s.region))));
      const zones = BASE_ZONES.filter(z => present.has(z.id)).map(z => zoneMetaFor(z.id, servers));
      const seen = new Set(zones.map(z => z.id));
      for (const s of servers || []) {
        const id = normalizeZoneId(s && (s.zone || s.region));
        if (seen.has(id)) continue;
        seen.add(id);
        zones.push(zoneMetaFor(id, servers));
      }
      return zones;
    }
    async function fetchWsConnectToken(shardId, purpose) {
      if (!wsBaseIsCrossOrigin(selectedWsBase)) return '';
      const q = new URLSearchParams({
        shard: String(Math.max(1, Number(shardId) | 0 || 1)),
        purpose: String(purpose || 'queue'),
      });
      /** Bind the minted token to the fleet the player picked, so the lobby can
       *  gate eligibility against the RIGHT fleet's shard and the controller can
       *  reject a token replayed against another fleet's shard of the same id. */
      if (selectedFleet) q.set('zone', selectedFleet);
      /** Fleet-unique display id -> the lobby resolves the gate for the exact
       *  box (us2 "Server 14" is local 3, same pair as US-01's club shard). */
      if (selectedDisplayServerId > 0) q.set('display', String(selectedDisplayServerId));
      const r = await fetch(`/api/lobby/connect-token?${q.toString()}`, {
        credentials: 'include',
        cache: 'no-store',
      });
      if (r.status === 404) return '';
      const j = await r.json().catch(() => null);
      if (!r.ok || !j || j.ok !== true || !j.token) {
        const err = j && j.error ? String(j.error) : 'connect_token_failed';
        throw new Error(err);
      }
      return String(j.token || '');
    }
    /** Viewer's average skill level — fetched once so level-gated special servers
     *  (minLevel > 0) can be greyed out before the player clicks. null = unknown
     *  (fetch failed); we then DON'T pre-lock and let the server gate decide. */
    let viewerAvgLevel = null;
    async function fetchViewerLevel() {
      try {
        // Player-specific → authoritative server, never the read-fanout cache.
        const r = await fetch('/api/auth/viewer-level', { credentials: 'include', cache: 'no-store' });
        const j = await r.json().catch(() => null);
        viewerAvgLevel = j && j.ok && Number.isFinite(Number(j.avgLevel)) ? Number(j.avgLevel) | 0 : null;
      } catch (_) {
        viewerAvgLevel = null;
      }
    }

    /** Viewer's Kintara Club membership + the purchasable tiers — fetched once so
     *  the members-only server can show "join" vs "subscribe". null = unknown
     *  (fetch failed); we then don't pre-lock and let the server gate decide. */
    let viewerMembership = null; // { active, expiresAtMs, tier } | null
    let clubTiers = [];
    async function fetchViewerMembership() {
      try {
        const r = await fetch('/api/club/status', { credentials: 'include', cache: 'no-store' });
        const j = await r.json().catch(() => null);
        if (j && j.ok) {
          viewerMembership = j.membership || null;
          clubTiers = Array.isArray(j.tiers) ? j.tiers : [];
          clubSoldOut = j.soldOut !== false;
        } else {
          viewerMembership = null;
        }
      } catch (_) {
        viewerMembership = null;
      }
    }
    const memberIsActive = () => !!(viewerMembership && viewerMembership.active);

    function tearDown() {
      try { if (pollTimer != null) clearInterval(pollTimer); } catch (_) { /* ignore */ }
      try { if (pingTimer != null) clearInterval(pingTimer); } catch (_) { /* ignore */ }
      pollTimer = null;
      pingTimer = null;
      if (activeQueueWs) {
        try { activeQueueWs.onmessage = null; activeQueueWs.onclose = null; activeQueueWs.onerror = null; } catch (_) { /* ignore */ }
        try { activeQueueWs.close(); } catch (_) { /* ignore */ }
        activeQueueWs = null;
      }
      try { if (root && root.parentNode) root.parentNode.removeChild(root); } catch (_) { /* ignore */ }
    }

    function fail(err, hint) {
      if (settled) return;
      joiningRouteShardId = 0;
      const message = hint || (err && err.message) || 'Connection failed.';
      renderError(message);
    }

    function settle(shardId) {
      if (settled) return;
      settled = true;
      _lastWsBase = selectedWsBase; // so reconnect (recordLastShard) targets the same host
      try {
        if (selectedServerName && typeof window !== 'undefined') {
          const names = window.__kintaraServerNamesByShard || {};
          names[Number(shardId) | 0] = selectedServerName;
          window.__kintaraServerNamesByShard = names;
          const regions = window.__kintaraServerRegionsByShard || {};
          regions[Number(shardId) | 0] = selectedServerRegionTag || '';
          window.__kintaraServerRegionsByShard = regions;
        }
      } catch (_) { /* ignore */ }
      const presenceUrl = wsUrl(`/ws/presence/s${shardId}`, selectedWsBase, selectedPresenceConnectToken);
      /** Adopt the region-local fanout. Every consumer (merchant WS, spectate,
       *  readFanoutFetch here) reads window.KINTARA_READ_FANOUT_ORIGIN lazily on
       *  each use, so overwriting the global switches them all — including after
       *  an in-game "Switch Server" hop to another region. Empty (legacy
       *  controller / single-region) leaves the page's injected origin alone. */
      try {
        if (selectedFanoutOrigin && typeof window !== 'undefined') {
          window.KINTARA_READ_FANOUT_ORIGIN = selectedFanoutOrigin;
        }
        if (typeof window !== 'undefined') {
          window.__kintaraSelectedFleet = selectedFleet || 'us';
          /** Persist for sessions that enter the game without this picker
           *  (direct-entry / reload edge paths): every proxied gameplay call
           *  routes lobby→controller by this fleet, and an empty value 400s
           *  with region_required. */
          try { localStorage.setItem('kintara_selected_fleet', window.__kintaraSelectedFleet); } catch (_) { /* ignore */ }
          /** DISPLAY id too — token re-mints (refreshPresenceUrlToken) happen
           *  outside this closure and must carry it, or the lobby's legacy
           *  (zone, shard) fallback resolves a us2 local 1-3 against US-01's
           *  club and bounces the reconnect (2026-07-27 deploy-restart wave). */
          window.__kintaraSelectedDisplayServerId = selectedDisplayServerId | 0;
        }
      } catch (_) { /* ignore */ }
      tearDown();
      resolve({ shardId, presenceUrl, fanoutOrigin: selectedFanoutOrigin });
    }

    function abort(reasonErr) {
      if (settled) return;
      settled = true;
      tearDown();
      reject(reasonErr || new Error('server_select_aborted'));
    }

    if (
      typeof window !== 'undefined' &&
      window.__KINTARA_E2E__ === true &&
      Number(window.__KINTARA_E2E_AUTO_SERVER_ID__) > 0
    ) {
      const shardId = Math.max(1, Number(window.__KINTARA_E2E_AUTO_SERVER_ID__) | 0);
      setBootPhase('Joining test server...', 90);
      setTimeout(() => settle(shardId), 0);
      return;
    }

    function renderError(message) {
      if (pollTimer != null) { clearInterval(pollTimer); pollTimer = null; }
      if (pingTimer != null) { clearInterval(pingTimer); pingTimer = null; }
      if (activeQueueWs) {
        try { activeQueueWs.onmessage = null; activeQueueWs.onclose = null; activeQueueWs.onerror = null; } catch (_) { /* ignore */ }
        try { activeQueueWs.close(); } catch (_) { /* ignore */ }
        activeQueueWs = null;
      }
      card.innerHTML = '';
      const sub = document.createElement('p');
      sub.className = 'kintara-server-select-sub';
      sub.textContent = '— Connection error —';
      const title = document.createElement('div');
      title.className = 'kintara-server-select-title';
      title.textContent = 'Something went wrong';
      const blurb = document.createElement('p');
      blurb.className = 'kintara-server-select-blurb';
      blurb.textContent = 'We could not reach the realm gate.';
      const errBox = document.createElement('div');
      errBox.className = 'kintara-server-select-error';
      errBox.textContent = String(message || 'Network error');
      const actions = document.createElement('div');
      actions.className = 'kintara-server-select-actions';
      const retryBtn = document.createElement('button');
      retryBtn.type = 'button';
      retryBtn.className = 'kintara-server-select-btn kintara-server-select-btn--primary';
      retryBtn.textContent = 'Retry';
      retryBtn.addEventListener('click', () => { void renderSelection(); });
      actions.appendChild(retryBtn);
      card.append(sub, title, blurb, errBox, actions);
      setBootPhase('Connection error', 92);
    }

    function renderQueue(shardId, info) {
      card.innerHTML = '';
      const sub = document.createElement('p');
      sub.className = 'kintara-server-select-sub';
      /** Use the authoritative label (e.g. "Kintara Club", "Level 20 Server",
       *  "Server 1") stashed from /api/servers — NOT the raw shard id, which is
       *  wrong because special shards are pulled out of the 1-based numbering. */
      const qNames = (typeof window !== 'undefined' && window.__kintaraServerNamesByShard) || null;
      const qName = qNames && qNames[Number(shardId) | 0];
      sub.textContent = `— ${qName ? String(qName) : `Server ${shardId}`} —`;
      const title = document.createElement('div');
      title.className = 'kintara-server-select-title';
      title.textContent = 'You are in queue';
      const body = document.createElement('div');
      body.className = 'kintara-server-select-queue';
      const aheadLabel = document.createElement('div');
      aheadLabel.className = 'kintara-server-select-queue__line2';
      const aheadCount = document.createElement('div');
      aheadCount.className = 'kintara-server-select-queue__pos';
      const followUp = document.createElement('div');
      followUp.className = 'kintara-server-select-queue__line2';
      followUp.textContent = 'Hold tight — you’ll enter automatically as soon as a slot opens.';
      queueStatusEl = followUp;
      const bar = document.createElement('div');
      bar.className = 'kintara-server-select-queue__bar';
      const fill = document.createElement('div');
      fill.className = 'kintara-server-select-queue__barFill';
      bar.appendChild(fill);
      body.append(aheadLabel, aheadCount, followUp, bar);
      const actions = document.createElement('div');
      actions.className = 'kintara-server-select-actions';
      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'kintara-server-select-btn';
      cancelBtn.textContent = 'Leave queue';
      cancelBtn.addEventListener('click', () => {
        if (activeQueueWs && activeQueueWs.readyState === WebSocket.OPEN) {
          try { activeQueueWs.send(JSON.stringify({ t: 'q_leave' })); } catch (_) { /* ignore */ }
        }
        if (activeQueueWs) {
          try { activeQueueWs.onmessage = null; activeQueueWs.onclose = null; activeQueueWs.onerror = null; } catch (_) { /* ignore */ }
          try { activeQueueWs.close(); } catch (_) { /* ignore */ }
          activeQueueWs = null;
        }
        void renderSelection();
      });
      const switchBtn = document.createElement('button');
      switchBtn.type = 'button';
      switchBtn.className = 'kintara-server-select-btn';
      switchBtn.textContent = 'Pick a different server';
      switchBtn.addEventListener('click', () => {
        if (activeQueueWs) {
          try { activeQueueWs.send(JSON.stringify({ t: 'q_leave' })); } catch (_) { /* ignore */ }
          try { activeQueueWs.onmessage = null; activeQueueWs.onclose = null; activeQueueWs.onerror = null; } catch (_) { /* ignore */ }
          try { activeQueueWs.close(); } catch (_) { /* ignore */ }
          activeQueueWs = null;
        }
        void renderSelection();
      });
      actions.append(cancelBtn, switchBtn);
      card.append(sub, title, body, actions);

      const updatePos = (pos, ahead) => {
        const a = Math.max(0, Number(ahead) || 0);
        aheadLabel.textContent = 'players ahead of you';
        aheadCount.textContent = String(a);
        const totalShown = Math.max(1, a + 1);
        const pct = Math.max(6, Math.min(100, Math.round(((totalShown - a) / totalShown) * 100)));
        fill.style.width = pct + '%';
        setBootPhase(`In queue · ${a} ahead`, 92);
      };
      if (info && typeof info.ahead === 'number') updatePos(info.pos, info.ahead);
      else updatePos(null, 0);

      return { updatePos };
    }

    /** A rejected WS *upgrade* (stale session, failed $KINS gate, ban) closes the
     *  socket before `onopen` fires, and the browser exposes neither the HTTP
     *  status nor the X-Kintara-Reason header for a failed handshake — every
     *  cause collapses to the same opaque "closed before established". When we
     *  never connected, probe /api/auth/gate-check, which re-runs the SAME entry
     *  gate the queue upgrade uses and returns the REAL verdict, so we tell the
     *  player what's actually wrong instead of guessing.
     *
     *  We must NOT assume "signed in -> must be a $KINS problem": a paying player
     *  with thousands of $KINS gets a rejected upgrade whenever the gate's Solana
     *  balance check times out under load (gate: balance_check_failed), or when
     *  the rejection was capacity / handoff / transient (gate: ok). The probe
     *  separates those so we never tell a funded player they're broke.
     *  Returns a specific message, or null if we couldn't even reach the probe
     *  (genuine network / reachability problem -> caller uses the generic text). */
    async function classifyGateConnectFailure(shardId) {
      try {
        const shardQ = Number(shardId) > 0 ? `?shard=${Number(shardId) | 0}` : '';
        const r = await fetch(`/api/auth/gate-check${shardQ}`, { credentials: 'include', cache: 'no-store' });
        let body = null;
        try { body = await r.json(); } catch (_) { /* non-JSON / empty */ }
        const gate = body && typeof body.gate === 'string' ? body.gate : '';
        if (gate === 'session' || r.status === 401) {
          return { message: 'Your session has expired. Reload the page and sign in again.', retryable: false };
        }
        if (gate === 'name_required') {
          /** Reached the gate without a display name (slipped past the boot picker
           *  on an earlier session). Bounce to /play, where the boot flow reliably
           *  shows the name picker for a nameless session (auth-gate.js) — once
           *  they pick a name they re-enter normally. */
          try { location.assign('/?play=1'); } catch (_) { location.href = '/?play=1'; }
          return { message: 'Choose a display name to enter — taking you there…', retryable: false };
        }
        if (gate === 'level_required') {
          /** This shard is level-gated (e.g. "Server 1 (Level 20+)") and the
           *  player's average skill level is below the floor. */
          const need = body && Number(body.minLevel) > 0 ? Number(body.minLevel) | 0 : 20;
          const have = body && Number.isFinite(Number(body.avgLevel)) ? Number(body.avgLevel) | 0 : null;
          return {
            message: have != null
              ? `This server needs an average skill level of ${need}+. You're level ${have} — keep training and come back, or pick another server.`
              : `This server needs an average skill level of ${need}+. Pick another server, or keep training to unlock it.`,
            retryable: false,
            stayOnPicker: true,
          };
        }
        if (gate === 'membership_required') {
          /** Members-only Kintara Club server and the player has no active
           *  membership. Refresh status + pop the subscription modal so they can
           *  buy in place rather than bounce. */
          void fetchViewerMembership().then(() => openMembershipModal(Number(shardId) | 0));
          return {
            message: 'This is the Kintara Club members-only server. Subscribe to enter.',
            retryable: false,
            /** A gate REFUSAL is a decision, not a failure: rendering the error
             *  card here tore down the server list under the subscribe modal,
             *  so closing the modal stranded non-members on a retry button that
             *  could only re-403 — the 2026-07-25 club expansion produced 25.7k
             *  membership-gate rejections from ~400 players in a day, mostly
             *  this loop. Keep the picker on screen instead. */
            stayOnPicker: true,
          };
        }
        if (gate === 'kins_required') {
          /** Genuinely under the 1,000 $KINS minimum. */
          return { message: 'You need at least 1,000 $KINS in your wallet to enter this realm. If you just topped up, wait a moment and retry.', retryable: false };
        }
        if (gate === 'balance_check_failed' || gate === 'balance_check_timeout') {
          /** We could NOT verify the balance (RPC slow/down) — the player may
           *  well hold plenty. Do NOT claim they're broke; retry automatically. */
          return { message: 'We couldn’t verify your $KINS balance just now — the network is busy. Retrying…', retryable: true };
        }
        if (gate === 'ok' || (r && r.ok)) {
          /** Gate passes: the upgrade was rejected for some other reason
           *  (server at capacity / handoff hiccup / transient). Generic retry —
           *  never a $KINS message for a player who clearly qualifies. */
          return { message: 'The realm gate is busy right now. Retrying…', retryable: true };
        }
        /** Unknown shape — fall back to the generic caller text. */
        return null;
      } catch (_) {
        return null;
      }
    }

    /** True for a mid-queue drop that is a transport-level blip rather than an
     *  intentional, terminal close. Abnormal 1xxx closures (1001 going away,
     *  1006 abnormal, 1011 server error, 1012/1013 restart/overload) and a gate
     *  that went silent after connecting (queue_no_response_timeout) are worth a
     *  silent re-join. Application-defined 4xxx closes (replaced / auth / banned /
     *  queue_error) and a clean 1000 are terminal — never auto-reconnect those. */
    function isTransientQueueDrop(errMsg) {
      if (errMsg.includes('queue_no_response_timeout')) return true;
      const m = /queue_closed:(\d+|unknown)/.exec(errMsg);
      if (!m) return false;
      if (m[1] === 'unknown') return true; // code 0 / browser hid it -> treat as transport blip
      const code = Number(m[1]);
      return code !== 1000 && code < 4000;
    }

    async function startQueueFor(shardId) {
      setBootPhase(joinPhaseLabel, 90);
      let queueCtl = null;
      /** True once the WS handshake completed (onopen). Distinguishes an
       *  upgrade-level rejection (never connected -> probe for the real reason)
       *  from a genuine mid-queue disconnect (connected then dropped). */
      let everConnected = false;
      try {
        /** Regional controllers are cross-origin, so their host cannot read the
         *  lobby's host-only session cookie. Admins skip the queue (which normally
         *  mints the presence token in `queue_ready`) but must still obtain the
         *  lobby-issued presence token before opening the regional socket. */
        if (adminBypassQueue) {
          selectedPresenceConnectToken = await fetchWsConnectToken(shardId, 'presence');
          settle(shardId);
          return;
        }
        const queueConnectToken = await fetchWsConnectToken(shardId, 'queue');
        await new Promise((res, rej) => {
          let ws;
          let done = false;
          let queueTimeout = null;
          let stableTimer = null;
          const clearQueueTimeout = () => {
            if (queueTimeout != null) {
              clearTimeout(queueTimeout);
              queueTimeout = null;
            }
          };
          const clearStableTimer = () => {
            if (stableTimer != null) {
              clearTimeout(stableTimer);
              stableTimer = null;
            }
          };
          const resolveOnce = () => {
            if (done) return;
            done = true;
            clearQueueTimeout();
            clearStableTimer();
            res();
          };
          const rejectOnce = err => {
            if (done) return;
            done = true;
            clearQueueTimeout();
            clearStableTimer();
            rej(err);
          };
          try {
            ws = new WebSocket(wsUrl(`/ws/queue/s${shardId}`, selectedWsBase, queueConnectToken));
          } catch (e) {
            rejectOnce(e);
            return;
          }
          activeQueueWs = ws;
          let connected = false;
          const onQueueTimeout = () => {
            rejectOnce(new Error(connected ? 'queue_no_response_timeout' : 'queue_connect_timeout'));
            try { ws.close(); } catch (_) { /* ignore */ }
          };
          /** Pre-connect: fixed connect deadline. After the first server message
           *  we re-arm this on EVERY message (see onmessage) as a sliding silence
           *  watchdog — so a player actively waiting in the queue (receiving
           *  queue_pos every ~5s) is never killed by a fixed deadline. Only a
           *  genuinely unresponsive gate (silent > QUEUE_STALL_TIMEOUT_MS) fails. */
          const armQueueTimeout = ms => {
            clearQueueTimeout();
            queueTimeout = setTimeout(onQueueTimeout, ms);
          };
          armQueueTimeout(QUEUE_CONNECT_TIMEOUT_MS);
          ws.onopen = () => {
            connected = true;
            everConnected = true;
            /** A fresh connection that survives a while proves the gate is healthy
             *  again — forgive earlier reconnects so a long, blip-prone queue wait
             *  isn't capped by blips that happened minutes ago. */
            if (stableTimer == null) {
              stableTimer = setTimeout(() => { queueReconnectCount = 0; }, QUEUE_RECONNECT_STABLE_MS);
            }
            if (pingTimer == null) {
              pingTimer = setInterval(() => {
                if (ws.readyState !== WebSocket.OPEN) return;
                try { ws.send(JSON.stringify({ t: 'q_ping' })); } catch (_) { /* ignore */ }
              }, QUEUE_PING_MS);
            }
          };
          ws.onmessage = ev => {
            let msg;
            try { msg = JSON.parse(typeof ev.data === 'string' ? ev.data : String(ev.data)); }
            catch (_) { return; }
            if (!msg || typeof msg !== 'object') return;
            /** Any valid server message proves the gate is alive — slide the
             *  silence watchdog forward. Queued players receive queue_pos every
             *  ~5s, so this keeps them connected indefinitely while waiting. */
            armQueueTimeout(QUEUE_STALL_TIMEOUT_MS);
            if (msg.t === 'queue_ready') {
              if (msg.connectToken) selectedPresenceConnectToken = String(msg.connectToken || '');
              resolveOnce();
              settle(shardId);
              return;
            }
            if (msg.t === 'queue_pos') {
              if (!queueCtl) queueCtl = renderQueue(shardId, { pos: msg.pos, ahead: msg.ahead });
              else queueCtl.updatePos(msg.pos, msg.ahead);
              return;
            }
            if (msg.t === 'queue_error') {
              rejectOnce(new Error(`queue_error:${msg.reason || 'unknown'}`));
            }
            if (msg.t === 'queue_evicted') {
              rejectOnce(new Error(`queue_evicted:${msg.reason || 'unknown'}`));
            }
          };
          ws.onerror = () => {
            if (!connected) rejectOnce(new Error('queue_ws_failed'));
          };
          ws.onclose = ev => {
            if (pingTimer != null) { clearInterval(pingTimer); pingTimer = null; }
            if (done) return;
            if (settled) return;
            const code = ev && typeof ev.code === 'number' ? ev.code : 0;
            if (code === 1000) {
              rejectOnce(new Error('queue_closed_before_ready'));
              return;
            }
            if (code === 4000) {
              rejectOnce(new Error('queue_replaced'));
              return;
            }
            if (code === 4001) {
              rejectOnce(new Error('queue_auth'));
              return;
            }
            rejectOnce(new Error(`queue_closed:${code || 'unknown'}`));
          };
        });
      } catch (e) {
        if (settled) return;
        const msg = (e && e.message) || 'queue_error';
        if (msg.includes('queue_auth')) { fail(e, 'You are not signed in. Reload the page and sign in again.'); return; }
        if (msg.includes('queue_evicted:idle')) { fail(e, 'Your queue spot timed out. Please try again.'); return; }
        if (msg.includes('queue_evicted:replaced')) { fail(e, 'You joined the queue from another tab.'); return; }
        /** Handshake never completed: the upgrade was rejected (stale session /
         *  $KINS gate / ban) or the gate was unreachable. The browser hides the
         *  reason, so probe to recover it. If we DID connect and then dropped,
         *  it's a genuine mid-queue disconnect — keep the connection-lost text. */
        if (!everConnected) {
          const refined = await classifyGateConnectFailure(shardId);
          if (settled) return;
          if (refined) {
            /** Transient gate failure (RPC balance check busy): auto-retry the SAME
             *  shard, but at most once per 5s and only a few times, so the client
             *  never hammers a throttled backend. Then fall back to manual retry. */
            if (refined.retryable && gateAutoRetryCount < GATE_AUTO_RETRY_MAX && Date.now() >= gateAutoRetryAt) {
              gateAutoRetryCount += 1;
              gateAutoRetryAt = Date.now() + GATE_AUTO_RETRY_MS;
              setBootPhase('Network busy — retrying…', 92);
              setTimeout(() => { if (!settled) void startQueueFor(shardId); }, GATE_AUTO_RETRY_MS);
              return;
            }
            /** Gate refusal (club membership / level floor): leave the server
             *  list exactly where it is — the join failed before any queue card
             *  rendered, so the picker is still on screen behind whatever modal
             *  classify opened. Just release the joining highlight so the
             *  player can immediately pick another server. */
            if (refined.stayOnPicker) {
              joiningRouteShardId = 0;
              try { if (typeof refreshSelectionRef === 'function') void refreshSelectionRef(); } catch (_) { /* keep the stale paint */ }
              setBootPhase('Select a server', 80);
              return;
            }
            fail(e, refined.message);
            return;
          }
        }
        /** We had connected and then the transport dropped (or the gate went
         *  silent). Most of these are transient — a coordinator event-loop spike,
         *  a brief gateway blip, a worker rebalance or a rolling deploy. Re-join
         *  the SAME queue automatically rather than bouncing the player to the
         *  error screen. Bounded by QUEUE_RECONNECT_MAX; a healthy reconnect
         *  forgives the count (see onopen). */
        if (everConnected && isTransientQueueDrop(msg) && queueReconnectCount < QUEUE_RECONNECT_MAX) {
          queueReconnectCount += 1;
          if (queueStatusEl) queueStatusEl.textContent = 'Connection hiccup — reconnecting…';
          setBootPhase('Reconnecting to the queue…', 92);
          setTimeout(() => { if (!settled) void startQueueFor(shardId); }, QUEUE_RECONNECT_DELAY_MS);
          return;
        }
        if (msg.includes('queue_replaced')) { fail(e, 'You joined the queue from another tab. Reload this page if you want to queue here instead.'); return; }
        if (msg.includes('wallet_banned') || msg.includes('ip_banned') || msg.includes('queue_closed:4009')) { fail(e, 'Your account is not permitted to enter right now.'); return; }
        if (msg.includes('queue_connect_timeout') || msg.includes('queue_no_response_timeout')) fail(e, 'The realm gate did not answer in time. Please retry.');
        else fail(e, 'We lost the connection to the realm gate while you were queued.');
      }
    }

    /* ── Kintara Club subscription modal ──────────────────────────────────
     * Shown when a non-member picks the members-only server. Lists the tiers,
     * runs the native SOL payment, confirms it server-side, then joins the queue
     * for `shardId`. Reuses the same wallet provider plumbing as the marketplace
     * token-buy flow. */
    let membershipModalOpen = false;
    async function openMembershipModal(shardId) {
      if (membershipModalOpen) return;
      membershipModalOpen = true;
      if (pollTimer != null) { clearInterval(pollTimer); pollTimer = null; }
      if (!clubTiers || !clubTiers.length) await fetchViewerMembership();
      /** Club sold out (env, default on): non-members see every payment tier as
       *  SOLD OUT and can't purchase. Active members are unaffected (can renew). */
      const tiersSoldOut = clubSoldOut && !memberIsActive();

      const layer = document.createElement('div');
      layer.className = 'kintara-club-overlay';
      const box = document.createElement('div');
      box.className = 'kintara-club-modal';
      const eyebrow = document.createElement('p');
      eyebrow.className = 'kintara-club-modal__eyebrow';
      eyebrow.textContent = '— Members Only —';
      const h = document.createElement('h2');
      h.className = 'kintara-club-modal__title';
      h.textContent = 'Kintara Club';
      const blurb = document.createElement('p');
      blurb.className = 'kintara-club-modal__blurb';
      blurb.textContent = memberIsActive()
        ? 'Extend your membership to keep your place on the exclusive Kintara Club realm.'
        : tiersSoldOut
          ? 'Kintara Club memberships are sold out right now. Check back soon for new spots.'
          : 'An exclusive members-only realm. Choose a plan to unlock access — paid in SOL.';
      box.append(eyebrow, h, blurb);

      const status = document.createElement('p');
      status.className = 'kintara-club-status';

      const tierWrap = document.createElement('div');
      tierWrap.className = 'kintara-club-tiers';

      let busy = false;
      const setStatus = (t, err) => { status.textContent = t || ''; status.classList.toggle('kintara-club-status--err', !!err); };
      const setBusy = (b) => {
        busy = b;
        for (const el of tierWrap.querySelectorAll('button')) el.disabled = b;
        closeBtn.disabled = b;
      };

      async function purchase(tier, label, usd) {
        if (busy) return;
        const sessPk = getSessionWalletPubkey();
        /** Reconnect INSIDE this click gesture, not just read the provider:
         *  Wallet Standard wallets (MetaMask) carry no account until a connect
         *  succeeds, and the page-load silent reconnect is one-shot — without
         *  this, their buyers dead-end on "Unlock your Solana wallet" with the
         *  wallet demonstrably unlocked. Same plumbing as the marketplace flow. */
        try {
          setBusy(true);
          setStatus('Waiting for your wallet…');
          /** Inlined (NOT an auth-gate import): browsers can hold a stale-cached
           *  auth-gate.js, and importing a just-added export from it hard-fails
           *  this whole module with a SyntaxError (broke server select on
           *  2026-07-17). Only long-standing auth-gate exports may be imported
           *  here. Silent connect first (no popup for trusted wallets), then
           *  interactive — legal inside this click gesture.
           *  A connect that never settles (an abandoned QR pairing) must not
           *  wedge the modal — busy disables every button, including "Back to
           *  servers". On timeout fall through to the unlock message; a late
           *  resolve is harmless (the next click takes the connected fast path). */
          const connectWallet = async () => {
            const p = getWalletProvider();
            if (!p || p.publicKey || typeof p.connect !== 'function') return p;
            try { await p.connect({ onlyIfTrusted: true }); } catch (_) { /* not trusted yet */ }
            if (!p.publicKey) {
              try { await p.connect(); } catch (_) { /* declined — unlock message below */ }
            }
            return p;
          };
          const wal = await Promise.race([
            connectWallet(),
            new Promise(res => setTimeout(res, 45_000, null)),
          ]);
          if (!wal || !wal.publicKey) {
            setStatus('Unlock your Solana wallet to continue.', true);
            setBusy(false);
            return;
          }
          setStatus('Fetching price quote…');
          const qr = await fetch('/api/club/quote', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tier }),
          });
          const jd = await qr.json().catch(() => ({}));
          if (!qr.ok || !jd.ok || !jd.quote) {
            setStatus(jd.error === 'price_unavailable' ? 'Could not fetch the SOL price — try again shortly.' : (jd.error || 'Could not prepare the purchase.'), true);
            setBusy(false);
            return;
          }
          setStatus(`Sign the payment for ${label} ($${usd}) in your wallet…`);
          const pay = await executeClubMembershipPayment(wal, jd.quote, sessPk);
          let sig = pay.ok ? pay.signature : '';
          if (!pay.ok) {
            if (pay.error === 'confirm_timeout' && pay.signature) {
              sig = pay.signature;
              setStatus('Wallet confirmation is slow — verifying your payment with the server…');
            } else {
              if (pay.error === 'wallet_mismatch') setStatus('That wallet does not match your signed-in account.', true);
              else if (pay.error === 'insufficient_sol') {
                const have = pay.haveLamports != null ? (Number(pay.haveLamports) / 1e9).toFixed(6) : '?';
                const need = pay.needLamports != null ? (Number(pay.needLamports) / 1e9).toFixed(6) : '?';
                setStatus(`Not enough SOL — wallet shows ${have} SOL, need ~${need} SOL (plus fee).`, true);
              }
              else if (pay.error === 'rejected') setStatus('Payment cancelled.', true);
              else setStatus(pay.detail ? `Payment failed: ${pay.detail}` : 'Payment failed.', true);
              setBusy(false);
              return;
            }
          }
          setStatus('Confirming your membership…');
          const cr = await fetch('/api/club/confirm', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ quoteId: jd.quote.quoteId, signature: sig }),
          });
          const cd = await cr.json().catch(() => ({}));
          if (!cr.ok || !cd.ok) {
            setStatus(cd.error === 'signature_reused' || cd.error === 'signature_used_other_flow'
              ? 'That payment was already used.'
              : `Could not confirm membership${cd.error ? ` (${cd.error})` : ''}. Your payment is safe — contact support if this persists.`, true);
            setBusy(false);
            return;
          }
          viewerMembership = cd.membership || { active: true, expiresAtMs: 0, tier };
          setStatus('Welcome to the Kintara Club! Entering…');
          setTimeout(() => {
            close();
            void startQueueFor(shardId);
          }, 700);
        } catch (e) {
          setStatus(`Something went wrong: ${(e && e.message) || 'unknown error'}`, true);
          setBusy(false);
        }
      }

      /** Per-month baseline = the shortest plan's monthly rate, so multi-month
       *  tiers can advertise their discount. Tiers are server-authoritative. */
      const monthlyRates = clubTiers
        .map((t) => (Number(t.months) > 0 ? (Number(t.usd) || 0) / Number(t.months) : Infinity))
        .filter((r) => Number.isFinite(r));
      const baseMonthly = monthlyRates.length ? Math.max(...monthlyRates) : 0;
      let bestIdx = -1;
      let bestSave = 0;
      clubTiers.forEach((t, i) => {
        const months = Number(t.months) || 0;
        if (months <= 1 || !baseMonthly) return;
        const save = 1 - (Number(t.usd) || 0) / (baseMonthly * months);
        if (save > bestSave) { bestSave = save; bestIdx = i; }
      });

      clubTiers.forEach((t, i) => {
        const usd = (Number(t.usd) || 0).toFixed(2);
        const months = Number(t.months) || 0;
        const label = t.label || `${months} Month${months === 1 ? '' : 's'}`;
        const perMonth = months > 0 ? (Number(t.usd) || 0) / months : 0;
        const save = months > 1 && baseMonthly ? Math.round((1 - perMonth / baseMonthly) * 100) : 0;

        const b = document.createElement('button');
        b.type = 'button';
        b.className =
          'kintara-club-tier' +
          (i === bestIdx && !tiersSoldOut ? ' kintara-club-tier--best' : '') +
          (tiersSoldOut ? ' kintara-club-tier--soldout' : '');
        if (tiersSoldOut) b.disabled = true;

        const left = document.createElement('div');
        left.className = 'kintara-club-tier__left';
        const name = document.createElement('div');
        name.className = 'kintara-club-tier__name';
        name.textContent = label;
        if (i === bestIdx) {
          const badge = document.createElement('span');
          badge.className = 'kintara-club-tier__badge';
          badge.textContent = 'Best Value';
          name.appendChild(badge);
        }
        const sub = document.createElement('div');
        sub.className = 'kintara-club-tier__sub';
        sub.textContent = months > 1
          ? `$${perMonth.toFixed(2)}/mo${save > 0 ? ` · Save ${save}%` : ''}`
          : 'Billed monthly';
        left.append(name, sub);

        const right = document.createElement('div');
        right.className = 'kintara-club-tier__right';
        const price = document.createElement('div');
        price.className = 'kintara-club-tier__price';
        price.textContent = tiersSoldOut ? 'SOLD OUT' : `$${usd}`;
        const cur = document.createElement('div');
        cur.className = 'kintara-club-tier__cur';
        cur.textContent = tiersSoldOut ? 'unavailable' : 'paid in SOL';
        right.append(price, cur);

        b.append(left, right);
        if (!tiersSoldOut) b.addEventListener('click', () => void purchase(t.id, label, usd));
        tierWrap.appendChild(b);
      });

      const foot = document.createElement('p');
      foot.className = 'kintara-club-foot';
      foot.textContent = 'Secured on Solana · Renewals stack onto your remaining time';

      const closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.textContent = 'Back to servers';
      closeBtn.className = 'kintara-server-select-btn';
      closeBtn.style.marginTop = '14px';
      function close() {
        membershipModalOpen = false;
        try { if (layer.parentNode) layer.parentNode.removeChild(layer); } catch (_) { /* ignore */ }
        /** Repaint (so the Club card flips to "join instantly" if they subscribed)
         *  and resume the live population poll we paused on open. */
        if (!settled && typeof refreshSelectionRef === 'function') {
          void refreshSelectionRef();
          if (pollTimer == null) pollTimer = setInterval(refreshSelectionRef, SERVERS_POLL_MS);
        }
      }
      closeBtn.addEventListener('click', () => { if (!busy) close(); });

      box.append(tierWrap, status, foot, closeBtn);
      layer.appendChild(box);
      root.appendChild(layer);
    }

    async function renderSelection() {
      card.innerHTML = '';
      const sub = document.createElement('p');
      sub.className = 'kintara-server-select-sub';
      sub.textContent = '— Server Zone —';
      const title = document.createElement('div');
      title.className = 'kintara-server-select-title';
      title.textContent = allowCancel ? 'Switch Server' : 'Select a Server';
      const blurb = document.createElement('p');
      blurb.className = 'kintara-server-select-blurb';
      blurb.textContent = allowCancel
        ? 'Hop to another world without reloading. Your character, items and progress come with you.'
        : 'Choose the closest zone, then pick a realm. Friends should enter the same one.';
      const tabs = document.createElement('div');
      tabs.className = 'kintara-server-zone-tabs';
      const list = document.createElement('div');
      list.className = 'kintara-server-select-list';
      /** Show loading spinner (same signal-bar style as the boot overlay)
       *  while fetching regions from controllers. */
      const loader = document.createElement('div');
      loader.className = 'kintara-server-select-loader';
      loader.innerHTML = '<div class="kintara-server-select-loader__bars"><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div><div class="kintara-server-select-loader__label">Loading realms\u2026</div>';
      list.appendChild(loader);
      card.append(sub, title, blurb, tabs, list);
      /** In-game switch only: a "Back to game" control so cancelling resumes the
       *  current world instead of stranding the player on the picker. */
      if (allowCancel) {
        const cancelRow = document.createElement('div');
        cancelRow.className = 'kintara-server-select-actions';
        const backBtn = document.createElement('button');
        backBtn.type = 'button';
        backBtn.className = 'kintara-server-select-btn';
        backBtn.textContent = 'Back to game';
        backBtn.addEventListener('click', () => abort(new Error('server_select_cancelled')));
        cancelRow.appendChild(backBtn);
        card.appendChild(cancelRow);
      }
      setBootConnectingMode('Choose a server…');
      setBootPhase('Choose a server…', 85);

      function paintServers(servers) {
        if (!servers || !servers.length) {
          tabs.innerHTML = '';
          for (const zone of BASE_ZONES) {
          const tab = document.createElement('button');
          tab.type = 'button';
          tab.className = 'kintara-server-zone-tab';
          tab.setAttribute('aria-selected', String(zone.id === selectedZone));
          const copy = document.createElement('span');
          copy.className = 'kintara-server-zone-tab__copy';
          const label = document.createElement('span');
          label.className = 'kintara-server-zone-tab__label';
          label.textContent = zone.label;
          const subText = document.createElement('span');
          subText.className = 'kintara-server-zone-tab__sub';
          subText.textContent = zone.sub || 'Server Region';
          copy.append(label, subText);
          const count = document.createElement('span');
          count.className = 'kintara-server-zone-tab__count';
          count.dataset.empty = 'true';
          count.textContent = 'Soon';
          tab.append(copy, count);
            tab.addEventListener('click', () => {
              selectedZone = zone.id;
              paintServers(servers);
            });
            tabs.appendChild(tab);
          }
          list.innerHTML = '';
          const msg = document.createElement('div');
          msg.className = 'kintara-server-select-error';
          msg.textContent = 'No servers are currently reachable. Retrying…';
          list.appendChild(msg);
          return;
        }
        const allServers = Array.isArray(servers) ? servers : [];
        const zones = zonesForServers(allServers);
        /** Ghost tabs are gone, so the remembered zone may no longer exist in
         *  this environment — snap to the first real zone instead of rendering
         *  an unselectable empty list. */
        if (zones.length && !zones.some(z => z.id === selectedZone)) selectedZone = zones[0].id;
        tabs.innerHTML = '';
        for (const zone of zones) {
          const zoneServers = allServers.filter(s => normalizeZoneId(s && (s.zone || s.region)) === zone.id);
          const tab = document.createElement('button');
          tab.type = 'button';
          tab.className = 'kintara-server-zone-tab';
          tab.setAttribute('aria-selected', String(zone.id === selectedZone));
          const copy = document.createElement('span');
          copy.className = 'kintara-server-zone-tab__copy';
          const label = document.createElement('span');
          label.className = 'kintara-server-zone-tab__label';
          label.textContent = zone.label;
          const subText = document.createElement('span');
          subText.className = 'kintara-server-zone-tab__sub';
          subText.textContent = zone.sub || 'Server Region';
          copy.append(label, subText);
          const count = document.createElement('span');
          count.className = 'kintara-server-zone-tab__count';
          count.dataset.empty = String(zoneServers.length === 0);
          count.textContent = zoneServers.length > 0
            ? `${zoneServers.length} Server${zoneServers.length === 1 ? '' : 's'}`
            : 'Soon';
          tab.append(copy, count);
          tab.addEventListener('click', () => {
            selectedZone = zone.id;
            paintServers(allServers);
          });
          tabs.appendChild(tab);
        }
        const visibleServers = allServers.filter(s => normalizeZoneId(s && (s.zone || s.region)) === selectedZone);
        list.innerHTML = '';
        if (!visibleServers.length) {
          const msg = document.createElement('div');
          msg.className = 'kintara-server-zone-empty';
          msg.textContent = `${zoneLabelFor(selectedZone, allServers)} zone is not online yet.`;
          list.appendChild(msg);
          return;
        }
        for (const s of visibleServers) {
          const routeShardId = Math.max(1, Number(s.routeShardId || s.localShardId || s.id) | 0 || 1);
          const isJoining = joiningRouteShardId === routeShardId;
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = `kintara-server-card${isJoining ? ' kintara-server-card--joining' : ''}`;
          /** In-game switch: the shard the player is already on isn't a useful
           *  pick — mark it and disable so a switch can't no-op into the same
           *  world (and drop them through a needless disconnect/reconnect). */
          const serverZone = normalizeZoneId(s && (s.zone || s.region));
          /** Route ids are BOX-local and restart on each box while a zone can
           *  span boxes (NA = 2 US boxes: display 12-21 are routes 1-10 over
           *  again) — so (route, zone) alone also flags the current server's
           *  cross-box twin "you are here" and disables it (ticket #3886,
           *  Club 1 ↔ Server 12). Require the globally-unique display id to
           *  match whenever we know it. */
          const isCurrent =
            currentShardId > 0 &&
            routeShardId === currentShardId &&
            serverZone === currentZone &&
            (currentDisplayServerId <= 0 || (Number(s.id) | 0) === currentDisplayServerId);
          if (isCurrent) btn.disabled = true;
          const isUnavailable = !!s.unavailable;
          if (isUnavailable) btn.disabled = true;
          const isFull = !adminBypassQueue && !!s.full && !isUnavailable;
          if (isFull && s.queueLength > 80) btn.disabled = true;
          if (joiningRouteShardId > 0 && !isJoining) btn.disabled = true;
          /** Level-gated special server the viewer can't enter yet → grey it out
           *  (the WS upgrade still enforces it server-side; this is just so they
           *  don't click into a bounce). Only when we actually know their level. */
          const needLvl = Number(s.minLevel) > 0 ? Number(s.minLevel) | 0 : 0;
          const levelLocked =
            !adminBypassQueue && needLvl > 0 && viewerAvgLevel != null && viewerAvgLevel < needLvl;
          if (levelLocked) btn.disabled = true;
          /** Members-only Kintara Club server. We never DISABLE it: a non-member
           *  click opens the subscription modal. "Locked" here only means "needs to
           *  subscribe first" (known false membership; unknown → let server decide). */
          const membersOnly = !adminBypassQueue && !!s.requiresMembership;
          const memberLocked =
            membersOnly && viewerMembership != null && !viewerMembership.active;
          const left = document.createElement('div');
          const name = document.createElement('div');
          name.className = 'kintara-server-card__name';
          name.textContent = s.name || `Server ${s.id}`;
          const hint = document.createElement('div');
          hint.className = 'kintara-server-card__hint';
          if (isJoining) {
            hint.textContent = 'Opening realm gate…';
          } else if (isUnavailable) {
            hint.textContent = 'Region starting up — check back shortly';
          } else if (isCurrent) {
            hint.textContent = '✓ Current server — you are here';
          } else if (levelLocked) {
            hint.textContent = `🔒 Requires Level ${needLvl} — you're Level ${viewerAvgLevel}`;
          } else if (membersOnly && !adminBypassQueue) {
            hint.textContent = memberLocked
              ? '🔒 Members only · tap to subscribe'
              : (viewerMembership && viewerMembership.active ? 'Kintara Club · join instantly' : 'Members only · Kintara Club');
          } else if (adminBypassQueue) {
            hint.textContent = s.full
              ? 'Admin · join anytime (over capacity ok)'
              : 'Admin · join instantly';
          } else if (needLvl > 0) {
            hint.textContent = isFull
              ? (s.queueLength > 0 ? `Level ${needLvl}+ · Full · ${s.queueLength} in queue` : `Level ${needLvl}+ · Full`)
              : `Level ${needLvl}+ · join instantly`;
          } else {
            hint.textContent = isFull
              ? (s.queueLength > 0 ? `Full · ${s.queueLength} in queue` : 'Full · queue opens')
              : 'Open · join instantly';
          }
          left.append(name, hint);
          /** Live Venomweaver (Glade Cave) occupancy for this shard — how many
           *  players are actively INSIDE the cave fighting the boss (max = the
           *  cave capacity, e.g. 4), reported by the shard's presence hub. Shown
           *  on every card so players can pick a server with an open cave slot. */
          const bossQ = document.createElement('div');
          bossQ.className = 'kintara-server-card__bossq';
          const bossCap = Math.max(1, Number(s.bossCaveCapacity) || 4);
          const bossActive = Math.max(0, Math.min(bossCap, Number(s.bossCaveActive) || 0));
          bossQ.textContent = `Venomweaver Cave: ${bossActive}/${bossCap}`;
          left.append(bossQ);
          const pop = document.createElement('span');
          pop.className = 'kintara-server-card__pop';
          const bucket = isJoining
            ? 'Joining'
            : (isUnavailable ? 'Soon' : (adminBypassQueue ? (s.populationLabel || 'Low') : (isFull ? 'Full' : (s.populationLabel || 'Low'))));
          pop.dataset.bucket = bucket;
          pop.textContent = bucket;
          btn.append(left, pop);
          btn.addEventListener('click', () => {
            if (btn.disabled) return;
            /** Non-member clicking the Club server → open the subscription modal
             *  instead of bouncing off the gate. Admins + active members fall
             *  through to the normal queue join. */
            if (membersOnly && !adminBypassQueue && !memberIsActive()) {
              void openMembershipModal(s.id);
              return;
            }
            if (pollTimer != null) { clearInterval(pollTimer); pollTimer = null; }
            selectedWsBase = String(s.wsBaseUrl || ''); // host-aware: connect to this server's own host
            selectedFanoutOrigin = String(s.fanoutOrigin || '');
            selectedFleet = normalizeZoneId(s.zone || s.region);
            selectedServerName = String(s.name || `Server ${s.id}`);
            selectedServerRegionTag = serverRegionAcronym(s);
            selectedDisplayServerId = Number(s.id) | 0;
            joiningRouteShardId = routeShardId;
            paintServers(allServers);
            try {
              if (typeof window !== 'undefined') {
                const names = window.__kintaraServerNamesByShard || {};
                names[routeShardId] = selectedServerName;
                window.__kintaraServerNamesByShard = names;
                const regions = window.__kintaraServerRegionsByShard || {};
                regions[routeShardId] = selectedServerRegionTag || '';
                window.__kintaraServerRegionsByShard = regions;
              }
            } catch (_) { /* ignore */ }
            void startQueueFor(routeShardId);
          });
          list.appendChild(btn);
        }
      }

      async function refresh() {
        try {
          const payload = await fetchServers();
          adminBypassQueue = payload.adminBypass === true;
          paintServers(payload.servers);
        } catch (e) {
          if (!list.children.length) paintServers(null);
        }
      }
      refreshSelectionRef = refresh;
      /** These three lobby reads are independent, but they ran as SERIAL
       *  awaits — one full lobby round-trip each (~250ms per leg from Asia,
       *  ~80ms from EU) on every boot AND every in-game server switch, so the
       *  picker sat blank for up to ~750ms before its first paint. Fetch all
       *  three concurrently and paint once, with the gate values (level /
       *  membership) guaranteed resolved before the first paint exactly as
       *  before. The periodic poll keeps using refresh() unchanged. */
      const [, , serversPayload] = await Promise.all([
        fetchViewerLevel(),
        fetchViewerMembership(),
        fetchServers().catch(() => null),
      ]);
      if (serversPayload) {
        adminBypassQueue = serversPayload.adminBypass === true;
        paintServers(serversPayload.servers);
      } else if (!list.children.length) {
        paintServers(null);
      }
      if (pollTimer != null) { clearInterval(pollTimer); pollTimer = null; }
      pollTimer = setInterval(refresh, SERVERS_POLL_MS);
    }

    /** Stalk / follow-a-friend: skip the picker entirely and queue straight into
     *  the friend's shard. Reuses the full gate + queue machinery (startQueueFor
     *  handles full shards via the queue, and level / membership / $KINS gates
     *  via classifyGateConnectFailure after a rejected upgrade). Falls back to the
     *  normal picker if the target shard can't be resolved from /api/servers. */
    async function autoJoinTargetShard(targetShardId) {
      const fallbackLabel = `Server ${targetShardId}`;
      setBootConnectingMode(`Entering ${fallbackLabel}…`);
      setBootPhase(`Entering ${fallbackLabel}…`, 88);
      try {
        await fetchViewerLevel();
        await fetchViewerMembership();
        const payload = await fetchServers();
        adminBypassQueue = payload.adminBypass === true;
        const entry = (payload.servers || []).find(s => (Number(s.id) | 0) === targetShardId);
        if (!entry) {
          /** Shard not advertised (offline / spun down) — let the player choose. */
          void renderSelection();
          return;
        }
        const label = String(entry.name || fallbackLabel);
        joinPhaseLabel = `Entering ${label}…`;
        setBootPhase(joinPhaseLabel, 90);
        selectedWsBase = String(entry.wsBaseUrl || ''); // host-aware: friend's own host
        selectedFanoutOrigin = String(entry.fanoutOrigin || '');
        selectedFleet = normalizeZoneId(entry.zone || entry.region);
        /** Record the DISPLAY name + region tag like the picker click does —
         *  settle() stashes them under the settled (route) shard id for the
         *  top-left HUD. Without this the auto-join (stalk/friend hop) left
         *  the name map empty and the HUD fell back to a display-id-keyed
         *  /api/servers map, labelling us2's local s4 as US-01's "Server 4"
         *  (Admin stalking Cook, 2026-07-27). */
        selectedServerName = String(entry.name || fallbackLabel);
        selectedServerRegionTag = serverRegionAcronym(entry);
        selectedDisplayServerId = Number(entry.id) | 0;
        /** ROUTE id, not the display id (2026-07-27, admin stalk to "Server
         *  15"): the display number is fleet-global but each box's shards are
         *  numbered locally — us2's "Server 15" is its local s4. The picker's
         *  own cards already join by routeShardId; passing `targetShardId`
         *  here minted tokens for a shard the target box doesn't have
         *  (`wss://us2/ws/presence/s15` → connect failed forever, chat poll
         *  503s, and the bad URL was cached so the client looped on it). */
        const routeShardId = Math.max(1, Number(entry.routeShardId || entry.localShardId || entry.id) | 0 || 1);
        void startQueueFor(routeShardId);
      } catch (_) {
        void renderSelection();
      }
    }

    if (autoJoinShardId > 0) {
      void autoJoinTargetShard(autoJoinShardId);
    } else {
      void renderSelection();
    }

    /** Surface a public abort handle so the game can cancel selection if e.g.
     *  the user navigates away or the auth-gate suddenly loses the session. */
    if (typeof window !== 'undefined') {
      window.__kintaraServerSelectAbort = () => abort(new Error('server_select_aborted'));
    }
  });
}

/**
 * Helper for the game-side reconnect path. Once a player has already entered
 * a shard and is then briefly disconnected (Wi-Fi blip, laptop lid), we
 * should reconnect to the SAME shard without re-showing the selection
 * screen. This helper exposes the cached presence URL for the shard that
 * was last successfully entered.
 */
let _lastShardId = null;
let _lastPresenceUrl = null;
let _lastWsBase = ''; // host of the last-entered server, so reconnect targets the same machine
export function shardIdFromPresenceUrl(url) {
  const s = String(url || '');
  const m = s.match(/\/ws\/presence\/s(\d+)/i);
  if (m) return Math.max(1, Number(m[1]) | 0 || 1);
  if (/\/ws\/presence(?:\/|\?|$)/i.test(s)) return 1;
  return null;
}
export function recordLastShard(shardId, presenceUrl = '') {
  const sid = Math.max(1, Number(shardId) | 0 || 0);
  if (!sid) return;
  _lastShardId = sid;
  _lastPresenceUrl = String(presenceUrl || '').trim() || wsUrl(`/ws/presence/s${sid}`, _lastWsBase);
}
export function getLastShardId() { return _lastShardId; }
export function getLastPresenceUrl() { return _lastPresenceUrl; }
export function clearLastShardCache() {
  _lastShardId = null;
  _lastPresenceUrl = null;
}

/** ── Reconnect token freshness (2026-07-26) ────────────────────────────────
 *  The cached presence URL carries the lobby-minted `kt` connect token in its
 *  query string, and that token lives ~10 minutes. Every reconnect replayed the
 *  cached URL verbatim, so ANY gap longer than the TTL — laptop sleep, a
 *  backgrounded mobile tab, the Back-Forward Cache, wifi out — meant each retry
 *  presented an EXPIRED token, was rejected `invalid_session`, and after the
 *  12-attempt ceiling the client went permanently silent with no way back but a
 *  manual reload. (Found on Admin's account: token minted 09:15Z, expired
 *  09:25Z, page bfcached, 12 dead retries, then nothing.) */

/** Expiry (ms epoch) of the `kt` token on a presence URL, or null when the URL
 *  carries no token (same-origin connect — the cookie authenticates instead). */
export function presenceUrlTokenExpiryMs(presenceUrl) {
  try {
    const raw = String(presenceUrl || '');
    const m = raw.match(/[?&]kt=([^&]+)/);
    if (!m) return null;
    const tok = decodeURIComponent(m[1]);
    const dot = tok.lastIndexOf('.');
    const b64 = dot > 0 ? tok.slice(0, dot) : tok;
    const json = atob(b64.replace(/-/g, '+').replace(/_/g, '/'));
    const exp = Number(JSON.parse(json).exp);
    return Number.isFinite(exp) ? exp : null;
  } catch (_) {
    return null; // unparseable → treat as "can't tell", caller reuses as before
  }
}

/** True when the cached URL's token is spent (or about to be). The skew covers
 *  the round trip plus clock drift, so we refresh just BEFORE it bites. */
export function presenceUrlTokenStale(presenceUrl, skewMs = 30000) {
  const exp = presenceUrlTokenExpiryMs(presenceUrl);
  if (exp == null) return false;
  return Date.now() + Math.max(0, skewMs) >= exp;
}

/** Re-mint the `kt` token on a cached presence URL, keeping the player on the
 *  SAME shard/host (no server picker, no realm change). Throws if the lobby
 *  won't issue one — the caller then falls back to the full selection flow. */
export async function refreshPresenceUrlToken(presenceUrl) {
  const raw = String(presenceUrl || '');
  if (!/[?&]kt=/.test(raw)) return raw; // nothing to refresh
  const shardId = shardIdFromPresenceUrl(raw) || _lastShardId || 1;
  const q = new URLSearchParams({ shard: String(shardId), purpose: 'presence' });
  /** Bind to the same fleet the player picked, exactly as the initial mint does
   *  — a zoneless token can be rejected by a gated fleet's shard of the same id. */
  try {
    const fleet = typeof window !== 'undefined' ? String(window.__kintaraSelectedFleet || '') : '';
    if (fleet) q.set('zone', fleet);
  } catch (_) { /* no window (tests) — zoneless mint is still valid */ }
  /** The DISPLAY id disambiguates same-numbered locals across boxes: without it
   *  the lobby's (zone, shard) fallback maps a us2 local 1-3 to US-01's club
   *  and this refresh dies on membership_required, dropping the player to the
   *  picker on every deploy-restart / sleep-gap reconnect (2026-07-27). */
  try {
    const disp = typeof window !== 'undefined' ? (Number(window.__kintaraSelectedDisplayServerId) | 0) : 0;
    if (disp > 0) q.set('display', String(disp));
  } catch (_) { /* no window (tests) — legacy mint still works off-club */ }
  const r = await fetch(`/api/lobby/connect-token?${q.toString()}`, {
    credentials: 'include',
    cache: 'no-store',
  });
  const j = await r.json().catch(() => null);
  if (!r.ok || !j || j.ok !== true || !j.token) {
    throw new Error((j && j.error) ? String(j.error) : 'connect_token_refresh_failed');
  }
  return raw.replace(/([?&]kt=)[^&]*/, `$1${encodeURIComponent(String(j.token))}`);
}
