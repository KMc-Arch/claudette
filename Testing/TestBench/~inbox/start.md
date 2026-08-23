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
| `outcome.md` | frontmatter: `item_id`, `branch`, `pr` (url or null), `terminus` (converged \| exhausted \| cap \| rejected \| failed-repeatedly \| quota \| unexpected), `qa_result` (converged \| exhausted \| n/a), `base_commit`, `head_commit`, `files_touched`, `attempts`, `session_id`, `transcript_path`, `cost_usd`, `duration_min`; body: summary — what was done and why it stopped |
| `context.md` | pause-format: what the worker was doing, decisions, open questions |
| `state.md` | pause-format: files viewed/modified, pending work |

**The inbox is read by a human.** The next night's runner never reads it. Disposal: review the PR/branch awake;
merge (never automated), or prune the branch / return the item to the backlog.
