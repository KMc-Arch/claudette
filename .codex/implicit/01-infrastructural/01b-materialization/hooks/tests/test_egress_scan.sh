#!/usr/bin/env bash
# test_egress_scan.sh — proves symlink-egress-scan.sh, the DETECTIVE egress sweep.
#
# The egress scan is NOT a PreToolUse hook and NOT a boundary — it is an
# on-demand/boot sweep that SURFACES symlinks whose real target escapes ^ (the
# links no input-gate can stop: interpreter- and transitive-command-created ones).
# It had zero coverage; this harness is developer-run (like the other tests here),
# not registered in the hook inventory.
#
# Verifies: an in-^ symlink is left alone; a symlink whose real target escapes ^
# is reported (exit 1) naming the target; the _-prefix and .git/ skips hold;
# a symlink to ^ itself is not an escape; dangling links are range-checked by
# their lexical target (out=flagged, in=fine); --quarantine neutralises the link;
# usage/'not a directory' errors exit 2; and ROOT defaults to $CLAUDE_PROJECT_DIR.
# Exit 0 = all pass.
#
# NB: this test CREATES symlinks (ln -s) inside a disposable mktemp sandbox that
# is torn down per case. They never touch ^ — fixtures, not an egress path.
set -u

HOOKS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCAN="$HOOKS_DIR/tools/symlink-egress-scan.sh"
[ -f "$SCAN" ] || { echo "missing $SCAN"; exit 2; }

PASS=0; FAIL=0
ok() {  # <desc> <got-rc> <want-rc>
    if [ "$2" = "$3" ]; then printf 'PASS  %-52s rc=%s\n' "$1" "$3"; PASS=$((PASS+1))
    else printf 'FAIL  %-52s want=%s got=%s\n' "$1" "$3" "$2"; FAIL=$((FAIL+1)); fi
}
oks() {  # <desc> <haystack> <needle>  — substring assertion
    case "$2" in
        *"$3"*) printf 'PASS  %-52s (found)\n' "$1"; PASS=$((PASS+1)) ;;
        *)      printf 'FAIL  %-52s (missing "%s")\n' "$1" "$3"; FAIL=$((FAIL+1)) ;;
    esac
}
# fresh sandbox holding root/ (the scanned ^) and an out-of-root sibling outside/
new() { d=$(mktemp -d "${TMPDIR:-/tmp}/egress-XXXXXX"); mkdir -p "$d/root/sub" "$d/outside"; printf '%s' "$d"; }

# E01 — clean tree, no symlinks -> nothing to find
d=$(new); CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok "clean tree, no symlinks -> allow" $? 0; rm -rf "$d"

# E02 — symlink inside ^ that stays inside ^
d=$(new); ln -s "$d/root/sub" "$d/root/inlink"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok "in-^ symlink (stays inside) -> allow" $? 0; rm -rf "$d"

# E03 — symlink inside ^ pointing OUTSIDE ^  (the core case)
d=$(new); ln -s "$d/outside" "$d/root/escape"
cap=$(CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" 2>&1 >/dev/null); rc=$?
ok  "egress symlink -> found (exit 1)" "$rc" 1
oks "egress report contains EGRESS" "$cap" "EGRESS"
oks "egress report names the outside target" "$cap" "$d/outside"; rm -rf "$d"

# E04 — a symlink to ^ itself is not an escape
d=$(new); ln -s "$d/root" "$d/root/selflink"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok "symlink to ^ itself -> allow" $? 0; rm -rf "$d"

# E05 — a nested (sub-directory) egress symlink is still found (recursive)
d=$(new); ln -s "$d/outside" "$d/root/sub/deeplink"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok "nested egress symlink -> found" $? 1; rm -rf "$d"

# E06 — _-prefixed egress link is skipped (invisible by convention)
d=$(new); ln -s "$d/outside" "$d/root/_hidden"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok "_-prefixed egress link -> skipped (allow)" $? 0; rm -rf "$d"

# E07 — .git/ egress link is skipped
d=$(new); mkdir -p "$d/root/.git/hooks"; ln -s "$d/outside" "$d/root/.git/hooks/evil"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok ".git/ egress link -> skipped (allow)" $? 0; rm -rf "$d"

# E08 — dangling link whose lexical target is OUTSIDE ^ is still flagged
d=$(new); ln -s "$d/outside/gone" "$d/root/dangling"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok "dangling link to outside -> found" $? 1; rm -rf "$d"

# E09 — dangling link whose lexical target is INSIDE ^ is fine
d=$(new); ln -s "$d/root/notyet" "$d/root/dangling_in"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok "dangling link to inside ^ -> allow" $? 0; rm -rf "$d"

# E10 — --quarantine neutralises the link (removes it, leaves a plain-file record)
d=$(new); ln -s "$d/outside" "$d/root/escape"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" --quarantine >/dev/null 2>&1
ok "quarantine egress -> exit 1" $? 1
if [ ! -L "$d/root/escape" ] && [ -f "$d/root/escape.egress-quarantined" ]; then
    printf 'PASS  %-52s\n' "quarantine removed link + left file record"; PASS=$((PASS+1))
else printf 'FAIL  %-52s\n' "quarantine did not neutralise the link"; FAIL=$((FAIL+1)); fi
oks "quarantine record carries restore hint" "$(cat "$d/root/escape.egress-quarantined" 2>/dev/null)" "restore: ln -s"
rm -rf "$d"

# E11 — an unknown flag is a usage error
d=$(new); CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" --bogus >/dev/null 2>&1
ok "unknown flag -> usage error (exit 2)" $? 2; rm -rf "$d"

# E12 — a ROOT that is not a directory is an error
CLAUDE_PROJECT_DIR="" bash "$SCAN" "/nonexistent-egress-$$-dir" >/dev/null 2>&1
ok "non-directory ROOT -> error (exit 2)" $? 2

# E13 — ROOT defaults to $CLAUDE_PROJECT_DIR when no positional arg is given
d=$(new); ln -s "$d/outside" "$d/root/escape"
CLAUDE_PROJECT_DIR="$d/root" bash "$SCAN" >/dev/null 2>&1
ok "ROOT defaults to \$CLAUDE_PROJECT_DIR" $? 1; rm -rf "$d"

# E14 — sibling-PREFIX egress target: /.../rootX must NOT be read as inside /.../root.
#       Mutation-proofs the escape check against a `case "$real" in "$ROOT"*)` refactor,
#       which the "outside"-named fixtures above cannot catch (they share no prefix).
d=$(new); mkdir -p "$d/rootX"; ln -s "$d/rootX" "$d/root/pfx"
cap=$(CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" 2>&1 >/dev/null); rc=$?
ok  "sibling-prefix target (rootX) -> found, not read as inside" "$rc" 1
oks "sibling-prefix egress names rootX" "$cap" "$d/rootX"; rm -rf "$d"

# E15 — ROOT under _-prefixed ANCESTORS is still swept (#3): a _-ancestor of ROOT
#       must NOT fail the whole tree open. Mirrors /_foo/_bar/apex/project.
d=$(new); mkdir -p "$d/_foo/_bar/apex" "$d/target"
ln -s "$d/target" "$d/_foo/_bar/apex/escape"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/_foo/_bar/apex" >/dev/null 2>&1
ok "egress under ROOT with _-prefixed ancestors -> found" $? 1; rm -rf "$d"

# E16 — a _-prefixed component INSIDE ROOT is still skipped (the relative skip works)
d=$(new); mkdir -p "$d/root/_hidden" "$d/target2"
ln -s "$d/target2" "$d/root/_hidden/escape"
CLAUDE_PROJECT_DIR="" bash "$SCAN" "$d/root" >/dev/null 2>&1
ok "_-prefixed dir INSIDE ROOT -> skipped (allow)" $? 0; rm -rf "$d"

echo "-------------------------------------------"
if [ "$FAIL" -eq 0 ]; then echo "PASS=$PASS FAIL=0"; echo "ALL PASS"; exit 0
else echo "PASS=$PASS FAIL=$FAIL"; echo "SOME FAILED"; exit 1; fi
