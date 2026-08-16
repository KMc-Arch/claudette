#!/usr/bin/env python3
"""Heartbeat sandbox guard logic (stdin: PreToolUse JSON). Invoked by hb-guard.sh."""
import json, re, shlex, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (data.get("tool_input") or {}).get("command") or ""
if not cmd.strip():
    sys.exit(0)

def block(msg):
    print(f"BLOCKED by hb-guard: {msg}", file=sys.stderr)
    sys.exit(2)

# Split on shell separators so chained commands are each inspected.
segments = re.split(r"\s*(?:&&|\|\||;|\||\n)\s*", cmd)
for seg in segments:
    try:
        toks = shlex.split(seg)
    except ValueError:
        toks = seg.split()
    if not toks:
        continue
    # skip leading env assignments / sudo-ish wrappers
    while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
        toks = toks[1:]
    if not toks:
        continue
    exe = toks[0].rsplit("/", 1)[-1]
    args = toks[1:]
    if exe == "gh":
        if len(args) >= 2 and args[0] == "pr" and args[1] in ("merge", "close", "ready", "lock", "unlock"):
            block(f"gh pr {args[1]} — Heartbeat never enacts a PR")
        if len(args) >= 2 and args[0] == "pr" and args[1] == "review" and any(a in ("--approve", "-a") for a in args):
            block("gh pr review --approve — Heartbeat never approves")
        if args[:1] == ["repo"]:
            block("gh repo — repository-level mutation")
        if args[:1] == ["api"] or args[:1] == ["release"] or args[:1] == ["issue"]:
            block(f"gh {args[0]} — shared GitHub state")
    if exe == "git":
        # strip global opts like -C path / -c k=v
        a = list(args)
        while a and a[0] in ("-C", "-c", "--git-dir", "--work-tree") and len(a) > 1:
            a = a[2:]
        if not a:
            continue
        sub = a[0]
        rest = a[1:]
        if sub == "push":
            if any(t in ("--delete", "-d") for t in rest):
                block("git push --delete — remote branch deletion")
            for t in rest:
                if not t.startswith("-") and ":" in t and t.split(":", 1)[0] == "":
                    block(f"git push {t} — empty-source refspec deletes the remote ref")
            if any(t in ("--force", "-f", "--force-with-lease", "--force-if-includes") for t in rest):
                block("force push")
            for t in rest:
                tgt = t.split(":")[-1] if ":" in t else t
                if tgt in ("main", "master") and not t.startswith("-"):
                    block("push to main/master")
        if sub == "update-ref":
            block("git update-ref — low-level ref mutation")
        if sub == "worktree":
            block("git worktree — sandbox must not spawn sandboxes")
        if sub == "branch" and any(t in ("-D", "-f", "--force", "--delete", "-d") for t in rest):
            block("git branch delete/force")
        if sub in ("checkout", "switch") and any(t in ("main", "master") for t in rest):
            block("checkout main/master — work only on the hb/ branch")
        # `git merge main` (main INTO the hb branch) is allowed and useful; merging INTO main needs a
        # checkout of main, which is blocked above and impossible in a worktree while live has it.
sys.exit(0)
