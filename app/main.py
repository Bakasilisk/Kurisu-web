import asyncio
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
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402
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


def _total_xp_for_level(level: int) -> int:  # mirrors Kurisu cogs/leveling.py curve
    return 25 * level * (level + 1)


def _human_bytes(n: int | None) -> str:
    """KB/MB rendering for the export card's server-rendered "done" state.
    export.js re-derives the same thing client-side for polled updates —
    small enough that duplicating it beats a round-trip for formatting."""
    if not n:
        return "0 B"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _level_progress(xp: int, level: int) -> dict:
    start = _total_xp_for_level(level)
    nxt = _total_xp_for_level(level + 1)
    span = nxt - start
    into = max(0, xp - start)
    return {"into": into, "span": span, "next_xp": nxt,
            "pct": round(100 * into / span, 1) if span else 0.0}


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
templates.env.filters["human_bytes"] = _human_bytes

_ERROR_TEXT = {
    403: ("You don't have access to this server",
          "Ask a server admin if you think you should."),
    404: ("Not found", "That page or member doesn't exist."),
    410: ("No export available",
          "No finished export — it may have expired or the bot restarted."),
    502: ("The bot is unreachable right now",
          "It may be restarting — try again in a moment."),
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # The six /guild/{gid}/data/* endpoints are fetched by dashboard.js via
    # Promise.all and must always get JSON back — an HTML error page here
    # would break every chart for anyone whose access lapsed mid-session.
    if "/data/" in request.url.path:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    # exc.detail is internal wording ("forbidden") — fine as an API payload,
    # too terse to show a signed-in user, so map it to a friendly pair.
    heading, message = _ERROR_TEXT.get(
        exc.status_code, ("Something went wrong", exc.detail)
    )
    return templates.TemplateResponse(
        request, "error.html",
        _page_ctx(request, heading=heading, message=message),
        status_code=exc.status_code,
    )


def _require_access(request: Request, gid: str) -> RedirectResponse | None:
    """Redirect to /login if not signed in; 403 if signed in but this guild
    isn't in the cached accessible set; None (proceed) otherwise."""
    if request.session.get("user") is None:
        return RedirectResponse("/login")
    if not authz.check_guild_access(request, gid):
        raise HTTPException(status_code=403, detail="forbidden")
    return None


def _require_member(request: Request, gid: str) -> RedirectResponse | None:
    """Self-view (harmless economy/leveling) gate: redirect to /login if not
    signed in; 403 if signed in but not a member of this guild; None otherwise.
    Unlike _require_access this needs no admin rights — any member qualifies."""
    if request.session.get("user") is None:
        return RedirectResponse("/login")
    if not authz.check_member_access(request, gid):
        raise HTTPException(status_code=403, detail="forbidden")
    return None


async def _guild_nav(bot_api, request: Request, gid: str) -> tuple[dict, list[dict]]:
    """Current guild + the switcher list, from ONE guilds() call. Replaces
    _guild_meta, which fetched this same list and discarded all but one entry.

    Each switcher entry also carries an `href`: /guild/{id} when the user has
    admin access to that guild, else /me/{id}. Without this, a switcher built
    from the plain guild list can't tell which tree to land a click in —
    picking wrong would link a member-only user into an admin route they'd
    get a 403 on, which the nav must never do (see plan's hard constraints)."""
    guilds = await bot_api.guilds()
    current = next((g for g in guilds if g["id"] == gid), {"id": gid, "name": "Unknown", "icon": None})
    admin_ids = set(request.session.get("accessible_guild_ids", []))
    member_ids = set(request.session.get("member_guild_ids", []))
    allowed = admin_ids | member_ids
    switcher = []
    for g in guilds:
        if g["id"] in allowed:
            entry = dict(g)
            entry["href"] = f"/guild/{g['id']}" if g["id"] in admin_ids else f"/me/{g['id']}"
            switcher.append(entry)
    return current, switcher


def _page_ctx(request: Request, *, gid: str | None = None, guild: dict | None = None,
              nav_active: str | None = None, switcher=(), **extra) -> dict:
    """Shared template context: session user, current guild, active tab, and
    which tabs this user may see. Both flags reuse authz's session-cached sets,
    so this adds no bot-API round-trip."""
    try:
        user = request.session.get("user")
    except Exception:
        # Defensive: request.session raises if SessionMiddleware isn't
        # installed on the request's scope for some reason — this mirrors
        # the same guard the exception handler used to have inline, since
        # that handler is now one of this helper's callers.
        user = None
    ctx = {
        "user": user,
        "guild": guild,
        "nav_active": nav_active,
        "switcher": switcher,
        "can_admin": authz.check_guild_access(request, gid) if gid else False,
        "can_member": authz.check_member_access(request, gid) if gid else False,
    }
    ctx.update(extra)
    return ctx


@app.get("/")
async def index(request: Request):
    user = request.session.get("user")
    if user is None:
        return templates.TemplateResponse(request, "login.html", _page_ctx(request))
    allowed_ids = set(request.session.get("accessible_guild_ids", []))
    bot_guilds = await request.app.state.bot_api.guilds()
    guilds = [g for g in bot_guilds if g["id"] in allowed_ids]
    # A user with no admin dashboards but at least one shared server lands on
    # their own economy/leveling self-view rather than an empty admin picker.
    if not guilds and request.session.get("member_guild_ids"):
        return RedirectResponse("/me")
    return templates.TemplateResponse(request, "picker.html", _page_ctx(request, guilds=guilds))


@app.get("/login")
async def login(request: Request):
    state = auth.new_state()
    request.session["oauth_state"] = state
    return RedirectResponse(auth.build_authorize_url(state, _redirect_uri()))


def _login_error(request: Request, message: str, status_code: int = 400) -> Response:
    return templates.TemplateResponse(
        request, "error.html", _page_ctx(request, message=message), status_code=status_code
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
        accessible, member, is_owner = await authz.login_guild_sets(request.app.state.bot_api, user, user_guilds)
    except BotAPIError as e:
        logger.warning("Bot API unavailable during login: %s", e)
        return _login_error(
            request,
            "The bot's data service is unavailable, so your servers couldn't be "
            "loaded. Please try again shortly.",
            status_code=502,
        )
    request.session["user"] = {"id": user["id"], "username": user.get("username"), "avatar": user.get("avatar")}
    request.session["accessible_guild_ids"] = [g["id"] for g in accessible]
    request.session["member_guild_ids"] = [g["id"] for g in member]
    request.session["is_owner"] = is_owner
    return RedirectResponse("/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/me")
async def my_stats(request: Request):
    """Self-view entry point. Auto-picks the single shared guild; shows a picker
    only when the user shares more than one server with the bot."""
    if request.session.get("user") is None:
        return RedirectResponse("/login")
    # The bot owner may open the self-view on every bot guild, so let them pick
    # from all of them (accessible == every bot guild for the owner), not just
    # the servers they personally belong to.
    if request.session.get("is_owner"):
        member_ids = request.session.get("accessible_guild_ids", [])
    else:
        member_ids = request.session.get("member_guild_ids", [])
    if not member_ids:
        # Logged in but shares no server with the bot — empty-state page.
        # Self-scoping: the user id comes from the signed session, NEVER from
        # the path/query — see my_stats_guild's "Self-scoping" comment below.
        uid = request.session["user"]["id"]
        try:
            reminders = (await request.app.state.bot_api.user_reminders(uid)).get("reminders", [])
        except BotAPIError:
            # The empty-state page must still render when the bot API is
            # down — the reminders card is just hidden (None, not []).
            reminders = None
        return templates.TemplateResponse(
            request, "me.html", _page_ctx(request, nav_active="me", reminders=reminders)
        )
    if len(member_ids) == 1:
        return RedirectResponse(f"/me/{member_ids[0]}")
    bot_guilds = await request.app.state.bot_api.guilds()
    member_set = set(member_ids)
    guilds = [g for g in bot_guilds if g["id"] in member_set]
    return templates.TemplateResponse(
        request, "me_picker.html", _page_ctx(request, guilds=guilds)
    )


@app.get("/me/{gid}")
async def my_stats_guild(request: Request, gid: str):
    redirect = _require_member(request, gid)
    if redirect:
        return redirect
    bot_api = request.app.state.bot_api
    # Self-scoping: the user id comes from the signed session, NEVER from the
    # path/query — a member can only ever read their own record, which is the
    # frontend-side enforcement the API's harmless tier assumes. The same uid
    # also feeds user_reminders below, whose self tier requires exactly this
    # session-derived (never path/query-derived) sourcing.
    uid = request.session["user"]["id"]
    try:
        profile = await bot_api.member(gid, uid)
        reminders = (await bot_api.user_reminders(uid)).get("reminders", [])
    except BotAPIError:
        raise HTTPException(status_code=502, detail="bot API unavailable")
    guild, switcher = await _guild_nav(bot_api, request, gid)
    level_progress = _level_progress(profile["leveling"]["xp"], profile["leveling"]["level"])
    return templates.TemplateResponse(
        request, "me.html",
        _page_ctx(
            request, gid=gid, guild=guild, nav_active="me", switcher=switcher,
            profile=profile, level_progress=level_progress, reminders=reminders,
        ),
    )


LEADERBOARD_LIMIT = 50


@app.get("/me/{gid}/leaderboards")
async def leaderboards(request: Request, gid: str):
    """Member-visible guild leaderboards from the API's harmless /leveling and
    /economy endpoints. Same member gate as the self-view — no admin rights."""
    redirect = _require_member(request, gid)
    if redirect:
        return redirect
    bot_api = request.app.state.bot_api
    uid = request.session["user"]["id"]
    try:
        leveling = await bot_api.leveling(gid, LEADERBOARD_LIMIT)
        economy = await bot_api.economy(gid, LEADERBOARD_LIMIT)
        # Self-scoped lookup so the "your standing" banner works even when the
        # member falls outside the top-LEADERBOARD_LIMIT list above.
        me = await bot_api.member(gid, uid)
    except BotAPIError:
        raise HTTPException(status_code=502, detail="bot API unavailable")
    guild, switcher = await _guild_nav(bot_api, request, gid)
    return templates.TemplateResponse(
        request, "leaderboards.html",
        _page_ctx(
            request, gid=gid, guild=guild, nav_active="leaderboards", switcher=switcher,
            leveling=leveling.get("entries", []),
            economy=economy.get("entries", []),
            me_id=uid,
            my_leveling_rank=me["leveling"]["rank"],
            my_economy_rank=me["economy"]["rank"],
            my_xp=me["leveling"]["xp"],
            my_bits=me["economy"]["bits"],
        ),
    )


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
    guild, switcher = await _guild_nav(bot_api, request, gid)
    return templates.TemplateResponse(
        request, "dashboard.html",
        _page_ctx(request, gid=gid, guild=guild, nav_active="overview", switcher=switcher, overview=overview),
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
    guild, switcher = await _guild_nav(bot_api, request, gid)
    level_progress = _level_progress(profile["leveling"]["xp"], profile["leveling"]["level"])
    return templates.TemplateResponse(
        request, "member.html",
        _page_ctx(
            request, gid=gid, guild=guild, nav_active="member", switcher=switcher,
            profile=profile, level_progress=level_progress,
        ),
    )


@app.get("/guild/{gid}/quietest")
async def quietest_page(request: Request, gid: str):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    bot_api = request.app.state.bot_api
    data = await bot_api.quietest(gid, limit=25)
    guild, switcher = await _guild_nav(bot_api, request, gid)
    return templates.TemplateResponse(
        request, "quietest.html",
        _page_ctx(request, gid=gid, guild=guild, nav_active="quietest", switcher=switcher, data=data),
    )


@app.get("/guild/{gid}/moderation")
async def moderation_page(request: Request, gid: str):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    bot_api = request.app.state.bot_api
    try:
        warnings, security, verification, palantir, moderation, features = await asyncio.gather(
            bot_api.warnings(gid, limit=100),
            bot_api.security(gid),
            bot_api.verification(gid),
            bot_api.palantir(gid),
            bot_api.moderation(gid),
            bot_api.features(gid),
        )
    except BotAPIError:
        raise HTTPException(status_code=502, detail="bot API unavailable")
    # Fetched separately from the gather above: an export-status hiccup (the
    # bot's Export cog not loaded, say) must not blank the rest of the
    # moderation page — the card just renders its own "unavailable" state.
    try:
        export_job = await bot_api.export_status(gid)
    except BotAPIError:
        export_job = {"state": "unavailable"}
    guild, switcher = await _guild_nav(bot_api, request, gid)
    return templates.TemplateResponse(
        request, "moderation.html",
        _page_ctx(
            request, gid=gid, guild=guild, nav_active="moderation", switcher=switcher,
            warnings=warnings.get("entries", []),
            security=security,
            verification=verification,
            palantir=palantir,
            moderation=moderation,
            features=features.get("cogs", []),
            export_job=export_job,
        ),
    )


@app.get("/guild/{gid}/data/export")
async def data_export_status(request: Request, gid: str):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    bot_api = request.app.state.bot_api
    try:
        job = await bot_api.export_status(gid)
    except BotAPIError as e:
        if str(e) == "unavailable":
            return JSONResponse({"state": "unavailable"})
        raise HTTPException(status_code=502, detail="bot API unavailable")
    return JSONResponse(job)


@app.post("/guild/{gid}/data/export")
async def data_export_start(request: Request, gid: str):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    # CSRF guard: this is the app's first POST route, so there's no prior
    # idiom to match here (every other mutation-shaped thing is a GET that
    # merely reads). A custom header forces a CORS preflight this app never
    # answers, so a bare cross-site <form> or fetch() can't attach it — that
    # stands in for a token, on top of the session cookie already being
    # SameSite=Lax + Secure.
    if request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(status_code=400, detail="bad request")
    # Self-scoping, same rule as everywhere else in this file: the requester
    # id is always the signed session's own, never taken from the body.
    uid = request.session["user"]["id"]
    bot_api = request.app.state.bot_api
    try:
        status, payload = await bot_api.export_start(gid, uid)
    except BotAPIError as e:
        if str(e) == "unavailable":
            return JSONResponse({"state": "unavailable"}, status_code=503)
        raise HTTPException(status_code=502, detail="bot API unavailable")
    logger.info("export start | guild=%s user=%s status=%s", gid, uid, status)
    return JSONResponse(payload, status_code=status)


@app.get("/guild/{gid}/export.csv")
async def export_csv(request: Request, gid: str):
    redirect = _require_access(request, gid)
    if redirect:
        return redirect
    uid = request.session["user"]["id"]
    bot_api = request.app.state.bot_api
    try:
        data, content_disposition = await bot_api.export_download(gid)
    except BotAPIError as e:
        if str(e) == "not_found":
            raise HTTPException(
                status_code=410,
                detail="No finished export — it may have expired or the bot restarted.",
            )
        raise HTTPException(status_code=502, detail="bot API unavailable")
    logger.info("export download | guild=%s user=%s", gid, uid)
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disposition or 'attachment; filename="export.csv"'},
    )
