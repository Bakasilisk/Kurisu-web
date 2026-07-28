#!/usr/bin/env python3
"""Render every Jinja template with fabricated data, so the design can be
looked at without a Discord login or a running bot API.

Every real page is behind OAuth *and* the bot's HTTP API, which means the only
way to see a CSS change used to be to deploy it. This renders the templates
straight through Jinja with fake context instead, writes them to .preview/, and
optionally serves them and drives headless Chrome for screenshots.

    python scripts/preview.py                 # render to .preview/
    python scripts/preview.py --serve         # ...and serve on :8199
    python scripts/preview.py --shots         # ...and write PNGs to .preview/shots/
    python scripts/preview.py --serve --open  # ...and open a browser

The data below is deliberately fictional (Steins;Gate lab members, round
numbers) so a screenshot of this can never be mistaken for real server stats.
It also leans on the awkward cases on purpose: top-three medals, the "this is
you" row, all three badge variants, the XP progress bar, labels long enough to
wrap, and the empty-state branches.
"""
from __future__ import annotations

import argparse
import http.server
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import webbrowser

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:  # pragma: no cover
    sys.exit("jinja2 missing — run: .venv/bin/python scripts/preview.py")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(REPO, "app", "templates")
STATIC = os.path.join(REPO, "app", "static")
OUT = os.path.join(REPO, ".preview")
SHOTS = os.path.join(OUT, "shots")
PORT = 8199

# Widths to screenshot at: desktop, and a phone narrow enough to trip the
# 640px breakpoint.
VIEWPORTS = [("wide", 1440, 1600), ("mobile", 390, 1400)]
THEMES = ["light", "dark"]

CHROME_CANDIDATES = [
    "google-chrome", "chromium", "chromium-browser", "google-chrome-stable",
]


class Ctx(dict):
    """dict that also answers attribute access, so templates can use `a.b.c`
    the same way they do with the bot API's parsed JSON."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def c(**kwargs) -> Ctx:
    return Ctx(**kwargs)


def user(uid: int, name: str) -> Ctx:
    return c(id=str(uid), name=name, avatar=None)


NAMES = [
    "Okabe Rintarou", "Makise Kurisu", "Shiina Mayuri", "Hashida Itaru",
    "Amane Suzuha", "Urushibara Ruka", "Feyris NyanNyan", "Akiha Rumiho",
    "Kiryu Moeka", "Tennouji Nae",
]

GUILD = c(id="123", name="Steins;Gate Lab Members", icon=None)
VIEWER = c(username="zetsu", id="1")
SWITCHER = [
    c(id="123", name="Steins;Gate Lab Members", icon=None, href="/guild/123"),
    c(id="456", name="Future Gadget Laboratory", icon=None, href="/guild/456"),
]

PROFILE = c(
    user=user(1, "Makise Kurisu"),
    leveling=c(level=42, xp=182_400, rank=2),
    economy=c(bits=98_320, rank=3, streak=17),
    total_messages=48_213, total_words=612_004, active_days=311,
    first_day="2023-04-11", server_rank=2, pct_of_server=12.4,
    words_per_msg=12.7, busiest_hour=21, voice_seconds=184_000,
    reactions_given=2044, reactions_received=3120,
    top_channels=[
        c(channel=c(name="general"), count=18_204),
        c(channel=c(name="lab-notes"), count=9_112),
        c(channel=c(name="time-travel-theory"), count=4_003),
    ],
)


def shell(**overrides) -> dict:
    """Context every page inherits from base.html / _nav.html."""
    ctx = dict(
        user=VIEWER, guild=GUILD, switcher=SWITCHER,
        nav_active=None, can_admin=True, can_member=True,
    )
    ctx.update(overrides)
    return ctx


def pages() -> dict[str, dict]:
    leveling = [
        c(user=user(i, name), level=60 - i * 4, xp=1_204_553 // (i + 1))
        for i, name in enumerate(NAMES)
    ]
    economy = [
        c(user=user(i, name), bits=10_210_553 // (i + 1), streak=(30 - i * 3) or None)
        for i, name in enumerate(NAMES)
    ]
    return {
        "login.html": dict(user=None, guild=None, switcher=None),
        "error.html": dict(
            user=None, guild=None, switcher=None, heading="Access denied",
            message="You don't have permission to view this server.",
        ),
        "picker.html": shell(guild=None, guilds=[
            c(id="123", name="Steins;Gate Lab Members", icon=None),
            c(id="456", name="Future Gadget Laboratory", icon=None),
            c(id="789", name="A deliberately long server name that wraps", icon=None),
        ]),
        "me_picker.html": shell(guild=None, guilds=[
            c(id="123", name="Steins;Gate Lab Members", icon=None),
            c(id="456", name="Future Gadget Laboratory", icon=None),
        ]),
        "dashboard.html": shell(nav_active="overview", overview=c(
            total_messages=1_204_553, active_members_30d=184,
            trend=c(text="Rising", pct=12.4, recent=48_100, prior=42_800),
            total_words=10_210_553, avg_day=1_204.7, reactions=88_412,
            voice_seconds=1_840_000, first_day="2023-04-11",
        )),
        "leaderboards.html": shell(
            nav_active="leaderboards", leveling=leveling, economy=economy,
            me_id="1", my_leveling_rank=2, my_xp=182_400,
            my_economy_rank=3, my_bits=98_320,
        ),
        # Populated self-view: medals, progress bar, reminders table.
        "me.html": shell(nav_active="me", profile=PROFILE, level_progress=c(
            pct=64, into=12_800, span=20_000,
        ), reminders=[
            c(fire_at="2026-08-01T09:30:00", guild=GUILD,
              channel=c(name="general"), text="Check the microwave"),
        ]),
        # Empty branches of the same template — the states that only show up
        # for a brand-new user, and so are the easiest to leave broken.
        "me_empty.html": ("me.html", shell(
            nav_active="me", profile=None, level_progress=None, reminders=[],
        )),
        "member.html": shell(profile=PROFILE, level_progress=c(
            pct=64, into=12_800, span=20_000,
        )),
        "quietest.html": shell(nav_active="quietest", data=c(entries=[
            c(user=user(i, name), count=i * 3) for i, name in enumerate(NAMES[:6])
        ])),
        "moderation.html": shell(
            nav_active="moderation",
            warnings=[c(user=user(9, "Kiryu Moeka"), count=2, warnings=[
                c(reason="Spam in #general", moderator=user(1, "Okabe"),
                  timestamp="2026-07-02"),
                c(reason="Repeated off-topic links", moderator=None,
                  timestamp="2026-07-14"),
            ])],
            moderation=c(mod_log_channel=c(name="mod-log"),
                         locked_channels=[c(name="general"), c(name="lounge")]),
            security=c(mode="active",
                       lockdown=c(active=False, stay_locked=False, remaining_seconds=0),
                       exempt_roles=3, exempt_users=1, protected_roles=2,
                       log_channel=c(name="security-log")),
            verification=c(granter_role=c(name="Verifier"), target_role=c(name="Member"),
                           welcome_channel=c(name="welcome"), welcome_enabled=True),
            palantir=c(log_channel=c(name="palantir"), archive_attachments=True,
                       muted_categories=["voice"], cached_messages=402_113),
            # All three badge variants: on / off / globally off.
            features=[c(name=name, enabled=enabled, globally_disabled=gone)
                      for name, enabled, gone in [
                          ("leveling", True, False), ("economy", True, False),
                          ("moderation", True, False), ("palantir", False, False),
                          ("music", False, True),
                      ]],
        ),
    }


# Stubs the data endpoints so the dashboard draws real Chart.js charts and a
# real heatmap from fake payloads, instead of five "couldn't load" boxes.
FETCH_STUB = """
<script>
(function () {
  const seq = (n, f) => Array.from({length: n}, (_, i) => f(i));
  const names = __NAMES__;
  const channels = ["general","lab-notes","voice-chat","memes","theory","links","bot-spam","intros"];
  const routes = {
    top: {entries: seq(10, i => ({user: {name: names[i]}, count: 4000 - i * 320}))},
    channels: {entries: seq(8, i => ({channel: {name: channels[i]}, count: 9000 - i * 900}))},
    voice: {entries: seq(10, i => ({user: {name: names[i]}, seconds: (60 - i * 5) * 3600}))},
    growth: {joins: 240, leaves: 96, net: 144, messages: 48100},
    activity: {
      grid: seq(7, wd => seq(24, h =>
        Math.round(Math.max(0, Math.sin((h - 6) / 24 * Math.PI) * 100 * (1 + wd / 8))) + (h * wd) % 17)),
      weekday_labels: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
      total: 48100, peak_weekday: 5, peak_hour: 21
    }
  };
  window.fetch = (url) => {
    const key = String(url).split("/data/")[1].split("?")[0];
    return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve(routes[key])});
  };
})();
</script>
"""


def render(env: Environment) -> list[str]:
    """Render each page, plus an explicit light and dark variant of it. Forcing
    data-theme on <html> means both themes are checkable without touching the
    OS setting — and it exercises the same attribute the toggle writes."""
    written = []
    stub = FETCH_STUB.replace("__NAMES__", str(NAMES).replace("'", '"'))

    for out_name, spec in pages().items():
        template_name, ctx = spec if isinstance(spec, tuple) else (out_name, spec)
        html = env.get_template(template_name).render(**ctx)
        if template_name == "dashboard.html":
            html = html.replace("</head>", stub + "</head>")

        base = out_name[:-5]  # strip .html
        for theme in [None, *THEMES]:
            if theme is None:
                body, path = html, f"{base}.html"
            else:
                body = html.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">')
                path = f"{base}__{theme}.html"
            with open(os.path.join(OUT, path), "w", encoding="utf-8") as fh:
                fh.write(body)
            written.append(path)
    return written


def write_index(names: list[str]) -> None:
    links = "\n".join(
        f'<li><a href="{n}">{n}</a></li>' for n in sorted(names) if "__" not in n
    )
    themed = "\n".join(
        f'<li><a href="{n}">{n}</a></li>' for n in sorted(names) if "__" in n
    )
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(
            "<!doctype html><meta charset=utf-8><title>kurisu-web preview</title>"
            '<link rel="stylesheet" href="static/css/style.css">'
            "<main><h1>Preview</h1>"
            "<p class=standing>Fabricated data. Not real server statistics.</p>"
            f"<h2>Pages (follows your OS theme)</h2><ul class=stat-list>{links}</ul>"
            f"<h2>Forced theme</h2><ul class=stat-list>{themed}</ul></main>"
        )


def find_chrome() -> str | None:
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def serve_background() -> socketserver.TCPServer:
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=OUT, **kw)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def screenshot(chrome: str) -> None:
    os.makedirs(SHOTS, exist_ok=True)
    # Only the pages worth eyeballing — every template is still rendered.
    for page in ["dashboard", "leaderboards", "me", "moderation", "picker", "login"]:
        for theme in THEMES:
            for label, width, height in VIEWPORTS:
                if label == "mobile" and page not in ("dashboard", "me"):
                    continue
                out = os.path.join(SHOTS, f"{page}-{theme}-{label}.png")
                subprocess.run([
                    chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--virtual-time-budget=4000", f"--window-size={width},{height}",
                    f"--screenshot={out}",
                    f"http://127.0.0.1:{PORT}/{page}__{theme}.html",
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                print(f"  shot {os.path.relpath(out, REPO)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve", action="store_true", help=f"serve .preview/ on :{PORT}")
    ap.add_argument("--shots", action="store_true", help="write screenshots (implies --serve)")
    ap.add_argument("--open", action="store_true", help="open a browser at the index")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    # Symlink rather than copy so edits to the real CSS show up on reload.
    link = os.path.join(OUT, "static")
    if os.path.islink(link):
        os.remove(link)
    elif os.path.isdir(link):
        shutil.rmtree(link)
    os.symlink(STATIC, link)

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    written = render(env)
    write_index(written)
    print(f"rendered {len(written)} files to {os.path.relpath(OUT, REPO)}/")

    if not (args.serve or args.shots or args.open):
        return 0

    httpd = serve_background()
    print(f"serving http://127.0.0.1:{PORT}/")

    if args.shots:
        chrome = find_chrome()
        if not chrome:
            print("no chrome/chromium found — skipping screenshots", file=sys.stderr)
        else:
            screenshot(chrome)

    if args.open:
        webbrowser.open(f"http://127.0.0.1:{PORT}/")

    if args.serve or args.open:
        print("ctrl-c to stop")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print()
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
