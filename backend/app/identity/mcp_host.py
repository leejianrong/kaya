"""Hosted Streamable HTTP transport for kaya's MCP server (ADR 0013, KAN-1744).

Before this file, the only way to reach the MCP tool surface was **stdio** (`kaya-mcp`, one local
subprocess per user, launched by a `.mcp.json` entry) — fine for Claude Code, useless for a client
that cannot spawn a local subprocess (Claude.ai, ChatGPT, Cursor's remote-MCP mode). This module
hosts the *exact same* tool registry (`kaya_mcp.server.server`, unchanged) over Streamable HTTP
instead, mounted at `/mcp` on kaya's own backend (`app/main.py`).

**Auth is the backend's job, not the MCP SDK's.** `server.streamable_http_app()` is built below
with **no** OAuth-authorization-server machinery from the SDK — that would stand up a *second*,
parallel authorization server inside the MCP SDK, forking the client/token model into two places
that could disagree, when kaya's own FastAPI backend already is the authorization server (the RFC
8628 device flow, ADR 0013; the `authorization_code`+PKCE grant, ADR 0014). Instead,
`_BearerAuthMiddleware` below validates each hosted request's own `Authorization: Bearer` against
`personal_access_token` — the same lookup (`app.auth.kaya_principal.principal_from_pat`) `/api/v1`
itself uses via `get_principal`, since an OAuth-issued token is a `personal_access_token` row too
(ADR 0014) — and, once valid, hands the raw token to the tool layer via `kaya_mcp.request_auth`'s
per-request contextvar rather than the stdio transport's process-wide singleton (see
`kaya_mcp.tools`'s own docstring for that half of the bridge). A missing/invalid bearer's `401`
carries an RFC 9728-compliant `WWW-Authenticate: Bearer resource_metadata="..."` header, so a cold
client discovers the authorization server with no out-of-band configuration — see
`app/identity/oauth_metadata.py` for the metadata document itself.

**Lifespan.** `server.streamable_http_app()` returns a Starlette app whose own lifespan starts/stops
the Streamable HTTP session manager — but mounting a sub-app with `FastAPI.mount()` does **not**
forward ASGI `lifespan` events to it: Starlette's `Router.app()` handles a `"lifespan"`-type scope
itself, before it ever consults the route table, so a mounted sub-app's lifespan simply never runs
on its own. Skipping this doesn't raise anywhere obvious — it just leaves the session manager never
started, so every request to `/mcp` would fail once it reached streaming. `hosted_mcp_lifespan` is
how `app/main.py` enters the mounted app's lifespan from its own top-level one.

**The Streamable HTTP app is rebuilt on every lifespan start, not built once at import time.** The
session manager `server.streamable_http_app()` wires up as the returned app's own lifespan refuses
to be entered a second time on the same instance ("can only be called once per instance"). A real
deployment only ever starts its lifespan once, so a module-level singleton would work there, but
**every** `TestClient(app)` in this repo's test suite starts and stops the FastAPI app's lifespan
again on the same process — the second one crashes on exactly that guard the first time this is
tried. `hosted_mcp_lifespan` rebuilds a fresh `server.streamable_http_app()` — a new session
manager included — on each start and publishes it through `_current_mcp_asgi_app` for
`_BearerAuthMiddleware` (registered once, for the process's whole life) to dispatch to.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from kaya_mcp.request_auth import clear_request_token, set_request_token
from kaya_mcp.server import server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.kaya_principal import principal_from_pat
from app.config import get_settings
from app.db import get_sessionmaker
from app.identity.oauth_metadata import METADATA_PATH


# `app/main.py` registers `hosted_mcp_app` as a plain `Route("/mcp", ...)`, NOT a `Mount` —
# `Mount("/mcp", ...)` strips that prefix before its own routing sees the request and its regex
# requires a literal trailing `/` after `mcp` (`compile_path` builds it as `/mcp/{path:path}`), so
# a bare `POST /mcp` with no trailing slash never reaches it at all; worse, once the SPA is built
# the catch-all `GET /{full_path:path}` route also matches that same bare path (on path, not
# method) and wins the tie-break with a confusing `405`, not the `307` redirect you'd expect. A
# `Route` matches the literal path with **any** method (the default when `methods=None`, exactly
# what streamable HTTP needs: `POST` for messages, `GET` for the SSE stream, `DELETE` to end a
# session), so it sidesteps all of that — the request scope reaches this ASGI app completely
# unmodified, hence the *default* `streamable_http_path="/mcp"` passed below (no stripping to
# account for, unlike a `Mount`).
#
# `transport_security=...enable_dns_rebinding_protection=False`: the SDK's default (`host=
# "127.0.0.1"`, its own default) auto-enables an allow-list of just `127.0.0.1`/`localhost`/`::1`
# `Host` headers — a guard against a malicious page's browser fetch being DNS-rebound at a
# *locally bound* MCP server that trusts its LAN/loopback origin. That threat model is backwards
# here: this transport's entire point is to be reached from a real, internet-facing hostname
# (Claude.ai, ChatGPT, Cursor), which the default allow-list would reject outright with a `421`.
# The actual authorization boundary for this endpoint is the bearer-token middleware below, not
# the `Host` header — unaffected by this setting either way.
def _build_mcp_asgi_app():
    return server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )


# The MCP Streamable HTTP app currently in service — `None` outside a lifespan (so a stray request
# before startup / after shutdown fails loudly instead of dispatching to a torn-down session
# manager). Rebuilt fresh by every `hosted_mcp_lifespan` start; see the module docstring's
# *rebuilt on every lifespan start* section for why this can't be a build-once module-level
# constant.
_current_mcp_asgi_app = None


def _bearer_token(scope: Scope) -> str | None:
    """The bearer credential from this request's `Authorization` header, or `None` if it's
    missing, malformed, or a non-Bearer scheme."""
    headers = dict(scope.get("headers") or [])
    raw = headers.get(b"authorization", b"").decode("latin-1")
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[len("bearer ") :].strip()
    return token or None


async def _unauthorized(scope: Scope, receive: Receive, send: Send, detail: str) -> None:
    # RFC 9728 discovery: point a cold client at the metadata document for THIS request's own
    # origin (dev/Fly-prod/self-hosted all differ, so this can't be a fixed string) — see
    # `app/identity/oauth_metadata.py`'s module docstring for why the origin is derived per
    # request rather than baked in at import time, and why `METADATA_PATH` is shared rather than
    # duplicated between the two modules.
    origin = str(Request(scope).base_url).rstrip("/")
    resource_metadata = f"{origin}{METADATA_PATH}"
    response = JSONResponse(
        {"detail": detail},
        status_code=401,
        headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata}"'},
    )
    await response(scope, receive, send)


class _BearerAuthMiddleware:
    """Validate the caller's own bearer token before every hosted MCP request, then dispatch to
    whichever `_current_mcp_asgi_app` a live `hosted_mcp_lifespan` has published.

    A raw ASGI middleware, not a FastAPI `Depends`: the mounted MCP app is a separate Starlette
    application under `/mcp` with its own routing, so FastAPI's dependency injection never runs
    against it — this is the equivalent chokepoint for that sub-app that `app.auth.get_principal`
    is for the rest of `/api/v1`.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Non-HTTP scopes (e.g. "lifespan", if one ever reached this far) pass straight
            # through — there's no bearer header to check.
            await self._dispatch(scope, receive, send)
            return

        token = _bearer_token(scope)
        if token is None:
            await _unauthorized(scope, receive, send, "missing bearer token")
            return

        secret = get_settings().kaya_auth_secret
        with get_sessionmaker()() as session:
            principal = principal_from_pat(session, token, secret=secret)
        if principal is None:
            await _unauthorized(scope, receive, send, "invalid or expired token")
            return

        set_request_token(token)
        try:
            await self._dispatch(scope, receive, send)
        finally:
            clear_request_token()

    async def _dispatch(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = _current_mcp_asgi_app
        if app is None:
            # Only reachable outside a running lifespan (startup not finished, or shutdown
            # already ran) — a real deployment never sees this.
            await _unauthorized(scope, receive, send, "MCP transport is not ready")
            return
        await app(scope, receive, send)


hosted_mcp_app: ASGIApp = _BearerAuthMiddleware()


@asynccontextmanager
async def hosted_mcp_lifespan() -> AsyncIterator[None]:
    """Build a fresh Streamable HTTP app + session manager, publish it for
    `_BearerAuthMiddleware` to dispatch to, and enter its lifespan (starting/stopping the session
    manager) for the duration of `app/main.py`'s own — see the module docstring's *rebuilt on
    every lifespan start* section for why a fresh instance every time is required, not merely
    allowed."""
    global _current_mcp_asgi_app
    mcp_asgi_app = _build_mcp_asgi_app()
    async with mcp_asgi_app.router.lifespan_context(mcp_asgi_app):
        _current_mcp_asgi_app = mcp_asgi_app
        try:
            yield
        finally:
            _current_mcp_asgi_app = None
