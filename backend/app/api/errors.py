"""The API error contract: **one** shape, ``{"error": {"code", "message", …}}``, for every failure.

KAN-536 owns this decision, and it is a decision rather than an inheritance. ``error_body`` already
built ``{"error": {…}}``, but FastAPI's default handler wraps whatever a raise site hands it in
``{"detail": …}``, so the wire shape was ``{"detail": {"error": {"code": …}}}``. KAN-534's author
flagged that double nesting as an accident and left the choice here. It is un-nested, for three
reasons:

1. ``detail`` is FastAPI's word, not kaya's. Nothing about a caller's contract should depend on
   which Python framework happened to serve the request, and a client that reaches for
   ``body["detail"]["error"]["code"]`` has hard-coded that.
2. ADR 0005 fixes the CLI's structured error as an ``{"error": {…}}`` object. With the nesting gone
   the API emits *that* object, so ``kaya-client`` forwards a body rather than unwrapping one, and
   there is one shape to learn across HTTP, the CLI and MCP instead of two.
3. It is the last moment it is free. Nothing consumes the API yet; KAN-540 (the client), KAN-552
   (the SPA) and V6's MCP tools are all written against whatever this PR lands.

``error_body`` stays the single builder — every raise site in ``app/auth/`` is untouched, and none
of them had to learn about this file. What changed is one handler at the app boundary.

Three handlers, because a caller cannot tell which layer refused it and should not have to:

- ``HTTPException`` — kaya's own refusals, and Starlette's (an unknown path, a wrong method).
- ``RequestValidationError`` — a malformed request body, which FastAPI otherwise answers with a
  bare list under ``detail``.
- Nothing for unhandled exceptions: a `500` stays Starlette's, because a handler that formats one
  prettily is a handler that can itself raise while the app is already broken.
"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.auth import error_body


def code_for_status(status_code: int) -> str:
    """A fallback ``code`` for a refusal raised without one — ``404`` → ``not_found``.

    Derived from the status phrase rather than read out of a table, so a status kaya has never
    raised before still arrives with a stable, greppable code instead of ``None``. Every refusal
    kaya writes itself goes through ``error_body`` and names its own code; this covers the ones
    Starlette raises on kaya's behalf, which is exactly the set nobody remembers to handle.
    """
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "http_error"


def as_error_payload(detail: Any, status_code: int) -> dict[str, Any]:
    """Whatever a raise site put in ``detail``, as the one error shape.

    A mapping that already carries ``error`` is passed through untouched — that is every call site
    in ``app/auth/`` and ``app/api/``, and the reason none of them needed editing. Anything else is
    a string from Starlette, and gets wrapped.
    """
    if isinstance(detail, Mapping) and "error" in detail:
        return dict(detail)
    return error_body(code_for_status(status_code), str(detail))


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(as_error_payload(exc.detail, exc.status_code)),
        # `WWW-Authenticate` on a `401` and `Retry-After` on Q9's `503` are part of those contracts,
        # not decoration. Dropping them here would be a silent regression in `app/auth/`.
        headers=getattr(exc, "headers", None),
    )


def _location(error: Mapping[str, Any]) -> str:
    """Pydantic's ``loc`` as a caller-facing field name. ``("body", "title")`` → ``title``.

    The leading segment is dropped: it says "body", which the caller already knows, and it would
    make the name unusable as-is against the JSON that was sent.
    """
    return ".".join(str(part) for part in tuple(error.get("loc", ()))[1:]) or "body"


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """A malformed body, in the same shape as every other refusal.

    FastAPI's default is a `422` carrying a *list* under ``detail``, which is informative and is a
    third shape for a client to special-case. Every complaint is folded into ``message`` instead, so
    nothing is lost, and ``field`` names the first one — ADR 0005's single-argument slot, and the
    part a human acts on. The error object stays flat and all-strings, which is what ``error_body``
    promises and what makes it renderable as one line in the CLI.
    """
    errors = exc.errors()
    complaints = [f"{_location(error)}: {error.get('msg', 'invalid')}" for error in errors]

    return JSONResponse(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        content=jsonable_encoder(
            error_body(
                "invalid_request",
                "; ".join(complaints) or "the request body is not valid",
                field=_location(errors[0]) if errors else "body",
            )
        ),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Wire both handlers onto an app. Called by ``app.main``; called by tests on their own apps."""
    # The `type: ignore`s are Starlette's signature being `(Request, Exception)` while a handler
    # registered for one exception class only ever receives that class. Widening the annotations
    # instead would mean an `isinstance` assertion in each body, which asserts what the registration
    # already guarantees.
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
