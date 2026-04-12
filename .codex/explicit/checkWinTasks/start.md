---
version: 1
short-desc: Check and kick stale Windows scheduled tasks
---

# checkWinTasks

Check Windows scheduled tasks by name pattern, report status, and kick any that are stale.

## Invocation

```
/checkWinTasks pattern1, pattern2[, ...]
```

## Protocol

1. Parse the comma-separated arguments into individual patterns (trim whitespace).
2. Run the sibling script:
   ```
   powershell -File .codex/explicit/checkWinTasks/check-tasks.ps1 <pattern1> <pattern2> ...
   ```
3. Present the output as a status grid to the user.
4. If any tasks show `Stale: YES` (last run >20hr ago), re-run with the `-Kick` flag:
   ```
   powershell -File .codex/explicit/checkWinTasks/check-tasks.ps1 -Kick <pattern1> <pattern2> ...
   ```
5. If any tasks were kicked, wait 5 seconds, then re-run without `-Kick` to show the refreshed grid (all tasks, kicked and not).
