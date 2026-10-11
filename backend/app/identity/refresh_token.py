"""Rotating, single-use refresh tokens (ADR 0016, KAY-171).

An access token minted by an interactive grant (the device flow or `authorization_code`) is a
normal `personal_access_token` row with a one-hour `expires_at`. This table is how its client gets
the next one without a human approving consent again. Mirrors pandan's `OAuthRefreshToken`
(pandan ADR 0026).

**Single-use by rotation.** `POST /auth/device/token` with `grant_type=refresh_token` consumes
exactly one row: it stamps `consumed_at`, mints a fresh access token and inserts a fresh row. A
second use of a consumed token fails. Reuse does not revoke the rest of the family (pandan parity;
ADR 0016 defers it).

**The raw token is `kaya_rt_<43 url-safe chars>`**, which departs from pandan's bare string so that
the log scrubber (`app/observability/redaction.py`) and `.gitleaks.toml` can recognise one by its
shape. Only its HMAC-SHA256, keyed with `KAYA_AUTH_SECRET`, is stored, exactly like a PAT (see
`app/identity/pat.py` for the reasoning behind HMAC over bcrypt).
"""

import secrets
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.pat import hash_token
from app.models.base import Base

REFRESH_TOKEN_PREFIX = "kaya_rt_"

ACCESS_TOKEN_TTL_SECONDS = 3600
"""One hour. Short enough that a leaked access token stops working on its own."""

REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
"""Thirty days, the same as pandan. An idle client re-authenticates after this; an active one never
notices, since every refresh issues a new one."""

DEVICE_FLOW_CLIENT_ID = "kaya-cli"
"""The device flow registers no client, so its refresh tokens are bound to this fixed literal. It
must equal `kaya_client.refresh.REFRESH_CLIENT_ID`."""


class OAuthRefreshToken(Base):
    """One row per issued refresh token. `ON DELETE CASCADE` from the access token it is currently
    paired with, so revoking that token in Settings kills its refresh token too: there is no point
    refreshing into a credential that no longer exists."""

    __tablename__ = "oauth_refresh_token"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    """HMAC-SHA256 hex digest. Unique and indexed: redeeming is one `WHERE token_hash = :h`."""

    personal_access_token_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("personal_access_token.id", ondelete="cascade"),
        nullable=False,
        index=True,
    )

    client_id: Mapped[str] = mapped_column(String(200), nullable=False)
    """Re-checked on every refresh: a refresh token works only for the client it was issued to."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Stamped the one time this row is redeemed: single-use, independent of `expires_at`."""


def generate_refresh_token(secret: str) -> tuple[str, str]:
    """Mint a refresh token → `(raw, token_hash)`. `raw` is returned to the client once and never
    stored."""
    raw = REFRESH_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_token(raw, secret)
