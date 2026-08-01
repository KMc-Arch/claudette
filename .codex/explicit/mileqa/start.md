---
version: 5
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

1. **Checkpoint commit.** If on `main`, create a feature branch first — named for the *work*, not the QA (`feature/<topic>`). If already on a branch, verify it is the *work's* feature branch (never `main`, never an unrelated branch). Commit all pending in-scope work so every round starts from a committed, diffable, revertible state; a clean tree makes the checkpoint a no-op — proceed. Never commit on `main`.
2. **Fan out a blind QA panel.** Parallel, independent agents. Mandatory lenses every round:
   - **Cold readers** — no conversation context; read the artifacts cold and *summarize detailed functionality back*. Divergence between their reconstruction and the intended design = finding.
   - **Adversaries** — push every seam: edge inputs, path escapes, symlinks, malformed state, interrupts, guard/boundary bypasses, refutation of any claimed guarantee.

   Add whatever else fits the subject (never fewer than the mandatory two, and add more whenever appropriate):
   - Conformance — docs/specs/READMEs vs actual behavior
   - Test integrity — tautology hunt; mutation-prove that hardened checks can actually fail
   - Security/scrub — secrets, credential classes, boundary interactions
   - Platform — 9p/drvfs, ugrep-not-GNU, WSL, chmod-EPERM hazards
   - Regression — green suites still green; adjacent modules unbroken

   **Blindness rule:** panelists get artifact paths + a task, never the conversation narrative and never each other's findings. Blindness is *orchestrator discipline* — this module is `inline`, so `reads:` declarations document rather than enforce; construct panel prompts accordingly, and never point a panelist at `^/.state/traces/` or the in-flight round reports.
3. **Adversarially verify every finding** before triage — independent verifier per finding, prompted to refute (CONFIRMED / PLAUSIBLE / refuted). Refuted findings die here.
4. **Triage** survivors: `critical | high | medium | low` (same vocabulary as the work entry schema).
5. **Fix all critical + high in-round**, each fix proven by a test or direct demonstration. A verified critical/high may be classed a **residual** ONLY if it is (a) **user-owned** — a guarded artifact the agent cannot edit; deliver exact fix text *plus the verification the user can run* (the proof obligation transfers, it does not vanish); (b) **user-deferred** — explicitly deferred by user ruling in this run; or (c) **out-of-subject** — pre-existing AND untouched-and-unworsened by the work under QA (if the work touched or worsened it, it is in-subject and gets fixed); file it to the correct register (the `^/.state/work/` files per their schema) with an owner, and the class-(c) claim itself is adversarially verified like any finding (an independent verifier confirms pre-existing + untouched/unworsened) before it can support HELD. Everything else critical/high gets fixed in-round, **including round 3; no exit state waives this step.** Medium/low: fix if trivial, else record in the session root's backlog with a deliberate-deferral note. Honor exclusions — never silently reintroduce cut scope.
6. **Commit the round's fixes** with a round-tagged message.

### Loop control

- **Repeat up to 3 rounds**, or stop early when a round's complete panel (mandatory lenses present; rotation applies from round 2 onward) returns nothing above medium **after verification** — judged on verified survivors, not raw claims. Steps 5–6 still run on the closing round (trivial mediums, deferral notes, round commit).
- Each round **rotates and expands** the panel — fresh lenses over identical reruns; any surface newly touched by fixes gets a fresh cold read next round.
- **Verdict inputs (defined):** an **open item** = a verified critical/high survivor not yet fixed-and-proven. PLAUSIBLE critical/high survivors get one targeted re-verification before exit; still-PLAUSIBLE counts as CONFIRMED (conservative). A **residual** = an open critical/high in exactly one step-5 class (user-owned / user-deferred / out-of-subject, per step 5's definitions). **"Still emerging" is evaluated on the post-coda state:** a critical/high that was fixed and coda-verified is NOT emerging — only an open, non-residual critical/high at exit evaluation counts. Residuals alone → HELD, never EXHAUSTED.
- **Closing coda (bounded):** if the final round's fixes touched the subject, run a verification-only pass over that fix diff (per-fix verifiers or a mini-panel — not a full round). If the coda confirms a NEW critical/high: apply step 5 to it once (fix, prove, commit) and run one more coda over that fix diff. **Maximum two codas** — a second coda still surfacing new critical/high means the tail is not converging: declare EXHAUSTED. The exit state describes the post-coda state. (First-run precedent: the post-round-3 validation cadre, which caught a CONFIRMED critical.)
- **Exit states** (evaluated after the closing round + coda):
  - **CLEAN** — no open critical/high and no residuals; all verified findings ≤ medium. The milestone gate is open.
  - **HELD** — no open critical/high *except* properly-classed residuals. The gate is closed pending the user's rulings on the residual list — present it as decision items (with exact fix text + verification where user-owned); their rulings convert HELD to CLEAN or into new in-scope work. (The first run closed HELD-shaped: user-owned CLAUDE.md fixes + an out-of-subject boundary filing.)
  - **EXHAUSTED** — the 3-round cap or the coda bound is hit with NEW critical/high still emerging beyond the residual classes: the fix loop is not converging. NOT a pass; the gate stays closed and **only the user can open it** (their merge/ship decision, made on your report). Step 5 is never waived — the final round's criticals/highs still get fixed in-round. **Report the defect-class trajectory across rounds with the verdict** (learned on the first run, 2026-08-01): a **monotonically narrowing** class (mainline design defects → regressions-in-fixes → exotic-edge/pre-existing-adjacent) = converging surface — report residuals as bounded and point at the planned structural remedy if one exists. A **flat or widening** class = redesign signal — the design itself is generating defects, and no round 4 will fix that (patch-of-patch is the tell: redesign the subsystem instead).
  - **ESCALATION** — a finding exceeds the subject's scope; route per the signal taxonomy (`^/.state/start.md`) and pause the loop for the user (gate closed while paused; not terminal). On their ruling the loop resumes at the same round count.

## Tooling

Prefer the **Workflow tool** (this protocol's instruction constitutes the multi-agent opt-in): pipeline finders into per-finding verifiers (no barrier unless deduping across the whole panel), loop-until-dry within a round, structured-output schemas for findings/verdicts. Fall back to parallel subagent dispatches when Workflow is unavailable. Scale panel size to the surface under review, not to a fixed number.

## Reporting

- Persist per round: `^/.state/tests/mileqa/YYYYMMDD-HHMM/round-N.md` — panel composition, findings with verdicts and severities, fixes, deferrals, checkpoint + fix commit SHAs. Final `summary.md` with the exit state.
- Final chat report: rounds run, findings by severity, fixes, residuals/deferrals, exit state — re-summarized so the last message stands alone. No error tallies.

## Governance interlocks

- **Commits:** invoking `/mileqa` authorizes the protocol's checkpoint and round-fix commits, on the feature branch only. It does NOT authorize push, merge, or any commit on `main`. Push remains a separate, user-instructed, scrub-gated action — push never implies more.
- **QA agents are read-only.** Only the fix phase (step 5, main session) writes. Destructive functional testing (e.g. `/test-burn`) runs only under its own module's confirmation gate — never dispatched implicitly by a panelist.
- `_`-visibility, containment, and state gravity bind all dispatched agents. Findings/reports land in this session's `^/.state/`, never a child's, unless the user gives explicit path notation.
