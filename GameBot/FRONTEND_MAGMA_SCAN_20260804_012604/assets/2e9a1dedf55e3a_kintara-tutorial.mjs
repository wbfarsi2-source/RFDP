/**
 * New-player tutorial: top-center HUD (under player count), persisted via `/api/auth/tutorial-progress`.
 * NPC highlights use the game's existing HUD "?" overlays (tinted red), not an extra scene marker.
 */

export const TUTORIAL_LAST_STEP_INDEX = 28;
const LAST_STEP_INDEX = TUTORIAL_LAST_STEP_INDEX;

const STEP_CONTINUES_ONLY = [];
for (let i = 0; i <= LAST_STEP_INDEX; i++) STEP_CONTINUES_ONLY[i] = false;
STEP_CONTINUES_ONLY[13] = true; // OBSOLETE (dead-merchant scene 2026-07): auto-skipped in game.js; Continue is the fallback for stale clients.
STEP_CONTINUES_ONLY[20] = true;
STEP_CONTINUES_ONLY[27] = true;

/** Matches `[data-npc-q]` values on HUD "?" overlays for red highlight during matching steps. */
const STEP_HUD_Q_RED_DS = [
  /* 0 */ null,
  /* 1 */ 'log',
  null,
  /* 3 */ 'mine',
  null,
  /* 5 */ 'const',
  null,
  null,
  /* 8 */ 'bank',
  /* 9 */ 'cloth',
  /* 10 */ 'pondFish',
  null,
  null,
  /* 13 */ null, // OBSOLETE — merchant dead (crime-scene event 2026-07)
  /* 14 */ 'armory',
  null,
  null,
  null,
  /* 18 */ 'alchemist',
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
];

const STEP_TEXT = [
  'Welcome. While you finish this tutorial, **world chat and player interactions** are disabled — those unlock when you complete it. Press **M** to open the map, then navigate to **Woodcutting** northwest of spawn.',
  'Walk to the lumberjack at **Woodcutting** and speak with them until you receive an **axe**.',
  'Equip your **axe**, then chop a tree until you have at least **1 wood**.',
  'Go to **Mining** on the mainland (**pickaxe icon** on the map) and enter the cave. Speak with the mining NPC inside until you obtain a **pickaxe**.',
  'Equip your **pickaxe**, go outside if you like, and mine until you have **10 stone** and **5 coal**.',
  'Visit **Construction** on the **west** side of the mainland and speak with the foreman / hammer NPC until you receive a **hammer**.',
  'Equip your **hammer**, then press **B** or tap the hammer / build button by the radar to open **Build** mode.',
  'In **Build** mode, place a **firepit** somewhere building is allowed. Fireplaces let you heal nearby; you can also heal at the **Healing Fountain** in the center of the mainland.',
  'Go to the **Bank** in town, **enter** it, then **click a chest** — browse your storage there or stash items so you don\'t lose them in the **Wilderness**. **Mounts and cosmetics** cannot be lost in the **Wilderness**.',
  'Visit the **Cosmetic Shop**. **Click the clerk NPC**, then open the **offers** screen — there is a **limited** offer and a **weekly** rotation, and they cost **gold**.',
  'Find the **Pond** on the **east** side of the mainland (follow the **floor arrows** toward the **Pond**), then speak with the fisherman and get your **fishing rod**.',
  'Equip the rod, **click the water** at the Pond, then wait — you do not need to click again. The fish is caught automatically after some time.',
  'Cook at least **1 fish** at the **Roast Pit** communal cooking station by the eastern **Pond** only — mainland firepits won\'t satisfy this.',
  'Word around the mainland: the **Travelling Merchant** has been found dead at his cart. The Watch has the scene taped off — nothing to do here for now. Tap **Continue**.',
  'Go to the **Armory** east of the plaza and obtain a **starter sword** from the vendor.',
  'Equip the **sword** and land a hit on a training dummy at the **Armory**.',
  'Go **north** on the mainland toward the **Wilderness** entrance (look for the warning / “Do Not Enter” area). The **Wilderness** is dangerous — you can lose items that are not in your **Bank**.',
  'Enter the **Wilderness** and defeat **1 creature** (zombie or dragon). If you die, this step **stays** until you get a kill — gather your gear and try again.',
  'Visit the **Alchemist Shop** and open the potion purchase interface. Potions help with combat and survival.',
  'Enter the **PvP Arena** on the mainland to learn where **safe PvP practice** happens — without the same **Wilderness** risk.',
  'When you are on the **Mainland**, you can **click other players** to add **Friends** — trading and wagering unlock after you finish the tutorial. If no one is around, tap **Continue** below.',
  'Open your **Friends** list from the HUD or the keybind **F**.',
  'Open your **Inventory** from the HUD or press **Tab**.',
  'Open the **Arena Leaderboard** by clicking the trophy button.',
  'Open your **Stats** panel.',
  'Open **Clothing / Outfit** to change your appearance.',
  'Open the **Marketplace**. You can sell items for gold or sell gold for the native currency at a fixed USD price.',
  'To use the **Daily Spinner** and the **Casino**, you must reach a **total level of 5**. Get grinding!',
  '**Housing** includes mansions, houses, trailers, and buildable shacks — earn them by farming, trading, and gold. The **mainland** is the premium living zone; newer players often build **shacks** farther out.',
];

async function tutorialApi(body) {
  const r = await fetch('/api/auth/tutorial-progress', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const d = await r.json().catch(() => (/** @type {any} */ ({})));
  return { ok: r.ok && d.ok !== false, data: d };
}

/**
 * @param {{
 *   initialTutorialStep: number,
 *   parentEl: HTMLElement,
 *   showHudToast: (msg: string, color?: string, opts?: { nowrap?: boolean }) => void,
 *   onVisibilityChange?: () => void,
 *   onTutorialHudPaint?: () => void,
 *   onTutorialComplete?: () => void,
 * }} boot
 */
export function bootstrapKintaraTutorial(boot) {
  let serverStep =
    typeof boot.initialTutorialStep === 'number' && Number.isFinite(boot.initialTutorialStep)
      ? Math.floor(boot.initialTutorialStep)
      : -1;

  /** @type {(s: number) => void} */
  let pushServerStepCb = () => {};

  let wildDeathHintOnStep17 = false;

  const styleEl = document.createElement('style');
  styleEl.id = 'kintara-tutorial-panel-style';
  styleEl.textContent = `
.kintara-tutorial{display:none;flex-direction:column;gap:8px;width:min(320px,calc(100vw - 24px));box-sizing:border-box;padding:10px;border-radius:12px;
border:2px solid #0a0a0a;background:linear-gradient(180deg,rgba(95,100,107,0.78),rgba(64,67,74,0.78) 38%,rgba(42,45,51,0.78) 100%);
font-family:system-ui,"Segoe UI",Roboto,sans-serif;pointer-events:auto;}
.kintara-tutorial__hdr{display:flex;align-items:flex-start;gap:8px;justify-content:space-between;}
.kintara-tutorial__title{color:#eceff3;font-size:11px;font-weight:900;letter-spacing:0.05em;text-transform:uppercase;margin:0;}
.kintara-tutorial__txt{font-size:12px;color:#e8eef8;line-height:1.42;font-weight:650;}
.kintara-tutorial__btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;}
.kintara-tutorial__btn{margin:0;padding:7px 10px;border-radius:9px;font-size:11px;font-weight:800;font-family:inherit;cursor:pointer;border:2px solid #050505;color:#eceff3;
background:linear-gradient(180deg,#5c6066,#3f4247);box-shadow:inset 0 1px 0 rgba(255,255,255,0.08),0 2px 0 rgba(0,0,0,0.32);}
.kintara-tutorial__btn:active{transform:translateY(1px) scale(.98);filter:brightness(.92);}
.kintara-tutorial__death{font-size:11px;color:#ffb4b4;font-weight:700;margin-top:4px;}
`;
  document.head.appendChild(styleEl);

  const root = document.createElement('div');
  root.className = 'kintara-tutorial';

  const hdr = document.createElement('div');
  hdr.className = 'kintara-tutorial__hdr';
  const title = document.createElement('h3');
  title.className = 'kintara-tutorial__title';
  title.textContent = 'TUTORIAL';
  hdr.appendChild(title);

  const body = document.createElement('div');
  body.className = 'kintara-tutorial__txt';

  const deathHint = document.createElement('div');
  deathHint.className = 'kintara-tutorial__death';
  deathHint.style.display = 'none';

  const btns = document.createElement('div');
  btns.className = 'kintara-tutorial__btns';

  const btnContinue = document.createElement('button');
  btnContinue.type = 'button';
  btnContinue.className = 'kintara-tutorial__btn';
  btnContinue.style.display = 'none';
  btnContinue.textContent = 'Continue';

  const btnFinish = document.createElement('button');
  btnFinish.type = 'button';
  btnFinish.className = 'kintara-tutorial__btn';
  btnFinish.style.display = 'none';
  btnFinish.textContent = 'Finish tutorial';

  btns.append(btnContinue, btnFinish);

  root.append(hdr, body, deathHint, btns);
  boot.parentEl.insertBefore(root, boot.parentEl.firstChild);

  function scheduleTutorialHudPaint() {
    /** Run after DOM updates + layout so HUD "?" positions exist before tinting red. */
    requestAnimationFrame(() => {
      boot.onTutorialHudPaint?.();
      requestAnimationFrame(() => boot.onTutorialHudPaint?.());
    });
  }

  async function applyServerTutorialStep(nextStep, suppressHooks) {
    const wasActive =
      typeof serverStep === 'number' && serverStep >= 0 && serverStep <= LAST_STEP_INDEX;
    serverStep =
      typeof nextStep === 'number' && Number.isFinite(nextStep) ? Math.floor(nextStep) : -1;
    const nowActive =
      typeof serverStep === 'number' && serverStep >= 0 && serverStep <= LAST_STEP_INDEX;
    pushServerStepCb(serverStep);
    if (!suppressHooks) boot.onVisibilityChange?.();
    renderPanel();
    if (wasActive && !nowActive) {
      try {
        boot.onTutorialComplete?.();
      } catch (_) {
        /* ignore */
      }
    }
  }

  async function advanceFrom(stepIndex) {
    const r = await tutorialApi({ action: 'advance', fromStep: stepIndex });
    if (!r.ok || r.data.tutorialStep == null) return;
    const prev = stepIndex;
    const nextTs = typeof r.data.tutorialStep === 'number' ? r.data.tutorialStep : -1;
    await applyServerTutorialStep(nextTs);
    if (prev === LAST_STEP_INDEX && nextTs === -1) {
      boot.showHudToast('Tutorial complete. Explore, farm, trade, fight, and build your way up.', '#eceff3', {
        nowrap: true,
      });
    }
  }

  function renderPanel() {
    const active =
      typeof serverStep === 'number' && serverStep >= 0 && serverStep <= LAST_STEP_INDEX;
    root.style.display = active ? 'flex' : 'none';
    if (!active) {
      scheduleTutorialHudPaint();
      return;
    }
    const line = STEP_TEXT[serverStep] || '';
    /**
     * Audit I4: `STEP_TEXT` is a hardcoded literal in this same file — never user input
     * — so the bold-only `**...**` → `<strong>...</strong>` replacement is safe. Any
     * future edit that pulls strings from the network must escape first.
     */
    body.innerHTML = line.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    const cont = !!(STEP_CONTINUES_ONLY[serverStep] && serverStep !== LAST_STEP_INDEX);
    btnContinue.style.display = cont ? 'inline-flex' : 'none';
    btnFinish.style.display = serverStep === LAST_STEP_INDEX ? 'inline-flex' : 'none';
    deathHint.style.display = serverStep === 17 && wildDeathHintOnStep17 ? 'block' : 'none';
    if (serverStep === 17 && wildDeathHintOnStep17)
      deathHint.textContent =
        'You died. Collect your sword and tools again, then defeat one Wilderness creature.';
    scheduleTutorialHudPaint();
  }

  btnContinue.addEventListener('click', async () => {
    if (!(STEP_CONTINUES_ONLY[serverStep])) return;
    await advanceFrom(serverStep);
  });
  btnFinish.addEventListener('click', async () => {
    await advanceFrom(LAST_STEP_INDEX);
  });

  /** @returns {boolean} */
  function tutorialActivePublic() {
    return typeof serverStep === 'number' && serverStep >= 0 && serverStep <= LAST_STEP_INDEX;
  }

  renderPanel();
  scheduleTutorialHudPaint();

  return {
    getServerStep() {
      return serverStep;
    },
    setServerStepUpdater(fn) {
      pushServerStepCb = typeof fn === 'function' ? fn : () => {};
    },
    isActive: tutorialActivePublic,
    renderPanel,

    /** @returns {string | null} `data-npc-q` value that should render red while the tutorial wants that NPC. */
    getHudTutorialQRedDataset() {
      if (!tutorialActivePublic()) return null;
      const v = STEP_HUD_Q_RED_DS[serverStep];
      return typeof v === 'string' ? v : null;
    },

    notify(event, _payload) {
      if (!tutorialActivePublic()) return;
      const s = serverStep;
      if (event === 'wildDeath' && s === 17) {
        wildDeathHintOnStep17 = true;
        renderPanel();
        scheduleTutorialHudPaint();
        return;
      }
      void event;
      void _payload;
    },

    advanceIfMatchesStep(stepIndex, pred) {
      if (!tutorialActivePublic() || typeof pred !== 'function') return Promise.resolve();
      if (serverStep !== stepIndex || !pred()) return Promise.resolve();
      return advanceFrom(stepIndex);
    },

    async restartFromSettings() {
      const r = await tutorialApi({ action: 'restart' });
      if (r.ok && r.data.tutorialStep != null) {
        wildDeathHintOnStep17 = false;
        await applyServerTutorialStep(Number(r.data.tutorialStep));
      }
    },

    marker: {
      refresh: () => {},
      hide: () => {},
    },
  };
}
