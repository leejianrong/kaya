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

**Workspace access (ADR 0017) is decided here too, from kaya's own tables**: ``authorization.py``'s
``Access`` ladder and ``notes_visible_to`` read ``workspace_member`` directly. Nothing in this
package calls pandan any more, so the cache, upstream and single-flight shape that ADR 0011's team
lookup needed are gone with it.
"""

from app.auth.authorization import (
    ROLE_ACCESS,
    Access,
    authorize_note,
    in_container,
    note_access,
    note_addressed_as_id,
    note_addressed_as_ref,
    note_ids_in_container,
    notes_graph_edges,
    notes_linking_to,
    notes_matching,
    notes_named_by_id,
    notes_titled,
    notes_visible_to,
    notes_with_paths,
    visible_workspace_ids,
    workspace_role_of,
    writable_workspace_ids,
)
from app.auth.dependencies import (
    get_principal,
    reset_auth,
)
from app.auth.digest import digest
from app.auth.errors import error_body
from app.auth.kaya_principal import (
    principal_from_cookie,
    principal_from_pat,
    resolve_principal,
)
from app.auth.principal import Principal, UpstreamUnavailable
from app.auth.single_flight import SingleFlight

__all__ = [
    "ROLE_ACCESS",
    "Access",
    "Principal",
    "SingleFlight",
    "UpstreamUnavailable",
    "authorize_note",
    "digest",
    "error_body",
    "get_principal",
    "note_addressed_as_id",
    "note_addressed_as_ref",
    "note_ids_in_container",
    "note_access",
    "in_container",
    "visible_workspace_ids",
    "workspace_role_of",
    "writable_workspace_ids",
    "notes_graph_edges",
    "notes_linking_to",
    "notes_matching",
    "notes_named_by_id",
    "notes_visible_to",
    "notes_with_paths",
    "notes_titled",
    "principal_from_cookie",
    "principal_from_pat",
    "reset_auth",
    "resolve_principal",
]
