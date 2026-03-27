---
version: 1
runtime: python
reads:
  - "^/.codex/pref-options.json"
  - "^/.codex/prefs.json"
  - "^/.state/prefs.json"
writes:
  - "^/.state/prefs-resolved.json"
---

# pref-resolve

Preference cascade resolver. Reads all cascade layers, merges them (most specific wins), and writes a single flat file that Claude reads for all preference lookups.

## Trigger

Runs at boot as part of `01b-materialization`. Must complete before any output — Claude's behavior depends on resolved preferences.

## Cascade Order

```
.codex/pref-options.json    (schema defaults)
  ↓ overridden by
.codex/prefs.json           (global identity)
  ↓ overridden by
.state/prefs.json           (instance overrides)
  ↓ overridden by
<project>/.state/prefs.json (project overrides, if in child context)
```

Each layer is sparse — only contains keys it overrides. Missing keys fall through.

## Context Resolution

- `pref-options.json` carries `default_context` for each preference's default value only.
- Downstream `prefs.json` files may provide their own `context` for any value they select.
- Resolution: downstream context → `default_context` (only if value equals default and no downstream context) → no context.

## Output Format

`.state/prefs-resolved.json`:

```json
{
    "_meta": {
        "generated": "2026-03-24T09:30:00Z",
        "sources": [
            { "file": ".codex/pref-options.json", "modified": "..." },
            { "file": ".codex/prefs.json", "modified": "..." },
            { "file": ".state/prefs.json", "modified": "..." }
        ],
        "project": null
    },
    "tone": {
        "value": "concise",
        "context": "No filler, no preamble. Lead with the answer.",
        "source": ".codex/pref-options.json (default)"
    }
}
```

## Staleness Detection

Compare `_meta.sources[].modified` against current file modification dates. If any source is newer than `_meta.generated`, the resolved file is stale — regenerate.
