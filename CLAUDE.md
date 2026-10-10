# kurisu-web — working notes

FastAPI + server-rendered Jinja2 + Chart.js (vendored, no CDN). Reads the bot's
HTTP API over localhost; never touches `stats.db` and never holds a bot token.
See `README.md` for setup, routes and the access-control tiers.

These are the things that aren't obvious from reading the code, and that are
easy to get wrong.

## Git workflow
- Never commit or push without showing me the diff first and getting explicit approval. This applies to subagents too: tell implementer agents to stop before committing and report back so I can review.
- Don't push straight to main unless I've asked for it.

## Looking at the site

Every page is behind Discord OAuth *and* a live bot API, so you cannot just
open one. Use the preview harness instead — it renders all 15 pages with
fabricated data, no login and no bot required:

```bash
.venv/bin/python scripts/preview.py --serve     # http://127.0.0.1:8199/
.venv/bin/python scripts/preview.py --shots     # PNGs in .preview/shots/
```

Each page is emitted three times: following the OS theme, and with
`data-theme="light"` / `"dark"` forced. Never conclude a page can only be
checked by deploying, and never ship a visual change without looking at it.

The fixture data is deliberately fictional. Keep it that way — a screenshot of
this must never be mistakable for real server statistics.

`moderation.html` has a running variant (`moderation_export_running.html`,
Start button disabled, no Download link) because the export card has two
states worth eyeballing and only one of them is the template's default
fixture — `--shots` covers both. `health.html` likewise has
`health_degraded.html` (a failed cog with its error, no recorded start time,
no heartbeat), since the null branches are what you'd see right after a
deploy.

The `-mobile` shots are not a true 390px render: headless Chrome won't make
a window narrower than 500px, runs the page's JS at that width, and then
crops. Chart.js sizes its canvases during that window, so every chart box
looks like it overflows the right edge — on the dashboard as much as anywhere
else. That's the harness, not the CSS. To check a chart page at real phone
width, load it in a `<iframe width=390>` on a wider window instead.

## Message export

The moderation page's export card is `app/static/js/export.js`
(`initExport(gid)`), not `dashboard.js` — that's the Chart.js machinery for
the chart pages (overview, channel drilldown, and the activity-over-time
chart on the member and self-view profiles) and isn't loaded here. (Each of
those chart pages has exactly one `runBoxes` runner: one period select drives
one list of boxes, because `currentBoxes` is what the `themechange` re-render
walks.) The export card starts a background job on the bot
(`POST /guild/{id}/data/export`) and polls it (`GET`, every 3s while
running), then serves the finished CSV at `GET /guild/{id}/export.csv`.

`POST /guild/{id}/data/export` is the app's first `POST` route — everything
else is a GET, including the "start" naming of that action. It's guarded by a
`X-Requested-With: fetch` header check instead of a CSRF token: a custom
header forces a CORS preflight this app never answers, so a bare cross-site
`<form>` or blind `fetch()` can't attach it. That's on top of the session
cookie already being `SameSite=Lax` + `Secure`, not instead of it.

`GET /guild/{id}/export.csv` passes the signed session's user id (never one
from the URL) to the bot as `requested_by`; the bot re-checks that user's
Manage Server right **live** and 403s if it's gone, so a demoted admin can't
download message content on the strength of the login-time rights cached in
the session. Sessions are capped at 1 day (`SESSION_MAX_AGE`, vs Starlette's
14-day default) to bound how stale that cached snapshot can get everywhere
else, and how long a stolen cookie lives (logout only clears the client copy).
Starlette re-signs the cookie with a fresh `Max-Age` on any session write, so
`/login` and `/auth/callback` `clear()` the session before writing to it —
keep it that way, and don't write to a logged-in session anywhere else, or
the cap becomes refreshable.

The POST body now also carries an optional `weeks` field (from the dropdown
next to "Start export"), forwarded to the bot unvalidated — same
pass-through division of labor as `period`/`limit` elsewhere — the 1–12 bound
lives solely in the bot, which clamps and echoes the effective value back as
`weeks` in the job JSON.

## Design workflow

`design/` is a drop zone, not something the app serves. Full conventions are in
`design/README.md`. The part that matters:

- **Check `design/incoming/` before starting design work.** Screenshots,
  exports and "make it look like this" references get dropped there for
  translation into `app/static/css/style.css` and `app/templates/`. Files stay
  after translation so there's a trail back to the original.
- `design/published/` mirrors the **Kurisu-web** Claude Design project
  (`eab088ba-ab1a-4db0-82a5-ca302d54249d`), pushed with `DesignSync`. It is
  published *from* this repo, not authored there — correct the local files
  first, then upload.

### The mirror invariant

`design/published/styles.css` is a **byte-for-byte copy** of
`app/static/css/style.css`, and `design/published/readme.md` says so. Changing
the app CSS means re-copying it and re-pushing, or the component previews stop
showing what the site actually renders:

```bash
cp app/static/css/style.css design/published/styles.css
diff app/static/css/style.css design/published/styles.css   # must be empty
```

The prose in `design/published/{components,foundations}/*.html` describes
specific values (radii, shadows, hover targets). If you change one, fix the
description in the same commit — stale design docs are worse than none.

## The chart token contract

`app/static/js/dashboard.js` reads CSS custom properties through
`getComputedStyle` at render time. Breaking this produces **no console error** —
just wrong colours, or an invisible heatmap.

- `--seq-0` … `--seq-5` must stay **6-digit hex literals**. `hexToRgb()` does
  `parseInt(hex.replace("#",""), 16)`, so `rgb()`, `oklch()`, `color-mix()`,
  3-digit shorthand and `light-dark()` all yield `NaN`.
- `--series-1`, `--series-6`, `--good`, `--critical` must stay plain colours,
  never gradients — Chart.js takes them directly as fill strings.
- `--text-secondary` and `--border` are the axis and grid colours.

Every *other* token is CSS-only and free to use `color-mix()` or a gradient.

This constraint is why the dark palette is **declared twice** in `style.css` —
once under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`
and once under `:root[data-theme="dark"]`, so an explicit toggle beats the OS.
`light-dark()` would remove the duplication but isn't resolved inside custom
properties; dropping the media query would leave the JS-free login page
light-only. Keep the two blocks in sync.

## Theming

`static/js/theme.js` wires the toggle, but the *boot* half is an inline
blocking `<script>` in `base.html`'s `<head>`. It has to stay inline and before
the stylesheet — deferred, the page paints in the OS theme and visibly flips.

Anything that reads a token at render time must listen for the `themechange`
event, because it won't re-read on its own. `dashboard.js` caches each box's
last payload and re-renders from cache on that event.

Bump the `?v=` on `style.css` in `base.html` when the CSS changes.

## Deploying

**This checkout is the server.** `kurisu-web.service` runs
`.venv/bin/python run.py` with `WorkingDirectory` pointing at this working
tree, so an edit here goes live the moment the service restarts — there is no
separate deploy target to copy to. The bot it reads over localhost is the
sibling checkout `../Kurisu`, running as `kurisu.service` on the same host.

If you are ever unsure whether the host you're on is the server, ask it:

```bash
systemctl show kurisu-web -p WorkingDirectory   # empty/absent => not the server
```

`scripts/finish-deploy.sh` is the whole flow, in this order: refuse to run on a
dirty tree → sync the venv to `requirements.txt` → restart the service →
**then** push to origin. So origin only ever receives a commit that has already
come back up here.

```bash
./scripts/finish-deploy.sh    # prompts for sudo to restart kurisu-web
```

It restarts but never pulls. Commits authored on another machine need a
`git pull origin main` first; commits authored here don't — the script pushes
them for you.

Safe to re-run; it asks before pruning merged branches, and prints a rollback
command if the restart fails.

## Shipping

Merge into `main` locally and push — no PRs. Fetch first; `origin/main` moves
independently. No Claude attribution in commit messages.
