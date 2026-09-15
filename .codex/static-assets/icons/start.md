---
version: 1
---

# icons

Favicon and application-icon set — the Rooted Hex at fixed pixel sizes, plus the
editable masters. Light treatment unless marked `-dark`. See `../start.md` for the
mark and the light/dark convention.

## What's here

| File | Role |
|---|---|
| `claudette.svg` | Light master (editable). Source for every light export. |
| `claudette-dark.svg` | Dark master (editable). |
| `claudette-{16,24,32,48,64,96,128,180,192,256,512}x…png` | Light PNG exports at those pixel sizes. |
| `claudette-dark-512.png` | Dark 512px, for display on a dark field. |
| `favicon.ico` | Multi-resolution ICO (16/24/32/48/64/128/256) for legacy favicon slots. |

## Which file for what

- **Browser favicon** — `favicon.ico`, or `claudette.svg` + `claudette-32x32.png` / `claudette-16x16.png`.
- **Apple touch icon** — `claudette-180x180.png`.
- **Android / PWA** — `claudette-192x192.png`, `claudette-512x512.png`.
- **On a dark background** — `claudette-dark-512.png`, or export from `claudette-dark.svg`.

Masters are the SVGs; the PNGs and `.ico` are exports — edit the SVG and re-export,
never hand-edit a raster.
