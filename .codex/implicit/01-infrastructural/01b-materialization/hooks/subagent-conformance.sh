#!/usr/bin/env bash
# H-11: SubagentStop — trigger contract conformance check
# Stdout injected into context when a subagent completes.

cat <<'CONFORM'
SUBAGENT COMPLETE — if this was an explicit module running with isolation: subagent, verify:
- Did the module's actual outputs match its declared writes: contract?
- Were any files written that weren't declared?
- Were any declared outputs not produced?

Log findings to .state/tests/reflexive/contract-conformance/ if mismatches found.
CONFORM
