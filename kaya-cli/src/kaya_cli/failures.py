"""ADR 0005 §contract 4's exit-code table, and the one place a failure becomes a process result.

### Why this is the *only* shaping-adjacent thing in `kaya-cli`

ADR 0004's review question is "why isn't this in the client?", and the test that settles it is
whether V6's MCP adapter would have to reimplement the piece to be correct. Run it over the two
halves of KAN-542 and they come apart cleanly:

- **The error object and its rendering** — ``{"error": {"code", "message", "arg", …}}`` and the
  ``error<TAB>…`` row — would have to be rebuilt in `mcp/` to report a refusal in the shape a
  consumer already knows. So it is in `kaya_client.errors` / `kaya_client.serialization`, and this
  module imports it rather than owning a byte of it. Pandan put its shaping in its CLI and its MCP
  adapter inherited none of it; the whole of V2a exists so that cannot happen twice.
- **Code → exit number** would not. An MCP tool returns content to a host; it has no process to
  exit and no status to return, so an exit table in the client would be a table with exactly one
  consumer, living one package away from it. It is here.

The seam between them is exactly where the two audiences differ, which is the test passing rather
than a coincidence.

### The table is add-only

A code string is a published contract from the moment it reaches stdout (ADR 0005: "do not renumber
them"). Adding a row is adding a meaning and is free. **Changing a row's number is breaking a
contract a script already depends on** — the caller who wrote ``if [ $? -eq 5 ]`` around a `404` is
the reason the numbers came from pandan verbatim rather than being invented here.
``tests/test_exit_codes.py`` pins each shipped row by literal value and each constant by literal
value, so a renumber is a red test naming the meaning that moved, and a new row reddens nothing.

### Two lookups, and which wins

``EXIT_FOR_STATUS`` is consulted first for an ``ApiError`` and ``EXIT_FOR_CODE`` second, because
`kaya_client.errors` already settled that ADR 0005's table "is keyed on meaning (`401`→3, `403`→4,
`404`→5) rather than on the code string for those three". The backend's code vocabulary grows
without this package's knowledge — ``note_not_found`` today, something else beside it tomorrow — and
a new `404` code must still exit `5`. Keying a refusal on its status is the only version of that
which cannot go stale. The code table then covers everything that never had a status: a bad flag, an
unreachable API, a format nobody registered.

Anything unrecognised is exit `1`. Not `2`: a failure this table has no row for is not evidence that
argv was wrong, and reporting "usage" for an unmapped `422` would send a caller to re-read the
manual over a server-side refusal.
"""

import sys
from collections.abc import Mapping
from types import MappingProxyType
from typing import IO

from kaya_client import ApiError, Format, render_error

EXIT_OK = 0
"""Nothing failed."""

EXIT_RUNTIME = 1
"""Something failed and no more specific meaning applies — the unreachable API, an unmapped code."""

EXIT_USAGE = 2
"""argv was rejected. Argparse's own number, which is why it is `2` and not something tidier."""

EXIT_UNAUTHENTICATED = 3
"""`401`. The credential is missing, malformed or rejected — re-authenticating may usefully help."""

EXIT_FORBIDDEN = 4
"""`403`. The credential is fine and the answer is still no; re-authenticating changes nothing."""

EXIT_NOT_FOUND = 5
"""`404`. Distinct from `4` because "not yours" and "not there" lead a script to different actions,
and `app/auth/authorization.py` goes to real trouble to keep them distinguishable."""

EXIT_FOR_CODE: Mapping[str, int] = MappingProxyType(
    {
        "usage": EXIT_USAGE,
        "unreachable": EXIT_RUNTIME,
        "runtime": EXIT_RUNTIME,
    }
)
"""The named-code table. **Add-only**: a row may be added, never renumbered.

Keys are ``KayaError.code`` values from `kaya_client.errors`, which is why a raise site picks a
meaning and never a number — ``raise TransportError(…)`` names ``unreachable`` and this dict decides
what that costs. Read-only at runtime as well as by rule, so a verb cannot register a code by
mutating the table from the outside; adding one is editing this file, in a diff a reviewer sees.
"""

EXIT_FOR_STATUS: Mapping[int, int] = MappingProxyType(
    {
        401: EXIT_UNAUTHENTICATED,
        403: EXIT_FORBIDDEN,
        404: EXIT_NOT_FOUND,
    }
)
"""ADR 0005's three status-keyed meanings. Consulted before ``EXIT_FOR_CODE`` for an ``ApiError``,
for the reason in this module's docstring: the API's code vocabulary grows and its statuses do not.
"""


def exit_code_for(failure: BaseException) -> int:
    """The process exit code for a failure. The only function that turns a meaning into a number."""
    if isinstance(failure, ApiError):
        by_status = EXIT_FOR_STATUS.get(failure.status)
        if by_status is not None:
            return by_status

    code = getattr(failure, "code", "")
    return EXIT_FOR_CODE.get(str(code), EXIT_RUNTIME)


def report(
    failure: BaseException,
    *,
    fmt: str = Format.HUMAN,
    stream: IO[str] | None = None,
) -> int:
    """Print the structured error and return its exit code. Every CLI failure path ends here.

    **stdout, deliberately.** ADR 0005 §contract 3 puts the structured row on stdout so an agent
    reading the CLI does not have to merge two streams to find out what happened — the interesting
    case being a failure *after* partial success, where the row and the rows above it arrive in one
    ordered stream. Only the human ``usage:`` text stays on stderr, and `kaya_cli.parsing` is what
    puts it there.

    ``stream`` defaults to whatever ``sys.stdout`` is **at call time** rather than at import, so a
    test's ``capsys`` and a real pipe are the same code path.
    """
    rendered = render_error(failure, fmt=fmt)
    print(rendered, file=stream if stream is not None else sys.stdout)
    return exit_code_for(failure)
