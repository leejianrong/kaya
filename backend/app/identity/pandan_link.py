"""A kaya account's linked pandan credential (ADR 0012's amendment, KAN-1741).

**Why this table exists at all.** Before ADR 0012's cutover, the same PAT authenticated both apps
(ADR 0002: kaya minted nothing of its own and forwarded whatever bearer it was handed straight to
pandan). `app/integrations/board_embed.py`'s live `pandan-board` preview free-rode on that: it
forwarded *the caller's own kaya-side bearer* to pandan and it just happened to work, because there
was only ever one bearer. `KAN-1740` ended that — the caller's bearer is now a `kaya_pat_…` kaya
minted itself, or nothing at all (a cookie session carries no bearer to forward), and pandan has
never seen either. A board embed forwarding it now reaches pandan with a credential pandan cannot
recognise, which the existing "unavailable" degrade path (correctly) can't tell apart from pandan
being down. This table is what makes that distinguishable and fixable: an explicit, one-time
"connect your pandan account" step, after which kaya holds pandan's *own* PAT on the caller's
behalf and forwards *that* instead.

**Encrypted, not hashed — the opposite of `app/identity/pat.py`'s own PAT.** Kaya's own PATs are
hashed because kaya only ever needs to *verify* one was presented, never to produce it again. A
linked pandan token is the reverse: kaya must hand the raw secret to pandan on every embed render,
so a one-way hash is useless here — the plaintext has to be recoverable. `Fernet` (AES-128-CBC +
HMAC-SHA256, from the `cryptography` package already a transitive dependency of `httpx-oauth`/
`fastapi-users`, now an explicit one) with a key derived from `KAYA_AUTH_SECRET` is the smallest
honest answer: symmetric, authenticated (a tampered or truncated ciphertext raises rather than
decrypting to garbage), and it costs no new secret to provision or rotate — `KAYA_AUTH_SECRET`
already doing double duty for OAuth CSRF signing and kaya's own PAT hashing (`pat.py`'s own
docstring) picks up a third use here. Rotating it invalidates every stored link the same way it
already invalidates every cookie session and PAT hash — expected, and a caller finds out the
honest way (`decrypt_token` returning `None`), not a crash.

One row per `kaya_account`, enforced by a unique index on `user_id` rather than allowing several:
pandan has no multi-account concept for kaya to mirror, and "which one forwards to a board embed"
is a UI decision this table has no business making for a caller who linked two.
"""

import base64
import hashlib
import uuid
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PandanLink(Base):
    """One kaya account's linked pandan PAT, `ON DELETE CASCADE` from `kaya_account` — deleting an
    account takes its linked credential with it, the same disposition `PersonalAccessToken` already
    has."""

    __tablename__ = "pandan_link"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kaya_account.id", ondelete="cascade"),
        nullable=False,
        unique=True,
        index=True,
    )
    """Unique, not just indexed: at most one linked pandan account per kaya account — see the
    module docstring for why a second link is not a case this table represents."""

    encrypted_token: Mapped[str] = mapped_column(String(1024), nullable=False)
    """A `Fernet` token (base64url text, comfortably under the column's width) wrapping pandan's raw
    PAT. Never the plaintext, never logged, never returned over the API — `app/api/pandan_link.py`
    exposes only `{"connected": bool}`, the same "don't reveal it exists beyond that" posture
    `app/api/tokens.py` already takes for kaya's own PATs."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _fernet_key(secret: str) -> bytes:
    """`KAYA_AUTH_SECRET` (arbitrary length) -> a 32-byte key, base64url-encoded the way `Fernet`
    requires. `sha256` rather than a slower KDF (PBKDF2/scrypt) on purpose: unlike a password, this
    secret is not attacker-chosen or low-entropy by construction — `pat.py`'s own hashing makes the
    identical call for the identical reason (a pepper, not a password)."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def encrypt_token(raw: str, secret: str) -> str:
    """Wrap a raw pandan PAT for storage. Returns ASCII text safe for `String(1024)`."""
    return Fernet(_fernet_key(secret)).encrypt(raw.encode()).decode("ascii")


def decrypt_token(encrypted: str, secret: str) -> str | None:
    """The inverse of `encrypt_token`, or `None` if it cannot be recovered — a `KAYA_AUTH_SECRET`
    rotation since the link was stored, or a corrupted row, both land here rather than raising.
    Callers treat `None` exactly like "never connected" (`app/api/embeds.py`): a link kaya can no
    longer read is indistinguishable, from the caller's chair, from one that was never made, and the
    fix is the same either way — reconnect."""
    try:
        return Fernet(_fernet_key(secret)).decrypt(encrypted.encode()).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
