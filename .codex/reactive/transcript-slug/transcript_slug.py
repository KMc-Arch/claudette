"""Claude Code transcript-store slug — ONE implementation.

Claude Code stores a project's session transcripts under
`~/.claude/projects/<slug>/`, where <slug> is the project's RESOLVED ABSOLUTE
path with every non-alphanumeric character replaced by '-'. Verified against the
real store: `/mnt/claudette/~majel` -> `-mnt-claudette--majel` (the leading slash,
the `/` separators, and the `~` all fold to `-`). The slug is always keyed on the
whole resolved path — there is no short form, so a bare `.steward` becomes
`-mnt-claudette--steward`, not `--steward`.

Callers need this identical derivation: purge (to find a project's transcript
store) and the `/roots` relink (to rename the store when a root moves out of
band); `/move-project` will need it too, once it lands on this branch, to migrate
the store on an in-session move. A second copy is the purge/cboot divergence bug a
third time, so the rule lives here and every caller loads it.

`.resolve()` is deliberate: it matches how Claude Code itself keys the store
(the resolved absolute path). That is an external key to match, not a
containment decision, so it does not follow the as-referenced rule.
"""

import re
from pathlib import Path


def project_slug(project_root):
    """The transcript-store slug for a project root (str or Path)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(project_root).resolve()))
