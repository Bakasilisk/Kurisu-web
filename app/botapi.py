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
    """Thin wrapper around the bot's HTTP API — attaches X-API-Key, reuses one
    shared httpx.AsyncClient for the app's lifetime (created/closed in
    main.py's lifespan, not per-request). Mostly read-only, except the export
    endpoints (_post, export_start), which kick off a background job on the
    bot."""

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
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise BotAPIError("unavailable" if resp.status_code == 503 else str(e)) from e
        return resp.json()

    async def _post(self, path: str, json: dict) -> tuple[int, dict]:
        """POST helper for the export endpoints. Unlike _get, the caller (a
        route handler) needs the status code too: 400/403/409 are expected,
        meaningful responses meant to be passed through to the browser, not
        failures to swallow into a BotAPIError."""
        try:
            resp = await self._client.post(
                f"{self._base_url}{path}", json=json, headers=self._headers, timeout=10.0
            )
        except httpx.HTTPError as e:
            raise BotAPIError(str(e)) from e
        if resp.status_code == 404:
            raise BotAPIError("not_found")
        if resp.status_code == 401:
            raise BotAPIError("unauthorized")
        if resp.status_code == 503:
            raise BotAPIError("unavailable")
        return resp.status_code, resp.json()

    async def meta(self) -> dict:
        return await self._get("/api/meta")

    async def health(self) -> dict:
        return await self._get("/api/health")

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

    async def channel_detail(self, gid: str, cid: str, period: str = "month", limit: int | None = None) -> dict:
        return await self._get(f"/api/guilds/{gid}/channels/{cid}", _params(period=period, limit=limit))

    async def member(self, gid: str, uid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/members/{uid}")

    async def member_series(self, gid: str, uid: str, period: str = "year") -> dict:
        return await self._get(f"/api/guilds/{gid}/members/{uid}/series", _params(period=period))

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

    async def moderation(self, gid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/moderation")

    async def features(self, gid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/features")

    async def user_reminders(self, uid: str) -> dict:
        return await self._get(f"/api/users/{uid}/reminders")

    async def export_status(self, gid: str) -> dict:
        return await self._get(f"/api/guilds/{gid}/export")

    async def export_start(self, gid: str, requested_by: str, weeks: int | None) -> tuple[int, dict]:
        return await self._post(
            f"/api/guilds/{gid}/export", {"requested_by": requested_by, "weeks": weeks}
        )

    async def export_download(self, gid: str, requested_by: str) -> tuple[bytes, str | None]:
        """Not streamed (unlike a proxy that might sit in front of a much
        bigger upstream): the payload is bot-side capped bytes on the same
        host, so a plain buffered GET is simpler than send(stream=True) +
        StreamingResponse/BackgroundTask.

        `requested_by` is the downloader's user id; the bot re-checks their
        Manage Server right live and answers 403 if it's gone, which this
        surfaces as BotAPIError("forbidden")."""
        try:
            resp = await self._client.get(
                f"{self._base_url}/api/guilds/{gid}/export/download",
                params={"requested_by": requested_by},
                headers=self._headers,
                timeout=httpx.Timeout(10.0, read=120.0),
            )
        except httpx.HTTPError as e:
            raise BotAPIError(str(e)) from e
        if resp.status_code == 404:
            raise BotAPIError("not_found")
        if resp.status_code == 401:
            raise BotAPIError("unauthorized")
        if resp.status_code == 403:
            raise BotAPIError("forbidden")
        if resp.status_code == 503:
            raise BotAPIError("unavailable")
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise BotAPIError(str(e)) from e
        return resp.content, resp.headers.get("content-disposition")
