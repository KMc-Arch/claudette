#!/usr/bin/env bash
# H-13: SessionStart — validate autoMemoryDirectory points to .state/memory/
# Stdout is injected into Claude's context before any user interaction.
# NOTE: SessionStart stdout is visible to Claude but NOT displayed to the user.
# Each warning includes an instruction for Claude to relay it in its first response.

SETTINGS_LOCAL="$CLAUDE_PROJECT_DIR/.claude/settings.local.json"
EXPECTED_DIR="$CLAUDE_PROJECT_DIR/.state/memory"

# Normalize expected path to POSIX if on Windows
if command -v cygpath &>/dev/null; then
    EXPECTED_DIR=$(cygpath -u "$EXPECTED_DIR")
fi

# Case 1: settings.local.json doesn't exist at all
if [ ! -f "$SETTINGS_LOCAL" ]; then
    cat <<'EOF'
╔══════════════════════════════════════════════════════════════════╗
║  ⚠  AUTO-MEMORY NOT CONFIGURED — STATE LEAKAGE ACTIVE  ⚠      ║
╠══════════════════════════════════════════════════════════════════╣
║  .claude/settings.local.json does not exist.                    ║
║  Auto-memory is writing to ~/.claude/projects/<hash>/memory/    ║
║  instead of .state/memory/. This breaks state containment.      ║
║                                                                  ║
║  FIX: Create .claude/settings.local.json with:                  ║
║  {                                                               ║
║    "autoMemoryDirectory": "<ABSOLUTE_PATH>/.state/memory"       ║
║  }                                                               ║
║  where <ABSOLUTE_PATH> is the absolute path to this project.    ║
╚══════════════════════════════════════════════════════════════════╝

IMPORTANT: You MUST display the above warning to the user in your FIRST response. The user cannot see SessionStart hook output — only you can. Reproduce the warning box verbatim so they are aware of the issue.
EOF
    exit 0
fi

# Extract autoMemoryDirectory value (simple grep — no jq dependency)
AUTO_MEM=$(grep -oE '"autoMemoryDirectory"\s*:\s*"[^"]*"' "$SETTINGS_LOCAL" | grep -oE '"[^"]*"$' | tr -d '"')

# Case 2: key is missing or empty
if [ -z "$AUTO_MEM" ]; then
    cat <<'EOF'
╔══════════════════════════════════════════════════════════════════╗
║  ⚠  AUTO-MEMORY NOT CONFIGURED — STATE LEAKAGE ACTIVE  ⚠      ║
╠══════════════════════════════════════════════════════════════════╣
║  .claude/settings.local.json exists but autoMemoryDirectory     ║
║  is missing or empty. Auto-memory is writing to the default     ║
║  ~/.claude/projects/<hash>/memory/ location.                    ║
║                                                                  ║
║  FIX: Set autoMemoryDirectory to the absolute path to           ║
║  this project's .state/memory/ directory.                       ║
╚══════════════════════════════════════════════════════════════════╝

IMPORTANT: You MUST display the above warning to the user in your FIRST response. The user cannot see SessionStart hook output — only you can. Reproduce the warning box verbatim so they are aware of the issue.
EOF
    exit 0
fi

# Case 3: placeholder value not replaced
if echo "$AUTO_MEM" | grep -qiE 'REPLACE|PLACEHOLDER|EXAMPLE|TODO'; then
    cat <<'EOF'
╔══════════════════════════════════════════════════════════════════╗
║  ⚠  AUTO-MEMORY PLACEHOLDER — STATE LEAKAGE ACTIVE  ⚠         ║
╠══════════════════════════════════════════════════════════════════╣
║  autoMemoryDirectory still contains the template placeholder.   ║
║  Auto-memory is NOT writing to .state/memory/.                  ║
║                                                                  ║
║  FIX: Replace the placeholder with the absolute path to         ║
║  this project's .state/memory/ directory.                       ║
╚══════════════════════════════════════════════════════════════════╝

IMPORTANT: You MUST display the above warning to the user in your FIRST response. The user cannot see SessionStart hook output — only you can. Reproduce the warning box verbatim so they are aware of the issue.
EOF
    exit 0
fi

# Case 4: relative path (known platform bug — silently ignored)
if [[ "$AUTO_MEM" != /* ]] && [[ ! "$AUTO_MEM" =~ ^[A-Za-z]:[\\/] ]]; then
    cat <<'EOF'
╔══════════════════════════════════════════════════════════════════╗
║  ⚠  AUTO-MEMORY RELATIVE PATH — STATE LEAKAGE ACTIVE  ⚠       ║
╠══════════════════════════════════════════════════════════════════╣
║  autoMemoryDirectory uses a relative path. Due to a known       ║
║  Claude Code bug (GitHub #36636), relative paths are silently   ║
║  ignored — auto-memory writes to the default location.          ║
║                                                                  ║
║  FIX: Use an absolute path to .state/memory/.                   ║
╚══════════════════════════════════════════════════════════════════╝

IMPORTANT: You MUST display the above warning to the user in your FIRST response. The user cannot see SessionStart hook output — only you can. Reproduce the warning box verbatim so they are aware of the issue.
EOF
    exit 0
fi

# Normalize configured path for comparison
CONFIGURED="$AUTO_MEM"
if command -v cygpath &>/dev/null; then
    CONFIGURED=$(cygpath -u "$CONFIGURED" 2>/dev/null || echo "$CONFIGURED")
fi

# Case 5: path doesn't end with .state/memory (points somewhere unexpected)
if [[ "$CONFIGURED" != */.state/memory ]] && [[ "$CONFIGURED" != */.state/memory/ ]]; then
    cat <<EOF
╔══════════════════════════════════════════════════════════════════╗
║  ⚠  AUTO-MEMORY MISDIRECTED — CHECK CONFIGURATION  ⚠          ║
╠══════════════════════════════════════════════════════════════════╣
║  autoMemoryDirectory does not point to a .state/memory/ path.   ║
║  Current value: $AUTO_MEM
║  Expected pattern: <project-root>/.state/memory                 ║
║                                                                  ║
║  Auto-memory may be writing outside state governance.            ║
╚══════════════════════════════════════════════════════════════════╝

IMPORTANT: You MUST display the above warning to the user in your FIRST response. The user cannot see SessionStart hook output — only you can. Reproduce the warning box verbatim so they are aware of the issue.
EOF
    exit 0
fi

# Case 6: path points to .state/memory but for a DIFFERENT project (stale after move)
# Normalize both to compare basenames
CONFIGURED_RESOLVED=$(realpath -m "$CONFIGURED" 2>/dev/null || echo "$CONFIGURED")
EXPECTED_RESOLVED=$(realpath -m "$EXPECTED_DIR" 2>/dev/null || echo "$EXPECTED_DIR")

if [ "$CONFIGURED_RESOLVED" != "$EXPECTED_RESOLVED" ]; then
    cat <<EOF
╔══════════════════════════════════════════════════════════════════╗
║  ⚠  AUTO-MEMORY PATH STALE — STATE LEAKAGE LIKELY  ⚠          ║
╠══════════════════════════════════════════════════════════════════╣
║  autoMemoryDirectory points to a .state/memory/ path, but       ║
║  not THIS project's .state/memory/.                             ║
║                                                                  ║
║  Configured: $AUTO_MEM
║  Expected:   $EXPECTED_DIR
║                                                                  ║
║  This usually means the project was moved. Update the path.     ║
╚══════════════════════════════════════════════════════════════════╝

IMPORTANT: You MUST display the above warning to the user in your FIRST response. The user cannot see SessionStart hook output — only you can. Reproduce the warning box verbatim so they are aware of the issue.
EOF
    exit 0
fi

# All checks passed — no output (clean boot)
exit 0
