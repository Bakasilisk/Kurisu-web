import os

import httpx

BOT_API_BASE = os.environ.get("BOT_API_BASE", "http://127.0.0.1:8080")
WEBAPI_KEY = os.environ.get("WEBAPI_KEY", "")


class BotAPIError(Exception):
    """Raised when the bot API call fails or returns a non-2xx status."""


def _params(**kwargs) -> dict:
    """Query params dict with unset (None) values dropped."""
    return {k: v for k, v in kwargs.items() if v is not None}


class BotAPIClient:
    """Thin wrapper around the bot's read-only HTTP API — attaches X-API-Key,
    reuses one shared httpx.AsyncClient for the app's lifetime (created/closed
    in main.py's lifespan, not per-request)."""

    def __init__(self, client: httpx.AsyncClient, base_url: str = BOT_API_BASE, api_key: str = WEBAPI_KEY):
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            resp = await self._client.get(
                f"{self._base_url}{path}", params=params, headers=self._headers, timeout=10.0
            )
        except httpx.HTTPError as e:
            raise BotAPIError(str(e)) from e
        if resp.status_code == 404:
            raise BotAPIError("not_found")
        if resp.status_code == 401:
            raise BotAPIError("unauthorized")
        resp.raise_for_status()
        return resp.json()

    async def meta(self) -> dict:
        return await self._get("/api/meta")

    async def guilds(self) -> list[dict]:
        return await self._get("/api/guilds")

    async def overview(self, gid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/overview")

    async def top(self, gid: str, period: str = "all", limit: int | None = None) -> dict:
        return await self._get(f"/api/guilds/{gid}/top", _params(period=period, limit=limit))

    async def channels(self, gid: str, period: str = "all", limit: int | None = None) -> dict:
        return await self._get(f"/api/guilds/{gid}/channels", _params(period=period, limit=limit))

    async def activity(self, gid: str, period: str = "month") -> dict:
        return await self._get(f"/api/guilds/{gid}/activity", {"period": period})

    async def voice(self, gid: str, period: str = "all", limit: int | None = None) -> dict:
        return await self._get(f"/api/guilds/{gid}/voice", _params(period=period, limit=limit))

    async def growth(self, gid: str, period: str = "month") -> dict:
        return await self._get(f"/api/guilds/{gid}/growth", {"period": period})

    async def member(self, gid: str, uid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/members/{uid}")

    async def quietest(self, gid: str, limit: int | None = None) -> dict:
        return await self._get(f"/api/guilds/{gid}/quietest", _params(limit=limit))

    async def leveling(self, gid: str, limit: int | None = None) -> dict:
        return await self._get(f"/api/guilds/{gid}/leveling", _params(limit=limit))

    async def economy(self, gid: str, limit: int | None = None) -> dict:
        return await self._get(f"/api/guilds/{gid}/economy", _params(limit=limit))

    async def warnings(self, gid: str, limit: int | None = None) -> dict:
        return await self._get(f"/api/guilds/{gid}/warnings", _params(limit=limit))

    async def security(self, gid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/security")

    async def verification(self, gid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/verification")

    async def palantir(self, gid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/palantir")
