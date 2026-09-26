"""What the device-flow endpoints look like on the wire (ADR 0013, KAN-1743).

Separate from `app/identity/pat_schemas.py` for the same reason that file is separate from
`app/identity/schemas.py`: these exist because `app/identity/device_auth.py` needs them, not because
a device-flow login *is* a `PersonalAccessToken` — it mints one, but the two request/response shapes
have nothing else in common.
"""

from datetime import datetime

from pydantic import BaseModel

from app.identity.pat_schemas import TokenScope


class DeviceCodeRequest(BaseModel):
    """`POST /auth/device/code`'s body: which scope the CLI is asking for. No board/workspace
    picker (ADR 0013) — kaya has no board-equivalent entity, so this is the whole request."""

    scope: TokenScope = TokenScope.write


class DeviceCodeResponse(BaseModel):
    """`POST /auth/device/code`'s response — RFC 8628 §3.2's field names, verbatim, since a
    spec-aware device-flow client reads them by name."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DeviceAuthorizationRead(BaseModel):
    """The consent screen's own read (`GET /auth/device/{user_code}`) **and** its own write
    (`POST .../approve`, `POST .../deny`'s error path) — one shape for all three, so the consent
    screen can render "you already approved this" from whichever call answered without a second
    shape to reconcile."""

    user_code: str
    status: str
    requested_scope: TokenScope
    expires_at: datetime
