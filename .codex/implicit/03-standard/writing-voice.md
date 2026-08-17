# Writing Voice

How Claude writes the artifacts it maintains — abstracts, start files, specs, plans, reports, memory,
work items. Governs the durable artifact, not conversation.

---

## Rules

1. **Write what is so and what to do.** Current state, standing authorizations, proven mechanisms, the
   next action. A reader who has never seen the session must be able to act from the text alone.
2. **Prefer the positive form.** "Client systems are production — get per-action permission before any
   write" beats a list of don'ts. "Approval is a human act" beats "the machine must not approve."
3. **Cut the self-correction layer.** `RETRACTED`, `I misread`, `NOT this`, "earlier I thought" — an
   artifact records the conclusion, not the path to it. A superseded decision is rewritten, not annotated
   with its own history.
4. **Session narrative belongs in the register that holds narrative** — traces, pauses, `work/` entries —
   never in an orientation document.
5. **Rewrite rather than patch** any artifact whose job is synthesis. Patching accretes; a rewrite forces
   the judgment about what still matters. This is why `state-abstract.md` is rewritten from scratch every
   time (`^/.codex/explicit/milestone/start.md`).

## The exception, and it is load-bearing

**Where the prohibition is the content, keep it negative, verbatim, and enumerated.**

An invariant, an enforcement boundary, a hold, a guard's deny list, a safety constraint: the forbidden
case is the claim being made, and the positive paraphrase is strictly weaker.

- `No path produces a commit on a default branch` — the positive rewrite ("commit to feature branches")
  recommends the good case without forbidding the bad one.
- **ABSOLUTE HOLD** and **CONFIRMED HOLD** (`^/CLAUDE.md`) are definitionally prohibitions.
- A guard's deny list is auditable precisely because each refused form is written out.

The test: **can a reviewer check compliance against this sentence?** If the negative is what makes the
check possible, the negative stays. Rule 2 is about tone in prose; it never rewrites a constraint.

## Why

The artifacts here are read cold — by the next session, by a child project, by a person the next
morning. A lean directive synthesis is a better pickup than a defensive changelog, and the difference
compounds: every hedge and retraction carried forward is read again by everyone who reads the file.

*Operator directive, 2026-08-17. Origin: the same rule proved out in a sibling project, adopted here
with the enforcement-boundary exception added.*
