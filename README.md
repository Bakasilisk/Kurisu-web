# kurisu-web

A stats dashboard frontend for the Kurisu Discord bot. FastAPI +
server-rendered Jinja2 templates + Chart.js (vendored locally, no CDN). Talks to the bot's
`cogs/webapi.py` read-only HTTP API over localhost + an `X-API-Key` header — it never touches
`stats.db` directly and never holds a Discord bot token.

Access control: Discord OAuth2 login (`identify guilds` scopes). The bot owner sees every server
the bot is in; anyone else sees only servers where they're the owner, an Administrator, or have
Manage Server, intersected with the servers the bot is actually in. No public/anonymous tier in v1.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./scripts/fetch-vendor.sh   # vendors Chart.js into app/static/vendor/ (needs network once)
```

Fill in `.env`:

- `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` — from a Discord application's **OAuth2** tab
  (Developer Portal). Reuse the same application as the bot, or a separate one — either works,
  since this only uses OAuth2 client credentials, not a bot token.
- `PUBLIC_BASE_URL` — the public URL this site is served at (e.g.
  `https://kurisu.magicsociety.moe`). The OAuth redirect URI is always computed from this
  (`{PUBLIC_BASE_URL}/auth/callback`) — register that exact URL under the Discord application's
  **OAuth2 → Redirects**. `DISCORD_REDIRECT_URI` in `.env` is documentation of that same value,
  not read by the code.
- `SESSION_SECRET` — generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- `BOT_API_BASE` / `WEBAPI_KEY` — point at the bot's web API cog; `WEBAPI_KEY` must match one of
  the (comma-separated) keys in the bot's own `.env`.
- `WEB_BIND` — `host:port` this site binds to (read by `run.py`). Optional `WEB_FORWARDED_ALLOW_IPS`
  sets which proxy IPs' `X-Forwarded-*` headers are trusted (default `127.0.0.1`).

Session cookies are `Secure` (`https_only=True`), so the login flow requires real TLS — it won't
work end-to-end over a plain `http://` origin (e.g. local `http://127.0.0.1`) beyond checking that
pages render and redirects are constructed correctly.

## Run

```bash
python run.py
```

`run.py` binds the `host:port` from `WEB_BIND` in `.env` and always enables `--proxy-headers`
(trusting `WEB_FORWARDED_ALLOW_IPS`, default `127.0.0.1`) for running behind nginx — so the port
lives only in `.env`, not on the command line. The systemd unit below invokes it the same way.

## Deployment (nginx + systemd)

1. Copy `deploy/kurisu-web.service` to `/etc/systemd/system/kurisu-web.service`, fill in `youruser`
   and the two `/path/to/kurisu-web` placeholders, then:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now kurisu-web
   ```
2. Copy `deploy/nginx/kurisu.magicsociety.moe` to `/etc/nginx/sites-available/`, symlink it into
   `/etc/nginx/sites-enabled/`, then:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d kurisu.magicsociety.moe
   ```
3. The bot API stays on `127.0.0.1:8080`, not exposed by nginx — `deploy/nginx/api.kurisu.magicsociety.moe`
   is a commented sample for exposing it later if `kurisu-web` ever moves to a different host.

## Notes

- No new dependency for `.env` loading — `app/main.py` uses the same inline `key=val` parser as
  the bot's `bot.py`.
- The activity heatmap is a hand-rendered HTML table (color-scaled client-side from the bot API's
  `grid` JSON), not a Chart.js chart — Chart.js's core bundle has no matrix/heatmap chart type.
- Chart/heatmap colors follow a validated categorical + sequential palette (see
  `app/static/css/style.css`'s `:root` tokens); `app/static/js/dashboard.js` reads them at render
  time so both light and dark OS themes are covered.
