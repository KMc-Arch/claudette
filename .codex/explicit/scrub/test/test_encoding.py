#!/usr/bin/env python3
"""Regression tests for scrub.py git-output decoding.

Guards two properties of git_run()/is_git_repo(), each proven red->green against
the two-line change that introduced them:

  1. UTF-8 PIN. git output is decoded as utf-8 regardless of the platform/locale
     default, so a valid-utf-8 diff never spuriously aborts. Without the pin, a
     Windows cp1252 default (or a forced-ASCII child locale, emulated here) raises
     UnicodeDecodeError on git's utf-8 bytes and the push is blocked with a
     misleading "could not scan". -> test_utf8_pin_survives_ascii_locale

  2. FAIL-CLOSED on undecodable input. When git output is genuinely NOT utf-8, the
     gate must fail closed (exit 2 = block), never scan a lossy decode and possibly
     certify a secret-bearing non-utf-8 diff clean. An errors="replace" decode turns
     the accented bytes of a password into U+FFFD, breaks the value char-class, and
     returns PASS -- a fail-open hole. -> test_non_utf8_secret_fails_closed

Run directly (`python3 test_encoding.py`) or under pytest. Non-zero exit on failure.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRUB = Path(__file__).resolve().parent.parent / "scrub.py"


def make_repo(work: Path) -> Path:
    repo = work / "repo"
    repo.mkdir()
    for arg in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo)] + arg, check=True)
    return repo


def scan_diff(repo: Path, env=None) -> subprocess.CompletedProcess:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return subprocess.run(
        [sys.executable, str(SCRUB), "diff", "--project-root", str(repo)],
        capture_output=True, text=True, env=env,
    )


def ascii_locale_env() -> dict:
    """Force the child's default text decode to ASCII, so the utf-8 pin is what
    keeps the scan alive. LC_ALL=C alone is coerced back to utf-8 by PEP 538;
    PYTHONUTF8=0 disables that coercion (mirrors a Windows cp1252 default)."""
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["PYTHONUTF8"] = "0"
    env.pop("PYTHONIOENCODING", None)
    return env


def test_utf8_pin_survives_ascii_locale():
    """Benign non-ASCII utf-8 diff under a forced-ASCII locale scans, not aborts.
    RED without the encoding="utf-8" pin (rc would be 2 + UnicodeDecodeError)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        (repo / "notes.md").write_text("contact = café résumé señor\n", encoding="utf-8")
        proc = scan_diff(repo, env=ascii_locale_env())
    assert proc.returncode in (0, 1), (
        f"expected scan to complete (0/1), got {proc.returncode}\n{proc.stdout}{proc.stderr}"
    )
    assert "UnicodeDecodeError" not in (proc.stdout + proc.stderr), "decode aborted the scan"


def test_non_utf8_secret_fails_closed():
    """A secret in a genuinely non-utf-8 file must BLOCK (exit 2), not PASS.
    RED under errors="replace" (rc would be 0: the U+FFFD-mangled value evades)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        # latin-1 bytes: 0xE4=a-umlaut 0xF6=o-umlaut inside a password value
        (repo / "config.ini").write_bytes(b'password = "P\xe455w\xf6rd7"\n')  # scrub:allow -- synthetic fixture
        proc = scan_diff(repo)
    assert proc.returncode == 2, (
        f"expected fail-closed block (2), got {proc.returncode} -- fail-open regression\n"
        f"{proc.stdout}{proc.stderr}"
    )


def test_ascii_secret_is_caught():
    """Control: an ASCII secret in a valid-utf-8 file is detected (exit 1)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        (repo / "config.ini").write_text('password = "Pa55word7xy"\n', encoding="utf-8")  # scrub:allow -- synthetic fixture
        proc = scan_diff(repo)
    assert proc.returncode == 1, (
        f"expected match/FAIL (1), got {proc.returncode}\n{proc.stdout}{proc.stderr}"
    )


def _main() -> int:
    tests = [test_utf8_pin_survives_ascii_locale,
             test_non_utf8_secret_fails_closed,
             test_ascii_secret_is_caught]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
