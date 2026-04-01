---
version: 3
short-desc: Restructure a project from audit findings (interactive, multi-phase)
reads:
  - "^/.state/tests/audits/"
  - "^/.codex/"
  - "^/.state/"
writes:
  - "^/<target>/"
---

# rebuild

Analyze and restructure a project based on audit findings. Requires a prior audit — rebuild needs compressed context about project state that raw source alone can't provide. Interactive and multi-phase. Single project per run.

## Usage

`rebuild <project>` — rebuild into a new folder, prompting for the folder name
`rebuild <project> <folder>` — rebuild into `^/<folder>/` (no prompt)

If no folder name is given, prompt: **"Folder name for the rebuild?"** and use the response as `^/<folder>/`. The folder must not already exist.

## Output Location

The rebuild folder **is** the rebuilt project — ready to swap in:

```
^/<folder>/
    CLAUDE.md
    .state/
    .codex/           (if project has local codex entries)
    .claude/
    .gitignore
    .rebuild/         (analysis artifacts, tucked away)
        phase1-analysis.md
        phase2-requirements.md
        phase3-spec-initial.md
        phase3-spec-final.md
```

The rebuild directory is the project. No unwrapping step — contents can be moved directly into the live project location.

`.rebuild/` is dot-prefixed (internal by convention) and holds the analysis trail. It is not part of the rebuilt project's operational structure.

## Phases

### Phase 0 — Pre-flight

1. Determine folder name: use the argument if provided, otherwise prompt.
2. Create `^/<folder>/`.
3. Offer a deep audit of the target project.
4. If accepted: run the audit protocol, then use those outputs as compressed context.
5. If declined: locate the most recent audit for this project in `.state/tests/audits/`. Use those outputs. **If no prior audit exists, fail — an audit is required first.**

### Phase 1 — Analysis & Questions

1. Launch a sub-agent with audit outputs, target project read access, and the user's known context.
2. Agent performs requirements analysis, identifies gaps, critiques against best practices.
3. Agent asks up to 10 preferential questions. At 10, signals: "That was 10 questions, but more would help — ask or go build?"
4. Main agent relays questions to the user.
5. **Output**: `.rebuild/phase1-analysis.md`

### Phase 2 — Refinement

1. Resume agent with the user's answers.
2. Agent synthesizes answers into refined, consolidated requirements.
3. **Output**: `.rebuild/phase2-requirements.md`

### Phase 3 — Spec & Confirm

1. Agent produces two files:
   - `.rebuild/phase3-spec-initial.md` — original spec state, captured as-is for baseline
   - `.rebuild/phase3-spec-final.md` — proposed rebuilt spec with all recommendations applied
2. For each element: original → assessment → recommendation → status (adopted / modified / flagged).
3. Main agent presents spec-final to the user for confirmation.

### Phase 4 — Rebuild

1. User confirms or provides adjustments.
2. Agent produces the rebuilt project files directly into `^/<folder>/` (the staging root).
3. Analysis artifacts remain in `.rebuild/`. Project files (CLAUDE.md, .state/, .codex/, .claude/, .gitignore) are at the root.

## Sub-Agent Scope

- **ABSOLUTE HOLD**: may only **read** from the target project path.
- **ABSOLUTE HOLD**: may only **write** to the rebuild output folder (`^/<folder>/`).
- No execution, no modification of the target project.
- Read-only access to target project source for direct reference.

## Question Budget

Up to 10 preferential questions per run, counted across all phases. If the budget is exhausted and more questions would materially improve output, the agent must signal this rather than silently proceeding with assumptions.
