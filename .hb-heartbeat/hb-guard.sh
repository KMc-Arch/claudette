#!/usr/bin/env bash
# Heartbeat sandbox guard — PreToolUse (Bash), installed ONLY in a worker sandbox's
# .claude/settings.local.json by runner.py. Position-agnostic checks that deny-prefix
# rules cannot express. Layers under remote-guard.sh (feature push + gh pr create allowed).
#
# Blocks:  gh pr merge|close|ready|review --approve   gh repo *   git push … --delete|-d|:<ref>
#          git update-ref   git worktree   git branch -D|-f|--force   git checkout|switch main|master
# Exit 0 = allow, exit 2 = block.

INPUT=$(cat)
PY=$(command -v python || command -v python3)
[ -z "$PY" ] && exit 0
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "$INPUT" | "$PY" "$DIR/hb-guard.py"
rc=$?
[ "$rc" -eq 2 ] && exit 2
exit 0
