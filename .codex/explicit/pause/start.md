---
version: 1
short-desc: Save session context for later resumption
reads:
  - "^/.state/"
writes:
  - "^/.state/pauses/"
---

# pause

Save current session context for later resumption.

## Usage

`pause` — save session state to a new pause folder

## Procedure

1. **Determine folder name:** `^/.state/pauses/YYYYMMDD.N` where N auto-increments (scan existing folders for today's date, use next N).
2. **Create the folder** with two files:
   - `context.md` — what we were doing, key decisions made, open questions, current train of thought.
   - `state.md` — files viewed/modified this session, pending work, any relevant file inventory.
3. **Be thorough.** The goal is to reconstruct the session from a cold start. Another Claude instance with no memory of this session should be able to resume from these files alone.
4. **Confirm** the folder name and a brief summary of what was captured.
