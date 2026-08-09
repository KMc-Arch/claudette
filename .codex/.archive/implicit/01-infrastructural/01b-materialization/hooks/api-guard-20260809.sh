#!/usr/bin/env bash
# H-1.8: PreToolUse (Bash) — ABSOLUTE HOLD on Anthropic API calls
# Blocks Bash commands that invoke the Anthropic API or SDK.

INPUT=$(cat)

COMMAND=$(echo "$INPUT" | grep -oE '"command"\s*:\s*"[^"]*"' | head -1 | sed 's/"command"\s*:\s*"//;s/"$//')

if [ -z "$COMMAND" ]; then
    exit 0
fi

# Check for API/SDK patterns
if echo "$COMMAND" | grep -qiE 'anthropic|api\.anthropic\.com|@anthropic-ai/sdk|claude_agent_sdk|pip install.*anthropic|npm install.*@anthropic'; then
    echo "BLOCKED: ABSOLUTE HOLD on Anthropic API invocation." >&2
    echo "  Command: $COMMAND" >&2
    echo "  This project prohibits calling the Claude API, importing Anthropic SDKs," >&2
    echo "  or any mechanism that would consume API credits or create external API traffic." >&2
    echo "  Three-step authorization required: explicit instruction → stated intent → user confirmation." >&2
    exit 2
fi

exit 0
