"""What a caller *is*, the seam that persists it, and the two ways resolution fails.

Kept in its own module so the interesting parts — the cache, the upstream client, the resolver —
depend on types rather than on each other. That is what lets the unit layer run the whole resolver
against in-memory fakes with no network and no database (dev-playbook §1, §2).

``Principal`` carries exactly what pandan's ``GET /api/v1/me`` returns: an id and an email. It is
deliberately *not* the SQLAlchemy row. The row is a mirror of this, and kaya's authorization
decisions read the UUID, so the resolver can answer without the database having been touched on
this request.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Principal:
    """A resolved caller. The UUID is pandan's, never one kaya generated (ADR 0002)."""

    id: uuid.UUID
    email: str


class PrincipalMirror(Protocol):
    """Ensures a local ``user`` row exists for a principal, creating it just-in-time.

    A seam rather than a direct call for two reasons. It is what makes the resolver testable
    without Postgres, and it keeps the mirror's *only* job — "this UUID must be addressable as a
    foreign key" — separable from the question of who the caller is. Implementations must be
    idempotent: step 4 of ADR 0002's resolver runs on every cache miss, not only the first ever.
    """

    def ensure(self, principal: Principal) -> None: ...


class TokenRejected(Exception):
    """Pandan looked at the bearer and said no.

    Deliberately one exception and not two. Pandan answers `401` with the same body for a garbage
    string and for a revoked PAT — it does not distinguish, and kaya inventing a distinction would
    mean guessing at a token's shape, which is the whole thing ADR 0002 forbids.

    Carries no token, not even a fragment: this reaches an exception handler and a log line.
    """


class UpstreamUnavailable(Exception):
    """Pandan could not be asked, so kaya does not know and says so.

    Distinct from ``TokenRejected`` on purpose, and the distinction is the point of Q9: this
    becomes a `503` naming pandan, never a `401`. A `401` here would tell a client its credential
    is bad when the credential is fine, and send it into a token-rotation loop over someone else's
    outage.
    """
