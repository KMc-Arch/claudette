#!/usr/bin/env python3
"""Claudette2 boot wrapper. Run this instead of `claude` directly.

Materializes all generated artifacts, validates configuration, writes a
bootstrap report to .state/tests/boot/, prints it to terminal, then
launches Claude Code.

Usage:
    python cboot.py            # boot with default args
    python cboot.py --resume   # pass args through to claude
"""

import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CODEX = ROOT / ".codex"
STATE = ROOT / ".state"
CLAUDE = ROOT / ".claude"

HOOKS_REL = ".codex/implicit/01-infrastructural/01b-materialization/hooks"
HOOKS_DIR = ROOT / HOOKS_REL

PREBOOT_DIR = CODEX / "implicit" / "00-preboot"


# ── Utilities ────────────────────────────────────────────────────────


def _load_module(path):
    """Load a Python module from an arbitrary filesystem path."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")


def hook_cmd(script_name, interpreter="bash"):
    """Return the hook command string for a script in the hooks dir."""
    abs_path = (HOOKS_DIR / script_name).as_posix()
    return f'{interpreter} "{abs_path}"'


class BootReport:
    """Collects bootstrap results for terminal output and file logging."""

    def __init__(self):
        self.entries = []
        self.warnings = []
        self.errors = []

    def ok(self, label):
        self.entries.append(("OK", label))

    def warn(self, label, detail=""):
        self.entries.append(("WARN", label))
        self.warnings.append(f"{label}: {detail}" if detail else label)

    def fail(self, label, detail=""):
        self.entries.append(("FAIL", label))
        self.errors.append(f"{label}: {detail}" if detail else label)

    def to_terminal(self):
        lines = []
        lines.append("")
        lines.append("  ┌─────────────────────────────────────────────┐")
        lines.append("  │         claudette2 bootstrap report         │")
        lines.append("  └─────────────────────────────────────────────┘")
        lines.append("")
        for status, label in self.entries:
            if status == "OK":
                lines.append(f"  [OK]   {label}")
            elif status == "WARN":
                lines.append(f"  [WARN] {label}")
            elif status == "FAIL":
                lines.append(f"  [FAIL] {label}")
        lines.append("")
        if self.warnings:
            lines.append("  Warnings:")
            for w in self.warnings:
                lines.append(f"    - {w}")
            lines.append("")
        if self.errors:
            lines.append("  Errors:")
            for e in self.errors:
                lines.append(f"    ! {e}")
            lines.append("")
        ok = sum(1 for s, _ in self.entries if s == "OK")
        total = len(self.entries)
        lines.append(f"  {ok}/{total} passed" +
                      (f", {len(self.warnings)} warnings" if self.warnings else "") +
                      (f", {len(self.errors)} errors" if self.errors else ""))
        lines.append("")
        return "\n".join(lines)

    def to_markdown(self):
        lines = []
        lines.append(f"# Bootstrap Report — {now_iso()}")
        lines.append("")
        lines.append("| Status | Check |")
        lines.append("|--------|-------|")
        for status, label in self.entries:
            lines.append(f"| {status} | {label} |")
        lines.append("")
        if self.warnings:
            lines.append("## Warnings")
            for w in self.warnings:
                lines.append(f"- {w}")
            lines.append("")
        if self.errors:
            lines.append("## Errors")
            for e in self.errors:
                lines.append(f"- {e}")
            lines.append("")
        return "\n".join(lines)


# ── Pre-flight ───────────────────────────────────────────────────────

def preflight(report):
    """Verify critical files exist before doing anything."""
    critical = [
        ROOT / "CLAUDE.md",
        CODEX / "start.md",
        STATE / "start.md",
    ]
    for f in critical:
        if f.exists():
            report.ok(f"Pre-flight: {f.relative_to(ROOT)} exists")
        else:
            report.fail(f"Pre-flight: {f.relative_to(ROOT)} MISSING",
                        "Cannot boot without this file")
            return False
    return True


# ── Directory scaffolding ────────────────────────────────────────────

def scaffold(report):
    """Ensure all .state/ subdirectories exist."""
    dirs = [
        STATE / "memory",
        STATE / "work",
        STATE / "tests" / "boot",
        STATE / "tests" / "audits",
        STATE / "tests" / "compliance",
        STATE / "tests" / "reflexive" / "contract-conformance",
        STATE / "tests" / "explicit" / "test-safe",
        STATE / "tests" / "explicit" / "test-burn",
        STATE / "tests" / "explicit" / "scrub",
        STATE / "traces",
        STATE / "pauses",
        STATE / "bundles",
        CLAUDE / "skills",
    ]
    created = 0
    for d in dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created += 1
    report.ok(f"Scaffolding: {len(dirs)} directories verified ({created} created)")


# ── Structure check ──────────────────────────────────────────────────

def check_structure(report):
    """Report structure counts and verify start.md presence in codex/state dirs."""

    # -- Count structure --
    hooks_dir = ROOT / HOOKS_REL
    hooks = [f for f in hooks_dir.iterdir() if f.suffix == ".sh"] if hooks_dir.exists() else []
    explicit = [d for d in (CODEX / "explicit").iterdir() if d.is_dir()] if (CODEX / "explicit").exists() else []
    reactive = [d for d in (CODEX / "reactive").iterdir() if d.is_dir()] if (CODEX / "reactive").exists() else []
    reflexive = [d for d in (CODEX / "reflexive").iterdir() if d.is_dir()] if (CODEX / "reflexive").exists() else []
    memory_files = [f for f in (STATE / "memory").iterdir() if f.suffix == ".md" and f.name != "start.md"] if (STATE / "memory").exists() else []
    work_files = [f for f in (STATE / "work").iterdir() if f.suffix == ".md" and f.name != "start.md"] if (STATE / "work").exists() else []
    specs = [f for f in (CODEX / "specs").iterdir() if f.suffix == ".md" and f.name != "start.md"] if (CODEX / "specs").exists() else []

    report.ok(f"Structure: {len(hooks)} hooks, {len(explicit)} commands, "
              f"{len(reactive)} reactive, {len(reflexive)} reflexive")
    report.ok(f"Structure: {len(memory_files)} memory files, {len(work_files)} work files, "
              f"{len(specs)} specs")

    # Check implicit tiers
    implicit_dir = CODEX / "implicit"
    if implicit_dir.exists():
        for tier in sorted(implicit_dir.iterdir()):
            if tier.is_dir():
                entries = [e for e in tier.iterdir() if e.name != "start.md"]
                if not entries:
                    report.ok(f"Structure: {tier.name} (empty tier)")
                else:
                    report.ok(f"Structure: {tier.name} — {len(entries)} entries")

    # -- start.md presence check --
    # Directories that SHOULD have a start.md: everything under .codex/ and
    # top-level .state/ subdirs. Exclude runtime-only output dirs and .claude/.
    EXCLUDE = {
        CLAUDE,
        ROOT / ".templates",
    }
    # Patterns for runtime-created subdirs that won't have start.md
    RUNTIME_PATTERNS = {"pauses", "bundles", "boot", "compliance", "contract-conformance",
                        "selftest", "scrub", "audits"}

    missing = []

    def check_tree(base):
        if not base.exists():
            return
        for d in sorted(base.rglob("*")):
            if not d.is_dir():
                continue
            # Skip excluded dirs and their children
            if any(d == ex or ex in d.parents for ex in EXCLUDE):
                continue
            # Skip _-prefixed dirs (invisible by convention)
            if d.name.startswith("_"):
                continue
            # Skip runtime output subdirs (timestamped folders, individual pauses, etc.)
            # These are created at runtime and don't need start.md
            parent_name = d.parent.name
            if parent_name in RUNTIME_PATTERNS:
                continue
            if not (d / "start.md").exists():
                missing.append(d.relative_to(ROOT))

    check_tree(CODEX)
    # For .state/, only check top-level subdirs (not runtime output dirs)
    if STATE.exists():
        for d in sorted(STATE.iterdir()):
            if d.is_dir() and d not in EXCLUDE and not (d / "start.md").exists():
                missing.append(d.relative_to(ROOT))

    if missing:
        for m in missing:
            report.warn(f"Manifest: {m}/ missing start.md")
    else:
        # Count how many we checked
        codex_dirs = sum(1 for d in CODEX.rglob("*") if d.is_dir() and
                         not any(d == ex or ex in d.parents for ex in EXCLUDE))
        state_dirs = sum(1 for d in STATE.iterdir() if d.is_dir() and d not in EXCLUDE)
        total = codex_dirs + state_dirs
        report.ok(f"Manifests: {total} directories have start.md")


# ── Skill shims ──────────────────────────────────────────────────────

def extract_command_description(start_md: Path) -> str:
    """Extract short-desc from start.md frontmatter."""
    try:
        text = start_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return ""
        end = text.find("---", 3)
        if end == -1:
            return ""
        frontmatter = text[3:end]
        for line in frontmatter.splitlines():
            if line.strip().startswith("short-desc:"):
                val = line.split(":", 1)[1].strip()
                # Strip quotes if present
                if (val.startswith('"') and val.endswith('"')) or \
                   (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                return val
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def generate_skill_shims(report):
    """Generate .claude/skills/<name>/SKILL.md for each explicit command."""
    explicit_dir = CODEX / "explicit"
    skills_dir = CLAUDE / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for entry in sorted(explicit_dir.iterdir()):
        if entry.is_dir():
            shim_dir = skills_dir / entry.name
            shim_dir.mkdir(parents=True, exist_ok=True)
            desc = extract_command_description(entry / "start.md")
            desc_line = f"\n[codex] {desc}\n" if desc else "\n"
            (shim_dir / "SKILL.md").write_text(
                f"---\nname: {entry.name}\n---\n"
                f"{desc_line}\n"
                f"Read and follow .codex/explicit/{entry.name}/start.md\n"
            )
            count += 1

    report.ok(f"Skill shims: {count} commands registered in .claude/skills/")
    return count


# ── Preference resolution ───────────────────────────────────────────

def resolve_preferences(report):
    """Merge the preference cascade and write prefs-resolved.json."""
    options_file = CODEX / "pref-options.json"
    codex_prefs_file = CODEX / "prefs.json"
    state_prefs_file = STATE / "prefs.json"
    output_file = STATE / "prefs-resolved.json"

    if not options_file.exists():
        report.warn("Pref-resolve: pref-options.json not found, skipping")
        return

    options = json.loads(options_file.read_text())
    codex_prefs = json.loads(codex_prefs_file.read_text()) if codex_prefs_file.exists() else {}
    state_prefs = json.loads(state_prefs_file.read_text()) if state_prefs_file.exists() else {}

    # Build resolved output
    resolved = {
        "_meta": {
            "generated": now_iso(),
            "sources": [
                {"file": ".codex/pref-options.json"},
                {"file": ".codex/prefs.json"},
                {"file": ".state/prefs.json"},
            ],
            "project": None,
        }
    }

    for key, schema in options.items():
        # Cascade: state_prefs > codex_prefs > schema default
        if key in state_prefs:
            value = state_prefs[key].get("value", schema.get("default"))
            context = state_prefs[key].get("context", "")
            source = ".state/prefs.json"
        elif key in codex_prefs:
            value = codex_prefs[key].get("value", schema.get("default"))
            context = codex_prefs[key].get("context", "")
            source = ".codex/prefs.json"
        else:
            value = schema.get("default")
            context = schema.get("default_context", "")
            source = ".codex/pref-options.json (default)"

        resolved[key] = {
            "value": value,
            "context": context,
            "source": source,
        }

    # Check if content actually changed (ignore _meta.generated timestamp)
    old_resolved = {}
    if output_file.exists():
        try:
            old_resolved = json.loads(output_file.read_text())
        except (json.JSONDecodeError, ValueError):
            pass

    old_values = {k: v for k, v in old_resolved.items() if k != "_meta"}
    new_values = {k: v for k, v in resolved.items() if k != "_meta"}

    output_file.write_text(json.dumps(resolved, indent=4) + "\n")

    if old_values and old_values != new_values:
        report.warn("Pref-resolve: preferences changed since last boot",
                     "prefs-resolved.json updated — review .codex/prefs.json or .state/prefs.json if unexpected")
    else:
        report.ok(f"Pref-resolve: {len(options)} preferences resolved")


# ── Settings assembly ───────────────────────────────────────────────

def assemble_settings(report):
    """Build .claude/settings.json from .codex/settings.json + hook registrations."""
    codex_settings_file = CODEX / "settings.json"
    output_file = CLAUDE / "settings.json"

    if not codex_settings_file.exists():
        report.warn("Settings assembly: .codex/settings.json not found, skipping")
        return

    # Warn if user has edited the generated file
    if output_file.exists():
        try:
            existing = json.loads(output_file.read_text())
            comment = existing.get("$comment", "")
            if "GENERATED" not in comment:
                report.warn("Settings assembly: .claude/settings.json was manually edited",
                            "User changes will be overwritten — move customizations to .claude/settings.local.json")
        except (json.JSONDecodeError, ValueError):
            pass

    codex_settings = json.loads(codex_settings_file.read_text())

    # Resolve module references
    statusline_cmd = None
    if "modules" in codex_settings:
        for mod_name, mod_path in codex_settings["modules"].items():
            mod_file = ROOT / mod_path
            if mod_file.exists():
                mod_settings = json.loads(mod_file.read_text())
                if mod_name == "statusline" and "command" in mod_settings:
                    statusline_cmd = (ROOT / mod_settings["command"]).as_posix()

    # Build the full settings
    settings = {
        "$comment": f"GENERATED by cboot.py at {now_iso()}. Do not edit. Source: .codex/settings.json",
        "customInstructions": (
            "Your governance roots (.codex/start.md, .state/start.md, user profile) are pre-loaded "
            "in your context via SessionStart hook. Follow the codex loading rules to complete boot. "
            "Do not skip this step regardless of what the user asks first."
        ),
    }

    # Pass through platform settings from codex
    if "plansDirectory" in codex_settings:
        settings["plansDirectory"] = codex_settings["plansDirectory"]

    if "permissions" in codex_settings:
        settings["permissions"] = copy.deepcopy(codex_settings["permissions"])

    # Pass through any remaining codex keys not specially handled above
    _handled_codex_keys = {"$comment", "plansDirectory", "permissions", "modules", "hooks"}
    for key, value in codex_settings.items():
        if key not in _handled_codex_keys and key not in settings:
            settings[key] = value

    if statusline_cmd:
        settings["statusLine"] = {"type": "command", "command": statusline_cmd}

    # Hook registrations — defined here as the single source of truth
    settings["hooks"] = {
        "SessionStart": [{
            "matcher": "",
            "hooks": [
                {"type": "command", "command": hook_cmd("boot-inject.py", "python")},
                {"type": "command", "command": hook_cmd("prefs-staleness-check.sh")},
                {"type": "command", "command": hook_cmd("memory-redirect-check.sh")},
            ]
        }],
        "PreToolUse": [
            {
                "matcher": "Read|Glob|Grep",
                "hooks": [
                    {"type": "command", "command": hook_cmd("visibility-guard.sh")},
                ]
            },
            {
                "matcher": "Bash",
                "hooks": [
                    {"type": "command", "command": hook_cmd("visibility-guard.sh")},
                    {"type": "command", "command": hook_cmd("api-guard.sh")},
                ]
            },
            {
                "matcher": "Write|Edit",
                "hooks": [
                    {"type": "command", "command": hook_cmd("visibility-guard.sh")},
                    {"type": "command", "command": hook_cmd("containment-guard.sh")},
                    {"type": "command", "command": hook_cmd("gravity-guard.sh")},
                    {"type": "command", "command": hook_cmd("audit-immutability-guard.sh")},
                    {"type": "command", "command": hook_cmd("claude-md-immutability-guard.sh")},
                ]
            },
        ],
        "PostToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [
                    {"type": "command", "command": hook_cmd("codex-edit-notify.sh")},
                ]
            },
            {
                "matcher": "Read|Write|Edit|Bash|Glob|Grep",
                "hooks": [
                    {"type": "command", "command": hook_cmd("trace-logger.sh")},
                ]
            },
        ],
        "Stop": [{
            "matcher": "",
            "hooks": [
                {"type": "command", "command": hook_cmd("session-close.sh")},
            ]
        }],
        "SubagentStop": [{
            "matcher": "",
            "hooks": [
                {"type": "command", "command": hook_cmd("subagent-conformance.sh")},
            ]
        }],
    }

    output_file.write_text(json.dumps(settings, indent=2) + "\n")
    report.ok("Settings assembly: .claude/settings.json generated from codex")


# ── Auto-memory directory ───────────────────────────────────────────

def configure_auto_memory(report):
    """Merge autoMemoryDirectory into settings.local.json, preserving user keys."""
    settings_local = CLAUDE / "settings.local.json"
    memory_dir = STATE / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    correct_path = str(memory_dir).replace("\\", "/")

    # Read existing content to preserve user-added keys
    existing = {}
    if settings_local.exists():
        try:
            existing = json.loads(settings_local.read_text())
        except (json.JSONDecodeError, ValueError):
            report.warn("Auto-memory: settings.local.json was malformed, resetting",
                        "User keys may have been lost")
            existing = {}

    current_path = existing.get("autoMemoryDirectory", "")

    if current_path == correct_path:
        report.ok(f"Auto-memory: already correct ({memory_dir.relative_to(ROOT)})")
        return

    # Merge — only touch our key, preserve everything else
    existing["autoMemoryDirectory"] = correct_path
    settings_local.write_text(json.dumps(existing, indent=4) + "\n")

    if current_path:
        report.ok(f"Auto-memory: updated ({memory_dir.relative_to(ROOT)}) — was: {current_path}")
    else:
        report.ok(f"Auto-memory: set to {memory_dir.relative_to(ROOT)}")


# ── Git hooks path ──────────────────────────────────────────────────

def configure_git_hooks(report):
    """Set core.hooksPath if scrub pre-push hook exists."""
    scrub_hooks = CODEX / "explicit" / "scrub" / "hooks"
    if scrub_hooks.is_dir() and (scrub_hooks / "pre-push").exists():
        try:
            subprocess.run(
                ["git", "config", "core.hooksPath", str(scrub_hooks.relative_to(ROOT))],
                cwd=ROOT, capture_output=True, check=True
            )
            report.ok("Git hooks: core.hooksPath set to scrub/hooks")
        except (subprocess.CalledProcessError, FileNotFoundError):
            report.warn("Git hooks: failed to set core.hooksPath")
    else:
        report.ok("Git hooks: no pre-push hook found, skipping")


# ── Trace session marker ────────────────────────────────────────────

def write_trace_marker(report):
    """Write session-start entry to today's trace file."""
    traces_dir = STATE / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    trace_file = traces_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.trace"

    # Warn if trace file is getting large (>100KB)
    if trace_file.exists() and trace_file.stat().st_size > 100_000:
        size_kb = trace_file.stat().st_size // 1024
        report.warn(f"Trace: {trace_file.name} is {size_kb}KB",
                     "Consider running purge to clean old traces")

    with open(trace_file, "a") as f:
        f.write(f"[{now_iso()}] CONTEXT: bootstrap, project={ROOT}\n")
    report.ok(f"Trace: session marker appended to {trace_file.name}")


# ── Hook coverage ────────────────────────────────────────────────────

def check_hook_coverage(report):
    """Verify every hook script has tests and every test maps to a hook."""
    try:
        from chooks import get_hook_coverage, HOOK_SCRIPTS
        all_hooks, tested_hooks, untested = get_hook_coverage()

        # Also verify hook scripts actually exist on disk
        missing_scripts = [h for h in HOOK_SCRIPTS if not (HOOKS_DIR / h).is_file()]
        if missing_scripts:
            report.warn(f"Hook coverage: {len(missing_scripts)} hook scripts missing from disk",
                        ", ".join(missing_scripts))
            return

        if untested:
            report.warn(f"Hook coverage: {len(untested)} hooks without tests",
                        ", ".join(sorted(untested)))
        else:
            report.ok(f"Hook coverage: all {len(all_hooks)} hooks have tests in chooks.py")
    except ImportError:
        report.warn("Hook coverage: chooks.py not found, skipping coverage check")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    report = BootReport()

    # Pre-flight
    if not preflight(report):
        print(report.to_terminal())
        print("  Bootstrap ABORTED — critical files missing.")
        print()
        sys.exit(1)

    # Materialize everything
    scaffold(report)
    check_structure(report)
    generate_skill_shims(report)
    resolve_preferences(report)
    assemble_settings(report)

    # Child propagation (00-preboot) — must run after settings + prefs
    preboot_script = PREBOOT_DIR / "child_propagate.py"
    if preboot_script.exists():
        child_propagate = _load_module(preboot_script)
        child_propagate.propagate(ROOT, report)

    configure_auto_memory(report)
    configure_git_hooks(report)
    write_trace_marker(report)
    check_hook_coverage(report)

    # Write report to .state/tests/boot/
    report_dir = STATE / "tests" / "boot"
    report_dir.mkdir(parents=True, exist_ok=True)
    existing_reports = list(report_dir.glob("*-bootstrap.md"))
    if len(existing_reports) > 20:
        report.warn(f"Report: {len(existing_reports)} bootstrap reports accumulated",
                     "Consider running purge to clean old reports")
    report_file = report_dir / f"{now_stamp()}-bootstrap.md"
    report.ok(f"Report: written to {report_file.relative_to(ROOT)}")

    # Write report and print to terminal (report entry added before both outputs)
    report_file.write_text(report.to_markdown())
    print(report.to_terminal())

    if report.errors:
        print("  Bootstrap completed with errors. Launching Claude Code anyway.")
        print()

    # Launch Claude Code (shutil.which resolves .cmd on Windows)
    import shutil
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        print("  Error: 'claude' command not found. Is Claude Code installed?")
        sys.exit(1)
    try:
        result = subprocess.run(
            [claude_cmd, *sys.argv[1:]],
            cwd=ROOT,
        )
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
