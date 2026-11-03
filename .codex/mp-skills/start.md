---
version: 2
---

# mp-skills

Third-party skills from `mattpocock/skills`, vendored as a **library**. Installed 2026-09-29 with
`npx skills add` (37 skills); provenance and hashes are in `skills-lock.json`.

**Not registered anywhere.** `codex-register` only walks `explicit/`, so nothing here becomes a slash
command or an auto-invocable skill in any project. Never symlink or copy these into a project's
`.claude/skills/`: that brings back automatic discovery and name clashes with built-ins (the vendored
`code-review` shadowed Claude Code's built-in `/code-review` while installed in zdm).

## How to use

From any project, run `/mp-skills <skill> [input]` (e.g. `/mp-skills wayfinder`); `/mp-skills` alone
lists the skills. That command is `^/^/.codex/explicit/mp-skills/`, which cboot propagates to every
child, so every project uses this one library and this one set of overrides. Naming a skill by path
(`^/^/.codex/mp-skills/skills/<skill>`) is equivalent. That path is the sanctioned exception to "no
lateral traversal"; invoking only reads these files.

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
| `skills/` | Upstream skills, **verbatim**. Never edit; adapt in `overrides/`. Exempt from cboot's every-folder-has-a-`start.md` check for that reason. |
| `skills/LICENSE` | Upstream MIT license (© Matt Pocock). This repo is public, so the notice must ship with every copy. |
| `overrides/` | Our conventions, layered on top of the upstream instructions. |
| `skills-lock.json` | Upstream source and content hashes at install time. |

## Updating

In a scratch directory outside any project, run `npx skills add mattpocock/skills --copy -y`. Diff its
`.agents/skills/` against `skills/`, then copy it over `skills/` and replace `skills-lock.json`.
`npx skills add` does not bring the license, so keep `skills/LICENSE`, and refresh it from the
upstream repo's `LICENSE` if that changed. Re-read the overrides against whatever changed.
