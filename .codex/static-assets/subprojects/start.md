---
version: 1
---

# subprojects

The **subordinate** mark — a simplified Rooted Hex for a child project's own favicon
and app icons. Same lineage as the apex mark (`../icons/`), deliberately demoted so a
subproject never wears the apex's crest. Light treatment only. See `../start.md` for
the palette and the naming convention.

## The semaphore

Two changes from the apex mark, each signalling subordination:

- **Square, not hexagon** — a plain rounded square instead of the apex's hex crest.
- **One caret + two dots**, not an ascending stack — a single top caret trailing
  straight into the two dots: a rooted node, not the full tree climbing to an apex.

Fill `#FFFFFF`, border `#454545`, black caret — the light palette, unchanged.

## When to use

- A subproject / child project's own favicon, app icon, or header glyph.
- NOT for claudette itself — the apex wears the full Rooted Hex in `../icons/`.

## What's here

| File | Role |
|---|---|
| `claudette-subproject.svg` | Editable master (light). Source for every export. |
| `claudette-subproject-{16,20,24,32,48,64,96,128,180,192,256,512,1024}x…png` | PNG exports at those pixel sizes. |
| `favicon.ico` | Multi-resolution ICO (16/20/24/32/48/64/128/256). |

## Which file for what

- **Browser favicon** — `favicon.ico` (or, for PNG `<link rel="icon">` slots, `claudette-subproject-32x32.png` / `claudette-subproject-16x16.png`).
- **Apple touch icon** — `claudette-subproject-180x180.png`.
- **Android / PWA** — `claudette-subproject-192x192.png`, `claudette-subproject-512x512.png`.
- **Store / large raster** — `claudette-subproject-1024x1024.png`.

No dark treatment: subprojects carry the light mark only. If one is ever needed, add
`claudette-subproject-dark.svg` and follow the `-dark` convention from `../start.md`.

Master is the SVG; the PNGs and `.ico` are exports — edit the SVG and re-export, never
hand-edit a raster.
