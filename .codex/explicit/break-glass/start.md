---
version: 1
short-desc: "Spawn isolated, contracted worker sub-session with QA review"
runtime: python
isolation: inline
reads:
  - "./baseline.md"
  - "^/.state/traces/break-glass/"
writes:
  - "^/.state/traces/break-glass/"
---

# break-glass

Spawn a mechanically isolated worker (glasser) to execute a scoped task against a single git repo. Each glasser invocation produces exactly one diff. An independent QA subagent reviews the diff. The parent presents both to the user.

## Roles

| Role | Responsibility | Context |
|---|---|---|
| **Parent** | Owns the user relationship. Assembles prompts, orchestrates flow, presents results. | Full session context |
| **Glasser** | Executes the task. Produces one diff per invocation. | Task + baseline only |
| **QA** | Reviews the diff against the task. Produces a verdict. | Task + diff + QA baseline only |

Glasser and QA contexts MUST NEVER cross-pollinate. The parent is the only entity that touches both. Neither receives the other's baseline or constraints.

## Contract

### Required Parameters

| Parameter | Type | Description |
|---|---|---|
| `task` | string | What the glasser should accomplish. Self-contained — the glasser has no other context. |
| `repo` | path | Which repo to operate on. Becomes the read-write worktree mount. |
| `tools` | list | Explicit tool allowlist. Validated as subset of host ceiling. |
| `timeout` | integer | Seconds. Maximum 600. |

### Optional Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `read_from` | list[path] | `[]` | Additional read-only mounts. Reference material the glasser can see but not modify. Sensitive paths trigger advisory (see Mount Model). |
| `max_turns` | integer | `10` | Maximum agentic turns before the glasser is stopped. Ceiling: 50. |
| `qa` | boolean | `true` | Whether to run QA review on the resulting diff. |

### Host Invariants (immutable, cannot be relaxed by caller)

| Invariant | Value | Enforcement |
|---|---|---|
| Permission ceiling | `acceptEdits` | CLI flag — mechanical |
| Tool ceiling | Caller's available tool set minus forbidden patterns | Contract validation — `tools` must be a subset |
| Forbidden tool patterns | `Bash`, `Bash(*)` | Contract validation — refuses on match |
| Recursion | Denied | No `claude` binary in container image — mechanical |
| Egress | `api.anthropic.com:443` only | Container network policy — mechanical |
| Audit | Mandatory | Parent-side, runs regardless of outcome |
| Worktree | Required for write-capable tools | Mount is the isolation boundary — mechanical |

### Validation Sequence

All gates must pass. Failure on any gate refuses the invocation with the specific violation.

1. **Completeness** — every required parameter present? Refuse with the missing field name.
2. **Repo validity** — `repo` is a valid git repository (`git rev-parse --git-dir` succeeds)? Refuse with: "repo is not a git repository."
3. **Tool containment** — every `tools` entry is a subset of the host ceiling? Refuse with the disallowed tool.
4. **Pattern safety** — no tool entry matches a forbidden pattern? Refuse with the matched pattern.
5. **Timeout bound** — `timeout ≤ 600`? Refuse (do not silently clamp).
6. **Turns bound** — `max_turns ≤ 50`? Refuse (do not silently clamp).
7. **Mount advisory** — any `read_from` path matches a sensitive-path pattern (see Mount Model)? Warn with the specific path. Proceed on user confirmation.

## Mechanical vs Behavioral Constraints

| Constraint | Enforcement | Strength |
|---|---|---|
| Permission mode | `--permission-mode` CLI flag | **Mechanical** |
| Tool allowlist | `--allowedTools` CLI flag | **Mechanical** |
| Timeout | Container kill | **Mechanical** |
| Max turns | `--max-turns` CLI flag | **Mechanical** |
| Recursion | No binary in image | **Mechanical** |
| Network egress | Container network policy | **Mechanical** |
| Filesystem scope | Mount boundary | **Mechanical** |
| Task scope compliance | `baseline.md` prompt injection | **Behavioral** |
| Output structure | Prompt instruction | **Behavioral** |

Seven mechanical, two behavioral.

## Mount Model

```
MOUNTS:
  rw:   exactly one — repo path → git worktree (the diff surface)
  ro:   zero or more — read_from paths → read-only bind mounts
```

One glasser = one repo = one worktree = one diff per invocation.

### Sensitive Path Advisory

The following paths trigger a warning at gate 7 if included in `read_from`. The parent surfaces the warning; the user confirms or cancels. Not a hard refusal — the prescriptive contract (explicit mount declaration) is the control.

```
~/.ssh/       ~/.aws/       ~/.claude/
~/.config/    ~/.kube/      ~/.docker/
```

### Worktree Lifecycle

The worktree persists until all user decisions are applied. Surgical edits require the worktree with prior changes intact. Cleanup occurs only after the final decision (merge, reject, or override) — never after diff extraction alone.

- **On timeout/error:** Worktree preserved for inspection. Parent logs state, user decides cleanup.
- **On final decision applied:** Worktree deleted. Audit trail entry closed.

## Assembly

1. Validate contract (all gates pass or refuse with specific violation).
2. Create git worktree from `repo`.
3. Build glasser prompt: `baseline.md` content + task string.
4. Spawn containerized `claude -p` with:
   - `--permission-mode acceptEdits`
   - `--allowedTools` from validated `tools` list
   - `--max-turns` from contract (default 10)
   - `--output-format text`
   - container timeout: `timeout` seconds from contract (container kill on expiry)
   - rw mount: worktree path
   - ro mounts: `read_from` paths
5. Receive diff from worktree (`git diff` in worktree path).
6. If `qa: true`, invoke `/break-glass-qa` with: task (verbatim) + diff + QA baseline (`break-glass-qa/baseline.md`). See `break-glass-qa/start.md`.
7. Present results to user based on QA verdict.
8. Log to audit trail regardless of outcome.

## Result Flow

### Without QA (`qa: false`)

Present the diff. User decides: **merge** or **reject**.

### With QA (`qa: true`)

| Verdict | User options |
|---|---|
| **PASS** | Merge · Reject |
| **IMPROVE** | **Holistic** (re-run: original task + user clarifications) · **Surgical** (new run: improvements only, on top of current diff) · Merge as-is · Reject |
| **FLAG** | Reject · Override (merge despite flags) |

### IMPROVE: Holistic vs Surgical

- **Holistic** — re-run the original task with user-provided clarifications woven in. Fresh worktree from the same base commit (parent saves the first worktree's base SHA). Produces a complete new diff that supersedes the first. Signals: task formulation was underspecified.
- **Surgical** — new glasser run where the task IS the improvements. Applies on top of the first diff (worktree retains first run's changes). Produces an incremental diff. Signals: execution was incomplete but directionally right.

Different failure modes produce different baseline evolution signals.

## Audit Trail

Every invocation logs to `^/.state/traces/break-glass/`:

```
YYYY-MM-DD-HHMM-SS.md:
  - task (verbatim)
  - repo
  - tools (exact list)
  - timeout
  - read_from (if any)
  - max_turns
  - outcome: completed | timeout | error
  - qa_verdict: PASS | IMPROVE | FLAG | skipped
  - user_action: merge | reject | holistic | surgical | override
```

## Baseline Evolution

The glasser baseline (`baseline.md` in this folder) starts minimal and grows empirically:

- `IMPROVE(holistic)` patterns → task formulation gaps → consider baseline addition
- `IMPROVE(surgical)` patterns → execution thoroughness gaps → consider baseline addition
- `FLAG` patterns → scope discipline gaps → consider baseline addition
- User overrides of QA → potential QA over-sensitivity → adjust QA baseline (in `break-glass-qa/`)

The user reviews QA findings periodically for drift patterns. New rules are added to the appropriate baseline only when patterns emerge — not speculatively.
