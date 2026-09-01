"""Claude Code transcript-store slug — ONE implementation.

Claude Code stores a project's session transcripts under
`~/.claude/projects/<slug>/`, where <slug> is the project's RESOLVED ABSOLUTE
path with every non-alphanumeric character replaced by '-'. Verified against the
real store: `/mnt/claudette/~majel` -> `-mnt-claudette--majel` (the leading slash,
the `/` separators, and the `~` all fold to `-`). The slug is always keyed on the
whole resolved path — there is no short form, so a bare `~majel` is keyed as
`-mnt-claudette--majel`, never `--majel`.

Callers need this identical derivation: purge (to find a project's transcript
store) and the `/roots` relink (to rename the store when a root moves out of
band); `/move-project` will need it too, once it lands on this branch, to migrate
the store on an in-session move. A second copy is the purge/cboot divergence bug a
third time, so the rule lives here and every caller loads it.

`.resolve()` is deliberate: it matches how Claude Code itself keys the store
(the resolved absolute path). That is an external key to match, not a
containment decision, so it does not follow the as-referenced rule.

NON-GOAL — ONE path system only (RUL-028). This derives one slug in one path
system, and Claudette's platform is the WSL claude-context store, which
project_slug() matches. Cross-platform project migration -- the WSL distro
(/mnt/claudette -> -mnt-... slugs) <-> native Windows (D:\\claudette -> D--...
slugs) -- is OUT OF SCOPE and must NOT be reconciled here: the two stores are
deliberately distinct. An out-of-band cross-platform move fails safe (unlinked
on the destination, orphaned on the source, both reported by /roots).
"""

import re
from pathlib import Path


def project_slug(project_root):
    """The transcript-store slug for a project root (str or Path)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(project_root).resolve()))
