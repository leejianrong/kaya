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
"""

from typing import Any


class KayaError(Exception):
    """Base for everything this package raises. An adapter can catch exactly this."""


class UnknownFormat(KayaError, ValueError):
    """``fmt`` named a serializer that does not exist.

    A ``ValueError`` as well, because the adapter's job is to turn this into ADR 0005's exit `2`
    (usage) and a bad ``--format`` value is argv being wrong, not the API.
    """


class TransportError(KayaError):
    """The API could not be *asked* — DNS, connection refused, timeout, TLS.

    Distinct from ``ApiError`` for the reason ``UpstreamUnavailable`` is distinct from a `401` in
    `app/auth/`: "kaya is unreachable" and "kaya said no" are different facts, and collapsing them
    tells the caller their token is bad when their wifi is off.

    This is also where KAN-666's fallback would land if the measurement asks for it. Retry with
    backoff belongs around ``KayaClient._request``, whose only failure mode is this class — see the
    note there. Nothing retries today.
    """


class ApiError(KayaError):
    """The API answered, and the answer was a refusal.

    ``payload`` is the whole ``{"error": {…}}`` object as it arrived. ``code`` and ``message`` are
    conveniences over it; ``status`` is the HTTP status, which the adapter needs because ADR 0005's
    exit-code table is keyed on meaning (`401`→3, `403`→4, `404`→5) rather than on the code string
    for those three.
    """

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload
        error = payload.get("error")
        detail: dict[str, Any] = dict(error) if isinstance(error, dict) else {}
        self.code: str = str(detail.get("code", "http_error"))
        self.message: str = str(detail.get("message", f"the API answered {status}"))
        super().__init__(f"{status} {self.code}: {self.message}")
