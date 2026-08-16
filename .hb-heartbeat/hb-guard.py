#!/usr/bin/env python3
"""Heartbeat sandbox guard (stdin: PreToolUse JSON for the Bash tool). Invoked by hb-guard.sh.

Runs ONLY inside a worker sandbox (installed via the sandbox's .claude/settings.local.json by runner.py).
Defense in depth under the structural controls (the worker has no git/gh credentials and the runner
does push + PR); this guard is ALLOWLIST-oriented so unknown shapes fail closed:

  * Bash path containment: any token that resolves under (or mentions, anywhere, case-insensitively) the live apex or an
    alias mount but outside the sandbox → block; globs fail closed toward the apex; `$VAR/...`-rooted paths are refused
    (unresolvable); heredoc bodies are data (dropped) unless they feed a shell/interpreter/eval, in which case they are code.
  * git: no global options (except --no-pager/-P and -c user.name/user.email), and only a fixed
    subcommand allowlist (push, remote, grep, config-writes, update-ref, symbolic-ref, worktree, tag, submodule,
    clone, filter-branch, replace, gc, reflog, -C … → block; use plain grep/rg instead of `git grep`); branch/checkout/switch may not touch main/master
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
import glob as globmod
import json
import os
import re
import shlex
import sys
from pathlib import Path

APEX = Path(__file__).resolve().parent.parent          # this file lives in <apex>/.hb-heartbeat/
# Alias mount points of the apex (drvfs mounts the same Windows dir more than once, e.g. /mnt/d/claudette);
# runner.py computes them from /proc/mounts and passes HB_APEX_ALIASES=path1:path2.
APEX_ROOTS = [APEX] + [Path(a) for a in os.environ.get("HB_APEX_ALIASES", "").split(":") if a]
GLOB_CHARS = set("*?[")
SHELL_KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "case", "esac", "{", "}",
                  "!", "function", "select", "in", "coproc", "((", "))", "[[", "]]"}
ENV_MUTATORS = {"unset", "export", "declare", "typeset", "local", "readonly"}


def block(msg: str):
    print(f"BLOCKED by hb-guard: {msg}", file=sys.stderr)
    sys.exit(2)


GIT_ALLOWED_SUB = {
    "add", "am", "apply", "bisect", "blame", "branch", "cat-file", "check-ignore", "checkout", "cherry",
    "cherry-pick", "clean", "commit", "count-objects", "describe", "diff", "diff-tree", "fetch",
    "for-each-ref", "format-patch", "fsck", "help", "log", "ls-files", "ls-tree", "merge", "merge-base",
    "mv", "name-rev", "pull", "range-diff", "rebase", "reset", "restore", "rev-list", "rev-parse", "revert",
    "rm", "shortlog", "show", "show-branch", "show-ref", "stash", "status", "switch", "var", "version",
    "whatchanged", "--version", "--help", "config",
}
GIT_ALLOWED_SUB.discard("difftool")
GIT_OK_GLOBAL_PREFIX = ("-P", "--no-pager")
GIT_OK_C_KEYS = ("user.name", "user.email")   # everything else (core.pager, diff.external, alias.*, …) can execute code
GH_ALLOWED_PR_SUB = {"view", "list", "diff", "status", "checks"}
WRAPPERS_DROP1 = {"env", "command", "builtin", "exec", "nohup", "setsid", "nice", "time", "stdbuf", "ionice", "chronic", "unbuffer", "sudo", "doas", "caffeinate"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = {"python", "python3", "python2", "perl", "node", "ruby", "php", "lua", "awk", "gawk"}
SECRET_RE = re.compile(r"(\.config/gh\b|hosts\.yml|\.claude/\.credentials|\bGH_TOKEN\b|\bGITHUB_TOKEN\b|\bGH_ENTERPRISE_TOKEN\b|\.git-credentials|\.netrc\b|id_rsa|id_ed25519)")
PROTECTED_VARS = r"(GIT_EDITOR|EDITOR|VISUAL|PAGER|GIT_PAGER|GIT_SEQUENCE_EDITOR|GIT_EXTERNAL_DIFF|GIT_PROXY_COMMAND|GIT_SSH_VARIANT|BROWSER|LESSOPEN|LESSCLOSE|GIT_DIFF_OPTS|GIT_TEMPLATE_DIR|GIT_ATTR_NOSYSTEM|GIT_ALLOW_PROTOCOL|GIT_PROTOCOL_FROM_USER|GIT_CURL_VERBOSE|GIT_TRACE[A-Z0-9_]*|HB_HOME|HB_SANDBOX|HB_APEX_ALIASES|CLAUDE_PROJECT_DIR|CLAUDE_CONFIG_DIR|GH_CONFIG_DIR|GH_TOKEN|GITHUB_TOKEN|GH_ENTERPRISE_TOKEN|GH_HOST|GIT_CONFIG_[A-Z0-9_]+|GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR|GIT_ASKPASS|SSH_ASKPASS|GIT_SSH|GIT_SSH_COMMAND|GIT_TERMINAL_PROMPT|GIT_EXEC_PATH|GIT_CEILING_DIRECTORIES|GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_OBJECT_DIRECTORY|PATH|HOME|XDG_CONFIG_HOME|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_CONFIG_NOSYSTEM|GIT_NAMESPACE|LD_PRELOAD|LD_LIBRARY_PATH|PYTHONPATH|PYTHONSTARTUP|BASH_ENV|ENV|PROMPT_COMMAND)"
ENV_ASSIGN_RE = re.compile(r"^" + PROTECTED_VARS + r"=")
PROTECTED_NAME_RE = re.compile(r"^" + PROTECTED_VARS + r"$")
WINPATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
GITGH_RE = re.compile(r"(^|[^A-Za-z0-9_./-])(git|gh)([^A-Za-z0-9_-]|$)")


def tokenize_segments(cmd: str):
    """Quote-aware split into command segments (lists of tokens). Uses shlex punctuation mode so
    ; | || && & > < ( ) split OUTSIDE quotes only. Falls back to a naive split on lexer errors."""
    # newlines are command separators (shlex treats them as whitespace): make them explicit
    cmd = cmd.replace("\r\n", "\n").replace("\n", " ; ")
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


def _under(rp: Path, root: Path) -> bool:
    """Prefix test, case-insensitive: drvfs mounts (the apex and its aliases) fold case below the mount point."""
    a, b = str(rp).lower().rstrip("/"), str(root).lower().rstrip("/")
    return a == b or a.startswith(b + "/")


def _mentions_live_tree(tok: str, sandbox) -> bool:
    """A live-tree path embedded ANYWHERE in a token (quoted multi-word strings, VAR=..., sh -c payloads)."""
    low = tok.lower()
    apex_l = str(APEX).lower().rstrip("/")
    sb = str(sandbox).lower().rstrip("/") if sandbox is not None else None
    for root in APEX_ROOTS:
        r = str(root).lower().rstrip("/")
        sb_here = (r + sb[len(apex_l):]) if (sb and sb.startswith(apex_l + "/")) else None
        i = low.find(r)
        while i != -1:
            tail = low[i + len(r):]
            if tail == "" or tail[0] in "/'\" \t)]};|&,>":
                seg = low[i:]
                if not (sb_here and (seg == sb_here or seg.startswith(sb_here + "/"))):
                    return True
            i = low.find(r, i + 1)
    return False


def _in_apex_not_sandbox(rp: Path, sandbox) -> bool:
    for root in APEX_ROOTS:
        if _under(rp, root):
            if sandbox is not None:
                # the sandbox is <apex>/<rel>; under an alias root the same rel applies
                rel = sandbox.relative_to(APEX) if _under(sandbox, APEX) else None
                sb_here = (root / rel) if rel is not None else sandbox
                if _under(rp, sb_here):
                    return False
            return True
    return False


def _candidates(tok: str):
    """Sub-strings of a token that may be paths: the token, anything after '=', anything from the first '/' or '~'
    in an option-looking token (-o/x, --file=/x, of=/x, --target-directory=/x)."""
    out = {tok}
    if "=" in tok:
        out.add(tok.split("=", 1)[1])
    if tok.startswith("-"):
        for ch in ("/", "~"):
            k = tok.find(ch)
            if k > 0:
                out.add(tok[k:])
    return [c for c in out if c]


def path_check(tok: str, cwd: Path, sandbox):
    """Any token (or embedded path-ish substring) resolving under the live apex — or any alias mount of it —
    but outside the sandbox is a live-tree reference → block. Globs are expanded (fail closed when the literal
    prefix could reach the apex); Windows drive paths and .exe interop are blocked outright."""
    if WINPATH_RE.match(tok) or WINPATH_RE.match(tok.split("=", 1)[-1]):
        block(f"'{tok}' is a Windows path — no interop from the sandbox")
    if _mentions_live_tree(tok, sandbox):
        block(f"'{tok[:80]}' mentions the LIVE tree — the sandbox worker may only touch its own worktree")
    if re.match(r"^\$\{?[A-Za-z_]", tok) and ("/" in tok or ".." in tok) or re.search(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/?\.\.", tok):
        block(f"'{tok[:80]}' is a path rooted in a shell variable — the guard cannot resolve it (write the literal path)")
    if "\\" in tok and re.search(r"[A-Za-z]:\\", tok):
        block(f"'{tok}' contains a Windows drive path")
    for t in _candidates(tok):
        if t.startswith("~"):
            t = os.path.expanduser(t)
        if not t or not ("/" in t or t in (".", "..") or any(c in t for c in GLOB_CHARS)):
            continue
        if any(c in t for c in GLOB_CHARS):
            _glob_check(t, cwd, sandbox, tok)
            continue
        try:
            p = Path(t) if os.path.isabs(t) else (cwd / t)
            rp = Path(os.path.normpath(str(p)))
        except (ValueError, OSError):
            continue
        if _in_apex_not_sandbox(rp, sandbox):
            block(f"'{tok}' resolves to the LIVE tree ({rp}) — the sandbox worker may only touch its own worktree")
        try:
            real = Path(os.path.realpath(str(rp)))
            if real != rp and _in_apex_not_sandbox(real, sandbox):
                block(f"'{tok}' resolves (via symlink) to the LIVE tree ({real})")
        except OSError:
            pass


def _glob_check(t: str, cwd: Path, sandbox, tok: str):
    first = min((t.find(c) for c in GLOB_CHARS if c in t), default=len(t))
    literal = t[:first]
    base = Path(literal) if os.path.isabs(literal) else (cwd / literal)
    basen = Path(os.path.normpath(str(base)))
    if sandbox is not None and _under(basen, sandbox):
        # a glob rooted inside the sandbox cannot climb out (globs never traverse '..'); only the secret check applies
        for m in globmod.glob(str(base) + t[first:]):
            if SECRET_RE.search(m):
                block(f"glob '{tok}' expands to a credential file ({m})")
        return
    # could this pattern reach the apex? (its literal prefix is a prefix of an apex root, or lies inside one)
    reach = any(str(root).startswith(str(basen).rstrip("/")) or _under(basen, root) for root in APEX_ROOTS)
    reach = reach or literal in ("", "/", "/mnt", "/mnt/") or basen == Path("/") or str(basen).startswith("/mnt")
    if not reach:
        # outside the apex entirely — still expand for the secret check
        for m in globmod.glob(str(base) + t[first:]) if os.path.isabs(t) else globmod.glob(str(cwd / t)):
            if SECRET_RE.search(m):
                block(f"glob '{tok}' expands to a credential file ({m})")
        return
    pattern = str(base) + t[first:]
    matches = globmod.glob(pattern)
    if not matches:
        block(f"glob '{tok}' could reach the live tree and matches nothing — refusing (fail closed)")
    for m in matches:
        rp = Path(os.path.normpath(m))
        if _in_apex_not_sandbox(rp, sandbox):
            block(f"glob '{tok}' expands into the LIVE tree ({rp})")
        if SECRET_RE.search(m):
            block(f"glob '{tok}' expands to a credential file ({m})")


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
    # exec-capable options of otherwise-allowed subcommands (rebase -x, bisect run, difftool/mergetool, add -p, …)
    if sub == "rebase" and any(t in ("-x", "--exec", "-i", "--interactive") or t.startswith("--exec=") for t in rest):
        block("git rebase -x/-i: shells out — not allowed in the sandbox")
    if sub == "bisect" and rest[:1] == ["run"]:
        block("git bisect run: shells out — not allowed in the sandbox")
    if sub in ("difftool", "mergetool"):
        block(f"git {sub}: shells out — not allowed in the sandbox")
    if sub == "help" and any(t in ("-w", "--web") for t in rest):
        block("git help --web: not allowed in the sandbox")
    if sub in ("cherry-pick", "revert", "am", "rebase") and any(t in ("-e", "--edit", "-i", "--interactive") for t in rest):
        block(f"git {sub} -e/-i: editor forms are not allowed in the sandbox")
    if any(t in ("-p", "--patch", "-i", "--interactive", "-e", "--edit") for t in rest) and sub in ("add", "commit", "reset", "checkout", "stash", "restore"):
        block(f"git {sub} -p/-i/-e: interactive/editor forms are not allowed in the sandbox")
    if any(t.startswith("--config-env") or t.startswith("--exec-path") for t in rest):
        block("git --config-env/--exec-path are not allowed in the sandbox")
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
    if depth > 8 or not toks:
        return
    # shell keywords are transparent: `if …; then CMD`, `{ CMD; }`, `! CMD`, `for …; do CMD`
    while toks and toks[0] in SHELL_KEYWORDS:
        toks = toks[1:]
    toks = strip_env_assign(toks)
    if not toks:
        return
    exe_full = toks[0]
    exe = exe_full.rsplit("/", 1)[-1]
    if not exe.isascii():
        block(f"non-ASCII executable name {exe!r}")
    if exe.lower().endswith(".exe") or exe.lower() in ("cmd", "powershell", "pwsh", "wsl", "wslpath", "explorer"):
        block(f"'{exe}' — Windows interop is not allowed from the sandbox")
    args = toks[1:]
    if exe in ENV_MUTATORS:
        for a in args:
            name = a.split("=", 1)[0].lstrip("-")
            if PROTECTED_NAME_RE.match(name):
                block(f"{exe} {name}: protected environment variable")
        return
    for t in toks:
        if SECRET_RE.search(t):
            block(f"token '{t}' references credentials")
    # wrappers
    if exe in WRAPPERS_DROP1:
        rest = args
        if exe == "env":
            while rest and (rest[0].startswith("-") or "=" in rest[0]):
                if rest[0] in ("-i", "--ignore-environment", "-", "-S", "--split-string", "-C", "--chdir"):
                    block(f"env {rest[0]}: not allowed in the sandbox")
                if rest[0] in ("-u", "--unset") and len(rest) > 1 and PROTECTED_NAME_RE.match(rest[1]):
                    block(f"env -u {rest[1]}: protected environment variable")
                if rest[0].startswith("-u") and len(rest[0]) > 2 and PROTECTED_NAME_RE.match(rest[0][2:]):
                    block(f"env {rest[0]}: protected environment variable")
                if rest[0].startswith("--unset=") and PROTECTED_NAME_RE.match(rest[0].split("=", 1)[1]):
                    block(f"{rest[0]}: protected environment variable")
                if "=" in rest[0] and ENV_ASSIGN_RE.match(rest[0]):
                    block(f"env override '{rest[0]}' is not allowed")
                rest = rest[1:] if rest[0] not in ("-u", "--unset") else rest[2:]
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
        # heuristic only (documented residual): any inline code mentioning git/gh/credentials/protected vars is refused
        for i, t in enumerate(args):
            if t in ("-c", "-e", "-E", "-m") and i + 1 < len(args):
                code = args[i + 1]
                if GITGH_RE.search(code) or SECRET_RE.search(code) or re.search(PROTECTED_VARS, code) or "subprocess" in code or "os.system" in code or "popen" in code.lower():
                    block(f"{exe} one-liner referencing git/gh/subprocess/credentials")
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


HEREDOC_RE = re.compile(r"(?P<line>[^\n]*?)<<-?\s*(?P<q>['\"]?)(?P<d>[A-Za-z_][A-Za-z0-9_]*)(?P=q)(?P<rest>[^\n]*)\n(?P<body>.*?)\n[ \t]*(?P=d)[ \t]*(?=\n|$)", re.S)
HEREDOC_EXEC = SHELLS | INTERPRETERS | {"eval", "source", ".", "xargs", "env", "exec", "command", "sudo", "builtin", "nohup", "setsid", "timeout"}


def strip_heredocs(cmd: str) -> str:
    """Here-document BODIES are data when they feed cat/tee/a file — drop those (the operator line, including any
    command chained on it, is kept intact). When the receiver is a shell/interpreter/eval, the body IS code:
    keep it so it gets tokenized and inspected like everything else (fail closed)."""
    def sub(m):
        line = m.group("line")
        try:
            toks = shlex.split(line)
        except ValueError:
            toks = line.split()
        while toks and (toks[0] in SHELL_KEYWORDS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0])):
            toks = toks[1:]
        exe = toks[0].rsplit("/", 1)[-1] if toks else ""
        head = line + "<<" + m.group("q") + m.group("d") + m.group("q") + m.group("rest") + "\n"
        body = m.group("body")
        if exe in INTERPRETERS:
            # the body is interpreter code: apply the one-liner rules, then drop it
            if GITGH_RE.search(body) or SECRET_RE.search(body) or re.search(PROTECTED_VARS, body) or "subprocess" in body or "os.system" in body or "popen" in body.lower():
                block(f"{exe} heredoc referencing git/gh/subprocess/credentials")
            for root in APEX_ROOTS:
                if str(root).lower() in body.lower():
                    block(f"{exe} heredoc mentions the LIVE tree")
            return head + m.group("d")
        piped = re.search(r"\|\s*(?:sudo\s+|env\s+|command\s+)?(?:bash|sh|zsh|dash|ksh|python3?|perl|node|ruby|eval|xargs|source)\b", line + m.group("rest"))
        if exe in HEREDOC_EXEC or piped or "$(" in line or "`" in line or "$(" in body or "`" in body:
            return head + body + "\n" + m.group("d")          # shell code (or expanded body): keep for inspection
        return head + m.group("d")
    return HEREDOC_RE.sub(sub, cmd)


def inspect_command(cmd: str, cwd: Path, sandbox, depth: int = 0):
    if depth > 6:
        return
    cmd = strip_heredocs(cmd)
    # command substitutions, backticks, process substitutions: inspect inner text as its own command
    for m in re.finditer(r"\$\((.*?)\)|`([^`]*)`|[<>]\((.*?)\)", cmd, re.S):
        inner = m.group(1) or m.group(2) or m.group(3) or ""
        if inner.strip():
            inspect_command(inner, cwd, sandbox, depth + 1)
    if re.search(r"\b(unset|export)\s+(-\w+\s+)*(?:" + PROTECTED_VARS.strip("()") + r")\b", cmd):
        block("unset/export of a protected environment variable")
    if SECRET_RE.search(cmd):
        block("command references credential files/variables")
    if re.search(r"(^|[\s'\"=])[A-Za-z]:[\\/](?![\\/])", cmd):
        block("Windows drive path in command — no interop from the sandbox")
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
