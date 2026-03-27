#!/usr/bin/env bash
# H-10: Stop — prompt for session close governance
# Stdout injected into context when Claude stops.

cat <<'CLOSE'
SESSION CLOSING — before ending, complete these governance tasks:

1. UPDATE .state/memory/state-abstract.md — rewrite from scratch with current project state (rolling abstract convention).
2. COMPLIANCE CHECK — review the session for boundary adherence (state gravity, path containment, identity isolation, enforcement tiers). Note any violations in .state/tests/compliance/.
3. TRACE FINALIZATION — ensure .state/traces/ session log is complete.

If the session was trivial (quick question, no state changes), skip items 1-3.
CLOSE
