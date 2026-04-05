#!/usr/bin/env python3
"""Destructive purge verification for TestBench.

Populates dummy content, runs purge, verifies correctness.
Designed to be run from the apex root.

Usage:
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py populate
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py standard
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py all
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# TestBench root: up 4 levels from .codex/explicit/test-purge/test-purge.py
TESTBENCH = Path(__file__).resolve().parents[3]
# Apex root: up from Testing/TestBench/
APEX = TESTBENCH.parents[1]
PURGE_SCRIPT = APEX / ".codex" / "explicit" / "purge" / "purge.py"


# ── Dummy content definitions ──────────────────────────────────────

# (relative_path, content, scope) — scope is "standard" or "all"
DUMMY_FILES = [
    # Standard purge targets
    (".claude/session.jsonl", '{"dummy": true}\n', "standard"),
    (".claude/conversation.md", "# Dummy conversation\n", "standard"),
    (".state/prefs-resolved.json", '{"dummy": true}\n', "standard"),
    (".state/tests/boot/dummy-report.md", "# Dummy boot report\n", "standard"),
    (".state/traces/dummy-trace.trace", "[2026-04-03T00:00:00Z] dummy trace\n", "standard"),
    (".state/pauses/dummy-pause.md", "# Dummy pause\n", "standard"),
    # Purge-all targets
    (".state/memory/dummy-memory.md", "---\nname: dummy\ntype: project\n---\nDummy.\n", "all"),
    (".state/work/dummy-work.md", "# Dummy work item\n", "all"),
    (".state/plans/dummy-plan.md", "# Dummy plan\n", "all"),
    (".state/bundles/dummy-bundle/contents.md", "# Dummy bundle\n", "all"),
]

# Files that must survive ALL purge modes
SURVIVORS = [
    ".state/tests/audits/20260403-0000/findings.md",
    ".state/start.md",
    ".state/memory/start.md",
    ".state/work/start.md",
    ".state/plans/start.md",
    ".state/traces/start.md",
    ".state/tests/start.md",
    "CLAUDE.md",
    ".codex/explicit/test-purge/test-purge.py",
    ".codex/explicit/test-purge/start.md",
]


# ── Populate ───────────────────────────────────────────────────────

def populate():
    """Create all dummy files and the audit fixture."""
    print(f"\n  Populating TestBench at {TESTBENCH}\n")

    # Ensure audit fixture exists (must survive everything)
    audit_dir = TESTBENCH / ".state" / "tests" / "audits" / "20260403-0000"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_file = audit_dir / "findings.md"
    if not audit_file.exists():
        audit_file.write_text("# Dummy audit — MUST survive purge-all\n")

    created = 0
    for rel, content, _scope in DUMMY_FILES:
        path = TESTBENCH / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        created += 1
        print(f"    created: {rel}")

    print(f"\n  {created} dummy files created.\n")


# ── Run purge ──────────────────────────────────────────────────────

def run_purge(scope: str):
    """Invoke purge.py against TestBench."""
    cmd = [
        sys.executable, str(PURGE_SCRIPT),
        scope,
        "--project-root", str(TESTBENCH),
        "--confirm",
    ]
    print(f"\n  Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            print(f"    ERR: {line}")
    print()
    return result.returncode


# ── Verify ─────────────────────────────────────────────────────────

def verify(scope: str) -> list[str]:
    """Check that the right files survived or died."""
    errors = []

    # Determine which dummy files should be gone
    if scope == "all":
        should_die = [rel for rel, _, _ in DUMMY_FILES]
    else:
        should_die = [rel for rel, _, s in DUMMY_FILES if s == "standard"]
        should_survive_scope = [rel for rel, _, s in DUMMY_FILES if s == "all"]

    # Check deaths
    for rel in should_die:
        path = TESTBENCH / rel
        if path.exists():
            errors.append(f"SHOULD BE GONE:  {rel}")

    # Check standard-scope survivors (only for standard purge)
    if scope == "default":
        for rel in should_survive_scope:
            path = TESTBENCH / rel
            if not path.exists():
                errors.append(f"WRONGLY DELETED: {rel} (should survive standard purge)")

    # Check permanent survivors
    for rel in SURVIVORS:
        path = TESTBENCH / rel
        if not path.exists():
            errors.append(f"WRONGLY DELETED: {rel} (must always survive)")

    return errors


# ── Main ───────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("populate", "standard", "all"):
        print("Usage: test-purge.py [populate|standard|all]")
        sys.exit(1)

    mode = sys.argv[1]

    if not PURGE_SCRIPT.exists():
        print(f"  Error: purge script not found at {PURGE_SCRIPT}")
        sys.exit(1)

    if mode == "populate":
        populate()
        sys.exit(0)

    # Test flow: populate → purge → verify
    populate()

    scope = "default" if mode == "standard" else "all"
    rc = run_purge(scope)
    if rc != 0:
        print(f"  Purge exited with code {rc}")
        sys.exit(1)

    errors = verify(scope)

    print("  +---------------------------------------------+")
    print("  |          test-purge verification             |")
    print("  +---------------------------------------------+")
    print()

    if errors:
        for e in errors:
            print(f"    FAIL  {e}")
        print(f"\n  {len(errors)} failures.\n")
        sys.exit(1)
    else:
        expected_dead = len([r for r, _, s in DUMMY_FILES if s == "standard"]) if scope == "default" else len(DUMMY_FILES)
        print(f"    {expected_dead} files correctly removed")
        print(f"    {len(SURVIVORS)} files correctly survived")
        print(f"\n  ALL PASSED.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
