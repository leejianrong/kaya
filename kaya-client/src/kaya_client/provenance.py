"""Which build am I? One answer, shared by every adapter.

ADR 0007 §1 fixes two strings and forbids a third:

    kaya 0.2.0 (a1b2c3d)                              a released artifact
    kaya 0.2.0 (source checkout, not a released build)  a working tree
    kaya 0.2.0                                          never — this is the bug

Pandan printed the bare third form, a stale binary became indistinguishable from current source,
and it cost two false bug reports (`KAN-435`). The explanatory clause is the deliverable, not
decoration: silence is what made the staleness undetectable.

### Why this lives in `kaya-client` rather than in the CLI

Formatting a line a user reads is a shaping decision, and ADR 0004 puts shaping in the shared
client so no adapter reimplements it. Provenance is the same argument with a second reason on top:
the sha is a fact about the *repository*, and both adapters are built from the same commit, so
there is exactly one stamp for the whole suite (`_build_stamp.py`, which lives here because
`kaya-cli` and `mcp` both already depend on this package and neither depends on the other). When
V6 stands the MCP server up it reports provenance by calling `version_line("kaya-mcp", …)` — it
does not grow its own copy of the string, and a copy appearing in `kaya-cli/` or `mcp/` is the bug
ADR 0004 exists to prevent.

It does *not* go through `render()`. `render` takes a `Payload` from the API and ADR 0005 freezes
its signature until V2b; routing a build fact through it would mean a fifth parameter, which is the
precise signal ADR 0005 says to stop on. Shaping lives in this package; it does not all live in one
function.

### The failure direction

`build_sha()` validates rather than trusts. Empty, whitespace, `unknown`, an unexpanded
`${GITHUB_SHA}`, a non-hex word, something too short to be a sha, or git's all-zero null sha all
resolve to `None`, and `None` prints the source-checkout form. A build that cannot say what it is
says *that*; it never invents a plausible sha, and it never prints an empty pair of brackets that a
reader would have to interpret. `scripts/stamp-build.sh` applies the same rule on the way in, so
the two ends agree by construction.
"""

import re

from kaya_client._build_stamp import COMMIT

#: What `--version` says when there is no usable stamp. ADR 0007 §1 fixes the wording; a test
#: asserts the whole line, so changing it is a deliberate act rather than a typo that ships.
SOURCE_CHECKOUT = "source checkout, not a released build"

#: How much of the sha a human reads. `git rev-parse --short` and GitHub's UI both default to
#: seven, and KAN-544's gate compares against `${GITHUB_SHA:0:7}`.
SHORT_SHA_LENGTH = 7

# Lowercase hex only, because that is what git writes and what `$GITHUB_SHA` carries. Seven is the
# shortest thing anyone abbreviates a sha to; forty is a whole one.
_SHA = re.compile(r"\A[0-9a-f]{7,40}\Z")

# Git's "nothing here" sha. It is valid hex and would otherwise sail through as provenance.
_NULL_SHA = "0" * 40


def build_sha() -> str | None:
    """The commit this build was stamped with, or ``None`` when it wasn't stamped.

    ``None`` is the safe answer and the only fallback: an unstamped, half-stamped or nonsense
    stamp is *not a release*, and saying so is the entire guarantee ADR 0007 buys.
    """
    stamped = COMMIT.strip()
    if not _SHA.fullmatch(stamped) or stamped == _NULL_SHA[: len(stamped)]:
        return None
    return stamped


def version_line(program: str, version: str) -> str:
    """The exact line ``<program> --version`` prints. One of ADR 0007 §1's two forms, always.

    ``program`` is the command a user typed (``kaya``), ``version`` the distribution's version.
    The sha is shared across the suite; the version is not, which is why the caller supplies it.
    """
    sha = build_sha()
    provenance = sha[:SHORT_SHA_LENGTH] if sha else SOURCE_CHECKOUT
    return f"{program} {version} ({provenance})"
