---
version: 1
---

# mp-skills

Third-party skills from `mattpocock/skills`, vendored as a **library**. Installed 2026-09-29 with
`npx skills add` (37 skills); provenance and hashes are in `skills-lock.json`.

**Not registered anywhere.** `codex-register` only walks `explicit/`, so nothing here becomes a slash
command or an auto-invocable skill in any project. Never symlink or copy these into a project's
`.claude/skills/`: that brings back automatic discovery and name clashes with built-ins (the vendored
`code-review` shadowed Claude Code's built-in `/code-review` while installed in zdm).

## How to use

The operator asks for a skill by explicit path, e.g. "use `/mnt/claudette/.codex/mp-skills/skills/wayfinder`".
That explicit path is the sanctioned exception to "no lateral traversal"; invoking only reads these files.

Read, in this order:

1. `overrides/common.md`: always.
2. `overrides/<name>.md`: if it exists.
3. `skills/<name>/SKILL.md` and any files it links.

**Precedence:** governance (holds, containment, state gravity, guards) > overrides > `SKILL.md`.
When a `SKILL.md` says "call the Skill tool with X", read `skills/X/SKILL.md` (plus its overrides) by
path instead; these skills are not registered.

## Layout

| Path | Contents |
|---|---|
| `skills/` | Upstream skills, **verbatim**. Never edit; adapt in `overrides/`. |
| `skills/LICENSE` | Upstream MIT license (© Matt Pocock). This repo is public, so the notice must ship with every copy. |
| `overrides/` | Our conventions, layered on top of the upstream instructions. |
| `skills-lock.json` | Upstream source and content hashes at install time. |

## Updating

In a scratch directory outside any project, run `npx skills add mattpocock/skills --copy -y`. Diff its
`.agents/skills/` against `skills/`, then copy it over `skills/` and replace `skills-lock.json`.
`npx skills add` does not bring the license, so keep `skills/LICENSE`, and refresh it from the
upstream repo's `LICENSE` if that changed. Re-read the overrides against whatever changed.
