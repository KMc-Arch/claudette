#!/usr/bin/env bash
# Heartbeat sandbox guard — PreToolUse (Bash), installed ONLY in a worker sandbox's .claude/settings.local.json
# by runner.py. Thin wrapper: all logic is in hb-guard.py (allowlist-oriented: live-tree path containment incl.
# alias mounts, git subcommand allowlist with no global/exec options, gh read-only pr view|list|diff|status|checks,
# wrapper peeling, unset/export of protected env, credential tokens, Windows interop). Unknown shapes fail closed.
# Sits under the structural controls (credential-less worker; runner-side push/PR). Exit 0 = allow, exit 2 = block.

INPUT=$(cat)
PY=$(command -v python || command -v python3)
[ -z "$PY" ] && exit 0
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "$INPUT" | "$PY" "$DIR/hb-guard.py"
rc=$?
[ "$rc" -eq 2 ] && exit 2
exit 0
