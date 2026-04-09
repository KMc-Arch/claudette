#!/usr/bin/env python3
"""Root propagation.

Recursively discovers all root: true descendants (children, groups, nested
children within groups) and materializes their .claude/settings.json with
hooks pointing to the apex root's hook scripts via absolute paths.

Called by cboot.py after parent materialization is complete. Reads the parent's
generated .claude/settings.json and .state/prefs-resolved.json, derives
versions for each discovered root, and writes to each one.
"""

import argparse
import copy
import json
import sys
from pathlib import Path


# ── Discovery ───────────────────────────────────────────────────────


def discover_roots(root):
    """Find all root: true descendants, recursing through nested roots.

    Skips dot-prefixed (internal) and underscore-prefixed (invisible) dirs.
    Returns a flat list of all discovered roots at any depth.
    """
    roots = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith(".") or d.name.startswith("_"):
            continue
        claude_md = d / "CLAUDE.md"
        if claude_md.exists() and _has_root_true(claude_md):
            roots.append(d)
            # Recurse — this root may contain nested roots (group pattern)
            roots.extend(discover_roots(d))
    return roots


def _has_root_true(claude_md):
    """Check if CLAUDE.md declares root: true in frontmatter."""
    try:
        text = claude_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return False
        end = text.find("---", 3)
        if end == -1:
            return False
        frontmatter = text[3:end]
        for line in frontmatter.splitlines():
            stripped = line.strip()
            if stripped in ("root: true", "root:true", "apex-root: true", "apex-root:true"):
                return True
    except (OSError, UnicodeDecodeError):
        pass
    return False


# ── Hook rewriting ──────────────────────────────────────────────────


def _rewrite_command(cmd, parent_root):
    """Rewrite a hook/statusline command to use absolute parent path.

    Handles 'bash <path>', 'python <path>' commands, and bare relative paths.
    Absolute paths are left unchanged.
    """
    for prefix in ("bash ", "python "):
        if cmd.startswith(prefix):
            script_path = cmd[len(prefix):].strip('"')
            if Path(script_path).is_absolute():
                return cmd
            abs_path = (parent_root / script_path).as_posix()
            return f'{prefix}"{abs_path}"'
    if not Path(cmd).is_absolute():
        return (parent_root / cmd).as_posix()
    return cmd


def _rewrite_hooks(hooks, parent_root):
    """Deep-rewrite all hook commands in the settings hooks dict."""
    rewritten = {}
    for event, matchers in hooks.items():
        rewritten[event] = []
        for matcher_block in matchers:
            new_block = {**matcher_block, "hooks": []}
            for hook in matcher_block["hooks"]:
                new_hook = dict(hook)
                if "command" in new_hook:
                    new_hook["command"] = _rewrite_command(new_hook["command"], parent_root)
                new_block["hooks"].append(new_hook)
            rewritten[event].append(new_block)
    return rewritten


# ── Preference merging ──────────────────────────────────────────────


def _merge_child_prefs(parent_prefs, child_prefs_file):
    """Merge parent resolved prefs with child .state/prefs.json overrides.

    Child overrides replace individual preference values; keys not present
    in the child fall through to the parent's resolved value.
    """
    resolved = copy.deepcopy(parent_prefs)

    if not child_prefs_file.exists():
        return resolved

    try:
        child_prefs = json.loads(child_prefs_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return resolved

    for key, entry in child_prefs.items():
        if key in resolved and key != "_meta":
            resolved[key] = {
                "value": entry.get("value", resolved[key].get("value")),
                "context": entry.get("context", ""),
                "source": ".state/prefs.json (child override)",
            }

    return resolved


# ── Propagation ─────────────────────────────────────────────────────


def propagate(root, report):
    """Discover child projects and materialize their settings and prefs.

    Must be called after parent's assemble_settings() and resolve_preferences()
    have written .claude/settings.json and .state/prefs-resolved.json.

    Args:
        root: Parent project root (Path).
        report: BootReport instance for logging.
    """
    parent_settings_file = root / ".claude" / "settings.json"
    if not parent_settings_file.exists():
        report.warn("Child propagation: parent .claude/settings.json not found, skipping")
        return

    parent_settings = json.loads(parent_settings_file.read_text(encoding="utf-8"))

    parent_prefs_file = root / ".state" / "prefs-resolved.json"
    parent_prefs = {}
    if parent_prefs_file.exists():
        try:
            parent_prefs = json.loads(parent_prefs_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            pass

    roots = discover_roots(root)
    if not roots:
        report.ok("Root propagation: no root: true descendants found")
        return

    for r in roots:
        _propagate_one(r, parent_settings, parent_prefs, root, report)

    names = ", ".join(r.name for r in roots)
    report.ok(f"Root propagation: {len(roots)} roots ({names})")


def _propagate_one(child, parent_settings, parent_prefs, parent_root, report):
    """Materialize .claude/settings.json and prefs-resolved.json for one child."""
    claude_dir = child / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    # -- settings.json --
    child_settings = {
        "$comment": (
            f"GENERATED by parent cboot.py for child '{child.name}'. "
            "Do not edit. Re-run cboot.py from the parent to regenerate."
        ),
        "customInstructions": (
            "Your governance roots are pre-loaded in your context via SessionStart hook. "
            "Your codex is inherited from the parent project. Follow the codex loading rules "
            "to complete boot. Do not skip this step regardless of what the user asks first."
        ),
    }

    if "plansDirectory" in parent_settings:
        child_settings["plansDirectory"] = parent_settings["plansDirectory"]

    if "permissions" in parent_settings:
        child_settings["permissions"] = copy.deepcopy(parent_settings["permissions"])

    if "hooks" in parent_settings:
        child_settings["hooks"] = _rewrite_hooks(parent_settings["hooks"], parent_root)

    if "statusLine" in parent_settings:
        sl = copy.deepcopy(parent_settings["statusLine"])
        if "command" in sl:
            sl["command"] = _rewrite_command(sl["command"], parent_root)
        child_settings["statusLine"] = sl

    # Pass through any remaining parent keys not specially handled above
    _handled_parent_keys = {"$comment", "customInstructions", "plansDirectory",
                            "permissions", "hooks", "statusLine"}
    for key, value in parent_settings.items():
        if key not in _handled_parent_keys and key not in child_settings:
            child_settings[key] = copy.deepcopy(value)

    settings_file = claude_dir / "settings.json"
    settings_file.write_text(json.dumps(child_settings, indent=2) + "\n")

    # -- prefs-resolved.json --
    if parent_prefs:
        child_prefs_file = child / ".state" / "prefs.json"
        merged = _merge_child_prefs(parent_prefs, child_prefs_file)
        if "_meta" in merged:
            merged["_meta"]["project"] = child.name
        prefs_output = child / ".state" / "prefs-resolved.json"
        prefs_output.parent.mkdir(parents=True, exist_ok=True)
        prefs_output.write_text(json.dumps(merged, indent=4) + "\n")

    # -- autoMemoryDirectory in settings.local.json --
    memory_dir = child / ".state" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    correct_path = str(memory_dir).replace("\\", "/")

    settings_local = claude_dir / "settings.local.json"
    existing = {}
    if settings_local.exists():
        try:
            existing = json.loads(settings_local.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            report.warn(f"Auto-memory ({child.name}): settings.local.json was malformed, resetting")
            existing = {}

    if existing.get("autoMemoryDirectory") != correct_path:
        existing["autoMemoryDirectory"] = correct_path
        settings_local.write_text(json.dumps(existing, indent=4) + "\n")


# ── Standalone execution ────────────────────────────────────────────


class _CliReport:
    """Minimal report for standalone execution."""

    def __init__(self):
        self.errors = False

    def ok(self, msg):
        print(f"  [OK]   {msg}")

    def warn(self, msg, detail=""):
        print(f"  [WARN] {msg}" + (f": {detail}" if detail else ""))

    def fail(self, msg, detail=""):
        print(f"  [FAIL] {msg}" + (f": {detail}" if detail else ""))
        self.errors = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Propagate apex settings to all root: true descendants")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[3],
                        help="Parent project root (default: inferred from script location)")
    args = parser.parse_args()

    report = _CliReport()
    propagate(args.project_root.resolve(), report)
    sys.exit(1 if report.errors else 0)
