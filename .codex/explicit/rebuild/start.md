---
version: 2
short-desc: Restructure a project from audit findings (interactive, multi-phase)
reads:
  - "^/.state/tests/audits/"
  - "^/.codex/"
  - "^/.state/"
writes:
  - "^/<project>-rebuild-*/"
---

# rebuild

Analyze and restructure a project based on audit findings. Requires a prior audit — rebuild needs compressed context about project state that raw source alone can't provide. Interactive and multi-phase. Single project per run.

## Usage

`rebuild <project>` — rebuild a child project (e.g., `rebuild Majel`)

## Output Location

Rebuild outputs go to a datestamp-suffixed sibling of the target project:

```
^/<project>-rebuild-YYYYMMDD-HHMM/
    phase1-analysis.md
    phase2-requirements.md
    phase3-spec-initial.md
    phase3-spec-final.md
    phase4-rebuild/
        <rebuilt files>
```

This keeps rebuild artifacts next to the project they describe, without polluting the project itself.

## Phases

### Phase 0 — Pre-flight

1. Offer a deep audit of the target project.
2. If accepted: run the audit protocol, then use those outputs as compressed context.
3. If declined: locate the most recent audit for this project in `.state/tests/audits/`. Use those outputs. **If no prior audit exists, fail — an audit is required first.**

### Phase 1 — Analysis & Questions

1. Launch a sub-agent with audit outputs, target project read access, and the user's known context.
2. Agent performs requirements analysis, identifies gaps, critiques against best practices.
3. Agent asks up to 10 preferential questions. At 10, signals: "That was 10 questions, but more would help — ask or go build?"
4. Main agent relays questions to the user.
5. **Output**: `phase1-analysis.md`

### Phase 2 — Refinement

1. Resume agent with the user's answers.
2. Agent synthesizes answers into refined, consolidated requirements.
3. **Output**: `phase2-requirements.md`

### Phase 3 — Spec & Confirm

1. Agent produces two files:
   - `phase3-spec-initial.md` — original spec state, captured as-is for baseline
   - `phase3-spec-final.md` — proposed rebuilt spec with all recommendations applied
2. For each element: original → assessment → recommendation → status (adopted / modified / flagged).
3. Main agent presents spec-final to the user for confirmation.

### Phase 4 — Rebuild

1. User confirms or provides adjustments.
2. Agent produces the rebuilt design/spec documents.
3. **Output**: `phase4-rebuild/` subfolder.

## Sub-Agent Scope

- **ABSOLUTE HOLD**: may only **read** from the target project path.
- **ABSOLUTE HOLD**: may only **write** to the rebuild output folder.
- No execution, no modification of the target project.
- Read-only access to target project source for direct reference.

## Question Budget

Up to 10 preferential questions per run, counted across all phases. If the budget is exhausted and more questions would materially improve output, the agent must signal this rather than silently proceeding with assumptions.
