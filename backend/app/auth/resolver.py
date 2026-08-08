"""ADR 0002's five-step resolver, and the HTTP contract wrapped around it.

The five steps, unchanged from the ADR:

1. Take the bearer verbatim. **Do not inspect its prefix.**
2. Look up ``sha256(raw_token)`` in a TTL cache.
3. On a miss, call pandan's ``GET /api/v1/me`` with the bearer forwarded unchanged — **once**,
   however many threads missed at the same moment (KAN-666, ``app.auth.single_flight``).
4. On success, ensure a local ``user`` mirror row exists, keyed on pandan's UUID.
5. Return it. (Step 5 proper — ``authorize_note`` — is ``app.auth.authorization``, KAN-535.)

Nothing here touches FastAPI's dependency machinery — that is ``app.auth.dependencies``, which is
wiring and nothing else. The split is what lets the status codes and error bodies below, including
Q9's `503`, be asserted by the no-infrastructure test layer: ``principal_from_bearer`` is an
ordinary function taking an ordinary object.
"""

from typing import Any

from fastapi import HTTPException, status

from app.auth.cache import PrincipalCache, digest
from app.auth.principal import (
    Principal,
    PrincipalMirror,
    TokenRejected,
    UpstreamUnavailable,
)
from app.auth.single_flight import SingleFlight
from app.auth.upstream import IdentityUpstream


class PrincipalResolver:
    """Bearer in, ``Principal`` out — or ``TokenRejected`` / ``UpstreamUnavailable``.

    Four injected collaborators and no framework, so the whole of ADR 0002's resolver runs in a
    unit test against in-memory fakes: no network, no database, no real PAT.
    """

    def __init__(
        self,
        *,
        upstream: IdentityUpstream,
        mirror: PrincipalMirror,
        cache: PrincipalCache,
        single_flight: SingleFlight,
    ) -> None:
        self._upstream = upstream
        self._mirror = mirror
        self._cache = cache
        # Required rather than defaulted, deliberately. A `SingleFlight()` default would look
        # harmless and be worse than nothing: `get_resolver` builds a resolver *per request*, so
        # every caller would get a private registry, coalesce with nobody, and pass every test in
        # this file — including the concurrency one, which would then be asserting about a stampede
        # that no longer happens through the object under test.
        self._single_flight = single_flight

    def resolve(self, bearer: str) -> Principal:
        hit, cached = self._cache.lookup(bearer)
        if hit:
            if cached is None:
                raise TokenRejected
            # Note what is *not* here: no upstream call, no mirror call, no database work at all.
            # That is what lets a cached session survive a pandan restart (ADR 0002 §Failure
            # behaviour), and what makes the steady-state cost a dict lookup rather than a hop.
            return cached

        # A miss. Every concurrent miss for *this* token collapses into one round trip; a miss for
        # a different token is a different key and is not held up behind this one. The key is the
        # digest, so the registry never holds a raw credential (ADR 0002, `single_flight.py`).
        #
        # The waiters skip the mirror as well as the round trip, and that is right rather than an
        # oversight: the leader's `ensure` has committed by the time anyone is woken, and a cache
        # *hit* has always skipped the mirror for the same reason. What a waiter must not skip is
        # the leader's failure — `SingleFlight` re-raises it, which is what keeps an outage a `503`
        # for all forty callers instead of a `401` for thirty-nine of them.
        principal = self._single_flight.do(digest(bearer), lambda: self._introspect(bearer))

        if principal is None:
            raise TokenRejected
        return principal

    def _introspect(self, bearer: str) -> Principal | None:
        """The uncached path, run by exactly one thread per token at a time.

        ``None`` is a rejection and is a *result*, not an error: it has to travel back through
        ``SingleFlight`` as a return value so every waiter caches and raises the same way.
        """
        # The second half of a double-check, and it closes a real window rather than tidying one.
        # ``resolve`` looked in the cache *before* asking for the key, so a thread can miss, lose
        # the race to a leader that then finishes and retires the key, and arrive here as a brand
        # new leader for an answer that is already cached. Coalescing cannot help — by then there
        # is nothing in flight to join. On a cold pandan that mistake costs a second twenty-second
        # round trip, which is worth one dict lookup to avoid.
        hit, cached = self._cache.lookup(bearer)
        if hit:
            return cached

        principal = self._upstream.introspect(bearer)

        if principal is None:
            self._cache.remember(bearer, None)
            return None

        # Mirror before caching. If the mirror fails, this request fails loudly and the next one
        # retries; caching first would paper over a broken mirror for a whole TTL and leave later
        # writes pointing at an owner_id with no row behind it.
        self._mirror.ensure(principal)
        self._cache.remember(bearer, principal)
        return principal


def error_body(code: str, message: str, **extra: Any) -> dict[str, dict[str, Any]]:
    """The error shape. One builder, so a status is never paired with a bare prose string.

    ``{"error": {"code", "message", …}}`` reaches the wire exactly as written. KAN-536 settled that
    (``app/api/errors.py``): FastAPI's default handler wraps a raise site's ``detail``, so this
    object used to arrive double-nested under ``detail``, and one handler at the app boundary
    un-nests it. Nothing at a raise site had to change, which is the point of there being one
    builder.

    ``code`` and ``message`` are always strings, and a refusal a human reads is those two alone.
    ``**extra`` is usually a string too — ``field`` on a `422`, ``ref`` on a bad identifier — but it
    is not restricted to one, because some refusals are only actionable with data attached: ADR
    0009's `409` carries two whole notes so the caller can diff them
    (``app/api/concurrency.py``). Anything passed here must be JSON-encodable;
    ``jsonable_encoder`` in the boundary handler does the rest.
    """
    return {"error": {"code": code, "message": message, **extra}}


def principal_from_bearer(bearer: str | None, resolver: PrincipalResolver) -> Principal:
    """The whole HTTP contract for authentication, with none of FastAPI's plumbing.

    ``bearer`` is the credential *after* Starlette has stripped the ``Bearer `` scheme, or ``None``
    if the request carried no usable ``Authorization`` header.
    """
    if bearer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_body("authentication_required", "a bearer token is required"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return resolver.resolve(bearer)
    except TokenRejected:
        # One code for both cases, because pandan returns one answer for both cases: a garbage
        # string and a revoked PAT come back byte-identical. Claiming to know which is which would
        # be a guess dressed up as a diagnosis, and guessing at a token's shape is the thing ADR
        # 0002 exists to forbid.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_body("invalid_token", "pandan did not accept this token"),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except UpstreamUnavailable as exc:
        # Q9, and the one status in this file worth arguing about: never a 401. A 401 here tells a
        # client its credential is bad when the credential is fine, and sends it into a rotation
        # loop over somebody else's outage. The body names pandan so the operator reads "the
        # identity provider is down" rather than "my token expired".
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_body(
                "upstream_unavailable",
                f"kaya could not reach pandan to resolve this token: {exc}",
                upstream="pandan",
            ),
            headers={"Retry-After": "5"},
        ) from exc
