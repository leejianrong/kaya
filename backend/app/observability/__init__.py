"""Seeing kaya run: structured logs on stdout, a request id, and a visible unhandled exception.

KAN-700, and the card exists as much for the *absence of a decision* as for the absence of code.
"logging", "observability", "metrics" and "error tracking" appeared nowhere in PLAN, QUESTIONS or
SLICES — this was never deferred, it was never raised. It is Q41 in ``docs/QUESTIONS.md`` now,
including the parts deliberately left out.

Three modules, layered one way: ``redaction`` ← ``logs`` ← ``middleware``.

- ``redaction`` — the credential scrubber, applied at serialization so no call site has to
  remember it exists. This is the file to read first; it is the one with ADR 0002 in it.
- ``logs`` — the JSON formatter, the stdout handler, and the request-id context variable.
- ``middleware`` — one access line per request, an id propagated through it, and an unhandled
  exception recorded (not handled) on its way out.

**What is deliberately not here.** No metrics endpoint: kaya has no Prometheus to scrape it and no
hosted deploy to scrape it from (ADR 0010), and an unscraped `/metrics` is a surface to secure for
no reader. No error-tracking client: a Sentry DSN is configuration for an environment that does
not exist yet, and ADR 0001's dependency list is short on purpose. No sampling: at this traffic,
sampling would only lose the one request somebody is asking about.
"""

from fastapi import FastAPI

from app.config import effective_overrides, get_settings
from app.observability.logs import (
    REQUEST_ID,
    JsonFormatter,
    StdoutHandler,
    configure_logging,
    get_logger,
)
from app.observability.middleware import (
    ACCESS_FIELDS,
    REQUEST_ID_HEADER,
    RequestLogMiddleware,
)
from app.observability.redaction import REDACTED, SENSITIVE_HEADERS, scrub, scrub_text

__all__ = [
    "ACCESS_FIELDS",
    "REDACTED",
    "REQUEST_ID",
    "REQUEST_ID_HEADER",
    "SENSITIVE_HEADERS",
    "JsonFormatter",
    "RequestLogMiddleware",
    "StdoutHandler",
    "configure_logging",
    "get_logger",
    "install_observability",
    "scrub",
    "scrub_text",
]


def install_observability(app: FastAPI) -> None:
    """Configure logging, add the request middleware, and log which settings are non-default.

    Takes the app rather than reaching for ``app.main``, for the same reason
    ``install_error_handlers`` does: a test stands up the real surface on its own ``FastAPI()``
    without the real settings, and an installer that knew about the singleton could not be used
    that way.
    """
    configure_logging()
    _log_effective_settings()
    app.add_middleware(RequestLogMiddleware)


def _log_effective_settings() -> None:
    """One startup line naming every ``Settings`` field that differs from its documented default.

    KAN-968. ``app.config.effective_overrides`` already refuses ``database_url`` (it embeds a
    credential in its userinfo) and there is no token/bearer field on ``Settings`` to leak in the
    first place, so this passes only plain strings and numbers. It still goes through the same
    ``get_logger`` → ``JsonFormatter`` → ``scrub`` path every other line does, rather than trusting
    that allow-list alone — ``scrub`` is the backstop, this call is not exempt from it.
    """
    overrides = effective_overrides(get_settings())
    get_logger("startup").info(
        "non-default settings at boot" if overrides else "no non-default settings at boot",
        extra={"settings_overrides": overrides},
    )
