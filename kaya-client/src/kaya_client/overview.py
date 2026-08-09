"""ADR 0005 §contract 7's banner: what a bare invocation says about itself. **Live since KAN-549.**

    Bare `kaya` prints live state and exits `0`; `--help` still prints usage.
    No token → a structured auth error, not a stack trace.

SLICES §V2b item 4 spells "live state" out as "the executable path, a one-line description, recent
notes and the aggregate". The last two are a ``Payload`` and go through ``render`` like every other
result. The first two are this module — three lines of prose about **the tool**, carrying no fact
derived from the payload printed under them.

### Why this is not a fifth step of ``render``, and not a second renderer either

``render``'s signature is frozen by ADR 0005's sequencing rule and has now absorbed six V2b cards
unmoved. A banner is not a shaping of the result: it is not projected, not truncated, not counted
and not serialized, and there is no format in which it is a key. Routing it through ``render`` would
mean a fifth parameter — ADR 0005's stop signal — for a string that describes the process rather
than the response.

So it takes the same door `provenance.version_line` already takes, and for the same reason its
module docstring gives: *"Shaping lives in this package; it does not all live in one function."*
``version_line`` is in fact the first line of what this returns.

**The guard that keeps that honest is the signature below.** `overview` takes three ``str``
parameters and no ``Payload``. It *cannot* format a result, so "``render`` is called in exactly one
place in `kaya-cli`" stays a checkable claim rather than a habit —
`kaya-cli/tests/test_bare_invocation.py` asserts both halves, the arity here and the single call
site there.

### Why it is in the shared client rather than in `kaya-cli`

ADR 0004's review question is "would V6's MCP adapter have to reimplement this to be correct?", and
the three lines answer it differently, which is why they are split the way they are:

- **the version line** — plainly yes. It is `provenance`'s, already shared, already the way V6
  reports its own build.
- **the one-line description** — yes. "What is kaya?" has one answer for the whole suite, and an MCP
  server advertises it in its server metadata. `kaya_cli.__main__.DESCRIPTION` is *derived* from
  ``DESCRIPTION`` below rather than being a second copy, so argparse's header and the banner cannot
  drift.
- **the executable path** — no. Only an adapter with an ``argv`` has one, and what "the executable"
  even means differs between a console script, ``python -m`` and a frozen binary. So it is a
  **parameter**, exactly as ``program`` and ``version`` are parameters of ``version_line``: this
  module owns the shape of the line, the adapter owns the fact. `kaya_cli.__main__.executable_path`
  is where that fact is derived, and its docstring says which of the three answers it picks.

### The third line, and why it is static

A bare invocation shows ``RECENT_NOTES`` notes out of however many the caller owns, so the reader
has to be told a slice happened — otherwise ADR 0005 §contract 5's footer (``5 notes``, describing
**the returned set**) reads as "you have five notes". The sentence therefore names the limit and the
verb that lifts it.

It is **static text**, containing no count and no title from the payload. That is deliberate and it
is the whole reason this module can be trusted next to `render`: a banner that reported "5 of 42"
would be a second thing in the process deriving output from a payload, and the second one is always
the one that grows a projection rule. The caller who wants 42 types the command the line names, and
gets it from the one seam. See ADR 0005's 2026-08-09 (KAN-549) amendment.

### Nothing here is derived from a credential

Q41/Q42 and ADR 0002. The three inputs are a program name, a version string and a filesystem path;
no bearer, no config value and no request reaches this function.
``kaya-cli/tests/test_bare_invocation.py`` sweeps every contiguous fragment of a fake token against
the whole of a bare invocation's output, the same technique `test_config_file.py` uses on
``config show`` and `backend/tests/unit/test_log_redaction.py` uses on the access log.
"""

from kaya_client.client import RECENT_NOTES
from kaya_client.provenance import version_line

DESCRIPTION = "markdown notes, API-first"
"""The one-line description, spelled once for the whole suite.

No trailing full stop: the callers punctuate it — argparse's ``description=`` wants a sentence and
the banner's second line wants a clause — and a period baked in here produces ``API-first.."""

SEPARATOR = " — "
"""Between the executable path and what it is. An em dash, matching `truncation`'s hint and this
package's other prose; it is never a column separator, so it does not have to survive ``cut``."""


def overview(program: str, version: str, executable: str) -> str:
    """The three lines a bare invocation prints above its notes.

    **Three ``str`` parameters and no ``Payload``** — see this module's docstring. ``program`` is
    the command a user typed, ``version`` the adapter's distribution version, ``executable`` the
    path that adapter resolved for itself.

    Returned as one string with no trailing newline, like everything `serialization` produces, so
    the caller joins it to the rendered payload with the same ``BLOCK_GAP`` every other trailing
    block already uses rather than inventing a second separator.
    """
    return "\n".join(
        (
            version_line(program, version),
            f"{executable}{SEPARATOR}{DESCRIPTION}.",
            f"showing up to {RECENT_NOTES} notes, most recently updated first"
            f"{SEPARATOR}{program} note list shows all of them",
        )
    )
