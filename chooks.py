#!/usr/bin/env python3
"""Claudette2 hook behavioral test harness.

Feeds mock tool-call JSON to each hook script via stdin, validates exit codes
and stdout/stderr. Pure Python + subprocess, no LLM, runs in seconds.
Requires Python 3.9+.

Designed for bidirectional coverage verification with cboot.py:
- HOOK_SCRIPTS: canonical list of all hook .sh files
- TEST_REGISTRY: maps hook name -> list of test functions
- At the end: verifies every hook has tests and every test has a hook.

Usage:
    python chooks.py                     # run all hook tests
    python chooks.py --project-root /path/to/project
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOOKS_REL = ".codex/implicit/01-infrastructural/01b-materialization/hooks"
HOOKS_DIR = ROOT / HOOKS_REL

# ── Canonical hook list (must match cboot.py and hooks/start.md) ─────

HOOK_SCRIPTS = [
    "api-guard.sh",
    "audit-immutability-guard.sh",
    "boot-inject.sh",
    "claude-md-immutability-guard.sh",
    "codex-edit-notify.sh",
    "containment-guard.sh",
    "gravity-guard.sh",
    "memory-redirect-check.sh",
    "prefs-staleness-check.sh",
    "session-close.sh",
    "subagent-conformance.sh",
    "trace-logger.sh",
    "visibility-guard.sh",
]

# ── Test infrastructure ──────────────────────────────────────────────

TEST_REGISTRY: dict[str, list[str]] = {}  # hook_name -> [test_name, ...]


def register_test(hook_name: str):
    """Decorator to register a test function against a hook."""
    def decorator(func):
        TEST_REGISTRY.setdefault(hook_name, []).append(func.__name__)
        func._hook_name = hook_name
        return func
    return decorator


class HookTestRunner:
    def __init__(self, project_root: Path):
        self.root = project_root.resolve()
        self.hooks_dir = self.root / HOOKS_REL
        self.results: list[tuple] = []
        self.pass_count = 0
        self.fail_count = 0

    def run_hook(self, script_name: str, stdin_data: str = "",
                 env_overrides: dict | None = None) -> tuple[int, str, str]:
        """Run a hook script with given stdin and return (exit_code, stdout, stderr)."""
        script = self.hooks_dir / script_name
        if not script.is_file():
            return (-1, "", f"Script not found: {script}")

        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.root)
        if env_overrides:
            env.update(env_overrides)

        result = subprocess.run(
            ["bash", str(script)],
            input=stdin_data,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            env=env,
            cwd=self.root,
        )
        return (result.returncode, result.stdout, result.stderr)

    def ok(self, test_name: str, label: str):
        self.results.append(("PASS", test_name, label))
        self.pass_count += 1

    def fail(self, test_name: str, label: str, detail: str = ""):
        self.results.append(("FAIL", test_name, label, detail))
        self.fail_count += 1

    def assert_exit(self, test_name: str, label: str, actual: int, expected: int,
                    stderr: str = ""):
        if actual == expected:
            self.ok(test_name, f"{label} (exit {actual})")
        else:
            self.fail(test_name, label, f"Expected exit {expected}, got {actual}. stderr: {stderr[:200]}")

    def assert_stdout_contains(self, test_name: str, label: str, stdout: str, substring: str):
        if substring in stdout:
            self.ok(test_name, label)
        else:
            self.fail(test_name, label, f"stdout missing '{substring}'. Got: {stdout[:200]}")

    def print_results(self):
        print()
        print("  ┌─────────────────────────────────────────────┐")
        print("  │        claudette2 hook tests (chooks)        │")
        print("  └─────────────────────────────────────────────┘")
        print()
        for entry in self.results:
            status, test_name, label = entry[0], entry[1], entry[2]
            if status == "PASS":
                print(f"  [PASS] {test_name} — {label}")
            else:
                detail = entry[3] if len(entry) > 3 else ""
                print(f"  [FAIL] {test_name} — {label}")
                if detail:
                    print(f"         {detail}")
        print()
        total = self.pass_count + self.fail_count
        print(f"  {self.pass_count}/{total} passed" +
              (f", {self.fail_count} failed" if self.fail_count else ""))
        print()


# ── Tool-call JSON helpers ───────────────────────────────────────────

def make_tool_json(**kwargs) -> str:
    return json.dumps(kwargs)


def read_tool(file_path: str) -> str:
    return make_tool_json(tool_name="Read", file_path=file_path)


def write_tool(file_path: str) -> str:
    return make_tool_json(tool_name="Write", file_path=file_path)


def bash_tool(command: str) -> str:
    return make_tool_json(tool_name="Bash", command=command)


def grep_tool(pattern: str, path: str = "", glob: str = "") -> str:
    d = {"tool_name": "Grep", "pattern": pattern}
    if path:
        d["path"] = path
    if glob:
        d["glob"] = glob
    return d if isinstance(d, str) else json.dumps(d)


# ── Hook tests ───────────────────────────────────────────────────────

# -- visibility-guard.sh --

@register_test("visibility-guard.sh")
def test_visibility_blocks_underscore_read(t: HookTestRunner):
    code, out, err = t.run_hook("visibility-guard.sh", read_tool("/project/_secret/data.txt"))
    t.assert_exit("VG01", "Blocks read of _-prefixed path", code, 2, err)

@register_test("visibility-guard.sh")
def test_visibility_allows_normal_read(t: HookTestRunner):
    code, out, err = t.run_hook("visibility-guard.sh", read_tool("/project/.codex/start.md"))
    t.assert_exit("VG02", "Allows read of normal path", code, 0, err)

@register_test("visibility-guard.sh")
def test_visibility_blocks_underscore_in_bash(t: HookTestRunner):
    code, out, err = t.run_hook("visibility-guard.sh", bash_tool("cat _hidden/file.txt"))
    t.assert_exit("VG03", "Blocks bash with _-prefixed path", code, 2, err)

@register_test("visibility-guard.sh")
def test_visibility_allows_normal_bash(t: HookTestRunner):
    code, out, err = t.run_hook("visibility-guard.sh", bash_tool("ls .codex/"))
    t.assert_exit("VG04", "Allows bash with normal path", code, 0, err)

@register_test("visibility-guard.sh")
def test_visibility_blocks_nested_underscore(t: HookTestRunner):
    code, out, err = t.run_hook("visibility-guard.sh", read_tool("/project/subdir/_private/file.md"))
    t.assert_exit("VG05", "Blocks nested _-prefixed path segment", code, 2, err)


# -- containment-guard.sh --

@register_test("containment-guard.sh")
def test_containment_blocks_outside_write(t: HookTestRunner):
    code, out, err = t.run_hook("containment-guard.sh", write_tool("/tmp/outside.txt"))
    t.assert_exit("CG01", "Blocks write outside project root", code, 2, err)

@register_test("containment-guard.sh")
def test_containment_allows_inside_write(t: HookTestRunner):
    inside_path = str(t.root / ".state" / "memory" / "test.md")
    code, out, err = t.run_hook("containment-guard.sh", write_tool(inside_path))
    t.assert_exit("CG02", "Allows write inside project root", code, 0, err)

@register_test("containment-guard.sh")
def test_containment_allows_no_file_path(t: HookTestRunner):
    code, out, err = t.run_hook("containment-guard.sh", bash_tool("echo hello"))
    t.assert_exit("CG03", "Allows tool call without file_path", code, 0, err)

@register_test("containment-guard.sh")
def test_containment_allows_relative_inside(t: HookTestRunner):
    code, out, err = t.run_hook("containment-guard.sh", write_tool(".state/memory/test.md"))
    t.assert_exit("CG04", "Allows relative path (resolves inside ^)", code, 0, err)


# -- gravity-guard.sh --

@register_test("gravity-guard.sh")
def test_gravity_blocks_parent_state_write(t: HookTestRunner):
    parent_state = str(t.root.parent / ".state" / "memory" / "leak.md")
    code, out, err = t.run_hook("gravity-guard.sh", write_tool(parent_state))
    t.assert_exit("GG01", "Blocks .state/ write outside project root", code, 2, err)

@register_test("gravity-guard.sh")
def test_gravity_allows_local_state_write(t: HookTestRunner):
    local_state = str(t.root / ".state" / "memory" / "ok.md")
    code, out, err = t.run_hook("gravity-guard.sh", write_tool(local_state))
    t.assert_exit("GG02", "Allows .state/ write inside project root", code, 0, err)

@register_test("gravity-guard.sh")
def test_gravity_allows_non_state_write(t: HookTestRunner):
    code, out, err = t.run_hook("gravity-guard.sh", write_tool(str(t.root / "README.md")))
    t.assert_exit("GG03", "Allows non-.state/ write (not its concern)", code, 0, err)


# -- api-guard.sh --

@register_test("api-guard.sh")
def test_api_blocks_anthropic_import(t: HookTestRunner):
    code, out, err = t.run_hook("api-guard.sh", bash_tool("pip install anthropic"))
    t.assert_exit("AG01", "Blocks pip install anthropic", code, 2, err)

@register_test("api-guard.sh")
def test_api_blocks_sdk_reference(t: HookTestRunner):
    code, out, err = t.run_hook("api-guard.sh", bash_tool("python -c 'import anthropic'"))
    t.assert_exit("AG02", "Blocks python import anthropic", code, 2, err)

@register_test("api-guard.sh")
def test_api_blocks_api_url(t: HookTestRunner):
    code, out, err = t.run_hook("api-guard.sh", bash_tool("curl https://api.anthropic.com/v1/messages"))
    t.assert_exit("AG03", "Blocks curl to api.anthropic.com", code, 2, err)

@register_test("api-guard.sh")
def test_api_allows_normal_bash(t: HookTestRunner):
    code, out, err = t.run_hook("api-guard.sh", bash_tool("ls -la"))
    t.assert_exit("AG04", "Allows normal bash command", code, 0, err)

@register_test("api-guard.sh")
def test_api_allows_no_command(t: HookTestRunner):
    code, out, err = t.run_hook("api-guard.sh", make_tool_json(tool_name="Bash"))
    t.assert_exit("AG05", "Allows tool call without command field", code, 0, err)


# -- audit-immutability-guard.sh --

@register_test("audit-immutability-guard.sh")
def test_audit_immutability_blocks_finding_edit(t: HookTestRunner):
    # Create a temp audit folder so the "existing and non-empty" check passes
    audit_dir = t.root / ".state" / "tests" / "audits" / "20260326-1200"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "architecture.md").write_text("finding")
    try:
        target = str(audit_dir / "architecture.md")
        code, out, err = t.run_hook("audit-immutability-guard.sh", write_tool(target))
        t.assert_exit("AI01", "Blocks write to existing audit finding", code, 2, err)
    finally:
        import shutil
        shutil.rmtree(audit_dir, ignore_errors=True)

@register_test("audit-immutability-guard.sh")
def test_audit_immutability_allows_decisions(t: HookTestRunner):
    audit_dir = t.root / ".state" / "tests" / "audits" / "20260326-1201"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "architecture.md").write_text("finding")
    try:
        target = str(audit_dir / "decisions.md")
        code, out, err = t.run_hook("audit-immutability-guard.sh", write_tool(target))
        t.assert_exit("AI02", "Allows decisions.md in audit folder", code, 0, err)
    finally:
        import shutil
        shutil.rmtree(audit_dir, ignore_errors=True)

@register_test("audit-immutability-guard.sh")
def test_audit_immutability_allows_non_audit_write(t: HookTestRunner):
    target = str(t.root / ".state" / "memory" / "test.md")
    code, out, err = t.run_hook("audit-immutability-guard.sh", write_tool(target))
    t.assert_exit("AI03", "Allows write outside audit folders", code, 0, err)


# -- claude-md-immutability-guard.sh --

@register_test("claude-md-immutability-guard.sh")
def test_claude_md_blocks_root_claude_md(t: HookTestRunner):
    target = str(t.root / "CLAUDE.md")
    code, out, err = t.run_hook("claude-md-immutability-guard.sh", write_tool(target))
    t.assert_exit("CM01", "Blocks write to root CLAUDE.md", code, 2, err)

@register_test("claude-md-immutability-guard.sh")
def test_claude_md_allows_other_files(t: HookTestRunner):
    target = str(t.root / ".codex" / "start.md")
    code, out, err = t.run_hook("claude-md-immutability-guard.sh", write_tool(target))
    t.assert_exit("CM02", "Allows write to non-CLAUDE.md files", code, 0, err)

@register_test("claude-md-immutability-guard.sh")
def test_claude_md_allows_child_claude_md(t: HookTestRunner):
    target = str(t.root / "ChildProject" / "CLAUDE.md")
    code, out, err = t.run_hook("claude-md-immutability-guard.sh", write_tool(target))
    t.assert_exit("CM03", "Allows write to child project CLAUDE.md", code, 0, err)


# -- boot-inject.sh --

@register_test("boot-inject.sh")
def test_boot_inject_outputs_boot_sequence(t: HookTestRunner):
    code, out, err = t.run_hook("boot-inject.sh")
    t.assert_exit("BI01", "Exits 0", code, 0, err)
    t.assert_stdout_contains("BI02", "Output contains BOOT SEQUENCE", out, "BOOT SEQUENCE")
    t.assert_stdout_contains("BI03", "Output contains command index", out, "Available explicit commands")


# -- prefs-staleness-check.sh --

@register_test("prefs-staleness-check.sh")
def test_prefs_staleness_missing_resolved(t: HookTestRunner):
    # If prefs-resolved.json doesn't exist, should note it
    resolved = t.root / ".state" / "prefs-resolved.json"
    existed = resolved.exists()
    if existed:
        resolved.rename(resolved.with_suffix(".json.bak"))
    try:
        code, out, err = t.run_hook("prefs-staleness-check.sh")
        t.assert_exit("PS01", "Exits 0 when resolved missing", code, 0, err)
        t.assert_stdout_contains("PS02", "Notes missing prefs-resolved.json", out, "does not exist")
    finally:
        if existed:
            resolved.with_suffix(".json.bak").rename(resolved)

@register_test("prefs-staleness-check.sh")
def test_prefs_staleness_clean(t: HookTestRunner):
    # If resolved exists and is newer than sources, should produce no warning
    resolved = t.root / ".state" / "prefs-resolved.json"
    if resolved.exists():
        code, out, err = t.run_hook("prefs-staleness-check.sh")
        t.assert_exit("PS03", "Exits 0 when prefs are fresh", code, 0, err)
        if "WARNING" not in out and "stale" not in out.lower():
            t.ok("PS04", "No staleness warning when prefs are fresh")
        else:
            t.fail("PS04", "No staleness warning expected", f"Got: {out[:200]}")
    else:
        t.ok("PS03", "Exits 0 (skipped — no resolved file)")
        t.ok("PS04", "No staleness check needed (skipped)")


# -- memory-redirect-check.sh --

@register_test("memory-redirect-check.sh")
def test_memory_redirect_missing_local(t: HookTestRunner):
    settings_local = t.root / ".claude" / "settings.local.json"
    existed = settings_local.exists()
    if existed:
        settings_local.rename(settings_local.with_suffix(".json.bak"))
    try:
        code, out, err = t.run_hook("memory-redirect-check.sh")
        t.assert_exit("MR01", "Exits 0 when settings.local.json missing", code, 0, err)
        t.assert_stdout_contains("MR02", "Warns about missing config", out, "AUTO-MEMORY NOT CONFIGURED")
    finally:
        if existed:
            settings_local.with_suffix(".json.bak").rename(settings_local)

@register_test("memory-redirect-check.sh")
def test_memory_redirect_correct_path(t: HookTestRunner):
    settings_local = t.root / ".claude" / "settings.local.json"
    if settings_local.exists():
        try:
            local = json.loads(settings_local.read_text())
            mem_path = local.get("autoMemoryDirectory", "")
            expected = str(t.root / ".state" / "memory").replace("\\", "/")
            if mem_path == expected:
                code, out, err = t.run_hook("memory-redirect-check.sh")
                t.assert_exit("MR03", "Exits 0 when path is correct", code, 0, err)
                if "AUTO-MEMORY" not in out and "⚠" not in out:
                    t.ok("MR04", "No warning when path is correct")
                else:
                    t.fail("MR04", "No warning expected for correct path", f"Got: {out[:200]}")
            else:
                t.ok("MR03", "Skipped — path not yet configured correctly")
                t.ok("MR04", "Skipped — path not yet configured correctly")
        except (json.JSONDecodeError, ValueError):
            t.ok("MR03", "Skipped — settings.local.json malformed")
            t.ok("MR04", "Skipped — settings.local.json malformed")
    else:
        t.ok("MR03", "Skipped — settings.local.json doesn't exist")
        t.ok("MR04", "Skipped — settings.local.json doesn't exist")


# -- codex-edit-notify.sh --

@register_test("codex-edit-notify.sh")
def test_codex_edit_notifies_on_py(t: HookTestRunner):
    code, out, err = t.run_hook("codex-edit-notify.sh",
                                 make_tool_json(file_path=".codex/explicit/scrub/scrub.py"))
    t.assert_exit("CE01", "Exits 0", code, 0, err)
    t.assert_stdout_contains("CE02", "Notifies about codex executable edit", out, "CODEX EXECUTABLE EDITED")

@register_test("codex-edit-notify.sh")
def test_codex_edit_silent_on_md(t: HookTestRunner):
    code, out, err = t.run_hook("codex-edit-notify.sh",
                                 make_tool_json(file_path=".codex/explicit/scrub/start.md"))
    t.assert_exit("CE03", "Exits 0 for .md file", code, 0, err)
    if "CODEX EXECUTABLE EDITED" not in out:
        t.ok("CE04", "No notification for non-executable codex file")
    else:
        t.fail("CE04", "Should not notify for .md files", f"Got: {out[:200]}")

@register_test("codex-edit-notify.sh")
def test_codex_edit_silent_on_non_codex(t: HookTestRunner):
    code, out, err = t.run_hook("codex-edit-notify.sh",
                                 make_tool_json(file_path=".state/memory/user.md"))
    t.assert_exit("CE05", "Exits 0 for non-codex file", code, 0, err)
    if "CODEX EXECUTABLE EDITED" not in out:
        t.ok("CE06", "No notification for non-codex file")
    else:
        t.fail("CE06", "Should not notify for non-codex files", f"Got: {out[:200]}")


# -- trace-logger.sh --

@register_test("trace-logger.sh")
def test_trace_logger_writes_trace(t: HookTestRunner):
    code, out, err = t.run_hook("trace-logger.sh",
                                 make_tool_json(tool_name="Read", file_path=".codex/start.md"))
    t.assert_exit("TL01", "Exits 0", code, 0, err)
    # Check trace file was written
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trace_file = t.root / ".state" / "traces" / f"{today}.trace"
    if trace_file.exists() and "TOOL: Read" in trace_file.read_text():
        t.ok("TL02", "Trace entry written for Read tool call")
    else:
        t.fail("TL02", "Trace entry written", "Not found in trace file")


# -- session-close.sh --

@register_test("session-close.sh")
def test_session_close_outputs_governance(t: HookTestRunner):
    code, out, err = t.run_hook("session-close.sh")
    t.assert_exit("SC01", "Exits 0", code, 0, err)
    t.assert_stdout_contains("SC02", "Output contains SESSION CLOSING", out, "SESSION CLOSING")
    t.assert_stdout_contains("SC03", "Output mentions state-abstract", out, "state-abstract")


# -- subagent-conformance.sh --

@register_test("subagent-conformance.sh")
def test_subagent_conformance_outputs_checklist(t: HookTestRunner):
    code, out, err = t.run_hook("subagent-conformance.sh")
    t.assert_exit("SA01", "Exits 0", code, 0, err)
    t.assert_stdout_contains("SA02", "Output contains SUBAGENT COMPLETE", out, "SUBAGENT COMPLETE")


# ── Coverage verification ────────────────────────────────────────────

def verify_coverage(t: HookTestRunner):
    """Check that every hook has tests and every test has a hook."""
    tested_hooks = set(TEST_REGISTRY.keys())
    all_hooks = set(HOOK_SCRIPTS)

    untested = all_hooks - tested_hooks
    orphaned = tested_hooks - all_hooks

    if untested:
        t.fail("COV1", "All hooks have tests", f"Untested hooks: {', '.join(sorted(untested))}")
    else:
        t.ok("COV1", f"All {len(all_hooks)} hooks have tests")

    if orphaned:
        t.fail("COV2", "All tests have hooks", f"Orphaned tests for: {', '.join(sorted(orphaned))}")
    else:
        t.ok("COV2", f"All test registrations map to existing hooks")


# ── Public API for cboot.py ──────────────────────────────────────────

def get_hook_coverage() -> tuple[set, set, set]:
    """Return (all_hooks, tested_hooks, untested_hooks) for external verification."""
    # Force test registration by collecting all test functions
    all_tests = [v for v in globals().values() if callable(v) and hasattr(v, '_hook_name')]
    all_hooks = set(HOOK_SCRIPTS)
    tested_hooks = set(TEST_REGISTRY.keys())
    untested = all_hooks - tested_hooks
    return all_hooks, tested_hooks, untested


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test Claudette2 hook scripts.")
    parser.add_argument("--project-root", type=Path, default=ROOT,
                        help="Project root (default: script directory)")
    args = parser.parse_args()

    t = HookTestRunner(args.project_root)

    # Collect and run all registered test functions
    test_funcs = sorted(
        [v for v in globals().values() if callable(v) and hasattr(v, '_hook_name')],
        key=lambda f: f.__name__
    )

    for func in test_funcs:
        try:
            func(t)
        except Exception as e:
            t.fail(func.__name__, f"Exception in {func.__name__}", str(e))

    # Coverage verification
    verify_coverage(t)

    t.print_results()
    sys.exit(1 if t.fail_count > 0 else 0)


if __name__ == "__main__":
    main()
