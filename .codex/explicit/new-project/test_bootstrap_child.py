#!/usr/bin/env python3
"""Focused tests for the new-project scaffolder's pure functions.

Hermetic: imports bootstrap-child.py and exercises `derive_folder_name` and
`fill_name_in_claude_md` directly -- no apex, template, or network needed.

Scope: the behaviours changed in commit 2a4c600 + its mileqa round --
(1) the 64-char folder-length cap, (2) the removal of the parent-group-rename
suggestion, (3) fill_name mechanics. The name-laundering WIRING (main() ->
mutator.launder) is proven by the mutator's own launder unit tests and by
mileqa's adversarial end-to-end sweep; a full integration harness for main()
is backlogged (bootstrap-child has no standalone integration test yet).

Run:  python3 test_bootstrap_child.py     # exit 1 on any failure
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "bootstrap_child", HERE / "bootstrap-child.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bc = _load()
fails = []


def check(cond, msg):
    print(("[PASS] " if cond else "[FAIL] ") + msg)
    if not cond:
        fails.append(msg)


# 1. Folder-length cap (MAX_FOLDER = 64).
check(len(bc.derive_folder_name("a" * 200)) == 64, "long name caps folder at 64 chars")

# 1a. The cap never empties and never leaves a trailing hyphen (strip runs before,
#     rstrip after).
capped = bc.derive_folder_name("a" * 63 + "-b" + "c" * 50)
check(len(capped) <= 64 and capped and not capped.endswith("-"),
      "capped folder is non-empty with no trailing hyphen")

# 2. Frontmatter-hostile characters are dropped from the derived folder.
check(bc.derive_folder_name("Web: API #2 Uber/Long") == "web-api-2-uberlong",
      "colons / '#' / slashes stripped from the folder name")

# 3. Non-ASCII transliterates (accents folded).
check(bc.derive_folder_name("Café Munchen") == "cafe-munchen",
      "accented characters transliterate to ASCII")

# 4. A name that derives to nothing raises ValueError (main() catches it -> clean exit).
try:
    bc.derive_folder_name("###")
    check(False, "all-punctuation name raises ValueError")
except ValueError:
    check(True, "all-punctuation name raises ValueError")

# 5. The parent-group-rename suggestion is gone (function + call removed).
check(not hasattr(bc, "parent_is_root_without_group"),
      "parent-group-rename suggestion removed")

# 6. fill_name replaces the empty `name:` line exactly once (no duplicate key).
with tempfile.TemporaryDirectory() as d:
    cm = Path(d) / "CLAUDE.md"
    cm.write_text("---\nroot: true\nname:\ncodex: ^/^/.codex\n---\n\nbody\n")
    bc.fill_name_in_claude_md(Path(d), "Clean Name")
    txt = cm.read_text()
    check("name: Clean Name" in txt and txt.count("name:") == 1,
          "fill_name replaces the empty name: exactly once")

print()
print("FAILURES:", len(fails))
sys.exit(1 if fails else 0)
