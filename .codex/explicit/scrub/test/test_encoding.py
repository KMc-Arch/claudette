#!/usr/bin/env python3
"""Regression tests for scrub.py git-output decoding.

Guards two properties of git_run()/is_git_repo():

  1. UTF-8 PIN. git output is decoded as utf-8 regardless of the platform/locale
     default, so a valid-utf-8 diff never spuriously aborts. Without the pin, a
     Windows cp1252 default (or a forced-ASCII child locale, emulated here) raises
     UnicodeDecodeError on git's utf-8 bytes and the push is blocked with a
     misleading "could not scan". -> test_utf8_pin_survives_ascii_locale

  2. errors="replace", NOT strict. The value patterns are ASCII-only, so a
     non-ASCII byte can never be part of a matched secret and replacing an
     undecodable byte with U+FFFD cannot hide one. Strict decoding would only
     over-block: one stray non-utf-8 byte (an Excel/CSV smart-quote, a latin-1
     config) with no secret present would abort the whole scan and block the push.
     Replace preserves detection of the real (ASCII) credentials that actually
     matter, even when the same diff also carries undecodable bytes.
       -> test_non_utf8_no_secret_does_not_overblock  (RED under strict: rc 2)
       -> test_ascii_secret_survives_non_utf8_bytes

This posture was set by mileqa 20260906 round 2, reversing the round-1 strict
decode: strict traded an illusory fail-open (no ASCII secret ever evaded replace)
for a real gate-eroding over-block. See git_run()'s rationale comment.

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


def test_non_utf8_no_secret_does_not_overblock():
    """A benign diff carrying a non-utf-8 byte and NO secret must PASS (exit 0),
    not block the push. RED under a strict decode (rc would be 2: the byte aborts
    the whole scan). This is the over-block round 2 rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        # 0x92 is the cp1252 right-single-quote (a smart apostrophe): a lone
        # continuation byte, invalid utf-8. Common in Excel/CSV/Word exports.
        (repo / "notes.txt").write_bytes(b"comment = draft\x92s ready to ship\n")
        proc = scan_diff(repo)
    assert proc.returncode == 0, (
        f"expected clean PASS (0), got {proc.returncode} -- strict over-block regression\n"
        f"{proc.stdout}{proc.stderr}"
    )


def test_ascii_secret_survives_non_utf8_bytes():
    """A real (ASCII) secret is still caught (exit 1) when the same diff also carries
    an undecodable byte -- replace mangles only the bad byte to U+FFFD and leaves the
    ASCII credential intact. This is why dropping strict loses no detection."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(Path(tmp))
        (repo / "config.ini").write_bytes(
            b"comment = draft\x92s ready to ship\n"
            b'password = "Pa55word7xy"\n'  # scrub:allow -- synthetic fixture
        )
        proc = scan_diff(repo)
    assert proc.returncode == 1, (
        f"expected match/FAIL (1), got {proc.returncode} -- replace dropped a real secret\n"
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
             test_non_utf8_no_secret_does_not_overblock,
             test_ascii_secret_survives_non_utf8_bytes,
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
