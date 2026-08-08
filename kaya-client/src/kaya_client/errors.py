"""Every failure an adapter can see, and nothing httpx-shaped among them.

ADR 0004 says an adapter owns only how it gets its arguments. That has a consequence nobody writes
down: an adapter that has to catch ``httpx.HTTPStatusError`` has learned the transport, and the next
thing it learns is how to format the error. So the transport stops here. `kaya-cli` and `mcp` import
from this module and never from ``httpx``.

``ApiError`` carries the API's error object through **unflattened**. `app/api/errors.py` settled the
wire shape as ``{"error": {"code", "message", …}}`` specifically so that "``kaya-client`` forwards a
body rather than unwrapping one", and the ``…`` is load-bearing: ADR 0009's `409` puts two whole
notes in there. An exception that kept only ``code`` and ``message`` would drop the half of that
response the caller needs to act on.

**No exception message here may contain a bearer.** The same rule as `backend/app/observability/`,
for the same reason — an exception string reaches a log, a traceback and, in the CLI, stdout. The
client never puts the token in a message, and ``TransportError`` wraps httpx's own message, which
carries the URL and never the headers (the reasoning `app/auth/upstream.py` already relies on).

### The named code, and why it is a class attribute

ADR 0005 §contract 4 says an adapter branches "on the stable ``code`` string, never on message
text", and KAN-542's rule is that a raise site picks a **meaning** and never a number. Both follow
from one arrangement: every class below carries a ``code``, so ``raise TransportError(…)`` *is* the
act of naming ``unreachable``, and the CLI's exit table is a lookup on that string rather than a
judgement made at the raise site. Adding a failure class is adding a code, which is adding a row —
the table is add-only, and `kaya-cli/tests/test_exit_codes.py` fails if a class arrives without one.

The code strings themselves live here, in the shared client, rather than in `kaya-cli`. They are
what appears in the wire-visible error object, so an adapter that invented its own would be
publishing a second vocabulary for the same failure — ADR 0004's drift, in the one place a consumer
is explicitly told to branch.

### ``error_payload``, and why the shape is the client's job

``error_payload`` is the single builder for the adapter-facing ``{"error": {…}}`` object, and it is
the mirror of `backend/app/api/errors.py`'s ``error_body``: same shape, same keys, one on the wire
and one at the CLI/MCP boundary. It lives here for the reason ADR 0004 gives — apply the review
question ("why isn't this in the client?") and the answer is that V6's MCP adapter has to report a
refusal in exactly this shape, and a copy in `mcp/` would be the second implementation that drifts.
Serialization of it is `serialization.serialize_error`; the two halves are deliberately apart so the
shape can be asserted without going through a formatter.
"""

from typing import Any, ClassVar

CODE_KEY = "code"
MESSAGE_KEY = "message"
ARG_KEY = "arg"

CONTRACT_KEYS: tuple[str, ...] = (CODE_KEY, MESSAGE_KEY, ARG_KEY)
"""ADR 0005 §contract 3's "all keys always present", named once.

These three are guaranteed on every error object this package emits, whatever produced it. A key
that vanishes when it is empty forces every consumer to write a conditional, and a consumer writing
a conditional around an error path is a consumer writing an untested branch.

The set is deliberately *these three and no more*. ``status`` is not among them because a
``TransportError`` has none and inventing a zero would be worse than its absence; anything else the
API attached is passed through unflattened alongside them.
"""


class KayaError(Exception):
    """Base for everything this package raises. An adapter can catch exactly this.

    ``code`` is the stable string ADR 0005 tells consumers to branch on, and it is a class attribute
    so that choosing the class *is* choosing the meaning. ``arg`` is contract 3's single-argument
    slot — the one scalar a refusal is usually *about* (the flag, the field, the ref).
    """

    code: ClassVar[str] = "runtime"
    arg: str = ""

    def __init__(self, *args: object, arg: str = "") -> None:
        super().__init__(*args)
        if arg:
            self.arg = arg


class UsageError(KayaError):
    """argv was wrong — an unknown flag, a missing argument, a value outside an enum.

    Lives in the client rather than in `kaya-cli` because ``usage`` is a published *code string*
    (it reaches stdout and a consumer branches on it), and a code string invented separately in each
    adapter is exactly the drift ADR 0004 forbids. The **interception** of argparse is the adapter's
    — `kaya_cli.parsing` — because only an adapter has an argv.
    """

    code: ClassVar[str] = "usage"


class UnknownFormat(UsageError, ValueError):
    """``fmt`` named a serializer that does not exist.

    A ``UsageError``, and therefore ADR 0005's exit `2`: a bad ``--format`` value is argv being
    wrong, not the API. Still a ``ValueError`` as well, so an adapter that never imported this
    package's base class already catches it.
    """


class TransportError(KayaError):
    """The API could not be *asked* — DNS, connection refused, timeout, TLS.

    Distinct from ``ApiError`` for the reason ``UpstreamUnavailable`` is distinct from a `401` in
    `app/auth/`: "kaya is unreachable" and "kaya said no" are different facts, and collapsing them
    tells the caller their token is bad when their wifi is off. Under ADR 0005's table that
    difference is exit `1` against exit `3`, and a script reacting to `3` discards a working
    credential.

    This is also where KAN-666's fallback would land if the measurement asks for it. Retry with
    backoff belongs around ``KayaClient._request``, whose only failure mode is this class — see the
    note there. Nothing retries today.
    """

    code: ClassVar[str] = "unreachable"


class ApiError(KayaError):
    """The API answered, and the answer was a refusal.

    ``payload`` is the whole ``{"error": {…}}`` object as it arrived. ``code`` and ``message`` are
    conveniences over it; ``status`` is the HTTP status, which the adapter needs because ADR 0005's
    exit-code table is keyed on meaning (`401`→3, `403`→4, `404`→5) rather than on the code string
    for those three.

    ``code`` shadows the class attribute with the API's own string — ``note_not_found``,
    ``invalid_token`` — because that is what a consumer branches on and what the backend will keep
    stable. It is *not* what the exit table is keyed on for a refusal: the backend's code vocabulary
    grows without this package's knowledge, and a new `404` code must still exit `5`. See
    `kaya_cli.failures`.
    """

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload
        error = payload.get("error")
        detail: dict[str, Any] = dict(error) if isinstance(error, dict) else {}
        self.code: str = str(detail.get(CODE_KEY, "http_error"))
        self.message: str = str(detail.get(MESSAGE_KEY, f"the API answered {status}"))
        super().__init__(f"{status} {self.code}: {self.message}")


def error_payload(failure: BaseException) -> dict[str, Any]:
    """Any failure as **the** error object: ``{"error": {"code", "message", "arg", …}}``.

    The single builder on this side of the wire, and the only thing that decides what an error looks
    like. Both adapters call it; neither reimplements it (ADR 0004).

    Three guarantees, in the order they matter:

    1. ``code``, ``message`` and ``arg`` are always present, always strings, and always first — so a
       consumer never writes ``if "arg" in error``.
    2. Everything else the API attached survives **unflattened**. ADR 0009's `409` carries two whole
       notes under ``attempted`` and ``stored``; an error object that kept only the three contract
       keys would drop the half of that response a client acts on.
    3. Nothing is added that the failure did not carry. A non-``KayaError`` exception — which should
       not reach here, but will one day — degrades to ``runtime`` plus its own ``str``.
    """
    detail: dict[str, Any] = {}
    if isinstance(failure, ApiError):
        error = failure.payload.get("error")
        if isinstance(error, dict):
            detail = dict(error)

    code = str(detail.pop(CODE_KEY, None) or getattr(failure, CODE_KEY, None) or "runtime")
    message = str(detail.pop(MESSAGE_KEY, None) or str(failure) or code)
    arg = str(detail.pop(ARG_KEY, None) or getattr(failure, ARG_KEY, "") or _implied_arg(detail))

    return {"error": {CODE_KEY: code, MESSAGE_KEY: message, ARG_KEY: arg, **detail}}


def _implied_arg(detail: dict[str, Any]) -> str:
    """Contract 3's ``arg`` slot, filled from the refusal's own first scalar detail.

    The backend attaches at most one scalar to a refusal and it is always the thing the refusal is
    *about* — ``ref`` on a bad identifier, ``field`` on a `422`, ``upstream`` on Q9's `503`. Reading
    the first scalar rather than consulting a list of blessed key names is the same discipline as
    ``Payload.field_names``: a vocabulary derived from the payload cannot drift from the API, and a
    list here would go stale the day the backend adds a code nobody updated this file for.

    A refusal whose only extras are *objects* — ADR 0009's `409` — yields ``""``, which is correct.
    Two whole notes do not fit in a tab-separated column, and they are still there in full under a
    structured format. An empty ``arg`` is a value, not a missing key.
    """
    for value in detail.values():
        if isinstance(value, str | int | float) and not isinstance(value, bool):
            return str(value)
    return ""
