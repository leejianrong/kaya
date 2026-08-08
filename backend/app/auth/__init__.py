"""Authentication: pandan resolves callers, kaya remembers the answer (ADR 0002).

Kaya has **no token format, no token table, and no prefix logic**. It takes the bearer it was
given, asks pandan who that is, and caches the answer under a SHA-256 digest. The two things most
likely to be "improved" back into bugs are written down at the top of the modules that hold them:

- ``upstream.py`` — pandan answers `401` identically for a malformed token and a revoked one, so
  there is nothing kaya could usefully infer from a token's shape even if it wanted to.
- ``cache.py`` — the negative cache is what a ``startswith`` guard was reaching for, and it sheds
  the same load without knowing anything about the token.

Import layering, deliberately one-way: ``principal`` ← ``cache``/``upstream`` ← ``resolver`` ←
``dependencies``/``mirror``. Only the last pair knows FastAPI and SQLAlchemy exist, which is why
the entire resolver is exercisable by the no-infrastructure test layer.
"""

from app.auth.cache import PrincipalCache, digest
from app.auth.principal import (
    Principal,
    PrincipalMirror,
    TokenRejected,
    UpstreamUnavailable,
)
from app.auth.resolver import PrincipalResolver, error_body, principal_from_bearer
from app.auth.upstream import IdentityUpstream, PandanIdentityUpstream

__all__ = [
    "IdentityUpstream",
    "PandanIdentityUpstream",
    "Principal",
    "PrincipalCache",
    "PrincipalMirror",
    "PrincipalResolver",
    "TokenRejected",
    "UpstreamUnavailable",
    "digest",
    "error_body",
    "principal_from_bearer",
]
