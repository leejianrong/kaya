"""One log line per request, one id to correlate everything else by.

Written as a raw ASGI middleware rather than a ``BaseHTTPMiddleware`` subclass. Starlette's
``BaseHTTPMiddleware`` runs the downstream app inside its own anyio task and buffers the response
through a memory stream; both are avoidable complications for something whose entire job is to
read a header, set a context variable and time the call. Raw ASGI is also the only form that sees
the response *status* without owning the response object.

**Position matters.** Starlette wraps the stack as ``ServerErrorMiddleware`` → user middleware →
``ExceptionMiddleware`` → router. So by the time control returns here, an ``HTTPException`` raised
by a route or by ``app/auth/`` has already become a real response with a real status code — which
is why a `401` or Q9's `503` shows up in the access line as itself rather than as an exception.
What passes *through* here as an exception is only the genuinely unhandled kind, and it keeps
going: this records it and re-raises unchanged, so ``ServerErrorMiddleware`` still produces the
`500`. ``app/api/errors.py`` explains at length why kaya installs no handler for an unhandled
exception, and that decision is about the *response body*. Nothing here formats one.

**What is logged is an allowlist, and that is the primary defence for ADR 0002.**
``app.observability.redaction`` is a backstop that recognises credential-shaped text; the reason it
so rarely has anything to do is that this file never assembles the credential in the first place.
``ACCESS_FIELDS`` is the whole set, ``tests/unit/test_log_redaction.py`` pins it, and two omissions
in it are deliberate:

- **No headers, of any name.** Not a denylist with ``Authorization`` removed — a denylist is a list
  someone extends without thinking, and the next header carrying a credential will not be called
  ``Authorization``.
- **No query string.** Kaya's API takes its credential in a header and never in a URL (ADR 0002),
  but a query string is the classic place a credential arrives by accident — a copied ``?token=``,
  a client library with a fallback — and logging it is how that accident becomes permanent. The
  path is enough to identify the route.
"""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import MutableHeaders

from app.observability.logs import REQUEST_ID, get_logger

REQUEST_ID_HEADER = "x-request-id"
"""Read on the way in, and always set on the way out.

Honoured from the client so a request that crossed the SPA, an ingress or another service can be
followed through kaya under the id it already had. Echoed back so a caller reporting a problem has
something to quote — the id is the only thing that connects "it failed for me at 14:02" to a line
in the pod's log.
"""

_ACCEPTABLE_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")
"""An inbound id is attacker-controlled text that ends up in every log line for that request.

JSON encoding already makes forging a second log line impossible — a newline inside a string is
``\\n``, not a line break — so this is not the injection guard it would have to be for a plain-text
format. It is a sanity bound: anything unrecognisable is replaced rather than rejected, because a
malformed correlation id is not worth failing a request over.
"""

ACCESS_FIELDS = ("method", "path", "status", "duration_ms", "client")
"""Every field the access line carries, and the list a reviewer should have to argue with.

Pinned by ``test_the_access_line_carries_only_the_allowlisted_fields``. Adding a field is allowed;
adding one without noticing is not.
"""

HEALTH_PATH = "/health"
"""Logged at DEBUG rather than INFO.

The liveness probe hits it every few seconds forever (``deploy/k8s/base/deployment.yaml``), and a
log where 99% of the lines are the kubelet is a log nobody reads. It is still *logged* — turn
``KAYA_LOG_LEVEL`` down to ``DEBUG`` and the probe traffic is there.
"""

_logger = get_logger("access")

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def request_id_from(scope: Scope) -> str:
    """The inbound ``X-Request-Id`` if it is usable, otherwise a fresh one."""
    for raw_name, raw_value in scope.get("headers", ()):
        if raw_name.decode("latin-1").lower() != REQUEST_ID_HEADER:
            continue
        candidate = raw_value.decode("latin-1")
        if _ACCEPTABLE_ID.match(candidate):
            return candidate
        break
    return uuid.uuid4().hex


def _client(scope: Scope) -> str | None:
    client = scope.get("client")
    return client[0] if client else None


class RequestLogMiddleware:
    """Times each request, logs one line for it, and gives everything in it a shared id."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Lifespan and websocket scopes have no status and no path in the sense used below.
            # Kaya serves no websockets; a lifespan message logged as a request would be a lie.
            await self.app(scope, receive, send)
            return

        request_id = request_id_from(scope)
        reset_token = REQUEST_ID.set(request_id)
        started = time.perf_counter()

        # 500 is the honest default rather than a pessimistic one: if no `http.response.start` is
        # ever sent, the request died without producing a status, and that is what happened.
        status = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Visibility, then out of the way. `logger.exception` attaches the traceback, and the
            # context variable is still set, so this line and the access line below share an id
            # the operator can grep for. The exception itself is re-raised untouched.
            _logger.exception(
                "unhandled exception",
                extra={"method": scope.get("method"), "path": scope.get("path")},
            )
            raise
        finally:
            # In `finally` so a request that failed is still counted and still timed. This runs
            # before the re-raised exception leaves the frame.
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            method = scope.get("method", "")
            path = scope.get("path", "")
            _logger.log(
                logging.DEBUG if path == HEALTH_PATH else logging.INFO,
                "%s %s %s",
                method,
                path,
                status,
                extra={
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": duration_ms,
                    "client": _client(scope),
                },
            )
            REQUEST_ID.reset(reset_token)
