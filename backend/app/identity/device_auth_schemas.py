"""What a device-flow login looks like on the wire (ADR 0013, KAN-1743, mirrors pandan ADR 0024's
own schemas — minus every board/workspace field, which kaya has no analogue for).

Separate from `pat_schemas.py` for the reason that file gives for being separate from
`app/identity/schemas.py`: `app/identity/device_auth_router.py` needs these and nothing else does.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.identity.pat_schemas import TokenScope


class DeviceCodeRequest(BaseModel):
    """``POST /auth/device/code`` — what the CLI asks for before a human has done anything. A
    pre-fill the consent screen shows and a human may change before approving; not binding until
    approval."""

    scope: TokenScope = TokenScope.write


class DeviceCodeResponse(BaseModel):
    """The RFC 8628 §3.2 response shape, verbatim field names so a spec-aware client needs no
    translation layer."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DeviceTokenRequest(BaseModel):
    """``POST /auth/device/token`` — polled by the CLI at ``interval``-second intervals with the
    ``device_code`` from `DeviceCodeResponse`."""

    device_code: str


class DeviceAuthorizationRead(BaseModel):
    """``GET /auth/device/{user_code}`` — what the consent screen renders: the requested scope and
    the code's current status, so a re-visited link (already approved/denied) reads as that state
    rather than a mysterious 404."""

    user_code: str
    status: Literal["pending", "approved", "denied"]
    requested_scope: TokenScope
    expires_at: datetime


class DeviceApproveRequest(BaseModel):
    """``POST /auth/device/{user_code}/approve`` — the human's final scope choice, pre-filled by the
    consent screen from `DeviceAuthorizationRead` but editable before submitting. Replaces (not
    merges with) the originally requested scope — approving is a fresh grant, not a diff against the
    request."""

    scope: TokenScope = TokenScope.write
