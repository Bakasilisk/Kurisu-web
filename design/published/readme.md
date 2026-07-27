# Kurisu-web

The design system of the Kurisu-web dashboard — a Flask app serving Discord
server statistics, leaderboards and moderation history.

This project is **published from the app, not authored here.** Every preview
links `styles.css`, which is a byte-for-byte mirror of
`app/static/css/style.css` in the repo. What you see on these cards is what
the site actually renders, not a re-drawing of it.

## Reading order

- **Foundations → Color** — both schemes side by side, plus the token/JS
  contract that constrains them.
- **Foundations → Typography** — Inter Variable, the heading treatments, and
  why every numeral is tabular.
- **Foundations → Layout & scales** — spacing, radius, elevation, the page
  column and its breakpoints.
- **Components** — buttons and badges, cards and panels, navigation, tables
  and lists, controls and progress, loading and error states.

## Two things that constrain changes

**Light and dark are independently chosen instances.** Not a filter flip, not
a lightness inversion. A new color token needs two values picked deliberately;
the light/dark pair for brand teal differs because `#00A5BD` measures 5.9:1 on
the dark surface and 2.9:1 on the light one.

**Some token names are a runtime API.** `app/static/js/dashboard.js` reads
`--text-secondary`, `--border`, `--series-1`, `--series-6`, `--good`,
`--critical` and `--seq-0`…`--seq-5` through `getComputedStyle` when it draws
charts. Renaming one breaks the dashboard silently. `--seq-*` must stay 6-digit
hex literals — the JS parses them with `parseInt(hex.replace("#",""), 16)`, so
`rgb()`, `oklch()`, `color-mix()` and 3-digit shorthand all break the heatmap.
`--series-1` must stay a flat color, because Chart.js takes it as a fill string.

## One deviation from production

The app self-hosts Inter Variable from `/static/vendor/inter-var.woff2` and
makes no external requests at runtime. That file isn't in this project, so the
`@font-face` rule is dropped and these previews render on the system stack —
the app's own declared fallback. Weights and metrics shift slightly here.
Nothing else differs.
