"""FastAPI wiring, and nothing else.

Everything with a decision in it lives one module down (``kaya_principal.py`` for identity,
``team_resolver.py``/``team_cache.py``/``team_upstream.py`` for team-default access). What is left
here is which object gets built where and how long it lives, which is the part that cannot be
unit-tested without a framework and does not need to be.

**Identity's own process-wide singletons are gone (KAN-1740).** ADR 0002's resolver needed a
process-wide cache, upstream client and single-flight registry because a cold lookup cost a
network round trip to pandan worth shielding a stampede from. ``kaya_principal.py``'s lookup is a
local, indexed database read — there is nothing left to cache, no connection pool worth keeping
warm, and no stampede to coalesce. ``get_principal`` below reads the request's cookie and bearer
directly and asks the session it already holds.

**Team-default access (ADR 0011, R16) is unaffected and stays exactly as it was** —
``team_cache``/``team_upstream`` ← ``team_resolver`` ← this module. It still calls pandan over
HTTP for every request, so it still needs everything identity's stack used to: a process-wide
cache, a process-wide upstream client, its own single-flight registry, never shared with
identity's former one — that separation was never about identity, it was about two different
calls to two different pandan endpoints having no business coalescing with each other, and that
argument is unchanged by identity moving off pandan entirely.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.errors import error_body
from app.auth.kaya_principal import resolve_principal
from app.auth.principal import Principal
from app.auth.single_flight import SingleFlight
from app.auth.team_cache import TeamMembershipCache
from app.auth.team_resolver import TeamAccessResolver
from app.auth.team_upstream import PandanTeamUpstream, TeamMembershipUpstream
from app.config import get_settings
from app.db import get_session
from app.identity.backend import COOKIE_NAME
from app.pandan_timeout import split_timeout


@lru_cache(maxsize=1)
def get_team_access_cache() -> TeamMembershipCache:
    settings = get_settings()
    return TeamMembershipCache(
        positive_ttl=settings.team_access_cache_ttl_seconds,
        negative_ttl=settings.team_access_negative_cache_ttl_seconds,
    )


@lru_cache(maxsize=1)
def get_team_single_flight() -> SingleFlight:
    """A separate registry from any other stampede-coalescing in this app — see `team_resolver.py`'s
    module docstring for why."""
    return SingleFlight()


@lru_cache(maxsize=1)
def get_team_upstream() -> TeamMembershipUpstream:
    settings = get_settings()
    return PandanTeamUpstream(
        settings.pandan_url,
        timeout=split_timeout(
            connect=settings.team_access_connect_timeout_seconds,
            read=settings.team_access_read_timeout_seconds,
        ),
    )


def get_team_access_resolver() -> TeamAccessResolver:
    """No per-request session, unlike `get_principal` — `TeamAccessResolver` touches no database
    (see its module docstring); the `team` mirror row a note's `team_id` eventually points at is
    written elsewhere (R16.5), not by this read-only membership check."""
    return TeamAccessResolver(
        upstream=get_team_upstream(),
        cache=get_team_access_cache(),
        single_flight=get_team_single_flight(),
    )


def reset_auth() -> None:
    """Drop the cached singletons. For fixtures that repoint the environment, and for tests that
    must not inherit another test's cache — a cache outliving a test is the classic way an auth
    suite passes in isolation and fails in a full run."""
    get_team_access_cache.cache_clear()
    get_team_single_flight.cache_clear()
    get_team_upstream.cache_clear()


bearer_scheme = HTTPBearer(
    scheme_name="kaya PAT",
    description="A personal access token minted by kaya itself (ADR 0012, `kaya_pat_…`).",
    # auto_error=False so a missing header reaches `get_principal` and comes back in the documented
    # error shape rather than in Starlette's bare `{"detail": ...}`.
    #
    # This is the only place in kaya where anything about the `Authorization` header is parsed, it
    # is Starlette doing the parsing, and what it parses is the HTTP *scheme* — the literal
    # `Bearer ` in front. Nothing here, or downstream of here, looks at the credential itself
    # beyond hashing it whole (`app/auth/kaya_principal.py`).
    auto_error=False,
)


def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
) -> Principal:
    """The dependency every ``/api/v1`` route depends on.

    Cookie session first, then a ``kaya_pat_…`` bearer, matching pandan's own precedence
    (`app/auth/kaya_principal.py`'s module docstring). ``401 authentication_required`` when neither
    was even supplied; ``401 invalid_token`` when one was supplied and didn't resolve — the same two
    codes ADR 0002's resolver used, preserved on purpose so nothing downstream (kaya-client's exit
    codes, `test_error_extras_stay_addressable.py`) has to learn a new one for the same shape of
    refusal.
    """
    bearer = credentials.credentials if credentials is not None else None
    cookie_token = request.cookies.get(COOKIE_NAME)

    if bearer is None and cookie_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_body("authentication_required", "a bearer token is required"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = resolve_principal(
        session,
        cookie_token=cookie_token,
        bearer=bearer,
        secret=get_settings().kaya_auth_secret,
    )
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_body("invalid_token", "kaya did not accept this credential"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal
