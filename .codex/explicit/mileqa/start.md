---
version: 9
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

**The loop, coarsely:** fan out a blind multi-lens panel → adversarially verify every finding → fix in-scope critical/high (report the rest) → **grow the roster** → repeat until a full-roster round comes back clean, or the fixes stop converging (keep regressing).

## Usage

`mileqa` — QA **this session's delta** (the files this session created or changed).
`mileqa <scope>` — QA a named subject (project, module, path set).

If the scope is ambiguous, enumerate the candidates and ask before dispatching anything.

**Freeze the scope set before round 1 and write it down** — an explicit path list, recorded in the run directory. It is the *declared* scope set for the whole run and **never grows**: the run's own fix commits, new tests, and round reports are all files "this session changed", so a scope set recomputed each round would swallow the QA's own output and flip findings between blocking and reportable with no operator misbehaviour. Fixes may only touch paths already on the list. If a fix genuinely needs a path outside it, that is an out-of-scope finding — report it (or escalate), do not widen the list.

## The roster — grows, never shrinks

The **roster** is the set of QA **lenses** you run — each lens a *group* of one or more agents, not necessarily a single agent. It starts with the two mandatory lens groups —

- **Cold readers** — no conversation context; read the artifacts cold and reconstruct the functionality back. Divergence between their reconstruction and the intended design = finding.
- **Adversaries** — push every seam: edge inputs, path escapes, malformed state, interrupts, boundary bypasses, refutation of any claimed guarantee.

— plus whatever the subject warrants: conformance (docs vs behavior), test-integrity (tautology hunt + mutation-prove), security/scrub, platform (9p/drvfs, ugrep-not-GNU, WSL, chmod-EPERM), green-suites (adjacent modules still pass).

**Remember the roster across rounds, and only ever ADD to it.** Every round re-runs the *entire* accumulated roster plus any new lens the previous round showed you needed. A lens is **never** dropped.

This is the **no-reintroduction guarantee**: a clean round is clean against *every lens ever applied*, so a later fix cannot quietly reintroduce something an earlier lens already caught. (A *rise* in findings after you add a lens is expected — you looked harder — not a regression; see **Exit**.)

## Per round

1. **Checkpoint.** If on `main`, branch first (`feature/<topic>`, named for the *work*); else confirm you are on the work's feature branch (if it is neither, stop and ask where the work should land). Commit the session's pending in-scope work so the round starts from a committed, revertible baseline (clean tree = no-op). Never commit on `main`.
2. **Fan out the FULL current roster, blind.** Parallel, independent agents; each gets only artifact paths + a task — never the conversation narrative, never each other's findings, never `^/.state/traces/` or the in-flight reports. (This is an `inline` module, so blindness is orchestrator discipline, not enforced — construct the prompts accordingly.) Prefer the **Workflow tool** (pipeline finders into per-finding verifiers); scale panel size to the surface.
3. **Adversarially verify every finding** — one independent verifier per finding, prompted to refute → CONFIRMED / PLAUSIBLE / refuted. Refuted findings die here; a still-PLAUSIBLE critical/high counts as CONFIRMED (conservative).
4. **Triage** survivors: `critical | high | medium | low`.
5. **Resolve every finding by scope.** A finding is **in-scope** if fixing it would edit *within the run's declared scope set* — the session's delta, or the named subject; **out-of-scope** if the fix would reach outside it.
   - **Out-of-scope → REPORT, don't fix.** Valuable to have found, but not this run's job: file it to the right `^/.state/work/` register (with an owner) and move on. Out-of-scope findings **never block CLEAN and never count as regressions** — which is exactly why the out-of-scope *claim* must clear the same bar as any other suppression. An out-of-scope claim must **name the specific path outside the frozen scope set that the minimal fix has to touch**, and — for a **critical or high** — that claim itself goes through the **same independent refutation pass as any finding** (step 3): a verifier is told to refute "the minimal fix must edit path P outside the frozen set", and the claim stands only if the verifier cannot. An unverified or refuted out-of-scope claim on a critical/high leaves the finding **in-scope** (fix it) — the run may never retire its own critical/high by self-classifying it out. A critical/high that is genuinely out-of-scope AND severe or cross-boundary does not just get filed: it forces **ESCALATION** (see Exit), so a human, not the run, decides. (The classification is a predicate over a *proposed* fix path, and the proposer picks the path — so independent refutation of the path, not the run's own say-so, is what stops it being used to dodge a fix.)
   - **In-scope → resolve it.** Fix every in-scope critical/high, each proven by a test or direct demonstration. Hold one as a **residual** only if (a) **user-owned** — you cannot edit the artifact; deliver exact fix text *plus the user-runnable verification* (the proof obligation transfers), or (b) **user-deferred** — an explicit user ruling this run. In-scope medium/low: fix if trivial, else backlog with a deferral note. Honor exclusions — never silently reintroduce cut scope.
6. **Commit the fixes, then GROW the roster.** Add any lens this round revealed you needed — a new failure mode a finding exposed, or a region a fix newly touched (which gets a fresh cold read next round). Never remove one. Record the roster so the next round re-runs it in full.

## Exit

Each round you resolve every **in-scope** critical/high — fix it, or (out-of-scope) report-and-continue. Because the fix surface is **bounded to the run's scope** and you drain the in-scope critical/high pool each round, a **clean** round arrives — **unless your fixes keep generating new defects.** That is the one true divergence signal. The raw finding count is **not**: it rises whenever you add a lens, look harder, or surface an out-of-scope issue — the roster working, not a regression.

**What counts as a regression** — mechanically, no judgment: a *new* **critical or high** finding raised by a lens **already in the roster last round** (it ran then and did not raise it) in an artifact a fix has since touched (see the region definition below) — a previously-passing check now fails, so a fix broke it. Three constraints, each load-bearing: (1) **critical/high only** — a fix that introduces a new medium/low is noise, not a divergence signal; (2) the **lens is not new** — a finding from a lens added this round is surfacing pre-existing state (you looked harder), never a regression, *even when that lens is the "fresh cold read" of a fix-touched region*: the fresh read is a new lens instance, so its findings are baseline, and only a lens that also ran **last** round establishes a before/after; (3) the finding is **in a region a fix touched** — a new critical/high elsewhere is something an old lens simply missed before, not something a fix broke. Count the regressing round at **detection** — the round whose fan-out raises it. A **region a fix touched** is defined mechanically: **any file that appears in the round's fix commit(s)** — the diff, computed the same way for code, docs, and schemas (a doc-only fix has a doc region, not a "code" region). A new critical/high in a file no fix commit touched this run is something an old lens missed, not a regression.

**Terminal-green — the sign-off is a *fix-free* round.** A round's fan-out runs *before* its fixing, so a CLEAN round is necessarily one whose fan-out found nothing above medium in-scope — it did no critical/high fixing. The round that fixes the last critical/high is **never itself CLEAN**: run one more, and its fresh full-roster fan-out either signs off or finds more. This is why the *independent roster* certifies CLEAN — never "I applied the fixes and believe it's done"; your own tests are necessary but not sufficient.

**The severity boundary.** CLEAN requires the fan-out to surface nothing **critical or high** in-scope after verification. Mediums and lows do not block it. "Above medium" therefore means *critical or high*, using the same four-level scale the finders and verifiers apply (critical = a security/containment boundary fails open or governance is actively wrong; high = a real defect that bites in normal use; medium = a genuine but bounded problem; low = cosmetic). A **trivial** medium/low — fixable in-round without touching control flow or a contract — may be fixed on the CLEAN round itself; doing so does not disqualify the round (the "fix-free" property is about *critical/high* fixing, which is what forces another round). A non-trivial medium/low is backlogged with a deferral note, not fixed on the sign-off round.

- **CLEAN (exit 0)** — a full-roster round whose fan-out surfaces no in-scope **critical or high** after verification (out-of-scope findings are reported, not blocking; mediums/lows do not block): a critical/high-fix-free sign-off (see above). Milestone gate opens.
- **HELD** — in-scope critical/high remain, but only as residuals (user-owned or user-deferred). Gate closed; present them to the user as decision items (exact fix text + the verification to run). A ruling that clears the last residual returns the run to the loop for one more fix-free round, which then signs off CLEAN (or surfaces more); a ruling can also open new in-scope work. A residual stays classed: when the roster re-surfaces it in a later round, recognize it as the same residual — do not re-triage it as new or count it as a regression.
- **NOT CONVERGING** — your fixes keep regressing: **two rounds** (not necessarily consecutive) in which a fix introduced a *new critical/high* regression (per the mechanical definition above — critical/high only, so a run does not terminate on repeated low-severity churn). A single regressing round is a tolerated blip — fix it and continue; the second says the fixes themselves are generating defects. Stop — a **redesign signal**, not a round-4 problem (patch-of-patch is the tell — redesign the subsystem). Gate closed; hand to the user with the trajectory.
- **ESCALATION** — an out-of-scope finding urgent or cross-boundary enough to need a user decision *now* (not just filing). Route per the signal taxonomy (`^/.state/start.md`) and pause for the user — this is **not** an exit; the loop resumes on their ruling. (Ordinary out-of-scope findings are simply reported per step 5 and pause nothing.)

When more than one verdict is eligible in a round, precedence is **ESCALATION** (pause) → **NOT CONVERGING** → **HELD** → **CLEAN**.

Report each round's finding tuple `(criticals, highs, mediums, lows)` for legibility, so the trend is visible at a glance — but **gate on regressions, not on the count.**

## Reporting

- Before round 1, persist the frozen scope set (the path list) and the starting roster to `^/.state/tests/mileqa/YYYYMMDD-HHMM/`.
- Per round, persist `^/.state/tests/mileqa/YYYYMMDD-HHMM/round-N.md`: the roster run, findings with verdicts + severities, fixes, deferrals, checkpoint + fix commit SHAs, and **the round's aggregate-severity tuple** (so the convergence trend is legible at a glance). Final `summary.md` with the exit state.
- Final chat report: rounds run, findings by severity, fixes, residuals/deferrals, exit — re-summarized so the last message stands alone. No error tallies.

## Governance interlocks

- **Commits:** invoking `/mileqa` authorizes the checkpoint + round-fix commits on the feature branch only. It does NOT authorize push, merge, or any commit on `main`. Push stays a separate, user-instructed, scrub-gated action.
- **Panel agents are read-only.** Only the main session writes — the checkpoint/fix commits, the reports, and the fixes; panel agents never write. Destructive functional testing (e.g. `/test-burn`) is never dispatched implicitly by a panelist.
- `_`-visibility, containment, and state gravity bind all dispatched agents. Findings/reports land in this session's `^/.state/`, never a child's, unless the user gives explicit path notation.
