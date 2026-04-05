#!/usr/bin/env bash
# H-01: SessionStart — inject boot chain instructions into Claude's context
# Stdout is injected into Claude's context before any user interaction.
# File I/O (shims, prefs, settings, traces) is handled by boot.py pre-launch.
# This hook handles ONLY context injection.

# Build dynamic command index
EXPLICIT_CMDS=""
for entry_dir in "$CLAUDE_PROJECT_DIR"/.codex/explicit/*/; do
    [ -d "$entry_dir" ] || continue
    name=$(basename "$entry_dir")
    if [ -n "$EXPLICIT_CMDS" ]; then
        EXPLICIT_CMDS="$EXPLICIT_CMDS, $name"
    else
        EXPLICIT_CMDS="$name"
    fi
done

# Boot chain instructions
cat <<BOOT
BOOT SEQUENCE — READ THESE FILES NOW, IN ORDER, BEFORE RESPONDING TO ANY USER MESSAGE:

1. Read .codex/start.md (governance root — primitives, taxonomy, loading rules)
2. Read .state/start.md (state interpretation, signal prefix taxonomy)
3. Read .state/memory/user.md (user profile — if it exists and has content)
4. Read .state/memory/state-abstract.md (project state synthesis — if it exists and has content)

The start.md convention: every folder has a start.md. Always read it BEFORE anything else in that folder. It describes what the folder contains, how to interpret it, and how to engage with it.

After reading the above files, follow the loading rules in .codex/start.md to complete the boot sequence (implicit tiers, lazy-load indexes for explicit/reactive/reflexive).

5. WARNING RELAY: If ANY other SessionStart hook produced a warning (look for lines containing ⚠ or BLOCKED or WARNING), you MUST reproduce that warning verbatim to the user in your FIRST response, BEFORE any other content. The user CANNOT see SessionStart hook output — you are the only relay. This is not optional.

Available explicit commands (invoke by name or /slash-command): $EXPLICIT_CMDS
When the user invokes any of these, read .codex/explicit/<name>/start.md and follow its protocol exactly.
BOOT
