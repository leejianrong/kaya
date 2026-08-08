"""FastAPI wiring, and nothing else.

Everything with a decision in it lives one module down (``resolver.py``, ``cache.py``,
``upstream.py``). What is left here is which object gets built where and how long it lives, which
is the part that cannot be unit-tested without a framework and does not need to be.

Lifetimes, and why each is what it is:

- **The cache is process-wide.** A per-request cache caches nothing. It is built lazily rather
  than at import for the same reason ``app/db.py`` builds its engine lazily: reading settings at
  import time binds to whatever the environment said before a fixture had a chance to change it.
- **The httpx client is process-wide**, so connections to pandan are pooled and a cache miss pays
  for a TLS handshake roughly never.
- **The mirror is per-request**, because it holds the request's session.

``/api/v1`` does not exist yet (KAN-536), so nothing depends on ``get_principal`` in the app
today. It is written now because the routes are written against it, not the other way round.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.cache import PrincipalCache
from app.auth.mirror import SqlAlchemyPrincipalMirror
from app.auth.principal import Principal
from app.auth.resolver import PrincipalResolver, principal_from_bearer
from app.auth.upstream import IdentityUpstream, PandanIdentityUpstream
from app.config import get_settings
from app.db import get_session


@lru_cache(maxsize=1)
def get_principal_cache() -> PrincipalCache:
    settings = get_settings()
    return PrincipalCache(
        positive_ttl=settings.principal_cache_ttl_seconds,
        negative_ttl=settings.principal_negative_cache_ttl_seconds,
    )


@lru_cache(maxsize=1)
def get_upstream() -> IdentityUpstream:
    settings = get_settings()
    return PandanIdentityUpstream(
        settings.pandan_url,
        timeout=settings.pandan_timeout_seconds,
    )


def reset_auth() -> None:
    """Drop the cached singletons. For fixtures that repoint the environment, and for tests that
    must not inherit another test's cache — the cache outliving a test is the classic way an auth
    suite passes in isolation and fails in a full run."""
    get_principal_cache.cache_clear()
    get_upstream.cache_clear()


def get_resolver(session: Annotated[Session, Depends(get_session)]) -> PrincipalResolver:
    return PrincipalResolver(
        upstream=get_upstream(),
        mirror=SqlAlchemyPrincipalMirror(session),
        cache=get_principal_cache(),
    )


bearer_scheme = HTTPBearer(
    scheme_name="pandan PAT",
    description="A personal access token minted by pandan. Kaya mints none of its own (ADR 0002).",
    # auto_error=False so a missing header reaches `principal_from_bearer` and comes back in the
    # documented error shape rather than in Starlette's bare `{"detail": ...}`.
    #
    # This is the only place in kaya where anything about the `Authorization` header is parsed, it
    # is Starlette doing the parsing, and what it parses is the HTTP *scheme* — the literal
    # `Bearer ` in front. Nothing here, or downstream of here, looks at the credential itself.
    auto_error=False,
)


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    resolver: Annotated[PrincipalResolver, Depends(get_resolver)],
) -> Principal:
    """The dependency every ``/api/v1`` route will depend on (KAN-536)."""
    return principal_from_bearer(
        credentials.credentials if credentials is not None else None,
        resolver,
    )
