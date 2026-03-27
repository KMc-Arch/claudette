#!/usr/bin/env python3
"""Claudette2 bootstrap verifier. Validates that cboot.py produced correct outputs.

Pure Python, no LLM, runs in milliseconds. Exits 0 if all checks pass, 1 if any fail.

Usage:
    python ctest.py                # run all checks
    python ctest.py --project-root /path/to/project
"""

import argparse
import json
import sys
from pathlib import Path


# ── Paths (same as cboot.py) ─────────────────────────────────────────

def resolve_paths(root: Path):
    return {
        "root": root,
        "codex": root / ".codex",
        "state": root / ".state",
        "claude": root / ".claude",
        "hooks_dir": root / ".codex" / "implicit" / "01-infrastructural" / "01b-materialization" / "hooks",
        "templates": root / ".templates",
    }


# ── Test runner ──────────────────────────────────────────────────────

class TestRunner:
    def __init__(self):
        self.results = []
        self.pass_count = 0
        self.fail_count = 0
        self.warn_count = 0

    def ok(self, test_id, label):
        self.results.append(("PASS", test_id, label))
        self.pass_count += 1

    def fail(self, test_id, label, detail=""):
        self.results.append(("FAIL", test_id, label, detail))
        self.fail_count += 1

    def warn(self, test_id, label, detail=""):
        self.results.append(("WARN", test_id, label, detail))
        self.warn_count += 1

    def print_results(self):
        print()
        print("  ┌─────────────────────────────────────────────┐")
        print("  │           claudette2 verify (ctest)          │")
        print("  └─────────────────────────────────────────────┘")
        print()
        for entry in self.results:
            status = entry[0]
            test_id = entry[1]
            label = entry[2]
            if status == "PASS":
                print(f"  [PASS] {test_id} — {label}")
            elif status == "FAIL":
                detail = entry[3] if len(entry) > 3 else ""
                print(f"  [FAIL] {test_id} — {label}")
                if detail:
                    print(f"         {detail}")
            elif status == "WARN":
                detail = entry[3] if len(entry) > 3 else ""
                print(f"  [WARN] {test_id} — {label}")
                if detail:
                    print(f"         {detail}")
        print()
        total = self.pass_count + self.fail_count + self.warn_count
        summary = f"  {self.pass_count}/{total} passed"
        if self.warn_count:
            summary += f", {self.warn_count} warnings"
        if self.fail_count:
            summary += f", {self.fail_count} failed"
        print(summary)
        print()


# ── Checks ───────────────────────────────────────────────────────────

def check_skill_shims(t, p):
    """V01-V02: Skill shims exist and match explicit commands."""
    explicit_dir = p["codex"] / "explicit"
    skills_dir = p["claude"] / "skills"

    if not explicit_dir.is_dir():
        t.fail("V01", "Explicit commands directory exists", f"Not found: {explicit_dir}")
        return

    expected = sorted(d.name for d in explicit_dir.iterdir() if d.is_dir())

    if not skills_dir.is_dir():
        t.fail("V01", f"Skill shims directory exists ({len(expected)} expected)", f"Not found: {skills_dir}")
        return

    actual = sorted(d.name for d in skills_dir.iterdir() if d.is_dir())
    if set(expected) == set(actual):
        t.ok("V01", f"Skill shims: {len(actual)} commands match explicit entries")
    else:
        missing = set(expected) - set(actual)
        extra = set(actual) - set(expected)
        detail = ""
        if missing:
            detail += f"Missing: {', '.join(sorted(missing))}. "
        if extra:
            detail += f"Extra: {', '.join(sorted(extra))}."
        t.fail("V01", "Skill shims match explicit entries", detail)

    # Check each shim has SKILL.md
    all_have_shim = True
    for name in expected:
        shim_file = skills_dir / name / "SKILL.md"
        if not shim_file.is_file():
            t.fail("V02", f"Skill shim {name}/SKILL.md exists", "File not found")
            all_have_shim = False
    if all_have_shim:
        t.ok("V02", "All skill shims have SKILL.md")


def check_prefs_resolved(t, p):
    """V03-V05: prefs-resolved.json is valid and consistent."""
    resolved_file = p["state"] / "prefs-resolved.json"
    options_file = p["codex"] / "pref-options.json"

    if not resolved_file.is_file():
        t.warn("V03", "prefs-resolved.json exists", "Not found — cboot.py may not have run")
        return

    try:
        resolved = json.loads(resolved_file.read_text())
    except (json.JSONDecodeError, ValueError) as e:
        t.fail("V03", "prefs-resolved.json is valid JSON", str(e))
        return

    t.ok("V03", "prefs-resolved.json exists and is valid JSON")

    # Check _meta
    if "_meta" in resolved and "generated" in resolved["_meta"]:
        t.ok("V04", f"prefs-resolved.json has _meta.generated: {resolved['_meta']['generated']}")
    else:
        t.fail("V04", "prefs-resolved.json has _meta.generated", "Missing _meta or generated timestamp")

    # Check keys match schema
    if not options_file.is_file():
        t.warn("V05", "pref-options.json exists for key validation", "Not found")
        return

    try:
        options = json.loads(options_file.read_text())
    except (json.JSONDecodeError, ValueError):
        t.fail("V05", "pref-options.json is valid JSON", "Parse error")
        return

    resolved_keys = {k for k in resolved if k != "_meta"}
    option_keys = set(options.keys())
    if resolved_keys == option_keys:
        t.ok("V05", f"Resolved keys match schema ({len(resolved_keys)} keys)")
    else:
        missing = option_keys - resolved_keys
        extra = resolved_keys - option_keys
        detail = ""
        if missing:
            detail += f"Missing from resolved: {', '.join(sorted(missing))}. "
        if extra:
            detail += f"Extra in resolved: {', '.join(sorted(extra))}."
        t.fail("V05", "Resolved keys match pref-options schema", detail)


def check_settings_json(t, p):
    """V06-V09: settings.json is valid, generated, and hooks resolve."""
    settings_file = p["claude"] / "settings.json"

    if not settings_file.is_file():
        t.fail("V06", "settings.json exists", "Not found")
        return

    try:
        settings = json.loads(settings_file.read_text())
    except (json.JSONDecodeError, ValueError) as e:
        t.fail("V06", "settings.json is valid JSON", str(e))
        return

    t.ok("V06", "settings.json exists and is valid JSON")

    # GENERATED marker
    comment = settings.get("$comment", "")
    if "GENERATED" in comment:
        t.ok("V07", "settings.json has GENERATED marker")
    else:
        t.warn("V07", "settings.json has GENERATED marker", f"$comment: {comment[:80]}")

    # Count hooks and verify paths
    hook_commands = []
    hooks_section = settings.get("hooks", {})
    for event_name, event_entries in hooks_section.items():
        for entry in event_entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd:
                    hook_commands.append(cmd)

    if len(hook_commands) == 0:
        t.warn("V08", "settings.json has 0 hook registrations", "Expected 13+")
    else:
        t.ok("V08", f"settings.json has {len(hook_commands)} hook registrations")

    # Verify each hook path resolves
    broken = []
    for cmd in hook_commands:
        if cmd.startswith("bash "):
            script_path = p["root"] / cmd[5:]
            if not script_path.is_file():
                broken.append(cmd[5:])

    if broken:
        t.fail("V09", "All hook paths resolve to existing files", f"Missing: {', '.join(broken)}")
    else:
        t.ok("V09", f"All {len(hook_commands)} hook script paths resolve")


def check_settings_local(t, p):
    """V10-V12: settings.local.json exists with correct absolute path."""
    settings_local = p["claude"] / "settings.local.json"

    if not settings_local.is_file():
        t.warn("V10", "settings.local.json exists", "Not found — auto-memory may be leaking")
        return

    try:
        local = json.loads(settings_local.read_text())
    except (json.JSONDecodeError, ValueError) as e:
        t.fail("V10", "settings.local.json is valid JSON", str(e))
        return

    t.ok("V10", "settings.local.json exists and is valid JSON")

    auto_mem = local.get("autoMemoryDirectory", "")
    if not auto_mem:
        t.fail("V11", "autoMemoryDirectory is set", "Key missing or empty")
        return

    # Check absolute
    is_absolute = auto_mem.startswith("/") or (len(auto_mem) >= 3 and auto_mem[1] == ":" and auto_mem[2] in "/\\")
    if not is_absolute:
        t.fail("V11", "autoMemoryDirectory is absolute path", f"Got relative: {auto_mem}")
        return

    t.ok("V11", f"autoMemoryDirectory is absolute")

    # Check points to .state/memory
    normalized = auto_mem.replace("\\", "/").rstrip("/")
    if normalized.endswith(".state/memory"):
        t.ok("V12", "autoMemoryDirectory points to .state/memory")
    else:
        t.fail("V12", "autoMemoryDirectory points to .state/memory", f"Got: {auto_mem}")


def check_scaffolding(t, p):
    """V13: All expected directories exist."""
    expected_dirs = [
        p["state"] / "memory",
        p["state"] / "work",
        p["state"] / "tests" / "boot",
        p["state"] / "tests" / "audits",
        p["state"] / "tests" / "compliance",
        p["state"] / "tests" / "explicit" / "test-safe",
        p["state"] / "tests" / "explicit" / "test-burn",
        p["state"] / "tests" / "explicit" / "scrub",
        p["state"] / "tests" / "reflexive" / "contract-conformance",
        p["state"] / "traces",
        p["state"] / "pauses",
        p["state"] / "bundles",
        p["claude"] / "skills",
    ]
    missing = [str(d.relative_to(p["root"])) for d in expected_dirs if not d.is_dir()]
    if missing:
        t.fail("V13", f"Scaffolding: {len(expected_dirs)} directories exist", f"Missing: {', '.join(missing)}")
    else:
        t.ok("V13", f"Scaffolding: all {len(expected_dirs)} directories exist")


def check_structure_counts(t, p):
    """V14-V15: Structure counts for hooks, commands, etc."""
    hooks_dir = p["hooks_dir"]
    hooks = [f for f in hooks_dir.iterdir() if f.suffix == ".sh"] if hooks_dir.is_dir() else []
    explicit = [d for d in (p["codex"] / "explicit").iterdir() if d.is_dir()] if (p["codex"] / "explicit").is_dir() else []
    reactive = [d for d in (p["codex"] / "reactive").iterdir() if d.is_dir()] if (p["codex"] / "reactive").is_dir() else []
    reflexive = [d for d in (p["codex"] / "reflexive").iterdir() if d.is_dir()] if (p["codex"] / "reflexive").is_dir() else []

    t.ok("V14", f"Structure: {len(hooks)} hooks, {len(explicit)} commands, {len(reactive)} reactive, {len(reflexive)} reflexive")

    # start.md presence in codex tree
    codex_dirs_missing_start = []
    for d in p["codex"].rglob("*"):
        if not d.is_dir():
            continue
        # Skip runtime output pattern dirs
        if d.parent.name in {"pauses", "bundles", "boot", "compliance", "contract-conformance", "selftest", "scrub", "audits", "test-safe", "test-burn"}:
            continue
        if not (d / "start.md").is_file():
            codex_dirs_missing_start.append(str(d.relative_to(p["root"])))

    if codex_dirs_missing_start:
        t.warn("V15", f"Codex manifests: {len(codex_dirs_missing_start)} dirs missing start.md",
               ", ".join(codex_dirs_missing_start[:5]))
    else:
        codex_dir_count = sum(1 for d in p["codex"].rglob("*") if d.is_dir())
        t.ok("V15", f"Codex manifests: all directories have start.md")


def check_critical_files(t, p):
    """V16: Critical files that must exist."""
    critical = {
        "CLAUDE.md": p["root"] / "CLAUDE.md",
        "cboot.py": p["root"] / "cboot.py",
        ".codex/start.md": p["codex"] / "start.md",
        ".state/start.md": p["state"] / "start.md",
        ".gitignore": p["root"] / ".gitignore",
        ".templates/child/CLAUDE.md": p["templates"] / "child" / "CLAUDE.md",
    }
    missing = [name for name, path in critical.items() if not path.is_file()]
    if missing:
        t.fail("V16", "Critical files exist", f"Missing: {', '.join(missing)}")
    else:
        t.ok("V16", f"Critical files: all {len(critical)} present")


def check_scripts(t, p):
    """V17: Python scripts exist."""
    scripts = {
        "scrub.py": p["codex"] / "explicit" / "scrub" / "scrub.py",
        "purge.py": p["codex"] / "explicit" / "purge" / "purge.py",
        "bootstrap-child.py": p["codex"] / "explicit" / "new-project" / "bootstrap-child.py",
    }
    missing = [name for name, path in scripts.items() if not path.is_file()]
    if missing:
        t.fail("V17", "Python scripts exist", f"Missing: {', '.join(missing)}")
    else:
        t.ok("V17", f"Scripts: all {len(scripts)} present")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Verify Claudette2 bootstrap outputs.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent,
                        help="Project root (default: script directory)")
    args = parser.parse_args()

    root = args.project_root.resolve()
    p = resolve_paths(root)
    t = TestRunner()

    check_critical_files(t, p)
    check_scaffolding(t, p)
    check_structure_counts(t, p)
    check_skill_shims(t, p)
    check_prefs_resolved(t, p)
    check_settings_json(t, p)
    check_settings_local(t, p)
    check_scripts(t, p)

    t.print_results()
    sys.exit(1 if t.fail_count > 0 else 0)


if __name__ == "__main__":
    main()
