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

**Team-default access (ADR 0011, R16) is a parallel, narrower stack**: ``team_cache``/
``team_upstream`` ← ``team_resolver`` ← ``dependencies``. It never imports and is never imported by
the identity stack above — a stampede on one bearer's team check has no business coalescing with,
or queuing behind, a stampede on that same bearer's identity check (`team_resolver.py`'s module
docstring). Where the identity stack turns a pandan outage into a hard `503` (ADR 0002's one
exception), `team_resolver.TeamAccessResolver` never raises at all — ADR 0011 made that dependency
soft.
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
from app.auth.dependencies import (
    get_principal,
    get_resolver,
    get_team_access_resolver,
    reset_auth,
)
from app.auth.mirror import SqlAlchemyPrincipalMirror
from app.auth.principal import (
    Principal,
    PrincipalMirror,
    TokenRejected,
    UpstreamUnavailable,
)
from app.auth.resolver import PrincipalResolver, error_body, principal_from_bearer
from app.auth.single_flight import SingleFlight
from app.auth.team_cache import TeamMembershipCache
from app.auth.team_resolver import TeamAccessResolver
from app.auth.team_upstream import PandanTeamUpstream, TeamMembershipUpstream
from app.auth.upstream import IdentityUpstream, PandanIdentityUpstream, split_timeout

__all__ = [
    "IdentityUpstream",
    "PandanIdentityUpstream",
    "PandanTeamUpstream",
    "Principal",
    "PrincipalCache",
    "PrincipalMirror",
    "PrincipalResolver",
    "SingleFlight",
    "SqlAlchemyPrincipalMirror",
    "TeamAccessResolver",
    "TeamMembershipCache",
    "TeamMembershipUpstream",
    "TokenRejected",
    "UpstreamUnavailable",
    "authorize_note",
    "digest",
    "error_body",
    "get_principal",
    "get_resolver",
    "get_team_access_resolver",
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
