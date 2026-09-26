"""RFC 8628 Device Authorization Grant *and* RFC 6749/7636 authorization_code+PKCE: the
`device_authorization` table and both grants' shared primitives (ADR 0013/KAN-1743, ADR 0014/
KAN-1744).

Mirrors pandan ADR 0024's shape independently (ADR 0012's reimplement-not-share stance) — same
mechanics (a high-entropy, hashed `device_code` the CLI polls with; a short, human-typed `user_code`
as a `gh auth login`-style fallback/confirmation), **minus the board/workspace picker** ADR 0013
explicitly drops: kaya has no board-equivalent entity, so a device-flow-minted `kaya_pat_…` is
always account-wide, exactly like every other kaya PAT.

**One table, two kinds of row, exactly like pandan's own `DeviceAuthorization`.** ADR 0014
(mirroring pandan ADR 0026) extends this same table for the browser-redirect authorization_code+PKCE
grant a hosted MCP client (Claude.ai, ChatGPT, Cursor) completes, rather than a parallel table — the
state either grant needs (pending → approved → consumed, expiring, single-use) is the same shape.
A row is one kind or the other, never both, enforced by `ck_device_authorization_kind` below:

- a **device-flow** row (ADR 0013) populates `device_code_hash`/`user_code` and leaves `client_id`
  (and everything after it) null;
- an **authorization-code-flow** row (ADR 0014) populates `client_id`/`redirect_uri`/
  `code_challenge`/`code_challenge_method`/`resource`/`code_hash` and leaves `device_code_hash`/
  `user_code` null. Unlike a device-flow row, it is inserted already `status="approved"` — nothing
  polls it beforehand (the `redirect_uri` callback is the poll), so there is no `pending` phase to
  occupy first. `code_hash` is looked up by `POST /auth/device/token`'s `grant_type=
  authorization_code` branch exactly like `device_code_hash` is for `grant_type=device_code`, and
  `redeemed_at` marks it single-use identically.

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
    """One in-flight (or just-resolved) device-flow login, **or** one approved
    authorization_code+PKCE grant — see the module docstring's kind split.

    A device-flow row is created by `POST /auth/device/code` (no auth — the CLI has no credential
    yet) and polled by `POST /auth/device/token` until it resolves. A human, already holding kaya's
    own cookie session, visits `verification_uri_complete`, sees the consent screen, and approves or
    denies — that stamps `user_id` and flips `status`.

    An authorization-code-flow row has no such `pending` phase: it is inserted already
    `status="approved"` by `POST /auth/authorize/approve`, since nothing polls it beforehand — the
    `redirect_uri` callback the browser follows next *is* the poll, immediately exchanged at
    `POST /auth/device/token`'s `grant_type=authorization_code` branch.

    **The PAT is minted at first-poll-after-approval, not at approval time** (mirroring pandan
    ADR 0024/0026's identical choice, and for the identical reason): minting at approval time would
    mean holding a raw secret in this table between approval (in the browser) and retrieval (the
    CLI's next poll, or the OAuth client's code exchange), which is the plaintext-secret-at-rest
    pattern `app/identity/pat.py` exists specifically to avoid. Approving either grant only stamps
    state on this row; `poll_device_token` (`app/identity/device_auth.py`) does the actual minting
    for both, via `app.identity.pat.generate_token` — a new minting *path* for an existing
    credential type, not a new storage pattern, and not a new credential shape either (ADR 0014's
    simplification from pandan's own short-lived-token-plus-refresh-token model).
    """

    __tablename__ = "device_authorization"

    __table_args__ = (
        CheckConstraint(f"status IN {DEVICE_AUTHORIZATION_STATUSES!r}", name="status"),
        CheckConstraint("requested_scope IN ('read', 'write')", name="requested_scope"),
        CheckConstraint(
            "(device_code_hash IS NOT NULL AND user_code IS NOT NULL AND client_id IS NULL)"
            " OR (device_code_hash IS NULL AND user_code IS NULL"
            " AND client_id IS NOT NULL AND code_hash IS NOT NULL)",
            name="kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    device_code_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    """HMAC-SHA256 hex digest, `app.identity.pat.hash_token`'s own shape — never the raw secret.
    Nullable: an authorization-code-flow row (ADR 0014) leaves this null; Postgres treats multiple
    `NULL`s in a unique index as distinct, so this doesn't collide across every such row."""

    user_code: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True)
    """The short, human-typed code (e.g. `WDJB-MJHT`). Stored as-is; see the module docstring.
    Nullable for the same reason as `device_code_hash` above."""

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

    # --- authorization-code-flow-only columns (ADR 0014, KAN-1744); null on every device-flow row,
    # see the class docstring's kind split. ---
    client_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """The requesting OAuth client: an RFC 7591 DCR `client_id` or a CIMD URL
    (`app.identity.oauth_client.resolve_client`) — no FK, since a CIMD client has no row."""

    redirect_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    """Validated at `GET /auth/authorize` time to be an exact match against the client's registered
    redirect URIs; re-checked again at token-exchange time against this stored value (RFC 6749
    §4.1.3) so a code can't be redeemed against a different `redirect_uri` than the one it was
    issued for."""

    code_challenge: Mapped[str | None] = mapped_column(String(128), nullable=True)
    code_challenge_method: Mapped[str | None] = mapped_column(String(16), nullable=True)

    resource: Mapped[str | None] = mapped_column(String, nullable=True)
    """RFC 8707 resource indicator — the MCP endpoint's canonical URI. Bound at `/auth/authorize`
    and re-checked at exchange time, exactly like `redirect_uri` above — the enforcement point
    ADR 0013 named and ADR 0014 built (`app.identity.oauth_authorize.canonical_mcp_resource`)."""

    code_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    """HMAC-SHA256 hex digest of the minted authorization `code` — the authorization-code-flow
    analogue of `device_code_hash` above, looked up the same way by `POST /auth/device/token`'s
    `grant_type=authorization_code` branch. Nullable for the same reason (a device-flow row never
    sets it)."""

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
