---
version: 3
---

# hooks

Boot-time hook registration. These scripts implement structural enforcement of governance rules via Claude Code's hook system.

## Hook Inventory

| Script | Hook Event | Matcher | Purpose |
|---|---|---|---|
| `boot-inject.py` | SessionStart | (all) | Inject hierarchy-aware boot chain + command index + warning relay mandate into Claude's context (replaces legacy `boot-inject.sh`) |
| `prefs-staleness-check.sh` | SessionStart | (all) | Warn if prefs-resolved.json is stale |
| `memory-redirect-check.sh` | SessionStart | (all) | Warn if autoMemoryDirectory is misconfigured (6 failure modes checked) |
| `visibility-guard.sh` | PreToolUse | Read\|Glob\|Grep\|Bash\|Write\|Edit | Block access to `_`-prefixed paths |
| `containment-guard.sh` | PreToolUse | Write\|Edit | Block writes outside `^` |
| `gravity-guard.sh` | PreToolUse | Write\|Edit | Block `.state/` writes outside `^` |
| `api-guard.sh` | PreToolUse | Bash | Block Anthropic API/SDK invocations (ABSOLUTE HOLD) |
| `audit-immutability-guard.sh` | PreToolUse | Write\|Edit | Block writes to existing audit folders (except `decisions.md`) |
| `claude-md-immutability-guard.sh` | PreToolUse | Write\|Edit | Block writes to root CLAUDE.md |
| `codex-edit-notify.sh` | PostToolUse | Write\|Edit | Notify when codex executables are edited |
| `trace-logger.sh` | PostToolUse | Read\|Write\|Edit\|Bash\|Glob\|Grep | Append tool calls + output size to session trace |
| `session-close.sh` | Stop | (all) | Prompt for state-abstract + compliance + trace finalization |
| `subagent-conformance.sh` | SubagentStop | (all) | Trigger contract conformance check |

## Enforcement Model

PreToolUse hooks provide **structural enforcement** — they block violations before they happen (exit code 2 = block). This moves governance from "purely directive" to "automation-backed" for these boundaries:

| Boundary | Hook | Defense layer |
|---|---|---|
| `_` visibility | `visibility-guard.sh` | Blocks Read/Glob/Grep/Write/Edit/Bash on `_`-prefixed paths |
| Path containment | `containment-guard.sh` | Blocks writes outside `^` |
| State gravity | `gravity-guard.sh` | Blocks `.state/` writes outside `^` |
| Access (API) | `api-guard.sh` | Blocks Anthropic API/SDK invocations in Bash |
| Audit immutability | `audit-immutability-guard.sh` | Blocks writes to existing audit run folders |
| CLAUDE.md immutability | `claude-md-immutability-guard.sh` | Blocks writes to root CLAUDE.md |
