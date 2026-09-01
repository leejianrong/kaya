"""Authentication: pandan resolves callers, kaya remembers the answer (ADR 0002).

Kaya has **no token format, no token table, and no prefix logic**. It takes the bearer it was
given, asks pandan who that is, and caches the answer under a SHA-256 digest. The two things most
likely to be "improved" back into bugs are written down at the top of the modules that hold them:

- ``upstream.py`` — pandan answers `401` identically for a malformed token and a revoked one, so
  there is nothing kaya could usefully infer from a token's shape even if it wanted to.
- ``cache.py`` — the negative cache is what a ``startswith`` guard was reaching for, and it sheds
  the same load without knowing anything about the token.
- ``single_flight.py`` — deduplicating concurrent misses is not tidiness, it is what makes the
  30 s read budget in ``upstream.py`` affordable without breaking ADR 0003 (KAN-666).

Import layering, deliberately one-way: ``principal`` ← ``cache``/``upstream``/``single_flight`` ←
``resolver`` ←
``authorization`` ← ``dependencies``, with ``mirror`` off to one side. ``resolver`` and
``authorization`` reach for ``fastapi.HTTPException`` and nothing else of the framework — no
``Depends``, no request, no session — so the entire HTTP contract, status codes and error bodies
included, is exercisable by the no-infrastructure test layer. ``dependencies`` is the only module
that knows FastAPI's dependency machinery exists, and ``mirror`` the only one holding a session.
"""

from app.auth.authorization import (
    authorize_note,
    note_addressed_as_id,
    note_addressed_as_ref,
    note_ids_owned_by,
    notes_graph_edges,
    notes_linking_to,
    notes_matching,
    notes_named_by_id,
    notes_owned_by,
    notes_titled,
)
from app.auth.cache import PrincipalCache, digest
from app.auth.dependencies import get_principal, get_resolver, reset_auth
from app.auth.mirror import SqlAlchemyPrincipalMirror
from app.auth.principal import (
    Principal,
    PrincipalMirror,
    TokenRejected,
    UpstreamUnavailable,
)
from app.auth.resolver import PrincipalResolver, error_body, principal_from_bearer
from app.auth.single_flight import SingleFlight
from app.auth.upstream import IdentityUpstream, PandanIdentityUpstream, split_timeout

__all__ = [
    "IdentityUpstream",
    "PandanIdentityUpstream",
    "Principal",
    "PrincipalCache",
    "PrincipalMirror",
    "PrincipalResolver",
    "SingleFlight",
    "SqlAlchemyPrincipalMirror",
    "TokenRejected",
    "UpstreamUnavailable",
    "authorize_note",
    "digest",
    "error_body",
    "get_principal",
    "get_resolver",
    "note_addressed_as_id",
    "note_addressed_as_ref",
    "note_ids_owned_by",
    "notes_graph_edges",
    "notes_linking_to",
    "notes_matching",
    "notes_named_by_id",
    "notes_owned_by",
    "notes_titled",
    "principal_from_bearer",
    "reset_auth",
    "split_timeout",
]
