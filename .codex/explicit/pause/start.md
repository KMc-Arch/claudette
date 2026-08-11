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

1. **Determine folder name:** `^/.state/pauses/YYYYMMDD.NNN`.
   - `NNN` is the day's ordinal, **zero-padded to 3 digits** (`001`, `002`, … `010`, …), so folder names sort chronologically by name.
   - Assign it as **MAX + 1**: parse the numeric ordinal of every existing folder for today's date, take the maximum, add 1 (first pause of the day = `001`). Never derive it from a count — a deleted middle folder must not cause a re-mint that overwrites a survivor.
2. **Stage, then commit (atomic write):**
   - Build the snapshot in a staging folder `^/.state/pauses/.tmp-YYYYMMDD.NNN/`, writing both files there:
     - `context.md` — what we were doing, key decisions made, open questions, current train of thought.
     - `state.md` — files viewed/modified this session, pending work, any relevant file inventory.
   - Once both files are fully written, **rename** the staging folder to its final name `YYYYMMDD.NNN/`. The rename is the commit — a folder under its final name is, by definition, complete. An interrupted pause leaves only a `.tmp-*` folder, which `unpause` ignores.
3. **Be thorough.** The goal is to reconstruct the session from a cold start. Another Claude instance with no memory of this session should be able to resume from these files alone.
4. **Confirm** the final folder name and a brief summary of what was captured.
