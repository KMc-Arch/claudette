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

1. **Reap stale staging (best-effort).** Remove leftover `^/.state/pauses/.tmp-*` folders left by *this session's* earlier interrupted attempts. In the normal single-session case every today-dated `.tmp-*` is stale and may go; do **not** delete a staging folder a concurrent same-root session could be actively writing (staging names carry no session discriminator yet). Skipping the reap entirely is always safe — orphans are harmless (`unpause` ignores them).
2. **Determine folder name:** `^/.state/pauses/YYYYMMDD.NNN`.
   - `NNN` is the day's ordinal, **zero-padded to 3 digits** (`001`, `002`, … `010`, …). Padding is cosmetic — `unpause` sorts numerically, so it is not load-bearing.
   - Assign it as **MAX + 1** over the **completed** (final-named) folders for today: parse each folder's ordinal as an integer, take the maximum, add 1 (first pause of the day = `001`). Never derive it from a count — a deleted or interrupted folder must not cause a re-mint that overwrites a survivor. Legacy unpadded names (`YYYYMMDD.N`) parse the same way and are counted. `.tmp-*` staging folders are **not** counted (they were just reaped).
3. **Stage, then commit (atomic write):**
   - Build the snapshot in a staging folder `^/.state/pauses/.tmp-YYYYMMDD.NNN/` (if that exact name somehow still exists, remove it first), writing both files there:
     - `context.md` — what we were doing, key decisions made, open questions, current train of thought.
     - `state.md` — files viewed/modified this session, pending work, any relevant file inventory.
   - Once both files are fully written, **rename** the staging folder to its final name `YYYYMMDD.NNN/`. The rename is the commit. A folder is a valid pause only once it is final-named **and** holds both files; anything else — a `.tmp-*` or a partial/ghosted dir — `unpause` skips.
4. **Be thorough.** The goal is to reconstruct the session from a cold start. Another Claude instance with no memory of this session should be able to resume from these files alone.
5. **Confirm** the final folder name and a brief summary of what was captured.
