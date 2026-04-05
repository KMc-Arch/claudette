---
version: 1
short-desc: "QA review agent for break-glass diffs — independent from glasser"
isolation: inline
reads:
  - "./baseline.md"
writes:
  - "^/.state/traces/break-glass/"
---

# break-glass-qa

Independent QA review of a break-glass glasser's diff. Evaluates the diff holistically against the original task statement. Produces a verdict with actionable feedback.

## Isolation Guarantee

QA and glasser contexts MUST NEVER cross-pollinate:

- QA does NOT receive the glasser's `baseline.md` or operating constraints
- QA does NOT know what tools or mounts the glasser had
- QA does NOT receive parent session context
- The glasser does NOT know QA exists

QA judges **output against objective**, blind to the glasser's constraints. If the glasser was under-tooled and produced a partial solution, QA should flag the gap — that feedback helps the parent assess whether its own scoping was too tight.

## Inputs

QA receives exactly three things from the parent:

1. **Task statement** — verbatim, the exact string the glasser received. This is the shared contract. No paraphrasing.
2. **Diff** — the glasser's output, as produced by `git diff` in the worktree.
3. **QA baseline** — `baseline.md` from this folder. Independent from the glasser's baseline.

Nothing else. No parent context, no glasser directives, no tool lists, no mount paths.

## Verdict Model

| Verdict | Meaning |
|---|---|
| **PASS** | Diff satisfies the task. No significant gaps or violations. |
| **IMPROVE** | Diff is directionally correct but could be better. Includes specific suggestions. |
| **FLAG** | Diff contains violations — changes that contradict or clearly exceed the task. Includes specific line references. |

### Verdict Format

```
VERDICT: PASS | IMPROVE | FLAG

[For IMPROVE]
SUGGESTIONS:
- <specific, actionable suggestion with line references>
- ...

[For FLAG]
VIOLATIONS:
- <specific violation with line references>
- ...

[For all verdicts]
SUMMARY:
<1-3 sentences: what the diff does well, what it misses>
```

## Invocation

Called by the parent after a glasser run completes (when `qa: true` in the break-glass contract). Not invoked directly by users.

The parent assembles the QA prompt:

```
[QA BASELINE — from break-glass-qa/baseline.md]
<baseline content>

[TASK — verbatim from break-glass contract]
<task string>

[DIFF]
<git diff output>
```

## Execution

QA runs as a lightweight subprocess — no container, no worktree, no filesystem access. Pure text-in, text-out evaluation.

```
claude -p "<assembled QA prompt>" \
  --permission-mode plan \
  --allowedTools "" \
  --max-turns 1 \
  --output-format text
```

- `--permission-mode plan` — QA has no write capability
- `--allowedTools ""` — no tools at all; QA only reasons about the inputs
- `--max-turns 1` — single-pass evaluation, no iteration

## Baseline Evolution

QA's baseline (`baseline.md` in this folder) evolves independently from the glasser's:

- **QA false-flags** (user overrides a FLAG) → QA was too strict → consider relaxing or clarifying a directive
- **QA misses** (user catches an issue QA didn't flag) → QA was too lenient → consider adding a directive
- **Consistent IMPROVE patterns** → if QA keeps suggesting the same improvement, it may belong in the glasser's baseline instead

QA baseline changes come from QA-specific feedback signals, never from glasser behavior.
