---
version: 1
---

# govgen tests

`python test_govgen.py` — determinism, budget, root resolution (rooted / unrooted-warn / missing), contract-block resolution, frontmatter list parsing. Fixtures are built in OS temp dirs at runtime (never in-tree — a `root: true` fixture inside the codex would pollute the cboot root inventory).
