"""Per-request bearer-token override for the hosted Streamable HTTP transport (ADR 0013, KAN-1744).

The stdio server (the only transport before this card) is **one process per user**: a single
`KAYA_TOKEN` env var, read once via `kaya_client.open_client`, good for the process's whole
lifetime. The hosted transport is the opposite shape: **one process serving every caller**, so the
credential has to come from each individual HTTP request instead.

This module is the seam between the two. `backend/app/identity/mcp_host.py`'s auth middleware
(which validates the caller's bearer against `personal_access_token` — the same lookup
`app.auth.kaya_principal.principal_from_pat` already makes for `/api/v1`, since an OAuth-issued
token is a `personal_access_token` row too, ADR 0014) calls `set_request_token` once it knows the
token is valid, for the duration of that one HTTP request; `kaya_mcp.tools` reads it via
`get_request_token` and builds a **fresh, per-request** `KayaClient` from it instead of touching the
stdio path's `open_client()`.

A `contextvars.ContextVar` rather than a global: Starlette/ASGI serves concurrent requests as
concurrent asyncio tasks, and a context var's value is task-local, so two hosted requests in flight
at once never see each other's token — the same isolation property a global would not have.
"""

from contextvars import ContextVar

_request_token: ContextVar[str | None] = ContextVar("_request_token", default=None)


def set_request_token(token: str) -> None:
    _request_token.set(token)


def get_request_token() -> str | None:
    return _request_token.get()


def clear_request_token() -> None:
    _request_token.set(None)
