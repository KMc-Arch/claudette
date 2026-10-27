---
version: 1
---

# domain-modeling overrides

- **Glossary:** `^/.state/memory/reference/glossary.md`, created lazily per upstream, in the format of
  `skills/domain-modeling/GLOSSARY-FORMAT.md`. Keep it free of implementation detail, as upstream says.
  Add it to `^/.state/memory/reference/start.md` when it is first created.
- **Decisions (ADRs):** apply upstream's three-part test (hard to reverse, surprising without context,
  a real trade-off). When a decision passes, record it as an entry in the matching
  `^/.state/memory/decisions/decisions-*.md`, matching that file's style. Use the headings of
  `ADR-FORMAT.md` only if the file has no established style. Never create `docs/adr/`.
- **Cross-reference with code:** see `common.md`. In zdm, the redesign artifacts are the reference,
  not the harvest-only code.
- **Conflicts:** surface a contradiction with a recorded decision explicitly, per upstream's "flag
  ADR conflicts" rule, naming the decision file and entry.
