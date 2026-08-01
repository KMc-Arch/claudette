---
version: 1
short-desc: Pre-milestone holistic QA — iterative blind multi-agent fan-out, fix critical/high, repeat until clean
isolation: inline
reads:
  - "^/"
writes:
  - "^/.state/tests/mileqa/"
  - "^/.state/work/backlog.md"
  - "^/ (fix phase only: files inside the QA scope, plus git commits on the feature branch)"
---

# mileqa

Meta-process: generalized, holistic, adversarial QA of a body of work **before it becomes a milestone**. Applies to any artifact set — code, codex modules, docs, schemas. Typically precedes `/milestone`; complements (never replaces) targeted suites like `/test-safe` or module test harnesses.

Built on the proven QA-molecule pattern: blind multi-lens fan-out → adversarial verification of every finding → fix → prove.

## Usage

`mileqa` — QA the current branch's changed surface (diff vs main, plus in-scope untracked files)
`mileqa <scope>` — QA a named subject (project, module, path set)

If the scope is ambiguous, enumerate the candidate surfaces and ask the user to pick before dispatching anything.

## Protocol

### Round structure (repeat per round)

1. **Checkpoint commit.** If on `main`, create a feature branch first — named for the *work*, not the QA (`feature/<topic>`). Commit all pending in-scope work so every round starts from a committed, diffable, revertible state. Never commit on `main`.
2. **Fan out a blind QA panel.** Parallel, independent agents. Mandatory lenses every round:
   - **Cold readers** — no conversation context; read the artifacts cold and *summarize detailed functionality back*. Divergence between their reconstruction and the intended design = finding.
   - **Adversaries** — push every seam: edge inputs, path escapes, symlinks, malformed state, interrupts, guard/boundary bypasses, refutation of any claimed guarantee.

   Add whatever else fits the subject (never fewer than the mandatory two, and add more whenever appropriate):
   - Conformance — docs/specs/READMEs vs actual behavior
   - Test integrity — tautology hunt; mutation-prove that hardened checks can actually fail
   - Security/scrub — secrets, credential classes, boundary interactions
   - Platform — 9p/drvfs, ugrep-not-GNU, WSL, chmod-EPERM hazards
   - Regression — green suites still green; adjacent modules unbroken

   **Blindness rule:** panelists get artifact paths + a task, never the conversation narrative and never each other's findings.
3. **Adversarially verify every finding** before triage — independent verifier per finding, prompted to refute (CONFIRMED / PLAUSIBLE / refuted). Refuted findings die here.
4. **Triage** survivors: `critical | high | medium | low` (same vocabulary as the work entry schema).
5. **Fix all critical + high in-round**, each fix proven by a test or direct demonstration. Medium/low: fix if trivial, else record in the session root's backlog with a deliberate-deferral note. Honor exclusions — never silently reintroduce cut scope.
6. **Commit the round's fixes** with a round-tagged message.

### Loop control

- **Repeat up to 3 rounds**, or stop early when a *full* fan-out returns nothing above medium.
- Each round **rotates and expands** the panel — fresh lenses over identical reruns; any surface newly touched by fixes gets a fresh cold read next round.
- Exit states:
  - **CLEAN** — a pass with all findings ≤ medium. The milestone gate is open.
  - **EXHAUSTED** — 3 rounds and critical/high still emerging. This is NOT a pass: report residuals and stop; the subject needs redesign, not a round 4.
  - **ESCALATION** — a finding exceeds the subject's scope; route per the signal taxonomy and pause the loop for the user.

## Tooling

Prefer the **Workflow tool** (this protocol's instruction constitutes the multi-agent opt-in): pipeline finders into per-finding verifiers (no barrier unless deduping across the whole panel), loop-until-dry within a round, structured-output schemas for findings/verdicts. Fall back to parallel subagent dispatches when Workflow is unavailable. Scale panel size to the surface under review, not to a fixed number.

## Reporting

- Persist per round: `^/.state/tests/mileqa/YYYYMMDD-HHMM/round-N.md` — panel composition, findings with verdicts and severities, fixes, deferrals, checkpoint + fix commit SHAs. Final `summary.md` with the exit state.
- Final chat report: rounds run, findings by severity, fixes, residuals/deferrals, exit state — re-summarized so the last message stands alone. No error tallies.

## Governance interlocks

- **Commits:** invoking `/mileqa` authorizes the protocol's checkpoint and round-fix commits, on the feature branch only. It does NOT authorize push, merge, or any commit on `main`. Push remains a separate, user-instructed, scrub-gated action — push never implies more.
- **QA agents are read-only.** Only the fix phase (step 5, main session) writes. Destructive functional testing (e.g. `/test-burn`) runs only under its own module's confirmation gate — never dispatched implicitly by a panelist.
- `_`-visibility, containment, and state gravity bind all dispatched agents. Findings/reports land in this session's `^/.state/`, never a child's, unless the user gives explicit path notation.
