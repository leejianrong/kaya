"""RFC 7591 Dynamic Client Registration (ADR 0014, KAN-1744).

One route: `POST /auth/register`, no auth — the whole point is obtaining a first client identity,
the same asymmetry `POST /auth/device/code` already has (ADR 0013). See
`app/identity/oauth_client.py` for the registration logic itself and why this backend also supports
the newer Client ID Metadata Document mechanism alongside it.

**Mounted at `/auth`, not `/api/v1`** — authentication infrastructure, alongside `/auth/device/*`
and `/auth/github/*`, not a versioned API resource.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.identity.oauth_authorize_schemas import (
    ClientRegistrationRequest,
    ClientRegistrationResponse,
)
from app.identity.oauth_client import InvalidClientMetadata, register_client

router = APIRouter(prefix="/auth", tags=["identity"])

DbSession = Annotated[Session, Depends(get_session)]


def _registration_error(error: str, description: str) -> JSONResponse:
    """The RFC 7591 §3.2.2 error body — `{"error": ..., "error_description": ...}`, always `400`
    (RFC 7591 defines no other status for a registration failure). Deliberately not kaya's own
    `{"error": {"code","message"}}` shape — see `app/identity/device_auth.py`'s module docstring
    for why OAuth protocol surface speaks the spec's own wire format rather than this codebase's
    REST convention."""
    return JSONResponse(status_code=400, content={"error": error, "error_description": description})


@router.post("/register", response_model=ClientRegistrationResponse, status_code=201)
def register(payload: ClientRegistrationRequest, db: DbSession):
    if payload.token_endpoint_auth_method not in (None, "none"):
        return _registration_error(
            "invalid_client_metadata",
            'this server registers public clients only; token_endpoint_auth_method must be "none"',
        )

    try:
        client = register_client(
            db, redirect_uris=payload.redirect_uris, client_name=payload.client_name
        )
    except InvalidClientMetadata as exc:
        error = "invalid_redirect_uri" if "redirect_uri" in str(exc) else "invalid_client_metadata"
        return _registration_error(error, str(exc))

    return ClientRegistrationResponse(
        client_id=client.client_id,
        client_id_issued_at=int(client.created_at.timestamp()),
        redirect_uris=client.redirect_uris,
        client_name=client.client_name,
    )
