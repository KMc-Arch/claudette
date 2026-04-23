#!/usr/bin/env bash
# H-3.9: PreToolUse (Write|Edit) — enforce apex CLAUDE.md immutability.
#
# Blocks Write operations to the apex CLAUDE.md entirely. Permits Edit
# operations only when the change is confined to the frontmatter block
# (between opening and closing `---` fences). Body evolution must happen
# in start.md files downstream.

INPUT=$(cat)
export CLAUDE_HOOK_INPUT="$INPUT"

# Resolve Python interpreter: python first (Windows convention + Linux alias),
# python3 as fallback (Unix PEP 394 canonical). See backlog BL-PY-INTERP.
PY=$(command -v python || command -v python3)
if [ -z "$PY" ]; then
    echo "WARN: claude-md-immutability-guard: no python interpreter found — guard inactive." >&2
    exit 0
fi

"$PY" - "$CLAUDE_PROJECT_DIR" <<'PY'
import json
import os
import re
import sys

project_dir = sys.argv[1]

try:
    data = json.loads(os.environ["CLAUDE_HOOK_INPUT"])
except (json.JSONDecodeError, KeyError):
    sys.exit(0)

tool_name = data.get("tool_name", "")
tool_input = data.get("tool_input", {})
file_path = tool_input.get("file_path", "")
if not file_path:
    sys.exit(0)

# Canonicalize to POSIX absolute path for comparison
file_path = file_path.replace("\\", "/")
if not os.path.isabs(file_path):
    file_path = os.path.join(project_dir, file_path)
file_path = os.path.normpath(file_path)

apex = os.path.normpath(os.path.join(project_dir, "CLAUDE.md"))
if file_path != apex:
    sys.exit(0)  # Not the apex — no constraint

# Write operations always blocked — a full rewrite would clobber the body.
if tool_name != "Edit":
    print("BLOCKED: apex CLAUDE.md is immutable (design constraint #2).", file=sys.stderr)
    print("  CLAUDE.md is a bootstrap pointer — it never grows.", file=sys.stderr)
    print("  Body evolves through start.md files downstream.", file=sys.stderr)
    print("  Frontmatter-only edits are permitted via the Edit tool.", file=sys.stderr)
    sys.exit(2)

old_string = tool_input.get("old_string", "")
new_string = tool_input.get("new_string", "")

try:
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
except OSError:
    sys.exit(0)  # Let the tool raise the real error

# Locate frontmatter: `---\n ... \n---\n`
m = re.match(r"^---\n(.*?\n)?---\n", content, re.DOTALL)
if not m:
    print("BLOCKED: apex CLAUDE.md has no parseable frontmatter; edit denied.", file=sys.stderr)
    sys.exit(2)

fm_end = m.end()

# Require old_string to be entirely within the frontmatter block.
old_idx = content.find(old_string)
if old_idx < 0:
    sys.exit(0)  # Edit tool will fail on its own with a clearer error
if old_idx + len(old_string) > fm_end:
    print("BLOCKED: apex CLAUDE.md edits must be confined to frontmatter.", file=sys.stderr)
    print("  Body is immutable — evolve via start.md files downstream.", file=sys.stderr)
    sys.exit(2)

# Verify the post-edit file still has a valid frontmatter block.
new_content = content[:old_idx] + new_string + content[old_idx + len(old_string):]
if not re.match(r"^---\n(.*?\n)?---\n", new_content, re.DOTALL):
    print("BLOCKED: apex CLAUDE.md edit would break frontmatter fences.", file=sys.stderr)
    sys.exit(2)

sys.exit(0)
PY
