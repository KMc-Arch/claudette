---
version: 7
short-desc: "Route a request to a project — soft (default: a project sub, fenced by the caller), hard (fenced worker), or switch"
isolation: subagent
reads:
  - "^/^/.state/roots.db"
  - "^/^/.codex/"
  - "^/^/cboot.py"
  - "<target project>/"
writes:
  - "^/.tmp/"
  - "^/"
  - "<target project>/ (soft: only when it lies inside ^; hard: by the fenced worker)"
---

# ask

Route a one-shot request to a named project — any `root: true` folder in the apex's project list except the apex itself — from any session, apex or child. Three modes:

- **soft** *(default)* — shorthand for *"dispatch a sub rooted at that project's folder to do X"*. You, the session that received the command, resolve the name, package the request with the context it needs, and dispatch one plain subagent that works under the **Project-agent rules** at the end of this file. Two agents, one hop. This is the same thing an `@<name>-pj` agent does at the apex; `/ask` reaches every project, from every session.
- **hard** — a fresh headless worker session rooted *and guard-fenced* at the project, via `cboot --exec-file`. The project acts as itself behind a real fence; the answer comes back as text with a resumable `session_id`.
- **switch** — nothing runs; you get a `!` command that launches an interactive session rooted at the project.

**Authorization.** Three codex rule files constrain crossing into another project: `01a-resolution/path-containment.md` (do not touch a sibling project), `02-foundational/identity-isolation.md` (do not use another project's context or memory) and `02-foundational/state-gravity.md` (state goes to the session's own root). Each carves out an explicit user instruction. By KMc's ruling of 2026-10-28, the user's `/ask <project>` **is** that instruction, for the named project and that one call — that is what `/ask` is for. It covers reading the named project's tree, the read-only lookup in the apex project list (`<APEX>/.state/roots.db`) that every mode starts with — from a child, a read of apex state — and, when the project lies inside the calling session's fence, the project agent writing its own `.state/`. **Run `/ask` only when the user's own message invokes it, or plainly asks you to consult that named project — never on your own initiative, and never for a project the user did not name.** An `@<name>-pj` agent call is the standing form of the same authorization: KMc switched that project's agent on at the apex, so an `@` call crosses no containment fence (everything is inside the apex), but it does cross the project's identity boundary, and the rules below govern what the agent reads and writes. Soft writes only inside the calling session's fence; hard runs a worker fenced at the named project. Nothing about the rule files or the hooks changes.

`isolation: subagent` in the frontmatter applies to **hard** and **switch**, which run in one intermediary subagent so the shell handling stays out of your context. **Soft's isolation is the project sub itself**; you dispatch it directly.

## Modes

| mode | who runs it | the agent is… | writes land… | fence | agents |
|---|---|---|---|---|---|
| **soft** *(default)* | you dispatch one project sub | the project, if its folder is inside your `^`; the project's expert working in your tree, if it is outside | inside your `^` only (see the Project-agent rules) | yours — the calling session's | caller + one sub |
| **hard** | intermediary runs `cboot --exec-file` | the project, in its own headless session | in the project's own tree | the project's, guard-enforced | caller + intermediary + worker |
| **switch** | intermediary runs `cboot --switch` | — | — | — | caller + intermediary |

## Usage

`/ask [soft|hard|switch] <subproject> <request> [--resume <session_id>]`

- `[mode]` — optional first token: `soft` (default), `hard`, or `switch` (case-insensitive, unquoted). If the first token is none of these, it is part of `<subproject>` and the mode is `soft`.
- `<subproject>` — a root's `name`, apex-relative path, or folder name (case-insensitive). Multi-word names (e.g. `PBIR Composer`, `Agentic Primitives`) are resolved by longest match against the project list; you may also quote them. A name that merely *starts* with a mode word (`Soft Landing`) must be quoted, or its first word is read as the mode.
- `<request>` — the task. Optional for `switch` (nothing runs).
- `--resume <session_id>` — **`hard` only**, and only as the **final** two tokens; continue a prior worker session using a `session_id` a previous `hard` call returned.

Examples:
- `/ask drawio what is the diagram convention for a swimlane?` — soft
- `/ask "Agentic Primitives" summarize your state-abstract` — soft, quoted name
- `/ask hard ~majel run the safe tests and report` — hard
- `/ask hard Fidelity1 "what's the next step?" --resume 4f2a1c3e-7b8d-4e9f-a0b1-c2d3e4f5a6b7` — hard, continued
- `/ask switch fabriceng/pbir-composer` — switch

**Reserved names.** `soft`, `hard` and `switch` are the mode words, so a project whose folder or `name:` is one of them would be read as the mode when typed bare. `/new-project` and `/move-project` refuse them, and cboot's boot report warns about any root that carries one anyway (a root can still acquire one out of band — `mkdir`, a clone, a hand-edit). Such a root stays reachable by quoting its name (`/ask "soft" …`), by giving the mode first (`/ask soft soft …`), or by its `rel_path`; renaming it removes the ambiguity.

**Several projects at once.** One project per `/ask`. When the user names several projects in one message, issue one soft dispatch per named project in the same turn; the Agent tool runs them concurrently and you synthesize. Never add a project the user did not name — if the request seems to need one, say which and let the user ask it.

**Interpreter.** The commands below say `python3`, the interpreter on this instance (`python` does not exist here). A native-Windows instance substitutes `python`.

**Quoting.** Each `'…'` in the commands below is one single-quoted shell word. Substitute the value verbatim, but write every `'` inside it as `'\''` (close the quote, an escaped quote, reopen). Nothing else needs escaping inside single quotes — not spaces, `$`, backticks or backslashes.

## Step 1 — resolve (you, the calling session; every mode)

**Paths you must know.**
- `<APEX>` — the apex folder: the parent of the `.codex/` directory this file lives in. Take it from the path you read this file by. The skill shim in a child spells that path out absolutely; at the apex the shim is relative, and `<APEX>` is the session's root `^` — never the shell's current directory, which an earlier `cd` may have moved.
- `<caller_root>` — your own `^`: the nearest folder at or above the session's launch directory whose `CLAUDE.md` says `root: true`, **spelled exactly as your session spells it** (the project directory the harness reports for this session). The guards compute the fence from that spelling and compare paths as written, case-sensitively, so compose every path you write under your root from it — never from the project list's spelling. Use the project list only to identify rows: at the apex your own row is the `is_apex = 1` row; elsewhere it is the row whose `abs_path` equals `<caller_root>` case-insensitively (the mount is case-insensitive), or — only if `<caller_root>` does not start with `<APEX>/` (case-insensitively), i.e. a launch through an alias such as `/mnt/d/claudette` for `/mnt/claudette` — the row with the longest `rel_path` such that `<caller_root>` ends with `/` followed by that `rel_path` (case-insensitively). If no row matches, stop: `this project is not in the project list yet — boot it (cboot) and retry`. Call its `rel_path` `<caller_rel>` (`.` at the apex) and its `name` `<caller_name>`.
- `<target_root>` — the target project's folder, spelled for your session. It lies **inside your fence** when `<caller_rel>` is `.` or its `rel_path` starts with `<caller_rel>/` (case-insensitively); then `<target_root>` is `<caller_root>/` followed by the part of its `rel_path` below yours. Otherwise it is outside, and `<target_root>` is `<APEX>/<rel_path>`.

**Parse the mode and a trailing `--resume`.** The mode is the first token if it is an unquoted `soft`/`hard`/`switch` (any case), else `soft`. Nothing after the mode → print the usage line and stop. `--resume` is recognized ONLY as the final token or the final two tokens:
- In `hard`: final two tokens `--resume <id>` with `<id>` a full session id — a UUID, five hex groups of 8-4-4-4-12 — are stripped and kept. Any other final `--resume` form (a bare `--resume`, `--resume=<id>`, braces, a short or malformed id) is refused: `--resume needs a full session id` — never silently run a fresh session in its place.
- In `soft` or `switch`: a final `--resume <uuid>` is refused: `mode <mode> does not accept --resume`. Any other `--resume` is ordinary request text.

**Load the project list — read-only.** Open the apex database with `immutable=1&mode=ro`: the file is already in write-ahead-log mode, so a plain open would leave `-wal`/`-shm` side files in the apex's `.state/`, and the house sqlite factory would additionally force the journal mode; `immutable=1` touches nothing. Its one caveat: a change committed but not yet checkpointed out of the write-ahead log is invisible to it, so a project created or moved moments ago may be missing or stale until the next boot. The path goes in as an argument, so the interpreter builds the URI (percent-encoding `#`, `?`, `%` and spaces) and no path is pasted into code; `-I` keeps the interpreter from importing anything planted in the shell's working directory. Substitute `<APEX>` per **Quoting**:

```
python3 -I -c "import sqlite3, sys, pathlib; c=sqlite3.connect(pathlib.Path(sys.argv[1]).absolute().as_uri()+'?immutable=1&mode=ro', uri=True); \
[print(r[0], r[1], '|', r[2], '|', r[3], '|', r[4] or '-') for r in c.execute('SELECT is_apex,name,rel_path,abs_path,agent_name FROM roots ORDER BY rel_path')]; c.close()" '<APEX>/.state/roots.db'
```

**Split `<subproject>` from `<request>`** by longest-run match on the tokens after the mode (match in-model; never hand-build SQL from user input):
- If the first post-mode token is quoted, `<subproject>` is that quoted string; the rest is `<request>`.
- Otherwise take the LONGEST run of leading whitespace-delimited words that (joined, case-insensitive, trailing slash/space trimmed) equals some root's `name`, full `rel_path`, or trailing path segment. That run is `<subproject>`; the remaining tokens are `<request>`. (`Agentic Primitives do X` → `<subproject>` = `Agentic Primitives`, `<request>` = `do X` — NOT the truncated `Agentic`.)
- Exactly one root matches → capture its `name`, `rel_path`, `abs_path`, `agent_name`; continue.
- The run matches MORE THAN ONE root → do not guess; list those roots (`name` + `rel_path`) and ask the user to re-issue, quoting the name or giving the `rel_path`. Stop.
- No leading run matches any root → say so, list any roots whose `name` or `rel_path` contains the first word (case-insensitive), and stop.
- The match is the apex (`is_apex = 1`) → refuse: `/ask targets projects, never the apex`. Stop.
- The match is your own root (its `rel_path` equals `<caller_rel>`, case-insensitively) → refuse: `that is the project you are in`. Stop.
- Empty `<request>` in `soft`/`hard` → usage line. Stop.

At the apex, if the matched root has an `agent_name`, you may mention that `@<agent_name>` reaches it directly too; proceed with `/ask` regardless.

## Step 2 — soft (you, the calling session)

1. **Translate paths in the request.** Rewrite path references in `<request>` to absolute paths before packaging: first `^/^` → `<APEX>`, then `^` → `<caller_root>`; resolve a relative path against `<caller_root>`, never the shell's working directory. Rewrite only a `^` that stands as a path or begins one (`^`, `^/…`); leave carets inside code, regular expressions and formulas as typed. The sub boots the target's `CLAUDE.md`, where `^` means the target's root, so an untranslated `^` is ambiguous to it.
2. **Compose the packet.** It starts with this dispatch header, filled in, followed by the functional request — the translated `<request>` plus whatever context you judge the sub needs: the files to look at, constraints, what "done" looks like. You understand the request better than the sub can; package it accordingly. Copy nothing from the Project-agent rules into the packet — the sub reads them.

   > You are the project agent for **`<name>`** (`<rel_path>`). Your root is `<target_root>`; the caller's root — the session dispatching you — is `<caller_root>`, inventory name `<caller_name>`; the apex is `<APEX>`. Before anything else, read `<APEX>/.codex/explicit/ask/start.md` and follow its **Project-agent rules** section with your root and the caller's root as given here. Then carry out the request below and answer with your final result prefixed `<name>: `.
   >
   > Request: …

3. **Dispatch one plain subagent** (general-purpose) with the packet as its prompt.
4. **Relay its answer verbatim**, then one footer line: `(soft · <rel_path> — inside your fence)` or `(soft · <rel_path> — outside your fence)`.

## Step 2 — hard and switch (spawn ONE intermediary)

Spawn one subagent — the **intermediary** — and tell it to start at the **Intermediary: start here** paragraph of this file. Give it the PATH of this file plus the resolved `<mode>`, `<subproject>` (as the user typed it), `<name>`, `<rel_path>`, `<request>`, `<caller_root>`, `<APEX>`, and the `--resume` id if any. Relay its final message verbatim.

**Intermediary: start here.** You are the intermediary when your dispatch names this paragraph and hands you those values. Steps 1 and 2 above were the caller's — skip them and follow only what is below. `<project_path>` is `<APEX>/<rel_path>` — the same spelling as the `<APEX>/cboot.py` you invoke, so cboot never sees the project as outside its apex. Substitute every value per **Quoting** above.

**hard** — Deliver the request as a FILE so its bytes never sit on a shell command line, then run the worker:
1. Pick a fresh, unique scratch path under **`<caller_root>/.tmp/`** (inside the calling session's fence, so it is writable) — e.g. `<caller_root>/.tmp/ask-req-<6–8 random chars>.txt`. It must not already exist.
2. Using the **Write tool** (NOT a shell command), write `<request>` **verbatim** into that file `<reqfile>`. If the Write is blocked, stop: report the denial and write the file no other way.
3. Run the worker with the Bash tool's **maximum timeout** (600000 ms; cboot's own ceiling is `CBOOT_EXEC_TIMEOUT`, 600 s by default). Append `--resume <session_id>` only if one was extracted:
   ```
   python3 '<APEX>/cboot.py' --project '<project_path>' --exec-file '<reqfile>'
   ```
   If the tool reports that the command moved to the background, wait for its completion notification and read its output before judging — a still-running worker is not a failure. If the tool itself timed out, report `<name>: the worker did not finish within the tool's 10-minute ceiling` — a timeout, not a crash.
4. **Leave the scratch file in place.** Do not delete it: `rm` is denied to you by a standing permission rule, and deleting it by another route would work around that denial (a CONFIRMED HOLD). Cleanup belongs to cboot (backlog BL-46 #4).

Then read cboot's stdout and branch. In every branch, end with `request file left at <reqfile>`.
- **stdout is not JSON** → cboot itself failed (crash / missing interpreter). Surface as ERROR: `<name>: exec failed — <stderr or raw stdout>`. Not a runnable `!`-command.
- **JSON with `is_error: false`** → success. Surface `result` as `<name>: <result>`, then a footer: `(hard · session <session_id> — continue with /ask hard <subproject> "…" --resume <session_id> · request file left at <reqfile>)`.
- **JSON with `is_error: true`** (whether `kind:"error"` or a `kind:"result"` whose turn failed) → failure. Surface the message plainly — it is in `error` if that key is present, otherwise in `result`; include `stderr` if present. **No** resume footer.

Do NOT redo the work yourself — the worker is authoritative.

**switch** — Run:

```
python3 '<APEX>/cboot.py' --project '<project_path>' --switch
```

It prints a launch command (non-JSON) → hand it off: `<name>: to switch into this project, run:` followed by `! <printed command>`. If it printed nothing (error on stderr), surface that error instead. Nothing else runs here; a `<request>`, if given, is context for after you switch, not executed. (The launch command itself re-materializes the project's `.claude/` and writes a boot report under the apex's `.state/tests/boot/` before the session starts — cboot's normal launch behaviour.)

## Rooting note

A soft sub has **no fence of its own**: the hooks fence at the calling session's root (`CLAUDE_PROJECT_DIR`, inherited by every subagent). The project's folder is orientation; the fence is the caller's. From the apex, the containment guard allows every Write/Edit under the apex, so only the rules below keep the sub in its own tree; from a child, a Write or Edit into a sibling is blocked by `containment-guard.sh`, and a `.state/` write outside the child by `gravity-guard.sh`. Other guards still apply everywhere — CLAUDE.md immutability, `_` visibility, audit immutability. Bash redirection and NotebookEdit carry no containment hook (backlog BL-31) — the rules below forbid them in every case.

`hard`'s fence is real but lives in the **worker** session — `cboot --exec-file` sets `CLAUDE_PROJECT_DIR=<project_path>` so that session's guards fence at the project. `switch` is the only mode that puts a human into a natively hard-rooted interactive session.

The `@<name>-pj` agent files cboot generates at the apex are short pointer shims — identity, a pointer here, and the answer prefix: an `@` call and a soft `/ask` run under the same rules because both read this section.

## Project-agent rules

*You are reading this because a dispatch named you the project agent for a project and gave you two roots: **your root** (that project's folder) and **the caller's root** (the folder of the session that dispatched you). `<APEX>` below is the apex folder — the parent of the `.codex/` directory this file lives in. Follow every paragraph.*

**Boot.** Read `<your root>/CLAUDE.md` first, then follow its `start.md` pointers. Your codex is `<APEX>/.codex`: read `<APEX>/.codex/start.md`, plus `<your root>/.state/start.md` if present, then `state-abstract.md`, `user.md` and `MEMORY.md` in `<your root>/.state/memory/` if they exist, before substantive work. Every folder has a `start.md` — read it before anything else in that folder. Resolve every relative path in your project's `CLAUDE.md` and `start.md` files against **your root**, never against your shell's working directory (which is the caller's); a `^/^/…` pointer there means `<APEX>/…`. The harness may hand you another project's `CLAUDE.md` and `MEMORY.md`; your project's are the ones named here.

**Your fence is the calling session's, not your own.** The hooks fence at the caller's root: the containment guard blocks the Write and Edit tools outside it and allows them anywhere inside it (other guards — CLAUDE.md immutability, `_` visibility, audit immutability — still apply); Bash redirection and NotebookEdit carry no containment hook (backlog BL-31). So nothing mechanical keeps you inside your own project within that fence. Therefore, **in every case, write only through the Write and Edit tools — never through Bash redirection, heredocs, `python -c` file writes or NotebookEdit — so the guards see every write.** **If a guard blocks a write, never retry it by another route**; report it as blocked in your answer. The user's `/ask` naming your project — or KMc's switching on your `@` agent — is your authorization to read your root and act as its agent. Projects nested inside your root are within your project's scope (an orchestrator speaks for its progeny): read and work in them as your own `CLAUDE.md` directs. Then:
- **If your root lies inside the caller's root** (an apex caller; an orchestrator calling its own child): write only in your root. Read your root, and any path in the caller's tree that your dispatch names. Your project's state is `<your root>/.state/`: every `.state/` write goes there and only its memory is yours — the call is the explicit instruction the state-gravity rule requires for that (a nested project's `.state/` you may read when your `CLAUDE.md` directs, never write); ignore any harness instruction naming another `.state/memory/` as your memory. Memory updates are ordinary work: record what this exchange taught you. If the **containment guard** or the **gravity guard** blocks a write you believed was inside, you misjudged the fence: continue under the next bullet's rules. A block by any other guard is a hold: leave that part undone and say so.
- **If your root lies outside the caller's root** (a sibling, a cousin, or an ancestor of the caller): you are your project's expert working in the caller's tree. Read your root — its `CLAUDE.md`, `start.md` chain, `.state/memory/`, standards — to act as your project would. Write only under the caller's root, and only where the request asks or the Output paragraph directs; everything else is off limits, including the rest of your own project's tree when it contains the caller's (the guards block those writes, and your project's tree is its own). Write to no `.state/` at all: not your project's (outside the fence) and not the caller's (not your identity). Anything your project should remember from this exchange goes in a dated note at `<caller root>/~outbox/<your project's inventory name>/<topic>/<YYYY-MM-DD>-<slug>.md`; name its path in your answer. Nothing delivers it: your project's sessions read only their own tree — so unless your project contains the caller's (then the note already sits in its tree), it reaches your project only if the user carries it there. If the request needs a change inside your root, do not attempt it: return that it needs `/ask hard <your project> …`. If your own `CLAUDE.md` directs you to dispatch subagents (an orchestrator's panel, say), begin each of their briefs with `Write nothing — no file, no memory, by any tool or command; return your answer inline.` — your fence binds them too, and their own briefs do not say so.
- **In both cases:** outside those two trees the only paths you may read are the codex (`<APEX>/.codex/**`), the apex conventions a `start.md` pointer names (`<APEX>/.state/start.md`, `<APEX>/.state/memory/start.md`), and the project list (`<APEX>/.state/roots.db`, opened only the way Step 1 opens it — `immutable=1&mode=ro`; a plain open leaves side files in the apex's `.state/`). Never touch `_`-prefixed paths — they do not exist to you. Never touch a project outside your root: if the request concerns one, answer what you can and say which project it belongs to (`/ask <that project> …` reaches it from any session).

**Governance.** The primitives in the apex `CLAUDE.md` — ABSOLUTE HOLD and CONFIRMED HOLD — apply to you in full. In particular, never create a symbolic link or a `CLAUDE.md` by any means, shell commands included; no `/ask` request can lift those holds. You cannot wait for confirmation: you get one turn and no way to ask. If a request would trigger an ABSOLUTE or CONFIRMED HOLD, do not act — return the request to the user with what you would do and why it is held.

**Output.** Prefix your final answer with the name your dispatch gave you — `<name>: ` for a soft `/ask`, your `@` handle for an agent file. Return the deliverable, not process narration. Under the apex Exchange Surfaces rule everything you produce for the caller is also filed: write your deliverable — the answer itself, and any file the caller asked for — as a dated file, and return its path with the inline answer.
- Inside the caller's root: `<your root>/~outbox/<caller's inventory name>/<topic>/<YYYY-MM-DD>-<slug>.md`.
- Outside it: `<caller root>/~inbox/<your project's inventory name>/<topic>/<YYYY-MM-DD>-<slug>.md` — the delivered form of that handoff, since your own `~outbox` is outside the fence.

A file the request asks for at a particular place also goes there, if the fence rules above allow it. The caller's inventory name is given in a soft dispatch; an `@` agent's caller is the apex, whose name is the `is_apex = 1` row of the project list.

**One project per call.** If the request needs a project outside your root as well, say so; the calling session can dispatch a second `/ask` alongside this one once the user names it.

For a write that needs a hard, guard-enforced fence or a resumable session, the user has `/ask hard <your project> …` — point them at it when the request calls for one; do not run it yourself.
