---
version: 1
---

# static-assets

Canonical Claudette brand iconography — the **Rooted Hex**. Single source of truth
for the mark wherever it appears: favicons, GitHub headers, slide decks, app icons.
Downstream surfaces copy or export from here; they do not invent their own.

## The mark

A hexagon enclosing an ascending stack of carets — largest at the apex, each smaller
and paler, trailing into two dots. It is the `^` context-root motif: nested carets =
a rooted tree climbing toward its apex. Monochrome by design, so it sits on any accent
colour without clashing.

## Two treatments — pick by surface

| Treatment | Files | Hex fill / border | Use on |
|---|---|---|---|
| **Light** (default, unmarked) | `claudette*` | `#FFFFFF` / `#454545`, black top caret | light or foregrounded surfaces — browser chrome, GitHub light, print, favicons |
| **Dark** | `claudette-dark*` | `#3F3F3F` / `#D9D9D9`, white top caret | dark or backgrounded surfaces — the brand dark field `#0B0F14` |

Naming convention, whole tree: **unmarked = light, `-dark` = dark.** Nothing else
marks theme.

## Masters vs exports

The two SVGs in `icons/` are the editable masters (`claudette.svg` light,
`claudette-dark.svg` dark). Every PNG and the `.ico` is an export at a fixed size.
**Edit the SVG, then re-export** — do not hand-edit a raster. After changing the
artwork, re-export all sizes *and* re-sync any surface that inlined a copy: a deck
that embeds the SVG as a data URI holds a frozen copy that will not track the master.

## Subfolders

- `icons/` — favicon and app-icon set (see its `start.md`)
- `full-size/` — GitHub social-preview banners (see its `start.md`)

## Provenance

Assembled 2026-09-15 from several manual exports, then deduped and renamed to the
convention above. If you ever find two files with identical pixels under different
names, the set has regressed — collapse them to one.
