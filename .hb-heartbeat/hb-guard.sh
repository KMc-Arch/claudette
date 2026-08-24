#!/usr/bin/env bash
# Heartbeat sandbox guard — PreToolUse (Bash), installed ONLY in a worker sandbox's .claude/settings.local.json
# by runner.py. Thin wrapper: all logic is in hb-guard.py (allowlist-oriented: live-tree path containment incl.
# alias mounts, git subcommand allowlist with no global/exec options, gh read-only pr view|list|diff|status|checks,
# wrapper peeling, unset/export of protected env, credential tokens, Windows interop). Unknown shapes fail closed.
# Sits under the structural controls (credential-less worker; runner-side push/PR).
# Wrapper contract: hb-guard.py exit 0 = allow; ANY other outcome = block (see below).

# FAIL CLOSED. Only a clean rc=0 from hb-guard.py allows the command; a missing
# interpreter, a crash, a syntax error, an OOM kill, or any unexpected rc BLOCKS.
# The old contract ("rc==2 blocks, everything else allows") meant every failure mode
# of the guard silently disabled it — verified: rc 1/3/137, an uncaught exception, a
# syntax error and an absent interpreter all yielded "allow", with no signal anywhere.
# This trades a security failure for an availability failure, which is the right trade
# for an unattended credential-adjacent worker: a wedged night is visible and
# recoverable, a silently ungated one is neither. The guard's stderr is passed through
# so a wedge is diagnosable rather than mysterious.
# python3 first: `config.json` declares "python": "python3", and a stray `python` shim
# on the worker's prepended extra_path must not decide which interpreter gates the run.
INPUT=$(cat)
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    echo "BLOCKED: hb-guard found no python interpreter (fail closed)." >&2
    exit 2
fi
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf '%s' "$INPUT" | "$PY" "$DIR/hb-guard.py"
rc=$?
[ "$rc" -eq 0 ] && exit 0
if [ "$rc" -ne 2 ]; then
    echo "BLOCKED: hb-guard exited rc=$rc (could not decide — fail closed)." >&2
fi
exit 2
