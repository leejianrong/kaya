"""RFC 8628 Device Authorization Grant: the `device_authorization` table and the grant's own
primitives (ADR 0013, KAN-1743).

Mirrors pandan ADR 0024's shape independently (ADR 0012's reimplement-not-share stance) — same
mechanics (a high-entropy, hashed `device_code` the CLI polls with; a short, human-typed `user_code`
as a `gh auth login`-style fallback/confirmation), **minus the board/workspace picker** ADR 0013
explicitly drops: kaya has no board-equivalent entity, so a device-flow-minted `kaya_pat_…` is
always account-wide, exactly like every other kaya PAT.

**`device_code` is hashed with `app.identity.pat.hash_token`, the same function and the same
`KAYA_AUTH_SECRET` pepper a PAT itself uses** — it is a bearer secret a network observer could
otherwise replay, and there is no reason for a second hashing scheme to exist beside the first one.
`user_code` is stored as-is: the consent screen it points at requires an authenticated human session
regardless, so its only job is being findable, not being secret.

**Expiry and poll interval are implementation details ADR 0013 leaves to the build**, pinned here at
RFC 8628's own suggested defaults (15 minutes, 5 seconds) — the same numbers pandan's build
independently chose for the same reason, which is a coincidence of both following the RFC's own
advice rather than a shared implementation.

**Poll-interval enforcement is in-process memory, not a DB column**, mirroring
`app/auth/cache.py`'s own accepted MVP tradeoff for the identical reason: a row lives at most 15
minutes, so losing its poll-cadence state to a process restart is inconsequential, and it avoids a
schema column and a write on every single poll.
"""

import secrets
import time
import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DEVICE_CODE_TTL_SECONDS = 900
"""15 minutes — long enough that switching to a browser, signing in via GitHub if not already, and
reviewing the consent screen is never rushed; short enough that a stale, un-actioned code cannot be
resurrected days later."""

DEVICE_POLL_INTERVAL_SECONDS = 5
"""RFC 8628's own suggested floor. A poll faster than this gets `slow_down` (`too_soon_to_poll`)."""

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
DEVICE_AUTHORIZATION_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_DENIED)


class DeviceAuthorization(Base):
    """One in-flight (or just-resolved) device-flow login.

    Created by `POST /auth/device/code` (no auth — the CLI has no credential yet) and polled by
    `POST /auth/device/token` (also no auth — the device code itself is the credential) until it
    resolves. A human, already holding kaya's own cookie session, visits
    `verification_uri_complete`, sees the consent screen, and approves or denies — that stamps
    `user_id` and flips `status`.

    **The PAT is minted at first-poll-after-approval, not at approval time** (mirroring pandan
    ADR 0024's identical choice, and for the identical reason): minting at approval time would mean
    holding a raw secret in this table between approval (in the browser) and retrieval (the CLI's
    next poll), which is the plaintext-secret-at-rest pattern `app/identity/pat.py` exists
    specifically to avoid. `approve` only stamps `status`/`user_id`; `poll_device_token`
    (`app/identity/device_auth.py`) does the actual minting, via `app.identity.pat.generate_token` —
    a new minting *path* for an existing credential type, not a new storage pattern.
    """

    __tablename__ = "device_authorization"

    __table_args__ = (
        CheckConstraint(f"status IN {DEVICE_AUTHORIZATION_STATUSES!r}", name="status"),
        CheckConstraint("requested_scope IN ('read', 'write')", name="requested_scope"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    device_code_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    """HMAC-SHA256 hex digest, `app.identity.pat.hash_token`'s own shape — never the raw secret."""

    user_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    """The short, human-typed code (e.g. `WDJB-MJHT`). Stored as-is; see the module docstring."""

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUS_PENDING)

    requested_scope: Mapped[str] = mapped_column(String(16), nullable=False, server_default="write")
    """What the CLI asked for when it created this row (`kaya auth login --scope`). The consent
    screen shows it; approving mints a PAT with exactly this scope — there is no override step,
    unlike pandan's board picker, because there is nothing here for a human to narrow."""

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kaya_account.id", ondelete="cascade"), nullable=True
    )
    """Set by the consent-screen approval; `NULL` until then. `CASCADE`: deleting the approving
    account removes its completed device-authorization rows too, mirroring `PersonalAccessToken`'s
    own disposition."""

    pat_id: Mapped[int | None] = mapped_column(
        ForeignKey("personal_access_token.id", ondelete="set null"), nullable=True
    )
    """The token minted on first successful poll. `SET NULL` rather than `CASCADE`: revoking the
    minted token from the Tokens UI afterward must not delete this row's own history of how that
    token came to exist."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Stamped the one time `POST /auth/device/token` returns a minted PAT — a second poll after
    that must not hand out the secret again, mirroring why a PAT itself is never re-displayed."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- Crockford-ish user codes: uppercase letters + digits, minus 0/O/1/I/L (visually ambiguous in
# most fonts, and the same set `gh auth login`'s own user codes avoid). ---------------------------

_USER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_USER_CODE_GROUP_LEN = 4
_USER_CODE_GROUPS = 2


def generate_device_code() -> str:
    """A high-entropy bearer secret, never shown to a human. Store only its hash."""
    return secrets.token_urlsafe(32)


def generate_user_code() -> str:
    """A short, human-typeable code: two groups of four from the restricted alphabet, joined with a
    hyphen (e.g. `"WDJB-MJHT"`). ~26 bits of entropy — plenty for a secret whose real job is
    uniqueness among the handful of codes live at any moment, not brute-force resistance (the
    consent screen it points at requires an authenticated human session regardless)."""
    groups = [
        "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(_USER_CODE_GROUP_LEN))
        for _ in range(_USER_CODE_GROUPS)
    ]
    return "-".join(groups)


class _PollThrottle:
    """The in-process poll-cadence tracker. A class rather than a bare module dict so a test can
    build its own instance instead of mutating shared process state (`app/auth/cache.py`'s own
    reason for taking a `clock` rather than reading `time.monotonic` at class-definition time)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._last_polled_at: dict[str, float] = {}

    def too_soon(self, device_code_hash: str) -> bool:
        """`True` if this code was polled less than `DEVICE_POLL_INTERVAL_SECONDS` ago — the caller
        should answer `slow_down` rather than evaluating status. Always records this poll's
        timestamp as a side effect, whether or not it was too soon, so a client that ignores
        `slow_down` and keeps polling at the same cadence keeps getting `slow_down` rather than
        sneaking in on alternating requests."""
        now = self.clock()
        last = self._last_polled_at.get(device_code_hash)
        self._last_polled_at[device_code_hash] = now
        return last is not None and (now - last) < DEVICE_POLL_INTERVAL_SECONDS

    def forget(self, device_code_hash: str) -> None:
        """Drop the poll-cadence entry once a code resolves — it will never be polled meaningfully
        again, and an unbounded dict across a long process lifetime is the failure mode worth a
        one-line guard against."""
        self._last_polled_at.pop(device_code_hash, None)


poll_throttle = _PollThrottle()
"""The process-wide instance `app/identity/device_auth.py` uses. `app/identity/dependencies.py`
(if a test ever needs a fresh one) replaces this module attribute rather than adding a `Depends` —
there is exactly one process-wide cache here, the same shape `get_card_epic_cache` gives its own."""
