"""Kaya's own personal access tokens (ADR 0012, KAN-1739 — mirrors pandan ADR 0014).

**Read through the SYNC engine, unlike everything else in this package.** A PAT is *our* table —
``app/db.py``'s plain ``get_session()``, an indexed ``SELECT`` on ``token_hash`` — not
``fastapi-users``' async store. That matters because note/board authentication (once `KAN-1740`
wires a PAT bearer into it) happens on the sync request path ADR 0001 pins; a PAT model that lived
only behind the async engine would force that path async too, which is exactly the drift
`app/db.py`'s own docstring warns about. The model shares kaya's one ``Base`` (same reasoning as
``app/identity/models.py``), so nothing about *reading* it needs the async engine at all —
SQLAlchemy models aren't bound to one engine, only sessions are.

**Hash, never the secret (R7.1).** The raw token is `kaya_pat_<43 url-safe chars>` — a 256-bit
random secret, returned to the caller **once**, on creation. Only **HMAC-SHA256 keyed with
`KAYA_AUTH_SECRET`** (a pepper) is stored, plus a short non-secret ``token_prefix`` for the UI list.

**Deliberately not bcrypt/argon2**, for the same reason pandan ADR 0014 gives: auth here is a
single ``WHERE token_hash = :h`` lookup, not a linear scan a per-row salt would force. A password
hash salts to slow brute force on a *low-entropy* secret a human chose; a 256-bit random token
needs neither the slowness nor the scan. The pepper means a stolen database alone can't verify a
guessed token offline.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TOKEN_PREFIX = "kaya_pat_"
"""Human-readable, greppable marker — a leaked token is recognisable, and secret scanners flag it.
No legacy prefix to carry: unlike pandan's `pandan_pat_`/`kanban_pat_` split (a post-rebrand
artifact), kaya's PATs have never been named anything else."""

PREFIX_DISPLAY_LEN = len(TOKEN_PREFIX) + 4
"""How much of the raw token the UI list may show — enough to tell two tokens apart, never enough
to be useful to an attacker who saw only the display value."""

TOKEN_SCOPES = ("read", "write")
"""`read` = observer (GET only); `write` = operator (the owning account's full access). Enforced at
auth time once `KAN-1740` wires a PAT bearer into `get_principal`'s replacement — this table and its
CHECK constraint exist first so that enforcement has something to read."""


class PersonalAccessToken(Base):
    """One row per minted `kaya_pat_…` secret, `ON DELETE CASCADE` from `kaya_account` — deleting
    an account revokes every token it ever minted, with nothing left dangling."""

    __tablename__ = "personal_access_token"

    __table_args__ = (
        # `name="scope"`, not `"ck_personal_access_token_scope"`: `app/models/base.py`'s naming
        # convention already builds `ck_%(table_name)s_%(constraint_name)s` from whatever `name`
        # is given here, so passing the fully-built name double-prefixes it
        # (`ck_personal_access_token_ck_personal_access_token_scope` — caught by re-diffing this
        # migration against the model before committing it).
        CheckConstraint("scope IN ('read', 'write')", name="scope"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kaya_account.id", ondelete="cascade"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    """Caller-chosen, for telling tokens apart in the UI list — not unique, not interpreted."""

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    """HMAC-SHA256 hex digest (64 chars). Unique + indexed: the whole auth-time lookup is one
    `WHERE token_hash = :h`."""

    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    """E.g. `kaya_pat_ab12` — a non-secret display hint, never the full secret."""

    scope: Mapped[str] = mapped_column(String(16), nullable=False, server_default="write")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Stamped on each successful auth once `KAN-1740` wires this table into request
    authentication — `None` until then, and `None` forever for a token that is minted and never
    used."""

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Optional; `None` means never. Enforced at auth time, not by this table."""


def hash_token(raw: str, secret: str) -> str:
    """HMAC-SHA256(secret, raw) as a 64-char hex digest. `secret` is always
    ``get_settings().kaya_auth_secret`` at a real call site — passed explicitly rather than read
    here, so this function stays a pure one with no `Settings` dependency to fake in a test."""
    return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()


def generate_token(secret: str) -> tuple[str, str, str]:
    """Mint a new PAT → `(raw, token_prefix, token_hash)`.

    `raw` is returned to the caller **once** and is never stored; persist only `token_prefix` (the
    display hint) and `token_hash`.
    """
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:PREFIX_DISPLAY_LEN], hash_token(raw, secret)
