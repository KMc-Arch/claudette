#!/usr/bin/env python3
"""Cascade integrity verification for TestBench.

Validates that the settings cascade (codex -> parent -> child) preserves
all keys at every stage. Runs from the parent context.

Usage:
    python Testing/TestBench/cascade-check.py --project-root .
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


# ── Test infrastructure ────────────────────────────────────────────

class CascadeChecker:
    def __init__(self, root):
        self.root = root
        self.passed = 0
        self.failed = 0
        self.warned = 0

    def ok(self, test_id, label):
        print(f"  [PASS] {test_id} -- {label}")
        self.passed += 1

    def fail(self, test_id, label, detail=""):
        print(f"  [FAIL] {test_id} -- {label}")
        if detail:
            print(f"         {detail}")
        self.failed += 1

    def warn(self, test_id, label, detail=""):
        print(f"  [WARN] {test_id} -- {label}")
        if detail:
            print(f"         {detail}")
        self.warned += 1

    def load_json(self, rel_path):
        p = self.root / rel_path
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))


# ── Tests ──────────────────────────────────────────────────────────

def run_checks(c):
    codex = c.load_json(".codex/settings.json")
    parent = c.load_json(".claude/settings.json")
    child = c.load_json("Testing/TestBench/.claude/settings.json")
    parent_prefs = c.load_json(".state/prefs-resolved.json")
    child_prefs = c.load_json("Testing/TestBench/.state/prefs-resolved.json")

    # ── CA: Cascade structure exists ───────────────────────────────

    if not codex:
        c.fail("CA01", "Codex settings exist", ".codex/settings.json not found")
        return
    c.ok("CA01", "Codex settings exist")

    if not parent:
        c.fail("CA02", "Parent materialized settings exist", ".claude/settings.json not found")
        return
    c.ok("CA02", "Parent materialized settings exist")

    if not child:
        c.fail("CA03", "Child materialized settings exist", "Testing/TestBench/.claude/settings.json not found")
        return
    c.ok("CA03", "Child materialized settings exist")

    # ── CA: Codex keys land in parent ──────────────────────────────

    # plansDirectory: verbatim pass-through
    if "plansDirectory" in codex:
        if "plansDirectory" in parent and parent["plansDirectory"] == codex["plansDirectory"]:
            c.ok("CA04", "plansDirectory: codex -> parent (verbatim)")
        else:
            c.fail("CA04", "plansDirectory: codex -> parent",
                   f"codex={codex.get('plansDirectory')}, parent={parent.get('plansDirectory')}")
    else:
        c.warn("CA04", "plansDirectory not in codex settings")

    # permissions: verbatim pass-through
    if "permissions" in codex:
        if "permissions" in parent and parent["permissions"] == codex["permissions"]:
            c.ok("CA05", "permissions: codex -> parent (verbatim)")
        else:
            c.fail("CA05", "permissions: codex -> parent",
                   f"codex has {len(codex.get('permissions', {}).get('allow', []))} rules, "
                   f"parent has {len(parent.get('permissions', {}).get('allow', []))}")
    else:
        c.warn("CA05", "permissions not in codex settings")

    # statusLine: module resolution (codex has modules.statusline, parent has statusLine)
    if "modules" in codex and "statusline" in codex["modules"]:
        if "statusLine" in parent:
            sl = parent["statusLine"]
            if sl.get("type") == "command" and sl.get("command"):
                cmd_path = Path(sl["command"])
                if cmd_path.exists():
                    c.ok("CA06", "statusLine: module resolved, command path exists")
                else:
                    c.fail("CA06", "statusLine: command path missing", str(cmd_path))
            else:
                c.fail("CA06", "statusLine: malformed", str(sl))
        else:
            c.fail("CA06", "statusLine: missing from parent (module not resolved)")

    # hooks: injected by cboot (not in codex, but must exist in parent)
    if "hooks" in parent:
        hook_events = list(parent["hooks"].keys())
        expected_events = ["SessionStart", "PreToolUse", "PostToolUse", "Stop", "SubagentStop"]
        missing = [e for e in expected_events if e not in hook_events]
        if missing:
            c.fail("CA07", f"hooks: parent missing events: {missing}")
        else:
            c.ok("CA07", f"hooks: parent has all {len(expected_events)} event types")
    else:
        c.fail("CA07", "hooks: missing from parent settings entirely")

    # ── CA: Parent keys land in child ──────────────────────────────

    # plansDirectory
    if "plansDirectory" in parent:
        if child.get("plansDirectory") == parent["plansDirectory"]:
            c.ok("CA08", "plansDirectory: parent -> child (verbatim)")
        else:
            c.fail("CA08", "plansDirectory: parent -> child",
                   f"parent={parent['plansDirectory']}, child={child.get('plansDirectory')}")

    # permissions
    if "permissions" in parent:
        if child.get("permissions") == parent["permissions"]:
            c.ok("CA09", "permissions: parent -> child (identical)")
        else:
            c.fail("CA09", "permissions: parent -> child mismatch",
                   f"parent has {len(parent['permissions'].get('allow', []))} rules, "
                   f"child has {len(child.get('permissions', {}).get('allow', []))}")

    # statusLine
    if "statusLine" in parent:
        if "statusLine" in child:
            child_sl = child["statusLine"]
            if child_sl.get("type") == "command" and child_sl.get("command"):
                cmd_path = Path(child_sl["command"])
                if cmd_path.exists():
                    c.ok("CA10", "statusLine: parent -> child, command path exists")
                else:
                    c.fail("CA10", "statusLine: child command path missing", str(cmd_path))
            else:
                c.fail("CA10", "statusLine: child has malformed statusLine", str(child_sl))
        else:
            c.fail("CA10", "statusLine: missing from child (casing bug?)",
                   f"child keys: {list(child.keys())}")

    # hooks: all events propagated
    if "hooks" in parent and "hooks" in child:
        parent_events = set(parent["hooks"].keys())
        child_events = set(child["hooks"].keys())
        if parent_events == child_events:
            c.ok("CA11", f"hooks: all {len(parent_events)} event types propagated")
        else:
            missing = parent_events - child_events
            extra = child_events - parent_events
            c.fail("CA11", "hooks: event mismatch",
                   f"missing={missing or 'none'}, extra={extra or 'none'}")
    elif "hooks" not in child:
        c.fail("CA11", "hooks: missing from child entirely")

    # hooks: count match
    if "hooks" in parent and "hooks" in child:
        def count_hooks(settings):
            total = 0
            for matchers in settings["hooks"].values():
                for block in matchers:
                    total += len(block.get("hooks", []))
            return total

        p_count = count_hooks(parent)
        c_count = count_hooks(child)
        if p_count == c_count:
            c.ok("CA12", f"hooks: hook count matches ({p_count})")
        else:
            c.fail("CA12", f"hooks: count mismatch (parent={p_count}, child={c_count})")

    # hooks: all child command paths resolve
    if "hooks" in child:
        broken = []
        for event, matchers in child["hooks"].items():
            for block in matchers:
                for hook in block.get("hooks", []):
                    cmd = hook.get("command", "")
                    # Extract path from 'bash "path"' or 'python "path"'
                    for prefix in ("bash ", "python "):
                        if cmd.startswith(prefix):
                            path_str = cmd[len(prefix):].strip('"')
                            if not Path(path_str).exists():
                                broken.append(f"{event}: {path_str}")
                            break
        if broken:
            c.fail("CA13", f"hooks: {len(broken)} broken command paths", "; ".join(broken[:3]))
        else:
            c.ok("CA13", "hooks: all child command paths resolve to existing files")

    # ── CA: Preferences ────────────────────────────────────────────

    if parent_prefs and child_prefs:
        # _meta.project
        child_project = child_prefs.get("_meta", {}).get("project")
        if child_project == "TestBench":
            c.ok("CA14", "prefs: _meta.project = 'TestBench'")
        else:
            c.fail("CA14", f"prefs: _meta.project = '{child_project}', expected 'TestBench'")

        # Non-meta keys match (when no child overrides)
        parent_keys = {k for k in parent_prefs if k != "_meta"}
        child_keys = {k for k in child_prefs if k != "_meta"}
        if parent_keys == child_keys:
            c.ok("CA15", f"prefs: all {len(parent_keys)} preference keys propagated")
        else:
            missing = parent_keys - child_keys
            c.fail("CA15", f"prefs: key mismatch", f"missing from child: {missing}")

        # Value match for non-overridden keys
        mismatched = []
        child_overrides_file = c.root / "Testing/TestBench/.state/prefs.json"
        child_overrides = {}
        if child_overrides_file.exists():
            try:
                child_overrides = json.loads(child_overrides_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass

        for key in parent_keys & child_keys:
            if key in child_overrides:
                continue  # Skip overridden keys
            if parent_prefs[key].get("value") != child_prefs[key].get("value"):
                mismatched.append(key)

        if mismatched:
            c.fail("CA16", f"prefs: {len(mismatched)} values differ without override", str(mismatched))
        else:
            c.ok("CA16", "prefs: non-overridden values match parent")
    elif not child_prefs:
        c.warn("CA14", "prefs: child prefs-resolved.json not found (run cboot)")


# ── Dummy key round-trip ───────────────────────────────────────────

def run_dummy_roundtrip(c):
    """Inject a dummy key, run cboot, verify cascade, clean up."""
    codex_path = c.root / ".codex/settings.json"
    codex_text = codex_path.read_text(encoding="utf-8")
    codex = json.loads(codex_text)

    # Inject
    codex["_cascadeTest"] = {"injected": True, "source": "cascade-check.py"}
    codex_path.write_text(json.dumps(codex, indent=2) + "\n", encoding="utf-8")

    try:
        # Run cboot
        result = subprocess.run(
            [sys.executable, str(c.root / "cboot.py")],
            cwd=str(c.root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, encoding="utf-8", errors="replace",
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
        )
        # cboot.py launches claude at the end, which fails in subprocess context.
        # Check stdout for bootstrap success instead of return code.
        if "passed" not in result.stdout:
            c.fail("DK01", "Dummy key: cboot ran successfully",
                   result.stderr[:200] if result.stderr else "no bootstrap output")
            return

        parent = c.load_json(".claude/settings.json")
        child = c.load_json("Testing/TestBench/.claude/settings.json")

        if parent and "_cascadeTest" in parent:
            c.ok("DK01", "Dummy key: present in parent after cboot")
        else:
            c.fail("DK01", "Dummy key: missing from parent after cboot")

        if child and "_cascadeTest" in child:
            c.ok("DK02", "Dummy key: present in child after cboot")
        else:
            c.fail("DK02", "Dummy key: missing from child after cboot")

    finally:
        # Clean up: remove dummy key and re-run cboot
        codex = json.loads(codex_path.read_text(encoding="utf-8"))
        codex.pop("_cascadeTest", None)
        codex_path.write_text(json.dumps(codex, indent=2) + "\n", encoding="utf-8")

        subprocess.run(
            [sys.executable, str(c.root / "cboot.py")],
            cwd=str(c.root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, encoding="utf-8", errors="replace",
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
        )

    # Verify cleanup
    parent_after = c.load_json(".claude/settings.json")
    child_after = c.load_json("Testing/TestBench/.claude/settings.json")

    if parent_after and "_cascadeTest" not in parent_after:
        c.ok("DK03", "Dummy key: removed from parent after cleanup")
    else:
        c.fail("DK03", "Dummy key: still in parent after cleanup")

    if child_after and "_cascadeTest" not in child_after:
        c.ok("DK04", "Dummy key: removed from child after cleanup")
    else:
        c.fail("DK04", "Dummy key: still in child after cleanup")


# ── Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cascade integrity check for TestBench")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="Apex project root (default: inferred from script location)")
    parser.add_argument("--with-roundtrip", action="store_true",
                        help="Run dummy key injection round-trip (modifies + restores codex settings)")
    args = parser.parse_args()

    root = args.project_root.resolve()

    print()
    print("  +-----------------------------------------+")
    print("  |     TestBench cascade integrity check    |")
    print("  +-----------------------------------------+")
    print()

    c = CascadeChecker(root)
    run_checks(c)

    if args.with_roundtrip:
        print()
        print("  -- Dummy key round-trip --")
        print()
        run_dummy_roundtrip(c)

    print()
    total = c.passed + c.failed + c.warned
    parts = [f"{c.passed}/{total} passed"]
    if c.failed:
        parts.append(f"{c.failed} failed")
    if c.warned:
        parts.append(f"{c.warned} warnings")
    print(f"  {', '.join(parts)}")
    print()

    sys.exit(1 if c.failed else 0)


if __name__ == "__main__":
    main()
