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

### Why `400` is a *row* rather than an exception to that rule (KAN-718)

`400` is the one status that is definitionally the caller's input being rejected, so it is the one
status the unmapped default gets wrong. ADR 0008 makes ``#NOTE-12`` a `400` **by design** — the
central ref resolver refuses a malformed identifier rather than answering `404` about a string that
is not a note reference at all — so the CLI meets it routinely rather than exceptionally, and the
default sent it to `1`. "Runtime" tells a script something went wrong on kaya's side, and a script
branching on exit codes would plausibly *retry* a runtime failure that can never succeed.

It is a row in ``EXIT_FOR_STATUS`` and **not** a row in ``EXIT_FOR_CODE``. Keying it on
``invalid_note_ref`` would be the narrower fix and the wrong one for the reason directly above: the
backend's code vocabulary grows without this package's knowledge, and the next `400` code — a
malformed cursor, a rejected path — must exit `2` without anybody remembering to add it. The default
for everything else stays `1`, because only `400` carries that meaning in its status alone.

### Why `409` is a *row*, and the one status that needed a number of its own (KAN-724)

`409` is where the default's two available answers are both wrong. It is not kaya failing, so `1` is
a lie; and the precondition was *correct when it was read*, so `2` would send a caller back to
re-read its own command line over a race it had no way to avoid — the direction KAN-718 was explicit
about not widening `2` into. What a `409` caller should do is re-read and retry, and ADR 0009's body
is built for exactly that: the refusal carries ``attempted`` and ``stored`` as two whole notes, so
the merge is available from one command's output. None of it is reachable from `1`, because a script
must read `1` as "kaya failed" — so it either retries the same stale precondition forever or
abandons a conflict it could have resolved.

That the code string is on stdout is not the answer to this. `401`, `403` and `404` are equally
derivable from it and have numbers anyway; the table exists so a shell can branch on ``$?`` without
parsing stdout at all.

It is a row in ``EXIT_FOR_STATUS`` and **not** in ``EXIT_FOR_CODE``, for the reason `400` is:
``note_conflict`` is today's only `409` code and the backend's vocabulary grows without this
package's knowledge, so the next one must exit `6` without anybody remembering to add it. The
default for everything else — `422`, `503`, whatever arrives next — is still `1`, and adding a row
is still the only way out of it.
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
"""The caller's input was rejected — by argparse, or by the API (`400`). Argparse's own number,
which is why it is `2` and not something tidier. KAN-718 widened the *meaning* without moving the
number: a malformed ref is the caller's error wherever it is caught, and which layer noticed is not
a fact a script should have to branch on."""

EXIT_UNAUTHENTICATED = 3
"""`401`. The credential is missing, malformed or rejected — re-authenticating may usefully help."""

EXIT_FORBIDDEN = 4
"""`403`. The credential is fine and the answer is still no; re-authenticating changes nothing."""

EXIT_NOT_FOUND = 5
"""`404`. Distinct from `4` because "not yours" and "not there" lead a script to different actions,
and `app/auth/authorization.py` goes to real trouble to keep them distinguishable."""

EXIT_CONFLICT = 6
"""`409`. The write was refused because the note moved under it (ADR 0009), and **nothing was
written**. KAN-724's addition, and the only meaning that needed a number rather than a reused one:
the caller did nothing wrong, kaya did not fail, and the action a script should take — re-read,
merge the ``attempted``/``stored`` pair the refusal carries, retry — is reachable from neither `1`
nor `2`. It is keyed on the *status* rather than on ``note_conflict``, so a second `409` code
arriving in the backend's vocabulary exits `6` without this package being told."""

EXIT_FOR_CODE: Mapping[str, int] = MappingProxyType(
    {
        "usage": EXIT_USAGE,
        "unreachable": EXIT_RUNTIME,
        "no_credential": EXIT_RUNTIME,
        "runtime": EXIT_RUNTIME,
    }
)
"""The named-code table. **Add-only**: a row may be added, never renumbered.

Keys are ``KayaError.code`` values from `kaya_client.errors`, which is why a raise site picks a
meaning and never a number — ``raise TransportError(…)`` names ``unreachable`` and this dict decides
what that costs. Read-only at runtime as well as by rule, so a verb cannot register a code by
mutating the table from the outside; adding one is editing this file, in a diff a reviewer sees.

``no_credential`` is KAN-541's addition and is `1`, not `3`, per SLICES §V2a's failure table. A
missing ``KAYA_TOKEN`` is not a rejected credential: nothing was refused because nothing was asked,
and a script that re-authenticated on `3` would be minting a PAT to replace one that was never
presented. The distinction is the same one `errors.py` draws between ``TransportError`` and a `401`.
"""

EXIT_FOR_STATUS: Mapping[int, int] = MappingProxyType(
    {
        400: EXIT_USAGE,
        401: EXIT_UNAUTHENTICATED,
        403: EXIT_FORBIDDEN,
        404: EXIT_NOT_FOUND,
        409: EXIT_CONFLICT,
    }
)
"""ADR 0005's status-keyed meanings. Consulted before ``EXIT_FOR_CODE`` for an ``ApiError``, for the
reason in this module's docstring: the API's code vocabulary grows and its statuses do not.

``400`` is KAN-718's addition and reuses ``EXIT_USAGE``, which is an **addition to this table**, not
a renumber — no shipped number moved, and ADR 0005's add-only rule permits exactly this. See the
module docstring for why it is keyed on the status rather than on ``invalid_note_ref``.

``409`` is KAN-724's addition and is the one row that brought a *new* number with it. Also an
addition and not a renumber, for the same reason and with the same proof — and a seventh meaning is
not what ADR 0005 warned against, because there was no existing number for "the note moved under
you". Mapping it onto one there was would have been the change that broke the sameness. Pandan's
matching change is tracked as KAN-831 on its board 5; until it lands, a `409` from pandan's CLI is
still its own unmapped `1`.
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
