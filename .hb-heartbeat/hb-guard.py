#!/usr/bin/env python3
"""Heartbeat sandbox guard (stdin: PreToolUse JSON for the Bash tool). Invoked by hb-guard.sh.

Runs ONLY inside a worker sandbox (installed via the sandbox's .claude/settings.local.json by runner.py).
Defense in depth under the structural controls (the worker has no git/gh credentials and the runner
does push + PR); this guard is ALLOWLIST-oriented so unknown shapes fail closed:

  * Bash path containment: any token that resolves under the live apex but outside the sandbox → block.
  * git: no global options (except --no-pager/-P and -c user.*/color.*/core.pager), and only a fixed
    subcommand allowlist (push, remote, config-writes, update-ref, symbolic-ref, worktree, tag, submodule,
    clone, filter-branch, replace, gc, reflog, -C … → block); branch/checkout/switch may not touch main/master
    or delete/force/rename.
  * gh: only pr view|list|diff|status|checks (read-only); everything else (create/merge/close/ready/review/
    edit, auth, alias, api, repo, release, issue, -R/--repo) → block.
  * wrappers are peeled and re-inspected: env, command, exec, nohup, setsid, nice, time, timeout, stdbuf,
    xargs, eval, bash/sh/zsh/dash -c, `$(...)`, backticks; interpreter one-liners (python/perl/node/ruby -c/-e)
    that mention git/gh → block; non-ASCII executable names → block.
  * secrets: tokens naming ~/.config/gh, hosts.yml, ~/.claude/.credentials*, GH_TOKEN/GITHUB_TOKEN, gh auth,
    or env assignments of HB_HOME/CLAUDE_PROJECT_DIR/GH_*/GIT_CONFIG_*/GIT_DIR/GIT_WORK_TREE → block.

Residual (documented, not claimed): a script file executed via python/bash that itself shells out.
Exit 0 = allow, exit 2 = block (message on stderr).
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

APEX = Path(__file__).resolve().parent.parent          # this file lives in <apex>/.hb-heartbeat/


def block(msg: str):
    print(f"BLOCKED by hb-guard: {msg}", file=sys.stderr)
    sys.exit(2)


GIT_ALLOWED_SUB = {
    "add", "am", "apply", "bisect", "blame", "branch", "cat-file", "check-ignore", "checkout", "cherry",
    "cherry-pick", "clean", "commit", "count-objects", "describe", "diff", "diff-tree", "difftool", "fetch",
    "for-each-ref", "format-patch", "fsck", "grep", "help", "log", "ls-files", "ls-tree", "merge", "merge-base",
    "mv", "name-rev", "pull", "range-diff", "rebase", "reset", "restore", "rev-list", "rev-parse", "revert",
    "rm", "shortlog", "show", "show-branch", "show-ref", "stash", "status", "switch", "var", "version",
    "whatchanged", "--version", "--help", "config",
}
GIT_OK_GLOBAL_PREFIX = ("-P", "--no-pager")
GIT_OK_C_KEYS = ("user.name", "user.email", "core.pager", "color.", "core.quotepath", "log.", "diff.", "advice.")
GH_ALLOWED_PR_SUB = {"view", "list", "diff", "status", "checks"}
WRAPPERS_DROP1 = {"env", "command", "exec", "nohup", "setsid", "nice", "time", "stdbuf", "ionice", "chronic", "unbuffer", "sudo", "doas", "caffeinate"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = {"python", "python3", "python2", "perl", "node", "ruby", "php", "lua", "awk", "gawk"}
SECRET_RE = re.compile(r"(\.config/gh\b|hosts\.yml|\.claude/\.credentials|\bGH_TOKEN\b|\bGITHUB_TOKEN\b|\bGH_ENTERPRISE_TOKEN\b|\.git-credentials|\.netrc\b|id_rsa|id_ed25519)")
ENV_ASSIGN_RE = re.compile(r"^(HB_HOME|CLAUDE_PROJECT_DIR|GH_CONFIG_DIR|GH_TOKEN|GITHUB_TOKEN|GH_HOST|GIT_CONFIG_[A-Z0-9_]+|GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR|GIT_ASKPASS|GIT_SSH_COMMAND|GIT_TERMINAL_PROMPT|GIT_EXEC_PATH|GIT_CEILING_DIRECTORIES|GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_OBJECT_DIRECTORY|PATH|HOME|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_CONFIG_NOSYSTEM|GIT_NAMESPACE)=")
GITGH_RE = re.compile(r"(^|[^A-Za-z0-9_./-])(git|gh)([^A-Za-z0-9_-]|$)")


def tokenize_segments(cmd: str):
    """Quote-aware split into command segments (lists of tokens). Uses shlex punctuation mode so
    ; | || && & > < ( ) split OUTSIDE quotes only. Falls back to a naive split on lexer errors."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        toks = None
    if toks is None:
        segs = []
        for s in re.split(r"\s*(?:&&|\|\||;|\||\n)\s*", cmd):
            if s.strip():
                try:
                    segs.append(shlex.split(s))
                except ValueError:
                    segs.append(s.split())
        return segs
    segs, cur = [], []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in (";", "|", "||", "&&", "&", "\n", "(", ")", ";;"):
            if cur:
                segs.append(cur); cur = []
            i += 1; continue
        if t in (">", ">>", "<", "<<", "<<<", "&>", "2>", "2>>", ">|"):
            # redirect: the target token gets a path check but is not part of the command tokens
            if i + 1 < len(toks):
                cur.append(("__redir__", toks[i + 1]))
            i += 2; continue
        cur.append(t); i += 1
    if cur:
        segs.append(cur)
    return segs


def path_check(tok: str, cwd: Path, sandbox: Path | None):
    """Any token resolving under APEX but not under the sandbox is a live-tree reference."""
    t = tok
    for pfx in ("--git-dir=", "--work-tree=", "--file=", "-f=", "--exec-path=", "--output=", "-o="):
        if t.startswith(pfx):
            t = t[len(pfx):]
    if t.startswith("~"):
        t = os.path.expanduser(t)
    if not t or t.startswith("-") and not t.startswith("-/"):
        return
    if not ("/" in t or t in (".", "..")):
        return
    try:
        p = Path(t) if os.path.isabs(t) else (cwd / t)
        rp = Path(os.path.normpath(str(p)))
    except (ValueError, OSError):
        return
    try:
        rp.relative_to(APEX)
    except ValueError:
        return                                     # outside the apex entirely — not our concern here
    if sandbox is not None:
        try:
            rp.relative_to(sandbox)
            return                                 # inside the sandbox — fine
        except ValueError:
            pass
    block(f"'{tok}' resolves to the LIVE tree ({rp}) — the sandbox worker may only touch its own worktree")


def check_git(args: list, cwd: Path, sandbox):
    a = list(args)
    # global options: allow only a tiny set; everything else (incl. -C, --git-dir, -c alias.*, --exec-path…) is out
    while a and a[0].startswith("-"):
        tok = a[0]
        if tok in GIT_OK_GLOBAL_PREFIX:
            a = a[1:]; continue
        if tok == "-c" and len(a) > 1 and a[1].split("=", 1)[0].startswith(GIT_OK_C_KEYS):
            a = a[2:]; continue
        if tok.startswith("-c") and len(tok) > 2 and tok[2:].split("=", 1)[0].startswith(GIT_OK_C_KEYS):
            a = a[1:]; continue
        if tok in ("--version", "--help"):
            return
        block(f"git global option '{tok}' is not allowed in the sandbox")
    if not a:
        return
    sub, rest = a[0], a[1:]
    if sub not in GIT_ALLOWED_SUB:
        block(f"git subcommand '{sub}' is not on the sandbox allowlist (push/remote/tag/worktree/update-ref/aliases… are runner-only or forbidden)")
    if sub == "config":
        if not any(t in ("--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--show-scope") for t in rest):
            block("git config: only reads (--get/--list) are allowed in the sandbox")
        return
    if sub == "branch":
        if any(t in ("-D", "-d", "--delete", "-f", "--force", "-M", "-m", "--move", "-c", "-C", "--copy", "-u", "--set-upstream-to", "--unset-upstream", "--edit-description") for t in rest):
            block("git branch: delete/force/rename/copy/upstream edits are not allowed in the sandbox")
        return
    if sub in ("checkout", "switch"):
        if any(t in ("main", "master", "-B", "--orphan", "--detach", "-C") for t in rest):
            block(f"git {sub}: main/master/-B/--orphan/--detach are not allowed — work only on the hb/ branch")
        for t in rest:
            if t.startswith("origin/main") or t.startswith("origin/master") or t.startswith("refs/heads/main") or t.startswith("refs/heads/master"):
                block(f"git {sub} {t}: main/master are off limits")
        return
    if sub in ("fetch", "pull"):
        for t in rest:
            if ":" in t and t.split(":", 1)[1].lstrip("+") in ("main", "master", "refs/heads/main", "refs/heads/master"):
                block(f"git {sub}: refspec into main/master")
        return
    if sub in ("reset",):
        if any(t.startswith("origin/main") or t.startswith("origin/master") for t in rest):
            return  # resetting the sandbox branch to origin/main is harmless (local)
        return


def check_gh(args: list):
    if any(t in ("-R", "--repo") or t.startswith("--repo=") or t.startswith("--hostname") for t in args):
        block("gh: -R/--repo/--hostname are not allowed in the sandbox")
    if not args or args[0] in ("--version", "--help", "help"):
        return
    if args[0] == "pr" and len(args) > 1 and args[1] in GH_ALLOWED_PR_SUB:
        return
    block(f"gh {' '.join(args[:2])}: only `gh pr view|list|diff|status|checks` are allowed — the runner creates the PR; nobody merges")


def strip_env_assign(toks: list):
    while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
        if ENV_ASSIGN_RE.match(toks[0]):
            block(f"environment override '{toks[0].split('=', 1)[0]}=' is not allowed in the sandbox")
        toks = toks[1:]
    return toks


def inspect_tokens(toks: list, cwd: Path, sandbox, depth: int = 0):
    if depth > 6 or not toks:
        return
    toks = strip_env_assign(toks)
    if not toks:
        return
    exe_full = toks[0]
    exe = exe_full.rsplit("/", 1)[-1]
    if not exe.isascii():
        block(f"non-ASCII executable name {exe!r}")
    args = toks[1:]
    # wrappers
    if exe in WRAPPERS_DROP1:
        rest = args
        if exe == "env":
            while rest and (rest[0].startswith("-") or "=" in rest[0]):
                if "=" in rest[0] and ENV_ASSIGN_RE.match(rest[0]):
                    block(f"env override '{rest[0]}' is not allowed")
                rest = rest[1:] if not rest[0] in ("-u", "--unset", "-C", "--chdir", "-S", "--split-string") else rest[2:]
        elif exe in ("nice", "ionice", "stdbuf", "sudo", "doas", "time", "timeout" ):
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
        return inspect_tokens(rest, cwd, sandbox, depth + 1)
    if exe == "timeout":
        rest = args
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return inspect_tokens(rest[1:], cwd, sandbox, depth + 1)   # skip the duration
    if exe == "xargs":
        rest = [t for t in args if not t.startswith("-")]
        return inspect_tokens(rest, cwd, sandbox, depth + 1)
    if exe == "eval":
        return inspect_command(" ".join(args), cwd, sandbox, depth + 1)
    if exe in SHELLS:
        for i, t in enumerate(args):
            if t in ("-c", "-lc", "-ic", "-xc", "-ec") or (t.startswith("-") and "c" in t and len(t) <= 4):
                if i + 1 < len(args):
                    return inspect_command(args[i + 1], cwd, sandbox, depth + 1)
        for t in args:
            if not t.startswith("-"):
                path_check(t, cwd, sandbox)
        return
    if exe in INTERPRETERS:
        for i, t in enumerate(args):
            if t in ("-c", "-e", "-E") and i + 1 < len(args) and GITGH_RE.search(args[i + 1]):
                block(f"{exe} one-liner referencing git/gh")
        for t in args:
            path_check(t, cwd, sandbox)
        return
    if exe == "git":
        for t in args:
            path_check(t, cwd, sandbox)
        return check_git(args, cwd, sandbox)
    if exe == "gh":
        return check_gh(args)
    for t in toks:
        if SECRET_RE.search(t):
            block(f"token '{t}' references credentials")
        path_check(t, cwd, sandbox)


def inspect_command(cmd: str, cwd: Path, sandbox, depth: int = 0):
    if depth > 6:
        return
    # command substitutions and backticks: inspect inner text as its own command
    for m in re.finditer(r"\$\((.*?)\)|`([^`]*)`", cmd, re.S):
        inner = m.group(1) or m.group(2) or ""
        if inner.strip():
            inspect_command(inner, cwd, sandbox, depth + 1)
    if SECRET_RE.search(cmd):
        block("command references credential files/variables")
    if "gh auth" in cmd or "gh alias" in cmd:
        block("gh auth/alias are not allowed in the sandbox")
    for toks in tokenize_segments(cmd):
        plain = []
        for t in toks:
            if isinstance(t, tuple):
                path_check(t[1], cwd, sandbox)
            else:
                plain.append(t)
        inspect_tokens(plain, cwd, sandbox, depth)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd.strip():
        sys.exit(0)
    cwd = Path(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    sb = os.environ.get("HB_SANDBOX") or os.environ.get("CLAUDE_PROJECT_DIR")
    sandbox = Path(sb).resolve() if sb else None
    if sandbox is not None:
        try:
            sandbox.relative_to(APEX)
        except ValueError:
            sandbox = None            # not our sandbox layout; containment check degrades to apex-wide
    inspect_command(cmd, cwd, sandbox)
    sys.exit(0)


if __name__ == "__main__":
    main()
