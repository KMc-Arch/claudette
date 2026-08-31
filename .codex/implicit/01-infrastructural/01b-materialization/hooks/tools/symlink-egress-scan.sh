#!/usr/bin/env bash
# symlink-egress-scan.sh — DETECTIVE control (NOT a PreToolUse hook, NOT a boundary).
#
# Scans a root for symlinks whose REAL target escapes that root. Under the
# as-referenced (lexical) path-resolution model, a symlink inside ^ is treated as
# an authorized extension of the project — which is only sound if every symlink was
# placed by a human. This sweep SURFACES the ones that weren't: interpreter-created
# links, and the transitive links that must-allow commands leave behind
# (git checkout, tar/unzip, npm install, python -m venv). No input-gate can prevent
# those; the actual boundary is environment isolation (BL-61). This only reports.
#
# Run it at session start (a boot sweep) and on demand. It is intentionally cheap
# and read-only unless --quarantine is given.
#
# Usage:
#   symlink-egress-scan.sh [ROOT] [--quarantine]
#     ROOT          directory to scan; defaults to $CLAUDE_PROJECT_DIR, then $PWD.
#     --quarantine  rename each escaping link to <name>.egress-quarantined
#                   (in place, next to the link) instead of only reporting it.
# Exit: 0 = no escaping symlinks found; 1 = found (and reported); 2 = usage/error.
set -u

QUARANTINE=0
ROOT=""
for a in "$@"; do
    case "$a" in
        --quarantine) QUARANTINE=1 ;;
        -*) echo "usage: symlink-egress-scan.sh [ROOT] [--quarantine]" >&2; exit 2 ;;
        *)  ROOT="$a" ;;
    esac
done
[ -n "$ROOT" ] || ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"

# Canonicalise the root the same way containment does (realpath, in python, so a
# broken/absent shell realpath is irrelevant and there is no dependency drift).
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then echo "symlink-egress-scan: no python interpreter." >&2; exit 2; fi
ROOT=$("$PY" -c 'import os,sys; sys.stdout.write(os.path.realpath(sys.argv[1]))' "$ROOT" 2>/dev/null)
[ -n "$ROOT" ] && [ -d "$ROOT" ] || { echo "symlink-egress-scan: root not a directory: $ROOT" >&2; exit 2; }

# Every symlink under ROOT, skipping _-prefixed paths (invisible by convention) and
# the .git internals (git's own refs/objects never symlink outside the tree).
FOUND=0
while IFS= read -r -d '' link; do
    # Skip _-prefixed and .git paths RELATIVE TO ROOT. Matching the absolute
    # $link would fail OPEN when a _-prefixed ANCESTOR of ROOT exists (e.g.
    # ROOT=/_foo/_bar/apex) — every link path would contain "/_" and the whole
    # sweep would skip. Strip ROOT first: only _-components AT or BELOW ROOT are
    # invisible-by-convention.
    rel=${link#"$ROOT"/}
    case "/$rel" in
        */_*|*/.git/*) continue ;;
    esac
    # Real destination of the link. A dangling link realpaths to its lexical target,
    # which is still the right thing to range-check.
    real=$("$PY" -c 'import os,sys; sys.stdout.write(os.path.realpath(sys.argv[1]))' "$link" 2>/dev/null)
    [ -n "$real" ] || continue
    # Escapes ROOT iff it is neither ROOT itself nor strictly beneath it.
    case "$real" in
        "$ROOT"|"$ROOT"/*) continue ;;   # target stays inside ^ — an in-project link, fine
    esac
    FOUND=$((FOUND+1))
    tgt=$(readlink "$link" 2>/dev/null)
    printf 'EGRESS  %s -> %s  (resolves to %s, OUTSIDE %s)\n' "$link" "$tgt" "$real" "$ROOT" >&2
    if [ "$QUARANTINE" -eq 1 ]; then
        # Neutralise by REPLACING the symlink with a regular file that records it.
        # A rename alone would leave a working symlink under a new name — the egress
        # would survive. Removing the link and dropping a plain-text record kills the
        # egress (there is no symlink any more) and preserves enough to restore it by
        # hand: `ln -s "<target>" "<link>"`.
        note="$link.egress-quarantined"
        if rm -- "$link" 2>/dev/null && \
           printf 'EGRESS-QUARANTINED symlink (neutralised by symlink-egress-scan)\nlink:   %s\ntarget: %s\nresolved-to: %s (outside %s)\nrestore: ln -s "%s" "%s"\n' \
                  "$link" "$tgt" "$real" "$ROOT" "$tgt" "$link" > "$note" 2>/dev/null; then
            printf '        neutralised -> %s (link removed; regular-file record)\n' "$note" >&2
        else
            printf '        COULD NOT quarantine (left in place)\n' >&2
        fi
    fi
done < <(find "$ROOT" -type l -print0 2>/dev/null)

if [ "$FOUND" -eq 0 ]; then
    exit 0
fi
echo "symlink-egress-scan: $FOUND escaping symlink(s) under $ROOT.$([ "$QUARANTINE" -eq 1 ] && echo ' Quarantined.' || echo ' Reported only (pass --quarantine to neutralise).')" >&2
exit 1
