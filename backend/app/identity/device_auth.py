"""RFC 8628 Device Authorization Grant endpoints (ADR 0013, KAN-1743).

Five routes, mounted at `/auth/device` — unversioned, like the rest of `/auth/*`
(`app/identity/router.py`'s own reasoning: authentication infrastructure, not a versioned API
resource):

- `POST /auth/device/code` — no auth. `kaya auth login` calls this first.
- `POST /auth/device/token` — no auth (the device code itself is the credential). Polled at
  `interval`-second intervals until the row resolves.
- `GET /auth/device/{user_code}` — **cookie-session auth required.** The consent screen's own read.
- `POST /auth/device/{user_code}/approve` — cookie-session auth required.
- `POST /auth/device/{user_code}/deny` — cookie-session auth required.

**Two error shapes in one router, and that split is deliberate, not an inconsistency.** `code`/
`token` speak RFC 8628 §3.5's own wire format — `{"error": "<code>"}`, a flat string a spec-aware
device-flow client reads by field name — because they are OAuth protocol surface, not kaya's REST
API surface; the CLI (`kaya_client.device_login`) is written against that spec, not against
`{"error": {"code","message"}}`. This is the same exception kaya's own `fastapi-users`-mounted
`/auth/login` already takes for the identical reason (third-party OAuth wire format, not this
codebase's own convention) — see `app/identity/router.py`. The three consent routes are ordinary,
kaya-owned, cookie-authenticated JSON endpoints exactly like `/api/v1/tokens`, so they use kaya's
own `error_body` shape like everything else under `app/api/`.

**Gated on `get_current_active_user`, not `get_principal`.** The same chicken-and-egg reasoning
`app/api/tokens.py` gives for minting kaya's very first PAT: approving a device-flow login mints a
token, so the approver must be a real, logged-in-via-GitHub human — never a `kaya_pat_…` bearer,
which `get_principal` would also accept.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# From the submodule, not `app.auth` itself: `app.auth`'s own import chain reaches
# `app.identity.models` (via `kaya_principal.py`), so importing this package from `app.auth`'s
# `__init__` would be circular. `errors.py` has no dependency of its own, so this is safe.
from app.auth.errors import error_body
from app.config import get_settings
from app.db import get_session
from app.identity.current_user import get_current_active_user
from app.identity.device_flow import (
    DEVICE_CODE_TTL_SECONDS,
    DEVICE_POLL_INTERVAL_SECONDS,
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_PENDING,
    DeviceAuthorization,
    generate_device_code,
    generate_user_code,
    poll_throttle,
)
from app.identity.device_flow_schemas import (
    DeviceAuthorizationRead,
    DeviceCodeRequest,
    DeviceCodeResponse,
    DeviceTokenRequest,
)
from app.identity.models import KayaAccount
from app.identity.pat import PersonalAccessToken, generate_token, hash_token
from app.identity.pat_schemas import TokenCreated

router = APIRouter(prefix="/auth/device", tags=["identity"])

CurrentUser = Annotated[KayaAccount, Depends(get_current_active_user)]
DbSession = Annotated[Session, Depends(get_session)]

_USER_CODE_COLLISION_RETRIES = 5
"""Retry budget for the astronomically unlikely `user_code` collision (~26 bits of entropy over an
ever-growing but short-lived population) before surfacing a `500` rather than looping forever."""


def _oauth_error(error: str) -> JSONResponse:
    """RFC 8628 §3.5's error body. Always `400` — the spec uses the token endpoint's ordinary
    error status for every one of these. See the module docstring for why this is not
    `error_body`."""
    return JSONResponse(status_code=400, content={"error": error})


@router.post("/code", response_model=DeviceCodeResponse)
def create_device_code(
    payload: DeviceCodeRequest, request: Request, db: DbSession
) -> DeviceCodeResponse:
    """Start a device-flow login. No auth — this is the entry point for a CLI with no credential."""
    secret = get_settings().kaya_auth_secret
    device_code = generate_device_code()
    expires_at = datetime.now(UTC) + timedelta(seconds=DEVICE_CODE_TTL_SECONDS)

    for attempt in range(_USER_CODE_COLLISION_RETRIES):
        row = DeviceAuthorization(
            device_code_hash=hash_token(device_code, secret),
            user_code=generate_user_code(),
            requested_scope=payload.scope.value,
            expires_at=expires_at,
        )
        db.add(row)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if attempt == _USER_CODE_COLLISION_RETRIES - 1:
                raise
    db.refresh(row)

    verification_uri = f"{str(request.base_url).rstrip('/')}/device"
    return DeviceCodeResponse(
        device_code=device_code,
        user_code=row.user_code,
        verification_uri=verification_uri,
        verification_uri_complete=f"{verification_uri}?user_code={row.user_code}",
        expires_in=DEVICE_CODE_TTL_SECONDS,
        interval=DEVICE_POLL_INTERVAL_SECONDS,
    )


@router.post("/token")
def poll_device_token(payload: DeviceTokenRequest, db: DbSession):
    """Poll for the outcome of a device-flow login.

    Every "not a live, pending row" case (unknown code, expired, already redeemed) collapses to the
    same `expired_token` response, uniformly — a stale poll must not be usable to probe whether a
    code ever existed.
    """
    secret = get_settings().kaya_auth_secret
    row = db.scalars(
        select(DeviceAuthorization).where(
            DeviceAuthorization.device_code_hash == hash_token(payload.device_code, secret)
        )
    ).first()
    if row is None:
        return _oauth_error("expired_token")
    if row.expires_at <= datetime.now(UTC) or row.redeemed_at is not None:
        poll_throttle.forget(row.device_code_hash)
        return _oauth_error("expired_token")
    if poll_throttle.too_soon(row.device_code_hash):
        return _oauth_error("slow_down")
    if row.status == STATUS_DENIED:
        poll_throttle.forget(row.device_code_hash)
        return _oauth_error("access_denied")
    if row.status == STATUS_PENDING:
        return _oauth_error("authorization_pending")

    # status == "approved": mint the PAT now, on this first successful poll — see
    # `DeviceAuthorization`'s own docstring for why minting happens here and not at approval.
    raw, prefix, token_hash = generate_token(secret)
    pat = PersonalAccessToken(
        user_id=row.user_id,
        name="Device flow login",
        token_hash=token_hash,
        token_prefix=prefix,
        scope=row.requested_scope,
    )
    db.add(pat)
    db.flush()  # assign pat.id before it's referenced below
    row.pat_id = pat.id
    row.redeemed_at = datetime.now(UTC)
    db.commit()
    db.refresh(pat)
    poll_throttle.forget(row.device_code_hash)

    return TokenCreated(
        id=pat.id,
        name=pat.name,
        token_prefix=pat.token_prefix,
        scope=pat.scope,  # type: ignore[arg-type]
        created_at=pat.created_at,
        last_used_at=pat.last_used_at,
        expires_at=pat.expires_at,
        token=raw,
    )


def _get_live_row_or_404(db: Session, user_code: str) -> DeviceAuthorization:
    """Load by `user_code`, `404` for unknown **or expired** — a stale link reads as gone. An
    already-resolved (approved/denied) row is *not* folded in here, unlike `poll_device_token`'s
    uniform collapse: the consent screen needs to render that state distinctly (e.g. "you already
    approved this"), so `status` is the caller's to branch on."""
    row = db.scalars(
        select(DeviceAuthorization).where(DeviceAuthorization.user_code == user_code)
    ).first()
    if row is None or row.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_body("device_code_not_found", "code not found"),
        )
    return row


@router.get("/{user_code}", response_model=DeviceAuthorizationRead)
def get_device_authorization(
    user_code: str, db: DbSession, _user: CurrentUser
) -> DeviceAuthorization:
    """The consent screen's own read: what was requested, and the code's current status."""
    return _get_live_row_or_404(db, user_code)


def _reject_if_already_resolved(row: DeviceAuthorization) -> None:
    """`409` if `row` isn't `pending` any more: already approved/denied is a state conflict, not a
    missing-resource or permission problem. Shared by `approve` and `deny`, which differ only in
    which status they stamp on success."""
    if row.status != STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_body(
                "device_code_already_resolved", f"this code was already {row.status}"
            ),
        )


@router.post("/{user_code}/approve", response_model=DeviceAuthorizationRead)
def approve_device_authorization(
    user_code: str, db: DbSession, user: CurrentUser
) -> DeviceAuthorization:
    """Approve a pending device-flow login as the calling account. Does **not** mint the PAT — see
    `DeviceAuthorization`'s own docstring — it only records who approved it."""
    row = _get_live_row_or_404(db, user_code)
    _reject_if_already_resolved(row)
    row.status = STATUS_APPROVED
    row.user_id = user.id
    db.commit()
    db.refresh(row)
    return row


@router.post("/{user_code}/deny", response_model=DeviceAuthorizationRead)
def deny_device_authorization(
    user_code: str, db: DbSession, _user: CurrentUser
) -> DeviceAuthorization:
    """Deny a pending device-flow login. Same `409` reasoning as `approve`."""
    row = _get_live_row_or_404(db, user_code)
    _reject_if_already_resolved(row)
    row.status = STATUS_DENIED
    db.commit()
    db.refresh(row)
    return row
