"""RFC 8628 Device Authorization Grant state (ADR 0013, KAN-1743, mirrors pandan ADR 0024's own
`DeviceAuthorization` table) — `kaya auth login`'s server-side half.

A row is created by ``POST /auth/device/code`` (the CLI, no auth) and polled by
``POST /auth/device/token`` (also the CLI, no auth — the device code itself is the credential)
until it resolves. A **human**, authenticated by kaya's own cookie session
(`app/identity/device_auth_router.py`'s module docstring explains why the consent routes gate on
that specifically, not on `get_principal`), visits ``verification_uri_complete``, sees the consent
screen (requested scope, pre-filled from ``requested_scope`` but editable), and approves or denies
— that request stamps ``user_id`` + flips ``status``, and approval also mints the real
``personal_access_token`` row this table points at via ``pat_id``.

**No board/workspace scoping column** — the one deliberate difference from pandan's own table.
ADR 0013 is explicit: kaya has no board-equivalent entity, so every `kaya_pat_…`
(device-flow-minted or not) is account-wide. Pandan's `requested_board_ids`/allow-list join table
have no analogue here.

**Short-lived and single-use** (ADR 0013, mirroring ADR 0024): ``expires_at`` is set at creation
(~15 min out, pinned by `app/identity/device_flow.py`, not here) and ``redeemed_at`` is stamped the
one time ``POST /auth/device/token`` returns a successful raw PAT — a second poll after that must
not hand out the secret again, mirroring why a PAT itself is never re-displayed after minting.

``device_code`` is stored **hashed**, exactly like a PAT (`app/identity/pat.py`'s `hash_token`),
since it is a bearer secret a network observer could otherwise replay. ``user_code`` is the short,
human-typed fallback and is stored as-is — it is not a secret on its own (the consent screen
requires an authenticated human session to act on it), only a lookup key.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DeviceAuthorization(Base):
    """One RFC 8628 device-flow login attempt, from creation through approval/denial/expiry to the
    PAT it mints (or never mints)."""

    __tablename__ = "device_authorization"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'denied')", name="status"),
        CheckConstraint("requested_scope IN ('read', 'write')", name="requested_scope"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    device_code_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    """HMAC-SHA256 hex digest (64 chars), like `PersonalAccessToken.token_hash` — unique + indexed
    for the polling endpoint's O(1) lookup."""

    user_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    """The short code shown to the human as a fallback/confirmation (e.g. `"WDJB-MJHT"`). Unique so
    the consent-screen lookup by code alone is unambiguous."""

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kaya_account.id", ondelete="cascade"), nullable=True
    )
    """Set by the consent-screen approval; `None` until then. CASCADE: deleting the approving
    account removes its completed device-authorization rows too, mirroring `PersonalAccessToken`'s
    own CASCADE."""

    requested_scope: Mapped[str] = mapped_column(String(16), nullable=False, server_default="write")
    """The scope the CLI asked for when it created this row — the consent screen pre-fills from this
    but the human may change it before approving."""

    pat_id: Mapped[int | None] = mapped_column(
        ForeignKey("personal_access_token.id", ondelete="set null"), nullable=True
    )
    """The minted PAT, set only on approval's first successful poll. SET NULL (not CASCADE):
    revoking the resulting PAT later should not silently rewrite this row's own history of what was
    approved and when."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
