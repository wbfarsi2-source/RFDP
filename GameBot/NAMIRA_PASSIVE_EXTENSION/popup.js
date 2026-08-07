"use strict";

const KEYS = {
  enabled: "namira_capture_enabled",
  events: "namira_events",
  markers: "namira_markers",
  meta: "namira_meta"
};

function nowIso() {
  return new Date().toISOString();
}

function safeFilenameTimestamp() {
  return new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z")
    .replace("T", "_");
}

async function activeTab() {
  const tabs =
    await chrome.tabs.query({
      active: true,
      currentWindow: true
    });

  return tabs[0] || null;
}

async function state() {
  return chrome.storage.local.get(
    Object.values(KEYS)
  );
}

async function refreshStatus() {
  const data = await state();

  const events =
    Array.isArray(data[KEYS.events])
      ? data[KEYS.events]
      : [];

  const markers =
    Array.isArray(data[KEYS.markers])
      ? data[KEYS.markers]
      : [];

  const enabled =
    Boolean(data[KEYS.enabled]);

  const meta =
    data[KEYS.meta] || {};

  document
    .getElementById("status")
    .textContent =
      `Capture: ${
        enabled
          ? "RUNNING"
          : "STOPPED"
      }\n` +
      `Events: ${events.length}` +
      ` | Markers: ${markers.length}\n` +
      `Dropped: ${
        Number(
          meta.droppedEvents || 0
        )
      }`;
}

async function addMarker(label) {
  const data = await state();

  const markers =
    Array.isArray(data[KEYS.markers])
      ? data[KEYS.markers]
      : [];

  const tab = await activeTab();

  markers.push({
    label: String(label),
    ts: nowIso(),
    epochMs: Date.now(),
    page:
      tab?.url
        ? tab.url
            .split("?")[0]
            .split("#")[0]
        : null
  });

  await chrome.storage.local.set({
    [KEYS.markers]: markers
  });

  await refreshStatus();
}

document
  .getElementById("start")
  .addEventListener(
    "click",
    async () => {
      const tab = await activeTab();

      await chrome.storage.local.set({
        [KEYS.enabled]: true,
        [KEYS.events]: [],
        [KEYS.markers]: [],
        [KEYS.meta]: {
          startedAt: nowIso(),
          page:
            tab?.url
              ? tab.url
                  .split("?")[0]
                  .split("#")[0]
              : null,
          droppedEvents: 0,
          version: "0.1.0"
        }
      });

      if (tab?.id) {
        try {
          await chrome.tabs.sendMessage(
            tab.id,
            {
              type: "namira_snapshot"
            }
          );
        } catch (_) {}
      }

      await refreshStatus();
    }
  );

document
  .getElementById("stop")
  .addEventListener(
    "click",
    async () => {
      await chrome.storage.local.set({
        [KEYS.enabled]: false
      });

      await refreshStatus();
    }
  );

document
  .querySelectorAll("[data-marker]")
  .forEach((button) => {
    button.addEventListener(
      "click",
      () => addMarker(
        button.dataset.marker
      )
    );
  });

document
  .getElementById("customMarker")
  .addEventListener(
    "click",
    async () => {
      const label = prompt(
        "Marker label:",
        "NOTE"
      );

      if (
        label &&
        label.trim()
      ) {
        await addMarker(
          label.trim()
        );
      }
    }
  );

document
  .getElementById("snapshot")
  .addEventListener(
    "click",
    async () => {
      const tab = await activeTab();

      if (!tab?.id) return;

      try {
        await chrome.tabs.sendMessage(
          tab.id,
          {
            type: "namira_snapshot"
          }
        );
      } catch (_) {
        alert(
          "Open or refresh the Kintara tab first."
        );
      }
    }
  );

document
  .getElementById("clear")
  .addEventListener(
    "click",
    async () => {
      if (
        !confirm(
          "Clear all Namira capture data?"
        )
      ) {
        return;
      }

      await chrome.storage.local.set({
        [KEYS.enabled]: false,
        [KEYS.events]: [],
        [KEYS.markers]: [],
        [KEYS.meta]: {}
      });

      await refreshStatus();
    }
  );

document
  .getElementById("export")
  .addEventListener(
    "click",
    async () => {
      const data = await state();

      const payload = {
        exportedAt: nowIso(),
        extension:
          "Namira Passive Capture",
        version: "0.1.0",
        enabled:
          Boolean(
            data[KEYS.enabled]
          ),
        meta:
          data[KEYS.meta] || {},
        markers:
          Array.isArray(
            data[KEYS.markers]
          )
            ? data[KEYS.markers]
            : [],
        events:
          Array.isArray(
            data[KEYS.events]
          )
            ? data[KEYS.events]
            : []
      };

      const blob =
        new Blob(
          [
            JSON.stringify(
              payload,
              null,
              2
            )
          ],
          {
            type: "application/json"
          }
        );

      const url =
        URL.createObjectURL(blob);

      try {
        await chrome.downloads.download({
          url,
          filename:
            `Namira_Capture_` +
            `${safeFilenameTimestamp()}.json`,
          saveAs: true
        });
      } finally {
        setTimeout(
          () => URL.revokeObjectURL(url),
          5000
        );
      }
    }
  );

chrome.storage.onChanged.addListener(
  () => refreshStatus()
);

refreshStatus();
