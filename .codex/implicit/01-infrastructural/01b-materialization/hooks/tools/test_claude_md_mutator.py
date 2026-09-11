#!/usr/bin/env python3
"""Acceptance suite for claude-md-mutator.py.

Every case runs the mutator as a subprocess (real CLI + exit code) against a
temp CLAUDE.md. Refusals must exit 2 AND leave the file byte-for-byte unchanged.
Run: python3 test_claude_md_mutator.py
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MUT = os.path.join(HERE, "claude-md-mutator.py")

FM = "---\nroot: true\nname: Old Name\ndescription: keep me\n---\n\n# Body\n\nkeep this too.\n"


def run(path, *sets):
    args = [sys.executable, MUT, path]
    for s in sets:
        args += ["--set", s]
    p = subprocess.run(args, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "CLAUDE.md")

    def write(self, content, name="CLAUDE.md"):
        path = os.path.join(self.d, name)
        if isinstance(content, bytes):
            with open(path, "wb") as f:
                f.write(content)
        else:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        return path

    def read_bytes(self, path):
        with open(path, "rb") as f:
            return f.read()

    def assert_unchanged(self, path, before):
        self.assertEqual(self.read_bytes(path), before, "file must be untouched on refusal")


class Happy(Base):
    def test_replace_name(self):
        p = self.write(FM)
        rc, _, err = run(p, "name=New Name")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: New Name\n", rd(p))
        self.assertNotIn("Old Name", rd(p))

    def test_append_orchestrator_when_absent(self):
        p = self.write(FM)
        rc, _, err = run(p, "orchestrator=true")
        self.assertEqual(rc, 0, err)
        t = rd(p)
        # inserted as the last frontmatter entry, before the closing fence
        self.assertIn("description: keep me\norchestrator: true\n---\n", t)

    def test_flip_orchestrator(self):
        p = self.write("---\nname: X\norchestrator: true\n---\nbody\n")
        rc, _, err = run(p, "orchestrator=false")
        self.assertEqual(rc, 0, err)
        self.assertIn("orchestrator: false\n", rd(p))

    def test_set_both_at_once(self):
        p = self.write(FM)
        rc, _, err = run(p, "name=Two", "orchestrator=false")
        self.assertEqual(rc, 0, err)
        t = rd(p)
        self.assertIn("name: Two\n", t)
        self.assertIn("orchestrator: false\n", t)

    def test_idempotent_noop(self):
        p = self.write(FM)
        before = self.read_bytes(p)
        rc, _, err = run(p, "name=Old Name")
        self.assertEqual(rc, 0, err)
        self.assert_unchanged(p, before)  # setting the same value writes nothing

    def test_body_and_other_keys_preserved(self):
        p = self.write(FM)
        rc, _, err = run(p, "name=New Name")
        self.assertEqual(rc, 0, err)
        t = rd(p)
        self.assertIn("root: true\n", t)
        self.assertIn("description: keep me\n", t)
        self.assertTrue(t.endswith("# Body\n\nkeep this too.\n"))

    def test_name_with_punctuation(self):
        p = self.write(FM)
        rc, _, err = run(p, "name=Acme (Group) v2 — ok")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: Acme (Group) v2 — ok\n", rd(p))


class Refuse(Base):
    def _refuse(self, path, *sets):
        before = self.read_bytes(path) if os.path.exists(path) else None
        rc, _, err = run(path, *sets)
        self.assertEqual(rc, 2, "expected refusal; stderr=%r" % err)
        self.assertTrue(err.strip().startswith("REFUSED"), err)
        if before is not None:
            self.assert_unchanged(path, before)

    def test_basename_not_claude_md(self):
        p = self.write(FM, name="notes.md")
        self._refuse(p, "name=X")

    def test_missing_file(self):
        self._refuse(os.path.join(self.d, "CLAUDE.md"), "name=X")

    def test_no_frontmatter(self):
        self._refuse(self.write("# just a heading\n"), "name=X")

    def test_unterminated_frontmatter(self):
        self._refuse(self.write("---\nname: X\nbody with no close\n"), "name=Y")

    def test_unknown_key(self):
        self._refuse(self.write(FM), "root=false")

    def test_bad_orchestrator_value(self):
        self._refuse(self.write(FM), "orchestrator=yes")

    def test_orchestrator_case(self):
        self._refuse(self.write(FM), "orchestrator=True")

    def test_name_too_long(self):
        self._refuse(self.write(FM), "name=" + "x" * 201)

    def test_name_empty(self):
        self._refuse(self.write(FM), "name=")

    def test_name_bad_leading_char(self):
        self._refuse(self.write(FM), "name=[bracketed")

    def test_value_with_newline(self):
        self._refuse(self.write(FM), "name=line1\nline2")

    def test_indented_key_variant(self):
        self._refuse(self.write("---\nroot: true\n  name: nested\n---\nb\n"), "name=X")

    def test_quoted_key_variant(self):
        self._refuse(self.write('---\n"name": q\n---\nb\n'), "name=X")

    def test_duplicate_key_in_frontmatter(self):
        self._refuse(self.write("---\nname: A\nname: B\n---\nb\n"), "name=C")

    def test_set_without_equals(self):
        self._refuse(self.write(FM), "name")

    def test_no_set_at_all(self):
        self._refuse(self.write(FM))

    def test_duplicate_set_same_key(self):
        self._refuse(self.write(FM), "name=A", "name=B")

    def test_non_utf8(self):
        self._refuse(self.write(b"---\nname: X\n---\n\n\xff\xfe body\n"), "name=Y")

    def test_frontmatter_over_cap(self):
        big = "---\n" + ("padkey: v\n" * 8000) + "---\nbody\n"  # ~72 KiB block
        self._refuse(self.write(big), "name=Y")

    def test_crlf_refused(self):
        # LF is the repo's line ending; a CRLF file is refused fail-closed.
        self._refuse(self.write(b"---\r\nname: X\r\n---\r\nbody\r\n"), "name=Y")


if __name__ == "__main__":
    unittest.main(verbosity=2)
