(() => {
  "use strict";

  const SOURCE = "NAMIRA_PASSIVE_V1";
  const COMMAND_SOURCE =
    "NAMIRA_PASSIVE_BRIDGE_V1";

  const KEY_ENABLED =
    "namira_capture_enabled";
  const KEY_EVENTS =
    "namira_events";
  const KEY_MARKERS =
    "namira_markers";
  const KEY_META =
    "namira_meta";

  const MAX_EVENTS = 1500;

  let enabled = false;
  let events = [];
  let markers = [];
  let meta = {};
  let pending = [];
  let flushTimer = null;

  async function loadState() {
    const state =
      await chrome.storage.local.get([
        KEY_ENABLED,
        KEY_EVENTS,
        KEY_MARKERS,
        KEY_META
      ]);

    enabled =
      Boolean(state[KEY_ENABLED]);

    events =
      Array.isArray(state[KEY_EVENTS])
        ? state[KEY_EVENTS]
        : [];

    markers =
      Array.isArray(state[KEY_MARKERS])
        ? state[KEY_MARKERS]
        : [];

    meta =
      state[KEY_META] &&
      typeof state[KEY_META] === "object"
        ? state[KEY_META]
        : {};
  }

  function scheduleFlush() {
    if (flushTimer) return;

    flushTimer =
      setTimeout(flush, 500);
  }

  async function flush() {
    flushTimer = null;

    if (!pending.length) return;

    events.push(
      ...pending.splice(0)
    );

    if (
      events.length > MAX_EVENTS
    ) {
      const removed =
        events.length - MAX_EVENTS;

      events =
        events.slice(-MAX_EVENTS);

      meta.droppedEvents =
        Number(
          meta.droppedEvents || 0
        ) + removed;
    }

    meta.lastEventAt =
      new Date().toISOString();

    meta.page =
      location.href
        .split("?")[0]
        .split("#")[0];

    await chrome.storage.local.set({
      [KEY_EVENTS]: events,
      [KEY_META]: meta
    });
  }

  window.addEventListener(
    "message",
    (event) => {
      if (
        event.source !== window ||
        event.origin !== location.origin
      ) {
        return;
      }

      const message = event.data;

      if (
        !message ||
        message.source !== SOURCE
      ) {
        return;
      }

      if (
        message.kind === "api_snapshot" ||
        message.kind === "hook_ready" ||
        message.kind === "hook_failed"
      ) {
        meta.lastProtocolMeta = {
          ts: new Date(
            message.ts || Date.now()
          ).toISOString(),
          kind: message.kind,
          data: message.data
        };

        chrome.storage.local.set({
          [KEY_META]: meta
        });
      }

      if (!enabled) return;

      pending.push({
        ts: new Date(
          message.ts || Date.now()
        ).toISOString(),
        epochMs: Number(
          message.ts || Date.now()
        ),
        kind: String(
          message.kind || "unknown"
        ),
        data: message.data ?? null
      });

      scheduleFlush();
    }
  );

  chrome.storage.onChanged.addListener(
    (changes, area) => {
      if (area !== "local") return;

      if (changes[KEY_ENABLED]) {
        enabled = Boolean(
          changes[KEY_ENABLED].newValue
        );
      }

      if (changes[KEY_EVENTS]) {
        events = Array.isArray(
          changes[KEY_EVENTS].newValue
        )
          ? changes[KEY_EVENTS].newValue
          : [];
      }

      if (changes[KEY_MARKERS]) {
        markers = Array.isArray(
          changes[KEY_MARKERS].newValue
        )
          ? changes[KEY_MARKERS].newValue
          : [];
      }

      if (changes[KEY_META]) {
        meta =
          changes[KEY_META].newValue || {};
      }
    }
  );

  chrome.runtime.onMessage.addListener(
    (
      message,
      _sender,
      sendResponse
    ) => {
      if (
        !message ||
        typeof message !== "object"
      ) {
        return;
      }

      if (
        message.type ===
        "namira_snapshot"
      ) {
        window.postMessage(
          {
            source: COMMAND_SOURCE,
            kind: "snapshot"
          },
          location.origin
        );

        sendResponse({
          ok: true
        });

        return true;
      }

      if (
        message.type ===
        "namira_status"
      ) {
        sendResponse({
          ok: true,
          enabled,
          eventCount:
            events.length +
            pending.length,
          markerCount:
            markers.length,
          page:
            location.href
              .split("?")[0]
              .split("#")[0]
        });

        return true;
      }
    }
  );

  loadState();
})();
