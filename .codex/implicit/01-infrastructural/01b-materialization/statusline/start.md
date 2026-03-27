---
version: 1
runtime: sh
reads:
  - "^/.codex/settings.json"
writes: []
---

# Statusline

Boot-time status bar configuration. Materializes the Claude Code status line that displays session context in the terminal.

## Platform Integration

This module is a shell script — an acknowledged exception to the Python-only runtime constraint (design constraint #6). The status bar is a platform/terminal integration, not a codex operation. Shell is the native tool for reading environment variables and printing formatted strings.

## Reference Chain

```
.claude/settings.json          → references .codex/settings.json (codex-authoritative)
.codex/settings.json           → references this module's settings.json ($ref)
./settings.json                → contains the command path to statusline.sh
./statusline.sh                → the script that generates status bar output
```

## Settings

`settings.json` (sibling file) defines the Claude Code `statusline` configuration:
- `command` — path to `statusline.sh`, relative to project root

## Script

`statusline.sh` is invoked by Claude Code to generate the status bar content. It reads environment variables provided by Claude Code and prints formatted output to stdout.
