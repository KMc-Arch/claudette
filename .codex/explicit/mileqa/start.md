---
version: 6
short-desc: Pre-milestone holistic QA — iterative blind multi-agent fan-out, fix critical/high, repeat until an independent fix-free green pass
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

A round is a **VERIFY** (steps 2–4: blind panel → adversarial verification → triage). It becomes a **FIX round** only if triage surfaces something to fix (steps 5–6). Per **Loop control**, only a fix-free VERIFY that comes back green ends the run.

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

- **Two pass types, capped differently.** A **FIX round** may edit files (steps 5–6) and is **capped** — the *convergence budget* (default 3). The cap exists to detect a design that keeps generating defects, **not** to end the run. A **VERIFY pass** (steps 2–4: blind panel → adversarial verification → triage, applying no fix) is **read-only**; because it changes no state it cannot loop forever, so it is **never capped**.
- **Terminal-green invariant — the only clean exit.** The run may be declared **CLEAN only by a VERIFY pass that applied no fixes and came back green** (nothing above medium after verification). A FIX round is **never terminal**: every fix is followed by another VERIFY, so the run is `VERIFY → (findings → FIX → VERIFY → …)` until a **fix-free green**. Your own test suite is **necessary but not sufficient** — it is the fixer's artifact; the independent blind panel is the sign-off. Never call it clean on "I applied the fixes and believe it's done."
- **Whole-subject, fresh, independent.** Each VERIFY reads the **whole subject** (full diff vs main), not just the last fix's diff, and **rotates/expands** the panel — fresh lenses; any surface a fix touched gets a fresh cold read. A diff-scoped check misses pre-existing holes in the files the work touches (learned 2026-08-12: three diff-scoped passes missed a pre-existing containment fail-open in a guard the branch was actively hardening; the full-surface independent pass caught it).
- **Security surfaces need two consecutive greens.** For a containment / permission / secrets boundary — or **any** surface where a fix has already introduced a regression — require **two independently-constructed green VERIFY passes back-to-back** before CLEAN. One green panel can be thin or lucky; two are evidence. It still terminates the moment the state is genuinely clean.
- **Verdict inputs (defined):** an **open item** = a verified critical/high survivor not yet fixed-and-proven. PLAUSIBLE critical/high survivors get one targeted re-verification before exit; still-PLAUSIBLE counts as CONFIRMED (conservative). A **residual** = an open critical/high in exactly one step-5 class (user-owned / user-deferred / out-of-subject, per step 5's definitions). Residuals alone → HELD, never EXHAUSTED.
- **Exit states** (evaluated on the last VERIFY pass):
  - **CLEAN** — a fix-free VERIFY came back green: no open critical/high, no residuals, all verified findings ≤ medium (two consecutive greens for a security surface). The milestone gate is open. This is the ONLY clean exit, and it is always an independent check — never self-certification.
  - **HELD** — the last VERIFY is green *except* properly-classed residuals (user-owned / user-deferred / out-of-subject open critical/high). The gate is closed pending the user's rulings — present them as decision items (with exact fix text + the verification to run, where user-owned); their rulings convert HELD to CLEAN or into new in-scope work.
  - **EXHAUSTED** — the FIX-round cap is hit and a subsequent VERIFY still surfaces NEW non-residual critical/high: the fix loop is not converging. **NOT clean** — fixes were applied but are not independently verified-green; the gate stays closed and **only the user can open it** (their merge/ship decision, on your report). Step 5 is never waived — the final round's criticals/highs still get fixed in-round. **Report the defect-class trajectory** (learned 2026-08-01): a **monotonically narrowing** class (mainline defects → regressions-in-fixes → exotic-edge/pre-existing-adjacent) = converging — report residuals as bounded and point at the planned structural remedy. A **flat or widening** class — or **your own fixes repeatedly regressing** — = redesign signal: the design itself is generating defects and no further round will fix that (patch-of-patch is the tell — redesign the subsystem).
  - **ESCALATION** — a finding exceeds the subject's scope; route per the signal taxonomy (`^/.state/start.md`) and pause the loop for the user (gate closed while paused; not terminal). On their ruling the loop resumes.

## Tooling

Prefer the **Workflow tool** (this protocol's instruction constitutes the multi-agent opt-in): pipeline finders into per-finding verifiers (no barrier unless deduping across the whole panel), loop-until-dry within a round, structured-output schemas for findings/verdicts. Fall back to parallel subagent dispatches when Workflow is unavailable. Scale panel size to the surface under review, not to a fixed number.

## Reporting

- Persist per round: `^/.state/tests/mileqa/YYYYMMDD-HHMM/round-N.md` — panel composition, findings with verdicts and severities, fixes, deferrals, checkpoint + fix commit SHAs. Final `summary.md` with the exit state.
- Final chat report: rounds run, findings by severity, fixes, residuals/deferrals, exit state — re-summarized so the last message stands alone. No error tallies.

## Governance interlocks

- **Commits:** invoking `/mileqa` authorizes the protocol's checkpoint and round-fix commits, on the feature branch only. It does NOT authorize push, merge, or any commit on `main`. Push remains a separate, user-instructed, scrub-gated action — push never implies more.
- **QA agents are read-only.** Only the fix phase (step 5, main session) writes. Destructive functional testing (e.g. `/test-burn`) runs only under its own module's confirmation gate — never dispatched implicitly by a panelist.
- `_`-visibility, containment, and state gravity bind all dispatched agents. Findings/reports land in this session's `^/.state/`, never a child's, unless the user gives explicit path notation.
