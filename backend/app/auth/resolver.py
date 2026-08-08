"""ADR 0002's five-step resolver, and the HTTP contract wrapped around it.

The five steps, unchanged from the ADR:

1. Take the bearer verbatim. **Do not inspect its prefix.**
2. Look up ``sha256(raw_token)`` in a TTL cache.
3. On a miss, call pandan's ``GET /api/v1/me`` with the bearer forwarded unchanged.
4. On success, ensure a local ``user`` mirror row exists, keyed on pandan's UUID.
5. Return it. (Step 5 proper — ``authorize_note`` — is ``app.auth.authorization``, KAN-535.)

Nothing here touches FastAPI's dependency machinery — that is ``app.auth.dependencies``, which is
wiring and nothing else. The split is what lets the status codes and error bodies below, including
Q9's `503`, be asserted by the no-infrastructure test layer: ``principal_from_bearer`` is an
ordinary function taking an ordinary object.
"""

from fastapi import HTTPException, status

from app.auth.cache import PrincipalCache
from app.auth.principal import (
    Principal,
    PrincipalMirror,
    TokenRejected,
    UpstreamUnavailable,
)
from app.auth.upstream import IdentityUpstream


class PrincipalResolver:
    """Bearer in, ``Principal`` out — or ``TokenRejected`` / ``UpstreamUnavailable``.

    Three injected collaborators and no framework, so the whole of ADR 0002's resolver runs in a
    unit test against two in-memory fakes: no network, no database, no real PAT.
    """

    def __init__(
        self,
        *,
        upstream: IdentityUpstream,
        mirror: PrincipalMirror,
        cache: PrincipalCache,
    ) -> None:
        self._upstream = upstream
        self._mirror = mirror
        self._cache = cache

    def resolve(self, bearer: str) -> Principal:
        hit, cached = self._cache.lookup(bearer)
        if hit:
            if cached is None:
                raise TokenRejected
            # Note what is *not* here: no upstream call, no mirror call, no database work at all.
            # That is what lets a cached session survive a pandan restart (ADR 0002 §Failure
            # behaviour), and what makes the steady-state cost a dict lookup rather than a hop.
            return cached

        principal = self._upstream.introspect(bearer)

        if principal is None:
            self._cache.remember(bearer, None)
            raise TokenRejected

        # Mirror before caching. If the mirror fails, this request fails loudly and the next one
        # retries; caching first would paper over a broken mirror for a whole TTL and leave later
        # writes pointing at an owner_id with no row behind it.
        self._mirror.ensure(principal)
        self._cache.remember(bearer, principal)
        return principal


def error_body(code: str, message: str, **extra: str) -> dict[str, dict[str, str]]:
    """The error shape. One builder, so a status is never paired with a bare prose string.

    **On the wire this ends up double-nested, and that is an artefact rather than a decision.**
    FastAPI's default handler wraps whatever it is given in ``{"detail": ...}``, so a caller sees
    ``{"detail": {"error": {"code": ...}}}``. Nothing consumes it yet — there are no routes under
    ``/api/v1``.

    KAN-536 owns the API error contract and should pick the shape on purpose. If it wants a bare
    ``{"error": {...}}``, an ``@app.exception_handler(HTTPException)`` that returns
    ``exc.detail`` when it is already a mapping is the whole change, and these call sites stay as
    they are. Flagged here so the accident is not inherited as a default.
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
