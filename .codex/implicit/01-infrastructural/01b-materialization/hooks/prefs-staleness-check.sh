#!/usr/bin/env bash
# H-2.5: SessionStart — check if prefs-resolved.json is stale
# Stdout injected into Claude's context.

RESOLVED="$CLAUDE_PROJECT_DIR/.state/prefs-resolved.json"

if [ ! -f "$RESOLVED" ]; then
    echo "NOTE: .state/prefs-resolved.json does not exist. Run pref-resolve to generate."
    exit 0
fi

STALE=false

for SOURCE in "$CLAUDE_PROJECT_DIR/.codex/pref-options.json" "$CLAUDE_PROJECT_DIR/.codex/prefs.json" "$CLAUDE_PROJECT_DIR/.state/prefs.json"; do
    if [ -f "$SOURCE" ] && [ "$SOURCE" -nt "$RESOLVED" ]; then
        STALE=true
        break
    fi
done

if [ "$STALE" = true ]; then
    echo "WARNING: Preferences may be stale — source files modified since last resolution."
    echo "Consider re-running pref-resolve to regenerate .state/prefs-resolved.json."
fi

exit 0
