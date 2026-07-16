import logging
import os

# Simple .env loader, no python-dotenv dependency — mirrors Kurisu bot.py's
# own inline parser. Must run before any `app.*` import below, since those
# modules read their config (e.g. DISCORD_CLIENT_ID) from os.environ at
# import time as module-level constants.
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())
                except ValueError:
                    pass

from contextlib import asynccontextmanager  # noqa: E402

import httpx  # noqa: E402
from fastapi import FastAPI, HTTPException, Request, Response  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from app import auth, authz  # noqa: E402
from app.botapi import BotAPIClient, BotAPIError  # noqa: E402

logger = logging.getLogger("kurisu-web")

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8081")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
REDIRECT_PATH = "/auth/callback"

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be set (see .env.example)")


def _redirect_uri() -> str:
    # Always derived from PUBLIC_BASE_URL, never read from DISCORD_REDIRECT_URI
    # (that env var is documentation for what to register in Discord's portal —
    # it must equal this same computed value).
    return PUBLIC_BASE_URL.rstrip("/") + REDIRECT_PATH


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = httpx.AsyncClient()
    app.state.bot_api = BotAPIClient(client)
    yield
    await client.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=True, same_site="lax")

BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def _require_access(request: Request, gid: str) -> RedirectResponse | None:
    """Redirect to /login if not signed in; 403 if signed in but this guild
    isn't in the cached accessible set; None (proceed) otherwise."""
    if request.session.get("user") is None:
        return RedirectResponse("/login")
    if not authz.check_guild_access(request, gid):
        raise HTTPException(status_code=403, detail="forbidden")
    return None


async def _guild_meta(bot_api, gid: str) -> dict:
    guilds = await bot_api.guilds()
    return next((g for g in guilds if g["id"] == gid), {"id": gid, "name": "Unknown", "icon": None})


@app.get("/")
async def index(request: Request):
    user = request.session.get("user")
    if user is None:
        return templates.TemplateResponse(request, "login.html")
    allowed_ids = set(request.session.get("accessible_guild_ids", []))
    bot_guilds = await request.app.state.bot_api.guilds()
    guilds = [g for g in bot_guilds if g["id"] in allowed_ids]
    return templates.TemplateResponse(request, "picker.html", {"user": user, "guilds": guilds})


@app.get("/login")
async def login(request: Request):
    state = auth.new_state()
    request.session["oauth_state"] = state
    return RedirectResponse(auth.build_authorize_url(state, _redirect_uri()))


def _login_error(request: Request, message: str, status_code: int = 400) -> Response:
    return templates.TemplateResponse(
        request, "error.html", {"message": message}, status_code=status_code
    )


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str | None = None, state: str | None = None):
    expected = request.session.pop("oauth_state", None)
    if not code or not state or state != expected:
        # Usually a stale/lost session cookie (e.g. serving over plain HTTP with
        # https_only cookies, or a bookmarked callback URL) rather than a real error.
        return _login_error(
            request,
            "Your login session expired or was lost before completing. Please try again.",
        )
    # The Discord OAuth exchange and the bot-API lookup can each fail for reasons
    # outside our control (bad client credentials, redirect_uri mismatch, the bot
    # API being down). Surface a readable reason instead of a bare 500.
    try:
        token = await auth.exchange_code(code, _redirect_uri())
        access_token = token["access_token"]
        user = await auth.fetch_user(access_token)
        user_guilds = await auth.fetch_user_guilds(access_token)
    except httpx.HTTPStatusError as e:
        logger.warning("Discord OAuth exchange failed: %s", e)
        return _login_error(
            request,
            "Discord rejected the sign-in. This usually means the app's OAuth "
            "credentials or redirect URL are misconfigured.",
            status_code=502,
        )
    except httpx.HTTPError as e:
        logger.warning("Could not reach Discord during login: %s", e)
        return _login_error(request, "Couldn't reach Discord. Please try again.", status_code=502)
    try:
        allowed = await authz.accessible_guilds(request.app.state.bot_api, user, user_guilds)
    except BotAPIError as e:
        logger.warning("Bot API unavailable during login: %s", e)
        return _login_error(
            request,
            "The bot's data service is unavailable, so your servers couldn't be "
            "loaded. Please try again shortly.",
            status_code=502,
        )
    request.session["user"] = {"id": user["id"], "username": user.get("username"), "avatar": user.get("avatar")}
    request.session["accessible_guild_ids"] = [g["id"] for g in allowed]
    return RedirectResponse("/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/guild/{gid}")
async def guild_dashboard(request: Request, gid: str):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    bot_api = request.app.state.bot_api
    try:
        overview = await bot_api.overview(gid)
    except BotAPIError:
        raise HTTPException(status_code=502, detail="bot API unavailable")
    guild = await _guild_meta(bot_api, gid)
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"user": request.session.get("user"), "guild": guild, "overview": overview},
    )


@app.get("/guild/{gid}/data/top")
async def data_top(request: Request, gid: str, period: str = "all", limit: int | None = None):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    return JSONResponse(await request.app.state.bot_api.top(gid, period, limit))


@app.get("/guild/{gid}/data/channels")
async def data_channels(request: Request, gid: str, period: str = "all", limit: int | None = None):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    return JSONResponse(await request.app.state.bot_api.channels(gid, period, limit))


@app.get("/guild/{gid}/data/activity")
async def data_activity(request: Request, gid: str, period: str = "month"):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    return JSONResponse(await request.app.state.bot_api.activity(gid, period))


@app.get("/guild/{gid}/data/voice")
async def data_voice(request: Request, gid: str, period: str = "all", limit: int | None = None):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    return JSONResponse(await request.app.state.bot_api.voice(gid, period, limit))


@app.get("/guild/{gid}/data/growth")
async def data_growth(request: Request, gid: str, period: str = "month"):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    return JSONResponse(await request.app.state.bot_api.growth(gid, period))


@app.get("/guild/{gid}/data/quietest")
async def data_quietest(request: Request, gid: str, limit: int | None = None):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    return JSONResponse(await request.app.state.bot_api.quietest(gid, limit))


@app.get("/guild/{gid}/member/{uid}")
async def member_profile(request: Request, gid: str, uid: str):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    bot_api = request.app.state.bot_api
    try:
        profile = await bot_api.member(gid, uid)
    except BotAPIError:
        raise HTTPException(status_code=404, detail="member not found")
    guild = await _guild_meta(bot_api, gid)
    return templates.TemplateResponse(
        request, "member.html",
        {"user": request.session.get("user"), "guild": guild, "profile": profile},
    )


@app.get("/guild/{gid}/quietest")
async def quietest_page(request: Request, gid: str):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    bot_api = request.app.state.bot_api
    data = await bot_api.quietest(gid, limit=25)
    guild = await _guild_meta(bot_api, gid)
    return templates.TemplateResponse(
        request, "quietest.html",
        {"user": request.session.get("user"), "guild": guild, "data": data},
    )
