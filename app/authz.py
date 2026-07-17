ADMINISTRATOR = 0x8
MANAGE_GUILD = 0x20


def is_admin_guild(user_guild: dict) -> bool:
    """True if this /users/@me/guilds entry grants owner, Administrator, or Manage Server."""
    if user_guild.get("owner"):
        return True
    try:
        perms = int(user_guild.get("permissions", 0))
    except (TypeError, ValueError):
        return False
    return bool(perms & ADMINISTRATOR) or bool(perms & MANAGE_GUILD)


async def login_guild_sets(bot_api, user: dict, user_guilds: list[dict]) -> tuple[list[dict], list[dict], bool]:
    """Computed ONCE at login (see main.py's /auth/callback) from a single
    meta()+guilds() round-trip. Returns (accessible, member, is_owner):

    - `accessible` — guilds whose ADMIN dashboard this user may open: every bot
      guild if they're the bot owner, else the intersection with guilds where
      Discord reports them owner/admin/manage-server.
    - `member` — every guild the user simply belongs to that the bot is also in.
      Backs the harmless self-view (own economy/leveling), which any member may
      read regardless of admin rights.
    - `is_owner` — True iff this user is the bot owner (meta.owner_id). The bot
      owner may open every tier (admin *and* self-view) on every bot guild, even
      ones they don't personally belong to; see check_member_access().

    Both list results are small (bounded by the bot's guild count) — that's what
    gets cached in the session, not the raw user_guilds list (which can be large
    enough to blow the signed-cookie size limit for a user in 100+ servers)."""
    meta = await bot_api.meta()
    owner_id = meta.get("owner_id")
    bot_guilds = await bot_api.guilds()
    member_ids = {g["id"] for g in user_guilds}
    member = [g for g in bot_guilds if g["id"] in member_ids]
    is_owner = bool(owner_id) and str(user.get("id")) == str(owner_id)
    if is_owner:
        accessible = bot_guilds
    else:
        admin_ids = {g["id"] for g in user_guilds if is_admin_guild(g)}
        accessible = [g for g in bot_guilds if g["id"] in admin_ids]
    return accessible, member, is_owner


def check_guild_access(request, gid: str) -> bool:
    """Cheap per-request check for ADMIN-tier access against the accessible-guild-id
    set cached in the session at login (see login_guild_sets())."""
    if request.session.get("user") is None:
        return False
    return gid in request.session.get("accessible_guild_ids", [])


def check_member_access(request, gid: str) -> bool:
    """Cheap per-request check for the harmless self-view tier: is the logged-in
    user a member of this guild (member-guild set cached at login)?

    The bot owner is granted the self-view on every bot guild — bounded to the
    accessible set (which, for the owner, is exactly every bot guild) so a random
    non-bot guild id is still rejected. Their self-scoped record simply reads as
    zeros/"Unknown" on servers they aren't in (see API.md /members/{uid})."""
    if request.session.get("user") is None:
        return False
    if request.session.get("is_owner"):
        return gid in request.session.get("accessible_guild_ids", [])
    return gid in request.session.get("member_guild_ids", [])
