from __future__ import annotations

import gzip
import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import httpx
import websocket

from core.system_proxy import websocket_proxy_options
from core.worker_protocol import WorkerEventType

logger = logging.getLogger(__name__)

EMBER_REGION = "ember"
REGISTER_MIN_INTERVAL_SECONDS = 0.75
IDLE_PING_SECONDS = 15.0
SOCKET_TIMEOUT_SECONDS = 0.5
STALE_AFTER_SECONDS = 7.0
SUMMARY_SECONDS = 20.0
SERVER_RETRY_MIN_SECONDS = 1.0
SERVER_RETRY_MAX_SECONDS = 20.0
MONITOR_IDLE_SECONDS = 0.2
VERIFICATION_TIMEOUT_SECONDS = 10.0
VERIFICATION_SNAPSHOTS = 2


class MonitorAuthenticationError(RuntimeError):
    pass


def _server_number(server: dict[str, Any]) -> int:
    match = re.fullmatch(r"Server\s+(\d+)", str(server.get("name") or ""))
    return int(match.group(1)) if match else -1


def _route_shard_id(server: dict[str, Any]) -> int:
    for key in ("routeShardId", "localShardId", "id"):
        try:
            value = int(float(server.get(key) or 0))
        except Exception:
            value = 0
        if value > 0:
            return value
    return 0


def _controller_id(server: dict[str, Any]) -> str:
    raw = str(server.get("controllerId") or "").strip().lower()
    return re.sub(r"[^a-z0-9_]", "", raw)[:24]


def _ws_url(server: dict[str, Any]) -> str:
    shard = _route_shard_id(server)
    if shard <= 0:
        raise RuntimeError("Invalid spectator shard")

    controller = _controller_id(server)
    route = (
        f"/ws/spectate/{controller}/s{shard}"
        if controller
        else f"/ws/spectate/s{shard}"
    )

    if controller:
        fanout_origin = str(server.get("fanoutOrigin") or "").strip()
        if not fanout_origin:
            raise RuntimeError("Missing spectator fanout origin")
        if fanout_origin.startswith(("ws://", "wss://")):
            return fanout_origin.rstrip("/") + route
        return re.sub(r"^http", "ws", fanout_origin, flags=re.I).rstrip("/") + route

    # Compatibility only for older server-list payloads that do not expose a controller.
    base = str(server.get("wsBaseUrl") or "").strip()
    if base:
        if base.startswith(("ws://", "wss://")):
            return base.rstrip("/") + route
        return re.sub(r"^http", "ws", base, flags=re.I).rstrip("/") + route
    return "wss://kintara.gg" + route


def _decode_frames(raw: Any) -> list[dict[str, Any]]:
    try:
        if isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
            if data and data[0] == 1:
                data = gzip.decompress(data[1:])
            text = data.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        payload = json.loads(text)
    except Exception:
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _human_player_id(player: Any) -> int | None:
    if not isinstance(player, dict):
        return None
    try:
        player_id = int(float(player.get("id")))
    except Exception:
        return None
    if player_id <= 0:
        return None
    if any(bool(player.get(key)) for key in ("isNpc", "isNPC", "npc", "isMob", "isBoss", "isPet")):
        return None
    marker = " ".join(
        str(player.get(key) or "").strip().lower()
        for key in ("type", "kind", "entityType", "entity_type", "npcType", "mobType", "species")
    )
    blocked = (
        "npc",
        "mob",
        "boss",
        "enemy",
        "monster",
        "creature",
        "spider",
        "pet",
        "companion",
        "minion",
        "summon",
        "animal",
    )
    if any(word in marker for word in blocked):
        return None
    return player_id


def _count_humans(players: Iterable[Any]) -> int:
    unique_ids = {
        player_id
        for player_id in (_human_player_id(player) for player in players)
        if player_id is not None
    }
    return len(unique_ids)


@dataclass(frozen=True)
class WatcherState:
    server: str
    number: int
    connected: bool
    count: int
    snapshots: int
    last_snapshot_at: float
    age: float | None
    error: str


class EmberSpectatorWatcher:
    """Persistent anonymous spectator for one numbered Kintara server."""

    def __init__(self, server: dict[str, Any], user_agent: str) -> None:
        self.server = dict(server)
        self.user_agent = user_agent
        self.name = str(server.get("name") or "?")
        self.number = _server_number(server)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.refresh_event = threading.Event()
        self.connected = False
        self.player_count = 0
        self.snapshots = 0
        self.last_snapshot_at = 0.0
        self.error = ""
        self._requested_snapshot_target = 0
        self.ws = None
        self.thread = threading.Thread(target=self._run, name=f"molten-{self.number}", daemon=True)

    @property
    def endpoint(self) -> str:
        return _ws_url(self.server)

    def start(self) -> "EmberSpectatorWatcher":
        self.thread.start()
        return self

    def request_snapshot_target(self, target: int) -> None:
        with self.lock:
            self._requested_snapshot_target = max(
                self._requested_snapshot_target,
                max(1, int(target)),
            )
        self.refresh_event.set()

    def stop(self) -> None:
        self.stop_event.set()
        self.refresh_event.set()
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass

    def state(self) -> WatcherState:
        with self.lock:
            age = None if self.last_snapshot_at <= 0 else max(0.0, time.time() - self.last_snapshot_at)
            return WatcherState(
                server=self.name,
                number=self.number,
                connected=bool(self.connected),
                count=int(self.player_count),
                snapshots=int(self.snapshots),
                last_snapshot_at=float(self.last_snapshot_at),
                age=age,
                error=str(self.error or ""),
            )

    def _connect(self):
        url = self.endpoint
        return websocket.create_connection(
            url,
            timeout=12,
            origin="https://kintara.gg",
            enable_multithread=True,
            header=[
                f"User-Agent: {self.user_agent}",
                "Pragma: no-cache",
                "Cache-Control: no-cache",
            ],
            **websocket_proxy_options(url),
        )

    def _send_registration(self) -> None:
        if self.ws is None:
            raise RuntimeError("spectator socket is not connected")
        self.ws.send(json.dumps({"t": "spec_reg", "region": EMBER_REGION}, separators=(",", ":")))

    def _run(self) -> None:
        retry_delay = SERVER_RETRY_MIN_SECONDS
        while not self.stop_event.is_set():
            try:
                self.ws = self._connect()
                self.ws.settimeout(SOCKET_TIMEOUT_SECONDS)
                with self.lock:
                    self.connected = True
                    self.error = ""
                retry_delay = SERVER_RETRY_MIN_SECONDS
                last_register_at = 0.0
                last_ping_at = time.monotonic()

                while not self.stop_event.is_set():
                    now = time.monotonic()
                    with self.lock:
                        pending_snapshot = self.snapshots < self._requested_snapshot_target

                    if pending_snapshot and (
                        self.refresh_event.is_set()
                        or now - last_register_at >= REGISTER_MIN_INTERVAL_SECONDS
                    ):
                        self._send_registration()
                        last_register_at = now
                        self.refresh_event.clear()
                    elif not pending_snapshot and now - last_ping_at >= IDLE_PING_SECONDS:
                        self.ws.ping()
                        last_ping_at = now

                    try:
                        raw = self.ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue

                    if raw in (None, ""):
                        raise RuntimeError("spectator socket closed")

                    for message in _decode_frames(raw):
                        if str(message.get("t") or "") != "snap":
                            continue
                        if str(message.get("region") or "").strip().lower() != EMBER_REGION:
                            continue
                        count = _count_humans(message.get("players") or [])
                        with self.lock:
                            self.player_count = count
                            self.snapshots += 1
                            self.last_snapshot_at = time.time()
                            self.error = ""

            except Exception as exc:
                with self.lock:
                    self.connected = False
                    self.error = str(exc)[:180]
            finally:
                try:
                    if self.ws is not None:
                        self.ws.close()
                except Exception:
                    pass
                self.ws = None
                with self.lock:
                    self.connected = False

            if not self.stop_event.is_set():
                self.stop_event.wait(retry_delay + random.uniform(0.0, 0.7))
                retry_delay = min(SERVER_RETRY_MAX_SECONDS, retry_delay * 1.7)


class KintaraEmberMonitor:
    def __init__(
        self,
        *,
        base_url: str,
        cookie: str,
        user_agent: str,
        cookie_provider: Callable[[], str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie = cookie
        self.user_agent = user_agent
        self.cookie_provider = cookie_provider
        self.watchers: dict[int, EmberSpectatorWatcher] = {}
        self._http_client: httpx.Client | None = None
        self._last_server_error = ""

    def _resolve_cookie(self) -> str:
        if self.cookie_provider is not None:
            try:
                latest = str(self.cookie_provider() or "").strip()
                if latest:
                    self.cookie = latest
            except Exception:
                pass
        return self.cookie

    def _client(self) -> httpx.Client:
        cookie = self._resolve_cookie()
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=httpx.Timeout(20.0, connect=15.0),
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json,text/plain,*/*",
                    "Origin": self.base_url,
                    "Referer": self.base_url + "/play",
                    "Cookie": cookie,
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
                trust_env=True,
            )
        else:
            self._http_client.headers["Cookie"] = cookie
        return self._http_client

    def _fetch_servers(self) -> list[dict[str, Any]]:
        response = self._client().get(
            self.base_url + "/api/servers",
            params={"_": str(int(time.time() * 1000))},
        )
        if response.status_code in (401, 403):
            raise MonitorAuthenticationError("The shared Kintara session is no longer valid")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("ok") is False:
            raise RuntimeError("Kintara server list is unavailable")
        rows = [
            dict(row)
            for row in (payload.get("servers") or [])
            if isinstance(row, dict) and _server_number(row) >= 1
        ]
        rows.sort(key=_server_number)
        if not rows:
            raise RuntimeError("Kintara returned no numbered servers")
        return rows

    def _replace_watcher(self, number: int, server: dict[str, Any]) -> None:
        previous = self.watchers.pop(number, None)
        if previous is not None:
            previous.stop()
            try:
                previous.thread.join(timeout=1.5)
            except Exception:
                pass
        self.watchers[number] = EmberSpectatorWatcher(server, self.user_agent).start()

    def _sync_watchers(self) -> None:
        servers = self._fetch_servers()
        current = {_server_number(row): row for row in servers}

        for number in list(self.watchers):
            if number not in current:
                watcher = self.watchers.pop(number)
                watcher.stop()

        for number, server in current.items():
            existing = self.watchers.get(number)
            if existing is None:
                self.watchers[number] = EmberSpectatorWatcher(server, self.user_agent).start()
                time.sleep(0.04)
                continue
            try:
                endpoint_changed = existing.endpoint != _ws_url(server)
            except Exception:
                endpoint_changed = True
            if endpoint_changed:
                self._replace_watcher(number, server)
            else:
                existing.server = dict(server)
                existing.name = str(server.get("name") or existing.name)

        self._last_server_error = ""

    def stop(self) -> None:
        for watcher in list(self.watchers.values()):
            watcher.stop()
        for watcher in list(self.watchers.values()):
            try:
                watcher.thread.join(timeout=1.5)
            except Exception:
                pass
        self.watchers.clear()
        if self._http_client is not None:
            try:
                self._http_client.close()
            except Exception:
                pass
            self._http_client = None

    def _verified_summary(self, stop_event, *, timeout_seconds: float) -> dict[str, Any]:
        watchers = dict(sorted(self.watchers.items()))
        if not watchers:
            return {
                "monitored": 0,
                "live": 0,
                "coverage": 0.0,
                "accurate": False,
                "total_players": 0,
                "top3": [],
                "missing_servers": [],
            }

        baseline = {number: watcher.state().snapshots for number, watcher in watchers.items()}
        round_started_at = time.time()
        for watcher in watchers.values():
            watcher.request_snapshot_target(baseline[watcher.number] + VERIFICATION_SNAPSHOTS)

        deadline = time.monotonic() + max(4.0, float(timeout_seconds))
        halfway = time.monotonic() + max(2.0, float(timeout_seconds) / 2.0)
        nudged = False
        fresh: dict[int, WatcherState] = {}

        while not stop_event.is_set() and time.monotonic() < deadline:
            fresh.clear()
            for number, watcher in watchers.items():
                state = watcher.state()
                if (
                    state.snapshots >= baseline[number] + VERIFICATION_SNAPSHOTS
                    and state.last_snapshot_at >= round_started_at
                    and state.age is not None
                    and state.age <= STALE_AFTER_SECONDS
                ):
                    fresh[number] = state

            if len(fresh) == len(watchers):
                break

            if not nudged and time.monotonic() >= halfway:
                for number, watcher in watchers.items():
                    if number not in fresh:
                        watcher.request_snapshot_target(baseline[watcher.number] + VERIFICATION_SNAPSHOTS)
                nudged = True

            stop_event.wait(0.1)

        missing_numbers = [number for number in watchers if number not in fresh]
        coverage = len(fresh) / len(watchers)
        accurate = not missing_numbers and bool(watchers)

        if not accurate:
            return {
                "monitored": len(watchers),
                "live": len(fresh),
                "coverage": coverage,
                "accurate": False,
                "total_players": 0,
                "top3": [],
                "missing_servers": [watchers[number].name for number in missing_numbers],
            }

        rows = list(fresh.values())
        top = sorted(
            [row for row in rows if row.count > 0],
            key=lambda row: (-row.count, row.number),
        )[:3]
        return {
            "monitored": len(watchers),
            "live": len(rows),
            "coverage": 1.0,
            "accurate": True,
            "total_players": sum(row.count for row in rows),
            "top3": [{"server": row.server, "count": row.count} for row in top],
            "missing_servers": [],
        }

    def run(
        self,
        stop_event,
        emit: Callable[..., None],
        *,
        summary_seconds: float = SUMMARY_SECONDS,
        refresh_requested: Callable[[], list[str] | bool] | None = None,
    ) -> None:
        summary_seconds = max(20.0, float(summary_seconds or SUMMARY_SECONDS))
        next_scheduled_at = 0.0
        retry_seconds = SERVER_RETRY_MIN_SECONDS

        try:
            while not stop_event.is_set():
                now = time.monotonic()
                request_ids: list[str] = []
                if refresh_requested is not None:
                    requested = refresh_requested()
                    if isinstance(requested, list):
                        request_ids = [str(item) for item in requested if str(item)]
                    elif requested:
                        request_ids = ["legacy"]

                source = "manual" if request_ids else "scheduled"
                due = bool(request_ids) or now >= next_scheduled_at
                if not due:
                    stop_event.wait(MONITOR_IDLE_SECONDS)
                    continue

                cycle_started = time.monotonic()
                try:
                    self._sync_watchers()
                    retry_seconds = SERVER_RETRY_MIN_SECONDS
                    payload = self._verified_summary(
                        stop_event,
                        timeout_seconds=VERIFICATION_TIMEOUT_SECONDS,
                    )
                    emit(
                        WorkerEventType.METRIC,
                        "Verified Come To Molten snapshot",
                        service_key="molten_location",
                        source=source,
                        request_ids=request_ids,
                        **payload,
                    )
                except MonitorAuthenticationError as exc:
                    message = str(exc)
                    if message != self._last_server_error:
                        logger.warning("Come To Molten authentication is unavailable: %s", message)
                        self._last_server_error = message
                    emit(
                        WorkerEventType.METRIC,
                        "Come To Molten data is unavailable",
                        service_key="molten_location",
                        source=source,
                        request_ids=request_ids,
                        monitored=len(self.watchers),
                        live=0,
                        coverage=0.0,
                        accurate=False,
                        total_players=0,
                        top3=[],
                        missing_servers=[],
                    )
                    stop_event.wait(min(20.0, retry_seconds))
                    retry_seconds = min(SERVER_RETRY_MAX_SECONDS, retry_seconds * 1.7)
                except Exception as exc:
                    message = str(exc)[:240]
                    if message != self._last_server_error:
                        logger.warning("Come To Molten verification failed: %s", message)
                        self._last_server_error = message
                    emit(
                        WorkerEventType.METRIC,
                        "Come To Molten data is unavailable",
                        service_key="molten_location",
                        source=source,
                        request_ids=request_ids,
                        monitored=len(self.watchers),
                        live=0,
                        coverage=0.0,
                        accurate=False,
                        total_players=0,
                        top3=[],
                        missing_servers=[],
                    )
                    stop_event.wait(min(10.0, retry_seconds))
                    retry_seconds = min(SERVER_RETRY_MAX_SECONDS, retry_seconds * 1.7)

                if source == "scheduled":
                    next_scheduled_at = max(cycle_started + summary_seconds, time.monotonic() + 0.2)
                elif next_scheduled_at <= 0.0:
                    next_scheduled_at = time.monotonic() + summary_seconds
        finally:
            self.stop()
