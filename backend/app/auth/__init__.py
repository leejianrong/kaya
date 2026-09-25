"""Authentication: kaya resolves its own callers now (ADR 0012, KAN-1740).

Before this card, kaya had no identity of its own: it forwarded every bearer to pandan's
``GET /api/v1/me`` and cached the answer (ADR 0002). ADR 0012 ends that — ``get_principal`` below
resolves a caller from kaya's own ``kaya_account``/``kaya_session``/``personal_access_token`` tables
(``app/identity/``), a local database lookup with no upstream to be slow, unavailable, or worth
caching against. See ``app/auth/kaya_principal.py`` for the two ways in (cookie session, PAT
bearer) and ``app/auth/dependencies.py`` for the HTTP wiring around it.

**A note created before this cutover still holds an old pandan UUID in `owner_id`**, with no row
anywhere to back it — migration `0009` drops the ADR 0002 `user` mirror table entirely and
re-points the column's foreign key at `kaya_account.id`, `NOT VALID` so the migration itself does
not choke on the rows it makes historically un-owned. That note is not reachable under anyone's new
`KayaAccount` id — a deliberate, accepted cutover cost (``docs/roadmap/BREADBOARD.md``'s R19
section), not a bug this package works around.

Import layering, deliberately one-way: ``principal`` ← ``kaya_principal`` ← ``dependencies`` ←
``authorization``. ``kaya_principal`` and ``authorization`` reach for ``fastapi.HTTPException`` and
nothing else of the framework — no ``Depends``, no request, no session type beyond the plain
SQLAlchemy one — so the whole of resolution and authorization is exercisable by the
no-infrastructure test layer.

**Team-default access (ADR 0011, R16) is a parallel, narrower stack, entirely unaffected by this
card**: ``team_cache``/``team_upstream`` ← ``team_resolver`` ← ``dependencies``. It still calls
pandan for every request (``GET /api/v1/teams``) and still needs the cache/upstream/single-flight
shape identity's own stack used to — that need was never about identity, it was about this
particular call being slow and worth shielding a stampede from, and pandan's `/api/v1/teams`
endpoint is unchanged by anything in this card.
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
from app.auth.dependencies import (
    get_principal,
    get_team_access_resolver,
    reset_auth,
)
from app.auth.digest import digest
from app.auth.errors import error_body
from app.auth.kaya_principal import (
    principal_from_cookie,
    principal_from_pat,
    resolve_principal,
)
from app.auth.mirror import ensure_team_mirrored
from app.auth.principal import Principal, UpstreamUnavailable
from app.auth.single_flight import SingleFlight
from app.auth.team_cache import TeamMembershipCache
from app.auth.team_resolver import TeamAccessResolver
from app.auth.team_upstream import PandanTeamUpstream, TeamMembershipUpstream

__all__ = [
    "PandanTeamUpstream",
    "Principal",
    "SingleFlight",
    "TeamAccessResolver",
    "TeamMembershipCache",
    "TeamMembershipUpstream",
    "UpstreamUnavailable",
    "authorize_note",
    "digest",
    "ensure_team_mirrored",
    "error_body",
    "get_principal",
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
    "principal_from_cookie",
    "principal_from_pat",
    "reset_auth",
    "resolve_principal",
]
