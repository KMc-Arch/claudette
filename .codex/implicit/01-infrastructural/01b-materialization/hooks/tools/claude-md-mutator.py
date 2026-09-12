#!/usr/bin/env python3
"""The approved mutator for CLAUDE.md frontmatter.

This is the SOLE authorized writer of allowlisted frontmatter keys in an
existing CLAUDE.md (per the "updating any CLAUDE.md" ABSOLUTE HOLD in the apex
CLAUDE.md). The claude-md guard hook deliberately denies every Write/Edit to a
CLAUDE.md-shaped path; the precision the hook does not carry lives HERE instead:
a fixed key allowlist, structural value validation, and an atomic write. The
hook never sees this script — it edits by direct file IO, not a tool call.

It matches how this repo's CLAUDE.md readers actually parse frontmatter — every
one (cboot, the containment/gravity guards, boot-inject, child_propagate) is a
tolerant, line-oriented parser: the block is `---`…`---` where a fence is a line
of `---` with optional trailing blanks (`^---[ \\t]*$`), and a key's value is
everything after the first colon, taken verbatim (no YAML). So the mutator does
NOT police YAML-scalar aesthetics (a colon or `#` in a name round-trips fine and
/new-project already inserts names verbatim); it only guarantees the value stays
a single, clean, UTF-8 line so it cannot inject structure or drift on round-trip.

Scope, on purpose:
  * EDIT ONLY. The target must already exist and already carry a leading
    frontmatter block. Creating a CLAUDE.md is /new-project's job, not this.
  * Allowlisted keys ONLY: name, orchestrator. Nothing else — not the body,
    not any other frontmatter key.
  * Not a security boundary. Path containment / gravity are other guards' job;
    this refuses only what it cannot mutate cleanly. It does insist the target
    basename is CLAUDE.md so it cannot be repurposed as a general file writer,
    and it writes to the file's real on-disk spelling so a case-insensitive
    mount's dirent is never silently case-flipped.

Usage:
    claude-md-mutator.py <path-to-CLAUDE.md> --set KEY=VALUE [--set KEY=VALUE ...]

    claude-md-mutator.py ./child/CLAUDE.md --set name="Child Group"
    claude-md-mutator.py ./CLAUDE.md --set orchestrator=true

Exit codes: 0 = written (or already equal, a no-op); 2 = refused (nothing
written), reason on stderr with a REFUSED: prefix. Every refusal — bad target,
bad value, unreadable/unwritable file, ambiguous frontmatter — is fail-closed:
on any doubt it writes nothing. (argparse usage errors also exit 2, without the
REFUSED: prefix; they too write nothing.)
"""

import argparse
import os
import re
import shutil
import sys
import tempfile

# The ONLY keys this mutator may change. Widening this is a change to the
# mutator itself — human-only under the ABSOLUTE HOLD; suggest, do not self-edit.
ALLOWED = ("name", "orchestrator")

# The guard stops reading frontmatter at this many bytes; stay in step (bytes,
# not characters — the readers are byte-oriented).
_FRONTMATTER_READ_CAP = 64 * 1024

# A frontmatter fence: `---` with only optional trailing blanks. Mirrors the
# readers (`^---[ \t]*$`). A CR (CRLF file) is deliberately NOT matched, so a
# CRLF CLAUDE.md fails closed (refused) rather than being risk-edited — this
# repo is LF, and the readers tolerate what we decline to touch.
_FENCE = re.compile(r"^---[ \t]*$")


def die(*msg):
    for m in msg:
        sys.stderr.write(str(m) + "\n")
    sys.exit(2)


def validate_value(key, value):
    """Structural validation only — return the value or die().

    The readers take the value verbatim after the first colon, so the only real
    hazards are (a) breaking the single-line structure (a newline would inject a
    second frontmatter line) and (b) a value that does not round-trip (control
    chars, non-UTF-8, or surrounding whitespace the readers strip).
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        die("REFUSED: a %s: value is not encodable as UTF-8 (fail closed)." % key)
    # Reject a line break of ANY kind — not just LF/CR but the Unicode line and
    # paragraph separators and NEL that str.splitlines() and YAML-1.1 recognise
    # (a trailing break included). Otherwise the value could inject a second
    # frontmatter line under a splitlines-based reader.
    if value != "".join(value.splitlines()):
        die("REFUSED: a %s: value may not contain a line break." % key)
    # Controls: C0 (<0x20), DEL (0x7F) and the C1 block (0x80-0x9F).
    if any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in value):
        die("REFUSED: a %s: value may not contain control characters." % key)
    if value != value.strip():
        die("REFUSED: a %s: value may not have leading or trailing whitespace "
            "(the readers strip it, so the file would not match the value)." % key)
    if key == "name":
        if not (1 <= len(value) <= 200):
            die("REFUSED: name: must be 1..200 characters (got %d)." % len(value))
        if value[0] in "|>[{":
            die("REFUSED: name: may not begin with a YAML block or flow indicator "
                "(| > [ {); use a plain single-line value.")
        if value[0] in "\"'" or value[-1] in "\"'":
            die("REFUSED: name: may not begin or end with a quote (a reader "
                "strips edge quotes, so the file would not match the value).")
        if "---" in value:
            die("REFUSED: name: may not contain '---' (a reader that closes the "
                "frontmatter on a '---' substring would truncate the value).")
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
    """Return (lines, close_index) for the leading `---`…`---` block.

    Fences are matched leniently (`^---[ \t]*$`), the same as every reader, so a
    trailing-whitespace fence closes the block here exactly where it closes it
    for them. Fail closed on any file that does not open with a fence or whose
    block never closes, or whose frontmatter exceeds the byte cap.
    """
    lines = text.split("\n")
    if not lines or not _FENCE.match(lines[0]):
        die("REFUSED: the file has no leading frontmatter block "
            "(first line is not a --- fence).")
    close = None
    consumed = len(lines[0].encode("utf-8")) + 1
    for i in range(1, len(lines)):
        consumed += len(lines[i].encode("utf-8")) + 1
        if consumed > _FRONTMATTER_READ_CAP:
            die("REFUSED: frontmatter exceeds %d bytes, where the guard stops "
                "reading (fail closed)." % _FRONTMATTER_READ_CAP)
        if _FENCE.match(lines[i]):
            close = i
            break
    if close is None:
        die("REFUSED: the frontmatter block is never closed by a --- fence "
            "(fail closed).")
    return lines, close


# A top-level key line: KEY at column 0 immediately followed by ':'. Matches
# `name:`, `name: X`, and `name:X` (no space) alike; NOT `named:`.
def _key_line_re(key):
    return re.compile(r"^" + re.escape(key) + r":")


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
        i = hits[0]
        # Refuse to touch a non-plain value — a block scalar, a flow collection,
        # or any value with a continuation line — rather than replace only the key
        # line and orphan (or promote) the rest. The mutator only ever WRITES a
        # plain single-line value (validate_value bars a leading | > [ {), so every
        # value it authored stays editable; this refuses only hand-authored ones.
        # A block scalar may begin after blank lines, so skip blanks before the
        # indented-continuation test.
        value_part = lines[i].split(":", 1)[1].strip()
        if value_part[:1] in "|>[{":
            die("REFUSED: %r has a block-scalar or flow value (%r); edit it by hand."
                % (key, lines[i]))
        j = i + 1
        while j < close and lines[j].strip() == "":
            j += 1
        if j < close and re.match(r"^[ \t]", lines[j]):
            die("REFUSED: %r has a multi-line value (an indented continuation "
                "follows); edit it by hand." % key)
        lines[i] = newline
        return close
    # Insert as the last frontmatter entry, just before the closing fence.
    lines.insert(close, newline)
    return close + 1


def canonical_target(path):
    """The real on-disk spelling of path's basename, so an atomic replace does
    not silently case-flip a case-insensitive/case-preserving dirent."""
    d = os.path.dirname(path) or "."
    base = os.path.basename(path)
    try:
        entries = os.listdir(d)
    except OSError:
        return path
    if base in entries:
        return path
    for entry in entries:
        if entry.lower() == base.lower() and os.path.isfile(os.path.join(d, entry)):
            return os.path.join(d, entry)
    return path


def atomic_write(path, text):
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".claude-md-mutator.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        try:
            shutil.copymode(path, tmp)  # preserve mode (portability; a no-op on metadata-less drvfs)
        except OSError:
            pass
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
    if os.path.islink(args.path):
        die("REFUSED: %r is a symlink; edit the real file directly "
            "(a symlink target is outside this mutator's scope)." % args.path)
    if not os.path.isfile(args.path):
        if os.path.exists(args.path):
            die("REFUSED: %r exists but is not a regular file (fail closed)." % args.path)
        die("REFUSED: %r does not exist. This mutator edits an existing "
            "CLAUDE.md; creating one is /new-project's job." % args.path)

    setters = parse_setters(args.sets)

    try:
        with open(args.path, "rb") as f:
            raw = f.read()
    except OSError as e:
        die("REFUSED: cannot read %r: %s (fail closed)." % (args.path, e))
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
    target = canonical_target(args.path)
    try:
        atomic_write(target, new_text)
    except OSError as e:
        die("REFUSED: cannot write %r: %s (fail closed)." % (target, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
