---
version: 1
---

# ~inbox

Things dropped **for this project's human / next session to read**. Visible (`~`), never git-tracked.

    ~inbox/<sender>/...                    # free-form drops from a person or a sibling project
    ~inbox/hb/<ITEM>/                      # Heartbeat outcome for one item (folder = pause format + outcome.md)
    ~inbox/hb/night-<YYYY-MM-DD>.md        # Heartbeat nightly summary — written EVERY night, even when nothing ran

## Heartbeat outcome folder

| file | content |
|---|---|
| `outcome.md` | frontmatter: `item_id`, `branch`, `pr` (url or null), `pushed` (bool), `publish_note`, `terminus` (converged \| exhausted \| cap \| rejected \| failed-repeatedly \| quota \| unexpected), `qa_result` (converged \| held \| exhausted \| escalation \| n/a), `summary` (worker's one-liner), `base_commit`, `head_commit`, `has_commits`, `files_touched`, `attempts`, `session_id`, `transcript_path`, `cost_usd`, `duration_min`, `worker_is_error`; body: what was done and why it stopped (also the PR body). Rejected / failed-repeatedly outcomes carry only the fields that exist. |
| `context.md` | pause-format: what the worker was doing, decisions, open questions (if the worker wrote it) |
| `state.md` | pause-format: files viewed/modified, pending work (if the worker wrote it) |
| `item.md` | the item as claimed (copy) |
| `state-delta.diff` | `git diff --no-index` of the sandbox's `.state/work/` vs live — a worker's backlog filings/resolutions, preserved for review, **never applied** |

**The inbox is read by a human.** The next night's runner never reads it. Disposal: review the PR/branch awake;
merge (never automated), or prune the branch / return the item to the backlog.
