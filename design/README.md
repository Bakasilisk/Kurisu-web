# design/

Drop zone for design work headed into `Kurisu-web`. Nothing here is served by
Flask — it's source material that gets translated into `app/static/css/style.css`
and `app/templates/`.

## Where things go

| Folder        | What belongs there                                                        |
|---------------|---------------------------------------------------------------------------|
| `incoming/`   | Raw, unsorted drops. Screenshots, exports, HTML from Claude Design, links in a `.md`, anything. No naming rules — just dump it. |
| `tokens/`     | Colors, type scale, spacing, radii, shadows. Whatever format (JSON, CSS, notes) — these become `:root` custom properties in `style.css`. |
| `components/` | Standalone component HTML/CSS previews — one file per component. These become Jinja partials in `app/templates/`. |
| `reference/`  | Inspiration and "make it look like this" material. Never translated directly, just consulted. |

## Workflow

1. You put files in `incoming/` (or straight into the right folder if obvious).
2. Tell me what to do with them — "wire the new button styles in", "apply
   these tokens", etc.
3. I sort, translate into the real app, and note what came from where.

Files stay here after translation so there's a trail back to the original.

## Claude Design projects

If the source is a `claude.ai/design` project, I can pull component files
directly with the DesignSync tool instead of you exporting by hand — just name
the component. Local files in `components/` can also be pushed up to a design
system project the same way.

## Conventions

- Prefix a file with `_` to mark it as done/archived rather than deleting it.
- Component files: name them after the component (`button.html`, `card.html`),
  not after the export (`Frame 12 copy.html`).
- Big binaries (videos, PSDs) — keep them out of the repo; drop a path or link
  in a `.md` instead.
