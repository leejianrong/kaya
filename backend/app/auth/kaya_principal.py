"""ADR 0012's resolver: kaya's own identity, not pandan's introspection (KAN-1740).

Mirrors pandan's own principal resolution exactly (its CLAUDE.md: "cookie session → User; else PAT
bearer → its owning User; else 401") rather than ADR 0002's five-step version this replaces. Two
ways in, one ``Principal`` out, and both are a single indexed row lookup on the sync session every
note/board route already holds:

1. A live ``kaya_session`` cookie (``app/identity/models.py``'s ``KayaSession``, the
   ``DatabaseStrategy`` table KAN-1738 built) — a primary-key lookup, then the account it points at.
2. A ``kaya_pat_…`` bearer (``app/identity/pat.py``'s ``PersonalAccessToken``) — an
   HMAC-SHA256 hash lookup, then the account it points at.

**No cache, no upstream, no single-flight — and that absence is the entire point of ADR 0012, not
an oversight.** Every one of those existed solely to make a slow, fallible network call to pandan
survivable (KAN-666's cold-start measurement, KAN-539's stampede). There is no network call left
here to protect a caller from: a local indexed lookup costs microseconds, not the twenty seconds a
cold pandan cost, so nothing this module does needs shielding from its own cost the way ADR 0002's
resolver did.

**One outcome for "no", same as before.** A missing row, an expired PAT, an inactive account, and a
cookie pointing nowhere all resolve to `None` here — the same flattening pandan's own `GET
/api/v1/me` forced on ADR 0002's resolver (a malformed token and a revoked one came back
byte-identical), continued on purpose rather than an opportunity to finally distinguish them. No
caller depended on kaya drawing that line before, and inventing one now would be new behaviour
nobody asked for, wearing a "cleanup" label.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.principal import Principal
from app.identity.models import KayaAccount, KayaSession
from app.identity.pat import PersonalAccessToken, hash_token


def principal_from_cookie(session: Session, cookie_token: str | None) -> Principal | None:
    """`cookie_token` is the raw value of kaya's own session cookie (`app.identity.backend
    .COOKIE_NAME`), or `None` if the request carried none — the caller's job, not this function's,
    to know which cookie name that is; this module only knows what a `KayaSession` row means once
    handed one."""
    if cookie_token is None:
        return None

    kaya_session = session.get(KayaSession, cookie_token)
    if kaya_session is None:
        return None

    account = session.get(KayaAccount, kaya_session.user_id)
    if account is None or not account.is_active:
        return None

    return Principal(id=account.id, email=account.email)


def principal_from_pat(session: Session, bearer: str | None, *, secret: str) -> Principal | None:
    """`secret` is always ``get_settings().kaya_auth_secret`` at a real call site, passed explicitly
    rather than read here so this function stays a pure one with no `Settings` dependency to fake
    in a test — the same discipline `app/identity/pat.py`'s own `hash_token` already keeps.

    Stamps `last_used_at` on a successful lookup — the one place this module writes rather than
    reads, and a `commit()` the caller does not have to remember to do."""
    if bearer is None:
        return None

    token_hash = hash_token(bearer, secret)
    pat = session.scalars(
        select(PersonalAccessToken).where(PersonalAccessToken.token_hash == token_hash)
    ).one_or_none()
    if pat is None:
        return None

    now = datetime.now(UTC)
    if pat.expires_at is not None and pat.expires_at <= now:
        return None

    account = session.get(KayaAccount, pat.user_id)
    if account is None or not account.is_active:
        return None

    pat.last_used_at = now
    session.commit()
    return Principal(id=account.id, email=account.email)


def resolve_principal(
    session: Session,
    *,
    cookie_token: str | None,
    bearer: str | None,
    secret: str,
) -> Principal | None:
    """Cookie first, matching pandan's own precedence — a browser holding both a stale bearer and a
    fresh session should get the fresh one, not a coin flip over which header wins. Falls through to
    the bearer only when the cookie names no live session, never when it names one that has simply
    expired versus one that never existed — this function does not need to (and does not) tell those
    two apart, per the module docstring's "one outcome for no"."""
    principal = principal_from_cookie(session, cookie_token)
    if principal is not None:
        return principal
    return principal_from_pat(session, bearer, secret=secret)
