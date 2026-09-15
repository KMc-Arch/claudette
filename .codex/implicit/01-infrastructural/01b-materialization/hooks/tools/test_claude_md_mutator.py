#!/usr/bin/env python3
"""Acceptance suite for claude-md-mutator.py.

CLI cases run the mutator as a subprocess (real argv + exit code) against a temp
CLAUDE.md; refusals must exit 2 AND leave the file byte-for-byte unchanged.
launder()/process_value() are also unit-tested directly. Run: python3 test_claude_md_mutator.py
"""

import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MUT = os.path.join(HERE, "claude-md-mutator.py")

_spec = importlib.util.spec_from_file_location("clmd", MUT)
clmd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clmd)

FM = "---\nroot: true\nname: Old Name\ndescription: keep this description\n---\n\n# Body\n\nkeep too.\n"


def run(path, *sets):
    args = [sys.executable, MUT, path]
    for s in sets:
        args += ["--set", s]
    p = subprocess.run(args, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _fs_enforces_perms(d):
    p = os.path.join(d, ".permcheck")
    try:
        with open(p, "w") as f:
            f.write("x")
        os.chmod(p, 0o000)
        return not os.access(p, os.R_OK)
    except OSError:
        return False
    finally:
        try:
            os.chmod(p, 0o600)
            os.unlink(p)
        except OSError:
            pass


def _fs_case_sensitive(d):
    a = os.path.join(d, "_CaseProbe")
    try:
        with open(a, "w") as f:
            f.write("x")
        return not os.path.exists(os.path.join(d, "_caseprobe"))
    except OSError:
        return False
    finally:
        try:
            os.unlink(a)
        except OSError:
            pass


class Launder(unittest.TestCase):
    def test_ascii_and_colon(self):
        self.assertEqual(clmd.launder("Café: Phase 2"), "Cafe Phase 2")

    def test_break_becomes_dash(self):
        self.assertEqual(clmd.launder("A\rB"), "A - B")
        self.assertEqual(clmd.launder("A\tB"), "A - B")
        self.assertEqual(clmd.launder("A B"), "A - B")

    def test_bare_hyphen_preserved(self):
        self.assertEqual(clmd.launder("model-selector"), "model-selector")

    def test_non_latin_empties(self):
        self.assertEqual(clmd.launder("中文项目"), "")

    def test_quotes_and_structural_dropped(self):
        self.assertEqual(clmd.launder('a "quoted" [x]'), "a quoted x")

    def test_triple_dash_neutralized(self):
        self.assertEqual(clmd.launder("--- danger ---"), "danger")

    def test_collapse_and_trim(self):
        self.assertEqual(clmd.launder("  Padded   Name  "), "Padded Name")

    def test_process_orchestrator_casefold(self):
        self.assertEqual(clmd.process_value("orchestrator", "True"), "true")
        self.assertEqual(clmd.process_value("orchestrator", "FALSE"), "false")

    def test_process_name_min_and_max(self):
        self.assertEqual(clmd.process_value("name", "Hello"), "Hello")   # exactly 5
        self.assertEqual(len(clmd.process_value("name", "x" * 400)), 200)  # truncated
        with self.assertRaises(SystemExit):   # below 5 -> die
            clmd.process_value("name", "Hi")
        with self.assertRaises(SystemExit):   # non-latin -> empty -> die
            clmd.process_value("name", "中文")

    def test_process_description_min(self):
        self.assertEqual(clmd.process_value("description", "A decent description"),
                         "A decent description")
        with self.assertRaises(SystemExit):
            clmd.process_value("description", "short")   # 5 chars < 10

    def test_control_chars_neutralized(self):
        # non-whitespace controls (which isspace misses) must become " - ", not
        # survive — the WHOLE non-whitespace C0 range (incl. ESC 0x1b, the ANSI-
        # escape introducer, the one C0 char isspace does not also cover) plus
        # DEL/NEL/C1.
        controls = [chr(c) for c in range(0x00, 0x20) if not chr(c).isspace()]
        controls += ["\x7f", "\x85", "\x9f", "\x1b"]
        for ch in controls:
            self.assertEqual(clmd.launder("A" + ch + "B"), "A - B", repr(ch))

    def test_format_chars_not_silently_joined(self):
        for ch in ("​", "­", "⁠", "﻿"):   # Cf category
            self.assertEqual(clmd.launder("A" + ch + "B"), "A - B", repr(ch))

    def test_triple_dash_regenerated_after_drop(self):
        # dropping chars between hyphens must not leave a '---' a substring reader closes on
        v = clmd.launder("Team-'-'-Xray")
        self.assertNotIn("---", v)
        self.assertEqual(v, "Team - Xray")
        self.assertNotIn("---", clmd.launder("abc-:-:-def"))

    def test_surrogateescape_recovered(self):
        s = b"Caf\xc3\xa9 Team".decode("ascii", "surrogateescape")  # LANG=C-style argv
        self.assertEqual(clmd.launder(s), "Cafe Team")

    def test_backslash_dropped(self):
        self.assertEqual(clmd.launder("a\\b path"), "ab path")

    def test_each_structural_char_dropped(self):
        for c in "`|<>[]{}\"'\\:":
            self.assertEqual(clmd.launder("a" + c + "b"), "ab", repr(c))

    def test_yaml_indicator_chars_dropped(self):
        # & * ! # % @ are YAML-significant at a scalar start (or, for #, after a
        # space); dropping them keeps a laundered value from reading differently
        # to a strict-YAML consumer than to a line reader.
        for c in "&*!#%@":
            self.assertEqual(clmd.launder("a" + c + "b"), "ab", repr(c))

    def test_leading_yaml_indicator_dropped(self):
        for v, expected in [
            ("*anchor value here", "anchor value here"),
            ("# hidden name here", "hidden name here"),
            ("&anchor real name", "anchor real name"),
            ("@reserved name here", "reserved name here"),
            ("%YAML directive here", "YAML directive here"),
        ]:
            self.assertEqual(clmd.launder(v), expected, repr(v))

    def test_mid_value_hash_dropped(self):
        # a ` #` mid-value would start a YAML comment (truncating the scalar)
        self.assertEqual(clmd.launder("Realname Corp #hidden tail"), "Realname Corp hidden tail")

    def test_yaml_tag_neutralized(self):
        v = clmd.launder("!!python/object apply here")
        self.assertNotIn("!", v)
        self.assertTrue(v.startswith("python"))

    def test_leading_block_indicator_stripped(self):
        # "- "/"? "/", " at the start would make a strict YAML parser reject the
        # whole frontmatter (sequence / complex-key / flow); strip the prefix.
        for v, expected in [
            ("- A tool for diagrams", "A tool for diagrams"),
            ("? complex key here now", "complex key here now"),
            (", flow mark value here", "flow mark value here"),
            ("\t- synth bullet here now", "synth bullet here now"),  # synthesized "- "
        ]:
            self.assertEqual(clmd.launder(v), expected, repr(v))

    def test_solo_leading_hyphen_word_preserved(self):
        # "-word" (no following space) is a valid plain scalar — keep it; and keep
        # bare hyphens inside a word.
        self.assertEqual(clmd.launder("-solo tag here now"), "-solo tag here now")
        self.assertEqual(clmd.launder("model-selector"), "model-selector")

    def test_truncation_does_not_reexpose_leading_indicator(self):
        # a leading ?/, shielded behind hyphen(s) is a valid scalar pre-truncation;
        # once truncation's strip("-") removes the hyphens it must not surface the
        # indicator as the first char (which a strict YAML reader would choke on).
        for prefix in ("-? ", "-, ", "--? ", "--, "):
            v = clmd.process_value("name", prefix + "a" * 260)
            self.assertLessEqual(len(v), 200)
            self.assertNotIn(v[:1], "?,-:", "re-exposed %r from %r" % (v[:1], prefix))

    def test_orchestrator_whitespace_tolerated(self):
        self.assertEqual(clmd.process_value("orchestrator", "  true  "), "true")

    def test_name_min_boundary(self):
        self.assertEqual(clmd.process_value("name", "abcde"), "abcde")   # exactly 5
        with self.assertRaises(SystemExit):
            clmd.process_value("name", "abcd")                            # 4

    def test_name_max_boundary(self):
        # exactly hi (200) is kept; hi+1 truncates to hi. A value laundering to
        # exactly hi and ending in '-' must NOT be truncated (pins `> hi`, not
        # `>= hi`: `>=` would run truncation and strip the trailing hyphen to 199).
        self.assertEqual(len(clmd.process_value("name", "a" * 200)), 200)
        self.assertEqual(len(clmd.process_value("name", "a" * 201)), 200)
        self.assertEqual(clmd.process_value("name", "a" * 199 + "-"), "a" * 199 + "-")

    def test_description_max_boundary(self):
        self.assertEqual(len(clmd.process_value("description", "a" * 300)), 300)
        self.assertEqual(len(clmd.process_value("description", "a" * 301)), 300)

    def test_description_min_boundary(self):
        self.assertEqual(clmd.process_value("description", "x" * 10), "x" * 10)
        with self.assertRaises(SystemExit):
            clmd.process_value("description", "x" * 9)

    def test_truncation_leaves_no_trailing_junk(self):
        v = clmd.process_value("name", "x" * 198 + " - " + "y" * 20)
        self.assertLessEqual(len(v), 200)
        self.assertFalse(v.endswith((" ", "-")))


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

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

    def no_litter(self):
        self.assertEqual([f for f in os.listdir(self.d) if f.startswith(".claude-md-mutator.")], [])


class Happy(Base):
    def test_set_name_launders_and_reports(self):
        p = self.write(FM)
        rc, out, err = run(p, "name=Café: New Team")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: Cafe New Team\n", rd(p))
        self.assertIn("name: Cafe New Team", out)        # whole block on stdout
        self.assertIn("note: name", err)                 # note on stderr
        self.no_litter()

    def test_stdout_is_the_whole_block(self):
        p = self.write(FM)
        rc, out, err = run(p, "name=Renamed Group")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "---\nroot: true\nname: Renamed Group\ndescription: keep this description\n---\n")

    def test_set_orchestrator_casefold(self):
        p = self.write(FM)
        rc, out, err = run(p, "orchestrator=TRUE")
        self.assertEqual(rc, 0, err)
        self.assertIn("orchestrator: true\n", rd(p))

    def test_set_description(self):
        p = self.write(FM)
        rc, out, err = run(p, "description=A brand new description of things")
        self.assertEqual(rc, 0, err)
        self.assertIn("description: A brand new description of things\n", rd(p))

    def test_append_when_absent(self):
        p = self.write("---\nroot: true\n---\nbody\n")
        rc, out, err = run(p, "name=Fresh Name", "orchestrator=true")
        self.assertEqual(rc, 0, err)
        self.assertEqual(rd(p), "---\nroot: true\nname: Fresh Name\norchestrator: true\n---\nbody\n")

    def test_body_and_other_keys_preserved(self):
        p = self.write(FM)
        rc, out, err = run(p, "name=New Name Here")
        self.assertEqual(rc, 0, err)
        t = rd(p)
        self.assertIn("root: true\n", t)
        self.assertTrue(t.endswith("# Body\n\nkeep too.\n"))

    def test_single_line_flow_value_accepted(self):
        # a balanced single-line flow value is one flat line and passes untouched
        # (the unbalanced-bracket refusal must not catch it).
        p = self.write("---\nroot: true\ntags: [a, b, c]\nname: Old Name\ndescription: keep this description\n---\nbody\n")
        rc, out, err = run(p, "name=New Name Here")
        self.assertEqual(rc, 0, err)
        self.assertIn("tags: [a, b, c]", rd(p))

    def test_idempotent_noop_still_prints_block(self):
        p = self.write(FM)
        ino = os.stat(p).st_ino
        rc, out, err = run(p, "name=Old Name")   # launders to same value
        self.assertEqual(rc, 0, err)
        self.assertEqual(os.stat(p).st_ino, ino, "no-op must not rewrite")
        self.assertIn("name: Old Name", out)
        self.no_litter()

    def test_replace_preserves_mode(self):
        if not _fs_enforces_perms(self.d):
            self.skipTest("filesystem does not enforce POSIX permission bits")
        p = self.write(FM)
        os.chmod(p, 0o640)
        rc, out, err = run(p, "name=New Name Here")
        self.assertEqual(rc, 0, err)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640)

    def test_ascii_locale_block_no_crash(self):
        # a preserved non-ASCII line + an ASCII locale must not crash the block echo
        p = self.write("---\nroot: true\ndescription: Café bar review here\nname: Old Name\n---\nbody\n")
        env = dict(os.environ, LC_ALL="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
        r = subprocess.run([sys.executable, MUT, p, "--set", "name=Renamed Group"],
                           capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"Renamed Group", r.stdout)
        self.assertIn(b"description:", r.stdout)   # the non-ASCII line is echoed, not crashed

    def test_bom_prefixed_file_accepted(self):
        # a UTF-8 BOM (a Windows editor may add one) must not lock out the sole
        # editor: decode strips it, matching boot-inject / bootstrap-child.
        p = self.write("﻿---\nroot: true\nname: Old Name\ndescription: keep this description\n---\n\nbody\n")
        rc, out, err = run(p, "name=Renamed Group")
        self.assertEqual(rc, 0, err)
        self.assertIn("name: Renamed Group", out)
        self.assertIn("name: Renamed Group\n", rd(p))


class DeadFlatRefuse(Base):
    def _refuse(self, path, *sets):
        before = self.read_bytes(path) if os.path.exists(path) else None
        rc, out, err = run(path, *sets)
        self.assertEqual(rc, 2, "expected refusal; stderr=%r" % err)
        self.assertTrue(err.strip().startswith("REFUSED"), err)
        if before is not None:
            self.assert_unchanged(path, before)

    def test_indented_line(self):
        self._refuse(self.write("---\nname: X here\n  indented: y\n---\nb\n"), "name=New Name")

    def test_block_scalar(self):
        self._refuse(self.write("---\nname: |\n  body\n  more\n---\nb\n"), "name=New Name")

    def test_block_scalar_blank_led(self):
        # the round-3 injection shape
        self._refuse(self.write("---\nname: |\n\n  orchestrator: true\n---\nb\n"), "name=New Name")

    def test_flow_multiline(self):
        self._refuse(self.write("---\nname: [a,\nb]\n---\nb\n"), "name=New Name")

    def test_embedded_cr(self):
        # the round-4 silent-deletion shape: one split('\n') line, two splitlines
        self._refuse(self.write("---\nname: Child\rorchestrator: true\n---\nb\n"), "name=New Name")

    def test_quoted_key(self):
        self._refuse(self.write('---\n"name": q\n---\nb\n'), "name=New Name")

    def test_space_before_colon(self):
        self._refuse(self.write("---\nname : spaced\n---\nb\n"), "name=New Name")

    def test_comment_line(self):
        self._refuse(self.write("---\nname: X here\n# a comment\n---\nb\n"), "name=New Name")

    def test_duplicate_key(self):
        self._refuse(self.write("---\nname: A here\nname: B here\n---\nb\n"), "name=New Name")

    def test_duplicate_of_a_non_set_key(self):
        # a duplicate of a key we're NOT setting is still ambiguous -> refuse
        self._refuse(self.write("---\nroot: true\nroot: false\nname: X here\n---\nb\n"), "name=New Name")

    def test_trailing_line_boundary_refused(self):
        # a single TRAILING line-boundary char on an otherwise-flat entry line is
        # a break to a YAML reader; str.splitlines() drops it, so the old
        # len(splitlines())>1 check missed it. Must now refuse, file untouched.
        for ch in ("\r", "\x0b", "\x0c", "\x85", " ", " ", "\x1c", "\x1d", "\x1e"):
            self._refuse(self.write("---\nname: keepone" + ch + "\n---\nb\n"), "name=New Name")

    def test_hyphen_leading_key_refused(self):
        # a key beginning with '-' (e.g. an all-hyphen '---: x' line) is closed on
        # by a find('\n---') reader; refuse rather than edit around the ambiguity.
        self._refuse(self.write("---\nname: Keep Name\n---: x\ndescription: keep this desc here\n---\nb\n"),
                     "name=New Name")


class WriteRefuse(Base):
    def _refuse(self, path, *sets):
        before = self.read_bytes(path)
        rc, out, err = run(path, *sets)
        self.assertEqual(rc, 2, "expected refusal; stderr=%r" % err)
        self.assertTrue(err.strip().startswith("REFUSED"), err)
        self.assert_unchanged(path, before)

    def test_name_below_min(self):
        self._refuse(self.write(FM), "name=Hi")

    def test_name_non_latin(self):
        self._refuse(self.write(FM), "name=中文项目")

    def test_description_below_min(self):
        self._refuse(self.write(FM), "description=short")

    def test_orchestrator_not_bool(self):
        for bad in ("yes", "1", "maybe", ""):
            self._refuse(self.write(FM), "orchestrator=" + bad)

    def test_unknown_key(self):
        self._refuse(self.write(FM), "root=false")

    def test_set_without_equals(self):
        self._refuse(self.write(FM), "name")

    def test_no_set(self):
        self._refuse(self.write(FM))

    def test_duplicate_set_same_key(self):
        self._refuse(self.write(FM), "name=First Name", "name=Second Name")


class FileRefuse(Base):
    def _refuse(self, path, *sets):
        before = self.read_bytes(path) if os.path.exists(path) else None
        rc, out, err = run(path, *sets)
        self.assertEqual(rc, 2, "expected refusal; stderr=%r" % err)
        self.assertTrue(err.strip().startswith("REFUSED"), err)
        if before is not None:
            self.assert_unchanged(path, before)

    def test_basename_not_claude_md(self):
        self._refuse(self.write(FM, name="notes.md"), "name=New Name")

    def test_missing(self):
        self._refuse(os.path.join(self.d, "CLAUDE.md"), "name=New Name")

    def test_directory_target(self):
        d2 = os.path.join(self.d, "CLAUDE.md")
        os.mkdir(d2)
        rc, out, err = run(d2, "name=New Name")
        self.assertEqual(rc, 2, err)
        self.assertIn("not a regular file", err)

    def test_no_frontmatter(self):
        # all-flat body but NO opening --- fence: the missing fence must be the
        # SOLE reason for refusal (fixture has no incidental non-flat line), so
        # this actually pins the opening-fence guard.
        self._refuse(self.write("name: real name\ndescription: a real value here\n---\nbody\n"), "name=New Name")

    def test_unterminated(self):
        # all-flat frontmatter with NO closing fence: the missing close must be
        # the sole reason for refusal, pinning the never-closed guard.
        self._refuse(self.write("---\nname: Real Name\ndescription: some description here\n"), "name=New Name")

    def test_fence_four_dashes_not_a_fence(self):
        # a "----" line is not a fence (fence is exactly three dashes) — it is read
        # as a body/key line and refused, pinning _FENCE to `^---[ \t]*$`.
        self._refuse(self.write("---\nname: Keep Name\n----\ndescription: v here now\n---\nb\n"), "name=New Name")

    def test_non_utf8_file(self):
        self._refuse(self.write(b"---\nname: X\n---\n\n\xff\xfe\n"), "name=New Name")

    def test_over_byte_cap(self):
        # dead-flat 'pad:' line; consumed hits exactly 65536 at the close fence.
        at = "---\npad: " + ("x" * 65522) + "\n---\nbody\n"
        rc, out, err = run(self.write(at), "name=New Name")
        self.assertEqual(rc, 0, err)          # exactly 65536 accepted
        over = "---\npad: " + ("x" * 65523) + "\n---\nbody\n"
        self._refuse(self.write(over), "name=New Name")

    def test_crlf(self):
        self._refuse(self.write(b"---\r\nname: X\r\n---\r\nbody\r\n"), "name=New Name")

    def test_over_file_size_cap(self):
        # a file larger than the whole-file cap is refused BEFORE it is read into
        # memory, even when its frontmatter is small and flat.
        big = "---\nname: Keep Name\n---\n" + ("x" * (1024 * 1024 + 16))
        self._refuse(self.write(big), "name=New Name")

    def test_file_size_cap_exact_boundary(self):
        # a file of EXACTLY the cap is accepted; one byte over is refused (proves
        # the boundary is `>`, not `>=`).
        base = "---\nname: Keep Name\n---\n"
        at = base + ("x" * (1024 * 1024 - len(base.encode("utf-8"))))
        self.assertEqual(len(at.encode("utf-8")), 1024 * 1024)
        rc, out, err = run(self.write(at), "name=New Name Here")
        self.assertEqual(rc, 0, err)                       # exactly at cap: accepted
        self._refuse(self.write(at + "y"), "name=New Name Here")  # one over: refused

    def test_unwritable_dir(self):
        if not _fs_enforces_perms(self.d):
            self.skipTest("filesystem does not enforce POSIX permission bits")
        p = self.write(FM)
        os.chmod(self.d, 0o555)
        try:
            self._refuse(p, "name=New Name")
        finally:
            os.chmod(self.d, 0o755)

    def test_unreadable_file(self):
        if not _fs_enforces_perms(self.d):
            self.skipTest("filesystem does not enforce POSIX permission bits")
        p = self.write(FM)
        os.chmod(p, 0o000)
        try:
            rc, out, err = run(p, "name=New Name")
            self.assertEqual(rc, 2, err)
            self.assertTrue(err.strip().startswith("REFUSED"), err)
        finally:
            os.chmod(p, 0o644)

    def test_missing_path_arg(self):
        p = subprocess.run([sys.executable, MUT], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)   # argparse usage error

    def test_symlink_target_refused(self):
        # A real symlink can't be created under the project's ABSOLUTE HOLD on
        # symlink creation, so prove the guard by making os.path.islink report the
        # target as a link: main() must refuse (exit 2) and leave the file
        # byte-for-byte unchanged. This replaces the former asserting-nothing skip.
        import unittest.mock as mock
        p = self.write(FM)
        before = self.read_bytes(p)
        with mock.patch.object(clmd.os.path, "islink", return_value=True):
            with self.assertRaises(SystemExit) as cm:
                clmd.main([p, "--set", "name=New Name"])
        self.assertEqual(cm.exception.code, 2)
        self.assert_unchanged(p, before)


class Unit(unittest.TestCase):
    def test_canonical_target_real_case(self):
        d = tempfile.mkdtemp()
        real = os.path.join(d, "CLAUDE.md")
        with open(real, "w") as f:
            f.write("x")
        self.assertEqual(clmd.canonical_target(real), real)
        self.assertEqual(clmd.canonical_target(os.path.join(d, "claude.md")), real)

    def test_canonical_target_skips_directory(self):
        d = tempfile.mkdtemp()
        if not _fs_case_sensitive(d):
            self.skipTest("filesystem is case-insensitive; dir+file case-variants can't coexist")
        os.mkdir(os.path.join(d, "CLAUDE.MD"))
        real = os.path.join(d, "claude.md")
        with open(real, "w") as f:
            f.write("x")
        self.assertEqual(clmd.canonical_target(os.path.join(d, "Claude.md")), real)


if __name__ == "__main__":
    unittest.main(verbosity=2)
