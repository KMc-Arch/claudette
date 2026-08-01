#!/usr/bin/env python3
"""Destructive purge verification for TestBench.

Populates dummy content, runs purge, verifies correctness against the allowlist
model:

  bare `purge`  — removes SAFE tier; prunes keep-recent dirs (traces, boot) to the
                  newest KEEP_RECENT REAL files (a _-prefixed match never takes a keep
                  slot); KEEPS precious (pauses), high-value (memory/work/plans/bundles)
                  and loose .tmp/ buffers; REPORTS sandbox rigs and stragglers without
                  deleting them.
  `purge all`   — nuclear: everything on the allowlist, keep-recent wiped entirely,
                  precious + high-value gone, and the ENTIRE .tmp/ cleared (loose
                  buffers + sandbox rigs). Straggler detection stays report-only; the
                  hard floor still survives — including a _-prefixed item buried inside
                  a high-value dir and the dir that holds it.

Designed to be run from the apex root.

── MODE MAP — what each invocation runs ─────────────────────────────────────
  populate   Create every fixture (no purge). For manual inspection.
  standard   Bare purge on TestBench. Inline coverage: refresh keep-recent (5 REAL
             kept even with _pinned.trace present), _-prefix protection
             (.claude/_keep.md + nested .state/memory/sub/_secret.md), settings
             preservation, sandbox rig REPORTED+kept, and a --dry-run preview pre-pass.
  all        Nuclear purge on TestBench, run under an ISOLATED HOME seeded with this
             project's transcript footprint (validates the slug + external removal,
             never touches the real ~/.claude/projects/). Asserts: _pinned.trace and
             nested _secret.md (+ its sub/ dir) SURVIVE the keep=0/high-value wipe;
             the whole .tmp/ incl. the sandbox rig is DELETED (not reported).
  dryrun     Dedicated --dry-run test: asserts "would remove" is emitted and
             every fixture STILL EXISTS afterward.
  footprint  External footprint (~/.claude/projects/<slug>/) under an ISOLATED
             HOME (temp dir) — bare keeps it, `all` removes it — plus an INDEPENDENT
             golden-slug oracle (catches a slug regression the round-trip can't), the
             no-fuzzy-fallback fail-safe (a decoy sharing the leaf name survives), and
             the fail-loud WARNING when no store resolves. NEVER touches the real dir.
  child      Nested `qachild/` child-scope purge: SAFE removed, high-value +
             settings kept, traces pruned; parent untouched; nonexistent child AND
             an out-of-root escape (isolated from the not-a-dir check) each rejected.
  symlink    Symlink protection on a throwaway REAL-fs root: a symlink inside a
             high-value dir survives `purge all` and its target is never reached
             THROUGH the link. Skips if the platform can't make symlinks.
  full       Runs standard, all, dryrun, footprint, child, symlink and aggregates.

Cleanup is self-healing: purge removes .claude/skills as SAFE tier, so cleanup
regenerates the child via `cboot.py --project Testing/TestBench` from the apex,
leaving the working tree whole. After any run, `git status --porcelain Testing/`
shows only the test-purge.py edit.

Usage:
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py populate
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py standard
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py all
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py dryrun
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py footprint
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py child
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py symlink
    python Testing/TestBench/.codex/explicit/test-purge/test-purge.py full
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# TestBench root: up 4 levels from .codex/explicit/test-purge/test-purge.py
TESTBENCH = Path(__file__).resolve().parents[3]
# Apex root: up from Testing/TestBench/
APEX = TESTBENCH.parents[1]
PURGE_SCRIPT = APEX / ".codex" / "explicit" / "purge" / "purge.py"
CBOOT_SCRIPT = APEX / "cboot.py"

# Scratch-looking files at the project root, OUTSIDE .tmp/. purge must REPORT each
# (straggler detection) but never delete it. Two patterns so a second TMP_STRAGGLER
# pattern is exercised, not just one.
STRAGGLER_FILE = "stray-prbody.md"   # matches *-prbody.md
STRAGGLER_FILE2 = "stray.bak"        # matches *.bak

# Golden slug values — HAND-COMPUTED, NOT derived from purge's own function. They
# anchor purge._project_slug to independent truth, so a regression (e.g. reverting to
# the old `\ / :`-only mapping) is caught even though the footprint fixture also uses
# an independent reimplementation (see _slug). `~`/`.`-roots are the real cases the
# slug fix exists to serve.
GOLDEN_SLUGS = {
    "/mnt/claudette": "-mnt-claudette",
    "/mnt/claudette/~majel": "-mnt-claudette--majel",
    "/mnt/claudette/.steward": "-mnt-claudette--steward",
    "/x/a.b": "-x-a-b",
}

# _-prefix protection fixtures. .claude/_keep.md survives BOTH scopes. _pinned.trace
# is created in BOTH scopes now: it matches the *.trace keep-recent glob but, being
# _-prefixed, is EXCLUDED from the keep-recent candidate list — so it must never
# occupy a keep slot (bare keeps 5 REAL traces) and must survive keep=0 (all).
UNDERSCORE_KEEP_REL = ".claude/_keep.md"
PINNED_TRACE_REL = ".state/traces/_pinned.trace"

# Nested _-prefixed secret buried in a high-value dir (ONE level down, a DIRECT child
# of sub/). Under `purge all`, remove_dir must keep it AND the .state/memory/sub/ dir
# that holds it — emptying the dir of deletables (its DUMMY_FILES sibling deleteme.md)
# rather than rmtree-ing it away. Exercises the DIRECT-child protection branch.
NESTED_SECRET_REL = ".state/memory/sub/_secret.md"

# TWO levels down, and the ONLY protected item under memory/deep/ is reachable purely
# by RECURSING into deeper/ (deep/ has no protected direct child). This exercises
# remove_dir's recursive survival-propagation — the branch a one-level fixture can't
# reach (a mutation there would rmtree deep/ and destroy _deep.md). Its sibling
# gone.md (DUMMY_FILES, scope all) proves deeper/ is pruned, not skipped wholesale.
NESTED_DEEP_SECRET_REL = ".state/memory/deep/deeper/_deep.md"

# Sandbox rig. bare/child REPORT it (kept, report-only); `purge all` DELETES it
# outright (the whole .tmp/ is cleared, sandbox included).
SANDBOX_RIG_REL = ".tmp/sandbox/dummy-rig/contents.md"

# Settings preservation. purge keeps every settings*.json in .claude/. TestBench
# ships a real settings.local.json; if present we assert it survives and NEVER
# delete it in cleanup. Only a dummy WE create (tagged with the marker) is removed.
SETTINGS_LOCAL_REL = ".claude/settings.local.json"
SETTINGS_LOCAL_MARKER = "_testPurgeDummy"


# Keep-recent prune count: read straight from purge.py (no hand-copied constant —
# avoids drift). Populate more than N of each keep-recent kind; expect oldest
# pruned, newest kept under bare purge, and all wiped under `purge all`. Lexical
# name order is ASSUMED to equal chronological order (purge sorts by filename),
# which the ISO-style names below satisfy by construction.
def _purge_constant(name: str, default):
    try:
        spec = importlib.util.spec_from_file_location("_purge_for_const", PURGE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, name, default)
    except Exception:
        return default


KEEP_RECENT = _purge_constant("KEEP_RECENT", 5)
# N+2 files each so the newest-N prune leaves exactly 2 casualties per dir.
BOOT_REPORTS = [f"2026-04-03-{i:04d}-bootstrap.md" for i in range(1, KEEP_RECENT + 3)]
# Refresh reports share the tests/boot dir but a DIFFERENT glob (*-refresh-*.md);
# purge prunes each glob independently. ISO-style names sort chronologically.
REFRESH_REPORTS = [f"2026-05-{i:02d}T0000-refresh-child.md" for i in range(1, KEEP_RECENT + 3)]
TRACE_FILES = [f"2026-04-{i:02d}.trace" for i in range(1, KEEP_RECENT + 3)]

# (reldir, filenames) keep-recent fixtures — mirror purge's KEEP_RECENT_TARGETS
# (traces/*.trace, tests/boot/*-bootstrap.md, tests/boot/*-refresh-*.md).
KEEP_RECENT_FIXTURES = [
    (".state/tests/boot", BOOT_REPORTS),
    (".state/tests/boot", REFRESH_REPORTS),
    (".state/traces", TRACE_FILES),
]


# ── Dummy content definitions ──────────────────────────────────────

# (relative_path, content, scope)
#   scope "standard" — removed by default purge (and by all)   [SAFE tier]
#   scope "all"      — removed only by `purge all`             [precious / high-value / loose]
DUMMY_FILES = [
    # SAFE tier — removed by default (and all)
    (".claude/session.jsonl", '{"dummy": true}\n', "standard"),
    (".claude/conversation.md", "# Dummy conversation\n", "standard"),
    # .claude/agents/ shim dir — SAFE tier, removed wholesale like skills/ (covers the
    # `agents` branch of _purge_claude_dir).
    (".claude/agents/dummy-agent/AGENT.md", "# dummy agent shim\n", "standard"),
    (".state/prefs-resolved.json", '{"dummy": true}\n', "standard"),
    (".state/tests/compliance/dummy-compliance.md", "# Dummy compliance log\n", "standard"),
    # PRECIOUS (session continuity) — kept by default, removed only by `purge all`
    (".state/pauses/dummy-pause.md", "# Dummy pause\n", "all"),
    # HIGH-VALUE (project brains) — removed only by `purge all`
    (".state/memory/dummy-memory.md", "---\nname: dummy\ntype: project\n---\nDummy.\n", "all"),
    # Deletable sibling of the nested _secret (1 level) — proves remove_dir PRUNES the
    # dir (deletes this) rather than skipping it wholesale. Dies under all, kept under bare.
    (".state/memory/sub/deleteme.md", "# deletable sibling of _secret.md\n", "all"),
    # Deletable sibling of the 2-level-deep _deep — proves deeper/ is pruned during the
    # recursive descent (dies under all).
    (".state/memory/deep/deeper/gone.md", "# deletable, two levels deep\n", "all"),
    (".state/work/dummy-work.md", "# Dummy work item\n", "all"),
    (".state/plans/dummy-plan.md", "# Dummy plan\n", "all"),
    (".state/bundles/dummy-bundle/contents.md", "# Dummy bundle\n", "all"),
    # Loose .tmp/ buffer — kept by default, removed by `purge all` (no freshness guard)
    (".tmp/dummy-buffer.txt", "# loose buffer\n", "all"),
]

# Files that must survive ALL purge modes
SURVIVORS = [
    ".state/tests/audits/20260403-0000/findings.md",
    NESTED_SECRET_REL,       # nested _-prefixed secret (1 level) — protected at depth
    NESTED_DEEP_SECRET_REL,  # nested _-prefixed secret (2 levels) — recursion branch
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

def populate(scope: str = "all"):
    """Create dummy files, the audit fixture, keep-recent fixtures, stragglers, and
    the _-prefix / settings-preservation fixtures.

    `scope` no longer gates any fixture (all are created every run); it is retained
    only for the log header. In particular _pinned.trace is now created in BOTH scopes
    because it is EXCLUDED from the keep-recent candidate list and so cannot shift the
    window — its presence under bare is itself the assertion.
    """
    print(f"\n  Populating TestBench at {TESTBENCH} (scope={scope})\n")

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

    # Keep-recent fixtures — exercise the keep-newest-N prune (bare) and full wipe (all).
    for reldir, names in KEEP_RECENT_FIXTURES:
        d = TESTBENCH / reldir
        d.mkdir(parents=True, exist_ok=True)
        for name in names:
            (d / name).write_text(f"# {name}\n")
            created += 1
        print(f"    created: {len(names)} files in {reldir}")

    # Stragglers: scratch-looking files OUTSIDE .tmp/, at the project root (two
    # distinct TMP_STRAGGLER patterns).
    (TESTBENCH / STRAGGLER_FILE).write_text("# stray scratch outside .tmp/\n")
    (TESTBENCH / STRAGGLER_FILE2).write_text("# stray .bak outside .tmp/\n")
    created += 2
    print(f"    created: {STRAGGLER_FILE}, {STRAGGLER_FILE2} (stragglers)")

    # _-prefix protection: .claude/_keep.md survives BOTH scopes.
    keep = TESTBENCH / UNDERSCORE_KEEP_REL
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("# _-prefixed — must survive every scope\n")
    created += 1
    print(f"    created: {UNDERSCORE_KEEP_REL} (_-prefixed, must survive)")

    # Settings preservation: ensure .claude/settings.local.json exists. Only create
    # (tagged) if absent — never clobber TestBench's real one.
    slp = TESTBENCH / SETTINGS_LOCAL_REL
    if not slp.exists():
        slp.parent.mkdir(parents=True, exist_ok=True)
        slp.write_text(json.dumps({SETTINGS_LOCAL_MARKER: True}) + "\n")
        created += 1
        print(f"    created: {SETTINGS_LOCAL_REL} (dummy settings, must survive)")
    else:
        print(f"    present: {SETTINGS_LOCAL_REL} (real settings — must survive, not ours to delete)")

    # _-prefixed trace — created in BOTH scopes. Excluded from the keep-recent
    # candidate list, so under bare it must NOT occupy a keep slot (5 REAL traces
    # survive) and under `all` (keep=0) it survives the wipe.
    pinned = TESTBENCH / PINNED_TRACE_REL
    pinned.parent.mkdir(parents=True, exist_ok=True)
    pinned.write_text("# _-prefixed trace — excluded from keep-recent, survives every scope\n")
    created += 1
    print(f"    created: {PINNED_TRACE_REL} (_-prefixed trace, must survive every scope)")

    # Nested _-prefixed secret inside a high-value dir. Under `purge all` remove_dir
    # keeps it AND .state/memory/sub/, while deleting the deletable DUMMY_FILES sibling.
    secret = TESTBENCH / NESTED_SECRET_REL
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("# nested _-prefixed secret — must survive purge all\n")
    created += 1
    print(f"    created: {NESTED_SECRET_REL} (nested _-prefixed, must survive purge all)")

    # 2-levels-deep _-prefixed secret (recursion-branch coverage). Its parent deep/ has
    # no protected DIRECT child, so only a recursive descent into deeper/ keeps it alive.
    deep = TESTBENCH / NESTED_DEEP_SECRET_REL
    deep.parent.mkdir(parents=True, exist_ok=True)
    deep.write_text("# 2-level-deep _-prefixed secret — must survive purge all\n")
    created += 1
    print(f"    created: {NESTED_DEEP_SECRET_REL} (2-level nested _-prefixed, must survive purge all)")

    # Sandbox rig: reported+kept under bare/child, DELETED under `purge all`.
    rig = TESTBENCH / SANDBOX_RIG_REL
    rig.parent.mkdir(parents=True, exist_ok=True)
    rig.write_text("# Dummy sandbox rig\n")
    created += 1
    print(f"    created: {SANDBOX_RIG_REL} (sandbox rig — reported under bare, deleted under all)")

    print(f"\n  {created} dummy artifacts created.\n")


# ── Run purge ──────────────────────────────────────────────────────

def run_purge(scope: str, extra_args: list | None = None, env: dict | None = None,
              project_root: Path | None = None):
    """Invoke purge.py. Returns (returncode, stdout).

    `env` lets the footprint test point purge's Path.home() at an isolated HOME so
    it never touches the real ~/.claude/projects/. `project_root` overrides the
    default (TESTBENCH).
    """
    root = project_root or TESTBENCH
    cmd = [
        sys.executable, str(PURGE_SCRIPT),
        scope,
        "--project-root", str(root),
        "--confirm",
    ]
    if extra_args:
        cmd += extra_args
    print(f"\n  Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            print(f"    ERR: {line}")
    print()
    return result.returncode, result.stdout or ""


def regenerate_child():
    """Re-materialize TestBench so purge's removal of .claude/skills is undone.

    purge deletes .claude/skills as SAFE tier; without regeneration a run would
    leave the child's shim dir missing (a damaged working tree). cboot --project
    rebuilds it. Best-effort: a failure here must not fail an otherwise-green test.
    """
    if not CBOOT_SCRIPT.exists():
        print(f"    WARN: cboot not found at {CBOOT_SCRIPT}; skills not regenerated")
        return
    try:
        r = subprocess.run(
            [sys.executable, str(CBOOT_SCRIPT), "--project", "Testing/TestBench"],
            cwd=str(APEX), capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            print(f"    WARN: cboot regeneration exited {r.returncode}")
    except Exception as e:  # noqa: BLE001 — best-effort cleanup
        print(f"    WARN: cboot regeneration failed: {e}")


# ── Verify ─────────────────────────────────────────────────────────

def _verify_keep_recent(scope: str, reldir: str, files: list, errors: list) -> None:
    """Bare purge keeps the newest KEEP_RECENT; `purge all` wipes the dir."""
    d = TESTBENCH / reldir
    ordered = sorted(files)
    if scope == "all":
        for name in ordered:
            if (d / name).exists():
                errors.append(f"SHOULD BE GONE:  {reldir}/{name} (purge all wipes keep-recent)")
    else:
        for name in ordered[:-KEEP_RECENT]:
            if (d / name).exists():
                errors.append(f"SHOULD BE GONE:  {reldir}/{name} (beyond newest {KEEP_RECENT})")
        for name in ordered[-KEEP_RECENT:]:
            if not (d / name).exists():
                errors.append(f"WRONGLY DELETED: {reldir}/{name} (within newest {KEEP_RECENT})")


def verify(scope: str, stdout: str) -> list[str]:
    """Check that the right files survived or died, and detection was reported."""
    errors = []

    if scope == "all":
        should_die = [r for r, _, s in DUMMY_FILES if s in ("standard", "all")]
        should_live = []  # every DUMMY_FILES entry dies under all; survivors are separate
    else:  # default
        should_die = [r for r, _, s in DUMMY_FILES if s == "standard"]
        should_live = [r for r, _, s in DUMMY_FILES if s == "all"]

    for rel in should_die:
        if (TESTBENCH / rel).exists():
            errors.append(f"SHOULD BE GONE:  {rel}")

    for rel in should_live:
        if not (TESTBENCH / rel).exists():
            errors.append(f"WRONGLY DELETED: {rel} (should survive {scope} purge)")

    for rel in SURVIVORS:
        if not (TESTBENCH / rel).exists():
            errors.append(f"WRONGLY DELETED: {rel} (must always survive)")

    # Keep-recent: boot reports, refresh reports, and traces.
    for reldir, names in KEEP_RECENT_FIXTURES:
        _verify_keep_recent(scope, reldir, names, errors)

    # _-prefix protection: .claude/_keep.md survives every scope.
    if not (TESTBENCH / UNDERSCORE_KEEP_REL).exists():
        errors.append(f"WRONGLY DELETED: {UNDERSCORE_KEEP_REL} (_-prefixed must survive {scope})")

    # Settings preservation: settings.local.json survives every scope.
    if not (TESTBENCH / SETTINGS_LOCAL_REL).exists():
        errors.append(f"WRONGLY DELETED: {SETTINGS_LOCAL_REL} (settings*.json must survive {scope})")

    # _-prefix keep-recent assertion (BOTH scopes): _pinned.trace matches *.trace but
    # is excluded from the keep-recent candidate list, so it never occupies a keep slot
    # (the 5-REAL-traces check above) and survives keep=0 under `all`.
    if not (TESTBENCH / PINNED_TRACE_REL).exists():
        errors.append(f"WRONGLY DELETED: {PINNED_TRACE_REL} (_-prefixed must survive {scope})")

    # Nested _-prefixed secret survives every scope; under `all`, the dir holding it
    # must survive too (emptied of deletables, not rmtree'd away).
    if not (TESTBENCH / NESTED_SECRET_REL).exists():
        errors.append(f"WRONGLY DELETED: {NESTED_SECRET_REL} (nested _-prefixed must survive {scope})")
    if scope == "all" and not (TESTBENCH / ".state" / "memory" / "sub").is_dir():
        errors.append("WRONGLY DELETED: .state/memory/sub/ (dir holding _secret.md must survive all)")

    # 2-level-deep _-item: both dirs on the path to it must survive `all` (recursive
    # survival-propagation), even though deep/ has no protected DIRECT child.
    if scope == "all":
        for d in (".state/memory/deep", ".state/memory/deep/deeper"):
            if not (TESTBENCH / d).is_dir():
                errors.append(f"WRONGLY DELETED: {d}/ (dir on the path to a 2-level-deep _-item must survive all)")

    # Stragglers: reported in output, but NOT removed — every scope. Two patterns.
    for sf in (STRAGGLER_FILE, STRAGGLER_FILE2):
        if not (TESTBENCH / sf).exists():
            errors.append(f"WRONGLY DELETED: {sf} (straggler must not be removed)")
        if "STRAGGLER" not in stdout or sf not in stdout:
            errors.append(f"NOT REPORTED: straggler {sf} not surfaced in purge output")

    # Sandbox rig: bare/child REPORT + KEEP it; `purge all` DELETES it (not reported).
    rig = TESTBENCH / SANDBOX_RIG_REL
    if scope == "all":
        if rig.exists():
            errors.append(f"SHOULD BE GONE:  {SANDBOX_RIG_REL} (purge all clears the whole .tmp/)")
        if (TESTBENCH / ".tmp" / "sandbox").exists():
            errors.append("SHOULD BE GONE:  .tmp/sandbox/ (purge all clears it)")
        if "SANDBOX" in stdout:
            errors.append("MISREPORTED: purge all should DELETE sandbox, not report it as kept")
    else:
        if not rig.exists():
            errors.append(f"WRONGLY DELETED: {SANDBOX_RIG_REL} (bare must keep sandbox — report only)")
        if "SANDBOX" not in stdout or "dummy-rig" not in stdout:
            errors.append("NOT REPORTED: sandbox rig dummy-rig not surfaced under bare purge")

    return errors


def assert_dry_run_preview(scope: str, env: dict | None = None) -> list[str]:
    """Inline --dry-run pre-pass: purge must PREVIEW ("would remove") and delete
    nothing. Run against the freshly-populated fixtures before the real purge.

    `env` carries the isolated HOME for the `all` scope so the preview never reads
    the real ~/.claude/projects/."""
    errors = []
    rc, out = run_purge(scope, ["--dry-run"], env=env)
    if rc != 0:
        errors.append(f"DRY-RUN: purge exited {rc}")
    if "would remove" not in out:
        errors.append("DRY-RUN: output missing 'would remove' preview text")
    # Representative fixtures a real purge WOULD delete must still be present.
    for probe in (".state/prefs-resolved.json", ".claude/session.jsonl",
                  f".state/tests/boot/{BOOT_REPORTS[0]}"):
        if not (TESTBENCH / probe).exists():
            errors.append(f"DRY-RUN: fixture {probe} was deleted (preview must not delete)")
    return errors


# ── Cleanup ────────────────────────────────────────────────────────

def cleanup():
    """Remove every artifact the test created, leaving TestBench pristine, then
    regenerate the child's .claude/skills (purge removed them as SAFE tier).

    Only test-created files are removed — real .state/traces/, .state/tests/boot/
    history and TestBench's real settings.local.json are left intact.
    """
    for rel, _, _ in DUMMY_FILES:
        try:
            (TESTBENCH / rel).unlink()
        except OSError:
            pass
    for reldir, names in KEEP_RECENT_FIXTURES:
        for name in names:
            try:
                (TESTBENCH / reldir / name).unlink()
            except OSError:
                pass
    for d in (".tmp/sandbox", ".state/bundles/dummy-bundle", ".state/tests/compliance",
              ".state/memory/sub", ".state/memory/deep", ".claude/agents"):
        shutil.rmtree(TESTBENCH / d, ignore_errors=True)
    for rel in (STRAGGLER_FILE, STRAGGLER_FILE2, UNDERSCORE_KEEP_REL, PINNED_TRACE_REL):
        try:
            (TESTBENCH / rel).unlink()
        except OSError:
            pass

    # settings.local.json: remove ONLY the dummy we created (tagged with marker).
    # Never delete a real settings.local.json we didn't author.
    slp = TESTBENCH / SETTINGS_LOCAL_REL
    if slp.exists():
        try:
            data = json.loads(slp.read_text())
            if isinstance(data, dict) and data.get(SETTINGS_LOCAL_MARKER):
                slp.unlink()
        except (OSError, ValueError):
            pass

    # Regenerate .claude/skills so the working tree is whole again.
    regenerate_child()


# ── Report ─────────────────────────────────────────────────────────

def emit_report(title: str, errors: list, ok_lines: list | None = None) -> None:
    print("  +---------------------------------------------+")
    print(f"  |  {title:<41}|")
    print("  +---------------------------------------------+")
    print()
    if errors:
        for e in errors:
            print(f"    FAIL  {e}")
        print(f"\n  {len(errors)} failures.\n")
    else:
        for line in (ok_lines or []):
            print(f"    {line}")
        print(f"\n  ALL PASSED.\n")


# ── Test flows ─────────────────────────────────────────────────────

def run_scope_test(mode: str) -> list[str]:
    """standard / all: populate → dry-run preview → real purge → verify → cleanup.

    For the `all` scope the real purge runs under an ISOLATED HOME (temp dir) seeded
    with this project's transcript-store footprint — so `purge all` exercises the
    external-footprint removal end to end (validating the slug) WITHOUT ever touching
    the real ~/.claude/projects/. Cleanup (fixtures + temp HOME) is try/finally-guarded.
    """
    scope = "default" if mode == "standard" else "all"
    populate(scope)
    errors = []
    tmp_home = None
    env = None
    fp = None
    try:
        if scope == "all":
            tmp_home = Path(tempfile.mkdtemp(prefix="test-purge-home-"))
            fp = tmp_home / ".claude" / "projects" / _slug(TESTBENCH)
            fp.mkdir(parents=True)
            (fp / "transcript.jsonl").write_text('{"transcript": true}\n')
            env = {**os.environ, "HOME": str(tmp_home)}

        # Inline --dry-run preview: must preview, delete nothing (isolated HOME too).
        errors += assert_dry_run_preview(scope, env)

        rc, stdout = run_purge(scope, env=env)
        if rc != 0:
            errors.append(f"purge exited with code {rc}")
            return errors

        errors += verify(scope, stdout)

        if scope == "all" and fp is not None and fp.exists():
            errors.append("footprint: isolated-HOME transcript store NOT removed under all (slug mismatch?)")
    finally:
        cleanup()
        if tmp_home is not None:
            shutil.rmtree(tmp_home, ignore_errors=True)

    if scope == "default":
        expected_dead = len([r for r, _, s in DUMMY_FILES if s == "standard"])
        ok = [
            f"{expected_dead} SAFE files removed; precious + high-value + loose buffers kept",
            f"keep-recent pruned to newest {KEEP_RECENT} REAL (bootstrap + refresh + traces; _pinned excluded)",
            "sandbox rig + straggler REPORTED (not removed); _keep.md + _secret.md + settings survived",
        ]
    else:
        expected_dead = len([r for r, _, s in DUMMY_FILES if s in ("standard", "all")])
        ok = [
            f"{expected_dead} files removed (SAFE + precious + high-value + loose); footprint removed",
            "keep-recent wiped; whole .tmp/ cleared incl. sandbox rig; straggler still reported",
            "_pinned.trace + _keep.md + _secret.md (+ its sub/ dir) + settings survived the nuclear wipe",
        ]
    emit_report(f"test-purge: {mode}", errors, ok)
    return errors


def run_dryrun_test() -> list[str]:
    """Dedicated --dry-run test: preview only, every fixture survives. Runs under an
    ISOLATED HOME seeded with a footprint (so the preview never even reads the real
    ~/.claude/projects/, and we can assert dry-run doesn't delete the external store
    either). Cleanup (fixtures + temp HOME) is try/finally-guarded."""
    populate("all")
    errors = []
    tmp_home = Path(tempfile.mkdtemp(prefix="test-purge-home-"))
    fp = tmp_home / ".claude" / "projects" / _slug(TESTBENCH)
    fp.mkdir(parents=True)
    (fp / "transcript.jsonl").write_text('{"transcript": true}\n')
    env = {**os.environ, "HOME": str(tmp_home)}
    try:
        rc, out = run_purge("all", ["--dry-run"], env=env)
        if rc != 0:
            errors.append(f"dry-run purge exited with code {rc}")
        if "would remove" not in out:
            errors.append("dry-run: output missing 'would remove' preview text")

        # Nothing a real `all` would delete may actually be gone.
        for rel, _, _ in DUMMY_FILES:
            if not (TESTBENCH / rel).exists():
                errors.append(f"dry-run DELETED {rel} (preview must not delete)")
        for reldir, names in KEEP_RECENT_FIXTURES:
            for name in names:
                if not (TESTBENCH / reldir / name).exists():
                    errors.append(f"dry-run DELETED {reldir}/{name} (preview must not delete)")
        for rel in (UNDERSCORE_KEEP_REL, PINNED_TRACE_REL, NESTED_SECRET_REL,
                    NESTED_DEEP_SECRET_REL, SANDBOX_RIG_REL, SETTINGS_LOCAL_REL,
                    STRAGGLER_FILE, STRAGGLER_FILE2):
            if not (TESTBENCH / rel).exists():
                errors.append(f"dry-run DELETED {rel} (preview must not delete)")
        if not fp.exists():
            errors.append("dry-run DELETED the external transcript footprint (preview must not delete)")
    finally:
        cleanup()
        shutil.rmtree(tmp_home, ignore_errors=True)

    emit_report("test-purge: dryrun", errors,
                ["--dry-run emitted 'would remove' and deleted nothing (external store included)"])
    return errors


def run_symlink_test() -> list[str]:
    """Symlink protection — a dedicated test on a throwaway project root on the REAL
    filesystem (not the 9p TestBench mount). purge must NEVER follow or delete a
    symlink, and NEVER reach its target THROUGH the link — even under `purge all`,
    even when the link sits inside a high-value dir that `all` otherwise empties.
    Skips gracefully if the platform cannot create symlinks."""
    errors = []
    root = Path(tempfile.mkdtemp(prefix="test-purge-symlink-"))
    home = Path(tempfile.mkdtemp(prefix="test-purge-home-"))
    try:
        (root / ".state" / "work").mkdir(parents=True)
        (root / ".state" / "work" / "start.md").write_text("floor\n")
        (root / ".state" / "start.md").write_text("floor\n")
        # Targets that must be untouched (kept outside the purge allowlist).
        target_dir = root / "precious-target"
        target_dir.mkdir()
        (target_dir / "keep.txt").write_text("must NOT be deleted via the link\n")
        target_file = root / "precious-file.txt"
        target_file.write_text("must survive\n")
        # Symlinks INSIDE a high-value dir (.state/work/, emptied under `all`).
        link_dir = root / ".state" / "work" / "link-to-dir"
        link_file = root / ".state" / "work" / "link-to-file"
        try:
            os.symlink(target_dir, link_dir)
            os.symlink(target_file, link_file)
        except (OSError, NotImplementedError) as e:
            print(f"    SKIP symlink test: platform cannot create symlinks ({e})")
            emit_report("test-purge: symlink", [], ["SKIPPED (symlinks unsupported here)"])
            return errors

        env = {**os.environ, "HOME": str(home)}
        rc, _ = run_purge("all", env=env, project_root=root)
        if rc != 0:
            errors.append(f"symlink: purge all exited {rc}")
        if not link_dir.is_symlink():
            errors.append("symlink: link-to-dir WRONGLY removed under all (symlinks are protected)")
        if not link_file.is_symlink():
            errors.append("symlink: link-to-file WRONGLY removed under all (symlinks are protected)")
        if not (target_dir / "keep.txt").exists():
            errors.append("symlink: target-dir contents deleted THROUGH the link (must not follow)")
        if not target_file.exists():
            errors.append("symlink: target file deleted through the link")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)

    emit_report("test-purge: symlink", errors, [
        "symlinks inside a high-value dir survived purge all; their targets untouched",
    ])
    return errors


def _slug(path: Path) -> str:
    """INDEPENDENT slug oracle. Deliberately re-implements the expected rule rather than
    importing purge's own _project_slug — that import made the footprint round-trip
    TAUTOLOGICAL (fixture and lookup moved together, so any slug regression stayed
    green). With an independent copy, a regression in purge's slug makes the fixture sit
    at a different path than purge looks for → the round-trip fails. GOLDEN_SLUGS anchors
    both implementations to hand-computed truth in case they ever drift identically."""
    import re
    return re.sub(r"[^A-Za-z0-9]", "-", str(path.resolve()))


def run_footprint_test() -> list[str]:
    """External footprint (item 6) under an ISOLATED HOME — never the real one.

    bare/default KEEPS ~/.claude/projects/<slug>/; `all` REMOVES it. Fail-safe: a
    decoy dir sharing the leaf name ("...-TestBench") is NOT removed, proving the
    fuzzy leaf-name fallback is gone.
    """
    errors = []
    slug = _slug(TESTBENCH)

    # (0) Independent golden-slug oracle: catches a regression in purge._project_slug
    # that the fixture round-trip alone cannot (both would move together). GOLDEN_SLUGS
    # are hand-computed, not derived from purge.
    purge_slug = _purge_constant("_project_slug", None)
    if purge_slug is None:
        errors.append("slug: purge._project_slug is not importable")
    else:
        for p, expected in GOLDEN_SLUGS.items():
            got = purge_slug(Path(p))
            if got != expected:
                errors.append(f"slug: _project_slug({p}) = {got!r}, expected {expected!r}")

    # (a) main footprint: bare keeps, all removes.
    T = Path(tempfile.mkdtemp(prefix="test-purge-home-"))
    try:
        fp = T / ".claude" / "projects" / slug
        (fp / "session-subdir").mkdir(parents=True)
        (fp / "abc123.jsonl").write_text('{"transcript": true}\n')
        (fp / "session-subdir" / "inner.jsonl").write_text('{"inner": true}\n')
        env = {**os.environ, "HOME": str(T)}

        rc, _ = run_purge("default", env=env)
        if rc != 0:
            errors.append(f"footprint bare: purge exited {rc}")
        if not fp.is_dir():
            errors.append("footprint bare: external footprint WRONGLY removed (bare must keep it)")

        rc, _ = run_purge("all", env=env)
        if rc != 0:
            errors.append(f"footprint all: purge exited {rc}")
        if fp.exists():
            errors.append("footprint all: external footprint NOT removed (all must remove it)")
    finally:
        shutil.rmtree(T, ignore_errors=True)

    # (b) fail-safe: exact slug ABSENT, decoy sharing the leaf must survive.
    T2 = Path(tempfile.mkdtemp(prefix="test-purge-home-"))
    try:
        decoy = T2 / ".claude" / "projects" / "-x-y-TestBench"
        decoy.mkdir(parents=True)
        (decoy / "other.jsonl").write_text('{"decoy": true}\n')
        env = {**os.environ, "HOME": str(T2)}
        rc, out = run_purge("all", env=env)
        if rc != 0:
            errors.append(f"footprint decoy: purge exited {rc}")
        if not decoy.is_dir():
            errors.append(
                "footprint decoy: decoy sharing leaf name WRONGLY removed (no fuzzy fallback expected)")
        # Fail-loud: with the exact slug absent, `purge all` must WARN — not silently
        # skip (a silent skip is the exact regression that once hid the slug bug).
        if "WARNING" not in out or "no transcript store" not in out:
            errors.append("footprint decoy: no fail-loud WARNING emitted for the absent transcript store")
    finally:
        shutil.rmtree(T2, ignore_errors=True)

    # `purge all` on TESTBENCH removed .claude/skills — regenerate.
    regenerate_child()

    emit_report("test-purge: footprint", errors, [
        "isolated-HOME footprint: bare kept it, all removed it",
        "decoy sharing leaf name survived (fuzzy fallback gone); real HOME untouched",
    ])
    return errors


def run_child_test() -> list[str]:
    """Child-scope purge (item 7) on a nested qachild/, plus escape/nonexistent
    rejection. Parent TestBench fixtures must stay untouched."""
    errors = []
    child = TESTBENCH / "qachild"

    # Parent sentinel — a file a PARENT-scoped purge would delete. It must survive
    # a child-scoped purge, proving scope containment. Only create if absent.
    parent_prefs = TESTBENCH / ".state" / "prefs-resolved.json"
    created_parent_prefs = not parent_prefs.exists()
    if created_parent_prefs:
        parent_prefs.parent.mkdir(parents=True, exist_ok=True)
        parent_prefs.write_text('{"parent": "sentinel"}\n')

    child_traces = [f"2026-06-{i:02d}.trace" for i in range(1, KEEP_RECENT + 3)]  # N+2 = 7

    try:
        (child / ".claude" / "skills" / "x").mkdir(parents=True, exist_ok=True)
        (child / ".claude" / "skills" / "x" / "SKILL.md").write_text("# child skill\n")
        (child / ".claude" / "settings.local.json").write_text(json.dumps({"child": True}) + "\n")
        (child / ".state" / "memory").mkdir(parents=True, exist_ok=True)
        (child / ".state" / "memory" / "keep.md").write_text("# child memory — high-value, keep\n")
        (child / ".state" / "prefs-resolved.json").write_text('{"child": true}\n')
        (child / ".state" / "traces").mkdir(parents=True, exist_ok=True)
        for n in child_traces:
            (child / ".state" / "traces" / n).write_text(f"# {n}\n")

        # Escape rejection — ISOLATES the containment guard from the not-a-dir check.
        # Target an EXISTING directory outside the root (a temp dir), so ONLY the
        # is_relative_to escape guard can produce the nonzero exit; a missing-dir error
        # would not distinguish the two. Harmless even if the guard regressed: the temp
        # dir holds no framework dirs, so a stray bare purge there deletes nothing.
        outside = Path(tempfile.mkdtemp(prefix="test-purge-escape-"))
        try:
            rc, _ = run_purge(str(outside))
            if rc == 0:
                errors.append(f"child-escape: expected nonzero exit for outside dir '{outside}'")
            if not (child / ".state" / "prefs-resolved.json").exists():
                errors.append("child-escape: qachild fixtures deleted despite rejection")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

        # Nonexistent child → nonzero exit (the OTHER rejection path, kept separate).
        rc, _ = run_purge("qachild-does-not-exist-xyz")
        if rc == 0:
            errors.append("child-nonexistent: expected nonzero exit for missing child")

        # Real child-scoped purge.
        rc, _ = run_purge("qachild")
        if rc != 0:
            errors.append(f"child purge exited with code {rc}")

        # SAFE tier removed inside the child.
        if (child / ".claude" / "skills").exists():
            errors.append("child: .claude/skills not removed (SAFE tier)")
        if (child / ".state" / "prefs-resolved.json").exists():
            errors.append("child: .state/prefs-resolved.json not removed (SAFE tier)")
        # High-value kept under bare rules.
        if not (child / ".state" / "memory" / "keep.md").exists():
            errors.append("child: memory/keep.md WRONGLY removed (bare keeps high-value)")
        # Settings preserved.
        if not (child / ".claude" / "settings.local.json").exists():
            errors.append("child: settings.local.json WRONGLY removed")
        # Traces pruned to newest KEEP_RECENT.
        ordered = sorted(child_traces)
        for n in ordered[:-KEEP_RECENT]:
            if (child / ".state" / "traces" / n).exists():
                errors.append(f"child: trace {n} should be pruned (beyond newest {KEEP_RECENT})")
        for n in ordered[-KEEP_RECENT:]:
            if not (child / ".state" / "traces" / n).exists():
                errors.append(f"child: trace {n} WRONGLY pruned (within newest {KEEP_RECENT})")
        # Parent untouched.
        if not parent_prefs.exists():
            errors.append("child: PARENT prefs-resolved.json removed (child scope must not touch parent)")
    finally:
        shutil.rmtree(child, ignore_errors=True)
        if created_parent_prefs:
            try:
                parent_prefs.unlink()
            except OSError:
                pass

    emit_report("test-purge: child", errors, [
        "qachild SAFE removed; memory + settings kept; traces pruned to newest 5",
        "parent untouched; escape + nonexistent child rejected (nonzero exit)",
    ])
    return errors


# ── Main ───────────────────────────────────────────────────────────

MODES = ("populate", "standard", "all", "dryrun", "footprint", "child", "symlink", "full")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print(f"Usage: test-purge.py [{'|'.join(MODES)}]")
        sys.exit(1)

    mode = sys.argv[1]

    if not PURGE_SCRIPT.exists():
        print(f"  Error: purge script not found at {PURGE_SCRIPT}")
        sys.exit(1)

    if mode == "populate":
        populate("all")
        sys.exit(0)

    if mode == "standard":
        errors = run_scope_test("standard")
    elif mode == "all":
        errors = run_scope_test("all")
    elif mode == "dryrun":
        errors = run_dryrun_test()
    elif mode == "footprint":
        errors = run_footprint_test()
    elif mode == "child":
        errors = run_child_test()
    elif mode == "symlink":
        errors = run_symlink_test()
    else:  # full
        errors = []
        results = []
        for label, fn in (
            ("standard", lambda: run_scope_test("standard")),
            ("all", lambda: run_scope_test("all")),
            ("dryrun", run_dryrun_test),
            ("footprint", run_footprint_test),
            ("child", run_child_test),
            ("symlink", run_symlink_test),
        ):
            e = fn()
            results.append((label, len(e)))
            errors += e
        print("  +=============================================+")
        print("  |            test-purge: FULL SUITE            |")
        print("  +=============================================+")
        for label, n in results:
            status = "PASS" if n == 0 else f"FAIL ({n})"
            print(f"    {label:<12} {status}")
        print()

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
