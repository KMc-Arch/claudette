#!/usr/bin/env python3
"""Tests for govgen.py. Stdlib only; fixtures in OS temp dirs (never in-tree —
a root: true fixture inside the codex would pollute the cboot root inventory)."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOVGEN = HERE.parent / "govgen.py"
sys.path.insert(0, str(HERE.parent))
import govgen  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond else f" — {detail}"))
    if not cond:
        FAILS.append(name)


def run(*args):
    return subprocess.run([sys.executable, str(GOVGEN), *args],
                          capture_output=True, text=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        rooted = Path(tmp) / "childproj"
        rooted.mkdir()
        (rooted / "CLAUDE.md").write_text("---\nroot: true\n---\n# Child\n", encoding="utf-8")
        unrooted = Path(tmp) / "plainfolder"
        unrooted.mkdir()

        # -- rooted dispatch --
        r = run("subagent", "--root", str(rooted))
        check("rooted: exit 0", r.returncode == 0, r.stderr)
        check("rooted: no warning", r.stderr.strip() == "", r.stderr)
        check("rooted: sentinel frame",
              r.stdout.startswith("=== GOV-PREAMBLE v") and "=== END GOV-PREAMBLE v" in r.stdout)
        check("rooted: resolved root", rooted.as_posix() in r.stdout)
        check("rooted: resolved state dir", (rooted / ".state").as_posix() in r.stdout)
        check("rooted: no unresolved placeholders", "{" not in r.stdout, r.stdout)

        # -- determinism --
        r2 = run("subagent", "--root", str(rooted))
        check("determinism: identical bytes", r.stdout == r2.stdout)

        # -- budget --
        size = len(r.stdout.encode("utf-8"))
        budget = govgen.PROFILES["subagent"]["budget"]
        check("budget: within ceiling", size <= budget, f"{size} B > {budget} B")

        # -- unrooted: warn, still emit --
        r = run("subagent", "--root", str(unrooted))
        check("unrooted: exit 0", r.returncode == 0, r.stderr)
        check("unrooted: warns about root: true", "root: true" in r.stderr, r.stderr)
        check("unrooted: still emits", r.stdout.startswith("=== GOV-PREAMBLE"))

        # -- missing root --
        r = run("subagent", "--root", str(Path(tmp) / "nope"))
        check("missing root: exit 2", r.returncode == 2, str(r.returncode))

        # -- unknown profile --
        r = run("interactive", "--root", str(rooted))
        check("unknown profile: nonzero exit", r.returncode != 0)

        # -- contract block via a temp codex --
        codex = Path(tmp) / "codex"
        mod = codex / "explicit" / "demo"
        mod.mkdir(parents=True)
        (mod / "start.md").write_text(
            '---\nversion: 1\nreads:\n  - "./spec.md"\n  - "^/.state/tests/"\nwrites:\n'
            '  - "^/.state/tests/demo/"\n---\n# demo\n', encoding="utf-8")
        block = govgen.contract_block(codex, "demo", rooted)
        check("contract: module-relative resolved", (mod / "spec.md").as_posix() in block)
        check("contract: root-relative resolved", (rooted / ".state/tests/demo").as_posix() in block)
        try:
            govgen.contract_block(codex, "ghost", rooted)
            check("contract: missing module raises", False)
        except SystemExit:
            check("contract: missing module raises", True)

        # -- frontmatter list parsing --
        fm = govgen.parse_frontmatter('---\na: 1\nlist:\n  - "x"\n  - y\nb: true\n---\nbody')
        check("frontmatter: flat + list + bool",
              fm.get("a") == "1" and fm.get("list") == ["x", "y"] and fm.get("b") is True, repr(fm))

    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failing" if FAILS
          else "\nPASS: all checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
