---
version: 7
short-desc: Pre-milestone holistic QA — blind multi-lens fan-out over an ever-growing roster; repeat until a full-roster round is clean or stops converging
isolation: inline
reads:
  - "^/"
writes:
  - "^/.state/tests/mileqa/"
  - "^/.state/work/ (residuals/deferrals to the right register: backlog/platform/architecture/boundaries/enhancements)"
  - "^/ (fix phase only: files inside the QA scope, plus git commits on the feature branch)"
---

# mileqa

Holistic, adversarial QA of a body of work **before it becomes a milestone**. Any artifact set — code, codex modules, docs, schemas. Precedes `/milestone`; complements (never replaces) targeted suites like `/test-safe`.

**The loop, coarsely:** fan out a blind multi-lens panel → adversarially verify every finding → fix critical/high → **grow the roster** → repeat until a full-roster round comes back clean, or the surface stops shrinking.

## Usage

`mileqa` — QA **this session's delta** (the files this session created or changed).
`mileqa <scope>` — QA a named subject (project, module, path set).

If the scope is ambiguous, enumerate the candidates and ask before dispatching anything.

## The roster — grows, never shrinks

The **roster** is the set of QA lenses you run. It starts with the mandatory two —

- **Cold readers** — no conversation context; read the artifacts cold and reconstruct the functionality back. Divergence between their reconstruction and the intended design = finding.
- **Adversaries** — push every seam: edge inputs, path escapes, malformed state, interrupts, boundary bypasses, refutation of any claimed guarantee.

— plus whatever the subject warrants: conformance (docs vs behavior), test-integrity (tautology hunt + mutation-prove), security/scrub, platform (9p/drvfs, ugrep-not-GNU, WSL, chmod-EPERM), regression.

**Remember the roster across rounds, and only ever ADD to it.** Every round re-runs the *entire* accumulated roster plus any new lens the previous round showed you needed. A lens is **never** dropped.

This is the regression guarantee: a clean round is clean against *every lens ever applied*, so a later fix cannot quietly reintroduce something an earlier lens already caught — and because the lens set never shrinks, a fall in findings between rounds is a **real** signal, not an artifact of looking less hard. The ever-growing roster is what makes the convergence test below trustworthy.

## Per round

1. **Checkpoint.** If on `main`, branch first (`feature/<topic>`, named for the *work*); else confirm you are on the work's feature branch (if it is neither, stop and ask where the work should land). Commit the session's pending in-scope work so the round starts from a committed, revertible baseline (clean tree = no-op). Never commit on `main`.
2. **Fan out the FULL current roster, blind.** Parallel, independent agents; each gets only artifact paths + a task — never the conversation narrative, never each other's findings, never `^/.state/traces/` or the in-flight reports. (This is an `inline` module, so blindness is orchestrator discipline, not enforced — construct the prompts accordingly.) Prefer the **Workflow tool** (pipeline finders into per-finding verifiers); scale panel size to the surface.
3. **Adversarially verify every finding** — one independent verifier per finding, prompted to refute → CONFIRMED / PLAUSIBLE / refuted. Refuted findings die here; a still-PLAUSIBLE critical/high counts as CONFIRMED (conservative).
4. **Triage** survivors: `critical | high | medium | low`.
5. **Fix all critical + high**, each proven by a test or direct demonstration. A verified critical/high may be held as a **residual** ONLY if (a) **user-owned** — you cannot edit it; deliver exact fix text *plus the verification the user can run* (the proof obligation transfers); (b) **user-deferred** — an explicit user ruling this run; or (c) **out-of-subject** — pre-existing AND untouched-and-unworsened by the work (if the work touched or worsened it, it is in-subject and gets fixed; the class-(c) claim is itself independently verified). File residuals to the correct `^/.state/work/` register with an owner. Medium/low: fix if trivial, else record in the backlog with a deliberate-deferral note. Honor exclusions — never silently reintroduce cut scope.
6. **Commit the fixes, then GROW the roster.** Add any lens this round revealed you needed — a new failure mode a finding exposed, or a surface a fix newly touched (which gets a fresh cold read next round). Never remove one. Record the roster so the next round re-runs it in full.

## Exit

Keep looping **as long as the surface is converging** — the aggregate severity of verified findings strictly **decreasing** round over round, with **no regressions** (no fix introducing a new finding). Aggregate severity = the finding counts compared as the tuple `(criticals, highs, mediums, lows)`; "decreasing" = strictly lower this round than last. Because the roster only grows, a decrease is trustworthy, and a strict decrease is self-terminating — it cannot continue forever.

Exit states:

- **CLEAN (0)** — a full-roster round surfaces nothing above **medium** after verification. The roster signs it off — never your own say-so; your own tests are necessary but not sufficient. Milestone gate opens.
- **HELD** — clean except properly-classed residuals. Gate closed; present the residuals to the user as decision items (exact fix text + the verification to run). Their rulings convert HELD → CLEAN or into new in-scope work.
- **NOT CONVERGING** — aggregate severity stops shrinking (flat or rising), or your fixes keep regressing. Stop: the surface is generating defects roughly as fast as you close them. This is a **redesign signal**, not a round-4 problem (patch-of-patch is the tell — redesign the subsystem). Not clean; gate closed; hand to the user with the severity trajectory.
- **ESCALATION** — a finding exceeds the subject's scope. Route per the signal taxonomy (`^/.state/start.md`), pause for the user (not terminal); resume on their ruling.

When more than one applies at once: **ESCALATION → NOT CONVERGING → HELD → CLEAN**.

## Reporting

- Per round, persist `^/.state/tests/mileqa/YYYYMMDD-HHMM/round-N.md`: the roster run, findings with verdicts + severities, fixes, deferrals, checkpoint + fix commit SHAs, and **the round's aggregate-severity tuple** (so the convergence trend is legible at a glance). Final `summary.md` with the exit state.
- Final chat report: rounds run, findings by severity, fixes, residuals/deferrals, exit — re-summarized so the last message stands alone. No error tallies.

## Governance interlocks

- **Commits:** invoking `/mileqa` authorizes the checkpoint + round-fix commits on the feature branch only. It does NOT authorize push, merge, or any commit on `main`. Push stays a separate, user-instructed, scrub-gated action.
- **Panel agents are read-only.** Only the main session writes — the checkpoint/fix commits, the reports, and the fixes; panel agents never write. Destructive functional testing (e.g. `/test-burn`) is never dispatched implicitly by a panelist.
- `_`-visibility, containment, and state gravity bind all dispatched agents. Findings/reports land in this session's `^/.state/`, never a child's, unless the user gives explicit path notation.
