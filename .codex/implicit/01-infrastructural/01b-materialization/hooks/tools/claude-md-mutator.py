#!/usr/bin/env python3
"""The approved mutator for CLAUDE.md frontmatter.

The SOLE authorized writer of allowlisted frontmatter keys in an existing
CLAUDE.md (per the "updating any CLAUDE.md" ABSOLUTE HOLD in the apex CLAUDE.md).
The claude-md guard hook denies every Write/Edit to a CLAUDE.md; the precision
lives here, and the hook never sees this — it edits by direct file IO.

Two independent halves:

  * READ side is STRICT. The existing frontmatter must be "dead flat": between
    the `---` fences, every line is blank or a column-0 `key: value` with no
    embedded line break, and no key repeats. Anything else — an indented line, a
    continuation, a block scalar, a wrapped/multi-line value, a quoted/odd key, a
    duplicate key, a stray CR/NEL — is REFUSED, pointing at the offending line.
    (A single-line flow value such as `tags: [a, b]` is one flat line and passes
    through untouched.) We never edit around a shape we cannot reason about, and
    we never parse the file two different ways than its readers do.

  * WRITE side LAUNDERS. An incoming value is down-converted to a clean, flat,
    ASCII, single-line scalar rather than rejected: Unicode-normalized, every
    line break / control / irregular whitespace turned into " - ", transliterated
    to ASCII, colons / `---` / structural & quote characters stripped, whitespace
    collapsed. The result must clear a per-field minimum length AFTER laundering
    (that is how a name that laundered to nothing — e.g. an all-non-Latin name —
    is refused). `orchestrator` is not laundered: it is case-folded to
    true/false or refused.

On success the whole post-edit frontmatter block is written to stdout (the total
net state the caller can read back), and any value the laundering changed is
noted on stderr. Exit 0 = written or already-equal no-op; exit 2 = fail-closed
refusal (reason on stderr, REFUSED: prefix). argparse usage errors also exit 2.

Usage:
    claude-md-mutator.py <path-to-CLAUDE.md> --set KEY=VALUE [--set KEY=VALUE ...]
    claude-md-mutator.py ./child/CLAUDE.md --set name="Child Group"
    claude-md-mutator.py ./CLAUDE.md --set orchestrator=true --set description="…"
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
import unicodedata

# Allowlisted keys -> (min, max) post-laundering length, or None for the boolean
# orchestrator. Widening this is a change to the mutator itself — human-only
# under the ABSOLUTE HOLD; suggest, do not self-edit.
FIELDS = {
    "name": (5, 200),
    "description": (10, 300),
    "orchestrator": None,
}
ALLOWED = tuple(FIELDS)

_FRONTMATTER_READ_CAP = 64 * 1024  # the guard stops reading here; stay in step (bytes)
_FENCE = re.compile(r"^---[ \t]*$")             # a fence: --- + optional trailing blanks
_ENTRY = re.compile(r"^[A-Za-z0-9_.\-]+:")      # a dead-flat entry: column-0 key + colon
_DROP = ":`|<>[]{}\"'\\"                          # structural / quote / escape chars laundering removes


def die(*msg):
    for m in msg:
        sys.stderr.write(str(m) + "\n")
    sys.exit(2)


def launder(value):
    """Down-convert value to a clean, flat, ASCII, single-line scalar."""
    # Recover the real characters if argv arrived surrogate-escaped (a non-UTF-8
    # locale), so transliteration is identical in every environment.
    value = value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    v = unicodedata.normalize("NFKC", value)
    # Every line break, control char, or non-space whitespace -> " - " (a visible
    # separator, so nothing is silently joined or dropped). isspace() already
    # covers the Unicode line/paragraph separators (U+2028/U+2029/NEL).
    v = "".join(
        " - " if (c != " " and (c.isspace() or ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F
                                or unicodedata.category(c) == "Cf"))
        else c
        for c in v
    )
    # Transliterate to ASCII (drop accents/combining marks and any non-ASCII).
    v = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode("ascii")
    # Drop colons and structural/quote characters FIRST, then neutralize any run
    # of 3+ hyphens — including one the drop just formed by removing characters
    # between hyphens — so no '---' can survive into a value a substring reader
    # (e.g. cboot's find('---')) would close the frontmatter on.
    v = v.translate({ord(c): None for c in _DROP})
    v = re.sub(r"-{3,}", " - ", v)
    # Collapse the " - " separators we introduced (bare hyphens are preserved),
    # tidy internal spaces, drop empty segments, trim.
    parts = [re.sub(r" {2,}", " ", p).strip() for p in v.split(" - ")]
    return " - ".join(p for p in parts if p)


def process_value(key, raw):
    """Return the value to write for key, or die() fail-closed."""
    spec = FIELDS[key]
    if spec is None:  # orchestrator
        v = raw.strip().lower()
        if v not in ("true", "false"):
            die("REFUSED: orchestrator must be true or false (got %r)." % raw)
        return v
    lo, hi = spec
    v = launder(raw)
    if len(v) > hi:
        v = v[:hi].strip().strip("-").strip()
    if len(v) < lo:
        die("REFUSED: %s laundered to %r (%d chars), below the %d-char minimum."
            % (key, v, len(v), lo))
    return v


def parse_setters(pairs):
    """--set KEY=VALUE -> ordered [(key, raw)], allowlist-checked, no dupes."""
    out = []
    seen = set()
    for raw in pairs:
        if "=" not in raw:
            die("REFUSED: --set expects KEY=VALUE, got %r." % raw)
        key, value = raw.split("=", 1)
        if key not in ALLOWED:
            die("REFUSED: %r is not an allowlisted key; only %s may be changed."
                % (key, " / ".join(ALLOWED)))
        if key in seen:
            die("REFUSED: key %r given more than once." % key)
        seen.add(key)
        out.append((key, value))
    if not out:
        die("REFUSED: nothing to do — pass at least one --set KEY=VALUE.")
    return out


def split_frontmatter(text):
    """Return (lines, close_index) for a DEAD-FLAT leading frontmatter block, or
    die() fail-closed on any file that does not open with a fence, never closes,
    exceeds the byte cap, or whose block is not entirely blank / column-0
    `key: value` lines free of embedded breaks."""
    lines = text.split("\n")
    if not lines or not _FENCE.match(lines[0]):
        die("REFUSED: no leading frontmatter block (first line is not a --- fence).")
    close = None
    consumed = len(lines[0].encode("utf-8")) + 1
    for i in range(1, len(lines)):
        consumed += len(lines[i].encode("utf-8")) + 1
        if consumed > _FRONTMATTER_READ_CAP:
            die("REFUSED: frontmatter exceeds %d bytes (fail closed)." % _FRONTMATTER_READ_CAP)
        if _FENCE.match(lines[i]):
            close = i
            break
    if close is None:
        die("REFUSED: frontmatter block is never closed by a --- fence (fail closed).")
    keys = []
    for k in range(1, close):
        ln = lines[k]
        if ln.strip() == "":
            continue
        if len(ln.splitlines()) > 1 or not _ENTRY.match(ln):
            die("REFUSED: frontmatter is not flat — line %d is not a plain "
                "'key: value': %r. Edit it by hand." % (k + 1, ln))
        keys.append(ln.split(":", 1)[0])
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        die("REFUSED: frontmatter has duplicate key(s) %s; ambiguous — edit by hand."
            % ", ".join(dupes))
    return lines, close


def apply_set(lines, close, key, value):
    """Replace or append `key: value`. Dead-flat guarantees each key sits on a
    single flat line, so a straight replace can never orphan a continuation."""
    kre = re.compile(r"^" + re.escape(key) + r":")
    hits = [i for i in range(1, close) if kre.match(lines[i])]
    if len(hits) > 1:
        die("REFUSED: %r appears on %d lines in the frontmatter; ambiguous "
            "(fail closed)." % (key, len(hits)))
    newline = "%s: %s" % (key, value)
    if hits:
        lines[hits[0]] = newline
        return close
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
            shutil.copymode(path, tmp)
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
    # Force UTF-8 on the console streams so the block echo and notes never raise
    # UnicodeEncodeError under an ASCII locale (LANG=C) after a successful write.
    for _s, _errs in ((sys.stdout, "strict"), (sys.stderr, "backslashreplace")):
        try:
            _s.reconfigure(encoding="utf-8", errors=_errs)
        except (AttributeError, ValueError):
            pass
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
        final = process_value(key, value)
        if final != value:
            sys.stderr.write("note: %s %r -> %r\n" % (key, value, final))
        close = apply_set(lines, close, key, final)
    new_text = "\n".join(lines)

    if new_text != text:
        target = canonical_target(args.path)
        try:
            atomic_write(target, new_text)
        except OSError as e:
            die("REFUSED: cannot write %r: %s (fail closed)." % (target, e))
    # Return the whole post-edit frontmatter block: the total net state.
    sys.stdout.write("\n".join(lines[:close + 1]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
