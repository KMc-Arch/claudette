#!/usr/bin/env python3
"""Root propagation.

Recursively discovers all root: true descendants (children, groups, nested
children within groups) and materializes their .claude/settings.json with
hooks pointing to the apex root's hook scripts via absolute paths, and
replicates skill shims so /commands are available in child sessions.

Called by cboot.py after parent materialization is complete. Reads the parent's
generated .claude/settings.json, .claude/skills/, and .state/prefs-resolved.json,
derives versions for each discovered root, and writes to each one.
"""

import argparse
import copy
import json
import re
import sys
from pathlib import Path


# Matches the broken/legacy Claude Code permission form Bash(command:<prefix>*).
# The canonical form is Bash(<prefix>:*). The legacy form is non-functional
# because the colon inside the parentheses is treated literally, so the rule
# matches nothing. See https://code.claude.com/docs/en/permissions.md.
_BROKEN_BASH_RULE = re.compile(r"^Bash\(command:(.+?)\s*\*\)$")


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
        text = claude_md.read_text(encoding="utf-8-sig")
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


# ── Skill shim propagation ─────────────────────────────────────────


def _collect_parent_shims(parent_root):
    """Read all SKILL.md shims from the parent's .claude/skills/.

    Returns a dict of {skill_name: shim_content} with paths rewritten
    to absolute so they resolve from any child working directory.
    """
    skills_dir = parent_root / ".claude" / "skills"
    if not skills_dir.is_dir():
        return {}

    codex_rel = ".codex/explicit"
    codex_abs = (parent_root / codex_rel).as_posix()
    shims = {}
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        content = skill_md.read_text(encoding="utf-8")
        # Rewrite relative codex path to absolute
        content = content.replace(
            f"Read and follow {codex_rel}/",
            f"Read and follow {codex_abs}/",
        )
        shims[skill_dir.name] = content
    return shims


def _write_child_shims(child, shims):
    """Write skill shims into a child's .claude/skills/, preserving child-local shims."""
    skills_dir = child / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for name, content in shims.items():
        shim_dir = skills_dir / name
        shim_dir.mkdir(parents=True, exist_ok=True)
        (shim_dir / "SKILL.md").write_text(content, encoding="utf-8")


# ── Child codex settings merging ────────────────────────────────────


def _merge_child_codex_settings(child_settings, child_codex_settings):
    """Merge child .codex/settings.json over propagated parent settings.

    permissions.allow and permissions.deny are additive (child entries appended, deduped).
    A child can make deny stricter but never weaker.
    All other keys: child overrides parent (innermost wins).
    """
    for key, value in child_codex_settings.items():
        if key == "$comment":
            continue
        if key == "permissions" and "permissions" in child_settings:
            parent_allow = child_settings["permissions"].get("allow", [])
            child_allow = value.get("allow", [])
            merged = list(dict.fromkeys(parent_allow + child_allow))
            child_settings["permissions"]["allow"] = merged
            for pkey, pval in value.items():
                if pkey == "allow":
                    continue  # already handled above
                elif pkey == "deny":
                    parent_deny = child_settings["permissions"].get("deny", [])
                    merged_deny = list(dict.fromkeys(parent_deny + pval))
                    child_settings["permissions"]["deny"] = merged_deny
                else:
                    child_settings["permissions"][pkey] = pval
        else:
            child_settings[key] = copy.deepcopy(value)


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


# ── Broken permission-rule healing ─────────────────────────────────


def _heal_broken_perm_rules(settings_local_file):
    """Rewrite legacy Bash(command:<prefix>*) rules to canonical Bash(<prefix>:*).

    The legacy form is a silent no-op in Claude Code — the colon inside the
    parentheses is treated literally, so rules like `Bash(command:git add*)`
    never match anything and users wonder why their allowlist isn't working.
    This pass auto-heals drift on every boot so hand-edits can't re-introduce
    the broken form. Dedupes while preserving first-occurrence order.

    Returns the number of rules rewritten (0 if file missing, unreadable, or clean).
    """
    if not settings_local_file.exists():
        return 0
    try:
        data = json.loads(settings_local_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return 0
    perms = data.get("permissions")
    if not isinstance(perms, dict):
        return 0

    rewritten = 0
    for key in ("allow", "deny"):
        rules = perms.get(key)
        if not isinstance(rules, list):
            continue
        new_rules = []
        for rule in rules:
            if isinstance(rule, str):
                m = _BROKEN_BASH_RULE.match(rule)
                if m:
                    rule = f"Bash({m.group(1).rstrip()}:*)"
                    rewritten += 1
            new_rules.append(rule)
        # Dedupe, preserving first-occurrence order
        perms[key] = list(dict.fromkeys(new_rules))

    if rewritten > 0:
        settings_local_file.write_text(json.dumps(data, indent=4) + "\n")
    return rewritten


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

    parent_shims = _collect_parent_shims(root)

    # Heal parent's own settings.local.json before propagating to children,
    # so broken rules never get merged into child allow/deny lists.
    heal_rules = _heal_broken_perm_rules(root / ".claude" / "settings.local.json")
    heal_projects = 1 if heal_rules > 0 else 0
    scanned = 1

    roots = discover_roots(root)
    if not roots:
        report.ok("Root propagation: no root: true descendants found")
    else:
        for r in roots:
            child_rules = _propagate_one(r, parent_settings, parent_prefs, parent_shims, root, report)
            scanned += 1
            if child_rules > 0:
                heal_rules += child_rules
                heal_projects += 1
        names = ", ".join(r.name for r in roots)
        report.ok(f"Root propagation: {len(roots)} roots ({names})")

    project_word = "project" if scanned == 1 else "projects"
    if heal_rules == 0:
        report.ok(f"Local perms heal: no broken Bash rules ({scanned} {project_word} scanned)")
    else:
        report.ok(f"Local perms heal: fixed {heal_rules} broken Bash rules in {heal_projects} of {scanned} {project_word}")


def _propagate_one(child, parent_settings, parent_prefs, parent_shims, parent_root, report):
    """Materialize .claude/settings.json, skill shims, and prefs-resolved.json for one child.

    Returns the number of broken Bash permission rules healed in this child's
    settings.local.json (0 if clean or file absent).
    """
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

    # Merge child's own codex settings if present (innermost wins)
    child_codex_settings_file = child / ".codex" / "settings.json"
    if child_codex_settings_file.exists():
        try:
            child_codex = json.loads(child_codex_settings_file.read_text(encoding="utf-8"))
            _merge_child_codex_settings(child_settings, child_codex)
            child_settings["$comment"] = (
                f"GENERATED by parent cboot.py for child '{child.name}' "
                f"(merged with {child.name}/.codex/settings.json). "
                "Do not edit. Re-run cboot.py from the parent to regenerate."
            )
        except (json.JSONDecodeError, ValueError, OSError):
            report.warn(f"Child {child.name}: invalid .codex/settings.json, skipping merge")

    settings_file = claude_dir / "settings.json"
    settings_file.write_text(json.dumps(child_settings, indent=2) + "\n")

    # -- settings.local.json: autoMemoryDirectory --
    child_memory = child / ".state" / "memory"
    child_memory.mkdir(parents=True, exist_ok=True)
    correct_mem_path = str(child_memory).replace("\\", "/")

    settings_local = claude_dir / "settings.local.json"
    local_existing = {}
    if settings_local.exists():
        try:
            local_existing = json.loads(settings_local.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            local_existing = {}

    if local_existing.get("autoMemoryDirectory") != correct_mem_path:
        local_existing["autoMemoryDirectory"] = correct_mem_path

    # -- settings.local.json: propagate parent local permissions --
    parent_local_file = parent_root / ".claude" / "settings.local.json"
    if parent_local_file.exists():
        try:
            parent_local = json.loads(parent_local_file.read_text(encoding="utf-8"))
            parent_local_perms = parent_local.get("permissions", {})
            parent_local_allow = parent_local_perms.get("allow", [])
            parent_local_deny = parent_local_perms.get("deny", [])
            if parent_local_allow or parent_local_deny:
                local_existing.setdefault("permissions", {})
            if parent_local_allow:
                child_local_allow = local_existing["permissions"].get("allow", [])
                merged_allow = list(dict.fromkeys(parent_local_allow + child_local_allow))
                local_existing["permissions"]["allow"] = merged_allow
            if parent_local_deny:
                child_local_deny = local_existing["permissions"].get("deny", [])
                merged_deny = list(dict.fromkeys(parent_local_deny + child_local_deny))
                local_existing["permissions"]["deny"] = merged_deny
        except (json.JSONDecodeError, ValueError):
            pass

    settings_local.write_text(json.dumps(local_existing, indent=4) + "\n")

    # -- skill shims --
    if parent_shims:
        _write_child_shims(child, parent_shims)

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

    # Heal any legacy Bash(command:<prefix>*) rules that drifted in (either
    # from the parent's local perms just merged above, or from hand-edits to
    # the child's own settings.local.json).
    return _heal_broken_perm_rules(settings_local)


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
