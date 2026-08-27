#!/usr/bin/env bash
# Asserts that gravity-guard.sh and containment-guard.sh share a BYTE-IDENTICAL
# decision core (the region between the guard-core markers). Only GUARD_MODE,
# set outside the region, may differ.
#
# This replaces a prose claim. The docs used to say the two guards "are run
# through the same scenario matrix so they cannot drift apart"; nothing enforced
# it, and a resolve_root edit made in one guard only passed every suite. The
# scenario matrix now runs both guards through every case (test_guards_walkup.sh)
# AND the shared code is asserted identical here — a diff, not an adjective.
#
# Run: bash test_guards_identical.sh   (exit 0 = identical)
# GUARD_DIR=<dir> overrides which copies are compared.
set -u

G=${GUARD_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
BEGIN='# >>> guard-core'
END='# <<< guard-core'

extract() {  # <file>
    awk -v b="$BEGIN" -v e="$END" '
        index($0, b) == 1 { on = 1 }
        on { print }
        index($0, e) == 1 { exit }
    ' "$1"
}

A=$(extract "$G/containment-guard.sh")
B=$(extract "$G/gravity-guard.sh")

if [ -z "$A" ] || [ -z "$B" ]; then
    echo "FAIL  guard-core markers missing — cannot compare the shared region"
    echo "      containment: $(printf '%s' "$A" | wc -l) lines"
    echo "      gravity:     $(printf '%s' "$B" | wc -l) lines"
    exit 1
fi

if [ "$A" = "$B" ]; then
    printf 'PASS  guard-core is byte-identical in both guards (%s lines)\n' "$(printf '%s\n' "$A" | wc -l | tr -d ' ')"
    echo "ALL PASS"
    exit 0
fi

echo "FAIL  guard-core has DRIFTED between the two guards:"
diff <(printf '%s\n' "$A") <(printf '%s\n' "$B") | head -40
exit 1
