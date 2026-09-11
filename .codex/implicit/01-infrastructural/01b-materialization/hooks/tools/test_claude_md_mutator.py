#!/usr/bin/env python3
"""Acceptance suite for claude-md-mutator.py.

Every case runs the mutator as a subprocess (real CLI + exit code) against a
temp CLAUDE.md. Refusals must exit 2 AND leave the file byte-for-byte unchanged.
Run: python3 test_claude_md_mutator.py
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MUT = os.path.join(HERE, "claude-md-mutator.py")

# Import the module (hyphenated filename) for direct unit tests of pure helpers.
_spec = importlib.util.spec_from_file_location("clmd_mut", MUT)
clmd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clmd)

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

    def no_temp_litter(self):
        leftovers = [f for f in os.listdir(self.d) if f.startswith(".claude-md-mutator.")]
        self.assertEqual(leftovers, [], "atomic write must leave no temp litter")


class Happy(Base):
    def test_replace_name(self):
        p = self.write(FM)
        rc, _, err = run(p, "name=New Name")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: New Name\n", rd(p))
        self.assertNotIn("Old Name", rd(p))
        self.no_temp_litter()

    def test_replace_name_full_byte_equality(self):
        # Only the name line changes; every other byte is identical.
        p = self.write(FM)
        rc, _, err = run(p, "name=New Name")
        self.assertEqual(rc, 0, err)
        self.assertEqual(rd(p), FM.replace("name: Old Name", "name: New Name"))

    def test_append_orchestrator_when_absent(self):
        p = self.write(FM)
        rc, _, err = run(p, "orchestrator=true")
        self.assertEqual(rc, 0, err)
        self.assertIn("description: keep me\norchestrator: true\n---\n", rd(p))

    def test_insert_name_when_absent(self):
        p = self.write("---\nroot: true\n---\nbody\n")
        rc, _, err = run(p, "name=Fresh")
        self.assertEqual(rc, 0, err)
        self.assertEqual(rd(p), "---\nroot: true\nname: Fresh\n---\nbody\n")

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
        self.no_temp_litter()

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

    def test_name_with_colon_accepted(self):
        # Tolerant readers first-colon-split, so a colon in a name round-trips.
        p = self.write(FM)
        rc, _, err = run(p, "name=Phase 2: Rollout")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: Phase 2: Rollout\n", rd(p))

    def test_name_with_hash_accepted(self):
        p = self.write(FM)
        rc, _, err = run(p, "name=Team #1")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: Team #1\n", rd(p))

    def test_name_bracket_lead_accepted(self):
        # No leading-char policy: the readers take it verbatim.
        p = self.write(FM)
        rc, _, err = run(p, "name=[squad]")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: [squad]\n", rd(p))

    def test_value_with_equals(self):
        p = self.write(FM)
        rc, _, err = run(p, "name=a=b=c")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: a=b=c\n", rd(p))

    def test_name_len_boundaries_accepted(self):
        for n in (1, 200):
            p = self.write(FM)
            rc, _, err = run(p, "name=" + "x" * n)
            self.assertEqual(rc, 0, "len %d should be accepted; %s" % (n, err))
            self.assertIn("name: " + "x" * n + "\n", rd(p))

    def test_no_space_after_colon_is_replaced_not_duplicated(self):
        p = self.write("---\nroot: true\nname:Old\n---\nbody\n")
        rc, _, err = run(p, "name=New")
        self.assertEqual(rc, 0, err)
        t = rd(p)
        self.assertEqual(t.count("name"), 1, "must replace, not append a second name")
        self.assertIn("name: New\n", t)

    def test_lenient_close_fence_edits_real_frontmatter_not_body(self):
        # Close fence carries trailing space; a later body '---' must NOT become
        # the close. name is inserted into the real frontmatter, body untouched.
        p = self.write("---\ntitle: X\n--- \nname: BODY prose\n---\ntail\n")
        rc, _, err = run(p, "name=NEW")
        self.assertEqual(rc, 0, err)
        t = rd(p)
        self.assertIn("title: X\nname: NEW\n--- \n", t)      # inserted in frontmatter
        self.assertIn("name: BODY prose\n", t)               # body line untouched

    def test_body_horizontal_rule_after_clean_close_ignored(self):
        p = self.write("---\nname: Old\n---\n\nintro\n\n---\n\nmore\n")
        rc, _, err = run(p, "name=New")
        self.assertEqual(rc, 0, err)
        self.assertEqual(rd(p), "---\nname: New\n---\n\nintro\n\n---\n\nmore\n")


class Refuse(Base):
    def _refuse(self, path, *sets):
        before = self.read_bytes(path) if os.path.exists(path) else None
        rc, _, err = run(path, *sets)
        self.assertEqual(rc, 2, "expected refusal; stderr=%r" % err)
        self.assertTrue(err.strip().startswith("REFUSED"), err)
        if before is not None:
            self.assert_unchanged(path, before)

    def test_basename_not_claude_md(self):
        self._refuse(self.write(FM, name="notes.md"), "name=X")

    def test_missing_file(self):
        self._refuse(os.path.join(self.d, "CLAUDE.md"), "name=X")

    def test_no_frontmatter(self):
        self._refuse(self.write("# just a heading\n"), "name=X")

    def test_unterminated_frontmatter(self):
        self._refuse(self.write("---\nname: X\nbody with no close\n"), "name=Y")

    def test_unknown_key(self):
        self._refuse(self.write(FM), "root=false")

    def test_bad_orchestrator_value(self):
        for bad in ("yes", "True", "1", "on", ""):
            self._refuse(self.write(FM), "orchestrator=" + bad)

    def test_name_too_long(self):
        self._refuse(self.write(FM), "name=" + "x" * 201)

    def test_name_empty(self):
        self._refuse(self.write(FM), "name=")

    def test_name_all_whitespace(self):
        self._refuse(self.write(FM), "name=   ")

    def test_name_leading_trailing_whitespace(self):
        self._refuse(self.write(FM), "name= Padded ")

    def test_value_with_newline(self):
        self._refuse(self.write(FM), "name=line1\nline2")

    def test_value_with_tab(self):
        self._refuse(self.write(FM), "name=a\tb")

    def test_value_with_control_char(self):
        # NUL can't be tested via argv (execve rejects it before the child runs),
        # so it can't reach the tool that way; the code's NUL check is defensive.
        self._refuse(self.write(FM), "name=a\x1bb")
        self._refuse(self.write(FM), "name=a\x7fb")

    def test_value_bare_cr(self):
        self._refuse(self.write(FM), "name=a\rb")

    def test_value_non_utf8(self):
        # Surrogate from argv that cannot encode to UTF-8 -> clean exit 2, not a crash.
        self._refuse(self.write(FM), "name=A\udcffB")

    def test_indented_key_variant(self):
        self._refuse(self.write("---\nroot: true\n  name: nested\n---\nb\n"), "name=X")

    def test_quoted_key_variant(self):
        self._refuse(self.write('---\n"name": q\n---\nb\n'), "name=X")

    def test_space_before_colon_variant(self):
        self._refuse(self.write("---\nname : spaced\n---\nb\n"), "name=X")

    def test_duplicate_key_in_frontmatter(self):
        self._refuse(self.write("---\nname: A\nname: B\n---\nb\n"), "name=C")

    def test_block_scalar_name_refused(self):
        self._refuse(self.write("---\nname: >\n  multi\n  line\n---\nb\n"), "name=X")

    def test_multiline_indented_value_refused(self):
        self._refuse(self.write("---\nname: Old\n  cont\n---\nb\n"), "name=X")

    def test_set_without_equals(self):
        self._refuse(self.write(FM), "name")

    def test_no_set_at_all(self):
        self._refuse(self.write(FM))

    def test_duplicate_set_same_key(self):
        self._refuse(self.write(FM), "name=A", "name=B")

    def test_non_utf8_file(self):
        self._refuse(self.write(b"---\nname: X\n---\n\n\xff\xfe body\n"), "name=Y")

    def test_frontmatter_over_byte_cap(self):
        # Under 64K *chars* but over 64K *bytes* (3-byte fillers) -> refused.
        big = "---\npad: " + ("中" * 22000) + "\n---\nbody\n"
        self._refuse(self.write(big), "name=Y")

    def test_crlf_refused(self):
        self._refuse(self.write(b"---\r\nname: X\r\n---\r\nbody\r\n"), "name=Y")

    def test_unwritable_dir_clean_refusal(self):
        # Dir 0555: mkstemp fails -> clean exit 2 REFUSED, not an exit-1 traceback.
        if os.geteuid() == 0:
            self.skipTest("root bypasses directory write permission")
        p = self.write(FM)
        os.chmod(self.d, 0o555)
        try:
            self._refuse(p, "name=New")
        finally:
            os.chmod(self.d, 0o755)


class Unit(unittest.TestCase):
    def test_canonical_target_resolves_real_case(self):
        d = tempfile.mkdtemp()
        real = os.path.join(d, "CLAUDE.md")
        with open(real, "w") as f:
            f.write("x")
        # Exact spelling -> returned as given.
        self.assertEqual(clmd.canonical_target(real), real)
        # Different case, same dirent -> resolves to the real on-disk spelling
        # (on a case-sensitive FS the entry is "CLAUDE.md", matched via .lower()).
        self.assertEqual(clmd.canonical_target(os.path.join(d, "claude.md")), real)


if __name__ == "__main__":
    unittest.main(verbosity=2)
