(() => {
  "use strict";

  if (window.__NAMIRA_PASSIVE_HOOK_V1__) return;
  window.__NAMIRA_PASSIVE_HOOK_V1__ = true;

  const SOURCE = "NAMIRA_PASSIVE_V1";
  const COMMAND_SOURCE = "NAMIRA_PASSIVE_BRIDGE_V1";
  const NativeWebSocket = window.WebSocket;
  const MAX_TEXT = 8000;

  let socketSeq = 0;

  const sensitiveKey =
    /(^|_)(token|cookie|authorization|session|secret|password|connecttoken|kt)($|_)/i;

  function cleanUrl(value) {
    try {
      const url = new URL(String(value), location.href);
      return `${url.protocol}//${url.host}${url.pathname}`;
    } catch (_) {
      return String(value || "").split("?")[0].split("#")[0];
    }
  }

  function redactString(value) {
    return String(value || "")
      .replace(
        /([?&](?:kt|token|connectToken|session)=)[^&\s]+/gi,
        "$1[REDACTED]"
      )
      .replace(
        /((?:token|cookie|authorization|session|connectToken|kt)\s*[:=]\s*["']?)[^"',}\s]+/gi,
        "$1[REDACTED]"
      )
      .slice(0, MAX_TEXT);
  }

  function redactDeep(value, depth = 0) {
    if (depth > 8) return "[MAX_DEPTH]";

    if (value === null || value === undefined) return value;

    if (typeof value === "string") {
      return redactString(value);
    }

    if (typeof value === "number" || typeof value === "boolean") {
      return value;
    }

    if (Array.isArray(value)) {
      return value
        .slice(0, 200)
        .map((item) => redactDeep(item, depth + 1));
    }

    if (typeof value === "object") {
      const out = {};

      for (const [key, item] of Object.entries(value).slice(0, 250)) {
        out[key] = sensitiveKey.test(key)
          ? "[REDACTED]"
          : redactDeep(item, depth + 1);
      }

      return out;
    }

    return String(value);
  }

  function emit(kind, data) {
    window.postMessage(
      {
        source: SOURCE,
        kind,
        ts: Date.now(),
        data: redactDeep(data)
      },
      location.origin
    );
  }

  async function gunzip(bytes) {
    if (typeof DecompressionStream !== "function") {
      throw new Error("DecompressionStream unavailable");
    }

    const stream = new Blob([bytes])
      .stream()
      .pipeThrough(new DecompressionStream("gzip"));

    return new Uint8Array(
      await new Response(stream).arrayBuffer()
    );
  }

  function bytesToBase64(bytes, limit = 4096) {
    const selected = bytes.slice(0, limit);
    let binary = "";
    const step = 0x8000;

    for (let i = 0; i < selected.length; i += step) {
      binary += String.fromCharCode(
        ...selected.subarray(i, i + step)
      );
    }

    return btoa(binary);
  }

  function normalizeText(text) {
    const cleaned = redactString(text);

    try {
      const parsed = JSON.parse(text);

      return {
        format: "json",
        text: JSON.stringify(redactDeep(parsed)).slice(0, MAX_TEXT)
      };
    } catch (_) {
      return {
        format: "text",
        text: cleaned
      };
    }
  }

  async function normalizePayload(payload) {
    try {
      if (typeof payload === "string") {
        return {
          ...normalizeText(payload),
          byteLength: new TextEncoder().encode(payload).length
        };
      }

      let bytes;

      if (payload instanceof Blob) {
        bytes = new Uint8Array(await payload.arrayBuffer());
      } else if (payload instanceof ArrayBuffer) {
        bytes = new Uint8Array(payload);
      } else if (ArrayBuffer.isView(payload)) {
        bytes = new Uint8Array(
          payload.buffer,
          payload.byteOffset,
          payload.byteLength
        );
      } else {
        return {
          format: typeof payload,
          text: redactString(String(payload))
        };
      }

      const originalLength = bytes.byteLength;
      let decodedBytes = bytes;
      let compression = "none";

      try {
        if (bytes.length > 2 && bytes[0] === 1) {
          decodedBytes = await gunzip(bytes.slice(1));
          compression = "prefix1+gzip";
        } else if (
          bytes.length > 2 &&
          bytes[0] === 0x1f &&
          bytes[1] === 0x8b
        ) {
          decodedBytes = await gunzip(bytes);
          compression = "gzip";
        }
      } catch (_) {
        decodedBytes = bytes;
        compression = "decode_failed";
      }

      try {
        const text = new TextDecoder(
          "utf-8",
          { fatal: false }
        ).decode(decodedBytes);

        return {
          ...normalizeText(text),
          byteLength: originalLength,
          compression
        };
      } catch (_) {
        return {
          format: "binary",
          byteLength: originalLength,
          compression,
          base64Prefix: bytesToBase64(bytes)
        };
      }
    } catch (error) {
      return {
        format: "capture_error",
        text: String(error)
      };
    }
  }

  function protocolsToArray(protocols) {
    if (Array.isArray(protocols)) {
      return protocols.map(String);
    }

    if (protocols === undefined) {
      return [];
    }

    return [String(protocols)];
  }

  function observeSocket(ws, url, protocols) {
    const socketId = `ws-${++socketSeq}`;
    const safeUrl = cleanUrl(url);

    emit("ws_created", {
      socketId,
      url: safeUrl,
      protocols: protocolsToArray(protocols),
      page: cleanUrl(location.href)
    });

    ws.addEventListener("open", () => {
      emit("ws_open", {
        socketId,
        url: safeUrl,
        protocol: ws.protocol || ""
      });
    });

    ws.addEventListener("close", (event) => {
      emit("ws_close", {
        socketId,
        url: safeUrl,
        code: event.code,
        reason: redactString(event.reason || ""),
        clean: event.wasClean
      });
    });

    ws.addEventListener("error", () => {
      emit("ws_error", {
        socketId,
        url: safeUrl
      });
    });

    ws.addEventListener("message", (event) => {
      normalizePayload(event.data).then((payload) => {
        emit("ws_frame_received", {
          socketId,
          url: safeUrl,
          payload
        });
      });
    });

    const nativeSend = ws.send;

    ws.send = function namiraObservedSend(data) {
      normalizePayload(data).then((payload) => {
        emit("ws_frame_sent", {
          socketId,
          url: safeUrl,
          payload
        });
      });

      return nativeSend.call(this, data);
    };
  }

  const WrappedWebSocket = new Proxy(
    NativeWebSocket,
    {
      construct(Target, args, newTarget) {
        const actualTarget =
          newTarget === WrappedWebSocket
            ? Target
            : newTarget;

        const ws = Reflect.construct(
          Target,
          args,
          actualTarget
        );

        observeSocket(ws, args[0], args[1]);
        return ws;
      }
    }
  );

  try {
    Object.defineProperty(
      window,
      "WebSocket",
      {
        configurable: true,
        enumerable: true,
        writable: true,
        value: WrappedWebSocket
      }
    );

    emit("hook_ready", {
      page: cleanUrl(location.href)
    });
  } catch (error) {
    emit("hook_failed", {
      error: String(error)
    });
  }

  function collectInterestingPaths(root) {
    const results = [];
    const visited = new WeakSet();

    const interesting =
      /(server|shard|zone|region|health|shield|armor|damage|\bhp\b|player|character|id|name)/i;

    function walk(value, path, depth) {
      if (
        results.length >= 300 ||
        depth > 7 ||
        value === null ||
        value === undefined
      ) {
        return;
      }

      if (typeof value !== "object") {
        const key = path.split(".").pop() || "";

        if (interesting.test(key)) {
          results.push({
            path,
            value: redactDeep(value)
          });
        }

        return;
      }

      if (visited.has(value)) return;
      visited.add(value);

      if (Array.isArray(value)) {
        value
          .slice(0, 30)
          .forEach((item, index) => {
            walk(
              item,
              `${path}[${index}]`,
              depth + 1
            );
          });

        return;
      }

      for (
        const [key, item]
        of Object.entries(value).slice(0, 150)
      ) {
        const nextPath = path
          ? `${path}.${key}`
          : key;

        if (
          interesting.test(key) &&
          (typeof item !== "object" || item === null)
        ) {
          results.push({
            path: nextPath,
            value: redactDeep(item)
          });
        }

        walk(
          item,
          nextPath,
          depth + 1
        );
      }
    }

    walk(root, "", 0);
    return results;
  }

  async function fetchJson(path) {
    try {
      const response = await fetch(
        path,
        {
          method: "GET",
          credentials: "include",
          cache: "no-store",
          headers: {
            Accept: "application/json"
          }
        }
      );

      const text = await response.text();
      let body = null;

      try {
        body = JSON.parse(text);
      } catch (_) {
        body = {
          raw: redactString(text)
        };
      }

      return {
        ok: response.ok,
        status: response.status,
        body
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        error: String(error)
      };
    }
  }

  async function captureApiSnapshot() {
    const [meResult, serversResult] =
      await Promise.all([
        fetchJson("/api/auth/me"),
        fetchJson("/api/servers")
      ]);

    const servers = [];
    const rawServers =
      serversResult?.body?.servers;

    if (Array.isArray(rawServers)) {
      for (const server of rawServers) {
        if (
          !server ||
          typeof server !== "object"
        ) {
          continue;
        }

        servers.push({
          name: server.name ?? null,
          id: server.id ?? null,
          displayId:
            server.displayId ?? null,
          routeShardId:
            server.routeShardId ?? null,
          localShardId:
            server.localShardId ?? null,
          zone: server.zone ?? null,
          region: server.region ?? null,
          wsBaseUrl: cleanUrl(
            server.wsBaseUrl || ""
          ),
          requiresMembership:
            Boolean(server.requiresMembership),
          full: Boolean(server.full),
          queueLength:
            server.queueLength ?? null
        });
      }
    }

    emit("api_snapshot", {
      page: cleanUrl(location.href),
      authStatus: meResult.status,
      authInterestingPaths:
        meResult.body
          ? collectInterestingPaths(
              meResult.body
            )
          : [],
      serversStatus:
        serversResult.status,
      servers
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
        message.source !== COMMAND_SOURCE
      ) {
        return;
      }

      if (message.kind === "snapshot") {
        captureApiSnapshot();
      }
    }
  );

  setTimeout(
    captureApiSnapshot,
    1800
  );
})();
