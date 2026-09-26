"""OAuth 2.1 authorization_code + PKCE grant (ADR 0014, KAN-1744) — the redirect-based flow ADR
0013 left unspecified, for a browser-embedded client (Claude.ai, ChatGPT, Cursor's remote-MCP mode)
that has no device to poll from, unlike the CLI's device flow (`app/identity/device_auth.py`).

Four routes, mounted at `/auth` like `device_auth.py`/`oauth_register.py` — authentication
infrastructure, not a versioned API resource:

- `GET /auth/authorize` — no auth of its own. The real top-level browser navigation an OAuth
  client redirects the user to. Validates the request and, on success, redirects again to kaya's
  own `/device` consent screen with the same params forwarded — no `device_authorization` row is
  created here (nothing polls this the way device flow's `POST /auth/device/code` does; the
  `redirect_uri` callback below is the "poll"). **Redirects to `/device`, not the SPA root** — kaya
  already has a dedicated, isolated consent-screen route (KAN-1743's `DeviceApproval.svelte`);
  pandan's own build redirects to its SPA root and lets that route multiplex on which query
  params are present, but kaya has no reason to move the multiplexing point when `/device` already
  exists for exactly this purpose.
- `GET /auth/authorize/info` — cookie-session auth required. The consent screen's own read: which
  client is asking, for what scope/resource. Re-validates everything `/authorize` did rather than
  trusting the URL alone, since no row persists any of it in between.
- `POST /auth/authorize/approve` / `POST /auth/authorize/deny` — cookie-session auth required.
  Unlike device flow's approve/deny (which render a JSON success/denial state in place), these end
  the flow by handing the SPA a URL to navigate the browser to — back to the requesting app, off
  kaya's own UI entirely.

**Gated on `get_current_active_user`, not `get_principal`** — the same chicken-and-egg reasoning
`app/identity/device_auth.py` already gives for its own consent routes: approving either grant
mints a token, so the approver must be a real, logged-in-via-GitHub human, never a `kaya_pat_…`
bearer.

**Two-tier error delivery, per RFC 6749 §4.1.2.1.** An unknown `client_id` or an unregistered
`redirect_uri` must NEVER be delivered via a redirect to that same (untrusted) `redirect_uri` —
that's the open-redirect guard ADR 0014 calls out by name. So `_resolve_trusted_client` below
always raises a flat `{"error": ...}` JSON response (mirroring `oauth_register.py`'s
`_registration_error` shape, not kaya's own `{"error": {"code","message"}}`) for those two
specifically. Only once `redirect_uri` is trusted does `GET /auth/authorize` deliver the rest of
its errors (bad `response_type`, unsupported PKCE method, wrong `resource`) as a `302` back to it.
The three JSON-only consent-screen routes below never need that split — they're reached by the
SPA's own `fetch()`, never a top-level navigation — so every one of their errors is the same flat
JSON shape.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.identity.current_user import get_current_active_user
from app.identity.device_flow import STATUS_APPROVED, DeviceAuthorization
from app.identity.models import KayaAccount
from app.identity.oauth_authorize import (
    AUTHORIZATION_CODE_TTL_SECONDS,
    SUPPORTED_CODE_CHALLENGE_METHOD,
    canonical_mcp_resource,
    generate_authorization_code,
)
from app.identity.oauth_authorize_schemas import (
    AuthorizeInfoResponse,
    AuthorizeParams,
    AuthorizeRedirect,
)
from app.identity.oauth_client import InvalidClientMetadata, ResolvedClient, resolve_client
from app.identity.pat import hash_token
from app.identity.pat_schemas import TokenScope

router = APIRouter(prefix="/auth", tags=["identity"])

CurrentUser = Annotated[KayaAccount, Depends(get_current_active_user)]
DbSession = Annotated[Session, Depends(get_session)]


def _flat_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    """The RFC 6749 §5.2 error body — `{"error": ..., "error_description": ...}`, deliberately flat
    (see the module docstring)."""
    return JSONResponse(
        status_code=status_code, content={"error": error, "error_description": description}
    )


class _AuthorizeError(Exception):
    """Raised by `_resolve_trusted_client` for the two errors that must never be delivered via
    redirect. Caught once per route, each turning it into that route's own flat JSON response —
    never re-raised past this module."""

    def __init__(self, error: str, description: str) -> None:
        self.error = error
        self.description = description
        super().__init__(description)


def _resolve_trusted_client(db: Session, client_id: str, redirect_uri: str) -> ResolvedClient:
    """Resolve `client_id` and check `redirect_uri` is registered for it — the two checks RFC 6749
    §4.1.2.1 says must be direct errors, never a redirect to an unverified `redirect_uri` (the
    open-redirect guard ADR 0014 names explicitly). Raises `_AuthorizeError` for either failure;
    every caller in this module catches it in the same place."""
    try:
        resolved = resolve_client(db, client_id)
    except InvalidClientMetadata as exc:
        raise _AuthorizeError("invalid_client", str(exc)) from exc
    if resolved is None:
        raise _AuthorizeError("invalid_client", "unknown client_id")
    if redirect_uri not in resolved.redirect_uris:
        raise _AuthorizeError("invalid_request", "redirect_uri is not registered for this client")
    return resolved


@router.get("/authorize")
def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    db: DbSession,
    scope: TokenScope = TokenScope.write,
    state: str | None = None,
):
    """The OAuth client's own redirect target. See the module docstring for the pre-trust/
    post-trust error split."""
    try:
        _resolve_trusted_client(db, client_id, redirect_uri)
    except _AuthorizeError as exc:
        return _flat_error(exc.error, exc.description)

    # redirect_uri is trusted from here on — every further problem goes back to the client via
    # that redirect_uri, per RFC 6749 §4.1.2.1, not a direct response the OAuth client (as opposed
    # to its end user's browser) never sees.
    def _redirect_error(error: str) -> RedirectResponse:
        params = {"error": error}
        if state is not None:
            params["state"] = state
        return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)

    if response_type != "code":
        return _redirect_error("unsupported_response_type")
    if code_challenge_method != SUPPORTED_CODE_CHALLENGE_METHOD:
        return _redirect_error("invalid_request")
    if resource != canonical_mcp_resource(request):
        return _redirect_error("invalid_target")

    forward = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "resource": resource,
        "scope": scope.value,
    }
    if state is not None:
        forward["state"] = state
    origin = str(request.base_url).rstrip("/")
    return RedirectResponse(f"{origin}/device?{urlencode(forward)}", status_code=302)


@router.get("/authorize/info", response_model=None)
def get_authorize_info(
    request: Request,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    db: DbSession,
    _user: CurrentUser,
    scope: TokenScope = TokenScope.write,
) -> AuthorizeInfoResponse | JSONResponse:
    """The consent screen's own read — re-validates everything `/authorize` did rather than
    trusting the URL alone, since nothing persists it in between (unlike device flow's stored
    row)."""
    try:
        resolved = _resolve_trusted_client(db, client_id, redirect_uri)
    except _AuthorizeError as exc:
        return _flat_error(exc.error, exc.description)
    if code_challenge_method != SUPPORTED_CODE_CHALLENGE_METHOD:
        return _flat_error("invalid_request", "unsupported code_challenge_method")
    if resource != canonical_mcp_resource(request):
        return _flat_error("invalid_target", "resource is not this server's MCP endpoint")
    return AuthorizeInfoResponse(
        client_name=resolved.client_name, requested_scope=scope, resource=resource
    )


@router.post("/authorize/approve", response_model=AuthorizeRedirect)
def approve_authorize(
    payload: AuthorizeParams, request: Request, db: DbSession, user: CurrentUser
) -> AuthorizeRedirect | JSONResponse:
    """Mint a short-lived, single-use authorization code and hand back the URL to redirect the
    browser to. No `pending` phase (unlike device flow): a `device_authorization` row is inserted
    already `status="approved"`, since nothing polls it beforehand — see the class docstring in
    `app/identity/device_flow.py`."""
    try:
        _resolve_trusted_client(db, payload.client_id, payload.redirect_uri)
    except _AuthorizeError as exc:
        return _flat_error(exc.error, exc.description)
    if payload.code_challenge_method != SUPPORTED_CODE_CHALLENGE_METHOD:
        return _flat_error("invalid_request", "unsupported code_challenge_method")
    if payload.resource != canonical_mcp_resource(request):
        return _flat_error("invalid_target", "resource is not this server's MCP endpoint")

    secret = get_settings().kaya_auth_secret
    code = generate_authorization_code()
    expires_at = datetime.now(UTC) + timedelta(seconds=AUTHORIZATION_CODE_TTL_SECONDS)
    row = DeviceAuthorization(
        status=STATUS_APPROVED,
        user_id=user.id,
        requested_scope=payload.scope.value,
        client_id=payload.client_id,
        redirect_uri=payload.redirect_uri,
        code_challenge=payload.code_challenge,
        code_challenge_method=payload.code_challenge_method,
        resource=payload.resource,
        code_hash=hash_token(code, secret),
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()

    params = {"code": code}
    if payload.state is not None:
        params["state"] = payload.state
    return AuthorizeRedirect(redirect_to=f"{payload.redirect_uri}?{urlencode(params)}")


@router.post("/authorize/deny", response_model=AuthorizeRedirect)
def deny_authorize(
    payload: AuthorizeParams, db: DbSession, _user: CurrentUser
) -> AuthorizeRedirect | JSONResponse:
    """Deny — no row to create or update (nothing was persisted at `/authorize` time), just a
    redirect the SPA navigates to."""
    try:
        _resolve_trusted_client(db, payload.client_id, payload.redirect_uri)
    except _AuthorizeError as exc:
        return _flat_error(exc.error, exc.description)

    params = {"error": "access_denied"}
    if payload.state is not None:
        params["state"] = payload.state
    return AuthorizeRedirect(redirect_to=f"{payload.redirect_uri}?{urlencode(params)}")
