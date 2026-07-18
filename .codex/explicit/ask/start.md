---
version: 5
short-desc: "Route a request to a subproject — soft (default), hard, or switch"
isolation: subagent
reads:
  - "^/.state/roots.db"
  - "^/.codex/"
  - "^/<subproject>/"
writes:
  - "^/.tmp/"
  - "^/<subproject>/"
---

# ask

Route a one-shot request to a named subproject, in one of three modes. `/ask` runs as an isolated subagent — the **intermediary** — which resolves the subproject against the root inventory (`.state/roots.db`) and then either does the work itself, dispatches a hard-rooted worker, or hands you a session-switch command. The apex sees only the intermediary's final message.

## Modes

| mode | what runs | rooting | returns | agents |
|---|---|---|---|---|
| **soft** *(default)* | the intermediary does the work itself | soft (discipline) | the answer | caller + intermediary |
| **hard** | intermediary spawns a headless worker via `cboot --exec-file` | **hard** (guard-enforced) | the answer + resumable `session_id` | caller + intermediary + worker |
| **switch** | nothing — intermediary emits a launch command | — | a `!`-command for you to run | caller + intermediary |

## Usage

`/ask [mode] <subproject> <request> [--resume <session_id>]`

- `[mode]` — optional first token: `soft` (default), `hard`, or `switch`. If the first (unquoted) token isn't one of these three, it is taken as part of `<subproject>` and the mode is `soft`.
- `<subproject>` — a root's `name`, apex-relative path, or directory basename (case-insensitive). Multi-word names (e.g. `PBIR Composer`, `Agentic Primitives`) are resolved by longest match against the inventory; you may also quote them.
- `<request>` — the task. Optional for `switch` (nothing runs).
- `--resume <session_id>` — **`hard` only**, and only as the **final** two tokens; continue a prior worker session using a `session_id` a previous `hard` call returned.

Examples:
- `/ask AggregatorM what is the current backlog?` — soft
- `/ask hard majel run the safe tests and report` — hard
- `/ask hard "PBIR Composer" summarize the architecture` — hard, quoted name
- `/ask hard Fidelity1 "what's the next step?" --resume 4f2a…` — hard, continued
- `/ask switch fabriceng/pbir-composer` — switch

An empty `<subproject>`, or an empty `<request>` in soft/hard, is an error — refuse with the usage line.

## Dispatch (apex, on invocation)

`/ask` is `isolation: subagent`: the apex spawns ONE subagent (the intermediary) with this `start.md` as the brief and the raw invocation as input, then relays the intermediary's final message verbatim. Nothing in *Execution* runs in the apex context.

## Execution (you are the intermediary)

Your final message is relayed verbatim to the user, who sees only that message — not your tool output. Return only the deliverable.

1. **Parse the mode and a trailing `--resume`.**
   - If the first token is `soft`/`hard`/`switch` (case-insensitive, unquoted), that's the mode; otherwise mode = `soft`.
   - `--resume <id>` is recognized ONLY as the final two tokens of the whole invocation, ONLY in `hard`, and only when `<id>` looks like a session id (hex and dashes, e.g. a UUID). Strip them if so. `--resume` appearing anywhere else, or with a non-id-shaped value, is ordinary request text — do NOT extract it. A trailing `--resume` with no id is an error (`--resume needs a session id`). If `--resume` is present in `soft`/`switch`, refuse: `mode <mode> does not accept --resume`.

2. **Resolve the subproject** against `^/.state/roots.db` (load all rows, match in-model; never hand-build SQL from user input):

   ```
   python3 -c "import sys; sys.path.insert(0,'.codex/reactive/sqlite'); from sqlite import connect; \
   [print(r['is_apex'], r['name'], '|', r['rel_path'], '|', r['abs_path']) \
    for r in connect('.state/roots.db').execute('SELECT is_apex,name,rel_path,abs_path FROM roots ORDER BY rel_path')]"
   ```

   Split `<subproject>` from `<request>` by **longest-run** match on the tokens after the mode:
   - If the first post-mode token is quoted, `<subproject>` is that quoted string; the rest is `<request>`.
   - Otherwise, take the LONGEST run of leading whitespace-delimited words that (joined, case-insensitive, trailing slash/space trimmed) equals some root's `name`, full `rel_path`, or trailing path segment. That run is `<subproject>`; the remaining tokens are `<request>`. (E.g. `Agentic Primitives do X` → the run `Agentic Primitives` matches the child root, so `<subproject>` = `Agentic Primitives`, `<request>` = `do X` — NOT the truncated `Agentic`.)
   - Exactly one root matches the chosen run → capture `name` + `abs_path`; go to step 3.
   - The chosen run matches MORE THAN ONE root, or no leading run matches any root → do not guess; list the candidate roots (`name` + `rel_path`) and ask the user to re-issue (quoting the name). Stop.
   - Match is the apex (`is_apex = 1`) → refuse: `/ask` targets subprojects. Stop.
   - Missing `<subproject>`, or empty `<request>` for soft/hard → usage line. Stop.

3. **Branch on mode.**

   **soft** — Adopt `<abs_path>` as your context root (`^`). Read `<abs_path>/CLAUDE.md` and follow its `start.md` pointers (inherits `^/^/.codex`). **Confinement is YOUR responsibility** — the apex guards fence at the apex, not here. Do not read or write outside `<abs_path>` except `^/.state/roots.db` and the inherited `^/^/.codex` files; never touch `_`-prefixed paths; `.state/` writes go to `<abs_path>/.state/`. If `<request>` references another root, answer only from within `<abs_path>` and tell the user to issue a separate `/ask` for it. Carry out `<request>`. Return the answer prefixed `<name>: `.

   **hard** — Deliver the request as a FILE so its bytes never sit on a shell command line, then run the worker:
   1. Pick a fresh, unique scratch path under `.tmp/` (inside the apex fence, so it is writable) — e.g. `.tmp/ask-req-<6–8 random chars>.txt`. It must not already exist.
   2. Using the **Write tool** (NOT a shell command), write `<request>` **verbatim** into that file `<reqfile>`.
   3. Run the worker (append `--resume <session_id>` only if one was extracted in step 1):
      ```
      python cboot.py --project '<abs_path>' --exec-file '<reqfile>'
      ```
   4. Delete the scratch file: `rm -f '<reqfile>'`.

   Then read cboot's stdout and branch:
   - **stdout is not JSON** → cboot itself failed (crash / missing python). Surface as ERROR: `<name>: exec failed — <stderr or raw stdout>`. Not a runnable `!`-command.
   - **JSON with `is_error: false`** → success. Surface `result` as `<name>: <result>`, then a footer: `(hard · session <session_id> — continue with /ask hard <subproject> "…" --resume <session_id>)`.
   - **JSON with `is_error: true`** (whether `kind:"error"` or a `kind:"result"` whose turn failed) → failure. Surface the message plainly — it is in `error` if that key is present, otherwise in `result`; include `stderr` if present. **No** resume footer.

   Do NOT redo the work yourself — the worker is authoritative.

   **switch** — Run:

   ```
   python cboot.py --project '<abs_path>' --switch
   ```

   It prints a launch command (non-JSON) → hand it off: `<name>: to switch into this project, run:` followed by `! <printed command>`. If it printed nothing (error on stderr), surface that error instead. Nothing else runs; a `<request>`, if given, is context for after you switch, not executed here.

## Rooting note

Neither `soft` nor `hard` makes the apex rebind its guards for *you*, the intermediary. `soft`'s confinement is discipline — and the apex guards allow any within-apex write, so a mis-resolved soft target could clobber a *sibling*; resolve carefully. `hard`'s fence is real but lives in the **worker** session — `cboot --exec-file` sets `CLAUDE_PROJECT_DIR=<abs_path>` so that session's guards fence at the child. `switch` is the only mode that puts a human into a natively hard-rooted interactive session. For the mechanics, see the root inventory and `cboot.py`'s `--exec-file` / `--switch`.
