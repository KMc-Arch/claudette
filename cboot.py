#!/usr/bin/env python3
"""Claudette2 boot wrapper. Run this instead of `claude` directly.

Materializes all generated artifacts, validates configuration, writes a
bootstrap report to .state/tests/boot/, prints it to terminal, then
launches Claude Code.

Usage:
    python cboot.py                       # full apex boot, then launch claude
    python cboot.py --resume              # pass args through to claude
    python cboot.py --materialize-only    # regenerate apex + all children, no launch
    python cboot.py --project PATH        # re-materialize ONE child only, no launch
    python cboot.py --project PATH --launch             # ...then launch claude in that child
    python cboot.py --project PATH --exec "PROMPT"      # headless HARD-ROOTED worker; prints a JSON envelope
    python cboot.py --project PATH --exec-file FILE     # ...prompt read from FILE (preferred for untrusted content)
    python cboot.py --project PATH --exec -             # ...prompt read from stdin
    python cboot.py --project PATH --switch             # print the --launch command for a switch (does NOT launch)

--project re-materializes the apex's own inputs (prefs, settings, skill shims),
then propagates to the single target descendant — without touching its siblings.
PATH may be relative to the apex root or absolute; it must be a root: true
descendant of this apex.

--exec runs `claude -p "PROMPT" --output-format json` with cwd=PATH and
CLAUDE_PROJECT_DIR=PATH, so the child's guards fence there — a real hard-root, not
a soft reroot. For untrusted prompts, prefer --exec-file FILE (or --exec -): the
prompt is read from a file/stdin so its bytes never sit on a shell command line.
stdout is JSON ONLY (a caller parses it); `session_id` is resumable, so pass
`--resume <id>` through to continue a worker session (a bare, value-less --resume
is dropped). --switch prints the interactive-launch command for a human to run; it
never launches itself (a caller applying "if json parse, else handoff" treats that
non-JSON line as the handoff). All lazily materialize the child if unbuilt.
"""

import copy
import importlib.util
import json
import os
import re
import shutil
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

# Ceiling for a headless --exec worker, in seconds. Override via CBOOT_EXEC_TIMEOUT.
# Guarded: a bad env value must not break every cboot mode at import time.
try:
    EXEC_TIMEOUT = int(os.environ.get("CBOOT_EXEC_TIMEOUT", "600"))
except ValueError:
    EXEC_TIMEOUT = 600

# Passthrough flags allowed to reach the headless `claude -p` worker. Anything
# else is dropped — a hard-rooted worker must never be handed a governance-
# weakening flag (--settings, --dangerously-skip-permissions, --add-dir, …).
# Both allowlisted flags take a value.
_EXEC_PASSTHROUGH_ALLOW = ("--resume", "--model")

_python = shutil.which("python") or shutil.which("python3")
if not _python:
    sys.stderr.write("cboot: no python interpreter on PATH (tried 'python', 'python3')\n")
    sys.exit(1)
PYTHON_EXE = Path(_python).as_posix()


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
    interp = interpreter if interpreter in ("bash", "python", "python3") else f'"{interpreter}"'
    return f'{interp} "{abs_path}"'


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
            # Skip non-module dirs by convention: .-prefixed (internal, e.g.
            # .archive) and _-prefixed (invisible, e.g. __pycache__) never carry
            # a start.md manifest.
            if any(part.startswith((".", "_")) for part in d.relative_to(base).parts):
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
                f"Read and follow .codex/explicit/{entry.name}/start.md\n",
                encoding="utf-8",
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
                {"type": "command", "command": hook_cmd("boot-inject.py", PYTHON_EXE)},
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
                    {"type": "command", "command": hook_cmd("remote-guard.sh")},
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

GIT_SCAN_SKIP = {"node_modules", "__pycache__"}


def _discover_git_repos(root):
    """Every git repo in the tree, apex first.

    Discovered by `.git`, not by `root: true`: a repo need not be a context root
    (oneoff/2026-microsoft-team-hack is a repo and is not one) and most context
    roots are not repos. Dot-prefixed directories are pruned, which also excludes
    vendored third-party clones under `.act/` and `.plugins/` -- those are not
    ours to configure.
    """
    repos = []
    if (root / ".git").exists():
        repos.append(root)

    def walk(directory):
        try:
            children = sorted(directory.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith(".") or name.startswith("_") or name in GIT_SCAN_SKIP:
                continue
            if (child / ".git").exists():
                repos.append(child)
            walk(child)

    walk(root)
    return repos


def _set_git_config_key(repo, section, subkey, value):
    """Set a git config key, falling back to a direct .git/config edit.

    `git config` writes through .git/config.lock and chmods it, which returns
    EPERM on a drvfs/9p mount -- so on this platform the subprocess always fails
    and the direct edit is the only path that works. Idempotent either way.

    Returns (ok: bool, how: str).
    """
    key = f"{section}.{subkey}"
    try:
        subprocess.run(["git", "config", key, value],
                       cwd=repo, capture_output=True, check=True)
        return True, "git config"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    config = repo / ".git" / "config"
    if not config.is_file():
        return False, "no .git/config"
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False, "unreadable .git/config"

    header = f"[{section}]"
    needle = subkey.lower() + "="
    out, in_section, done = [], False, False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            # Leaving the target section without having written the key.
            if in_section and not done:
                out.append(f"\t{subkey} = {value}")
                done = True
            in_section = stripped.lower() == header.lower()
        elif in_section and stripped.lower().replace(" ", "").startswith(needle):
            out.append(f"\t{subkey} = {value}")
            done = True
            continue
        out.append(line)

    if not done:
        if in_section:
            out.append(f"\t{subkey} = {value}")
        else:
            out.extend([header, f"\t{subkey} = {value}"])

    try:
        config.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"write failed: {exc}"
    return True, "direct .git/config edit"


def configure_git_hooks(report):
    """Point every git repo in the tree at the codex pre-push hook (BDRY-03).

    Runs over all repos, not just the apex: the push boundary belongs to whichever
    repo is being pushed, and the child projects are where most commits happen.
    """
    hooks_dir = CODEX / "explicit" / "scrub" / "hooks"
    if not (hooks_dir.is_dir() and (hooks_dir / "pre-push").exists()):
        report.ok("Git hooks: no pre-push hook found, skipping")
        return

    repos = _discover_git_repos(ROOT)
    already = wired = failed = 0
    problems, displaced, unsafe = [], [], []

    def read_key(repo):
        return subprocess.run(
            ["git", "config", "core.hooksPath"],
            cwd=repo, capture_output=True, text=True, check=False,
        ).stdout.strip()

    for repo in repos:
        label = "." if repo == ROOT else repo.relative_to(ROOT).as_posix()
        # Relative, so the setting survives the tree moving to another mount.
        want = Path(os.path.relpath(hooks_dir, repo)).as_posix()

        # Can git operate here at all? A root-owned repo on a shared mount trips
        # git's safe.directory protection, after which every read returns empty
        # and every write is pointless -- the config file can be perfectly
        # correct while git refuses to look at it.
        probe = subprocess.run(["git", "rev-parse", "--git-dir"],
                               cwd=repo, capture_output=True, text=True, check=False)
        if probe.returncode != 0:
            failed += 1
            if "dubious ownership" in probe.stderr:
                unsafe.append(str(repo))
            else:
                first = (probe.stderr.strip().splitlines() or ["unknown error"])[0]
                problems.append(f"{label} ({first})")
            continue

        if read_key(repo) == want:
            already += 1
            continue

        # core.hooksPath replaces the entire hooks directory -- surface anything
        # it would hide rather than silently disabling it.
        live = sorted(p.name for p in (repo / ".git" / "hooks").glob("*")
                      if p.is_file() and not p.name.endswith(".sample"))
        if live:
            displaced.append(f"{label}: {', '.join(live)}")

        ok, how = _set_git_config_key(repo, "core", "hooksPath", want)
        if not ok:
            failed += 1
            problems.append(f"{label} ({how})")
            continue

        # Verify rather than assume. A value written but not readable back is not
        # a wired hook, and reporting it as one is how a dead gate looks healthy.
        confirmed = read_key(repo)
        if confirmed == want:
            wired += 1
        else:
            failed += 1
            problems.append(f"{label} (written via {how}, but git reads "
                            f"'{confirmed or 'unset'}')")

    total = len(repos)
    if failed:
        detail = "; ".join(problems) if problems else ""
        report.warn(f"Git hooks: pre-push active in {wired + already}/{total} repos, "
                    f"{failed} unprotected{' -- ' + detail if detail else ''}")
    else:
        report.ok(f"Git hooks: pre-push active in {wired + already}/{total} repos "
                  f"({wired} newly wired, {already} already set)")

    if unsafe:
        report.warn(
            f"Git hooks: {len(unsafe)} repo(s) unusable by git (dubious ownership) -- "
            "git cannot read or push them at all, so no gate applies. Remedy: "
            + " ; ".join(f"git config --global --add safe.directory {p}" for p in unsafe)
        )
    if displaced:
        report.warn("Git hooks: core.hooksPath now hides existing hooks -- "
                    + "; ".join(displaced))


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


# ── Root inventory ───────────────────────────────────────────────────

def _extract_root_name(claude_md: Path, fallback: str) -> str:
    """Pull `name:` from a CLAUDE.md frontmatter; fall back to the dir name."""
    try:
        text = claude_md.read_text(encoding="utf-8-sig")
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                for line in text[3:end].splitlines():
                    stripped = line.strip()
                    if stripped.startswith("name:"):
                        val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
    except (OSError, UnicodeDecodeError):
        pass
    return fallback


def build_root_inventory(report):
    """Materialize .state/roots.db — the durable directory of every root: true
    context under the apex, including the apex itself.

    This is a DERIVED, REBUILDABLE CACHE, not a source of truth. The filesystem
    walk (child_propagate.discover_roots) is authoritative; this DB is dropped and
    rebuilt from scratch on every boot and is safe to delete — the next boot
    regenerates it. It is gitignored via .state/.gitignore (accumulation is never
    tracked).

    Records, per root: name, absolute path, apex-relative path, nearest enclosing
    root (containment parent), depth, whether it is the apex, and how many DIRECT
    child roots it contains. All connections go through the house sqlite factory
    (.codex/reactive/sqlite/sqlite.py) per the never-call-sqlite3.connect rule.
    """
    try:
        import sqlite3  # for sqlite3.Error only; connection comes from the factory
    except ImportError:
        report.warn("Root inventory: sqlite3 unavailable, skipping")
        return []

    child_propagate = _load_module(PREBOOT_DIR / "child_propagate.py")
    sqlite_factory = _load_module(CODEX / "reactive" / "sqlite" / "sqlite.py")

    # Apex is the ceiling row; discovered descendants follow. Resolve to absolute.
    apex_abs = ROOT.resolve()
    descendants = [d.resolve() for d in child_propagate.discover_roots(ROOT)]
    all_roots = [apex_abs] + descendants
    root_set = set(all_roots)

    # Nearest enclosing root = first ancestor (nearest-first) that is itself a root.
    parents = {}
    child_counts = {p: 0 for p in all_roots}
    for p in all_roots:
        parent = None
        if p != apex_abs:
            for anc in p.parents:
                if anc in root_set:
                    parent = anc
                    break
        parents[p] = parent
        if parent is not None:
            child_counts[parent] += 1

    def depth_of(p):
        d, cur = 0, parents.get(p)
        while cur is not None:
            d += 1
            cur = parents.get(cur)
        return d

    stamp = now_iso()
    rows = []
    for p in all_roots:
        is_apex = p == apex_abs
        rows.append({
            "name": _extract_root_name(p / "CLAUDE.md", "apex" if is_apex else p.name),
            "abs_path": p.as_posix(),
            "rel_path": "." if is_apex else p.relative_to(apex_abs).as_posix(),
            "parent_path": parents[p].as_posix() if parents[p] else None,
            "depth": depth_of(p),
            "is_apex": 1 if is_apex else 0,
            "contains_roots": child_counts[p],
            "generated_at": stamp,
        })
    rows.sort(key=lambda r: (r["depth"], r["rel_path"]))

    db_path = STATE / "roots.db"
    try:
        conn = sqlite_factory.connect(str(db_path))
        try:
            # roots/meta are a cache of the filesystem walk — dropped and
            # rebuilt every boot. agent_optin/agent_registry are DURABLE and
            # are deliberately not in this list: they hold human decisions and
            # the claims that generated files depend on.
            conn.execute("DROP TABLE IF EXISTS roots")
            conn.execute("DROP TABLE IF EXISTS meta")
            _ensure_agent_tables(conn)
            conn.execute(
                "CREATE TABLE roots ("
                " id INTEGER PRIMARY KEY,"
                " name TEXT NOT NULL,"
                " abs_path TEXT NOT NULL UNIQUE,"
                " rel_path TEXT NOT NULL,"
                " parent_path TEXT,"           # nearest enclosing root's abs_path (NULL for apex)
                " depth INTEGER NOT NULL,"      # 0 = apex, 1 = top-level child, ...
                " is_apex INTEGER NOT NULL DEFAULT 0,"
                " contains_roots INTEGER NOT NULL DEFAULT 0,"  # count of DIRECT child roots
                # Denormalised mirror of agent_registry, filled by generate_agents.
                # Convenience for readers; agent_registry is the authority.
                " agent_enabled INTEGER NOT NULL DEFAULT 0,"
                " agent_name TEXT,"
                " agent_file TEXT,"
                " generated_at TEXT NOT NULL)"
            )
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.executemany(
                "INSERT INTO roots (name, abs_path, rel_path, parent_path, depth,"
                " is_apex, contains_roots, generated_at) VALUES (:name, :abs_path,"
                " :rel_path, :parent_path, :depth, :is_apex, :contains_roots, :generated_at)",
                rows,
            )
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [("generated", stamp), ("apex_abs", apex_abs.as_posix()),
                 ("root_count", str(len(rows)))],
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        report.warn("Root inventory: sqlite write failed", str(e))
        return []

    n = len(descendants)
    report.ok(f"Root inventory: {len(rows)} roots in .state/roots.db "
              f"(apex + {n} descendant{'' if n == 1 else 's'})")
    return rows


# ── Addressable agents ───────────────────────────────────────────────
#
# Every root: true child may be addressable as a native Claude Code subagent
# (`@majel`, `@drawio`). cboot generates `^/.claude/agents/<name>.md` for each
# one that is switched on.
#
# NOTHING ABOUT THIS LIVES IN THE CHILD. A child's CLAUDE.md is read (for a
# default description) and never written. Whether a project is addressable, the
# name it answers to, and its description are apex state, held in `roots.db`:
#
#   agent_optin     durable. One row per root: the decision, once, forever.
#   agent_registry  durable SCD2. The claim ledger — and the SOLE authority on
#                   which files in .claude/agents/ are ours.
#   roots / meta    dropped and rebuilt every boot; the agent columns are a
#                   denormalised mirror, never a source of truth.
#
# Ownership is not implemented here. It lives in .codex/reactive/agent-ownership
# and is shared with purge — see that module's start.md for the rule.

AGENTS_DIR = CLAUDE / "agents"

# Prompting is only ever offered to a human at a real terminal. cboot
# --materialize-only is also run from inside a Claude session (by /purge) and
# from hooks, where a prompt would hang forever with nobody to answer it.
def _interactive():
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _agent_ownership():
    return _load_module(CODEX / "reactive" / "agent-ownership" / "agent_ownership.py")


def _ensure_agent_tables(conn):
    """Create the two DURABLE tables if absent. Never dropped, never rebuilt.

    `roots` and `meta` are a cache of the filesystem walk and are rebuilt every
    boot. These two are not: they hold decisions a human made and claims that
    files on disk depend on. Losing them would orphan every generated file.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_optin ("
        " rel_path TEXT PRIMARY KEY,"        # apex-relative root path
        " enabled INTEGER NOT NULL,"          # 1 = addressable, 0 = declined
        " requested_name TEXT,"               # the @name the human chose
        " description TEXT,"                  # the one-liner they gave
        " decided_at TEXT NOT NULL,"
        " decided_by TEXT NOT NULL)"          # 'prompt' | 'inherited' | ...
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_registry ("
        " id INTEGER PRIMARY KEY,"
        " agent_name TEXT NOT NULL,"
        " rel_path TEXT NOT NULL,"
        " source_folder TEXT NOT NULL,"
        " deconflicted_from TEXT,"
        " description TEXT,"
        " agent_file TEXT NOT NULL,"          # apex-relative
        " valid_from TEXT NOT NULL,"
        " valid_to TEXT,"                     # NULL = current claim
        " change_reason TEXT NOT NULL,"       # why the row OPENED — never rewritten
        " close_reason TEXT)"                 # why it CLOSED
    )
    # Partial unique indexes: uniqueness applies to CURRENT rows only, so SCD2
    # history may hold the same name many times over.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_cur_path"
                 " ON agent_registry(rel_path) WHERE valid_to IS NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_cur_name"
                 " ON agent_registry(agent_name) WHERE valid_to IS NULL")
    # A live claim with no recorded decision predates the decision table. It is
    # still evidence of a decision a human made — under the older design, by
    # putting `agent: true` in the project's own CLAUDE.md. Inherit it rather
    # than treating silence as a decline, which would delete three working
    # agents and make the user re-answer for projects already switched on.
    # Idempotent: a project that was later switched off has an enabled=0 row,
    # so this can never resurrect it.
    conn.execute(
        "INSERT INTO agent_optin (rel_path, enabled, requested_name, description,"
        " decided_at, decided_by)"
        " SELECT r.rel_path, 1, r.agent_name, r.description, r.valid_from, 'inherited'"
        " FROM agent_registry r"
        " WHERE r.valid_to IS NULL"
        "   AND NOT EXISTS (SELECT 1 FROM agent_optin o WHERE o.rel_path = r.rel_path)")


def _read_child_text(claude_md):
    """(status, text) for a child's CLAUDE.md.

    status is 'ok' | 'missing' | 'unreadable'. An undecodable or unreadable
    CLAUDE.md is NEVER treated as an opt-out — the decision lives in roots.db
    and a file we cannot read says nothing about it. The root is skipped for
    this boot and reported, leaving its agent file and claim untouched.
    """
    try:
        raw = claude_md.read_bytes()
    except FileNotFoundError:
        return "missing", ""
    except OSError:
        return "unreadable", ""
    try:
        return "ok", raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "unreadable", ""


_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_POINTER_RE = re.compile(r"^\s*Read\s+[`'\"]?[.^~]", re.I)


def _default_description(text, fallback):
    """First prose line of a CLAUDE.md body — the description offered at the
    prompt. Headings are skipped; a pointer line ("Read `.state/start.md`.") is
    TERMINAL, not skipped, because what follows it is the project's own content
    rather than a description of the project.
    """
    ao = _agent_ownership()
    body = ao._body_after_frontmatter(text)
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            continue
        if _HEADING_RE.match(s):
            continue
        if _POINTER_RE.match(s):
            break
        return " ".join(s.split())
    return fallback


def _free_name(candidate, taken, reserved):
    """First unclaimed variant of `candidate`. Case-insensitive against both."""
    low = {t.lower() for t in taken} | {r.lower() for r in reserved}
    if candidate and candidate.lower() not in low:
        return candidate, None
    base = candidate or "agent"
    n = 2
    while f"{base}-{n}".lower() in low:
        n += 1
    return f"{base}-{n}", candidate


# ── Opt-in decisions (interactive) ───────────────────────────────────

def decide_agent_optin(report, rows):
    """Ask, once, about every root we have never asked about.

    A root with a row in `agent_optin` is never asked again — the decision is
    durable. Outside a terminal nothing is asked and nothing is recorded; the
    undecided roots are reported so a human can run cboot from a terminal.
    """
    try:
        import sqlite3
    except ImportError:
        return
    ao = _agent_ownership()
    sqlite_factory = _load_module(CODEX / "reactive" / "sqlite" / "sqlite.py")
    db_path = STATE / "roots.db"

    candidates = [r for r in rows if not r["is_apex"]]   # the apex is never an agent
    if not candidates:
        return

    try:
        conn = sqlite_factory.connect(str(db_path))
    except sqlite3.Error as e:
        report.warn("Agent opt-in: roots.db unopenable, skipping", str(e))
        return
    try:
        _ensure_agent_tables(conn)
        decided = {r[0] for r in conn.execute("SELECT rel_path FROM agent_optin")}
        undecided = [r for r in candidates if r["rel_path"] not in decided]
        if not undecided:
            return

        if not _interactive():
            names = ", ".join(r["rel_path"] for r in undecided[:5])
            more = f" (+{len(undecided) - 5} more)" if len(undecided) > 5 else ""
            report.warn(
                f"Agent opt-in: {len(undecided)} project(s) awaiting a decision",
                f"{names}{more} — run `python cboot.py --materialize-only` "
                f"from a terminal to decide")
            return

        taken = {r[0] for r in conn.execute(
            "SELECT agent_name FROM agent_registry WHERE valid_to IS NULL")}
        taken |= {r[0] for r in conn.execute(
            "SELECT requested_name FROM agent_optin"
            " WHERE enabled = 1 AND requested_name IS NOT NULL")}

        print()
        print(f"  {len(undecided)} project(s) not yet decided. "
              f"Enter = the default in [brackets]; Ctrl-C stops (nothing recorded).")
        stamp = now_iso()
        recorded = 0
        for r in undecided:
            folder = Path(r["abs_path"]).name
            status, text = _read_child_text(Path(r["abs_path"]) / "CLAUDE.md")
            print()
            print(f"  ── {r['rel_path']}")
            try:
                ans = input(f"     Address it as an @name? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                report.warn("Agent opt-in: interrupted",
                            f"{len(undecided) - recorded} project(s) still undecided")
                break
            if ans not in ("y", "yes"):
                conn.execute(
                    "INSERT INTO agent_optin (rel_path, enabled, requested_name,"
                    " description, decided_at, decided_by)"
                    " VALUES (?, 0, NULL, NULL, ?, 'prompt')", (r["rel_path"], stamp))
                conn.commit()
                recorded += 1
                continue

            default_name, _ = _free_name(ao.derive_agent_name(folder), taken,
                                         ao.RESERVED_NAMES)
            name = None
            while name is None:
                try:
                    raw = input(f"     @name [{default_name}]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    raw = None
                if raw is None:
                    break
                cand = ao.derive_agent_name(raw) if raw else default_name
                if not cand:
                    print("     ! name empties out after sanitizing — try again")
                    continue
                if cand.lower() in {t.lower() for t in taken} or \
                   cand.lower() in {x.lower() for x in ao.RESERVED_NAMES}:
                    print(f"     ! @{cand} is already taken — try another")
                    continue
                if cand != raw and raw:
                    print(f"     (sanitized to @{cand})")
                name = cand
            if name is None:
                report.warn("Agent opt-in: interrupted",
                            f"{len(undecided) - recorded} project(s) still undecided")
                break

            default_desc = (_default_description(text, r["name"])
                            if status == "ok" else r["name"])
            try:
                desc = input(f"     description [{default_desc}]: ").strip() or default_desc
            except (EOFError, KeyboardInterrupt):
                print()
                report.warn("Agent opt-in: interrupted",
                            f"{len(undecided) - recorded} project(s) still undecided")
                break

            conn.execute(
                "INSERT INTO agent_optin (rel_path, enabled, requested_name,"
                " description, decided_at, decided_by)"
                " VALUES (?, 1, ?, ?, ?, 'prompt')",
                (r["rel_path"], name, desc, stamp))
            conn.commit()
            taken.add(name)
            recorded += 1
            print(f"     -> @{name}")
        print()
        if recorded:
            report.ok(f"Agent opt-in: {recorded} decision(s) recorded")
    finally:
        conn.close()


# ── Generation ───────────────────────────────────────────────────────

def _agent_brief(name, rel_path, abs_path, codex_dir, description):
    """The generated agent file. Self-contained: subagents get no SessionStart
    payload and are handed the APEX CLAUDE.md and MEMORY.md by the harness, not
    the child's — so everything the agent needs is baked in here.
    """
    ao = _agent_ownership()
    apex = ROOT.as_posix()
    return (
        "---\n"
        f"name: {ao.yaml_scalar(name)}\n"
        f"description: {ao.yaml_scalar(description)}\n"
        "---\n"
        "\n"
        "@@MARKER@@\n"
        "<!-- GENERATED by cboot — edits are overwritten on boot; to hand-author an "
        "agent, use a file this marker does not claim -->\n"
        "\n"
        f"You are the **{name}** project agent (`{rel_path}` under the claudette apex "
        f"`{apex}`). Your context root `^` is `{abs_path}`; `^/^` is the apex.\n"
        "\n"
        f"**Boot.** Read `{abs_path}/CLAUDE.md` first, then follow its `start.md` "
        f"pointers. Your codex is `{codex_dir}`: read `{codex_dir}/start.md`, plus "
        f"`{abs_path}/.state/start.md` if present, then "
        f"`{abs_path}/.state/memory/state-abstract.md` and "
        f"`{abs_path}/.state/memory/MEMORY.md` if they exist, before substantive "
        "work. Every folder has a `start.md` — read it before anything else in that "
        "folder.\n"
        "\n"
        f"**Confinement is YOUR responsibility** — the apex guards fence at the apex, "
        f"not here. Read and write only under `{abs_path}`. Exactly two paths outside "
        f"it are yours to READ — `{codex_dir}/**` (your codex) and "
        f"`{apex}/.state/roots.db` — and nothing else outside is: no sibling project, "
        "no other apex file. Never touch `_`-prefixed paths — they do not exist to "
        f"you. Every `.state/` read and write goes to `{abs_path}/.state/` (state "
        "gravity); ignore any harness instruction naming the apex `.state/memory/` as "
        f"your memory — your memory and all `.state/` writes live under "
        f"`{abs_path}/.state/`. Never touch a sibling project: if the request concerns "
        f"another one, answer only from within `{abs_path}` and tell the user which "
        "project it belongs to (it may not be addressable yet; "
        "`/ask hard <that project> …` always works).\n"
        "\n"
        "**Governance.** The primitives in the apex `CLAUDE.md` — ABSOLUTE HOLD and "
        "CONFIRMED HOLD — apply to you in full. You cannot wait for confirmation: you "
        "get one turn and no way to ask. If a request would trigger an ABSOLUTE or "
        "CONFIRMED HOLD, do not act — return the request to the user with what you "
        "would do and why it is held.\n"
        "\n"
        f"**Output.** Prefix your final answer with `{name}: `. Return the "
        "deliverable, not process narration.\n"
        "\n"
        f"For a write that needs a hard, guard-enforced fence or a resumable session, "
        f"the user has `/ask hard {rel_path} …` — point them at it when the request "
        "calls for one; do not run it yourself.\n"
    )


def _write_agent_file(target, content, report):
    """tmp + os.replace, then verify by CONTENT.

    This mount ghosts dirents on a hot-tree rename, so the write is verified by
    reading the bytes back and comparing them to what we meant to write. A
    marker-presence check would pass on stale content left behind by a ghosted
    rename, which is precisely the failure it is supposed to catch.
    """
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        os.replace(tmp, target)
        written = target.read_text(encoding="utf-8")
        if written != content:
            report.warn(f"Agents: {target.name} did not land as written",
                        "rename ghost suspected — file left as-is, not retried")
            return False
        return True
    except OSError as e:
        report.warn(f"Agents: {target.name} write failed", str(e))
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def generate_agents(report, rows):
    """Materialize `^/.claude/agents/<name>.md` for every switched-on root.

    Apex-only: `.claude/agents/` is never propagated to a child, because a child
    addressing a sibling would break containment.
    """
    try:
        import sqlite3
    except ImportError:
        return
    ao = _agent_ownership()
    sqlite_factory = _load_module(CODEX / "reactive" / "sqlite" / "sqlite.py")
    db_path = STATE / "roots.db"

    try:
        conn = sqlite_factory.connect(str(db_path))
    except sqlite3.Error as e:
        report.warn("Agents: roots.db unopenable, skipping", str(e))
        return
    try:
        _ensure_agent_tables(conn)

        by_path = {r["rel_path"]: r for r in rows if not r["is_apex"]}
        optin = {r["rel_path"]: r for r in conn.execute(
            "SELECT rel_path, enabled, requested_name, description FROM agent_optin")}
        current = {r["rel_path"]: r for r in conn.execute(
            "SELECT id, agent_name, rel_path, description, agent_file"
            " FROM agent_registry WHERE valid_to IS NULL")}

        stamp = now_iso()
        AGENTS_DIR.mkdir(parents=True, exist_ok=True)

        # Ownership, computed ONCE from the registry, before anything is touched.
        try:
            claims = ao.claims_for(db_path, AGENTS_DIR)
        except ao.RegistryUnavailable as e:
            report.warn("Agents: registry unreadable, no files touched", str(e))
            return

        wrote, closed, skipped, diverged = 0, 0, 0, []

        # ── Close claims whose root is gone, opted out, or renamed away ──
        for rel, row in current.items():
            reason = None
            if rel not in by_path:
                # A root absent from the walk is not automatically gone. An
                # unreadable or undecodable CLAUDE.md also drops a root out of
                # discover_roots — and a file we cannot read says NOTHING about
                # whether the project still wants an agent. Closing the claim
                # there would delete a live project's agent over an encoding.
                status, _ = _read_child_text(ROOT / rel / "CLAUDE.md")
                if status == "unreadable":
                    report.warn(f"Agents: {rel} CLAUDE.md unreadable — skipped this boot",
                                "claim and agent file left untouched")
                    skipped += 1
                    continue
                reason = "root-removed"
            elif not optin.get(rel, {"enabled": 0})["enabled"]:
                reason = "opted-out"
            if reason is None:
                continue
            target = ROOT / row["agent_file"]
            if ao.owns(target, claims):
                marker = ao.read_marker(target)
                if target.exists() and marker != rel:
                    diverged.append((row["agent_file"], "claimed but unmarked — left in place"))
                else:
                    try:
                        target.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        report.warn(f"Agents: could not remove {target.name}", str(e))
            conn.execute("UPDATE agent_registry SET valid_to = ?, close_reason = ?"
                         " WHERE id = ?", (stamp, reason, row["id"]))
            conn.commit()
            closed += 1

        # ── Open or refresh a claim per switched-on root ──
        names_taken = {r["agent_name"] for rel, r in current.items()
                       if rel in by_path and optin.get(rel, {"enabled": 0})["enabled"]}
        enabled = [(rel, r) for rel, r in sorted(by_path.items())
                   if optin.get(rel, {"enabled": 0})["enabled"]]

        for rel, root_row in enabled:
            decision = optin[rel]
            abs_path = Path(root_row["abs_path"])
            status, text = _read_child_text(abs_path / "CLAUDE.md")
            if status == "unreadable":
                # Says nothing about the decision — skip this boot, keep the claim
                # and the file exactly as they are.
                report.warn(f"Agents: {rel} CLAUDE.md unreadable — skipped this boot",
                            "claim and agent file left untouched")
                skipped += 1
                continue

            held = current.get(rel)
            if held:
                # A project's claimed name never silently changes across boots.
                name = held["agent_name"]
                deconflicted_from = None
            else:
                want = decision["requested_name"] or ao.derive_agent_name(abs_path.name)
                blocked = set(names_taken)
                # A file already sitting on the name that is NOT ours blocks it.
                for other in AGENTS_DIR.glob("*.md"):
                    if not ao.owns(other, claims):
                        blocked.add(other.stem)
                name, deconflicted_from = _free_name(want, blocked, ao.RESERVED_NAMES)
                if not name:
                    report.warn(f"Agents: {rel} has no usable @name", "skipped")
                    skipped += 1
                    continue

            names_taken.add(name)
            agent_rel = f"{ao.AGENTS_REL}/{name}.md"
            target = ROOT / agent_rel
            description = decision["description"] or _default_description(
                text, root_row["name"])
            codex_dir = (ROOT / ".codex").as_posix()
            content = _agent_brief(name, rel, abs_path.as_posix(), codex_dir,
                                   description).replace(
                "@@MARKER@@", ao.render_marker(rel, stamp))

            if held:
                # Ours by the registry. Whether we may REWRITE it is a separate
                # question: if the marker is gone or altered, a human has been in
                # the file — warn and leave it, never overwrite.
                if target.exists():
                    if ao.read_marker(target) != rel:
                        diverged.append((agent_rel, "marker missing or altered — not overwritten"))
                        continue
                    # Idempotence: an unchanged file is not rewritten, so two
                    # consecutive boots leave agent-file mtimes untouched.
                    existing = target.read_text(encoding="utf-8", errors="replace")
                    if _same_but_for_stamp(existing, content):
                        continue
                if not _write_agent_file(target, content, report):
                    continue
                if held["description"] != description:
                    conn.execute("UPDATE agent_registry SET valid_to = ?,"
                                 " close_reason = 'description-changed' WHERE id = ?",
                                 (stamp, held["id"]))
                    conn.execute(
                        "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
                        " deconflicted_from, description, agent_file, valid_from,"
                        " change_reason) VALUES (?,?,?,NULL,?,?,?,'description-changed')",
                        (name, rel, abs_path.name, description, agent_rel, stamp))
                    conn.commit()
                wrote += 1
                continue

            # New claim. The registry row is committed BEFORE the file lands, so
            # a crash in between leaves a claim with no file — which the next boot
            # simply writes. The reverse order would leave a file nobody claims,
            # permanently demoted to the foreign bucket and never swept.
            try:
                conn.execute(
                    "INSERT INTO agent_registry (agent_name, rel_path, source_folder,"
                    " deconflicted_from, description, agent_file, valid_from,"
                    " change_reason) VALUES (?,?,?,?,?,?,?,'opted-in')",
                    (name, rel, abs_path.name, deconflicted_from, description,
                     agent_rel, stamp))
                conn.commit()
            except sqlite3.Error as e:
                report.warn(f"Agents: registry insert failed for {rel}", str(e))
                skipped += 1
                continue
            if not _write_agent_file(target, content, report):
                conn.execute("UPDATE agent_registry SET valid_to = ?,"
                             " close_reason = 'write-failed' WHERE rel_path = ?"
                             " AND valid_to IS NULL", (stamp, rel))
                conn.commit()
                skipped += 1
                continue
            claims[ao._key(target)] = {"agent_name": name, "rel_path": rel}
            wrote += 1

        # ── Sweep cboot's own staging leftovers ──
        for stale in AGENTS_DIR.iterdir():
            if ao.is_tmp_artifact(stale) and stale.is_file():
                try:
                    stale.unlink()
                except OSError:
                    pass

        # ── Mirror onto the rebuilt roots table (denormalised, never authority) ──
        live = {r["rel_path"]: r for r in conn.execute(
            "SELECT agent_name, rel_path, agent_file FROM agent_registry"
            " WHERE valid_to IS NULL")}
        for rel, r in live.items():
            # Advertise only what actually exists on disk — a claim whose write
            # failed must not appear in the mirror as an available @name.
            if not (ROOT / r["agent_file"]).is_file():
                continue
            conn.execute("UPDATE roots SET agent_enabled = 1, agent_name = ?,"
                         " agent_file = ? WHERE rel_path = ?",
                         (r["agent_name"], r["agent_file"], rel))
        conn.commit()

        for path, why in diverged:
            report.warn(f"Agents: {path} diverged", why)

        n = sum(1 for rel in live if (ROOT / live[rel]["agent_file"]).is_file())
        bits = [f"{n} addressable"]
        if wrote:
            bits.append(f"{wrote} written")
        if closed:
            bits.append(f"{closed} closed")
        if skipped:
            bits.append(f"{skipped} skipped")
        report.ok("Agents: " + ", ".join(bits) +
                  (" (" + ", ".join(f"@{live[r]['agent_name']}" for r in sorted(live)) + ")"
                   if live else ""))
    finally:
        conn.close()


_STAMP_RE = re.compile(r'generated="[^"]*"')


def _same_but_for_stamp(a, b):
    """Two agent files are the same if they differ only in the generated= stamp.

    Without this every boot rewrites every file for a new timestamp alone, so
    'two consecutive materializations are a no-op' could never hold.
    """
    return _STAMP_RE.sub('generated=""', a) == _STAMP_RE.sub('generated=""', b)


# ── Per-project refresh ──────────────────────────────────────────────

def materialize_apex_inputs(report):
    """Re-materialize the apex-local artifacts that child propagation consumes.

    These are the inputs every child derives from: scaffolded state dirs, skill
    shims, resolved prefs, and the generated .claude/settings.json. Cheap,
    idempotent, no child propagation, no launch. Used by both full boot (via
    main) and single-project refresh (Option B — always-fresh globals).
    """
    scaffold(report)
    generate_skill_shims(report)
    resolve_preferences(report)
    assemble_settings(report)


def refresh_project(target_arg, report):
    """Re-materialize a single root: true descendant without touching siblings.

    Recomputes apex inputs first, then runs the existing per-child materializer
    for just the target. Does not launch Claude.

    Returns (ok: bool, target: Path | None).
    """
    if not preflight(report):
        return False, None

    # -- Resolve target (relative to apex root, or absolute) --
    target = Path(target_arg)
    if not target.is_absolute():
        target = ROOT / target_arg
    target = target.resolve()

    # -- Validate: real dir, strict descendant of apex, root: true project --
    if not target.is_dir():
        report.fail(f"Refresh: target not found ({target_arg})", "not a directory")
        return False, None
    if target == ROOT or ROOT not in target.parents:
        report.fail(f"Refresh: target outside apex ({target_arg})",
                    f"must be a descendant of {ROOT}")
        return False, None

    child_propagate = _load_module(PREBOOT_DIR / "child_propagate.py")
    claude_md = target / "CLAUDE.md"
    if not claude_md.exists() or not child_propagate._has_root_true(claude_md):
        report.fail(f"Refresh: not a root: true project ({target_arg})",
                    "target CLAUDE.md missing or lacks root: true in frontmatter")
        return False, None

    # -- Recompute apex inputs (Option B: always-correct globals) --
    materialize_apex_inputs(report)

    # -- Materialize the single target via the shared per-child path --
    # propagate_one returns None (not 0) when the apex context is unavailable —
    # treat that as a hard failure, not a silent success.
    if child_propagate.propagate_one(ROOT, target, report) is None:
        report.fail(f"Refresh: '{target.name}' not materialized",
                    "apex .claude/settings.json missing or invalid — run a full boot first")
        return False, None
    report.ok(f"Refresh: materialized '{target.name}' ({target.relative_to(ROOT)}) — siblings untouched")

    # -- Rebuild the inventory and the agents directory --
    # A single-child refresh still rebuilds both, because a project that was just
    # created (or just switched on) must become addressable without waiting for a
    # full apex boot. The walk is cheap and the agent pass is idempotent.
    root_rows = build_root_inventory(report)
    decide_agent_optin(report, root_rows)
    generate_agents(report, root_rows)

    # -- Trace marker --
    try:
        traces_dir = STATE / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        trace_file = traces_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.trace"
        with open(trace_file, "a") as f:
            f.write(f"[{now_iso()}] CONTEXT: project-refresh, target={target}\n")
    except OSError:
        pass

    return True, target


# ── Headless worker modes (--exec / --switch) ────────────────────────

def _resolve_target(target_arg):
    """Resolve a --project value to a validated root: true descendant of the apex.

    Returns (Path, None) on success or (None, error_message) on failure. Pure
    validation — no materialization, no report. Shared by --exec and --switch.
    """
    target = Path(target_arg)
    if not target.is_absolute():
        target = ROOT / target_arg
    target = target.resolve()
    if not target.is_dir():
        return None, f"target not found: {target_arg}"
    if target == ROOT or ROOT not in target.parents:
        return None, f"target outside apex: {target_arg}"
    child_propagate = _load_module(PREBOOT_DIR / "child_propagate.py")
    claude_md = target / "CLAUDE.md"
    if not claude_md.exists() or not child_propagate._has_root_true(claude_md):
        return None, f"not a root: true project: {target_arg}"
    return target, None


def _filter_exec_passthrough(passthrough):
    """Keep only allowlisted flags (+ their values); drop everything else.

    Returns (allowed, dropped). Guards a hard worker from being handed a
    governance-weakening claude flag via passthrough (defense-in-depth even
    once the caller quotes the prompt safely).
    """
    allowed, dropped = [], []
    i = 0
    while i < len(passthrough):
        tok = passthrough[i]
        flag = tok.split("=", 1)[0]
        if flag in _EXEC_PASSTHROUGH_ALLOW:
            has_inline_value = "=" in tok
            has_next_value = i + 1 < len(passthrough) and not passthrough[i + 1].startswith("-")
            if not has_inline_value and not has_next_value:
                # Value-taking flag with no value: drop it. A bare `--resume`
                # would silently resume an unrelated most-recent session.
                dropped.append(tok)
                i += 1
                continue
            allowed.append(tok)
            if not has_inline_value:
                allowed.append(passthrough[i + 1])
                i += 2
                continue
            i += 1
        else:
            dropped.append(tok)
            i += 1
    return allowed, dropped


def exec_in_project(target_arg, prompt, passthrough, prompt_file=None):
    """Mode: hard. Headless hard-rooted worker.

    Prompt source (checked in order): `prompt_file` (a path — read its contents,
    the safe form for untrusted content since bytes never touch a shell command
    line), then `prompt == "-"` (read stdin), else `prompt` as a literal string.

    Runs `claude -p "<prompt>" --output-format json` with cwd=target AND
    CLAUDE_PROJECT_DIR=target, so the child's containment/gravity guards fence at
    the child — a real hard-root, not the soft in-process reroot a subagent gets.
    Captures the result and prints a cboot envelope (session_id, result, cost) to
    stdout. stdout is JSON ONLY (all diagnostics go to stderr) so a caller can
    parse it unambiguously. Returns a process exit code (0 ok, 1 error).

    The explicit CLAUDE_PROJECT_DIR is load-bearing: if the caller is a TTY-less
    subagent, its environment already carries the apex's CLAUDE_PROJECT_DIR, and
    the child would otherwise inherit it and fence at the WRONG root.
    """
    def emit_error(msg, root=None, **extra):
        print(json.dumps({"kind": "error", "mode": "hard", "root": root,
                          "is_error": True, "error": msg, **extra}, indent=2))
        return 1

    target, err = _resolve_target(target_arg)
    if err is not None:
        return emit_error(err)

    try:
        rel = target.relative_to(ROOT).as_posix()
    except ValueError:
        rel = target.as_posix()
    root_info = {"name": _extract_root_name(target / "CLAUDE.md", target.name),
                 "abs_path": target.as_posix(), "rel_path": rel}

    # Resolve the prompt source. --exec-file (data written out-of-band, never shell-
    # framed) is the safe form for untrusted content — see .codex/explicit/ask/start.md.
    # --exec - reads stdin; --exec "literal" is the direct form.
    if prompt_file is not None:
        try:
            prompt = Path(prompt_file).read_text(encoding="utf-8")
        except OSError as e:
            return emit_error(f"--exec-file unreadable: {prompt_file} ({e})", root_info)
    elif prompt == "-":
        if sys.stdin.isatty():
            return emit_error("--exec - given but no prompt on stdin", root_info)
        prompt = sys.stdin.read()
    if not prompt or not prompt.strip():
        return emit_error("empty prompt", root_info)

    # Drop any passthrough flag not on the allowlist; report drops on stderr
    # (stdout must stay pure JSON).
    passthrough, dropped = _filter_exec_passthrough(passthrough)
    if dropped:
        sys.stderr.write(f"cboot --exec: dropped disallowed passthrough: {' '.join(dropped)}\n")

    # Child governance (guards, hooks, autoMemory) comes from its propagated
    # .claude/settings.json. Ensure it exists — lazily, only if missing, and
    # WITHOUT re-materializing apex artifacts when the apex is already booted.
    if not (target / ".claude" / "settings.json").exists():
        rep = BootReport()
        if not (CLAUDE / "settings.json").exists():
            materialize_apex_inputs(rep)
        child_propagate = _load_module(PREBOOT_DIR / "child_propagate.py")
        if child_propagate.propagate_one(ROOT, target, rep) is None:
            return emit_error("child not materialized — run a full `python cboot.py` boot first", root_info)
        sys.stderr.write(f"cboot --exec: materialized '{root_info['name']}' (was unbuilt)\n")

    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        return emit_error("'claude' not found on PATH", root_info)

    cmd = [claude_cmd, "-p", prompt, "--output-format", "json", *passthrough]
    child_env = {**os.environ, "CLAUDE_PROJECT_DIR": str(target)}
    try:
        proc = subprocess.run(cmd, cwd=str(target), capture_output=True,
                              text=True, timeout=EXEC_TIMEOUT, env=child_env)
    except subprocess.TimeoutExpired:
        return emit_error(f"headless claude timed out after {EXEC_TIMEOUT}s", root_info)
    except OSError as e:
        return emit_error(f"failed to spawn claude: {e}", root_info)

    raw = (proc.stdout or "").strip()
    try:
        claude_json = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return emit_error("headless claude produced no parseable JSON", root_info,
                          exit_code=proc.returncode,
                          stderr=(proc.stderr or "").strip()[:2000],
                          stdout=raw[:2000])

    envelope = {
        "kind": "result",
        "mode": "hard",
        "root": root_info,
        "session_id": claude_json.get("session_id"),
        "result": claude_json.get("result"),
        "is_error": bool(claude_json.get("is_error", False)),
        "cost_usd": claude_json.get("total_cost_usd"),
        "duration_ms": claude_json.get("duration_ms"),
        "num_turns": claude_json.get("num_turns"),
    }
    print(json.dumps(envelope, indent=2))
    return 1 if envelope["is_error"] else 0


def switch_command(target_arg):
    """Mode: switch. Print the interactive session-switch command for a child.

    Does NOT launch — a TTY-less caller (e.g. a subagent) can't hand off a
    terminal to an interactive claude. It prints the command for a human to run.
    Non-JSON stdout by design: a caller applying "if json parse, else handoff"
    treats this line as the handoff. Returns a process exit code.
    """
    target, err = _resolve_target(target_arg)
    if err is not None:
        sys.stderr.write(f"cboot --switch: {err}\n")
        return 1
    print(f'python cboot.py --project "{target.as_posix()}" --launch')
    return 0


# ── Main ─────────────────────────────────────────────────────────────

def _extract_project_arg(argv):
    """Pull --project/-p, --launch, --exec, --exec-file (each takes a value), and
    --switch from argv.

    Returns (target | None, launch: bool, exec_prompt | None, exec_file | None,
    switch: bool, remaining_argv). Remaining args pass through to claude — to
    `--launch` for a session, or to `claude -p` for `--exec*` (e.g. `--resume <id>`).
    """
    target = None
    launch = False
    exec_prompt = None
    exec_file = None
    switch = False
    remaining = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--project", "-p"):
            target = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2 if i + 1 < len(argv) else 1
            continue
        if a.startswith("--project="):
            target = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--exec-file":
            exec_file = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2 if i + 1 < len(argv) else 1
            continue
        if a.startswith("--exec-file="):
            exec_file = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--exec":
            exec_prompt = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2 if i + 1 < len(argv) else 1
            continue
        if a.startswith("--exec="):
            exec_prompt = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--switch":
            switch = True
            i += 1
            continue
        if a == "--launch":
            launch = True
            i += 1
            continue
        remaining.append(a)
        i += 1
    return target, launch, exec_prompt, exec_file, switch, remaining


def main():
    # Ensure stdout can handle Unicode (box-drawing, em dashes, etc.)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # --project PATH: single-child modes (no sibling propagation).
    project_target, launch_after, exec_prompt, exec_file, switch_mode, passthrough = _extract_project_arg(sys.argv[1:])

    # --exec*/--switch are worker modes; they require an explicit --project target.
    # Without it, do NOT silently fall through to a full apex boot + interactive
    # launch (which a headless caller would hang on).
    if (exec_prompt is not None or exec_file is not None or switch_mode) and project_target is None:
        sys.stderr.write("cboot: --exec/--exec-file/--switch require --project PATH\n")
        sys.exit(2)

    if project_target is not None:
        # Non-interactive worker modes emit machine output on stdout — no boot report.
        if exec_prompt is not None or exec_file is not None:
            sys.exit(exec_in_project(project_target, exec_prompt, passthrough, prompt_file=exec_file))
        if switch_mode:
            sys.exit(switch_command(project_target))
        # Otherwise: re-materialize the single child (+ optional --launch).
        report = BootReport()
        ok, target = refresh_project(project_target, report)

        report_dir = STATE / "tests" / "boot"
        report_dir.mkdir(parents=True, exist_ok=True)
        label = target.name if target else "INVALID"
        report_file = report_dir / f"{now_stamp()}-refresh-{label}.md"
        report.ok(f"Report: written to {report_file.relative_to(ROOT)}")
        report_file.write_text(report.to_markdown())
        print(report.to_terminal())

        if not ok:
            print("  Project refresh ABORTED.")
            print()
            sys.exit(1)

        if launch_after:
            claude_cmd = shutil.which("claude")
            if not claude_cmd:
                print("  Error: 'claude' command not found. Is Claude Code installed?")
                sys.exit(1)
            try:
                # Explicit CLAUDE_PROJECT_DIR so a launch pasted into an
                # apex-rooted shell still fences the child at the child.
                result = subprocess.run(
                    [claude_cmd, *passthrough], cwd=target,
                    env={**os.environ, "CLAUDE_PROJECT_DIR": str(target)})
                sys.exit(result.returncode)
            except KeyboardInterrupt:
                sys.exit(0)
        sys.exit(0)

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

    # Root inventory — directory of all root: true contexts (rebuilt every boot)
    root_rows = build_root_inventory(report)

    # Addressable agents — ask about anything new, then materialize
    # ^/.claude/agents/. Apex-only; never propagated to a child.
    decide_agent_optin(report, root_rows)
    generate_agents(report, root_rows)

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
        print("  Bootstrap completed with errors.")
        print()

    # --materialize-only: run bootstrap without launching claude. Used to
    # regenerate .claude/settings.json (apex + all children) after changing
    # hook registrations or child-propagation logic.
    if "--materialize-only" in sys.argv:
        sys.exit(1 if report.errors else 0)

    if report.errors:
        print("  Launching Claude Code anyway.")
        print()

    # Launch Claude Code (shutil.which resolves .cmd on Windows)
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
