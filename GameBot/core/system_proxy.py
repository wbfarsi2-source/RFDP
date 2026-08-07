from __future__ import annotations

import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Mapping

logger = logging.getLogger(__name__)

_PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)

_DIRECT_PROBE_URL = "https://api.telegram.org"
_DIRECT_PROBE_TTL_SECONDS = 12.0
_DIRECT_PROBE_TIMEOUT_SECONDS = 2.5
_direct_probe_cached_at = 0.0
_direct_probe_cached_value = False


@dataclass(frozen=True, slots=True)
class ProxyConfiguration:
    enabled: bool
    source: str = "direct"
    http_proxy: str = ""
    https_proxy: str = ""
    all_proxy: str = ""
    no_proxy: str = ""

    def safe_summary(self) -> str:
        if not self.enabled:
            return "direct"
        value = self.https_proxy or self.http_proxy or self.all_proxy
        try:
            parsed = urllib.parse.urlparse(value)
            host = parsed.hostname or "proxy"
            port = f":{parsed.port}" if parsed.port else ""
            return f"{self.source} ({host}{port})"
        except Exception:
            return self.source

    def fingerprint(self) -> tuple[bool, str, str, str]:
        return (
            bool(self.enabled),
            str(self.http_proxy or ""),
            str(self.https_proxy or ""),
            str(self.all_proxy or ""),
        )


def _normalize_proxy(value: str, default_scheme: str = "http") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"{default_scheme}://{text}"
    if text.lower().startswith("socks5h://"):
        text = "socks5://" + text[len("socks5h://"):]
    return text


def _parse_proxy_server(raw: str) -> tuple[str, str, str]:
    text = str(raw or "").strip()
    if not text:
        return "", "", ""

    if "=" not in text:
        proxy = _normalize_proxy(text, "http")
        return proxy, proxy, ""

    values: dict[str, str] = {}
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key.strip().lower()] = value.strip()

    http_proxy = _normalize_proxy(values.get("http", ""), "http")
    https_proxy = _normalize_proxy(values.get("https", ""), "http")
    socks_proxy = _normalize_proxy(values.get("socks", ""), "socks5")

    if not https_proxy:
        https_proxy = http_proxy
    if not http_proxy:
        http_proxy = https_proxy
    return http_proxy, https_proxy, socks_proxy


def _normalize_no_proxy(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "localhost,127.0.0.1,::1"

    parts: list[str] = []
    for item in re.split(r"[;,]", text):
        item = item.strip()
        if not item:
            continue
        if item.lower() == "<local>":
            parts.extend(["localhost", "127.0.0.1", "::1"])
        else:
            parts.append(item)

    seen: set[str] = set()
    result: list[str] = []
    for item in parts:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return ",".join(result)


def _from_environment(environ: Mapping[str, str]) -> ProxyConfiguration:
    """Explicit helper retained for tests/callers.

    Normal runtime detection intentionally does not trust HTTP_PROXY values
    inherited from START_GAMEBOT.bat because those values may describe the VPN
    route that existed when the process first started.
    """
    http_proxy = _normalize_proxy(
        environ.get("HTTP_PROXY", "") or environ.get("http_proxy", ""),
        "http",
    )
    https_proxy = _normalize_proxy(
        environ.get("HTTPS_PROXY", "") or environ.get("https_proxy", ""),
        "http",
    )
    if not https_proxy:
        https_proxy = http_proxy
    if not http_proxy:
        http_proxy = https_proxy

    all_proxy = _normalize_proxy(
        environ.get("ALL_PROXY", "") or environ.get("all_proxy", ""),
        "socks5",
    )
    no_proxy = _normalize_no_proxy(
        environ.get("NO_PROXY", "") or environ.get("no_proxy", "")
    )
    return ProxyConfiguration(
        bool(http_proxy or https_proxy or all_proxy),
        "environment",
        http_proxy,
        https_proxy,
        all_proxy,
        no_proxy,
    )


def _manual_proxy_value() -> str:
    direct = str(os.environ.get("GAMEBOT_PROXY_URL") or "").strip()
    if direct:
        return direct

    try:
        path = os.path.join(os.getcwd(), ".env")
        with open(path, "r", encoding="utf-8-sig") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip().upper() == "GAMEBOT_PROXY_URL":
                    return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _manual_route_mode() -> str:
    value = _manual_proxy_value().strip()
    lowered = value.lower()
    if not value or lowered == "auto":
        return "auto"
    if lowered in {"direct", "none", "off"}:
        return "direct"
    return "proxy"


def _from_manual_proxy() -> ProxyConfiguration:
    value = _manual_proxy_value()
    if _manual_route_mode() != "proxy":
        return ProxyConfiguration(False)

    proxy = _normalize_proxy(value, "http")
    return ProxyConfiguration(
        True,
        "gamebot-manual",
        proxy,
        proxy,
        proxy,
        "localhost,127.0.0.1,::1",
    )


def _from_launcher_fallback() -> ProxyConfiguration:
    value = str(os.environ.get("GAMEBOT_AUTO_PROXY_URL") or "").strip()
    if not value:
        return ProxyConfiguration(False)
    proxy = _normalize_proxy(value, "http")
    source = str(os.environ.get("GAMEBOT_AUTO_PROXY_SOURCE") or "launcher-fallback").strip()
    return ProxyConfiguration(
        True,
        source or "launcher-fallback",
        proxy,
        proxy,
        proxy,
        "localhost,127.0.0.1,::1",
    )


def _direct_connection_available() -> bool:
    """Probe Telegram without consuming any system/environment proxy.

    The short TTL keeps normal websocket/HTTP calls fast while still allowing
    a running bot to switch between direct internet and a proxy fallback.
    Any HTTP response (including 4xx/5xx) proves that the direct route works.
    """
    global _direct_probe_cached_at, _direct_probe_cached_value

    now = time.monotonic()
    if now - _direct_probe_cached_at < _DIRECT_PROBE_TTL_SECONDS:
        return _direct_probe_cached_value

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        _DIRECT_PROBE_URL,
        method="HEAD",
        headers={"User-Agent": "GameBot-Network-Probe/1.0"},
    )
    try:
        with opener.open(request, timeout=_DIRECT_PROBE_TIMEOUT_SECONDS):
            available = True
    except urllib.error.HTTPError:
        available = True
    except Exception:
        available = False

    _direct_probe_cached_at = now
    _direct_probe_cached_value = available
    return available


def _from_windows_registry() -> ProxyConfiguration:
    if sys.platform != "win32":
        return ProxyConfiguration(False)

    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            try:
                enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0]) == 1
            except OSError:
                enabled = False
            try:
                raw = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "")
            except OSError:
                raw = ""
            try:
                bypass = str(winreg.QueryValueEx(key, "ProxyOverride")[0] or "")
            except OSError:
                bypass = ""

        if not enabled or not raw:
            return ProxyConfiguration(False)

        http_proxy, https_proxy, all_proxy = _parse_proxy_server(raw)
        return ProxyConfiguration(
            bool(http_proxy or https_proxy or all_proxy),
            "windows-system",
            http_proxy,
            https_proxy,
            all_proxy,
            _normalize_no_proxy(bypass),
        )
    except Exception:
        logger.debug("Windows proxy registry detection failed", exc_info=True)
        return ProxyConfiguration(False)


def _from_system_resolver() -> ProxyConfiguration:
    """Read the live OS proxy without re-consuming stale process env values."""
    try:
        if sys.platform == "win32":
            resolver = getattr(urllib.request, "getproxies_registry", None)
            proxies = resolver() if callable(resolver) else {}
        else:
            proxies = urllib.request.getproxies()
    except Exception:
        return ProxyConfiguration(False)

    http_proxy = _normalize_proxy(str(proxies.get("http") or ""), "http")
    https_proxy = _normalize_proxy(str(proxies.get("https") or ""), "http")
    all_proxy = _normalize_proxy(
        str(proxies.get("all") or proxies.get("socks") or ""),
        "socks5",
    )
    if not https_proxy:
        https_proxy = http_proxy
    if not http_proxy:
        http_proxy = https_proxy

    return ProxyConfiguration(
        bool(http_proxy or https_proxy or all_proxy),
        "system-resolver",
        http_proxy,
        https_proxy,
        all_proxy,
        _normalize_no_proxy(str(proxies.get("no") or "")),
    )


def detect_proxy(environ: Mapping[str, str] | None = None) -> ProxyConfiguration:
    # Explicit test/caller environments keep their historical behavior.
    if environ is not None:
        explicit = _from_environment(environ)
        if explicit.enabled:
            return explicit

    mode = _manual_route_mode()
    if mode == "direct":
        return ProxyConfiguration(
            False,
            "direct-forced",
            no_proxy="localhost,127.0.0.1,::1",
        )

    manual = _from_manual_proxy()
    if manual.enabled:
        return manual

    # AUTO is direct-first. Only when the direct Telegram route is unavailable
    # do we fall back to the proxy route verified by the launcher / Windows.
    if _direct_connection_available():
        return ProxyConfiguration(
            False,
            "direct-verified",
            no_proxy="localhost,127.0.0.1,::1",
        )

    launcher = _from_launcher_fallback()
    if launcher.enabled:
        return launcher

    windows = _from_windows_registry()
    if windows.enabled:
        return windows

    resolved = _from_system_resolver()
    if resolved.enabled:
        return resolved

    return ProxyConfiguration(
        False,
        "direct-unverified",
        no_proxy="localhost,127.0.0.1,::1",
    )


def apply_system_proxy() -> ProxyConfiguration:
    config = detect_proxy()

    # Remove the route inherited from the launcher or a previous VPN state.
    for key in _PROXY_KEYS:
        os.environ.pop(key, None)

    if config.enabled:
        values = {
            "HTTP_PROXY": config.http_proxy or config.https_proxy or config.all_proxy,
            "HTTPS_PROXY": config.https_proxy or config.http_proxy or config.all_proxy,
            "ALL_PROXY": config.all_proxy,
            "NO_PROXY": config.no_proxy,
        }
        for key, value in values.items():
            if not value:
                continue
            os.environ[key] = value
            os.environ[key.lower()] = value
    else:
        os.environ["NO_PROXY"] = config.no_proxy
        os.environ["no_proxy"] = config.no_proxy

    return config


def route_fingerprint(config: ProxyConfiguration | None = None) -> tuple[bool, str, str, str]:
    return (config or detect_proxy()).fingerprint()


def proxy_url_for(target_url: str = "https://kintara.gg") -> str:
    config = detect_proxy()
    if not config.enabled:
        return ""
    if str(target_url).lower().startswith(("https://", "wss://")):
        return config.https_proxy or config.all_proxy or config.http_proxy
    return config.http_proxy or config.all_proxy or config.https_proxy


def websocket_proxy_options(target_url: str = "wss://kintara.gg") -> dict[str, object]:
    config = detect_proxy()
    if not config.enabled:
        return {"http_no_proxy": ["*"]}

    proxy_url = (
        config.https_proxy
        if str(target_url).lower().startswith("wss://")
        else config.http_proxy
    )
    proxy_url = (
        proxy_url
        or config.all_proxy
        or config.http_proxy
        or config.https_proxy
    )
    if not proxy_url:
        return {"http_no_proxy": ["*"]}

    parsed = urllib.parse.urlparse(proxy_url)
    host = parsed.hostname
    if not host:
        return {"http_no_proxy": ["*"]}

    scheme = (parsed.scheme or "http").lower()
    proxy_type = {
        "socks": "socks5",
        "socks5h": "socks5h",
        "socks5": "socks5",
        "socks4a": "socks4a",
        "socks4": "socks4",
        "https": "http",
        "http": "http",
    }.get(scheme, "http")

    default_port = 1080 if proxy_type.startswith("socks") else 8080
    options: dict[str, object] = {
        "http_proxy_host": host,
        "http_proxy_port": int(parsed.port or default_port),
        "proxy_type": proxy_type,
    }
    if parsed.username:
        options["http_proxy_auth"] = (
            urllib.parse.unquote(parsed.username),
            urllib.parse.unquote(parsed.password or ""),
        )
    return options
