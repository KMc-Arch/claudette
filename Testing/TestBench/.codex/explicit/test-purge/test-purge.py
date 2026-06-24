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

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

# TestBench root: up 4 levels from .codex/explicit/test-purge/test-purge.py
TESTBENCH = Path(__file__).resolve().parents[3]
# Apex root: up from Testing/TestBench/
APEX = TESTBENCH.parents[1]
PURGE_SCRIPT = APEX / ".codex" / "explicit" / "purge" / "purge.py"

# A scratch-looking file at the project root, OUTSIDE .tmp/. purge must REPORT it
# (straggler detection) but never delete it.
STRAGGLER_FILE = "stray-prbody.md"

# Boot reports: purge prunes .state/tests/boot/*-bootstrap.md to the newest N.
# Read N straight from purge.py (no hand-copied constant — avoids drift). Populate
# more than N; expect oldest pruned, newest kept. Lexical name order is ASSUMED to
# equal chronological order (purge sorts by filename), which the ISO-style names
# below satisfy by construction.
def _purge_constant(name: str, default):
    try:
        spec = importlib.util.spec_from_file_location("_purge_for_const", PURGE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, name, default)
    except Exception:
        return default


BOOT_KEEP = _purge_constant("BOOT_REPORTS_KEEP", 5)
BOOT_REPORTS = [f"2026-04-03-{i:04d}-bootstrap.md" for i in range(1, BOOT_KEEP + 3)]  # N+2 files


# ── Dummy content definitions ──────────────────────────────────────

# (relative_path, content, scope)
#   scope "standard" — removed by default purge (and by all)
#   scope "all"      — removed only by `purge all`
#   scope "never"    — survives both modes (e.g. a fresh .tmp/ buffer that the
#                      freshness guard keeps, since this test cannot backdate
#                      mtime on this filesystem)
DUMMY_FILES = [
    # Standard purge targets
    (".claude/session.jsonl", '{"dummy": true}\n', "standard"),
    (".claude/conversation.md", "# Dummy conversation\n", "standard"),
    (".state/prefs-resolved.json", '{"dummy": true}\n', "standard"),
    (".state/traces/dummy-trace.trace", "[2026-04-03T00:00:00Z] dummy trace\n", "standard"),
    (".state/pauses/dummy-pause.md", "# Dummy pause\n", "standard"),
    # .tmp/ sandbox rig — cleared in default scope (and all)
    (".tmp/sandbox/dummy-rig/contents.md", "# Dummy sandbox rig\n", "standard"),
    # Purge-all targets
    (".state/memory/dummy-memory.md", "---\nname: dummy\ntype: project\n---\nDummy.\n", "all"),
    (".state/work/dummy-work.md", "# Dummy work item\n", "all"),
    (".state/plans/dummy-plan.md", "# Dummy plan\n", "all"),
    (".state/bundles/dummy-bundle/contents.md", "# Dummy bundle\n", "all"),
    # .tmp/ loose buffer, freshly written — kept by the freshness guard even under
    # `purge all` (removal-when-old is proven separately via the window=0 probe).
    (".tmp/fresh-prbody.md", "# fresh buffer\n", "never"),
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
    ".tmp/start.md",
    "CLAUDE.md",
    ".codex/explicit/test-purge/test-purge.py",
    ".codex/explicit/test-purge/start.md",
]


# ── Populate ───────────────────────────────────────────────────────

def populate():
    """Create all dummy files, the audit fixture, and the root straggler."""
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

    # Boot reports — exercise the keep-newest-N prune.
    boot_dir = TESTBENCH / ".state" / "tests" / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    for name in BOOT_REPORTS:
        (boot_dir / name).write_text(f"# {name}\n")
        created += 1
    print(f"    created: {len(BOOT_REPORTS)} boot reports in .state/tests/boot/")

    # Straggler: scratch-looking file OUTSIDE .tmp/, at the project root.
    (TESTBENCH / STRAGGLER_FILE).write_text("# stray scratch outside .tmp/\n")
    created += 1
    print(f"    created: {STRAGGLER_FILE} (straggler)")

    print(f"\n  {created} dummy artifacts created.\n")


# ── Run purge ──────────────────────────────────────────────────────

def run_purge(scope: str, extra_args: list | None = None):
    """Invoke purge.py against TestBench. Returns (returncode, stdout)."""
    cmd = [
        sys.executable, str(PURGE_SCRIPT),
        scope,
        "--project-root", str(TESTBENCH),
        "--confirm",
    ]
    if extra_args:
        cmd += extra_args
    print(f"\n  Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            print(f"    ERR: {line}")
    print()
    return result.returncode, result.stdout or ""


# ── Verify ─────────────────────────────────────────────────────────

def verify(scope: str, stdout: str) -> list[str]:
    """Check that the right files survived or died, and stragglers were reported."""
    errors = []

    if scope == "all":
        should_die = [r for r, _, s in DUMMY_FILES if s in ("standard", "all")]
        should_live = [r for r, _, s in DUMMY_FILES if s == "never"]
    else:  # default
        should_die = [r for r, _, s in DUMMY_FILES if s == "standard"]
        should_live = [r for r, _, s in DUMMY_FILES if s in ("all", "never")]

    for rel in should_die:
        if (TESTBENCH / rel).exists():
            errors.append(f"SHOULD BE GONE:  {rel}")

    for rel in should_live:
        if not (TESTBENCH / rel).exists():
            errors.append(f"WRONGLY DELETED: {rel} (should survive {scope} purge)")

    for rel in SURVIVORS:
        if not (TESTBENCH / rel).exists():
            errors.append(f"WRONGLY DELETED: {rel} (must always survive)")

    # Boot reports: oldest pruned, newest BOOT_KEEP retained.
    boot_dir = TESTBENCH / ".state" / "tests" / "boot"
    ordered = sorted(BOOT_REPORTS)
    boot_should_die = ordered[:-BOOT_KEEP]
    boot_should_live = ordered[-BOOT_KEEP:]
    for name in boot_should_die:
        if (boot_dir / name).exists():
            errors.append(f"SHOULD BE GONE:  .state/tests/boot/{name} (beyond newest {BOOT_KEEP})")
    for name in boot_should_live:
        if not (boot_dir / name).exists():
            errors.append(f"WRONGLY DELETED: .state/tests/boot/{name} (within newest {BOOT_KEEP})")

    # Straggler: reported in output, but NOT removed.
    if not (TESTBENCH / STRAGGLER_FILE).exists():
        errors.append(f"WRONGLY DELETED: {STRAGGLER_FILE} (straggler must not be removed)")
    if "STRAGGLER" not in stdout or STRAGGLER_FILE not in stdout:
        errors.append(f"NOT REPORTED: straggler {STRAGGLER_FILE} not surfaced in purge output")

    return errors


def verify_loose_removal() -> list[str]:
    """Prove the loose-buffer sweep deletes when a file is past the freshness window.

    mtime can't be backdated on this filesystem, so instead force the window to 0
    (every loose file is then "old") and confirm a loose buffer is removed while the
    protected charter survives.
    """
    errors = []
    probe = TESTBENCH / ".tmp" / "probe-commitmsg.txt"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("probe buffer\n")

    run_purge("all", extra_args=["--tmp-freshness-hours", "0"])

    if probe.exists():
        errors.append("LOOSE NOT REMOVED: .tmp/probe-commitmsg.txt should be removed at freshness window=0")
    if not (TESTBENCH / ".tmp" / "start.md").exists():
        errors.append("WRONGLY DELETED: .tmp/start.md (charter must survive even at window=0)")

    # Unconditional cleanup of the probe, regardless of the assertion outcome.
    try:
        probe.unlink()
    except OSError:
        pass
    return errors


# ── Cleanup ────────────────────────────────────────────────────────

def cleanup():
    """Remove every artifact the test created, leaving TestBench pristine.

    purge removes most dummies itself; survivors (fresh .tmp/ buffer, straggler)
    would otherwise linger as untracked files in the git-tracked Testing/ tree.
    """
    for rel, _, _ in DUMMY_FILES:
        try:
            (TESTBENCH / rel).unlink()
        except OSError:
            pass
    for d in (".tmp/sandbox/dummy-rig", ".state/bundles/dummy-bundle", ".state/tests/boot"):
        shutil.rmtree(TESTBENCH / d, ignore_errors=True)
    try:
        (TESTBENCH / STRAGGLER_FILE).unlink()
    except OSError:
        pass


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

    # Test flow: populate → purge → verify → cleanup
    populate()

    scope = "default" if mode == "standard" else "all"
    rc, stdout = run_purge(scope)
    if rc != 0:
        print(f"  Purge exited with code {rc}")
        cleanup()
        sys.exit(1)

    errors = verify(scope, stdout)
    if scope == "all":
        errors += verify_loose_removal()
    cleanup()

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
        if scope == "default":
            expected_dead = len([r for r, _, s in DUMMY_FILES if s == "standard"])
        else:
            expected_dead = len([r for r, _, s in DUMMY_FILES if s in ("standard", "all")])
        print(f"    {expected_dead} files correctly removed")
        print(f"    {len(SURVIVORS)} files correctly survived")
        if scope == "all":
            print(f"    fresh .tmp/ buffer kept; loose buffer removed at window=0; straggler reported")
        else:
            print(f"    straggler reported (not removed)")
        print(f"\n  ALL PASSED.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
