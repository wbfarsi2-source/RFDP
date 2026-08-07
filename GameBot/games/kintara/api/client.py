from __future__ import annotations

from typing import Any

import httpx


class KintaraClient:
    def __init__(self, base_url: str, cookie: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie = cookie

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json,text/plain,*/*",
            "Cookie": self.cookie,
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/play",
            "User-Agent": "GameBotPlatform/0.2",
        }

    async def get_json(self, path: str) -> tuple[int, dict[str, Any]]:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            response = await client.get(f"{self.base_url}{path}", headers=self.headers)
            try:
                data = response.json()
            except Exception:
                data = {}
            return response.status_code, data if isinstance(data, dict) else {}

    async def auth_me(self) -> tuple[int, dict[str, Any]]:
        return await self.get_json("/api/auth/me")
