# kurisu-web — working notes

FastAPI + server-rendered Jinja2 + Chart.js (vendored, no CDN). Reads the bot's
HTTP API over localhost; never touches `stats.db` and never holds a bot token.
See `README.md` for setup, routes and the access-control tiers.

These are the things that aren't obvious from reading the code, and that are
easy to get wrong.

## Looking at the site

Every page is behind Discord OAuth *and* a live bot API, so you cannot just
open one. Use the preview harness instead — it renders all 11 pages with
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

This dev machine is **not** the server. `scripts/finish-deploy.sh` runs on the
server host, and it restarts but does not pull:

```bash
git pull origin main
./scripts/finish-deploy.sh    # prompts for sudo to restart kurisu-web
```

Safe to re-run; it asks before pruning merged branches, and prints a rollback
command if the restart fails.

## Shipping

Merge into `main` locally and push — no PRs. Fetch first; `origin/main` moves
independently. No Claude attribution in commit messages.
