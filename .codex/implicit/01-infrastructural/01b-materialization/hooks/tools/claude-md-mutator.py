#!/usr/bin/env python3
"""The approved mutator for CLAUDE.md frontmatter.

This is the SOLE authorized writer of allowlisted frontmatter keys in an
existing CLAUDE.md (per the "updating any CLAUDE.md" ABSOLUTE HOLD in the apex
CLAUDE.md). The claude-md guard hook deliberately denies every Write/Edit to a
CLAUDE.md-shaped path; the precision the hook does not carry lives HERE instead:
a fixed key allowlist, per-key value validation, and an atomic write. The hook
never sees this script — it edits by direct file IO, not a Write/Edit tool call.

Scope, on purpose:
  * EDIT ONLY. The target must already exist and already carry a leading
    frontmatter block. Creating a CLAUDE.md is /new-project's job, not this.
  * Allowlisted keys ONLY: name, orchestrator. Nothing else — not the body,
    not any other frontmatter key.
  * Not a security boundary. Path containment / gravity are other guards' job;
    this refuses only what it cannot mutate cleanly. It does insist the target
    basename is CLAUDE.md so it cannot be repurposed as a general file writer.

Usage:
    claude-md-mutator.py <path-to-CLAUDE.md> --set KEY=VALUE [--set KEY=VALUE ...]

    claude-md-mutator.py ./child/CLAUDE.md --set name="Child Group"
    claude-md-mutator.py ./CLAUDE.md --set orchestrator=true

Exit codes: 0 = written (or already equal, a no-op); 2 = refused (nothing
written), with the reason on stderr. Refusals are fail-closed: on any doubt it
writes nothing.
"""

import argparse
import os
import re
import sys
import tempfile

# The ONLY keys this mutator may change. Widening this is a change to the
# mutator itself — human-only under the ABSOLUTE HOLD; suggest, do not self-edit.
ALLOWED = ("name", "orchestrator")

# Value grammar per key. name: one printable line, no YAML-significant leading
# character (so a reader cannot mistake the value for a flow collection, anchor,
# tag, etc.), 1..200 chars. orchestrator: the literal true or false.
_NAME_BAD_LEAD = set(" \t[]{}&*!|>%@`\"'#,?:-")
_FRONTMATTER_READ_CAP = 64 * 1024  # the guard stops reading here; stay in step


def die(*msg):
    for m in msg:
        sys.stderr.write(str(m) + "\n")
    sys.exit(2)


def validate_value(key, value):
    """Return the validated value, or die() with a reason."""
    if "\n" in value or "\r" in value:
        die("REFUSED: a %s: value may not contain a line break." % key)
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        die("REFUSED: a %s: value may not contain control characters." % key)
    if key == "name":
        if not (1 <= len(value) <= 200):
            die("REFUSED: name: must be 1..200 characters (got %d)." % len(value))
        if value[0] in _NAME_BAD_LEAD:
            die("REFUSED: name: may not begin with %r "
                "(a YAML-significant or whitespace character)." % value[0])
        return value
    if key == "orchestrator":
        if value not in ("true", "false"):
            die("REFUSED: orchestrator: must be exactly 'true' or 'false' (got %r)." % value)
        return value
    die("REFUSED: %r is not an allowlisted key; only %s may be changed."
        % (key, " / ".join(ALLOWED)))


def parse_setters(pairs):
    """--set KEY=VALUE pairs -> ordered [(key, value)], validated, no dupes."""
    out = []
    seen = set()
    for raw in pairs:
        if "=" not in raw:
            die("REFUSED: --set expects KEY=VALUE, got %r." % raw)
        key, value = raw.split("=", 1)
        key = key.strip()
        if key not in ALLOWED:
            die("REFUSED: %r is not an allowlisted key; only %s may be changed."
                % (key, " / ".join(ALLOWED)))
        if key in seen:
            die("REFUSED: key %r given more than once." % key)
        seen.add(key)
        out.append((key, validate_value(key, value)))
    if not out:
        die("REFUSED: nothing to do — pass at least one --set KEY=VALUE.")
    return out


def split_frontmatter(text):
    """Return (fm_lines, body_start_index) for the leading --- ... --- block.

    fm_lines are the raw lines strictly between the fences. Fail closed on any
    document that does not open with a clean fence or whose block never closes.
    """
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        die("REFUSED: the file has no leading frontmatter block "
            "(first line is not exactly '---').")
    close = None
    consumed = 0
    for i in range(1, len(lines)):
        consumed += len(lines[i]) + 1
        if consumed > _FRONTMATTER_READ_CAP:
            die("REFUSED: frontmatter exceeds %d bytes, where the guard stops "
                "reading (fail closed)." % _FRONTMATTER_READ_CAP)
        if lines[i] == "---":
            close = i
            break
    if close is None:
        die("REFUSED: the frontmatter block is never closed by a line that is "
            "exactly '---' (fail closed).")
    return lines, close


# A top-level key line: KEY at column 0, then ':' then EOL or whitespace.
def _key_line_re(key):
    return re.compile(r"^" + re.escape(key) + r":(?:$|[ \t].*$)")


# Variants we refuse to touch rather than risk a second, conflicting entry:
# indented (nested), quoted, or a space before the colon.
def _suspicious_variant(line, key):
    stripped = line.lstrip()
    if stripped != line and re.match(r"^" + re.escape(key) + r"\s*:", stripped):
        return "indented"
    if re.match(r"""^["']""" + re.escape(key) + r"""["']\s*:""", line):
        return "quoted"
    if re.match(r"^" + re.escape(key) + r"\s+:", line):
        return "space before ':'"
    return None


def apply_set(lines, close, key, value):
    """Replace or append `key: value` within lines[1:close]. Returns new close."""
    kre = _key_line_re(key)
    hits = [i for i in range(1, close) if kre.match(lines[i])]
    for i in range(1, close):
        variant = _suspicious_variant(lines[i], key)
        if variant and not kre.match(lines[i]):
            die("REFUSED: %r appears in a form this mutator will not touch (%s): "
                "%r. Fix the frontmatter by hand." % (key, variant, lines[i]))
    if len(hits) > 1:
        die("REFUSED: %r appears on %d lines in the frontmatter; ambiguous "
            "(fail closed)." % (key, len(hits)))
    newline = "%s: %s" % (key, value)
    if hits:
        lines[hits[0]] = newline
        return close
    # Insert as the last frontmatter entry, just before the closing fence.
    lines.insert(close, newline)
    return close + 1


def atomic_write(path, text):
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".claude-md-mutator.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__)
    ap.add_argument("path", help="path to an existing CLAUDE.md")
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    metavar="KEY=VALUE", help="allowlisted key to set (repeatable)")
    args = ap.parse_args(argv)

    if os.path.basename(args.path).lower() != "claude.md":
        die("REFUSED: target basename is not CLAUDE.md: %r." % args.path)
    if not os.path.isfile(args.path):
        die("REFUSED: %r does not exist. This mutator edits an existing "
            "CLAUDE.md; creating one is /new-project's job." % args.path)

    setters = parse_setters(args.sets)

    try:
        with open(args.path, "rb") as f:
            raw = f.read()
    except OSError as e:
        die("REFUSED: cannot read %r: %s" % (args.path, e))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        die("REFUSED: %r is not valid UTF-8 (fail closed)." % args.path)

    lines, close = split_frontmatter(text)
    for key, value in setters:
        close = apply_set(lines, close, key, value)
    new_text = "\n".join(lines)

    if new_text == text:
        # Already equal — a no-op success, so callers can be idempotent.
        return 0
    atomic_write(args.path, new_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
