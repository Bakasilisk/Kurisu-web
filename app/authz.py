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


async def accessible_guilds(bot_api, user: dict, user_guilds: list[dict]) -> list[dict]:
    """Computed ONCE at login (see main.py's /auth/callback) — all bot guilds if
    this user is the bot owner, else the intersection with guilds where Discord
    reports them as owner/admin/manage-server. The result (small) is what gets
    cached in the session, not the raw user_guilds list (which can be large
    enough to blow the signed-cookie size limit for a user in 100+ servers)."""
    meta = await bot_api.meta()
    owner_id = meta.get("owner_id")
    bot_guilds = await bot_api.guilds()
    if owner_id and str(user.get("id")) == str(owner_id):
        return bot_guilds
    admin_ids = {g["id"] for g in user_guilds if is_admin_guild(g)}
    return [g for g in bot_guilds if g["id"] in admin_ids]


def check_guild_access(request, gid: str) -> bool:
    """Cheap per-request check against the accessible-guild-id set cached in
    the session at login (see accessible_guilds())."""
    if request.session.get("user") is None:
        return False
    return gid in request.session.get("accessible_guild_ids", [])
