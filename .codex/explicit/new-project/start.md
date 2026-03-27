---
version: 2
short-desc: Scaffold a new child project from template
runtime: python
reads:
  - "^/.codex/specs/child-project.md"
  - "^/.templates/child/"
writes:
  - "^/<name>/"
---

# new-project

Create a new child project with the claudette2 minimum standard structure.

## Usage

`new-project <name>` — create a child project folder in the current directory

## What It Creates

Runs `bootstrap-child.py` which copies the full `^/.templates/child/` tree:

```
<name>/
    CLAUDE.md              (root: true, codex: ^/^/.codex)
    .state/
        start.md
        prefs.json
        memory/
            start.md
            decisions.md
        work/
            start.md
            backlog.md
        tests/
            start.md
        traces/
            start.md
```

All `start.md` files are pre-populated with child-appropriate content that references `^/^/` for inherited definitions. Content lives in the template files, not in the script.

## Execution

```
python .codex/explicit/new-project/bootstrap-child.py <name> --project-root ^
```

## Child Project Spec

See `.codex/specs/child-project.md` for the minimum standard and guidance on when/why a child project would add its own `.codex/` entries.
