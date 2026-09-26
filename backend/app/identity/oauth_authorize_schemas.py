"""What the authorization_code+PKCE grant's endpoints look like on the wire (ADR 0014, KAN-1744).

Separate from `app/identity/device_flow_schemas.py` for the same reason that file is separate from
`app/identity/pat_schemas.py`: these exist because `app/identity/oauth_authorize_router.py` and
`app/identity/oauth_register.py` need them, not because this grant *is* the device flow.
"""

from pydantic import BaseModel

from app.identity.pat_schemas import TokenScope


class AuthorizeParams(BaseModel):
    """The OAuth params a browser-embedded client's redirect to `GET /auth/authorize` carries
    (RFC 6749 §4.1.1 + PKCE + RFC 8707), and that `GET /auth/authorize/info`/
    `POST /auth/authorize/approve`/`deny` (ADR 0014) all re-validate independently rather than
    trust from a prior step — there is no persisted row for this flow until approval, unlike the
    device-flow `user_code` these consent-screen routes sit alongside."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    resource: str
    scope: TokenScope = TokenScope.write
    state: str | None = None


class AuthorizeInfoResponse(BaseModel):
    """`GET /auth/authorize/info` — what the consent screen renders: which client is asking, for
    what scope/resource."""

    client_name: str | None
    requested_scope: TokenScope
    resource: str


class AuthorizeRedirect(BaseModel):
    """The response both `POST /auth/authorize/approve` and `/deny` return: a URL for the SPA to
    navigate the browser to (a real top-level navigation back to the requesting app), not a JSON
    success/failure state to render in place — unlike the device-flow consent screen, this flow
    ends by leaving kaya's own UI entirely."""

    redirect_to: str


class ClientRegistrationRequest(BaseModel):
    """`POST /auth/register` (RFC 7591 §2). Only the fields this backend actually acts on — an
    unrecognized field in the request body is silently ignored per RFC 7591's own extensibility
    model, rather than rejected, so a client sending `scope`/`contacts`/etc. isn't punished for
    spec-completeness this backend doesn't need yet.

    `token_endpoint_auth_method`, when given, must be `"none"` — this backend registers public
    clients only (see `app.identity.oauth_client`'s module docstring); any other value is a
    `400 invalid_client_metadata`.
    """

    redirect_uris: list[str]
    client_name: str | None = None
    token_endpoint_auth_method: str | None = None


class ClientRegistrationResponse(BaseModel):
    """The RFC 7591 §3.2.1 response shape, verbatim field names. No
    `registration_access_token`/`registration_client_uri` — this backend doesn't implement the
    optional RFC 7592 client-management protocol (read/update/delete a registration after the
    fact)."""

    client_id: str
    client_id_issued_at: int
    redirect_uris: list[str]
    client_name: str | None
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = ["authorization_code"]
    response_types: list[str] = ["code"]
