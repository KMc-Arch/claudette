---
version: 1
---

# git-guardrails-claude-code overrides

- **Scope:** this project only. Skip step 1's question. Never install to `~/.claude/`; it is outside the
  project.
- **Hook registration:** merge the hook into `hooks.PreToolUse` of `^/.claude/settings.local.json`, never
  `^/.claude/settings.json`. Local settings are where this instance persists such settings, and cboot
  keeps their other keys at every boot; it regenerates `settings.json` from the codex and would drop
  the hook.
- **Script:** `^/.claude/hooks/block-dangerous-git.sh`, as upstream's project option; the hook command
  stays `"$CLAUDE_PROJECT_DIR"/.claude/hooks/block-dangerous-git.sh`.
- **Per project:** cboot passes only permissions from the apex's local settings down to children, not
  hooks. An install covers the project it was run in, nothing below it.
