---
version: 7
short-desc: "Route a request to a project — soft (default: a project sub, fenced by the caller), hard (fenced worker), or switch"
isolation: subagent
reads:
  - "^/^/.state/roots.db"
  - "^/^/.codex/"
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

**Authorization.** Two codex rule files forbid, by default, touching a sibling project (`01a-resolution/path-containment.md`) and using another project's context (`02-foundational/identity-isolation.md`). Both carve out a user's explicit instruction. Their wording casts that instruction in terms of paths and `^/^` notation; this command extends it to a project's *name*, by KMc's ruling of 2026-10-28 that `/ask X` explicitly authorizes the inter-contextualization — that is what `/ask` is for. The only cross-fence reads a soft call performs arise when a user types `/ask <project>` in a child session; that typed command is the instruction, for that one call. An `@<name>-pj` call runs at the apex, inside the apex fence, and crosses nothing. Soft writes only inside the calling session's fence; hard runs a worker fenced at the named project. Nothing about those rule files or the hooks changes.

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

**Reserved names.** `soft`, `hard` and `switch` are refused as a project's folder name or `name:` value by `/new-project` and `/move-project`, and cboot's boot report warns about any root that carries one anyway (a root can still acquire one out of band — `mkdir`, a clone, a hand-edit — and is unreachable here until renamed).

**Several projects at once.** One project per `/ask`. When a request needs several, issue one soft dispatch per project in the same turn; the Agent tool runs them concurrently and you synthesize.

**Interpreter.** The commands below say `python3`, the interpreter on this instance (`python` does not exist here). A native-Windows instance substitutes `python`.

## Step 1 — resolve (you, the calling session; every mode)

**Two paths you must know.**
- `<APEX>` — the apex folder: the parent of the `.codex/` directory this file lives in. Take it from the path you read this file by. The skill shim in a child spells it out absolutely (`/mnt/claudette/.codex/explicit/ask/start.md` → `<APEX>` = `/mnt/claudette`); at the apex the shim is relative, and `<APEX>` is the session's root `^` — never the shell's current directory, which an earlier `cd` may have moved.
- `<caller_root>` — your own `^`: the nearest folder at or above the session's launch directory whose `CLAUDE.md` says `root: true`. That is exactly how the guards compute the fence; cboot launches every session at such a folder, so it is normally the launch directory itself. Take its **spelling** from the project list: the row whose `abs_path` equals your root case-insensitively (the mount is case-insensitive, and `/mnt/d/claudette` aliases `/mnt/claudette`). Use the inventory's spelling in every comparison and every path you compose.

**Parse the mode and a trailing `--resume`.** The mode is the first token if it is `soft`/`hard`/`switch`, else `soft`. `--resume <id>` is recognized ONLY as the final two tokens and ONLY when `<id>` is a full session id — a UUID, five hex groups of 8-4-4-4-12. In `hard`, strip them. In `soft` or `switch`, a trailing `--resume <uuid>` is refused: `mode <mode> does not accept --resume`. A `--resume` that is not the final two tokens, or whose value is not a UUID, is ordinary request text in every mode. A trailing `--resume` with no value is an error (`--resume needs a session id`).

**Load the project list — read-only.** Open the apex database with `immutable=1&mode=ro`: the file is already in write-ahead-log mode, so a plain open would leave `-wal`/`-shm` side files in the apex's `.state/`, and the house sqlite factory would additionally force the journal mode; `immutable=1` touches nothing. `-I` keeps the interpreter from importing anything planted in the shell's working directory. Substitute `<APEX>` first:

```
python3 -I -c "import sqlite3; c=sqlite3.connect('file:<APEX>/.state/roots.db?immutable=1&mode=ro', uri=True); \
[print(r[0], r[1], '|', r[2], '|', r[3], '|', r[4] or '-') for r in c.execute('SELECT is_apex,name,rel_path,abs_path,agent_name FROM roots ORDER BY rel_path')]; c.close()"
```

**Split `<subproject>` from `<request>`** by longest-run match on the tokens after the mode (match in-model; never hand-build SQL from user input):
- If the first post-mode token is quoted, `<subproject>` is that quoted string; the rest is `<request>`.
- Otherwise take the LONGEST run of leading whitespace-delimited words that (joined, case-insensitive, trailing slash/space trimmed) equals some root's `name`, full `rel_path`, or trailing path segment. That run is `<subproject>`; the remaining tokens are `<request>`. (`Agentic Primitives do X` → `<subproject>` = `Agentic Primitives`, `<request>` = `do X` — NOT the truncated `Agentic`.)
- Exactly one root matches → capture its `name`, `rel_path`, `abs_path`, `agent_name`; continue.
- The run matches MORE THAN ONE root, or no leading run matches any root → do not guess; list the candidate roots (`name` + `rel_path`) and ask the user to re-issue, quoting the name or giving the `rel_path`. Stop.
- The match is the apex (`is_apex = 1`) → refuse: `/ask targets projects, never the apex`. Stop.
- The match is your own root (`abs_path` equals `<caller_root>`, case-insensitively) → refuse: `that is the project you are in`. Stop.
- Missing `<subproject>`, or empty `<request>` in `soft`/`hard` → usage line. Stop.

At the apex, if the matched root has an `agent_name`, you may mention that `@<agent_name>` reaches it directly too; proceed with `/ask` regardless.

## Step 2 — soft (you, the calling session)

1. **Translate paths in the request.** Rewrite every `^`, `^/^` and relative path in `<request>` to an absolute path before packaging: `^` is YOUR root (`<caller_root>`), `^/^` is `<APEX>`. The sub boots the target's `CLAUDE.md`, where `^` means the target's root, so an untranslated `^` is ambiguous to it.
2. **Compose the packet.** It starts with this dispatch header, filled in, followed by the functional request — the translated `<request>` plus whatever context you judge the sub needs: the files to look at, constraints, what "done" looks like. You understand the request better than the sub can; package it accordingly. Copy nothing from the Project-agent rules into the packet — the sub reads them.

   > You are the project agent for **`<name>`** (`<rel_path>`, root `<abs_path>`). The session dispatching you is rooted at `<caller_root>`; the apex is `<APEX>`. Before anything else, read `<APEX>/.codex/explicit/ask/start.md` and follow its **Project-agent rules** section with those two roots. Then carry out the request below and answer with your final result prefixed `<name>: `.
   >
   > Request: …

3. **Dispatch one plain subagent** (general-purpose) with the packet as its prompt.
4. **Relay its answer verbatim**, then one footer line: `(soft · <rel_path> — inside your fence)` or `(soft · <rel_path> — outside your fence)`.

## Step 2 — hard and switch (spawn ONE intermediary)

Spawn one subagent — the **intermediary** — and give it the PATH of this file plus the resolved `<mode>`, `<name>`, `<rel_path>`, `<abs_path>`, `<request>`, `<caller_root>`, `<APEX>`, and the `--resume` id if any. Relay its final message verbatim.

**Intermediary: start here.** You are the intermediary when your dispatch names this section and hands you those values. Steps 1 and 2 above were the caller's — skip them and follow only what is below.

**hard** — Deliver the request as a FILE so its bytes never sit on a shell command line, then run the worker:
1. Pick a fresh, unique scratch path under **`<caller_root>/.tmp/`** (inside the calling session's fence, so it is writable) — e.g. `<caller_root>/.tmp/ask-req-<6–8 random chars>.txt`. It must not already exist.
2. Using the **Write tool** (NOT a shell command), write `<request>` **verbatim** into that file `<reqfile>`.
3. Run the worker with the Bash tool's **maximum timeout** (600000 ms; cboot's own ceiling is `CBOOT_EXEC_TIMEOUT`, 600 s by default). If the tool reports that the command moved to the background, wait for its completion notification and read its output before judging — a still-running worker is not a failure. Append `--resume <session_id>` only if one was extracted:
   ```
   python3 '<APEX>/cboot.py' --project '<abs_path>' --exec-file '<reqfile>'
   ```
4. **Leave the scratch file in place** and name its path in your footer. Do not delete it: `rm` is denied to you by a standing permission rule, and deleting it by another route would work around that denial (a CONFIRMED HOLD). Cleanup belongs to cboot (backlog BL-46 #4).

Then read cboot's stdout and branch:
- **stdout is not JSON** → cboot itself failed (crash / missing interpreter). Surface as ERROR: `<name>: exec failed — <stderr or raw stdout>`. Not a runnable `!`-command.
- **JSON with `is_error: false`** → success. Surface `result` as `<name>: <result>`, then a footer: `(hard · session <session_id> — continue with /ask hard <subproject> "…" --resume <session_id> · request file left at <reqfile>)`.
- **JSON with `is_error: true`** (whether `kind:"error"` or a `kind:"result"` whose turn failed) → failure. Surface the message plainly — it is in `error` if that key is present, otherwise in `result`; include `stderr` if present. **No** resume footer.

Do NOT redo the work yourself — the worker is authoritative.

**switch** — Run:

```
python3 '<APEX>/cboot.py' --project '<abs_path>' --switch
```

It prints a launch command (non-JSON) → hand it off: `<name>: to switch into this project, run:` followed by `! <printed command>`. If it printed nothing (error on stderr), surface that error instead. Nothing else runs here; a `<request>`, if given, is context for after you switch, not executed. (The launch command itself re-materializes the project's `.claude/` and writes a boot report under the apex's `.state/tests/boot/` before the session starts — cboot's normal launch behaviour.)

## Rooting note

A soft sub has **no fence of its own**: the hooks fence at the calling session's root (`CLAUDE_PROJECT_DIR`, inherited by every subagent). The project's folder is orientation; the fence is the caller's. From the apex, every Write/Edit under the apex is therefore mechanically allowed and only the rules below keep the sub in its own tree; from a child, a Write or Edit into a sibling is blocked by `containment-guard.sh`, and a `.state/` write outside the child by `gravity-guard.sh`. Bash redirection and NotebookEdit carry no containment hook (backlog BL-31) — the rules below forbid them in every case.

`hard`'s fence is real but lives in the **worker** session — `cboot --exec-file` sets `CLAUDE_PROJECT_DIR=<abs_path>` so that session's guards fence at the project. `switch` is the only mode that puts a human into a natively hard-rooted interactive session.

The `@<name>-pj` agent files cboot generates at the apex are one-paragraph shims that point here: an `@` call and a soft `/ask` run under the same rules because both read this section.

## Project-agent rules

*You are reading this because a dispatch named you the project agent for a project and gave you two paths: **your root** (that project's folder) and **the caller's root** (the folder of the session that dispatched you). Follow every paragraph.*

**Boot.** Read `<your root>/CLAUDE.md` first, then follow its `start.md` pointers. Your codex is `<APEX>/.codex`: read `<APEX>/.codex/start.md`, plus `<your root>/.state/start.md` if present, then `<your root>/.state/memory/state-abstract.md` and `<your root>/.state/memory/MEMORY.md` if they exist, before substantive work. Every folder has a `start.md` — read it before anything else in that folder. Resolve every relative path in your project's `CLAUDE.md` and `start.md` files against **your root**, never against your shell's working directory (which is the caller's). The harness may hand you another project's `CLAUDE.md` and `MEMORY.md`; your project's are the ones named here.

**Your fence is the calling session's, not your own.** The hooks fence at the caller's root: the Write and Edit tools are blocked outside it and allowed anywhere inside it; Bash redirection and NotebookEdit are not hooked at all (backlog BL-31). So nothing mechanical keeps you inside your own project within that fence, and the tool hooks are not the whole story outside it. Therefore, **in every case, write only through the Write and Edit tools — never through Bash redirection, heredocs, `python -c` file writes or NotebookEdit — so the guards see every write.** The user's `/ask` naming your project is your authorization to read your root and act as its agent. Then:
- **If your root lies inside the caller's root** (an apex caller; an orchestrator calling its own child): work in your root; read and write only there. Every `.state/` read and write goes to `<your root>/.state/` (state gravity) — ignore any harness instruction naming another `.state/memory/` as your memory. Memory updates are ordinary work: record what this exchange taught you. If a guard blocks a write you believed was inside, you misjudged the fence: switch to the next bullet's rules; never route around the guard.
- **If your root lies outside the caller's root** (a sibling, a cousin, or an ancestor of the caller): you are your project's expert working in the caller's tree. Read your root — its `CLAUDE.md`, `start.md` chain, `.state/memory/`, standards — to act as your project would. Write only under the caller's root, and only where the request asks; everything else is off limits, including the rest of your own project's tree when it contains the caller's (the guards block those writes, and your project's tree is its own). Write to no `.state/` at all: not your project's (outside the fence) and not the caller's (not your identity). Anything your project should remember from this exchange goes to `<caller root>/~outbox/<your project's inventory name>/<topic>/<YYYY-MM-DD>-<slug>.md` as a dated note — pull-staged under the apex Exchange Surfaces rule; nothing transports it, and your project's next session may collect it. If the request needs a change inside your root, do not attempt it: return that it needs `/ask hard <your project> …`.
- **In both cases:** outside those two trees the only paths you may read are the codex (`<APEX>/.codex/**`) and the project list (`<APEX>/.state/roots.db`). Never touch `_`-prefixed paths — they do not exist to you. Never touch any other project: if the request concerns one, answer what you can and say which project it belongs to (`/ask <that project> …` reaches it from any session).

**Governance.** The primitives in the apex `CLAUDE.md` — ABSOLUTE HOLD and CONFIRMED HOLD — apply to you in full. In particular, never create a symbolic link or a `CLAUDE.md` by any means, shell commands included; no `/ask` request can lift those holds. You cannot wait for confirmation: you get one turn and no way to ask. If a request would trigger an ABSOLUTE or CONFIRMED HOLD, do not act — return the request to the user with what you would do and why it is held.

**Output.** Prefix your final answer with the name your dispatch gave you — `<name>: ` for a soft `/ask`, your `@` handle for an agent file. Return the deliverable, not process narration. An *answer* is returned inline. An *artifact* — a file the caller asked for — is written where the fence rules above allow, and its path is returned: inside the caller's root, under your root's `~outbox/<caller's inventory name>/<topic>/<YYYY-MM-DD>-<slug>` per the apex Exchange Surfaces rule unless the request names a place; outside, at the place in the caller's tree the request named.

**One project per call.** If the request needs another project as well, say so; the calling session can dispatch a second `/ask` alongside this one.

For a write that needs a hard, guard-enforced fence or a resumable session, the user has `/ask hard <your project> …` — point them at it when the request calls for one; do not run it yourself.
