"""RFC 8628 Device Authorization Grant endpoints (ADR 0013, KAN-1743, mirrors pandan ADR 0024's own
`routers/device_auth.py` — minus every board/workspace concern kaya has no analogue for).

Five routes:

- ``POST /auth/device/code`` — no auth. The CLI calls this first; returns a ``device_code`` (secret,
  polled with) and a ``user_code`` (short, human-typed fallback) plus where a human approves.
- ``POST /auth/device/token`` — no auth (the ``device_code`` itself is the credential). Polled at
  ``interval``-second intervals until the row resolves.
- ``GET /auth/device/{user_code}`` — **cookie-session auth required**. The consent screen's own
  read: what scope was requested and the code's current status, so a re-visited link after
  already-approved/denied reads as that state, not a mysterious 404.
- ``POST /auth/device/{user_code}/approve`` — auth required. The human's final scope choice
  (pre-filled by the ``GET`` above, editable before submitting) mints nothing yet — see below.
- ``POST /auth/device/{user_code}/deny`` — auth required.

**Mounted at ``/auth/device``, not ``/api/v1``** — this is authentication infrastructure, alongside
``/auth/github/*``, not a note-scoped resource. The three consent routes still require a session
(unlike ``code``/``token`` above) because *approving* is an action only an authenticated human
should be able to take — the RFC 8628 asymmetry is "no credential to start," not "no credential
ever."

**Gated on `get_current_active_user` (`app/identity/current_user.py`), not `get_principal` —
deliberately, for two independent reasons, not one.** The obvious-looking choice would be
`get_principal` (cookie session *or* `kaya_pat_…` bearer, everything else in `app/api/` uses it),
and it was tried first; it produces a real circular import. `app.auth.kaya_principal` needs
`app.identity.pat`, so importing anything under `app.identity` runs `app.identity`'s own package
`__init__`, which imports this router — if this router then reached back into `app.auth` for
`get_principal`, that import would land mid-way through `app.auth`'s own package `__init__` (the
very call that started the chain), before `get_principal` exists in its namespace yet. But the
*security* argument stands on its own and would be worth making even without the import problem:
`POST /api/v1/tokens`'s module docstring gives the exact same reasoning for gating PAT *minting* on
a cookie session alone — an existing `kaya_pat_…` must not be usable to mint a new one, because a
leaked PAT could otherwise mint an unbounded number of further PATs. Approving a device-flow login
is exactly that action (it mints a PAT on the CLI's next poll), so it inherits the identical
chicken-and-egg argument: only a freshly cookie-authenticated human may approve one, never an
existing PAT bearer.

**The PAT is minted at first-poll-after-approval, not at approval time.** ADR 0013 doesn't fix the
exact moment (mirroring ADR 0024's own silence on it); minting at approval time would require
holding the raw secret in `device_authorization` between approval (in the browser) and retrieval
(by the CLI's next poll), which is a plaintext-secret-at-rest pattern `app/identity/pat.py` avoids
everywhere else (R7.1: a PAT's raw form is returned once, at creation, and never stored). So
``approve`` only stamps ``status``/``user_id`` and overwrites ``requested_scope`` with the human's
final choice (approving is a fresh grant, not a diff against the request) — ``poll_device_token``
does the actual minting, exactly like ``POST /api/v1/tokens`` already works elsewhere.

**The error body on ``token`` is deliberately flat — `{"error": "<code>"}` — not kaya's usual
`{"error": {"code", "message", ...}}`.** RFC 8628 §3.5 specifies the flat shape verbatim, and a
spec-aware device-flow client (kaya's own CLI included) reads the ``error`` field name as a string,
not an object. This is a `JSONResponse` **returned**, not an `HTTPException` **raised** — kaya's
global error handlers (`app/api/errors.py`) only rewrite raised exceptions, so a directly-returned
response bypasses that machinery entirely rather than fighting it. Every other route in this file
(``code``, the three consent routes) raises the ordinary way and gets the ordinary nested shape;
``token`` is the one deliberate, RFC-mandated exception, the same call pandan's own build made.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.identity.current_user import get_current_active_user
from app.identity.device_auth_schemas import (
    DeviceApproveRequest,
    DeviceAuthorizationRead,
    DeviceCodeRequest,
    DeviceCodeResponse,
    DeviceTokenRequest,
)
from app.identity.device_authorization import DeviceAuthorization
from app.identity.device_flow import (
    DEVICE_CODE_TTL_SECONDS,
    DEVICE_POLL_INTERVAL_SECONDS,
    forget_poll_state,
    generate_device_code,
    generate_user_code,
    too_soon_to_poll,
)
from app.identity.models import KayaAccount
from app.identity.pat import PersonalAccessToken, hash_token
from app.identity.pat import generate_token as generate_pat

router = APIRouter(prefix="/auth/device", tags=["identity"])

DbSession = Annotated[Session, Depends(get_session)]
CurrentActiveUser = Annotated[KayaAccount, Depends(get_current_active_user)]

# Retry budget for the astronomically unlikely user_code collision (~26 bits of entropy over an
# ever-growing but short-lived population) before giving up and surfacing a 500 rather than looping
# forever.
_USER_CODE_COLLISION_RETRIES = 5


def _oauth_error(error: str) -> JSONResponse:
    """The RFC 8628 / OAuth 2.0 error body — see the module docstring for why this is flat and
    returned rather than raised. Always `400` — RFC 8628 §3.5 uses the token endpoint's ordinary
    error status for every one of these."""
    return JSONResponse(status_code=400, content={"error": error})


@router.post("/code", response_model=DeviceCodeResponse)
def create_device_code(
    payload: DeviceCodeRequest,
    request: Request,
    db: DbSession,
) -> DeviceCodeResponse:
    """Start a device-flow login. No auth — this is the entry point for a CLI that has no
    credential yet."""
    device_code = generate_device_code()
    secret = get_settings().kaya_auth_secret
    expires_at = datetime.now(UTC) + timedelta(seconds=DEVICE_CODE_TTL_SECONDS)

    # user_code has a UNIQUE constraint; retry (a fresh row each time) on the vanishingly unlikely
    # collision rather than letting it surface as a raw 500 from the commit.
    row: DeviceAuthorization | None = None
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
    assert row is not None  # loop above always assigns or raises
    db.refresh(row)

    # The SPA's own consent page, on this same origin (ADR 0010) — an absolute URL, not a relative
    # path, because the CLI hands `verification_uri_complete` straight to `webbrowser.open()`.
    verification_uri = str(request.base_url).rstrip("/") + "/device"
    return DeviceCodeResponse(
        device_code=device_code,
        user_code=row.user_code,
        verification_uri=verification_uri,
        verification_uri_complete=f"{verification_uri}?user_code={row.user_code}",
        expires_in=DEVICE_CODE_TTL_SECONDS,
        interval=DEVICE_POLL_INTERVAL_SECONDS,
    )


@router.post("/token", response_model=None)
def poll_device_token(payload: DeviceTokenRequest, db: DbSession) -> JSONResponse | dict[str, Any]:
    """Poll for the outcome of a device-flow login.

    ``response_model=None``: the return type is a genuine union (RFC 8628's `{"error": ...}` states
    versus the success shape's `{"token", "id", ...}`), which FastAPI cannot build one Pydantic
    response field from — and should not, since kaya's own error shape is deliberately absent from
    both (see the module docstring on why ``token``'s error body is flat).

    Every "not a live, pending row" case (unknown code, expired, already redeemed) collapses to the
    same ``expired_token`` response — uniformly, so a stale poll can't be used to probe whether a
    code ever existed."""
    secret = get_settings().kaya_auth_secret
    row = db.scalar(
        select(DeviceAuthorization).where(
            DeviceAuthorization.device_code_hash == hash_token(payload.device_code, secret)
        )
    )
    if row is None:
        return _oauth_error("expired_token")
    if row.expires_at <= datetime.now(UTC) or row.redeemed_at is not None:
        forget_poll_state(row.device_code_hash)
        return _oauth_error("expired_token")
    if too_soon_to_poll(row.device_code_hash):
        return _oauth_error("slow_down")
    if row.status == "denied":
        forget_poll_state(row.device_code_hash)
        return _oauth_error("access_denied")
    if row.status == "pending":
        return _oauth_error("authorization_pending")

    # status == "approved": mint the PAT now, on this first successful poll (see the module
    # docstring for why minting happens here and not at approval).
    raw, prefix, token_hash = generate_pat(secret)
    pat = PersonalAccessToken(
        user_id=row.user_id,
        name="Device flow login",
        token_hash=token_hash,
        token_prefix=prefix,
        scope=row.requested_scope,
    )
    db.add(pat)
    db.flush()  # assign pat.id before device_authorization's FK to it
    row.pat_id = pat.id
    row.redeemed_at = datetime.now(UTC)
    db.commit()
    forget_poll_state(row.device_code_hash)

    return {
        "token": raw,
        "id": pat.id,
        "name": pat.name,
        "token_prefix": pat.token_prefix,
        "scope": pat.scope,
        "created_at": pat.created_at,
    }


def _get_live_row_or_404(db: Session, user_code: str) -> DeviceAuthorization:
    """Load by ``user_code``, 404 for unknown **or expired** — a stale link reads as gone, not as a
    confusing 200 for a code that can never resolve. An *already-resolved* (approved/denied) row is
    NOT folded in here — the consent screen needs to render that state distinctly."""
    row = db.scalar(select(DeviceAuthorization).where(DeviceAuthorization.user_code == user_code))
    if row is None or row.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="code not found")
    return row


@router.get("/{user_code}", response_model=DeviceAuthorizationRead)
def get_device_authorization(
    user_code: str,
    db: DbSession,
    user: CurrentActiveUser,
) -> DeviceAuthorization:
    """The consent screen's own read: what was requested, and the code's current status."""
    return _get_live_row_or_404(db, user_code)


@router.post("/{user_code}/approve", response_model=DeviceAuthorizationRead)
def approve_device_authorization(
    user_code: str,
    payload: DeviceApproveRequest,
    db: DbSession,
    user: CurrentActiveUser,
) -> DeviceAuthorization:
    """Approve a pending device-flow login as the calling human. Does **not** mint the PAT (see
    the module docstring) — it only records who approved it and with what final scope;
    ``poll_device_token`` mints on the CLI's next poll.

    409 if the code isn't `pending` anymore (already approved/denied is a state conflict, not a
    missing-resource or permission problem)."""
    row = _get_live_row_or_404(db, user_code)
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"this code was already {row.status}",
        )
    row.status = "approved"
    row.user_id = user.id
    row.requested_scope = payload.scope.value
    db.commit()
    db.refresh(row)
    return row


@router.post("/{user_code}/deny", status_code=status.HTTP_204_NO_CONTENT)
def deny_device_authorization(
    user_code: str,
    db: DbSession,
    user: CurrentActiveUser,
) -> Response:
    """Deny a pending device-flow login. 409 if it isn't `pending` anymore (same state-conflict
    reasoning as `approve`)."""
    row = _get_live_row_or_404(db, user_code)
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"this code was already {row.status}",
        )
    row.status = "denied"
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
