#!/usr/bin/env bash
# statusline.sh — Claude Code status bar generator
# Invoked by Claude Code via settings.json statusline.command
# Reads CC environment variables, prints formatted status to stdout

# Available environment variables (from Claude Code):
#   CLAUDE_MODEL        - current model name
#   CLAUDE_SESSION_ID   - session identifier
#   CLAUDE_PROJECT_DIR  - project root path

printf "%s | %s" "${CLAUDE_MODEL:-unknown}" "${CLAUDE_PROJECT_DIR##*/}"
